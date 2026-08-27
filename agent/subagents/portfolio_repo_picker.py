"""
LaunchPad-AI — Portfolio Repo Picker (agent/subagents/portfolio_repo_picker.py).

Lists the repos the GitHub App installation can access and picks ONE best
guess for "which of these is probably the user's portfolio site" — a
suggestion the user confirms via POST /api/portfolio-config, never an
automatic choice. Deterministic heuristics only, no LLM call: this is a
simple, explainable pre-select, not a judgment worth a model call.

Priority order (stops at the first match across the whole repo list):
  1. name == "<owner>.github.io" (GitHub Pages' own convention)
  2. name is one of a handful of common portfolio-repo names
  3. the repo has an index.html at its root
If nothing matches any tier, every entry has is_probable_portfolio=False —
the user picks manually.

list_candidate_repos() can raise (network/auth/GitHub API errors) — the
caller (server.py's /api/repos) decides how to degrade (empty list + an
error field), matching the rest of this codebase's subagent functions.
"""

from __future__ import annotations

from typing import Any

from agent.tools.github_tool import github_get_file, github_list_installation_repos

_PORTFOLIO_NAME_CANDIDATES = {
    "portfolio",
    "personal-site",
    "personal-website",
    "website",
    "my-portfolio",
}


def _is_github_io_repo(full_name: str, name: str) -> bool:
    owner = full_name.split("/", 1)[0] if "/" in full_name else ""
    return bool(owner) and name.lower() == f"{owner}.github.io".lower()


def list_candidate_repos() -> list[dict[str, Any]]:
    """Returns [{full_name, name, is_probable_portfolio}] for every repo the
    installation can access. At most ONE entry has is_probable_portfolio=True.
    """
    repos = github_list_installation_repos()
    candidates = [
        {"full_name": r["full_name"], "name": r["name"], "is_probable_portfolio": False}
        for r in repos
    ]

    for c in candidates:
        if _is_github_io_repo(c["full_name"], c["name"]):
            c["is_probable_portfolio"] = True
            return candidates

    for c in candidates:
        if c["name"].lower() in _PORTFOLIO_NAME_CANDIDATES:
            c["is_probable_portfolio"] = True
            return candidates

    for c in candidates:
        try:
            if github_get_file(c["full_name"], "index.html") is not None:
                c["is_probable_portfolio"] = True
                return candidates
        except Exception:
            continue

    return candidates
