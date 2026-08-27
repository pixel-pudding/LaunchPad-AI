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


# get_portfolio_repo/get_portfolio_auto_merge lazily do `from agent import
# memory` inside the function body, then call `memory.get_portfolio_config()`
# — an attribute lookup at call time, not an import-time binding — so
# patching `memory.get_portfolio_config` directly is what actually takes
# effect here (same reasoning as everywhere else in this codebase).


def test_get_portfolio_repo_prefers_firestore_over_env(monkeypatch: pytest.MonkeyPatch) -> None:
    from agent import memory

    monkeypatch.setenv("PORTFOLIO_REPO", "owner/env-repo")
    monkeypatch.setattr(
        memory, "get_portfolio_config", lambda client=None: {"portfolio_repo": "owner/firestore-repo"}
    )

    assert config.get_portfolio_repo() == "owner/firestore-repo"


def test_get_portfolio_repo_falls_back_to_env_when_firestore_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    from agent import memory

    monkeypatch.setenv("PORTFOLIO_REPO", "owner/env-repo")
    monkeypatch.setattr(memory, "get_portfolio_config", lambda client=None: None)

    assert config.get_portfolio_repo() == "owner/env-repo"


def test_get_portfolio_repo_returns_none_when_neither_is_set(monkeypatch: pytest.MonkeyPatch) -> None:
    from agent import memory

    monkeypatch.delenv("PORTFOLIO_REPO", raising=False)
    monkeypatch.setattr(memory, "get_portfolio_config", lambda client=None: None)

    assert config.get_portfolio_repo() is None


def test_get_portfolio_auto_merge_prefers_firestore_over_env(monkeypatch: pytest.MonkeyPatch) -> None:
    from agent import memory

    monkeypatch.setattr(config, "PORTFOLIO_AUTO_MERGE", True)
    monkeypatch.setattr(
        memory,
        "get_portfolio_config",
        lambda client=None: {"portfolio_repo": "owner/repo", "auto_merge": False},
    )

    assert config.get_portfolio_auto_merge() is False


def test_get_portfolio_auto_merge_falls_back_to_env_constant(monkeypatch: pytest.MonkeyPatch) -> None:
    from agent import memory

    monkeypatch.setattr(config, "PORTFOLIO_AUTO_MERGE", True)
    monkeypatch.setattr(memory, "get_portfolio_config", lambda client=None: None)

    assert config.get_portfolio_auto_merge() is True
