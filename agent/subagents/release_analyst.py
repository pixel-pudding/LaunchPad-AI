"""
LaunchPad-AI — Release Analyst (agent/subagents/release_analyst.py).

Given a release event, fetches the repo via github_tool and derives a project
profile. Deterministic on purpose (no LLM call here) so it's testable against
a recorded fixture with no live network calls.
"""

from __future__ import annotations

from typing import Any

from agent.tools.github_tool import github_get_repo

_MARKER_TAGS = {
    "Dockerfile": "docker",
    "docker-compose.yml": "docker",
    ".github": "ci-cd",
    "pyproject.toml": "python-packaging",
    "package.json": "node",
}


def analyze_release(event: dict[str, Any]) -> dict[str, Any]:
    """Returns a project profile: {name, summary, stack, skill_tags, readme, images[], release_notes, tag}."""
    repo_data = github_get_repo(event.get("repo", ""))
    profile = build_profile(repo_data)
    profile["tag"] = event.get("tag", "")
    profile["release_name"] = event.get("release_name", "")
    profile["release_notes"] = event.get("release_body") or event.get("release_notes") or ""
    return profile


import re


_TECH_KEYWORD_MAP = {
    r"\breact(?:\.js|js)?\b": "React",
    r"\bnext(?:\.js|js)?\b": "Next.js",
    r"\bvue(?:\.js|js)?\b": "Vue",
    r"\bangular\b": "Angular",
    r"\bsvelte\b": "Svelte",
    r"\bfastapi\b": "FastAPI",
    r"\bflask\b": "Flask",
    r"\bdjango\b": "Django",
    r"\bexpress(?:\.js)?\b": "Express",
    r"\bnode(?:\.js)?\b": "Node.js",
    r"\btailwind(?:css)?\b": "Tailwind CSS",
    r"\bprisma\b": "Prisma",
    r"\bmongodb\b": "MongoDB",
    r"\bpostgres(?:ql)?\b": "PostgreSQL",
    r"\bredis\b": "Redis",
    r"\bgraphql\b": "GraphQL",
    r"\bwebsocket(?:s)?\b": "WebSockets",
    r"\bopentelemetry\b": "OpenTelemetry",
    r"\bdocker\b": "docker",
    r"\bgemini\b": "Gemini",
    r"\bllm(?:s)?\b": "LLMs",
    r"\bast\b": "AST",
    r"\bjwt\b": "JWT",
    r"\bzero-backend\b": "Zero-Backend",
    r"\btelemetry\b": "Telemetry",
}


def build_profile(repo_data: dict[str, Any]) -> dict[str, Any]:
    """Pure mapping from raw github_get_repo() output to the profile shape."""
    langs = repo_data.get("langs", [])
    tree = repo_data.get("tree", [])
    readme = repo_data.get("readme", "")
    description = repo_data.get("description") or ""

    return {
        "name": repo_data.get("name", ""),
        "summary": _derive_summary(repo_data),
        "demo_url": _derive_demo_url(repo_data),
        "stack": [lang.lower() for lang in langs],
        "skill_tags": _derive_skill_tags(langs, tree, readme=readme, description=description),
        "readme": readme,
        "images": repo_data.get("images", []),
    }


def _derive_demo_url(repo_data: dict[str, Any]) -> str:
    homepage = repo_data.get("homepage", "")
    if homepage and homepage.startswith("http"):
        return homepage.strip()
    readme = repo_data.get("readme", "")
    match = re.search(
        r"(?:live demo|demo|live site|deployment|app|website|live|preview):\s*(https?://[^\s)\]]+)",
        readme,
        re.IGNORECASE,
    )
    if match:
        return match.group(1).strip()
    return ""


def _derive_summary(repo_data: dict[str, Any]) -> str:
    description = repo_data.get("description") or ""
    if description:
        return description
    for line in repo_data.get("readme", "").splitlines():
        stripped = line.strip().lstrip("#").strip()
        if stripped:
            return stripped
    return ""


def _derive_skill_tags(
    langs: list[str], tree: list[str], readme: str = "", description: str = ""
) -> list[str]:
    tags = {lang.lower() for lang in langs}
    for entry in tree:
        tag = _MARKER_TAGS.get(entry)
        if tag:
            tags.add(tag)

    combined_text = f"{description}\n{readme}".lower()
    for pattern, label in _TECH_KEYWORD_MAP.items():
        if re.search(pattern, combined_text):
            tags.add(label)

    return sorted(tags)
