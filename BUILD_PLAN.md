# LaunchPad-AI — Build Plan
### All Things Agentic Hackathon · Taskmaster track · Deadline: Aug 31, 2026, 5:00 PM PDT

> **One-sentence pitch:** *An autonomous career agent that manages your hireability — it watches what you build on GitHub, keeps a live model of your skills against the jobs you actually want, decides how each project changes your standing, prepares everything needed to publish it, and tells you what to build next to close the gap.*

This document is the single source of truth. If a task isn't in here, we don't build it this week.

---

## 0. Guardrails (read before every work session)

**The winning thesis.** We win on the 40% (Innovation & Operational Utility) by making the agent's *decisions* strategic and high-stakes, not by adding more actions. The plumbing is easy; the intelligence is the moat.

**What makes it agentic (must stay true):**
- It runs on its own from a real event (a GitHub push) — no human prompt starts it.
- It makes a genuine multi-way decision (LLM-driven routing), not a fixed pipeline.
- It uses tools to change real systems (GitHub PRs, image gen, post package).
- It has memory across runs (Firestore) that informs the next decision.
- It critiques its own output (self-review) and keeps a human in the loop by design.

**Anti-scope list — we will NOT build these (each adds brittleness, not points):**
- ❌ Auto-posting to LinkedIn (we prepare a one-tap package; the human presses Post).
- ❌ Additional output destinations (no multi-platform posting, no email, no Slack bots).
- ❌ Extra triggers beyond the push (the weekly scheduled review is *stretch only*).
- ❌ GKE, multi-region, A2A protocol, a second database, a login/multi-user system.
- ❌ Engagement/analytics loops or anything depending on a fragile third-party feed.

**The degradation trap to avoid:** if the Career Strategist ever becomes "always do all 3 actions," the project collapses into a script and loses the 40%. The decision must be real.

---

## 1. Hackathon compliance checklist (all must be TRUE at submission)

| Requirement | How we satisfy it |
|---|---|
| Gemini 3.5 Flash **or newer** | Reasoning brain throughout (confirm exact model ID in console; use 3.5-flash or current 3.6-flash) |
| ≥1 Google agent framework | **Google ADK (Python)** — orchestrator + sub-agents/tools |
| ≥1 Google Cloud service | **Cloud Run + Pub/Sub + Firestore + Secret Manager** (we use four) |
| Taskmaster-track fit | Event → autonomous decision → action across apps → visible result, end to end |
| Public/private code repo | GitHub repo + `README.md` with spin-up steps |
| Architecture diagram | Included in repo + shown in the video |
| ~4-min demo video, live & unedited | Recorded screen capture, one clean take, with GCP-console proof |
| Text write-up | Features, tech, data sources, learnings |
| **Bonus (do these):** | Build-in-public blog post + `#AllThingsAgenticHackathon` social post + Imagen integration |

---

## 2. Architecture (final — cleanest, no over-engineering)

```
                         GitHub push (default branch)
                                   │  HMAC-signed webhook
                                   ▼
        ┌───────────────────────────────────────────────────────┐
        │  Cloud Run service: LaunchPad-AI-agent (ADK app)         │
        │                                                        │
        │   POST /webhook   → verify HMAC (Secret Manager),      │
        │                     publish event to Pub/Sub, 200 OK   │
        │                                                        │
        │   POST /process   ← Pub/Sub push (async worker)        │
        │        └── ADK Root Orchestrator (LLM-driven routing)  │
        │              ├─ Repo Analyst                           │
        │              ├─ Career Strategist  (the decision)      │
        │              ├─ Roadmap Planner    (what to build next)│
        │              ├─ README Author      → GitHub PR         │
        │              ├─ Portfolio Publisher→ GitHub PR + image │
        │              ├─ Announcer          → post package      │
        │              ├─ Self-Reviewer      (critique/revise)   │
        │              └─ Verifier           → build check + log │
        │                                                        │
        │   GET  /            → dashboard (decision log + card)  │
        └───────────────────────────────────────────────────────┘
                │                     │                    │
                ▼                     ▼                    ▼
          Pub/Sub topic         Firestore            Secret Manager
          + Dead-letter    (memory · decisions ·     (GitHub App key ·
          (retries)         skill-map · voice ·       webhook secret ·
                            idempotency keys)         API keys)
                │
                ▼
          Vertex AI — Gemini 3.5/3.6 Flash   +   Imagen (preview images)   +   Cloud Trace (OpenTelemetry from ADK)
```

