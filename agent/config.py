"""
LaunchPad-AI — startup config + loud guardrails (agent/config.py).

Enforces two non-negotiable stack facts from CLAUDE.md:
  - the model must be Gemini 3.5 or newer — never 2.x
  - it must run on Vertex AI, not the public Gemini API

Both are checked at import time (module-level, not inside a function), so a
bad .env fails the process on startup instead of silently degrading into a
worse model or the wrong backend.
"""

from __future__ import annotations

import os
import re

MIN_GEMINI_VERSION = (3, 5)
_VERSION_RE = re.compile(r"^gemini-(\d+)\.(\d+)")


def check_model_version(model: str) -> None:
    """Raises RuntimeError unless `model` is a versioned Gemini model >= MIN_GEMINI_VERSION."""
    match = _VERSION_RE.match(model)
    if not match:
        raise RuntimeError(
            f"GEMINI_MODEL={model!r} doesn't look like a versioned Gemini model "
            "(expected e.g. 'gemini-3.5-flash'). Refusing to guess — set it explicitly."
        )
    version = (int(match.group(1)), int(match.group(2)))
    if version < MIN_GEMINI_VERSION:
        raise RuntimeError(
            f"GEMINI_MODEL={model!r} is below the minimum gemini-3.5. "
            "This build never runs on Gemini 2.x — fix GEMINI_MODEL (see CLAUDE.md)."
        )


def check_vertex_ai_enabled() -> None:
    """Raises RuntimeError unless GOOGLE_GENAI_USE_VERTEXAI is truthy."""
    if os.environ.get("GOOGLE_GENAI_USE_VERTEXAI", "").strip().lower() not in ("1", "true"):
        raise RuntimeError(
            "GOOGLE_GENAI_USE_VERTEXAI is not set to a truthy value. This build must run "
            "on Vertex AI, not the public Gemini API — set GOOGLE_GENAI_USE_VERTEXAI=1."
        )


GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash")
check_model_version(GEMINI_MODEL)
check_vertex_ai_enabled()

# Auto-merges the portfolio PR right after opening it, so the user's live
# site updates with zero clicks. Default ON for the demo — this is the
# opt-out gate, since (unlike everything else in this file) it changes the
# user's LIVE site, not just this agent's own behavior. NOT added to
# .env.example here (outside agent/'s lane) — flagged for the teammate.
PORTFOLIO_AUTO_MERGE = os.environ.get("PORTFOLIO_AUTO_MERGE", "1").strip().lower() in ("1", "true")


def get_portfolio_repo() -> str | None:
    """Resolves the target portfolio repo: Firestore config/portfolio wins
    (the user's choice via the repo picker), falling back to the
    PORTFOLIO_REPO env var. None if neither is set — portfolio_publisher
    treats that as "not configured yet", not an error.

    Lazily imports memory so this module's own import-time checks above
    stay side-effect-free (no Firestore client construction at import).
    """
    from agent import memory

    saved = memory.get_portfolio_config()
    if saved and saved.get("portfolio_repo"):
        return saved["portfolio_repo"]
    return os.environ.get("PORTFOLIO_REPO")


def get_portfolio_auto_merge() -> bool:
    """Resolves the auto-merge flag: Firestore config/portfolio wins,
    falling back to the PORTFOLIO_AUTO_MERGE env-derived constant above.
    """
    from agent import memory

    saved = memory.get_portfolio_config()
    if saved is not None and "auto_merge" in saved:
        return bool(saved["auto_merge"])
    return PORTFOLIO_AUTO_MERGE


def get_portfolio_format_explicit() -> str | None:
    """The picker's raw, explicit format choice ("convention"/"arbitrary"),
    or None if the "format" key was never written at all — distinct from
    get_portfolio_format() below. This is what portfolio_publisher.py's
    auto-merge confidence check reads: a repo whose format was only ever
    defaulted (this returns None) hasn't been confirmed by anyone, so its
    first (bootstrap) write shouldn't be trusted with auto-merge even
    though it still resolves to "convention" for routing purposes.
    """
    from agent import memory

    saved = memory.get_portfolio_config()
    return saved.get("format") if saved and "format" in saved else None


def get_portfolio_format() -> str:
    """Resolved format for ROUTING: the explicit choice if one was ever
    made, else "convention" — the project's own default assumption (see
    CLAUDE.md's frozen contract). Tier 2 (agent/subagents/
    portfolio_structure_detector.py) only ever runs when this explicitly
    resolves to "arbitrary".
    """
    return get_portfolio_format_explicit() or "convention"
