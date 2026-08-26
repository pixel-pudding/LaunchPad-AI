"""
LaunchPad-AI — unit tests for agent/subagents/content_writer.py.

No live Vertex AI: _call_gemini (the one function that actually talks to
google-genai) is monkeypatched to return a canned ContentDraft. These tests
check write_content()'s contract — package shape, non-empty fields, and that
"#" prefixes get stripped from hashtags — not the LLM's actual writing.
"""

from __future__ import annotations

from agent.subagents import content_writer

_PROFILE = {
    "name": "local-rag-cli",
    "summary": "A from-scratch RAG pipeline with a CLI and eval harness.",
    "stack": ["python"],
    "skill_tags": ["python", "ml", "rag"],
    "readme": "# local-rag-cli\n\nA complete RAG pipeline.\n",
    "images": [],
}

_DECISION = {
    "action": "feature_new",
    "reasoning": "substantial, matches interests",
    "target_project": None,
    "positioning": "Lead with the from-scratch retrieval pipeline.",
    "next_build_suggestion": None,
}

_VOICE_PROFILE = {"tone_notes": "direct, a little dry", "sample_snippets": []}


def test_write_content_returns_expected_shape(monkeypatch):
    monkeypatch.setattr(
        content_writer,
        "_call_gemini",
        lambda prompt: content_writer.ContentDraft(
            text="Shipped a RAG pipeline from scratch — here's what it does.",
            hashtags=["#Python", "RAG", "MachineLearning"],
            image_prompt="A clean diagram of a retrieval pipeline.",
        ),
    )

    package = content_writer.write_content(_PROFILE, _DECISION, _VOICE_PROFILE)

    assert set(package.keys()) == {"text", "hashtags", "image_prompt"}
    assert package["text"]
    assert package["image_prompt"]
    assert package["hashtags"]


def test_write_content_strips_hash_prefix_from_hashtags(monkeypatch):
    monkeypatch.setattr(
        content_writer,
        "_call_gemini",
        lambda prompt: content_writer.ContentDraft(
            text="x", hashtags=["#Python", "##RAG", "MachineLearning"], image_prompt="y"
        ),
    )

    package = content_writer.write_content(_PROFILE, _DECISION, _VOICE_PROFILE)

    assert package["hashtags"] == ["Python", "RAG", "MachineLearning"]


def test_build_prompt_includes_decision_fields_not_raw_reasoning():
    prompt = content_writer._build_prompt(_PROFILE, _DECISION, _VOICE_PROFILE)
    assert "Lead with the from-scratch retrieval pipeline." in prompt
    assert "feature_new" in prompt
    assert "local-rag-cli" in prompt
