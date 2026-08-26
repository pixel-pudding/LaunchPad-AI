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

            github_token = get_installation_token()
            # Inject into the event so the agent's github_tool can use it
            event["_github_token"] = github_token
            logger.info("GitHub installation token injected for delivery=%s", delivery_id)
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
        return []


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
        docs = (
            db.collection("decisions")
            .where("action", "in", ["flagship", "update", "feature_new", "update_existing"])
            .order_by("ts", direction=firestore_client.Query.DESCENDING)
            .limit(1)
            .stream()
        )
        for doc in docs:
            data = doc.to_dict()
            artifacts = data.get("artifacts", {})
            return {
                "repo": data.get("repo", ""),
                "action": data.get("action", ""),
                "reasoning": data.get("reasoning", ""),
                "post_package": artifacts.get("post_package", {}),
                "readme_pr": artifacts.get("readme_pr", ""),
                "portfolio_pr": artifacts.get("portfolio_pr", ""),
            }
        return {}
    except Exception:
        logger.exception("Error fetching latest post")
        return {}


# ── Entrypoint ───────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
