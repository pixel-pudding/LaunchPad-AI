"""
LaunchPad-AI — Agent runner (the seam).

This module is OWNED BY Claude Code [CC]. [AG] calls run_agent() from
the /process route but NEVER modifies this file's signature.

The seam signature is frozen (CLAUDE.md / WORK_SPLIT.md §1) and must not change.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from agent import memory
from agent.subagents.relevance_curator import curate
from agent.subagents.release_analyst import analyze_release

logger = logging.getLogger(__name__)


def run_agent(event: dict) -> dict:
    """
    The seam function from CLAUDE.md's frozen contract.

    event = the release Pub/Sub message:
    {
        "delivery_id": "str",
        "event_type": "release",
        "repo": "owner/name",
        "tag": "v1.0",
        "release_name": "str"
    }

    Returns the decision record that also gets written to Firestore.

    Flow: idempotency check -> release_analyst -> relevance_curator ->
    memory write-back (if featured) -> save decision -> mark processed ->
    return.
    """
    delivery_id = event.get("delivery_id", "")
    repo = event.get("repo", "")

    if memory.is_duplicate_delivery(delivery_id):
        logger.info("Duplicate delivery %s for %s — skipping", delivery_id, repo)
        return {"status": "duplicate", "delivery_id": delivery_id, "repo": repo}

    logger.info(
        "Processing release: repo=%s tag=%s delivery=%s",
        repo,
        event.get("tag"),
        delivery_id,
    )

    profile = analyze_release(event)

    memory_context = {
        "featured_projects": memory.list_projects(),
        "context_profile": memory.get_context_profile(),
    }
    decision = curate(profile, memory_context, delivery_id)

    if decision["action"] in ("feature_new", "update_existing"):
        # TODO: Portfolio Publisher owns the richer write (portfolio_url, the
        # full profile fields, etc.) — this just keeps memory minimally
        # consistent so the curator sees this repo as already-featured on
        # its next release.
        memory.upsert_project(
            repo,
            {
                "repo": repo,
                "name": profile.get("name", ""),
                "status": "featured",
                "tag": event.get("tag", ""),
                "ts": datetime.now(timezone.utc).isoformat(),
            },
        )

    record = {
        "repo": repo,
        "tag": event.get("tag", ""),
        **decision,
        "artifacts": {},
        "self_review": None,
        "verified": None,
    }

    memory.save_decision(delivery_id, record)
    memory.mark_delivery_processed(delivery_id)
    return record