**Why one Cloud Run service, two endpoints:** `/webhook` must return 200 within GitHub's ~10s timeout, but the agent run is slow (LLM + tools). So `/webhook` just verifies + publishes to Pub/Sub and returns; Pub/Sub push delivers to `/process`, which runs the agent with **retries + dead-letter** for free. One deployable, fully decoupled — minimum moving parts, maximum architecture score.

---

## 3. Runtime workflow (what happens on one push)

1. Developer pushes to `main`. GitHub fires the webhook to `/webhook`.
2. `/webhook` verifies the HMAC signature, publishes `{delivery_id, repo, commits}` to Pub/Sub, returns 200.
3. Pub/Sub pushes the event to `/process`. **Idempotency check:** if `delivery_id` already in Firestore, ack and stop (no double-processing).
4. **Repo Analyst** pulls repo metadata, README, languages, file tree, and any screenshots (Gemini vision) → a structured project profile.
5. **Career Strategist** loads memory (published projects, skill-map, gaps, target roles) and makes the **multi-way decision**: `flagship_publish` / `update_existing` / `not_ready(gap)` / `skip` — with written reasoning.
6. Routing on the decision:
   - `skip` → log reason, done.
   - `not_ready` → log the specific gap, notify via dashboard, done.
   - `flagship_publish` / `update_existing` → run the action agents.
7. **Action agents** (in parallel where possible): README Author opens/updates a PR; Portfolio Publisher opens a PR with an on-theme project card + an Imagen preview image; Announcer assembles the LinkedIn **post package** (voice-matched text + attached images + hashtags).
8. **Roadmap Planner** compares the updated skill-map against real job postings for the target roles and recommends the highest-leverage next project/skill; optionally opens a GitHub issue to scaffold it.
9. **Self-Reviewer** critiques each artifact against a rubric (no unverifiable claims, hashtags relevant, image matches, README correct). One revision pass if needed.
10. **Verifier** confirms the portfolio site still builds; writes the full decision + artifacts to the Firestore decision log.
11. **Dashboard** shows the run: the decision + reasoning, links to the PRs, and the post-review card (copy-all + prefilled share link). Human approves the PRs and presses Post.

---

## 4. Tech stack (exact)

- **Language:** Python 3.12+ (use `uv` for envs).
- **Agent framework:** Google ADK (`google-adk`), Python. Tools wired as **MCP tools** where clean (plays to the MCP cert; ADK supports MCP natively).
- **Model:** Gemini 3.5 Flash / current 3.6 Flash via **Vertex AI** (`GOOGLE_GENAI_USE_VERTEXAI=1`).
- **Images:** Imagen on Vertex AI (portfolio card + post image). *(Stretch: Veo teaser.)*
- **Compute:** Cloud Run (the ADK service, deployed with `adk deploy cloud_run`).
- **Eventing:** Pub/Sub (topic + push subscription + dead-letter topic).
- **State/memory:** Firestore (native mode).
- **Secrets:** Secret Manager.
- **Observability:** ADK's built-in OpenTelemetry → Cloud Trace / Cloud Logging.
- **Integrations:** a GitHub App (webhook + PR permissions); a job-postings source for market grounding (search/fetch tool, with a seeded-JD fallback).
- **Web framework:** FastAPI (ADK serves on it; add `/webhook`, `/process`, `/` routes).

---

## 5. Memory model (Firestore collections)

- `projects/{repo}` → `{ name, summary, stack, skill_tags[], status, portfolio_url, published_at }`
- `skill_map/current` → `{ skills: { skillName: coverage_score }, gaps: [ {skill, why, priority} ] }`
- `targets/roles` → `{ target_roles: [...], target_jds: [ {source, text, required_skills[]} ] }`
- `roadmap/current` → `{ next_recommendation, rationale, issue_url }`
- `decisions/{delivery_id}` → `{ repo, decision, reasoning, artifacts:{readme_pr, portfolio_pr, post_package}, self_review, verified, ts }`
- `voice/profile` → `{ tone_notes, sample_snippets }`
- `idempotency/{delivery_id}` → `{ processed_at }`

**Seed this on Day 2 with Aditi's real projects and 2–3 real target JDs** — the plan lives or dies on the memory being grounded in real data.

---

## 6. The agents & tools (ADK)

