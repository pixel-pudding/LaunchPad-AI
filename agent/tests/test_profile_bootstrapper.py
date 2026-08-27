"""
LaunchPad-AI — unit tests for agent/subagents/profile_bootstrapper.py.

No live GitHub or Vertex AI calls: _fetch_github_signal and _synthesize_profile
are monkeypatched.  These tests verify ensure_profile()'s contract:
  - bootstrap when profile is missing
  - no-op when profile already exists
  - graceful default on GitHub failure
  - graceful default on Gemini failure
"""

from __future__ import annotations

from agent.subagents import profile_bootstrapper
from agent.subagents.profile_bootstrapper import DEFAULT_PROFILE, ensure_profile

_SAMPLE_PROFILE = {
    "interests": ["AI agents", "web dev"],
    "primary_languages": ["Python", "TypeScript"],
    "summary": "A builder focused on agentic systems.",
    "focus_areas": ["event-driven architecture", "LLM orchestration"],
}

_EVENT = {
    "delivery_id": "test-001",
    "repo": "pixel-pudding/smart-notes-test",
    "tag": "v1.0",
    "_github_token": "fake-token",
}


def test_bootstrap_runs_when_profile_missing(monkeypatch):
    """Profile missing → bootstrap runs, writes context/profile."""
    written = {}

    monkeypatch.setattr(
        profile_bootstrapper, "memory",
        type("FakeMemory", (), {
            "get_context_profile": staticmethod(lambda: {}),
            "set_context_profile": staticmethod(lambda data: written.update(data)),
        })(),
    )
    monkeypatch.setattr(
        profile_bootstrapper, "_fetch_github_signal",
        lambda owner, token: {"bio": "I build things", "repos": []},
    )
    monkeypatch.setattr(
        profile_bootstrapper, "_synthesize_profile",
        lambda signal: _SAMPLE_PROFILE,
    )

    result = ensure_profile(_EVENT)

    assert result == _SAMPLE_PROFILE
    assert written == _SAMPLE_PROFILE


def test_existing_profile_is_not_overwritten(monkeypatch):
    """Profile already exists → no-op (not overwritten, no GitHub/Gemini call)."""
    fetch_called = False
    synth_called = False

    def fake_fetch(*a, **kw):
        nonlocal fetch_called
        fetch_called = True
        return {}

    def fake_synth(*a, **kw):
        nonlocal synth_called
        synth_called = True
        return {}

    monkeypatch.setattr(
        profile_bootstrapper, "memory",
        type("FakeMemory", (), {
            "get_context_profile": staticmethod(lambda: _SAMPLE_PROFILE),
        })(),
    )
    monkeypatch.setattr(profile_bootstrapper, "_fetch_github_signal", fake_fetch)
    monkeypatch.setattr(profile_bootstrapper, "_synthesize_profile", fake_synth)

    result = ensure_profile(_EVENT)

    assert result == _SAMPLE_PROFILE
    assert not fetch_called
    assert not synth_called


def test_github_fetch_failure_returns_default(monkeypatch):
    """GitHub fetch fails → returns default profile, no crash."""
    monkeypatch.setattr(
        profile_bootstrapper, "memory",
        type("FakeMemory", (), {
            "get_context_profile": staticmethod(lambda: {}),
        })(),
    )
    monkeypatch.setattr(
        profile_bootstrapper, "_fetch_github_signal",
        lambda owner, token: (_ for _ in ()).throw(ConnectionError("GitHub down")),
    )

    result = ensure_profile(_EVENT)

    assert result == DEFAULT_PROFILE


def test_gemini_synth_failure_returns_default(monkeypatch):
    """Gemini synthesis fails → returns default profile, no crash."""
    monkeypatch.setattr(
        profile_bootstrapper, "memory",
        type("FakeMemory", (), {
            "get_context_profile": staticmethod(lambda: {}),
        })(),
    )
    monkeypatch.setattr(
        profile_bootstrapper, "_fetch_github_signal",
        lambda owner, token: {"bio": "test", "repos": []},
    )
    monkeypatch.setattr(
        profile_bootstrapper, "_synthesize_profile",
        lambda signal: (_ for _ in ()).throw(RuntimeError("Gemini failed")),
    )

    result = ensure_profile(_EVENT)

    assert result == DEFAULT_PROFILE
