"""
LaunchPad-AI — Profile Bootstrapper (agent/subagents/profile_bootstrapper.py).

On the first release from a user with no context/profile in Firestore, this
module reads the dev's public GitHub signal (repos, bio), synthesizes a
lightweight profile via one Gemini 3.5 structured-output call, and persists
it to Firestore context/profile.  Every subsequent release reuses the
existing profile — no re-bootstrapping, no overwriting.

DESIGN: plain generate_content + response_schema (same pattern as
content_writer.py — NOT a new ADK agent).

SAFETY: the entire bootstrap is wrapped in try/except.  If GitHub or Gemini
fails, a safe DEFAULT_PROFILE is returned so the curator still runs and the
webhook never 500s.

Called from runner.py, EARLY — right after idempotency, BEFORE the
relevance_curator, because the curator consumes context/profile.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import requests
from pydantic import BaseModel

from agent import config, memory

logger = logging.getLogger(__name__)

DEFAULT_PROFILE: dict[str, Any] = {
    "interests": [],
    "primary_languages": [],
    "summary": "",
    "focus_areas": [],
}


class ProfileSchema(BaseModel):
    interests: list[str]
    primary_languages: list[str]
    summary: str
    focus_areas: list[str]


_BOOTSTRAPPER_INSTRUCTION = """\
You are a developer profile and technical domain synthesizer for LaunchPad-AI. \
Given a developer's public GitHub signal (their repos, descriptions, languages, topics, bio), \
produce a rich profile that captures who they are as a builder and architect.

Return structured output matching the schema:
- interests: 3-7 broad technical interests (e.g. "Distributed Systems", "AI Agents", "Cloud Infrastructure", "Full-Stack Engineering").
- primary_languages: the 3-5 programming languages they use most (e.g. "TypeScript", "Python", "JavaScript").
- summary: a 1-2 sentence description of this developer's engineering focus, technical domains, and builder style.
- focus_areas: 3-7 specific technical domains and conceptual capabilities they concentrate on \
  (e.g. "Event-Driven Telemetry", "Real-Time Observability", "LLM Orchestration", "Incident Management", "Cloud Deployments").

Base EVERYTHING on the concrete repos/bio provided. Capture rich conceptual domains and architectural capabilities, not just basic syntax keywords.
"""


def _fetch_github_signal(owner: str, token: str) -> dict[str, Any]:
    """Fetches the dev's public GitHub profile + top repos."""
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
    }

    # User bio
    user_resp = requests.get(
        f"https://api.github.com/users/{owner}",
        headers=headers,
        timeout=10,
    )
    user_resp.raise_for_status()
    user_data = user_resp.json()
    bio = user_data.get("bio") or ""

    # Top repos by recent push (cap at 15)
    repos_resp = requests.get(
        f"https://api.github.com/users/{owner}/repos",
        headers=headers,
        params={"sort": "pushed", "direction": "desc", "per_page": 15, "type": "owner"},
        timeout=10,
    )
    repos_resp.raise_for_status()

    repos = []
    for r in repos_resp.json():
        if r.get("fork"):
            continue
        repos.append({
            "name": r.get("name", ""),
            "description": r.get("description") or "",
            "language": r.get("language") or "",
            "topics": r.get("topics", []),
            "stars": r.get("stargazers_count", 0),
        })

    return {"bio": bio, "repos": repos}


def _synthesize_profile(github_signal: dict[str, Any]) -> dict[str, Any]:
    """One Gemini call to synthesize a profile from GitHub signal."""
    from google import genai
    from google.genai import types

    prompt = (
        "Synthesize a developer profile from this GitHub signal.\n\n"
        + json.dumps(github_signal, indent=2, default=str)
    )

    client = genai.Client()
    response = client.models.generate_content(
        model=config.GEMINI_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=_BOOTSTRAPPER_INSTRUCTION,
            response_mime_type="application/json",
            response_schema=ProfileSchema,
            temperature=0.3,
        ),
    )
    parsed = response.parsed
    if not isinstance(parsed, ProfileSchema):
        raise RuntimeError(f"profile bootstrapper returned unparseable output: {response.text!r}")
    return parsed.model_dump()


def ensure_profile(event: dict[str, Any]) -> dict[str, Any]:
    """Ensures context/profile exists in Firestore.

    - If profile already exists and is non-empty → returns it unchanged.
    - If missing/empty → bootstraps from GitHub + Gemini, writes to Firestore.
    - On ANY failure → returns DEFAULT_PROFILE (never blocks the pipeline).
    """
    try:
        existing = memory.get_context_profile()
        if existing:
            logger.info("context/profile already exists — skipping bootstrap")
            return existing

        logger.info("context/profile missing — bootstrapping from GitHub")

        # Extract owner from repo ("owner/name" → "owner")
        repo = event.get("repo", "")
        owner = repo.split("/")[0] if "/" in repo else repo

        token = event.get("_github_token", "")
        if not token:
            logger.warning("No GitHub token available — using default profile")
            return DEFAULT_PROFILE

        github_signal = _fetch_github_signal(owner, token)
        profile = _synthesize_profile(github_signal)

        memory.set_context_profile(profile)
        logger.info("context/profile bootstrapped and persisted for %s", owner)
        return profile

    except Exception:
        logger.error(
            "Profile bootstrap failed — returning default profile",
            exc_info=True,
        )
        return DEFAULT_PROFILE


def ensure_portfolio_projects(event: dict[str, Any]) -> None:
    """If a portfolio repo is connected, scans the portfolio source code (index.html,
    projects.json, etc.) to discover and register any already-featured projects into
    Firestore projects memory. This guarantees that legacy projects already present
    on the site are correctly curated as 'update_existing' rather than 'feature_new'.
    """
    try:
        portfolio_repo = config.get_portfolio_repo()
        if not portfolio_repo:
            return

        token = event.get("_github_token", "")
        if not token:
            return

        import re
        from agent.tools.github_tool import github_get_file, github_list_repo_shallow

        existing = memory.list_projects()
        indexed_repos = {p.get("repo") for p in existing if p.get("repo")}

        files = github_list_repo_shallow(portfolio_repo, token)
        candidate_files = [
            f for f in files
            if f.endswith((".html", ".json", ".jsx", ".tsx", ".astro", ".md", ".vue"))
        ]

        for fname in candidate_files[:4]:
            content = github_get_file(portfolio_repo, fname, token)
            if not content:
                continue

            matches = re.findall(r"github\.com/([a-zA-Z0-9_\-]+/[a-zA-Z0-9_\-]+)", content)
            for found_repo in set(matches):
                if found_repo.lower() == portfolio_repo.lower() or found_repo.endswith((".png", ".jpg", ".svg", ".gif")):
                    continue
                if found_repo not in indexed_repos:
                    memory.save_project(found_repo, {
                        "name": found_repo.split("/")[-1],
                        "status": "featured",
                        "portfolio_file": fname,
                        "source": "portfolio_scan",
                    })
                    indexed_repos.add(found_repo)
                    logger.info("Auto-indexed existing portfolio project %s from %s", found_repo, fname)

    except Exception:
        logger.warning("ensure_portfolio_projects failed gracefully", exc_info=True)