| Agent / tool | Input | Job | Output |
|---|---|---|---|
| **Root Orchestrator** | event | LLM-driven routing; owns session state | invokes sub-agents |
| **Repo Analyst** | repo ref | fetch + understand the project (incl. vision) | project profile |
| **Career Strategist** | profile + memory | the multi-way decision + framing | decision + reasoning |
| **Roadmap Planner** | skill-map + live JDs | recommend next build; open scaffold issue | roadmap + issue |
| **README Author** | profile + decision | write/upgrade README, open PR | README PR |
| **Portfolio Publisher** | profile + decision | on-theme card + Imagen image, open PR | portfolio PR |
| **Announcer** | profile + voice | assemble post package (text+img+tags) | post package |
| **Self-Reviewer** | all artifacts | critique vs rubric, request 1 revision | pass/fixed artifacts |
| **Verifier** | portfolio PR | confirm site builds; write decision log | verified log entry |

---

## 7. Repo structure (agree this Day 1 so parallel work doesn't collide)

```
LaunchPad-AI/
├─ agent/
│  ├─ __init__.py
│  ├─ agent.py            # root_agent (orchestrator) — ENTRY POINT
│  ├─ subagents/          # strategist, roadmap, readme, publisher, announcer, reviewer, verifier
│  ├─ tools/              # github_tool, image_tool, jobs_tool (MCP where clean)
│  └─ memory.py           # Firestore accessors (the shared contract)
├─ ingest/                # /webhook + /process routes (FastAPI)
├─ dashboard/             # decision log + post-review card
├─ infra/                 # gcloud setup scripts, pubsub, firestore rules, secrets
├─ eval/                  # lightweight ADK eval on the Strategist's decisions
├─ ARCHITECTURE.md        # the diagram + component notes
├─ README.md              # spin-up instructions (judge-followable)
└─ .env.example
```

**The interface contract (freeze Day 1):** the Firestore schema in §5 and the tool signatures in §6. As long as both devs code to these, the two streams merge cleanly.

---

## 8. Build sequence — day by day

Owner tags: **[CC]** = Aditi in Claude Code · **[AG]** = teammate in Antigravity · **[both]** = pair.

### Day 1 — Tue Aug 25 · "the pipe breathes"
- **[both]** Freeze the interface contract (§5 schema + §6 tool signatures). Create the repo with the §7 structure.
- **[AG]** Create GCP project, claim the $150 credits + GEAR badge. Enable APIs: `run, aiplatform, pubsub, firestore, secretmanager, cloudbuild`. Provision Firestore (native), the Pub/Sub topic + dead-letter, and Secret Manager. Register the GitHub App (push webhook, contents + pull_requests write); store its key + webhook secret in Secret Manager.
- **[CC]** Scaffold the ADK app: a `root_agent` in `agent/agent.py` + a trivial tool; get it running locally with `adk web`. Add the `/webhook` (verify HMAC → publish → 200) and `/process` (ack + log) routes.
- **[AG]** Deploy to Cloud Run with `adk deploy cloud_run --with_ui`; wire the Pub/Sub push subscription (OIDC-authenticated) to `/process`.
- **✅ Done when:** a real push produces a logged event at `/process` through Pub/Sub.

### Day 2 — Wed Aug 26 · "memory + understanding"
- **[CC]** Build the **Repo Analyst** (GitHub API + Gemini vision) → project profile. Implement `memory.py` accessors.
- **[both]** Seed Firestore with Aditi's real projects and 2–3 real target JDs.
- **✅ Done when:** a push yields a structured project profile + a successful memory read/write.

### Day 3 — Thu Aug 27 · "the decision (the heart)"
- **[CC]** Build the **Career Strategist**: the multi-way LLM decision using memory, with written reasoning; wire the Orchestrator's routing on the decision.
- **[AG]** Idempotency (dedupe on `delivery_id`), dead-letter handling, structured logging.
- **✅ Done when:** a push produces a logged multi-way decision + rationale, and a duplicate delivery is safely ignored.

### Day 4 — Fri Aug 28 · "first visible actions"
- **[CC]** **README Author** (opens real PR) + **Portfolio Publisher** (on-theme card PR + **Imagen** image).
- **[AG]** GitHub App auth for PRs end-to-end; a demo portfolio-site repo the Publisher targets.
- **✅ Done when:** one push → two real PRs appear on GitHub.

### Day 5 — Sat Aug 29 · "complete the loop + the keystone"
- **[CC]** **Announcer** (post package) + **Self-Reviewer** loop + **Verifier**.
- **[CC]** **Roadmap Planner** + **live job-market grounding** (with seeded fallback) — the keystone upgrade.
- **[AG]** **Dashboard** (decision log + post-review card with copy-all + prefilled share link). Approval digest.
- **✅ Done when:** full loop runs self-reviewed and idempotent; a push produces PRs + a ready post package + a "next build" recommendation; partial failures degrade gracefully.

