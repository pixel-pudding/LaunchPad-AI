"""
LaunchPad-AI — schema-level unit tests for CuratorDecision
(agent/subagents/relevance_curator.py).

Pure pydantic validation, no network/LLM calls — these check the contract
ADK's output_schema relies on: the three-way action enum, which fields are
required vs. nullable, and that a malformed action is rejected before it
could ever reach a "genuine decision" downstream.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from agent.subagents.relevance_curator import CuratorDecision


def test_accepts_minimal_skip_decision():
    decision = CuratorDecision(action="skip", reasoning="trivial release", positioning="")
    assert decision.action == "skip"
    assert decision.target_project is None
    assert decision.next_build_suggestion is None


def test_accepts_full_decision_with_all_fields():
    decision = CuratorDecision(
        action="update_existing",
        reasoning="adds a real capability",
        target_project="dev/rag-pipeline",
        positioning="lead with the new streaming support",
        next_build_suggestion="a small demo notebook",
    )
    assert decision.target_project == "dev/rag-pipeline"
    assert decision.next_build_suggestion == "a small demo notebook"


@pytest.mark.parametrize("bad_action", ["feature", "always_feature", "maybe", ""])
def test_rejects_action_outside_the_three_way_enum(bad_action: str):
    with pytest.raises(ValidationError):
        CuratorDecision(action=bad_action, reasoning="x", positioning="")


def test_rejects_missing_reasoning():
    with pytest.raises(ValidationError):
        CuratorDecision(action="skip", positioning="")


def test_dump_excludes_none_matches_adk_behavior():
    """ADK's output_schema handling calls model_dump(exclude_none=True) on the
    validated result (verified against the installed ADK 2.7.1 source) — so
    curate() must .get() optional fields back with defaults rather than
    assume they're present as explicit None keys."""
    decision = CuratorDecision(action="skip", reasoning="x", positioning="")
    dumped = decision.model_dump(exclude_none=True)
    assert "target_project" not in dumped
    assert "next_build_suggestion" not in dumped
