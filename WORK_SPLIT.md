# LaunchPad-AI — Work Split & Prompts
### Aditi = Claude Code `[CC]` (agent brain) · Ameya (me) = Antigravity `[AG]` (infra + frontend)

Read this alongside `BUILD_PLAN.md`. This file tells each of you exactly what to build, in what order, and gives copy-paste prompts for your coding tool.

> **The one rule that prevents 90% of errors:** freeze §1 (the contract) on Day 1. Neither of you changes a Firestore field name or a function signature without telling the other. Both code *to the contract*, not to each other's code.

---

## 1. THE FROZEN CONTRACT (both agree Day 1, then don't touch)

### Repo ownership (who edits what — never cross these lines)
- `[CC]` owns: `agent/` and `eval/`
- `[AG]` owns: `infra/`, `dashboard/`, `server.py`, `Dockerfile`
- Shared read-only reference: `BUILD_PLAN.md`, `WORK_SPLIT.md`, `architecture.svg`

### The seam (the ONE function that connects the two halves)
`[CC]` exposes this in `agent/runner.py`; `[AG]` calls it from the `/process` route:
```python
def run_agent(event: dict) -> dict:
    """event = the Pub/Sub message (see schema below).
       Returns the decision record that also gets written to Firestore."""
```

### Pub/Sub message schema (`[AG]` produces it, `[CC]` consumes it)
```json
{ "delivery_id": "str", "repo": "owner/name", "default_branch": "main",
  "commits": [ { "message": "str" } ], "pusher": "str" }
```

### Firestore collections (exact names/fields)
- `projects/{repo}` → `{ name, summary, stack, skill_tags[], status, portfolio_url, published_at }`
- `skill_map/current` → `{ skills: {name: score}, gaps: [{skill, why, priority}] }`
- `targets/roles` → `{ target_roles: [], target_jds: [{source, text, required_skills[]}] }`
- `roadmap/current` → `{ next_recommendation, rationale, issue_url }`
- `decisions/{delivery_id}` → `{ repo, action, reasoning, highlights[], gap, artifacts:{readme_pr, portfolio_pr, post_package}, self_review, verified, ts }`
- `voice/profile` → `{ tone_notes, sample_snippets[] }`
- `idempotency/{delivery_id}` → `{ processed_at }`

### Tool signatures (`[CC]` implements under `agent/tools/`)
```python
github_get_repo(repo: str) -> dict            # profile: name, readme, langs, tree, images[]
github_open_pr(repo, branch, title, body, files: dict) -> str   # returns PR url
github_open_issue(repo, title, body) -> str   # returns issue url
generate_image(prompt: str) -> str            # returns image url/path (Imagen)
fetch_jobs(roles: list[str]) -> list[dict]    # live JDs; MUST fall back to seeded JDs
verify_build(portfolio_repo: str) -> dict     # {ok: bool, detail: str}
```

### Decision object (`[CC]` — the core output)
```json
{ "action": "flagship | update | not_ready | skip", "reasoning": "str",
  "highlights": ["str"], "gap": "str | null" }
```

### Post package object (`[CC]` — Announcer output)
```json
{ "text": "str", "hashtags": ["str"], "image_url": "str" }
```

### Environment variables (both use the same names)
```
GOOGLE_GENAI_USE_VERTEXAI=1
GOOGLE_CLOUD_PROJECT=<project-id>
GOOGLE_CLOUD_LOCATION=<region>
GEMINI_MODEL=<gemini-3.5-flash or current 3.6-flash — confirm exact id in Vertex console>
# secrets come from Secret Manager at runtime, NOT env files in the repo
```

---

## 2. GOLDEN RULES (both, every session)

1. **Verify ADK APIs against the live docs** (`google.github.io/adk-docs`) before writing agent code — do not trust memorized signatures; ADK moves fast. Put this instruction in every prompt.
2. **The Career Strategist must be a real LLM decision.** If it ever becomes "always do all actions," the project stops being agentic. Test it by feeding a trivial repo and confirming `skip`.
3. **No secrets in the repo.** GitHub token, webhook secret, API keys → Secret Manager only. Commit a `.env.example`, never `.env`.
4. **Idempotency is mandatory** — dedupe on `delivery_id` before doing any work.
5. **Small commits, push often, one shared `main`.** Sync at the end of every day against the §1 contract.

---

## 3. ADITI — Claude Code `[CC]`

