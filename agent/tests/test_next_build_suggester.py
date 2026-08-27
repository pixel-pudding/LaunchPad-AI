"""
LaunchPad-AI — unit tests for agent/subagents/next_build_suggester.py.

No live Vertex AI: _call_gemini is monkeypatched to return a canned
NextBuildSuggestions. Checks the 1-3 shape, and — the behavior this feature
exists to guarantee — that thin/empty memory produces an honest empty list
rather than invented filler.
"""

from __future__ import annotations

from agent.subagents import next_build_suggester as nbs

_FEATURED_PROJECTS = [
    {
        "repo": "owner/local-rag-cli",
        "name": "local-rag-cli",
        "summary": "A RAG pipeline.",
        "stack": ["python"],
        "skill_tags": ["python", "ml"],
    }
]
_CONTEXT_PROFILE = {"interests": ["LLM tooling", "developer tools"], "past_projects": ["a Discord bot"]}


def test_returns_one_to_three_suggestions_with_title_and_reason(monkeypatch):
    monkeypatch.setattr(
        nbs,
        "_call_gemini",
        lambda prompt: nbs.NextBuildSuggestions(
            suggestions=[
                nbs.NextBuildSuggestion(
                    title="Hosted API for local-rag-cli",
                    one_line_reason="Extends your local-rag-cli work with a hosted endpoint.",
                ),
                nbs.NextBuildSuggestion(
                    title="Web dashboard for the Discord bot",
                    one_line_reason="Complements your Discord bot with a visual admin panel.",
                ),
            ]
        ),
    )

    suggestions = nbs.suggest_next_builds(_FEATURED_PROJECTS, _CONTEXT_PROFILE)

    assert 1 <= len(suggestions) <= 3
    for s in suggestions:
        assert set(s.keys()) == {"title", "one_line_reason"}
        assert s["title"]
        assert s["one_line_reason"]


def test_returns_empty_list_when_memory_is_too_thin(monkeypatch):
    """The model itself decides there's nothing to ground a suggestion in —
    confirms the function faithfully passes an empty list through rather
    than padding it with something invented."""
    monkeypatch.setattr(nbs, "_call_gemini", lambda prompt: nbs.NextBuildSuggestions(suggestions=[]))

    suggestions = nbs.suggest_next_builds([], {})

    assert suggestions == []


def test_schema_rejects_more_than_three_suggestions():
    """The model is instructed to return at most 3, and the schema itself
    enforces it — a >3 response should fail validation before it ever
    reaches suggest_next_builds()."""
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        nbs.NextBuildSuggestions(
            suggestions=[nbs.NextBuildSuggestion(title=f"idea {i}", one_line_reason=f"reason {i}") for i in range(4)]
        )


def test_slices_to_three_if_validation_is_ever_bypassed(monkeypatch):
    """Defense in depth: even if response.parsed somehow carried more than
    3 items (bypassing NextBuildSuggestions's own max_length=3 via
    model_construct, which skips validation), the public function still
    caps at 3."""
    oversized = nbs.NextBuildSuggestions.model_construct(
        suggestions=[nbs.NextBuildSuggestion(title=f"idea {i}", one_line_reason=f"reason {i}") for i in range(5)]
    )
    monkeypatch.setattr(nbs, "_call_gemini", lambda prompt: oversized)

    suggestions = nbs.suggest_next_builds(_FEATURED_PROJECTS, _CONTEXT_PROFILE)

    assert len(suggestions) == 3


def test_build_prompt_includes_featured_projects_and_context():
    prompt = nbs._build_prompt(_FEATURED_PROJECTS, _CONTEXT_PROFILE)
    assert "local-rag-cli" in prompt
    assert "LLM tooling" in prompt
