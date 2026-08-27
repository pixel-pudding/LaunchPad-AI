"""
LaunchPad-AI — unit tests for agent/subagents/self_reviewer.py.

No live Vertex AI: _call_gemini is monkeypatched to return a canned
ReviewOutcome. Checks the leave-unchanged-when-passed and
apply-the-one-revision-when-not-passed behaviors.
"""

from __future__ import annotations

from agent.subagents import self_reviewer

_POST_PACKAGE = {"text": "original text", "hashtags": ["python"], "image_url": "x"}
_PROFILE = {"name": "demo", "summary": "s", "stack": ["python"], "readme": "# demo"}
_DECISION = {"action": "feature_new", "positioning": "p"}
_VOICE_PROFILE = {"tone_notes": "direct", "sample_snippets": []}


def test_passed_review_leaves_post_package_unchanged(monkeypatch):
    monkeypatch.setattr(
        self_reviewer,
        "_call_gemini",
        lambda prompt: self_reviewer.ReviewOutcome(passed=True, issues=[]),
    )

    final_package, outcome = self_reviewer.review(_POST_PACKAGE, _PROFILE, _DECISION, _VOICE_PROFILE)

    assert final_package == _POST_PACKAGE
    assert outcome == {"passed": True, "issues": [], "revised": False}


def test_failed_review_applies_the_one_revision(monkeypatch):
    monkeypatch.setattr(
        self_reviewer,
        "_call_gemini",
        lambda prompt: self_reviewer.ReviewOutcome(
            passed=False,
            issues=["hashtag too generic"],
            revised_text="revised text",
            revised_hashtags=["#RAG", "MachineLearning"],
        ),
    )

    final_package, outcome = self_reviewer.review(_POST_PACKAGE, _PROFILE, _DECISION, _VOICE_PROFILE)

    assert final_package["text"] == "revised text"
    assert final_package["hashtags"] == ["RAG", "MachineLearning"]
    assert final_package["image_url"] == _POST_PACKAGE["image_url"]  # untouched
    assert outcome == {"passed": False, "issues": ["hashtag too generic"], "revised": True}


def test_failed_review_without_a_revision_keeps_original_text(monkeypatch):
    monkeypatch.setattr(
        self_reviewer,
        "_call_gemini",
        lambda prompt: self_reviewer.ReviewOutcome(passed=False, issues=["voice inconsistent"]),
    )

    final_package, outcome = self_reviewer.review(_POST_PACKAGE, _PROFILE, _DECISION, _VOICE_PROFILE)

    assert final_package["text"] == _POST_PACKAGE["text"]
    assert outcome["revised"] is False
