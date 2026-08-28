"""
LaunchPad-AI — Agent runner (the seam).

This module is OWNED BY Claude Code [CC]. [AG] calls run_agent() from
the /process route but NEVER modifies this file's signature.

The seam signature is frozen (CLAUDE.md / WORK_SPLIT.md §1) and must not change.
"""

from __future__ import annotations

import logging
import time
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

    start_time = time.time()
    started_at_iso = datetime.now(timezone.utc).isoformat()
    logger.info(
        "Ingesting release for repo=%s tag=%s delivery_id=%s",
        repo,
        event.get("tag"),
        delivery_id,
    )

    try:
        memory.set_agent_status({
            "status": "running",
            "stage": 1,
            "stage_name": "Webhook Received",
            "repo": repo,
            "tag": event.get("tag", ""),
            "delivery_id": delivery_id,
            "started_at": started_at_iso,
        })
    except Exception:
        pass

    # Auto-bootstrap profile from GitHub if missing (before curator runs,
    # because the curator consumes context/profile).
    from agent.subagents.profile_bootstrapper import ensure_profile

    ensure_profile(event)

    try:
        time.sleep(0.4)
        memory.set_agent_status({
            "status": "running",
            "stage": 2,
            "stage_name": "Profiling Repo",
            "repo": repo,
            "tag": event.get("tag", ""),
            "delivery_id": delivery_id,
            "started_at": started_at_iso,
        })
    except Exception:
        pass

    profile = analyze_release(event)

    memory_context = {
        "featured_projects": memory.list_projects(),
        "context_profile": memory.get_context_profile(),
    }

    try:
        time.sleep(0.4)
        memory.set_agent_status({
            "status": "running",
            "stage": 3,
            "stage_name": "Gemini 3.5 Deciding",
            "repo": repo,
            "tag": event.get("tag", ""),
            "delivery_id": delivery_id,
            "started_at": started_at_iso,
        })
    except Exception:
        pass

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

        try:
            time.sleep(0.4)
            memory.set_agent_status({
                "status": "running",
                "stage": 4,
                "stage_name": "Staging LinkedIn Post & Image",
                "repo": repo,
                "tag": event.get("tag", ""),
                "delivery_id": delivery_id,
                "started_at": started_at_iso,
            })
        except Exception:
            pass

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

        try:
            time.sleep(0.4)
            memory.set_agent_status({
                "status": "running",
                "stage": 5,
                "stage_name": "Splicing Codebase",
                "repo": repo,
                "tag": event.get("tag", ""),
                "delivery_id": delivery_id,
                "started_at": started_at_iso,
            })
        except Exception:
            pass

        pr_number = None
        pr_repo = None
        pr_mode = None
        pr_auto_merge_suppressed = False
        try:
            pr = publish_to_portfolio(
                repo, profile, decision, artifacts.get("post_package", {}), delivery_id, event.get("tag", "")
            )
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

        if pr_number is not None:
            artifacts["portfolio_pr_merged"] = False
            if not pr_auto_merge_suppressed and config.get_portfolio_auto_merge():
                try:
                    time.sleep(0.4)
                    memory.set_agent_status({
                        "status": "running",
                        "stage": 6,
                        "stage_name": "Auto-Merging PR",
                        "repo": repo,
                        "tag": event.get("tag", ""),
                        "delivery_id": delivery_id,
                        "started_at": started_at_iso,
                    })
                except Exception:
                    pass
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

        # Pure byproduct, last step
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

    memory.save_decision(delivery_id, {**record, "ts": firestore.SERVER_TIMESTAMP})
    memory.mark_delivery_processed(delivery_id)

    total_seconds = round(time.time() - start_time, 1)
    try:
        memory.set_agent_status({
            "status": "idle",
            "stage": 6,
            "stage_name": "Completed",
            "repo": repo,
            "tag": event.get("tag", ""),
            "last_delivery_id": delivery_id,
            "action": decision["action"],
            "started_at": started_at_iso,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "duration_seconds": total_seconds,
        })
    except Exception:
        pass

    return {**record, "ts": datetime.now(timezone.utc).isoformat()}
