"""
LaunchPad-AI — unit tests for the content-generation wiring in agent/runner.py.

No live network: release_analyst/relevance_curator/content_writer/image_tool
and the memory accessors are all monkeypatched. The functions runner.py
imports by name (curate, analyze_release, write_content, generate_image,
assemble_post_package) are patched as `runner.<name>` — patching the
originating module (e.g. content_writer.write_content) would have no effect,
since `from x import y` binds a separate reference into runner's own
namespace at import time. memory.* is patched on the memory module itself,
since runner.py calls those via `memory.<name>(...)` attribute access.

Confirms the two behaviors this wiring exists to guarantee: a "skip"
decision produces NO post_package and never even calls the content
pipeline, and a "feature_new" decision produces a post_package in the exact
{text, hashtags, image_url} shape the dashboard reads.
"""

from __future__ import annotations

from agent import memory, runner

_PROFILE = {
    "name": "demo",
    "summary": "x",
    "stack": ["python"],
    "skill_tags": ["python"],
    "readme": "# demo",
    "images": [],
}


def _patch_memory(monkeypatch):
    saved: dict = {}
    monkeypatch.setattr(memory, "is_duplicate_delivery", lambda delivery_id, client=None: False)
    monkeypatch.setattr(memory, "list_projects", lambda client=None: [])
    monkeypatch.setattr(memory, "get_context_profile", lambda client=None: {})
    monkeypatch.setattr(memory, "get_voice_profile", lambda client=None: {})
    monkeypatch.setattr(memory, "upsert_project", lambda repo, data, client=None: None)
    monkeypatch.setattr(
        memory,
        "save_decision",
        lambda delivery_id, record, client=None: saved.update(delivery_id=delivery_id, record=record),
    )
    monkeypatch.setattr(memory, "mark_delivery_processed", lambda delivery_id, client=None: None)
    return saved


def test_skip_produces_no_post_package_and_skips_content_pipeline(monkeypatch):
    saved = _patch_memory(monkeypatch)
    monkeypatch.setattr(runner, "analyze_release", lambda event: dict(_PROFILE))
    monkeypatch.setattr(
        runner,
        "curate",
        lambda profile, memory_context, delivery_id=None: {
            "action": "skip",
            "reasoning": "trivial release",
            "target_project": None,
            "positioning": "",
            "next_build_suggestion": None,
        },
    )

    content_writer_called = {"value": False}
    generate_image_called = {"value": False}
    monkeypatch.setattr(
        runner,
        "write_content",
        lambda *a, **k: content_writer_called.__setitem__("value", True) or {},
    )
    monkeypatch.setattr(
        runner,
        "generate_image",
        lambda *a, **k: generate_image_called.__setitem__("value", True) or "",
    )

    result = runner.run_agent({"delivery_id": "d1", "repo": "owner/repo", "tag": "v1.0"})

    assert result["action"] == "skip"
    assert result["artifacts"] == {}
    assert content_writer_called["value"] is False
    assert generate_image_called["value"] is False
    assert saved["record"]["artifacts"] == {}


def test_feature_new_produces_post_package_in_dashboard_shape(monkeypatch):
    saved = _patch_memory(monkeypatch)
    monkeypatch.setattr(runner, "analyze_release", lambda event: dict(_PROFILE))
    monkeypatch.setattr(
        runner,
        "curate",
        lambda profile, memory_context, delivery_id=None: {
            "action": "feature_new",
            "reasoning": "substantial, matches interests",
            "target_project": None,
            "positioning": "lead with the pipeline",
            "next_build_suggestion": None,
        },
    )
    monkeypatch.setattr(
        runner,
        "write_content",
        lambda profile, decision, voice_profile: {
            "text": "Shipped a thing.",
            "hashtags": ["python", "opensource"],
            "image_prompt": "a diagram",
        },
    )
    monkeypatch.setattr(runner, "generate_image", lambda prompt: "data:image/svg+xml;base64,ZmFrZQ==")

    result = runner.run_agent({"delivery_id": "d2", "repo": "owner/repo", "tag": "v1.0"})

    assert result["action"] == "feature_new"
    pkg = result["artifacts"]["post_package"]
    assert pkg == {
        "text": "Shipped a thing.",
        "hashtags": ["python", "opensource"],
        "image_url": "data:image/svg+xml;base64,ZmFrZQ==",
    }
    # The Firestore-bound copy carries the real "ts" write; the returned
    # dict must stay JSON-serializable (a plain ISO string, not the
    # SERVER_TIMESTAMP sentinel).
    assert isinstance(result["ts"], str)
    assert saved["record"]["artifacts"]["post_package"] == pkg


def test_content_writer_failure_degrades_to_no_post_package(monkeypatch):
    _patch_memory(monkeypatch)
    monkeypatch.setattr(runner, "analyze_release", lambda event: dict(_PROFILE))
    monkeypatch.setattr(
        runner,
        "curate",
        lambda profile, memory_context, delivery_id=None: {
            "action": "feature_new",
            "reasoning": "substantial",
            "target_project": None,
            "positioning": "x",
            "next_build_suggestion": None,
        },
    )

    def _boom(*a, **k):
        raise RuntimeError("content writer exploded")

    monkeypatch.setattr(runner, "write_content", _boom)

    result = runner.run_agent({"delivery_id": "d3", "repo": "owner/repo", "tag": "v1.0"})

    assert result["action"] == "feature_new"
    assert result["artifacts"] == {}


def test_image_tool_failure_still_produces_post_package_without_image(monkeypatch):
    _patch_memory(monkeypatch)
    monkeypatch.setattr(runner, "analyze_release", lambda event: dict(_PROFILE))
    monkeypatch.setattr(
        runner,
        "curate",
        lambda profile, memory_context, delivery_id=None: {
            "action": "feature_new",
            "reasoning": "substantial",
            "target_project": None,
            "positioning": "x",
            "next_build_suggestion": None,
        },
    )
    monkeypatch.setattr(
        runner,
        "write_content",
        lambda profile, decision, voice_profile: {
            "text": "Shipped a thing.",
            "hashtags": ["python"],
            "image_prompt": "a diagram",
        },
    )

    def _boom(*a, **k):
        raise RuntimeError("image tool exploded")

    monkeypatch.setattr(runner, "generate_image", _boom)

    result = runner.run_agent({"delivery_id": "d4", "repo": "owner/repo", "tag": "v1.0"})

    pkg = result["artifacts"]["post_package"]
    assert pkg["text"] == "Shipped a thing."
    assert pkg["image_url"] == ""
