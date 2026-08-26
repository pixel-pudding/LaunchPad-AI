"""
LaunchPad-AI — hard pytest assertions for the two Relevance Curator canary
cases named in CLAUDE.md's agentic rule: a trivial release on an
already-featured project must SKIP (not auto-update), and a genuinely new
capability on an already-featured project must UPDATE (not skip, not treated
as a new feature).

These call the REAL curator — real Vertex AI, a couple of small requests.
Requires GOOGLE_GENAI_USE_VERTEXAI=1, GOOGLE_CLOUD_PROJECT,
GOOGLE_CLOUD_LOCATION, and application-default credentials with Vertex AI
access. Run with: python -m pytest eval/test_curator_canaries.py -v
"""

from __future__ import annotations

import pytest

from agent.subagents.relevance_curator import curate
from eval.curator_cases import CASES

_CANARIES = [case for case in CASES if case["canary"]]


@pytest.mark.parametrize("case", _CANARIES, ids=[c["name"] for c in _CANARIES])
def test_curator_canary(case) -> None:
    decision = curate(case["profile"], case["memory_context"], delivery_id=f"eval-{case['name']}")
    assert decision["action"] == case["expected_action"], (
        f"canary '{case['name']}' expected {case['expected_action']!r}, "
        f"got {decision['action']!r} — reasoning: {decision.get('reasoning')!r}"
    )
