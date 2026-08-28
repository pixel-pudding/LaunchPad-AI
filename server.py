"""
LaunchPad-AI — FastAPI server.

Assembles all routes into a single FastAPI app deployed on Cloud Run:
  POST /webhook  → GitHub webhook ingest (verify HMAC → Pub/Sub → 200)
  POST /process  → Pub/Sub push handler (calls agent/runner.py::run_agent)
  GET  /          → Dashboard (decision log + post-review card)
  GET  /health    → Health check for Cloud Run
"""

from __future__ import annotations

import base64
import json
import logging
import os

from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

# ── ingest router (webhook) ──────────────────────────────────
from ingest import router as webhook_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="LaunchPad-AI",
    description="Autonomous career agent — watches GitHub, manages hireability",
    version="0.1.0",
)

# Mount the webhook router
app.include_router(webhook_router)

# Mount dashboard static files (CSS, JS)
_dashboard_dir = Path(__file__).parent / "dashboard"
app.mount("/static", StaticFiles(directory=str(_dashboard_dir)), name="static")


# ── POST /process — Pub/Sub push handler ─────────────────────
@app.post("/process")
async def process(request: Request) -> Response:
    """
    Receives Pub/Sub push messages and invokes the agent.

    Pub/Sub push format:
    {
        "message": {
            "data": "<base64-encoded JSON>",
            "messageId": "...",
            ...
        },
        "subscription": "..."
    }

    Steps:
    1. Decode the Pub/Sub message.
    2. Idempotency check: skip if delivery_id already processed.
    3. Acquire a GitHub installation token for the agent's tools.
    4. Call agent.runner.run_agent(event).
    5. Mark delivery_id as processed in Firestore.
    Must return 200/204 to acknowledge; non-2xx causes Pub/Sub retry.
    """
    try:
        envelope = await request.json()
        pubsub_message = envelope.get("message", {})
        data = pubsub_message.get("data", "")

        if not data:
            logger.warning("Empty Pub/Sub message received")
            return Response(status_code=204)

        # Decode the base64 Pub/Sub payload
        event = json.loads(base64.b64decode(data).decode("utf-8"))
        delivery_id = event.get("delivery_id", "unknown")
        logger.info(
            "Processing event: repo=%s delivery=%s",
            event.get("repo"),
            delivery_id,
        )

        # ── Idempotency: skip if already processed ───────────
        from google.cloud import firestore as firestore_client

        db = firestore_client.Client()
        idemp_ref = db.collection("idempotency").document(delivery_id)
        if idemp_ref.get().exists:
            logger.info(
                "Duplicate delivery_id=%s — already processed, skipping.",
                delivery_id,
            )
            return Response(status_code=200, content="duplicate — skipped")

        # ── Acquire GitHub installation token for agent tools ─
        try:
            from infra.github_auth import get_installation_token

            repo_name = event.get("repo", "")
            repo_owner = repo_name.split("/")[0] if "/" in repo_name else None
            github_token = get_installation_token(owner=repo_owner)
            # Inject into the event so the agent's github_tool can use it
            event["_github_token"] = github_token
            logger.info("GitHub installation token injected for delivery=%s (owner=%s)", delivery_id, repo_owner or "default")
        except Exception:
            logger.warning(
                "Could not acquire GitHub token for delivery=%s — agent will run without PR capability",
                delivery_id,
                exc_info=True,
            )

        # ── Call the agent (the seam from WORK_SPLIT.md §1) ──
        try:
            from agent.runner import run_agent

            result = run_agent(event)
            logger.info(
                "Agent completed: delivery=%s action=%s",
                delivery_id,
                result.get("action", "unknown"),
            )
        except ImportError:
            logger.warning(
                "agent.runner not available yet — skipping processing for delivery=%s",
                delivery_id,
            )
            result = {"status": "agent_not_ready", "delivery_id": delivery_id}

        # ── Mark as processed (idempotency) ──────────────────
        idemp_ref.set({"processed_at": firestore_client.SERVER_TIMESTAMP})

        return Response(status_code=200, content=json.dumps(result))

    except Exception:
        logger.exception("Error processing Pub/Sub message")
        # Return 200 to avoid infinite Pub/Sub retries on bad data.
        # Real errors (transient) should raise and return 500 for retry.
        return Response(status_code=200, content="error logged")


# ── GET / — Dashboard ────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def dashboard() -> HTMLResponse:
    """Serve the dashboard from dashboard/index.html."""
    html_path = _dashboard_dir / "index.html"
    return HTMLResponse(content=html_path.read_text(encoding="utf-8"), status_code=200)


# ── GET /health — Health check ───────────────────────────────
@app.get("/health")
async def health() -> dict:
    """Health check endpoint for Cloud Run."""
    return {"status": "healthy", "service": "launchpad-ai"}


