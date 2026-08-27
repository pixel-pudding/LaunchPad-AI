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

from agent import config, memory
from agent.subagents.announcer import assemble_post_package
from agent.subagents.content_writer import write_content
from agent.subagents.next_build_suggester import suggest_next_builds
from agent.subagents.portfolio_publisher import publish as publish_to_portfolio
from agent.subagents.relevance_curator import curate
from agent.subagents.release_analyst import analyze_release
from agent.subagents.self_reviewer import review as run_self_review
from agent.tools.github_tool import github_merge_pr
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
    is an independent artifact; returns None, not an error, if no portfolio
    repo is configured yet via config.get_portfolio_repo(); internally picks
    the convention path (root projects.json) or the Tier 2 arbitrary-repo
    path — see portfolio_publisher.py — and reports which one ran via
    pr["mode"]) -> auto-merge the PR just opened, on the repo it was
    actually opened on, ONLY if pr["mode"] == "convention" (own try/except,
    gated by config.get_portfolio_auto_merge(); Tier 2 PRs never auto-merge
    regardless of that setting, and a merge failure leaves the PR open
    rather than losing it) -> next_build_suggester (a pure, secondary
    byproduct — reads only already-fetched memory, writes only its own
    artifacts key, never influences the decision/post/PR),
    each failing gracefully: log and continue/skip rather than crash the
    webhook] -> save decision -> mark processed -> return.
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

    # Auto-bootstrap profile from GitHub if missing (before curator runs,
    # because the curator consumes context/profile).
    from agent.subagents.profile_bootstrapper import ensure_profile

    ensure_profile(event)

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
                try:
                    image_url = generate_image(draft.get("image_prompt", ""), repo=repo, profile=profile)
                except TypeError:
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

        pr_number = None
        pr_repo = None
        pr_mode = None
        pr_auto_merge_suppressed = False
        try:
            pr = publish_to_portfolio(
                repo, profile, decision, artifacts.get("post_package", {}), delivery_id, event.get("tag", "")
            )
            # publish() returns None (not an exception) when no portfolio
            # repo is configured yet — an expected state, already logged
            # at INFO inside portfolio_publisher. Nothing to merge either.
            # This covers BOTH paths inside publish() (convention and Tier
            # 2 arbitrary) — a failure or a None in either one is handled
            # identically here; pr["mode"] is what tells them apart below.
            if pr is not None:
                artifacts["portfolio_pr"] = pr["url"]
                artifacts["portfolio_mode"] = pr["mode"]
                pr_number = pr["number"]
                pr_repo = pr["portfolio_repo"]
                pr_mode = pr["mode"]
                pr_auto_merge_suppressed = pr.get("auto_merge_suppressed", False)
        except Exception:
            logger.error(
                "portfolio_publisher failed for delivery=%s — post package (if any) is unaffected",
                delivery_id,
                exc_info=True,
            )

        # Separate try/except from opening the PR above: opening and
        # merging are independent outcomes. A merge failure (branch
        # protection, conflicts, permissions) must never lose the
        # already-open PR or the post_package built earlier. Only ever
        # merges the exact PR this run just opened, on the repo it was
        # actually opened on (pr_repo — the portfolio repo, NOT `repo`,
        # which is the source release repo the webhook fired for) —
        # never looks up or touches any other PR.
        #
        # HARD INVARIANT: Tier 2 arbitrary-repo PRs (pr_mode in
        # "arbitrary_high"/"arbitrary_low") NEVER auto-merge, regardless of
        # config.get_portfolio_auto_merge() — they either edit unreviewed
        # site code or drop content nobody's placed yet, and always need a
        # human look. The convention path is ALSO suppressed for exactly
        # one case: its own first (bootstrap) write when format was never
        # explicitly confirmed via the picker (see portfolio_publisher.py's
        # confidence check) — pr["auto_merge_suppressed"] carries that
        # signal the same way Tier 2 always sets it.
        if pr_number is not None:
            artifacts["portfolio_pr_merged"] = False
            if not pr_auto_merge_suppressed and config.get_portfolio_auto_merge():
                try:
                    merge_result = github_merge_pr(pr_repo, pr_number)
                    artifacts["portfolio_pr_merged"] = merge_result["merged"]
                    artifacts["portfolio_pr_sha"] = merge_result["sha"]
                except Exception:
                    logger.error(
                        "auto-merge failed for delivery=%s — PR left open for manual merge",
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
