"""
LaunchPad-AI — Webhook ingest router.

POST /webhook receives GitHub webhook events, verifies the HMAC signature
using the secret stored in Secret Manager, builds the §1 Pub/Sub message
schema, publishes it to the launchpad-ai-events topic, and returns 200
immediately (must respond within GitHub's ~10s timeout).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request, Response
from google.cloud import pubsub_v1, secretmanager

logger = logging.getLogger(__name__)

router = APIRouter()

# ── Lazy-initialised clients (created on first request, reused after) ────
_publisher: pubsub_v1.PublisherClient | None = None
_secret_client: secretmanager.SecretManagerServiceClient | None = None
_webhook_secret: bytes | None = None


def _get_publisher() -> pubsub_v1.PublisherClient:
    global _publisher
    if _publisher is None:
        _publisher = pubsub_v1.PublisherClient()
    return _publisher


def _get_webhook_secret() -> bytes:
    """Fetch the webhook secret from Secret Manager (cached after first call)."""
    global _secret_client, _webhook_secret
    if _webhook_secret is not None:
        return _webhook_secret

    if _secret_client is None:
        _secret_client = secretmanager.SecretManagerServiceClient()

    project = os.environ["GOOGLE_CLOUD_PROJECT"]
    secret_name = f"projects/{project}/secrets/github-webhook-secret/versions/latest"
    response = _secret_client.access_secret_version(request={"name": secret_name})
    _webhook_secret = response.payload.data
    return _webhook_secret


def _verify_signature(payload: bytes, signature_header: str | None) -> None:
    """Verify the X-Hub-Signature-256 HMAC. Raises 401 on failure."""
    if not signature_header:
        raise HTTPException(status_code=401, detail="Missing X-Hub-Signature-256")

    secret = _get_webhook_secret()
    expected = "sha256=" + hmac.new(secret, payload, hashlib.sha256).hexdigest()

    if not hmac.compare_digest(expected, signature_header):
        raise HTTPException(status_code=401, detail="Invalid signature")


def _build_pubsub_message(event: dict[str, Any]) -> dict[str, Any]:
    """
    Build the frozen-contract Pub/Sub message from a GitHub push event.

    Schema (WORK_SPLIT.md §1):
    {
        "delivery_id": "str",
        "repo": "owner/name",
        "default_branch": "main",
        "commits": [{"message": "str"}],
        "pusher": "str"
    }
    """
    repo = event.get("repository", {})
    commits_raw = event.get("commits", [])

    return {
        "delivery_id": event.get("delivery", ""),
        "repo": repo.get("full_name", ""),
        "default_branch": repo.get("default_branch", "main"),
        "commits": [{"message": c.get("message", "")} for c in commits_raw],
        "pusher": event.get("pusher", {}).get("name", ""),
    }


@router.post("/webhook")
async def webhook(
    request: Request,
    x_hub_signature_256: str | None = Header(None),
    x_github_event: str | None = Header(None),
    x_github_delivery: str | None = Header(None),
) -> Response:
    """
    GitHub webhook endpoint.

    1. Verify HMAC signature (Secret Manager).
    2. Ignore non-push events.
    3. Build the §1 Pub/Sub message and publish.
    4. Return 200 immediately.
    """
    body = await request.body()

    # 1. Verify HMAC
    _verify_signature(body, x_hub_signature_256)

    # 2. Only process push events
    if x_github_event != "push":
        logger.info("Ignoring non-push event: %s", x_github_event)
        return Response(status_code=200, content="ignored")

    # 3. Parse and build the Pub/Sub message
    event = json.loads(body)
    # Inject the delivery ID from the header (more reliable than body)
    event["delivery"] = x_github_delivery or ""

    message = _build_pubsub_message(event)
    logger.info(
        "Publishing event for repo=%s delivery=%s",
        message["repo"],
        message["delivery_id"],
    )

    # 4. Publish to Pub/Sub
    project = os.environ["GOOGLE_CLOUD_PROJECT"]
    topic = f"projects/{project}/topics/launchpad-ai-events"
    publisher = _get_publisher()
    future = publisher.publish(topic, json.dumps(message).encode("utf-8"))
    future.result()  # Block until published (still fast — Pub/Sub is <50ms)

    logger.info("Published to Pub/Sub: delivery=%s", message["delivery_id"])
    return Response(status_code=200, content="ok")
