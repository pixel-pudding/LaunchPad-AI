"""
LaunchPad-AI — Portfolio Publisher (agent/subagents/portfolio_publisher.py).

Opens a PR on the portfolio repo that adds or updates a project card in
projects.json — a single JSON array at the repo root. The target repo comes
from config.get_portfolio_repo(): Firestore config/portfolio (set via the
repo picker, POST /api/portfolio-config) wins, falling back to the
PORTFOLIO_REPO env var. If neither is set, publish() returns None and logs
at INFO — an expected "not configured yet" state, not a failure.

publish() returns {url, number, portfolio_repo} so runner.py's auto-merge
step targets the repo the PR actually lives on, not the source release
repo — those are two different repos and merging against the wrong one is
exactly the kind of bug this return shape exists to prevent.

Detection is against the ACTUAL file content, not decision["action"]: if an
entry for this repo already exists there, it's edited in place, never
duplicated — regardless of what the curator believed going in. Firestore's
projects/{repo} is then backfilled to match that ground truth, so a
stale/missing Firestore record can't cause a duplicate card on a later run.

publish() can raise (network/auth/GitHub API errors) — runner.py decides
how to degrade, matching content_writer/image_tool/self_reviewer. A failure
here must never touch artifacts.post_package, which is why this only ever
adds artifacts.portfolio_pr and never rewrites keys other steps own.

publish() returns {url, number} rather than a bare URL string, so runner.py
can auto-merge this exact PR afterward (see runner.py) without needing a
second API round-trip to look the number up. The PR number is parsed off
the URL github_open_pr already returns rather than changing that function's
return type, since github_open_pr's `-> str` signature is part of the
frozen CLAUDE.md contract.

Alongside the project card, publish() also merges this release's real
stack/languages into skills.json — a flat JSON array at the portfolio
repo's root — in the SAME PR (github_open_pr already commits every path in
its `files` dict onto one branch before opening one PR, so this needs no
second PR and no tool changes). The skills update is best-effort and
wrapped in its own try/except: a failure there can only mean skills.json is
left out of this PR, never that the project card or the PR itself is lost.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from agent import config, memory
from agent.tools.github_tool import github_get_file, github_open_pr

logger = logging.getLogger(__name__)

_PROJECTS_FILE = "projects.json"
_SKILLS_FILE = "skills.json"

# Deterministic display casing for common terms .title() gets wrong
# (acronyms, internal capitals) — NOT an LLM call. Only re-cases real
# stack entries; never invents or expands the skill list itself.
_KNOWN_SKILL_CASING = {
    "python": "Python",
    "dockerfile": "Dockerfile",
    "javascript": "JavaScript",
    "typescript": "TypeScript",
    "fastapi": "FastAPI",
    "css": "CSS",
    "html": "HTML",
    "api": "API",
    "sql": "SQL",
}


def _get_portfolio_repo() -> str | None:
    return config.get_portfolio_repo()


def _load_projects(portfolio_repo: str) -> list[dict[str, Any]]:
    content = github_get_file(portfolio_repo, _PROJECTS_FILE)
    if content is None:
        return []
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        logger.error("%s in %s is not valid JSON — treating as empty", _PROJECTS_FILE, portfolio_repo)
        return []
    return data if isinstance(data, list) else []


def _load_skills(portfolio_repo: str) -> list[str]:
    content = github_get_file(portfolio_repo, _SKILLS_FILE)
    if content is None:
        return []
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        logger.error("%s in %s is not valid JSON — treating as empty", _SKILLS_FILE, portfolio_repo)
        return []
    return data if isinstance(data, list) else []


def _display_case(skill: str) -> str:
    """Known-term map first, .title() fallback otherwise."""
    return _KNOWN_SKILL_CASING.get(skill.strip().lower(), skill.strip().title())


def _merge_skills(existing: list[str], candidates: list[str]) -> list[str] | None:
    """Case-insensitive merge of `candidates` into `existing`. Returns None
    if nothing new — signals the caller to leave skills.json out of the PR
    entirely rather than open a no-op change. Casing is applied only to
    newly-added entries; pre-existing entries are left exactly as they are.
    """
    seen_lower = {s.lower() for s in existing if isinstance(s, str)}
    new_skills = []
    for candidate in candidates:
        if not isinstance(candidate, str) or not candidate.strip():
            continue
        key = candidate.strip().lower()
        if key not in seen_lower:
            new_skills.append(_display_case(candidate))
            seen_lower.add(key)
    return [*existing, *new_skills] if new_skills else None


def _build_card(
    repo: str,
    profile: dict[str, Any],
    decision: dict[str, Any],
    post_package: dict[str, Any],
    now_iso: str,
) -> dict[str, Any]:
    return {
        "repo": repo,
        "name": profile.get("name", ""),
        "summary": profile.get("summary", ""),
        "stack": profile.get("stack", []),
        "positioning": decision.get("positioning", ""),
        "image_url": post_package.get("image_url", ""),
        "url": f"https://github.com/{repo}",
        "updated_at": now_iso,
    }


def _parse_pr_number(pr_url: str) -> int:
    """Extracts the PR number from a GitHub PR URL (.../pull/{number})."""
    return int(pr_url.rstrip("/").rsplit("/", 1)[-1])


def publish(
    repo: str,
    profile: dict[str, Any],
    decision: dict[str, Any],
    post_package: dict[str, Any],
    delivery_id: str,
) -> dict[str, Any] | None:
    """Adds or edits this repo's card in the portfolio repo's projects.json,
    opens a PR, backfills Firestore, and returns {url, number, portfolio_repo}.

    Returns None — logged at INFO, not an error — if no portfolio repo is
    configured (Firestore config/portfolio and the PORTFOLIO_REPO env var
    are both absent). That's an expected state for a user who hasn't set up
    the picker yet, not a failure; real GitHub/network errors still raise.
    """
    portfolio_repo = _get_portfolio_repo()
    if portfolio_repo is None:
        logger.info("No portfolio configured for %s — skipping portfolio publish", repo)
        return None

    now_iso = datetime.now(timezone.utc).isoformat()
    card = _build_card(repo, profile, decision, post_package, now_iso)

    projects = _load_projects(portfolio_repo)
    existing_index = next((i for i, entry in enumerate(projects) if entry.get("repo") == repo), None)

    if existing_index is not None:
        projects[existing_index] = card
        verb = "update"
    else:
        projects.append(card)
        verb = "add"

    files = {_PROJECTS_FILE: json.dumps(projects, indent=2) + "\n"}

    # Best-effort: a failure here must never cost the project card or the
    # PR. Deliberately NOT wrapped together with github_open_pr below,
    # which should still raise normally on its own failures (unchanged,
    # caught by runner.py as today).
    try:
        existing_skills = _load_skills(portfolio_repo)
        merged_skills = _merge_skills(existing_skills, profile.get("stack", []))
        if merged_skills is not None:
            files[_SKILLS_FILE] = json.dumps(merged_skills, indent=2) + "\n"
    except Exception:
        logger.error(
            "skills.json update failed for %s — continuing with the project card only",
            repo,
            exc_info=True,
        )

    branch = f"launchpad-ai/{delivery_id}"
    title = f"LaunchPad-AI: {verb} {profile.get('name', repo)}"
    body = decision.get("positioning") or f"Automated {verb} for {repo}."

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

    return {"url": pr_url, "number": _parse_pr_number(pr_url), "portfolio_repo": portfolio_repo}
