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

from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse

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

    Calls agent.runner.run_agent(event) with the decoded message.
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

        # ── Call the agent (the seam from WORK_SPLIT.md §1) ──
        # Import here to avoid circular imports and to keep the
        # server bootable even if agent/ isn't fully built yet.
        try:
            from agent.runner import run_agent

            result = run_agent(event)
            logger.info(
                "Agent completed: delivery=%s action=%s",
                delivery_id,
                result.get("action", "unknown"),
            )
        except ImportError:
            # agent/ not built yet — log and ack so Pub/Sub doesn't retry
            logger.warning(
                "agent.runner not available yet — skipping processing for delivery=%s",
                delivery_id,
            )
            result = {"status": "agent_not_ready", "delivery_id": delivery_id}

        return Response(status_code=200, content=json.dumps(result))

    except Exception:
        logger.exception("Error processing Pub/Sub message")
        # Return 200 to avoid infinite Pub/Sub retries on bad data.
        # Real errors (transient) should raise and return 500 for retry.
        return Response(status_code=200, content="error logged")


# ── GET / — Dashboard ────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def dashboard() -> HTMLResponse:
    """
    Dashboard placeholder — will be replaced with the full decision log
    and post-review card UI on Day 5.
    """
    return HTMLResponse(
        content="""
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>LaunchPad-AI — Dashboard</title>
            <style>
                body {
                    font-family: 'Inter', system-ui, sans-serif;
                    display: flex; align-items: center; justify-content: center;
                    min-height: 100vh; margin: 0;
                    background: #fafafa; color: #1a1a1a;
                }
                .card {
                    text-align: center; padding: 3rem;
                    background: white; border-radius: 12px;
                    box-shadow: 0 1px 3px rgba(0,0,0,0.08);
                }
                h1 { font-size: 1.5rem; margin-bottom: 0.5rem; }
                p { color: #666; font-size: 0.95rem; }
                .status { color: #22c55e; font-weight: 600; }
            </style>
        </head>
        <body>
            <div class="card">
                <h1>🚀 LaunchPad-AI</h1>
                <p class="status">Service is running</p>
                <p>Dashboard coming Day 5 — decision log + post-review card</p>
            </div>
        </body>
        </html>
        """,
        status_code=200,
    )


# ── GET /health — Health check ───────────────────────────────
@app.get("/health")
async def health() -> dict:
    """Health check endpoint for Cloud Run."""
    return {"status": "healthy", "service": "launchpad-ai"}


# ── Entrypoint ───────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
