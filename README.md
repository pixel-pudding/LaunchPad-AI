# 🚀 LaunchPad-AI

### Autonomous Career Agent · All Things Agentic Hackathon (Taskmaster Track)

> **An autonomous career agent that manages your hireability** — watching what you build on GitHub, maintaining a live model of your skills against the jobs you want, deciding how each project changes your standing, preparing publish-ready materials, and recommending what to build next to close the gap.

[![Live Dashboard](https://img.shields.io/badge/Live%20Demo-Cloud%20Run-blue?style=for-the-badge&logo=googlecloud)](https://launchpad-ai-757438144336.asia-south1.run.app/)
[![Gemini 3.5 Flash](https://img.shields.io/badge/Model-Gemini%203.5%20Flash-purple?style=for-the-badge&logo=googlegemini)](https://cloud.google.com/vertex-ai)
[![Google ADK](https://img.shields.io/badge/Framework-Google%20ADK-green?style=for-the-badge)](https://google.github.io/adk-docs/)

---

## 🏆 Hackathon Compliance Checklist

| Mandatory Requirement | Implementation in LaunchPad-AI |
|:---|:---|
| **Gemini 3.5+ Model** | Powered by `gemini-3.5-flash` via Vertex AI (`GOOGLE_GENAI_USE_VERTEXAI=1`) in `asia-south1` |
| **≥1 Google Agent Framework** | **Google ADK (Python)** for multi-agent orchestration and subagent routing |
| **≥1 Google Cloud Infrastructure** | **4 Google Cloud Services**: Cloud Run + Cloud Pub/Sub + Cloud Firestore + Secret Manager |
| **Taskmaster Track Fit** | Autonomous trigger from GitHub Releases → multi-way LLM decision → automated PR generation + post preparation |
| **Observability** | Integrated OpenTelemetry distributed tracing viewable in **Google Cloud Trace** |

---

## 🏛️ System Architecture

LaunchPad-AI uses a decoupled, event-driven serverless architecture on Google Cloud:

```
GitHub Release (published)
       │ HMAC-signed Webhook
       ▼
Cloud Run [POST /webhook]  ──(Secret Manager)──► Fast 200 OK (<200ms)
       │
       ▼
Google Cloud Pub/Sub [launchpad-ai-events]  ──(Dead-Letter Queue)──► [launchpad-ai-dead-letter]
       │ OIDC Authenticated Push
       ▼
Cloud Run [POST /process]
       ├─ Idempotency Check (Firestore deduplication on delivery_id)
       ├─ GitHub App Auth (RS256 JWT exchange via Secret Manager .pem)
       ▼
Google ADK Agent Orchestrator (Gemini 3.5 Flash on Vertex AI)
       ├─ Repo Analyst: Ingests repository tree, README, tech stack
       ├─ Career Strategist: Multi-way decision (feature_new | update_existing | not_ready | skip)
       ├─ Action Subagents: README PR + Portfolio Card PR + Announcer Post Package
       ├─ Self-Reviewer & Roadmap Planner: Validates claims & recommends next build
       ▼
Cloud Firestore Memory & Decision Logs
       ▼
Dashboard UI [GET /]: Decision Log + 1-Tap LinkedIn Post Review Card
```

*For in-depth architecture diagrams, security models, and data contracts, see [ARCHITECTURE.md](ARCHITECTURE.md).*

---

## ⚡ Quickstart & Local Evaluation

### Prerequisites
- Python 3.12+
- Google Cloud CLI (`gcloud`) with ADC configured (`gcloud auth application-default login`)

### 1. Clone & Install Dependencies
```bash
git clone https://github.com/pixel-pudding/LaunchPad-AI.git
cd LaunchPad-AI

# Install package and dev dependencies
pip install -e ".[dev]"
```

### 2. Run the Strategist / Curator Evaluation Suite
LaunchPad-AI includes a 10-case evaluation suite and hard-gate canary tests validating the LLM decision accuracy:

```bash
# Run canary test gates
python -m pytest eval/test_curator_canaries.py -v

# Run the full 10-case evaluation against Vertex AI Gemini 3.5 Flash
python -m eval.run_curator_eval
```

### 3. Run the Server Locally
```bash
cp .env.example .env
# Edit .env with your Google Cloud Project ID

uvicorn server:app --host 0.0.0.0 --port 8080 --reload
```
Open `http://localhost:8080` to access the Dashboard.

---

## 🚀 Google Cloud Deployment

### 1. Deploy Cloud Run Service
```bash
./infra/deploy.sh
```

### 2. Configure Pub/Sub OIDC Push Auth & Dead-Letter Queue
```bash
./infra/setup_pubsub_auth.sh
```

---

## 📂 Repository Structure

```
LaunchPad-AI/
├── agent/                  # Google ADK Agent Core & Subagents
│   ├── agent.py            # Root orchestrator & subagents
│   ├── config.py           # Model version checks (Gemini 3.5+)
│   ├── memory.py           # Firestore memory accessors
│   ├── runner.py           # The run_agent(event) entrypoint seam
│   ├── subagents/          # Curator, Analyst, Announcer, Reviewer subagents
│   └── tools/              # GitHub App tools & external integrations
├── dashboard/              # Clean Light-Mode Dashboard UI
│   ├── index.html          # Decision log + Post review card
│   ├── dashboard.css       # Polished responsive design & badges
│   └── dashboard.js        # Dynamic fetch & 1-tap copy/share logic
├── eval/                   # ADK Evaluation Suite & Canaries
│   ├── curator_cases.py    # 10 labeled test cases
│   ├── run_curator_eval.py # Live Vertex AI evaluation runner
│   └── test_curator_canaries.py # Pytest canary validation gates
├── ingest/                 # FastAPI Webhook Ingest Router
├── infra/                  # GCP Setup, Deploy Scripts & Auth Helpers
│   ├── deploy.sh           # Cloud Run deployment script
│   ├── github_auth.py      # GitHub App RS256 JWT installation token helper
│   └── setup_pubsub_auth.sh # OIDC push auth & DLQ setup script
├── ARCHITECTURE.md         # Full architectural design & Mermaid diagrams
├── BUILD_PLAN.md           # Master hackathon execution plan
├── WORK_SPLIT.md           # Multi-agent collaboration contracts
├── server.py               # Main FastAPI server (Ingest + Worker + Dashboard)
├── Dockerfile              # Production multi-stage container
└── pyproject.toml          # Project configuration & dependencies
```

---

## 👥 Team
- **Aditi (`[CC]`)** — Agent Brain, ADK Orchestration, Reasoning, Prompts & Evals
- **Ameya (`[AG]`)** — Cloud Infrastructure, Event Ingestion, Security, Auth & Frontend Dashboard
