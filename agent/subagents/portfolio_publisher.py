"""
LaunchPad-AI — Portfolio Publisher (agent/subagents/portfolio_publisher.py).

Opens a PR on the portfolio repo that adds or updates a project entry. The
target repo comes from config.get_portfolio_repo(): Firestore
config/portfolio (set via the repo picker) wins, falling back to the
PORTFOLIO_REPO env var. If neither is set, publish() returns None and logs
at INFO — an expected "not configured yet" state, not a failure.

TWO PATHS, chosen by config.get_portfolio_format() — NOT by whether
projects.json currently exists. File existence alone can't tell "this repo
doesn't use the convention" apart from "this repo uses the convention but
hasn't had its first card written yet" — both look identical (file absent)
from GitHub's side. get_portfolio_format() defaults to "convention" unless
the picker explicitly set "arbitrary", so an unconfigured convention repo
still bootstraps correctly instead of being misread as arbitrary-format.

- CONVENTION (the default; unchanged from before Tier 2 existed, EXCEPT
  for one new safety rule below): edit projects.json + skills.json in one
  PR. Detection of an existing card is against the ACTUAL file content,
  not decision["action"] — ground truth wins over a possibly-stale curator
  belief. Returns {"mode": "convention", "url", "number", "portfolio_repo"}.

  Auto-merge confidence: a repo whose projects.json doesn't exist yet
  (is_bootstrap) is only trusted with auto-merge if the picker EXPLICITLY
  set format="convention" — a merely-defaulted format on a never-written
  repo is a guess, not evidence. That specific combination sets
  "auto_merge_suppressed": True and opens a review PR instead; every
  release after the first is merged (projects.json now exists,
  is_bootstrap=False) auto-merges normally regardless of the format field.

- ARBITRARY (Tier 2): only when format is explicitly "arbitrary" ->
  agent/subagents/portfolio_structure_detector.py figures out (read-only)
  whether a project list exists elsewhere in a recognizable format. High
  confidence -> a format-matched edit to that file. Low confidence -> a
  brand-new standalone markdown file at launchpad-ai/<repo>-<tag>.md;
  nothing existing is touched. Both open a review-only PR and always set
  auto_merge_suppressed=True — see runner.py, which enforces that
  arbitrary-mode PRs are NEVER auto-merged regardless of config, since
  they either edit unreviewed site code or drop unplaced content. Returns
  {"mode": "arbitrary_high" | "arbitrary_low", "url", "number",
  "portfolio_repo", "auto_merge_suppressed": True}.

publish() can raise (network/auth/GitHub/Gemini errors) — runner.py decides
how to degrade, matching content_writer/image_tool/self_reviewer. A failure
here — in EITHER path — must never touch artifacts.post_package, which is
why this only ever adds its own artifacts keys and never rewrites keys
other steps own.

publish() returns {..., "url", "number", "portfolio_repo"} rather than a
bare URL string, so runner.py's auto-merge step targets the repo the PR
actually lives on, not the source release repo — those are two different
repos and merging against the wrong one is exactly the kind of bug this
return shape exists to prevent.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from agent import config, memory
from agent.subagents.portfolio_structure_detector import detect_structure, generate_format_matched_file
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


def _parse_projects(content: str | None) -> list[dict[str, Any]]:
    if content is None:
        return []
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        logger.error("%s is not valid JSON — treating as empty", _PROJECTS_FILE)
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


def _build_standalone_markdown(
    repo: str, profile: dict[str, Any], decision: dict[str, Any], post_package: dict[str, Any]
) -> str:
    """Deterministic template, no Gemini call — content_writer/announcer
    already produced real, voice-matched text (post_package["text"]) and a
    real summary (profile["summary"]); this just lays out data we already
    have as plain markdown. A third LLM call to reformat data we already
    have would add cost and latency for no real benefit."""
    name = profile.get("name") or repo
    description = profile.get("summary") or post_package.get("text", "")
    stack = ", ".join(profile.get("stack", [])) or "—"
    return (
        f"# {name}\n\n"
        f"{description}\n\n"
        f"**Stack:** {stack}\n\n"
        f"**Link:** https://github.com/{repo}\n\n"
        "*Prepared automatically by LaunchPad-AI — place this content wherever "
        "your portfolio's project section lives.*\n"
    )


def _parse_pr_number(pr_url: str) -> int:
    """Extracts the PR number from a GitHub PR URL (.../pull/{number})."""
    return int(pr_url.rstrip("/").rsplit("/", 1)[-1])


def _publish_convention(
    repo: str,
    profile: dict[str, Any],
    decision: dict[str, Any],
    post_package: dict[str, Any],
    delivery_id: str,
    portfolio_repo: str,
    now_iso: str,
    projects_content: str,
) -> dict[str, Any]:
    """The original, UNCHANGED convention-repo path: edit projects.json (+
    skills.json best-effort) in one PR, auto-merge per config. This is the
    pre-Tier-2 publish() body, extracted verbatim — same behavior, same
    auto-merge eligibility, untouched by Tier 2's existence.
    """
    card = _build_card(repo, profile, decision, post_package, now_iso)
    projects = _parse_projects(projects_content)
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

    # Auto-merge confidence: real evidence this repo genuinely follows the
    # convention (a card was already written before) or an explicit
    # picker confirmation both count. A merely-defaulted format on a repo
    # that has never had projects.json written to it is a GUESS, not
    # evidence — that specific combination gets a review PR instead, even
    # though the edit itself is identical. Once this first write is merged
    # and projects.json exists, every later release is_bootstrap=False and
    # auto-merges normally regardless of the format field.
    is_bootstrap = projects_content is None
    confident = (not is_bootstrap) or (config.get_portfolio_format_explicit() == "convention")

    if is_bootstrap and not confident:
        body = (
            (decision.get("positioning") or f"Automated {verb} for {repo}.")
            + "\n\nThis is the first project card LaunchPad-AI has written to this "
            "repo — review before merging. Once merged, future releases will "
            "auto-merge automatically."
        )
    else:
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

    result: dict[str, Any] = {
        "mode": "convention",
        "url": pr_url,
        "number": _parse_pr_number(pr_url),
        "portfolio_repo": portfolio_repo,
    }
    if not confident:
        result["auto_merge_suppressed"] = True
    return result


def _publish_arbitrary(
    repo: str,
    profile: dict[str, Any],
    decision: dict[str, Any],
    post_package: dict[str, Any],
    delivery_id: str,
    tag: str,
    portfolio_repo: str,
) -> dict[str, Any]:
    """Tier 2: this portfolio repo doesn't follow the projects.json
    convention. detect_structure() is read-only; this function is what
    actually writes, via exactly one github_open_pr call, matching the
    convention path's shape (one PR either way). NEVER auto-merges — see
    runner.py, which additionally enforces this via pr["mode"] regardless
    of config, since these PRs edit unreviewed site code (high confidence)
    or drop content nobody's placed yet (low confidence).
    """
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
            f"({location['format']}) and prepared this update. Review before "
            "merging — this edits your site's code."
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

    return {
        "mode": mode,
        "url": pr_url,
        "number": _parse_pr_number(pr_url),
        "portfolio_repo": portfolio_repo,
        "auto_merge_suppressed": True,
    }


def publish(
    repo: str,
    profile: dict[str, Any],
    decision: dict[str, Any],
    post_package: dict[str, Any],
    delivery_id: str,
    tag: str = "",
) -> dict[str, Any] | None:
    """Publishes to the portfolio repo via whichever path fits it — see
    module docstring. Returns None (logged at INFO, not an error) if no
    portfolio repo is configured at all. May raise on real GitHub/Gemini
    failures in either path; runner.py decides how to degrade.
    """
    portfolio_repo = _get_portfolio_repo()
    if portfolio_repo is None:
        logger.info("No portfolio configured for %s — skipping portfolio publish", repo)
        return None

    now_iso = datetime.now(timezone.utc).isoformat()

    # Routing keys off the RESOLVED format, not file existence. File
    # existence alone can't tell "this repo doesn't use the convention"
    # apart from "this repo uses the convention but hasn't had its first
    # card written yet" — both look identical (projects.json absent) from
    # GitHub's side. config.get_portfolio_format() defaults to
    # "convention" unless the picker explicitly set "arbitrary", so an
    # unconfigured convention repo (e.g. a fresh demo repo) still bootstraps
    # correctly instead of being misread as an arbitrary-format site.
    if config.get_portfolio_format() == "convention":
        projects_content = github_get_file(portfolio_repo, _PROJECTS_FILE)
        return _publish_convention(
            repo, profile, decision, post_package, delivery_id, portfolio_repo, now_iso, projects_content
        )

    return _publish_arbitrary(repo, profile, decision, post_package, delivery_id, tag, portfolio_repo)
