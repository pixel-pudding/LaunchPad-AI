"""
LaunchPad-AI — Portfolio Publisher (agent/subagents/portfolio_publisher.py).

Opens a PR on the target portfolio repository that directly adds or updates a project entry
in the repository's native format (index.html, React/Next.js components, Astro markdown, etc.).

No convention JSON files are used. The agent automatically detects the site's structure,
splicing the new project card directly into the codebase.

Auto-merge behavior is directly controlled by config.get_portfolio_auto_merge():
  - If Auto-Merge is ON: The PR is automatically merged immediately.
  - If Auto-Merge is OFF: The PR is opened for manual 1-click review on GitHub.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from agent import config, memory
from agent.subagents.portfolio_structure_detector import detect_structure, generate_format_matched_file
from agent.tools.github_tool import github_open_pr

logger = logging.getLogger(__name__)


def _get_portfolio_repo() -> str | None:
    return config.get_portfolio_repo()


def _parse_pr_number(pr_url: str) -> int:
    """Extracts the PR number from a GitHub PR URL (.../pull/{number})."""
    return int(pr_url.rstrip("/").rsplit("/", 1)[-1])


def _build_standalone_markdown(
    repo: str, profile: dict[str, Any], decision: dict[str, Any], post_package: dict[str, Any]
) -> str:
    name = profile.get("name") or repo
    description = profile.get("summary") or post_package.get("text", "")
    stack = ", ".join(profile.get("stack", [])) or "—"
    demo_url = profile.get("demo_url", "")
    demo_line = f"**Live Demo:** {demo_url}\n\n" if demo_url else ""
    return (
        f"# {name}\n\n"
        f"{description}\n\n"
        f"**Stack:** {stack}\n\n"
        f"{demo_line}"
        f"**GitHub:** https://github.com/{repo}\n\n"
        "*Prepared automatically by LaunchPad-AI — place this content wherever "
        "your portfolio's project section lives.*\n"
    )


def publish(
    repo: str,
    profile: dict[str, Any],
    decision: dict[str, Any],
    post_package: dict[str, Any],
    delivery_id: str,
    tag: str = "",
) -> dict[str, Any] | None:
    """Publishes to the portfolio repository by detecting its native framework
    and updating the source code directly.
    """
    portfolio_repo = _get_portfolio_repo()
    if portfolio_repo is None:
        logger.info("No portfolio configured for %s — skipping portfolio publish", repo)
        return None

    now_iso = datetime.now(timezone.utc).isoformat()
    detection = detect_structure(portfolio_repo)
    branch = f"launchpad-ai/{delivery_id}"

    if detection["confidence"] == "high":
        location = detection["projects_location"]
        edited_content = generate_format_matched_file(
            portfolio_repo, location, profile, decision, post_package, repo
        )
        title = f"LaunchPad-AI: add {profile.get('name', repo)} to {location['file_path']}"
        body = (
            f"LaunchPad-AI detected your projects in `{location['file_path']}` "
            f"({location['format']}) and prepared this update.\n\n"
            f"Positioning: {decision.get('positioning', '')}"
        )
        files = {location["file_path"]: edited_content}
        mode = "arbitrary_high"
    else:
        repo_slug = repo.replace("/", "-")
        content_path = f"launchpad-ai/{repo_slug}-{tag or delivery_id}.md"
        title = f"LaunchPad-AI: prepared content for {profile.get('name', repo)}"
        body = (
            "LaunchPad-AI couldn't confidently locate where projects live in "
            "this repo, so it prepared the content here for you to place "
            "manually. Nothing in your existing site was changed."
        )
        files = {content_path: _build_standalone_markdown(repo, profile, decision, post_package)}
        mode = "arbitrary_low"

    pr_url = github_open_pr(portfolio_repo, branch, title, body, files)

    memory.upsert_project(
        repo,
        {
            "repo": repo,
            "name": profile.get("name", ""),
            "summary": profile.get("summary", ""),
            "stack": profile.get("stack", []),
            "skill_tags": profile.get("skill_tags", []),
            "status": "featured",
            "portfolio_url": pr_url,
            "published_at": now_iso,
        },
    )

    should_auto_merge = config.get_portfolio_auto_merge()

    return {
        "mode": mode,
        "url": pr_url,
        "number": _parse_pr_number(pr_url),
        "portfolio_repo": portfolio_repo,
        "auto_merge_suppressed": not should_auto_merge,
    }