### Step 0 — set up persistent context (run once)
Paste into Claude Code:
```
We're building "LaunchPad-AI" for the All Things Agentic hackathon (Taskmaster track).
Read BUILD_PLAN.md, WORK_SPLIT.md, and architecture.svg in this repo.

Create a CLAUDE.md that captures, tersely:
- The one-sentence pitch (autonomous career agent that manages hireability).
- The AGENTIC RULE: the Career Strategist must be a genuine LLM decision returning
  flagship/update/not_ready/skip — never a fixed pipeline.
- The frozen contract: paste WORK_SPLIT.md §1 (schema, tool signatures, run_agent seam).
- Stack: ADK Python + Gemini 3.5 Flash on Vertex AI; Firestore for memory.
- MY LANE: I only edit agent/ and eval/. I never touch infra/, dashboard/, server.py.
- Rule: before writing ADK code, check the current ADK docs for exact APIs.

Then stop and show me CLAUDE.md. Do not write any other code yet.
```

### Prompt 1 — scaffold the agent + memory (Day 1→2)
```
Using the CURRENT ADK Python docs (google.github.io/adk-docs — verify exact imports/APIs,
do not guess), scaffold agent/:
- agent/agent.py with a root LlmAgent named root_agent using GEMINI_MODEL via Vertex AI.
- agent/runner.py exposing run_agent(event: dict) -> dict (the seam from §1).
- agent/memory.py implementing the Firestore accessors for every collection in §1,
  with exact field names. Support the Firestore emulator via env for local tests.
- One trivial "ping" sub-agent so `adk web` runs locally.
Write pytest unit tests for memory.py against the emulator.
Do NOT edit anything outside agent/. Done when `adk web` runs and memory tests pass.
```

### Prompt 2 — Repo Analyst + GitHub tool (Day 2)
```
Implement agent/tools/github_tool.py (github_get_repo, github_open_pr, github_open_issue
per §1 signatures) reading the GitHub token from the runtime secret, not from code.
Implement agent/subagents/repo_analyst.py as an ADK agent that, given a repo ref, returns
a project profile dict (name, summary, stack, skill_tags, readme, images) — run any repo
images through Gemini vision. Add tests with a recorded sample-repo fixture (no live calls
in tests). Stay inside agent/.
```

### Prompt 3 — Career Strategist (Day 3, THE HEART)
```
Implement agent/subagents/career_strategist.py as an LLM-driven ADK agent.
Input: the project profile + memory (targets, skill_map, existing projects).
Output: the decision object from §1 {action, reasoning, highlights, gap}.
Write the system prompt so the decision is GENUINE: include few-shot examples where it
returns "skip" (trivial push) and "not_ready" (real project but a gap). Then wire
root_agent to route on `action`: skip/not_ready → log and stop; flagship/update → continue.
Create eval/strategist_eval with 8-10 labeled cases (mix of all four actions).
Done when a real push logs a decision+reasoning AND a trivial repo returns "skip".
```

### Prompt 4 — README Author + Portfolio Publisher (Day 4)
```
Implement agent/subagents/readme_author.py: generate/upgrade a README and open a PR via
github_open_pr. Implement agent/subagents/portfolio_publisher.py: build an on-theme project
card that MATCHES the target portfolio site's existing style, generate a preview image via
generate_image (Imagen), and open a PR on the portfolio repo. Wire both into the flagship/
update path. Actions must be independent so one failing doesn't abort the other. Tests with
mocked GitHub/image calls.
```

### Prompt 5 — Announcer + Self-Reviewer + Verifier + Roadmap + jobs (Day 5)
```
Implement:
- agent/subagents/announcer.py → the post package object from §1 (voice-matched text using
  voice/profile, hashtags, image_url). No auto-posting — output only.
- agent/tools/jobs_tool.py fetch_jobs(roles) with a SEEDED fallback so it never blocks.
- agent/subagents/roadmap_planner.py → compare skill_map vs live JDs, recommend the next
  build, optionally open a scaffold issue via github_open_issue; write roadmap/current.
- agent/subagents/self_reviewer.py → critique each artifact vs a rubric (no unverifiable
  claims, hashtags relevant, image matches, README correct); allow ONE revision pass.
- agent/tools/verify_tool.py verify_build(portfolio_repo).
Write the full decision record (with artifacts + self_review + verified) to Firestore.
```

### Prompt 6 — eval + docs (Day 6)
```
Finalize eval/ as a lightweight ADK eval over the Strategist's decisions and report
pass rate. Write the agent-side of README.md: how the multi-agent flow works, how to run
locally with `adk web`, and the eval command. Add 1-line justifications for why each agent
exists (for the submission write-up).
```

---

## 4. TEAMMATE — Antigravity `[AG]`

> Paste each as a task to Antigravity, or run the commands directly. You own infra + the dashboard. **Never edit `agent/`.**

### Step 0 — context
```
Read BUILD_PLAN.md and WORK_SPLIT.md. We're deploying "LaunchPad-AI", an ADK Python agent,
to Google Cloud. MY LANE: infra/, dashboard/, server.py, Dockerfile only — never agent/.
I build to the frozen contract in WORK_SPLIT.md §1. The agent exposes run_agent(event)
in agent/runner.py — I call it from the /process route; I do not change its signature.
```

