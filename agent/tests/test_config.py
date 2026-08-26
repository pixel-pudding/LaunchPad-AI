"""
LaunchPad-AI — unit tests for the loud model/backend guardrails (agent/config.py).

agent/config.py enforces both checks at import time (that's the point). So
we set valid env vars BEFORE importing it here, then exercise the two
check_* functions directly with arbitrary inputs — independent of whatever
the ambient environment happens to have.
"""

from __future__ import annotations

import os

os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "1")
os.environ.setdefault("GEMINI_MODEL", "gemini-3.5-flash")

import pytest

from agent import config


@pytest.mark.parametrize("model", ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-pro"])
def test_rejects_gemini_2x(model: str) -> None:
    with pytest.raises(RuntimeError, match="gemini-3.5"):
        config.check_model_version(model)


@pytest.mark.parametrize("model", ["gemini-3.5-flash", "gemini-3.6-flash", "gemini-4.0-pro"])
def test_accepts_gemini_3_5_and_newer(model: str) -> None:
    config.check_model_version(model)  # must not raise


def test_rejects_unversioned_model_name() -> None:
    with pytest.raises(RuntimeError, match="doesn't look like a versioned"):
        config.check_model_version("gemini-flash-latest")


def test_rejects_vertex_ai_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GOOGLE_GENAI_USE_VERTEXAI", raising=False)
    with pytest.raises(RuntimeError, match="Vertex AI"):
        config.check_vertex_ai_enabled()


def test_accepts_vertex_ai_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOOGLE_GENAI_USE_VERTEXAI", "1")
    config.check_vertex_ai_enabled()  # must not raise
