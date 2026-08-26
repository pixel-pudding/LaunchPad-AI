"""
LaunchPad-AI — Agent runner (the seam).

This module is OWNED BY Claude Code [CC]. [AG] calls run_agent() from
the /process route but NEVER modifies this file's signature.

The seam signature is frozen (CLAUDE.md / WORK_SPLIT.md §1) and must not change.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from google.cloud import firestore

from agent import memory
from agent.subagents.announcer import assemble_post_package
from agent.subagents.content_writer import write_content
from agent.subagents.relevance_curator import curate
from agent.subagents.release_analyst import analyze_release
from agent.tools.image_tool import generate_image

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
    memory write-back (if featured) -> [feature_new/update_existing only:
    content_writer -> generate_image -> announcer, each failing gracefully:
    log and continue/skip rather than crash the webhook] -> save decision ->
    mark processed -> return.
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

    artifacts: dict = {}

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

        draft = None
        try:
            draft = write_content(profile, decision, memory.get_voice_profile())
        except Exception:
            logger.error(
                "content_writer failed for delivery=%s — no post package this run",
                delivery_id,
                exc_info=True,
            )

        if draft is not None:
            image_url = ""
            try:
                image_url = generate_image(draft.get("image_prompt", ""))
            except Exception:
                logger.error(
                    "image_tool failed for delivery=%s — continuing without an image",
                    delivery_id,
                    exc_info=True,
                )

            try:
                artifacts["post_package"] = assemble_post_package(draft, image_url)
            except Exception:
                logger.error(
                    "announcer failed for delivery=%s — no post package this run",
                    delivery_id,
                    exc_info=True,
                )

    record = {
        "repo": repo,
        "tag": event.get("tag", ""),
        **decision,
        "artifacts": artifacts,
        "self_review": None,
        "verified": None,
    }

    # decisions/{delivery_id} needs a real "ts" for the dashboard's
    # order_by("ts") queries (/api/decisions, /api/latest-post) to return it
    # at all — Firestore excludes documents missing an ordered field
    # entirely. SERVER_TIMESTAMP matches server.py's own idempotency-write
    # pattern, but it's a write-only sentinel: it can't go through
    # json.dumps() in the value this function returns to the caller, so the
    # Firestore write and the returned dict use two different "ts" values.
    memory.save_decision(delivery_id, {**record, "ts": firestore.SERVER_TIMESTAMP})
    memory.mark_delivery_processed(delivery_id)
    return {**record, "ts": datetime.now(timezone.utc).isoformat()}
