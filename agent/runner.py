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
from agent.subagents.next_build_suggester import suggest_next_builds
from agent.subagents.portfolio_publisher import publish as publish_to_portfolio
from agent.subagents.relevance_curator import curate
from agent.subagents.release_analyst import analyze_release
from agent.subagents.self_reviewer import review as run_self_review
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
    content_writer -> generate_image -> announcer -> self_reviewer (only if
    a post_package exists to review) -> portfolio_publisher (runs
    regardless of whether the post pipeline succeeded — the portfolio card
    is an independent artifact) -> next_build_suggester (a pure, secondary
    byproduct — reads only already-fetched memory, writes only its own
    artifacts key, never influences the decision/post/PR), each failing
    gracefully: log and continue/skip rather than crash the webhook] ->
    save decision -> mark processed -> return.
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
    self_review_outcome = None

    if decision["action"] in ("feature_new", "update_existing"):
        # Safety-net write: even if everything below fails, Firestore still
        # learns this repo is featured, so the curator won't repeat
        # feature_new next time. portfolio_publisher below overwrites this
        # with a richer record when it succeeds.
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

        if artifacts.get("post_package"):
            try:
                revised_package, self_review_outcome = run_self_review(
                    artifacts["post_package"], profile, decision, memory.get_voice_profile()
                )
                artifacts["post_package"] = revised_package
            except Exception:
                logger.error(
                    "self_reviewer failed for delivery=%s — keeping the unreviewed post package",
                    delivery_id,
                    exc_info=True,
                )

        try:
            artifacts["portfolio_pr"] = publish_to_portfolio(
                repo, profile, decision, artifacts.get("post_package", {}), delivery_id
            )
        except Exception:
            logger.error(
                "portfolio_publisher failed for delivery=%s — post package (if any) is unaffected",
                delivery_id,
                exc_info=True,
            )

        # Pure byproduct, last step: reads only the already-fetched
        # memory_context, writes only its own artifacts key. A failure here
        # cannot touch the decision, post_package, or portfolio_pr above.
        try:
            artifacts["next_builds"] = suggest_next_builds(
                memory_context["featured_projects"], memory_context["context_profile"]
            )
        except Exception:
            logger.error(
                "next_build_suggester failed for delivery=%s — continuing without suggestions",
                delivery_id,
                exc_info=True,
            )

    record = {
        "repo": repo,
        "tag": event.get("tag", ""),
        **decision,
        "artifacts": artifacts,
        "self_review": self_review_outcome,
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
