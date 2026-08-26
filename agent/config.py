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
