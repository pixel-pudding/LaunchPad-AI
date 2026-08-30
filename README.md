# LaunchPad-AI

### An autonomous agent that keeps your developer presence in sync with what you ship
**All Things Agentic Hackathon · Taskmaster Track**

> You publish a GitHub release. LaunchPad-AI decides — on its own — whether that release is worth showing the world, and if it is, it updates your live portfolio and drafts your LinkedIn post. You ship. It handles the rest.

[![Live Demo](https://img.shields.io/badge/Live%20Demo-Cloud%20Run-4F684F?style=for-the-badge&logo=googlecloud)](https://launchpad-ai-757438144336.asia-south1.run.app/)
[![Gemini 3.5 Flash](https://img.shields.io/badge/Model-Gemini%203.5%20Flash-E8C96A?style=for-the-badge&logo=googlegemini)](https://cloud.google.com/vertex-ai)
[![Google ADK](https://img.shields.io/badge/Framework-Google%20ADK-5D7A5B?style=for-the-badge)](https://google.github.io/adk-docs/)

---

## The friction it solves

Developers ship constantly and then never update the places people actually look — their portfolio and LinkedIn. The tedious part isn't writing one post; it's the *judgment call* on every release: is this worth featuring as new, an update to something already shown, or nothing at all?

LaunchPad-AI is an agent that makes that decision autonomously and acts on it — no dashboard clicking, no manual editing, no redeploy. **The agent's decision is the product.** It's not a bot that posts on every release; it's an agent with the judgment to know when *not* to.

---

## What makes it agentic (not a script)

The core is a **Relevance Curator**: a real [Google ADK](https://google.github.io/adk-docs/) `LlmAgent` running **Gemini 3.5 Flash on Vertex AI** through the ADK Runner, producing a schema-constrained structured decision. On each release it receives the shipped repo's profile, the projects already featured, and the developer's interests — and returns one of three actions with written reasoning:

| Decision | When | What it does |
|:---|:---|:---|
| `feature_new` | A substantial, not-yet-featured project | Writes a new portfolio card + drafts the LinkedIn post |
| `update_existing` | A real new capability on an already-featured project | Refreshes the LinkedIn announcement; no duplicate entry |
| `skip` | Trivial bumps, doc-only fixes, WIP | Leaves everything untouched |

It **explains every decision in its own words** ("a dependency bump with no new capability — not notable enough to feature"), and it **remembers what's already public** (via Firestore) so it never posts the same project twice. Correctly *declining* to act is the clearest evidence that it's reasoning, not automating.

---

## Architecture

Event-driven and decoupled end to end. Each Google Cloud service is chosen for a specific engineering reason.

```
GitHub Release (published)
      │ HMAC-signed webhook
      ▼
Cloud Run  [ingest]  ──(Secret Manager: webhook secret)──►  fast 200 OK
      │
      ▼
Cloud Pub/Sub  [launchpad-ai-events]  ──(retries + dead-letter)──►  [launchpad-ai-dead-letter]
      │ OIDC-authenticated push
      ▼
Cloud Run  [POST /process]
      ├─ Idempotency (Firestore: per-delivery + atomic per-release {repo}:{tag})
      ├─ GitHub App auth (RS256 JWT via Secret Manager .pem)
      ▼
Google ADK Agent — Gemini 3.5 Flash on Vertex AI
      ├─ Release Analyst      → deterministic repo/stack profiling
      ├─ Relevance Curator    → the genuine multi-way LLM decision (feature/update/skip)
      ├─ Content Writer       → project card + LinkedIn draft
      ├─ Image Tool (Imagen)  → post image
      ├─ Self-Reviewer        → one critique/revision pass on the draft
      ├─ Portfolio Publisher  → opens a PR to the portfolio repo (feature_new only)
      └─ Next-Build Suggester → optional byproduct footnote
      ▼
Cloud Firestore — memory (featured projects, profile) + decision log
      ▼
Dashboard [GET /] — live decision feed + copy-ready LinkedIn post
```

**Why each piece:**
- **Cloud Run** — scales to zero between releases and spins up on the webhook; matches a bursty, event-triggered workload with no always-on cost.
- **Pub/Sub** — decouples ingest from processing so the webhook returns instantly and the agent works in the background; its dead-letter queue and retries make a transient failure recoverable instead of lost.
- **Vertex AI (Gemini 3.5 Flash)** — service-account auth (no API keys) and structured output we can gate real actions on.
- **Firestore** — the agent's serverless memory: featured projects, developer profile, and a full decision log.
- **Secret Manager** — holds the webhook secret and the GitHub App private key.

Every stage has its own error handling and **fails safe**: if the curator errors, it defaults to `skip` — never publishes something unreviewed. Each action subagent fails independently, so one failure never takes down the run. Portfolio changes are attempted **only** on `feature_new`, so an update or a skip can never mutate the live site.

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full diagram and data contracts.

---

## How the portfolio gets updated

When the agent features a new project, the **Portfolio Publisher** detects where projects live in the target repo (HTML cards, JSX/React, Astro, Markdown) and opens a pull request that inserts the new card in the repo's own native format. On repos where auto-merge is enabled, the PR is merged so the live site updates hands-free; otherwise it's left open for review. Detection confidence is explicit — when the structure can't be confidently located, the agent instead prepares the card content in a standalone file for the developer to place, rather than editing code it isn't sure about. Fully reliable unattended editing of every possible portfolio shape is an ongoing area of work.

---

## Tech stack

**Google ADK** (agent orchestration) · **Gemini 3.5 Flash on Vertex AI** (the decision) · **Cloud Run** · **Cloud Pub/Sub** · **Cloud Firestore** · **Secret Manager** · **FastAPI** · **Python 3.11**

**External data:** GitHub Releases API + GitHub App (release events, repo contents, pull requests) — the agent's trigger and action surface.

---

## Spin-up & local reproducibility

### 1. Prerequisites
- **Python** 3.11 or 3.12
- **Google Cloud CLI (`gcloud`)** installed and authenticated ([install guide](https://cloud.google.com/sdk/docs/install))
- A **Google Cloud project** with Vertex AI, Cloud Run, Firestore, and Pub/Sub APIs enabled

### 2. Clone & environment setup
```bash
git clone https://github.com/pixel-pudding/LaunchPad-AI.git
cd LaunchPad-AI

python -m venv .venv
# Windows (PowerShell):
.\.venv\Scripts\Activate.ps1
# macOS / Linux:
source .venv/bin/activate

pip install -e ".[dev]"
```

### 3. Configure environment
```bash
cp .env.example .env
```
Set in `.env`:
```env
GOOGLE_GENAI_USE_VERTEXAI=1
GOOGLE_CLOUD_PROJECT=your-gcp-project-id
GOOGLE_CLOUD_LOCATION=asia-south1
GEMINI_MODEL=gemini-3.5-flash
GITHUB_APP_ID=your-github-app-id     # optional for local; mocked in the test suite
PORTFOLIO_AUTO_MERGE=1
```
Authenticate with Application Default Credentials:
```bash
gcloud auth application-default login
gcloud config set project your-gcp-project-id
```

### 4. Run the tests & the decision evaluation
```bash
# Full unit test suite (99 tests across agent, ingest, and eval)
pytest

# The decision canaries — the two hardest traps:
#   trivial patch to a featured project must SKIP (not auto-update)
#   major release to a featured project must UPDATE (not duplicate)
pytest eval/test_curator_canaries.py -v

# Full evaluation against real Gemini 3.5 Flash on Vertex AI
python -m eval.run_curator_eval
```

### 5. Run the server & dashboard locally
```bash
uvicorn server:app --host 0.0.0.0 --port 8080 --reload
```
- Dashboard: [`http://localhost:8080`](http://localhost:8080)
- Health check: [`http://localhost:8080/health`](http://localhost:8080/health)
- Agent status API: [`http://localhost:8080/api/agent-status`](http://localhost:8080/api/agent-status)

### 6. Deploy to Google Cloud Run
```bash
gcloud run deploy launchpad-ai \
  --source . \
  --project your-gcp-project-id \
  --region asia-south1 \
  --allow-unauthenticated \
  --port 8080 \
  --memory 512Mi \
  --set-env-vars "GOOGLE_CLOUD_PROJECT=your-gcp-project-id,GOOGLE_CLOUD_LOCATION=asia-south1,\
GOOGLE_GENAI_USE_VERTEXAI=1,GEMINI_MODEL=gemini-3.5-flash,GITHUB_APP_ID=your-app-id,PORTFOLIO_AUTO_MERGE=1"
```
Or run the deploy script:
```bash
bash ./infra/deploy.sh
```
Then provision the Pub/Sub topic, OIDC push subscription, and dead-letter queue (`infra/setup_pubsub_auth.sh`), and point your GitHub App's webhook at the ingest endpoint for `release` events.

---

## Repository structure

```
agent/
  runner.py                 # the frozen seam: run_agent(event) — orchestrates the pipeline
  config.py                 # config resolution (Firestore-first, env fallback); enforces Gemini 3.5+
  memory.py                 # Firestore accessors (projects, profile, decisions, config)
  subagents/
    relevance_curator.py    # the genuine ADK LlmAgent decision — the agentic core
    release_analyst.py      # deterministic repo/stack profiling
    content_writer.py       # project card + LinkedIn draft
    self_reviewer.py        # one critique/revision pass
    portfolio_publisher.py  # opens the portfolio PR (feature_new only)
    portfolio_structure_detector.py  # detects where projects live in the target repo
    portfolio_repo_picker.py# finds the user's portfolio repo regardless of name
    profile_bootstrapper.py # synthesizes a profile from GitHub if none exists
    announcer.py            # assembles the post package
    next_build_suggester.py # optional byproduct
  tools/
    github_tool.py          # GitHub App auth, PR create/merge
    image_tool.py           # Imagen image generation
eval/                       # curator evaluation + canary gates + placeholder guard
ingest/                     # HMAC webhook verification + Pub/Sub publish + release dedup
infra/                      # deploy + Pub/Sub/OIDC setup, GitHub App auth, Firestore seed
server.py                   # FastAPI: /process, dashboard, /api/*
dashboard/                  # live decision-feed UI
```

---

## Findings & learnings

- **The hard part of an agent is the decision, not the plumbing** — and making that decision *legible* (written reasoning per action) is what makes it feel like an agent instead of a script.
- **Live systems surprise you.** One release was creating three decision records because GitHub fires three webhooks (`published`/`released`/`created`) with distinct delivery IDs. The fix: accept only `published`, plus an atomic per-release dedupe using Firestore's `create()` (a check-then-write races, since the duplicates arrive within milliseconds). This passed every unit test — we only found it by running the real system.
- **Decoupling is what makes "runs in the background" true.** Pub/Sub between ingest and processing, per-stage failure isolation, and fail-safe defaults are what turn a demo into something that survives a bad network day.

---

## Team

**Aditi** ([pixel-pudding](https://github.com/pixel-pudding)) · **Ameya** ([AmeyaSingh23](https://github.com/AmeyaSingh23))

**Built for the All Things Agentic Hackathon with Google ADK**, Gemini 3.5 Flash on Vertex AI, Cloud Run, Pub/Sub, and Firestore.