### Day 6 — Sun Aug 30 · "polish + record"
- **[AG]** `ARCHITECTURE.md` diagram, confirm OpenTelemetry traces show in Cloud Trace, README spin-up steps.
- **[CC]** Lightweight **ADK eval** on the Strategist's decisions.
- **[both]** 2–3 full dry runs on a staged repo, then record the **~4-min unedited demo** with GCP-console proof.
- **✅ Done when:** the video is recorded and the repo is judge-followable.

### Day 7 — Mon Aug 31 · "write-up + submit"
- **[both]** Devpost write-up (features, tech, data sources, learnings). Bonus: blog post + `#AllThingsAgenticHackathon` social post.
- **Submit with buffer** well before 5:00 PM PDT (≈5:30 AM IST Sep 1 — do not cut it fine).
- **✅ Done when:** submitted early, all artifacts attached.

---

## 9. Work split & tooling

**Aditi — Claude Code [CC]:** the agent brain. ADK orchestrator, all sub-agents, the Strategist/Roadmap reasoning, prompts, self-review, memory accessors, the eval, README/docs. Drive Claude Code by pointing it at `BUILD_PLAN.md` + the frozen contract; have it write tests against the tool signatures so the merge with [AG]'s infra is clean.

**Teammate — Antigravity [AG]:** the Google-native infra. GCP setup, GitHub App, `/webhook` + Pub/Sub wiring, deployment (`adk deploy cloud_run`), Firestore rules, Secret Manager, the dashboard, observability. Antigravity's tight Gemini/Cloud integration makes it the right tool for the GCP plumbing and deploy loop.

**They meet at:** the Firestore schema (§5) and the tool signatures (§6). Freeze both on Day 1; neither dev changes them without telling the other.

---

## 10. Demo plan (4 min, recorded, unedited)

- **0:00–0:30** The problem, personal and honest: "I build constantly; my portfolio and my sense of what to build next are always behind."
- **0:30–1:00** Show the career memory on screen: projects, target roles, gaps. Flash the architecture diagram.
- **1:00–3:00** Live push of a real project → Cloud Run logs + the ADK reasoning trace → the multi-way decision ("fills your LLMOps gap → flagship") → README PR + portfolio PR (with generated image) + the post package appear → Self-Reviewer catches and fixes one thing → the roadmap recommends the next build.
- **3:00–3:20** Push something trivial → it **skips**. (Proves the decision is real.)
- **3:20–3:45** GCP console proof: Cloud Run service, Firestore documents, Cloud Trace.
- **3:45–4:00** Close: "It doesn't just publish my work — it manages my hireability and tells me what to build next."

---

## 11. Submission checklist

- [ ] Code repo (public or private) + `README.md` with spin-up steps
- [ ] `ARCHITECTURE.md` diagram
- [ ] ~4-min unedited demo video with GCP-console proof
- [ ] Devpost text write-up (features, tech, data sources, learnings)
- [ ] Category selected: **Taskmaster**
- [ ] Gemini 3.5+ ✓ · ADK ✓ · Cloud Run + Pub/Sub + Firestore + Secret Manager ✓ (all visible in the video)
- [ ] Bonus: blog post + `#AllThingsAgenticHackathon` post + Imagen integration noted
- [ ] Submitted before Aug 31, 5:00 PM PDT (with buffer)

---

## 12. Risk register

| Risk | Mitigation |
|---|---|
| "Assembled from parts" perception | Lead every description with "manages hireability / what to build next," never "writes READMEs." The Strategist + Roadmap are the story. |
| Demo breaks on camera | It's recorded/unedited — re-record until clean. Reliable webhook trigger, pre-staged repo, keep a backup take. |
| Decision degrades into a script | Keep the Strategist a genuine LLM decision; demo a `skip` to prove it. |
| Scope creep | The anti-scope list in §0 is binding. Tier 2 items only if Tier 1 is done. |
| Job-market feed unreliable | Seeded-JD fallback so grounding can never block the run/demo. |
| GitHub 10s webhook timeout | `/webhook` only verifies + publishes; the slow work is async in `/process`. |

---

## 13. Do these today (Day 1, both)

1. **[both]** Freeze the interface contract (§5 + §6) and create the repo (§7).
2. **[AG]** GCP project + credits + GEAR + enable APIs + Firestore + Pub/Sub + Secret Manager + GitHub App.
3. **[CC]** ADK `root_agent` running locally + `/webhook` and `/process` routes.
4. **[AG]** Deploy to Cloud Run + wire Pub/Sub push.
5. **[both]** Confirm: a real push produces a logged event end-to-end. Ship Day 1's milestone before you sleep.

---

*Stick to this document. Depth over width. The decision is the product.*
