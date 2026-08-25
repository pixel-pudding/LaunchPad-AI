# LaunchPad-AI — Product Requirements Document (PRD)

| | |
|---|---|
| **Product** | LaunchPad-AI — an autonomous career agent |
| **One-liner** | It watches what you ship on GitHub, keeps a live model of your skills vs. the jobs you want, decides how each release changes your standing, prepares everything to publish it, and tells you what to build next. |
| **Event** | All Things Agentic Hackathon · Taskmaster track |
| **Deadline** | Aug 31, 2026, 5:00 PM PDT |
| **Team** | Aditi (agent/Claude Code) · Ameya (infra/Antigravity) |
| **Status** | Locked for build |

---

## 1. Problem statement

Developers ship constantly, but turning finished work into something **visible and legible to the people who hire** — a clear README, a portfolio entry, an announcement on linkedin framed for recruiters — is a tedious, multi-step, cross-app chore that gets deferred or skipped. Worse, developers rarely have a clear model of **what to build next** to become more hireable for the roles they actually want. The result: strong work stays buried, portfolios run months behind reality, and effort isn't aimed where it moves the needle. For students and job-seekers whose portfolio *is* their resume, this quietly costs opportunities.

## 2. Goals & non-goals

**Goals**
- G1 — When a project is genuinely shipped, publish it everywhere it should go, autonomously, with a single human approval.
- G2 — Maintain a persistent, strategic model of the developer's skills vs. target roles, and recommend the highest-leverage next build.
- G3 — Make a *real* readiness/positioning decision per release — not a fixed pipeline.
- G4 — Win the hackathon: score across the 40/30/30 rubric and qualify for multiple prize buckets.

**Non-goals**
- N1 — Not a general social-media scheduler or multi-platform poster.
- N2 — Not a CI/CD or code-quality tool.
- N3 — Not a multi-user SaaS product (single developer, this build).
- N4 — Does not auto-publish to LinkedIn (prepares a one-tap package; human posts).

## 3. Target user

A developer actively building a portfolio and job-hunting (primary persona: a CS student / early-career engineer). They ship projects to GitHub, want their work seen, and want direction on what to build next for their target roles.

## 4. Success metrics — "what perfect looks like" (Definition of Done)

- SM1 — **End-to-end autonomy:** publishing a GitHub release produces (a) a README PR, (b) a portfolio-card PR with a generated image, (c) a ready one-tap LinkedIn post package, and (d) a next-build recommendation — unattended, in a single run, visible on the dashboard.
- SM2 — **Real decision:** on a labeled eval set (≥10 cases spanning all four actions), the Strategist picks the correct action in a clear majority; a deliberately trivial release yields `skip`; a v1.1 of a published project yields `update`, not a new post.
- SM3 — **Reliability:** duplicate webhook deliveries never double-publish (idempotent on `repo + release tag`); a failed sub-action degrades gracefully (others still complete).
- SM4 — **Proof on Google Cloud:** the run is visibly traceable (Cloud Run + Firestore + Pub/Sub + Cloud Trace) in the demo.
- SM5 — **Submission complete:** repo + README spin-up, architecture diagram, ~4-min unedited demo, write-up, bonus blog + social post — all present before the deadline with buffer.

## 5. Scope

**In scope**
- Trigger on a **GitHub Release** (deliberate "done" signal); fallback: a `[publish]` commit marker or `ready-to-publish` label.
- Persistent career memory (projects, skill-map, gaps, target JDs).
- One multi-way autonomous decision per release.
- Four outputs: README PR, portfolio-card PR (+ image), LinkedIn post package, roadmap recommendation.
- Self-review, build verification, human-in-the-loop approval, decision log.
- One lightweight light-mode dashboard (decision log + post-review card).

**Out of scope (explicitly)**
- Auto-posting to any network; additional posting destinations.
- Additional triggers beyond release + the fallback marker.
- GitLab/Bitbucket; multi-user auth; engagement/analytics loops; GKE; agent-to-agent negotiation.

## 6. Functional requirements

> Each has an acceptance criterion (AC). "Agent decides" always means a genuine LLM judgment, never a hardcoded branch.