### Prompt 1 — GCP bootstrap (Day 1)
```
Set up the Google Cloud project for LaunchPad-AI. Enable APIs, then create Firestore, the
Pub/Sub topics, and Secret Manager entries. Use these commands (fill in PROJECT and REGION):

gcloud config set project <PROJECT>
gcloud services enable run.googleapis.com aiplatform.googleapis.com pubsub.googleapis.com \
  firestore.googleapis.com secretmanager.googleapis.com cloudbuild.googleapis.com \
  artifactregistry.googleapis.com cloudtrace.googleapis.com
gcloud firestore databases create --location=<REGION>
gcloud pubsub topics create LaunchPad-AI-events
gcloud pubsub topics create LaunchPad-AI-dead-letter

Then create Secret Manager secrets (empty for now): github-app-key, github-webhook-secret.
Confirm everything succeeded and print the enabled services.
```

### Prompt 2 — GitHub App + /webhook ingest (Day 1→2)
```
Create infra/ and a FastAPI ingest router with POST /webhook that:
1) reads the raw body + X-Hub-Signature-256 header,
2) verifies the HMAC using github-webhook-secret from Secret Manager,
3) on a push event, builds the §1 Pub/Sub message and publishes to LaunchPad-AI-events,
4) returns 200 immediately (must be fast — GitHub times out ~10s).
Register a GitHub App with permissions contents:write, pull_requests:write, metadata:read,
subscribed to push events, webhook URL = <cloud-run-url>/webhook. Store its private key in
the github-app-key secret. Verify a test push lands a message on LaunchPad-AI-events.
```

### Prompt 3 — assemble server.py + deploy to Cloud Run (Day 2)
```
Create server.py: a FastAPI app that (a) embeds the ADK agent using ADK's FastAPI helper
(check current ADK docs for the exact function), and (b) mounts my ingest router (/webhook),
a /process route, and the dashboard (/). The /process route parses the Pub/Sub push message
and calls agent.runner.run_agent(event) — do not change that signature.
Write a Dockerfile. Deploy to Cloud Run (adk deploy cloud_run or gcloud run deploy), grant
the runtime service account roles for Firestore, Vertex AI, Secret Manager, and Pub/Sub.
Then create a Pub/Sub push subscription on LaunchPad-AI-events → <cloud-run-url>/process with
OIDC auth and a dead-letter policy to LaunchPad-AI-dead-letter. Confirm a push flows end-to-end.
```

### Prompt 4 — the dashboard frontend (Day 5)
```
Build dashboard/ served at GET / on the Cloud Run service. LIGHT MODE, clean and minimal.
It reads from Firestore and shows:
- The decision log: each run's repo, action (flagship/update/not_ready/skip), and reasoning.
- The post-review card: the latest post package (text + image + hashtags) with a "Copy all"
  button and a prefilled LinkedIn share link so the user can post in one tap.
- Links to the opened README PR, portfolio PR, and roadmap issue.
No auth, no build step needed beyond static + a small JSON endpoint. Make it look polished
for a demo video.
```

### Prompt 5 — observability + hardening (Day 6)
```
Confirm ADK's OpenTelemetry traces appear in Cloud Trace and add a link from the dashboard.
Verify the dead-letter topic catches poison messages and that duplicate deliveries are
ignored (idempotency). Write the infra section of README.md: one-command spin-up steps a
judge can follow. Confirm the GCP console clearly shows Cloud Run + Firestore + Pub/Sub for
the demo proof shot.
```

---

## 5. WHERE YOU MEET EACH DAY (handoff points)

| Day | `[CC]` delivers | `[AG]` delivers | Integration check |
|---|---|---|---|
| 1 | root_agent + run_agent stub | GCP + /webhook → Pub/Sub | a push logs an event via Pub/Sub |
| 2 | Repo Analyst + memory | server.py + deploy + /process wired | /process calls run_agent on Cloud Run |
| 3 | Career Strategist decision | idempotency + DLQ live | push → logged decision; dup ignored |
| 4 | README + Portfolio agents (PRs) | portfolio demo repo + PR auth | push → 2 real PRs |
| 5 | Announcer + Reviewer + Roadmap | dashboard live | push → PRs + post card + roadmap on dashboard |
| 6 | eval + agent docs | traces + hardening + infra docs | full dry run recorded |

---

## 6. DAILY SYNC (5 min, end of day)
1. Did today's integration check pass? (see §5)
2. Did anyone need to change the §1 contract? If yes — agree it together, update this file, both re-pull.
3. Anything blocking tomorrow? Assign it now.

---

## 7. IF YOU'RE BEHIND (cut in this order — protect the core)
Drop Roadmap live-JD grounding → seeded JDs only. Then drop Self-Reviewer's revision loop
(keep the critique log). Then drop the Imagen image (keep the card). **Never** drop the
Career Strategist decision or the human-in-the-loop — those are the project.
```
