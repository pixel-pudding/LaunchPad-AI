"""
LaunchPad-AI — Firestore memory accessors (agent/memory.py).

Collection contract is frozen in CLAUDE.md (adapted from WORK_SPLIT.md §1).
Do not rename a collection or field here without agreeing it with [AG] first.

Every accessor takes an optional `client` so callers (tests) can inject a
fake Firestore client instead of hitting real GCP.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from google.cloud import firestore

logger = logging.getLogger(__name__)

_client: firestore.Client | None = None


def get_client() -> firestore.Client:
    """Lazily creates the shared Firestore client (real GCP, or the emulator
    if FIRESTORE_EMULATOR_HOST is set)."""
    global _client
    if _client is None:
        _client = firestore.Client()
    return _client


def _doc_id(repo: str) -> str:
    """Firestore document IDs can't contain '/', which repo names ('owner/name') do."""
    return repo.replace("/", "__")


# ── projects/{repo} — what's currently featured on portfolio + LinkedIn ──


def get_project(repo: str, client: firestore.Client | None = None) -> dict[str, Any] | None:
    client = client or get_client()
    doc = client.collection("projects").document(_doc_id(repo)).get()
    return doc.to_dict() if doc.exists else None


def list_projects(client: firestore.Client | None = None) -> list[dict[str, Any]]:
    client = client or get_client()
    return [doc.to_dict() for doc in client.collection("projects").stream()]


def upsert_project(repo: str, data: dict[str, Any], client: firestore.Client | None = None) -> None:
    client = client or get_client()
    client.collection("projects").document(_doc_id(repo)).set(data, merge=True)


# ── context/profile — dev's past projects + interests (decision CONTEXT only) ──


def get_context_profile(client: firestore.Client | None = None) -> dict[str, Any]:
    client = client or get_client()
    doc = client.collection("context").document("profile").get()
    return doc.to_dict() if doc.exists else {}


def set_context_profile(data: dict[str, Any], client: firestore.Client | None = None) -> None:
    """Writes (or overwrites) the dev's context/profile document."""
    client = client or get_client()
    client.collection("context").document("profile").set(data, merge=True)


# ── config/portfolio — the user's chosen portfolio repo + auto-merge setting ──


def get_portfolio_config(client: firestore.Client | None = None) -> dict[str, Any] | None:
    """Returns the saved config/portfolio doc, or None if never configured."""
    client = client or get_client()
    doc = client.collection("config").document("portfolio").get()
    if not doc.exists:
        return None
    data = doc.to_dict()
    ts = data.get("ts")
    if ts is not None and hasattr(ts, "isoformat"):
        data["ts"] = ts.isoformat()
    return data


def set_portfolio_config(
    portfolio_repo: str,
    auto_merge: bool,
    format: str | None = None,
    client: firestore.Client | None = None,
) -> None:
    """Writes the config/portfolio doc. `ts` is written as a Firestore
    server timestamp; get_portfolio_config() converts it back to an ISO
    string on read, since the raw sentinel isn't JSON-serializable — same
    reasoning as the decisions/{delivery_id} writes in runner.py.

    `format` ("convention"/"arbitrary") is OPTIONAL and its KEY PRESENCE
    (not just its value) carries meaning to config.get_portfolio_format_
    explicit(): present = the picker explicitly chose it, absent = purely
    defaulted. So when `format` isn't passed here, the "format" key is left
    out of this write entirely — not written as None/null, which would
    still count as "present" on read. This write uses merge=True
    specifically so that omitting `format` on a later call (e.g. a caller
    just toggling auto_merge) doesn't wipe a previously-explicit choice
    back to unset.
    """
    client = client or get_client()
    data: dict[str, Any] = {
        "portfolio_repo": portfolio_repo,
        "auto_merge": auto_merge,
        "ts": firestore.SERVER_TIMESTAMP,
    }
    if format is not None:
        data["format"] = format
    client.collection("config").document("portfolio").set(data, merge=True)


# ── voice/profile — post voice ───────────────────────────────────────────


def get_voice_profile(client: firestore.Client | None = None) -> dict[str, Any]:
    client = client or get_client()
    doc = client.collection("voice").document("profile").get()
    return doc.to_dict() if doc.exists else {}


# ── idempotency/{delivery_id} — dedupe on release delivery ──────────────


def is_duplicate_delivery(delivery_id: str, client: firestore.Client | None = None) -> bool:
    client = client or get_client()
    return client.collection("idempotency").document(delivery_id).get().exists


def mark_delivery_processed(delivery_id: str, client: firestore.Client | None = None) -> None:
    client = client or get_client()
    client.collection("idempotency").document(delivery_id).set(
        {"processed_at": datetime.now(timezone.utc).isoformat()}
    )


# ── decisions/{delivery_id} — the decision log ───────────────────────────


def save_decision(delivery_id: str, record: dict[str, Any], client: firestore.Client | None = None) -> None:
    client = client or get_client()
    client.collection("decisions").document(delivery_id).set(record)


# ── config/agent_status — real-time live terminal telemetry ──────────────


def get_agent_status(client: firestore.Client | None = None) -> dict[str, Any]:
    """Returns the most recently STARTED run's live-terminal status.

    Each run gets its own doc (see set_agent_status()) keyed by
    delivery_id, instead of every run overwriting one shared doc — so a
    page reload mid-run, or two runs that happen to overlap, can never
    read a status blended from two different deliveries. Every write
    within one run carries the same started_at, so ordering by it and
    taking the top match always returns whichever run is newest, whether
    it's still running or already idle/completed.
    """
    client = client or get_client()
    docs = (
        client.collection("agent_status")
        .order_by("started_at", direction=firestore.Query.DESCENDING)
        .limit(1)
        .stream()
    )
    for doc in docs:
        data = doc.to_dict()
        ts = data.get("ts")
        if ts is not None and hasattr(ts, "isoformat"):
            data["ts"] = ts.isoformat()
        return data
    return {"status": "idle"}


def set_agent_status(data: dict[str, Any], client: firestore.Client | None = None) -> None:
    """Writes this run's live-terminal telemetry to ITS OWN doc, keyed by
    delivery_id — not one doc every run shares and overwrites. Every
    stage-transition call from runner.py already carries "delivery_id";
    the final idle/completed call carries "last_delivery_id" instead
    (it's describing a run that just finished, not one in progress), so
    that's checked too — both land in the same per-run doc, keeping one
    run's full lifecycle (stage 1 through idle) together.
    """
    client = client or get_client()
    run_key = data.get("delivery_id") or data.get("last_delivery_id") or "unknown"
    record = {**data, "ts": datetime.now(timezone.utc).isoformat()}
    client.collection("agent_status").document(run_key).set(record, merge=True)
