"""
LaunchPad-AI — unit tests for the full content + publishing + next-build
wiring in agent/runner.py.

No live network: release_analyst/relevance_curator/content_writer/
image_tool/self_reviewer/portfolio_publisher/next_build_suggester and the
memory accessors are all monkeypatched. The functions runner.py imports by
name are patched as `runner.<name>` — patching the originating module
(e.g. content_writer.write_content) would have no effect, since
`from x import y` binds a separate reference into runner's own namespace at
import time. memory.* is patched on the memory module itself, since
runner.py calls those via `memory.<name>(...)` attribute access.

Confirms: a "skip" decision runs NONE of this (content, publishing, or
suggestions); a "feature_new" decision produces a post_package in the
dashboard's exact shape, a portfolio PR, AND next-build suggestions; and a
next_build_suggester failure leaves the decision, post_package, and
portfolio_pr completely untouched — the isolation this feature was built
around.
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

_FEATURE_NEW_DECISION = {
    "action": "feature_new",
    "reasoning": "substantial, matches interests",
    "target_project": None,
    "positioning": "lead with the pipeline",
    "next_build_suggestion": None,
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


def _patch_happy_content_pipeline(monkeypatch):
    """Patches content_writer/image_tool/self_reviewer/portfolio_publisher/
    next_build_suggester to a working, non-network default — individual
    tests override one piece to exercise a failure path."""
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
    monkeypatch.setattr(
        runner,
        "run_self_review",
        lambda post_package, profile, decision, voice_profile: (
            post_package,
            {"passed": True, "issues": [], "revised": False},
        ),
    )
    monkeypatch.setattr(
        runner,
        "publish_to_portfolio",
        lambda repo, profile, decision, post_package, delivery_id: "https://github.com/owner/portfolio-demo/pull/1",
    )
    monkeypatch.setattr(
        runner,
        "suggest_next_builds",
        lambda featured_projects, context_profile: [
            {"title": "Hosted API", "one_line_reason": "Extends the pipeline work."}
        ],
    )


def test_skip_runs_none_of_the_content_publishing_or_suggestion_pipeline(monkeypatch):
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

    called = {
        "content_writer": False,
        "image_tool": False,
        "self_reviewer": False,
        "portfolio_publisher": False,
        "next_build_suggester": False,
    }
    monkeypatch.setattr(runner, "write_content", lambda *a, **k: called.__setitem__("content_writer", True) or {})
    monkeypatch.setattr(runner, "generate_image", lambda *a, **k: called.__setitem__("image_tool", True) or "")
    monkeypatch.setattr(
        runner,
        "run_self_review",
        lambda *a, **k: called.__setitem__("self_reviewer", True) or ({}, {}),
    )
    monkeypatch.setattr(
        runner,
        "publish_to_portfolio",
        lambda *a, **k: called.__setitem__("portfolio_publisher", True) or "",
    )
    monkeypatch.setattr(
        runner,
        "suggest_next_builds",
        lambda *a, **k: called.__setitem__("next_build_suggester", True) or [],
    )

    result = runner.run_agent({"delivery_id": "d1", "repo": "owner/repo", "tag": "v1.0"})

    assert result["action"] == "skip"
    assert result["artifacts"] == {}
    assert result["self_review"] is None
    assert not any(called.values())
    assert saved["record"]["artifacts"] == {}


def test_feature_new_produces_post_package_pr_and_suggestions(monkeypatch):
    saved = _patch_memory(monkeypatch)
    monkeypatch.setattr(runner, "analyze_release", lambda event: dict(_PROFILE))
    monkeypatch.setattr(runner, "curate", lambda profile, memory_context, delivery_id=None: dict(_FEATURE_NEW_DECISION))
    _patch_happy_content_pipeline(monkeypatch)

    result = runner.run_agent({"delivery_id": "d2", "repo": "owner/repo", "tag": "v1.0"})

    assert result["action"] == "feature_new"
    pkg = result["artifacts"]["post_package"]
    assert pkg == {
        "text": "Shipped a thing.",
        "hashtags": ["python", "opensource"],
        "image_url": "data:image/svg+xml;base64,ZmFrZQ==",
    }
    assert result["artifacts"]["portfolio_pr"] == "https://github.com/owner/portfolio-demo/pull/1"
    assert result["artifacts"]["next_builds"] == [
        {"title": "Hosted API", "one_line_reason": "Extends the pipeline work."}
    ]
    assert result["self_review"] == {"passed": True, "issues": [], "revised": False}
    # The Firestore-bound copy carries the real "ts" write; the returned
    # dict must stay JSON-serializable (a plain ISO string, not the
    # SERVER_TIMESTAMP sentinel).
    assert isinstance(result["ts"], str)
    assert saved["record"]["artifacts"] == result["artifacts"]


def test_content_writer_failure_degrades_to_no_post_package_but_publisher_still_runs(monkeypatch):
    _patch_memory(monkeypatch)
    monkeypatch.setattr(runner, "analyze_release", lambda event: dict(_PROFILE))
    monkeypatch.setattr(runner, "curate", lambda profile, memory_context, delivery_id=None: dict(_FEATURE_NEW_DECISION))

    def _boom(*a, **k):
        raise RuntimeError("content writer exploded")

    monkeypatch.setattr(runner, "write_content", _boom)
    self_reviewer_called = {"value": False}
    monkeypatch.setattr(
        runner, "run_self_review", lambda *a, **k: self_reviewer_called.__setitem__("value", True) or ({}, {})
    )
    monkeypatch.setattr(
        runner, "publish_to_portfolio", lambda *a, **k: "https://github.com/owner/portfolio-demo/pull/2"
    )
    monkeypatch.setattr(runner, "suggest_next_builds", lambda *a, **k: [])

    result = runner.run_agent({"delivery_id": "d3", "repo": "owner/repo", "tag": "v1.0"})

    assert result["action"] == "feature_new"
    assert "post_package" not in result["artifacts"]
    # Nothing to review without a post_package.
    assert self_reviewer_called["value"] is False
    # But the portfolio card is an independent artifact — it still runs.
    assert result["artifacts"]["portfolio_pr"] == "https://github.com/owner/portfolio-demo/pull/2"


def test_image_tool_failure_still_produces_post_package_without_image(monkeypatch):
    _patch_memory(monkeypatch)
    monkeypatch.setattr(runner, "analyze_release", lambda event: dict(_PROFILE))
    monkeypatch.setattr(runner, "curate", lambda profile, memory_context, delivery_id=None: dict(_FEATURE_NEW_DECISION))
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
    monkeypatch.setattr(
        runner,
        "run_self_review",
        lambda post_package, profile, decision, voice_profile: (post_package, {"passed": True, "issues": [], "revised": False}),
    )
    monkeypatch.setattr(runner, "publish_to_portfolio", lambda *a, **k: "https://github.com/owner/portfolio-demo/pull/3")
    monkeypatch.setattr(runner, "suggest_next_builds", lambda *a, **k: [])

    result = runner.run_agent({"delivery_id": "d4", "repo": "owner/repo", "tag": "v1.0"})

    pkg = result["artifacts"]["post_package"]
    assert pkg["text"] == "Shipped a thing."
    assert pkg["image_url"] == ""


def test_self_reviewer_failure_keeps_the_unreviewed_post_package(monkeypatch):
    _patch_memory(monkeypatch)
    monkeypatch.setattr(runner, "analyze_release", lambda event: dict(_PROFILE))
    monkeypatch.setattr(runner, "curate", lambda profile, memory_context, delivery_id=None: dict(_FEATURE_NEW_DECISION))
    monkeypatch.setattr(
        runner,
        "write_content",
        lambda profile, decision, voice_profile: {
            "text": "Shipped a thing.",
            "hashtags": ["python"],
            "image_prompt": "a diagram",
        },
    )
    monkeypatch.setattr(runner, "generate_image", lambda prompt: "data:x")

    def _boom(*a, **k):
        raise RuntimeError("self reviewer exploded")

    monkeypatch.setattr(runner, "run_self_review", _boom)
    monkeypatch.setattr(runner, "publish_to_portfolio", lambda *a, **k: "https://github.com/owner/portfolio-demo/pull/4")
    monkeypatch.setattr(runner, "suggest_next_builds", lambda *a, **k: [])

    result = runner.run_agent({"delivery_id": "d5", "repo": "owner/repo", "tag": "v1.0"})

    assert result["artifacts"]["post_package"]["text"] == "Shipped a thing."
    assert result["self_review"] is None
    assert result["artifacts"]["portfolio_pr"] == "https://github.com/owner/portfolio-demo/pull/4"


def test_portfolio_publisher_failure_preserves_post_package(monkeypatch):
    _patch_memory(monkeypatch)
    monkeypatch.setattr(runner, "analyze_release", lambda event: dict(_PROFILE))
    monkeypatch.setattr(runner, "curate", lambda profile, memory_context, delivery_id=None: dict(_FEATURE_NEW_DECISION))
    monkeypatch.setattr(
        runner,
        "write_content",
        lambda profile, decision, voice_profile: {
            "text": "Shipped a thing.",
            "hashtags": ["python"],
            "image_prompt": "a diagram",
        },
    )
    monkeypatch.setattr(runner, "generate_image", lambda prompt: "data:x")
    monkeypatch.setattr(
        runner,
        "run_self_review",
        lambda post_package, profile, decision, voice_profile: (post_package, {"passed": True, "issues": [], "revised": False}),
    )

    def _boom(*a, **k):
        raise RuntimeError("portfolio publisher exploded")

    monkeypatch.setattr(runner, "publish_to_portfolio", _boom)
    monkeypatch.setattr(runner, "suggest_next_builds", lambda *a, **k: [])

    result = runner.run_agent({"delivery_id": "d6", "repo": "owner/repo", "tag": "v1.0"})

    assert result["artifacts"]["post_package"] == {
        "text": "Shipped a thing.",
        "hashtags": ["python"],
        "image_url": "data:x",
    }
    assert "portfolio_pr" not in result["artifacts"]


def test_next_build_suggester_failure_preserves_everything_else(monkeypatch):
    """The specific guarantee this feature was built around: a
    next_build_suggester failure — its own try/except, last step — must
    leave the decision, the post_package, and the portfolio_pr completely
    intact, and simply omit artifacts["next_builds"]."""
    saved = _patch_memory(monkeypatch)
    monkeypatch.setattr(runner, "analyze_release", lambda event: dict(_PROFILE))
    monkeypatch.setattr(runner, "curate", lambda profile, memory_context, delivery_id=None: dict(_FEATURE_NEW_DECISION))
    monkeypatch.setattr(
        runner,
        "write_content",
        lambda profile, decision, voice_profile: {
            "text": "Shipped a thing.",
            "hashtags": ["python"],
            "image_prompt": "a diagram",
        },
    )
    monkeypatch.setattr(runner, "generate_image", lambda prompt: "data:x")
    monkeypatch.setattr(
        runner,
        "run_self_review",
        lambda post_package, profile, decision, voice_profile: (post_package, {"passed": True, "issues": [], "revised": False}),
    )
    monkeypatch.setattr(runner, "publish_to_portfolio", lambda *a, **k: "https://github.com/owner/portfolio-demo/pull/5")

    def _boom(*a, **k):
        raise RuntimeError("next build suggester exploded")

    monkeypatch.setattr(runner, "suggest_next_builds", _boom)

    result = runner.run_agent({"delivery_id": "d7", "repo": "owner/repo", "tag": "v1.0"})

    assert result["action"] == "feature_new"
    assert result["reasoning"] == _FEATURE_NEW_DECISION["reasoning"]
    assert result["artifacts"]["post_package"] == {
        "text": "Shipped a thing.",
        "hashtags": ["python"],
        "image_url": "data:x",
    }
    assert result["artifacts"]["portfolio_pr"] == "https://github.com/owner/portfolio-demo/pull/5"
    assert "next_builds" not in result["artifacts"]
    assert result["self_review"] == {"passed": True, "issues": [], "revised": False}
    # And the Firestore-bound record matches exactly what was returned.
    assert saved["record"]["artifacts"] == result["artifacts"]