# ── GET /api/decisions — Decision log for the dashboard ──────
@app.get("/api/decisions")
async def api_decisions() -> list:
    """
    Return the last 20 decisions from Firestore, newest first.
    The dashboard fetches this to render the decision log.
    """
    try:
        from google.cloud import firestore as firestore_client

        db = firestore_client.Client()
        docs = (
            db.collection("decisions")
            .order_by("ts", direction=firestore_client.Query.DESCENDING)
            .limit(20)
            .stream()
        )
        results = []
        for doc in docs:
            data = doc.to_dict()
            data["id"] = doc.id
            # Convert Firestore timestamps to ISO strings for JSON
            if data.get("ts"):
                data["ts"] = data["ts"].isoformat() if hasattr(data["ts"], "isoformat") else str(data["ts"])
            results.append(data)
        return results
    except Exception:
        logger.exception("Error fetching decisions")
# ── GET /api/agent-status — Live Execution Status ────────────
@app.get("/api/agent-status")
async def api_agent_status() -> dict:
    """
    Return current real-time agent execution status for dashboard live terminal.
    """
    try:
        from agent import memory
        return memory.get_agent_status()
    except Exception:
        return {"status": "idle"}


# ── GET /api/latest-post — Latest post package for the card ──
@app.get("/api/latest-post")
async def api_latest_post() -> dict:
    """
    Return the latest post package (text + hashtags + image) from
    the most recent flagship/update decision for the post-review card.
    """
    try:
        from google.cloud import firestore as firestore_client

        db = firestore_client.Client()
        # Query recent decisions ordered by timestamp, filter in Python to avoid composite index requirement
        docs = (
            db.collection("decisions")
            .order_by("ts", direction=firestore_client.Query.DESCENDING)
            .limit(20)
            .stream()
        )
        valid_actions = {"flagship", "update", "feature_new", "update_existing"}
        for doc in docs:
            data = doc.to_dict()
            if data.get("action") in valid_actions:
                artifacts = data.get("artifacts", {})
                return {
                    "repo": data.get("repo", ""),
                    "action": data.get("action", ""),
                    "reasoning": data.get("reasoning", ""),
                    "post_package": artifacts.get("post_package", {}),
                    "next_builds": artifacts.get("next_builds", []),
                    "readme_pr": artifacts.get("readme_pr", ""),
                    "portfolio_pr": artifacts.get("portfolio_pr", ""),
                }
        return {}
    except Exception:
        logger.exception("Error fetching latest post")
        return {}


# ── GET /api/repos — repos the GitHub App can access, smart pre-select ──
@app.get("/api/repos")
async def api_repos() -> dict:
    """
    List repos the GitHub App installation can access, with ONE smart
    pre-select for the likely portfolio repo (agent/subagents/
    portfolio_repo_picker.py). The agent only SUGGESTS — the user confirms
    (or picks something else) via POST /api/portfolio-config.
    """
    try:
        from agent.subagents.portfolio_repo_picker import list_candidate_repos

        repos = list_candidate_repos()
        return {"repos": repos, "error": None}
    except Exception as exc:
        logger.exception("Error listing installation repos")
        return {"repos": [], "error": str(exc)}


# ── POST /api/portfolio-config — save the chosen portfolio repo ─────
@app.post("/api/portfolio-config")
async def api_set_portfolio_config(request: Request) -> dict:
    """
    Persist the user's chosen portfolio repo + auto-merge setting (and,
    optionally, an explicit format choice) to Firestore config/portfolio.
    This is what agent/config.py resolves from now on — the
    PORTFOLIO_REPO/PORTFOLIO_AUTO_MERGE env vars are only the fallback for
    as long as nothing's been configured here yet.

    "format" ("convention"/"arbitrary") is OPTIONAL and deliberately NOT
    defaulted here: if the caller omits it, memory.set_portfolio_config()
    leaves the "format" key out of the write entirely (not written as
    null), preserving the explicit-vs-defaulted distinction
    agent/config.py's resolvers depend on. Defaulting it to "convention" at
    write time here would destroy that distinction and make every
    first-time bootstrap look "explicitly confirmed" when it isn't.
    """
    try:
        body = await request.json()
        portfolio_repo = body.get("portfolio_repo", "")
        auto_merge = bool(body.get("auto_merge", True))
        format = body.get("format")  # None if omitted — left as None, not defaulted

        from agent import memory

        memory.set_portfolio_config(portfolio_repo, auto_merge, format=format)
        return {"ok": True, "error": None}
    except Exception as exc:
        logger.exception("Error saving portfolio config")
        return {"ok": False, "error": str(exc)}


# ── GET /api/portfolio-config — the current saved portfolio config ──
@app.get("/api/portfolio-config")
async def api_get_portfolio_config() -> dict | None:
    """Return the saved config/portfolio doc, or null if never configured."""
    try:
        from agent import memory

        return memory.get_portfolio_config()
    except Exception:
        logger.exception("Error fetching portfolio config")
        return None


# ── Entrypoint ───────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