- **FR-1 · Release trigger.** Subscribe to the GitHub `release` (published) event; support the `[publish]`/label fallback. *AC:* publishing a release invokes the agent exactly once; routine commits do not.
- **FR-2 · Ingest & decouple.** Verify the webhook HMAC, publish the event to Pub/Sub, return 200 fast. *AC:* `/webhook` responds < 2s; slow work runs async.
- **FR-3 · Idempotency.** Key on `repo + release tag`. *AC:* a re-delivered event produces no new PRs/posts.
- **FR-4 · Repo analysis (multimodal).** Extract metadata, README, languages, structure, and read screenshots via Gemini vision → a project profile. *AC:* profile includes stack and demonstrated-skill tags.
- **FR-5 · Career memory.** Read/write projects, skill-map, gaps, target JDs, voice profile. *AC:* a new release updates the skill-map and project record.
- **FR-6 · The decision (core).** The Career Strategist returns one of `flagship | update | not_ready | skip`, with written reasoning, highlights, and (if applicable) the gap. *AC:* trivial release → `skip`; incomplete-but-real → `not_ready` + named gap; new substantial project → `flagship`; new version of existing → `update`.
- **FR-7 · README author.** On publish paths, open a PR upgrading the README. *AC:* a real PR appears on the source repo.
- **FR-8 · Portfolio publisher.** Open a PR adding an on-theme card (matching the site's style) with an Imagen preview image. *AC:* a real PR appears on the portfolio repo with an image.
- **FR-9 · LinkedIn post package (no auto-post).** Produce voice-matched text + attached image + hashtags, staged to a review card with copy-all and a prefilled share link. *AC:* the user can post in one tap; nothing is published automatically.
- **FR-10 · Roadmap + live grounding.** Compare the skill-map against current job postings for target roles (seeded fallback) and recommend the next build; optionally open a scaffold issue. *AC:* a concrete next-build recommendation with rationale is written and shown.
- **FR-11 · Self-review.** Critique each artifact vs. a rubric; allow one revision. *AC:* the decision log records the review outcome.
- **FR-12 · Verify.** Confirm the portfolio site still builds after the PR. *AC:* build status logged.
- **FR-13 · Human-in-the-loop.** All irreversible steps (merge PRs, post) require human action. *AC:* nothing external is finalized without the human.
- **FR-14 · Dashboard.** Light-mode page showing the decision log + the post-review card + links to PRs/issue. *AC:* the latest run is visible and understandable at a glance.
- **FR-15 · Observability.** Emit OpenTelemetry traces of the agent's reasoning to Cloud Trace. *AC:* a run's trace is viewable.

## 7. Non-functional requirements

- **NFR-1 · Reliability:** Pub/Sub retries + dead-letter topic; graceful partial failure.
- **NFR-2 · Security:** all secrets in Secret Manager; HMAC-verified webhooks; least-privilege service accounts; no secrets in the repo.
- **NFR-3 · Performance:** `/webhook` returns fast; a full run completes in a few minutes.
- **NFR-4 · Cost:** runs within hackathon credits; no always-on premium resources.
- **NFR-5 · Reproducibility:** README lets a judge spin it up; architecture diagram included.
- **NFR-6 · Agentic integrity:** the Strategist must remain a genuine LLM decision. If it becomes "always run all actions," it fails this requirement even if outputs look fine.

## 8. System & data

- **Framework:** Google ADK (Python), multi-agent (orchestrator + 8 sub-agents/tools), MCP tools where clean.
- **Model:** Gemini 3.5 Flash (or current) on Vertex AI; Imagen for images.
- **Infra:** Cloud Run (one service), Pub/Sub (+ DLQ), Firestore (memory + decision log), Secret Manager, Cloud Trace.
- **Integrations:** GitHub App (webhook + PRs + issues); job-postings source (with seeded fallback).
- **Data model:** `projects/{repo}`, `skill_map/current`, `targets/roles`, `roadmap/current`, `decisions/{delivery_id}`, `voice/profile`, `idempotency/{key}` (see WORK_SPLIT.md §1 for exact fields).

## 9. Assumptions & dependencies

- A GitHub App with the right permissions is installed on the target account.
- Vertex AI access + hackathon credits are active.
- Firestore is seeded with the user's **real projects and 2–3 real target JDs** (the "hireability" story depends on real data).
- A demo portfolio-site repo exists as the PR target.
- these r not assumptions exactly u need to guid me step by step to set these up according to my work split in work_split.md file.

## 10. Judging-criteria alignment

| Criterion | How LaunchPad-AI scores |
|---|---|
| Innovation & Utility (40%) | Strategic career memory + multi-way decision + "what to build next" grounded in live jobs = high-stakes autonomous judgment, not data-shuffling. |
| Architecture (30%) | Decoupled (Pub/Sub + DLQ), stateful (Firestore), secure (Secret Manager), observable (Cloud Trace), self-reviewing → target **Best Architectural Design**. |
| Demo & Production (30%) | Reliable release trigger, visible artifacts, reproducible README, GCP proof, recorded unedited video. |
| Extra buckets | Imagen → **Best Multimodal UX**; solo/small-team → **Individual/Hobbyist**; blog + `#AllThingsAgenticHackathon` → bonus. |

## 11. Risks & mitigations

- Commoditization perception → lead with "manages hireability / what to build next," not "writes READMEs."
- Decision degrades into a script → guard FR-6/NFR-6; demo a `skip`.
- Demo breakage → recorded/unedited, reliable release trigger, pre-staged repo, backup take.
- LinkedIn integration fragility → package-only (no OAuth posting).
- Scope creep → §5 out-of-scope is binding.

## 12. Milestones

Day-by-day build sequence and the two-person split live in `BUILD_PLAN.md` and `WORK_SPLIT.md`. Targets: core loop by Day 5, keystone (roadmap + grounding) Days 4–6, record Day 6, submit Day 7 with buffer.

## 13. Open questions (resolve before/early in build)

- OQ1 — Portfolio site format? (Assume a static-site repo whose cards are simple markdown/JSON the Publisher can PR.)
- OQ2 — Confirm the exact current Gemini model ID available in your Vertex region.
- OQ3 — Does LinkedIn's share-link reliably prefill an image? If not, the dashboard card's download+copy flow is the guaranteed one-tap path.

---

*Perfect = SM1–SM5 all true, on real data, demoed live and unedited. Everything in this PRD serves that.*
