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
from google.api_core.exceptions import AlreadyExists
from google.cloud import firestore, pubsub_v1, secretmanager

logger = logging.getLogger(__name__)

router = APIRouter()

# ── Lazy-initialised clients (created on first request, reused after) ────
_publisher: pubsub_v1.PublisherClient | None = None
_secret_client: secretmanager.SecretManagerServiceClient | None = None
_webhook_secret: bytes | None = None
_firestore_client: firestore.Client | None = None


def _get_publisher() -> pubsub_v1.PublisherClient:
    global _publisher
    if _publisher is None:
        _publisher = pubsub_v1.PublisherClient()
    return _publisher


def _get_firestore_client() -> firestore.Client:
    global _firestore_client
    if _firestore_client is None:
        _firestore_client = firestore.Client()
    return _firestore_client


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


def _claim_release_once(repo: str, tag: str, release_id: Any) -> bool:
    """Release-level idempotency safety net, additive to the existing
    delivery_id-based check: GitHub sends up to three webhooks per release
    (published/released/created), each with its own X-GitHub-Delivery id,
    so delivery_id alone can't dedupe them. Keyed on {repo, tag or
    release_id} instead, so all of a single release's webhooks collide on
    the same doc.

    Uses Firestore's atomic .create() (raises AlreadyExists if the doc is
    already there) rather than get().exists followed by set() — GitHub's
    duplicate webhooks for one release arrive within milliseconds of each
    other, well inside a check-then-write race window.

    Returns True if this call claimed the doc (caller should proceed),
    False if it was already claimed (caller should skip).
    """
    doc_id = f"release_{repo.replace('/', '__')}_{tag or release_id}"
    doc_ref = _get_firestore_client().collection("idempotency").document(doc_id)
    try:
        doc_ref.create({"processed_at": firestore.SERVER_TIMESTAMP})
        return True
    except AlreadyExists:
        return False


def _build_pubsub_message(event: dict[str, Any], delivery_id: str) -> dict[str, Any]:
    """
    Build the Pub/Sub message from a GitHub release event.

    Schema:
    {
        "delivery_id": "str",
        "event_type": "release",
        "repo": "owner/name",
        "tag": "v1.0.0",
        "release_name": "Release Title"
    }
    """
    repo = event.get("repository", {})
    release = event.get("release", {})

    tag = release.get("tag_name", "")
    release_name = release.get("name") or tag
    release_body = release.get("body") or ""

    return {
        "delivery_id": delivery_id,
        "event_type": "release",
        "repo": repo.get("full_name", ""),
        "tag": tag,
        "release_name": release_name,
        "release_body": release_body,
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
    2. Handle ping and filter for release.published events.
    3. Build the Pub/Sub message and publish.
    4. Return 200 immediately.
    """
    body = await request.body()

    # 1. Verify HMAC
    _verify_signature(body, x_hub_signature_256)

    delivery_id = x_github_delivery or ""

    # Handle GitHub webhook handshake ping
    if x_github_event == "ping":
        logger.info("Received GitHub ping event. Webhook verification successful.")
        return Response(status_code=200, content="pong")

    # 2. Only process release events with action == 'published'
    if x_github_event != "release":
        logger.info("Ignoring non-release event: %s", x_github_event)
        return Response(status_code=200, content="ignored non-release event")

    event = json.loads(body)
    action = event.get("action")
    if action != "published":
        logger.info("Ignoring release action: %s (only published is processed)", action)
        return Response(status_code=200, content=f"ignored release action {action}")

    # 2b. Release-level idempotency safety net (see _claim_release_once) —
    # behind the published-only filter above, not a replacement for it.
    repo_full_name = event.get("repository", {}).get("full_name", "")
    release = event.get("release", {})
    tag = release.get("tag_name", "")
    release_id = release.get("id", "")
    if not _claim_release_once(repo_full_name, tag, release_id):
        logger.info(
            "Duplicate release webhook for repo=%s tag=%s (delivery=%s) — already ingested, skipping",
            repo_full_name,
            tag,
            delivery_id,
        )
        return Response(status_code=200, content="already ingested")

    # 3. Parse and build the Pub/Sub message
    message = _build_pubsub_message(event, delivery_id)
    logger.info(
        "Publishing release event for repo=%s tag=%s delivery=%s",
        message["repo"],
        message["tag"],
        message["delivery_id"],
    )

    # Immediately signal Stage 1 live telemetry so dashboard opens and glows instantly
    try:
        from datetime import datetime, timezone
        from agent.memory import set_agent_status
        set_agent_status({
            "status": "running",
            "stage": 1,
            "stage_name": "Webhook Received",
            "repo": message["repo"],
            "tag": message["tag"],
            "delivery_id": delivery_id,
            "started_at": datetime.now(timezone.utc).isoformat(),
        })
    except Exception:
        pass

    # 4. Publish to Pub/Sub
    project = os.environ["GOOGLE_CLOUD_PROJECT"]
    topic = f"projects/{project}/topics/launchpad-ai-events"
    publisher = _get_publisher()
    future = publisher.publish(topic, json.dumps(message).encode("utf-8"))
    future.result()  # Block until published (<50ms)

    logger.info("Published to Pub/Sub: delivery=%s", message["delivery_id"])
    return Response(status_code=200, content="ok")
