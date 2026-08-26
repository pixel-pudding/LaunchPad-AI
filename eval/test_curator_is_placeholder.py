"""
LaunchPad-AI — guard against the Relevance Curator shipping as a silent
placeholder (agent/subagents/relevance_curator.py).

This test is EXPECTED TO FAIL right now, on purpose, while curate() is still
the explicit placeholder that always returns skip/"placeholder". It flips to
pass once the real relevance decision (CLAUDE.md's "agentic rule": a genuine
feature_new / update_existing / skip judgment) replaces the placeholder body
— that is the next, separate change. Do not delete or weaken this test to
make it pass; make the curator real instead.
"""

from __future__ import annotations

from agent.subagents.relevance_curator import curate


def test_curator_is_not_still_a_placeholder() -> None:
    profile = {
        "name": "big-genuine-ml-project",
        "summary": "A from-scratch transformer training pipeline.",
        "stack": ["python"],
        "skill_tags": ["ml", "python"],
        "readme": "# Big ML Project\nA real, substantial release.",
        "images": [],
    }
    memory_context = {"featured_projects": [], "context_profile": {"interests": ["ml"]}}

    decision = curate(profile, memory_context)

    assert decision["reasoning"] != "placeholder", (
        "relevance_curator.curate() is still the explicit placeholder. "
        "See CLAUDE.md's 'agentic rule' — implement the real decision."
    )
