"""
LaunchPad-AI — unit tests for the full content + publishing + auto-merge +
next-build wiring in agent/runner.py.

No live network: release_analyst/relevance_curator/content_writer/
image_tool/self_reviewer/portfolio_publisher/github_merge_pr/
next_build_suggester and the memory accessors are all monkeypatched. The
functions runner.py imports by name are patched as `runner.<name>` —
patching the originating module (e.g. content_writer.write_content) would
have no effect, since `from x import y` binds a separate reference into
runner's own namespace at import time. memory.* is patched on the memory
module itself, since runner.py calls those via `memory.<name>(...)`
attribute access.

runner.py now calls config.get_portfolio_auto_merge() (Firestore-first,
env-fallback), not the raw PORTFOLIO_AUTO_MERGE constant directly. That
function's Firestore read is neutralized in _patch_memory (memory.
get_portfolio_config -> None), so tests keep controlling the resolved value
the same way as before — `monkeypatch.setattr(config, "PORTFOLIO_AUTO_MERGE",
...)` — since that's a plain module-global read inside the fallback branch.

Confirms: a "skip" decision runs NONE of this; a "feature_new" decision
with auto-merge ON gets a merged PR — targeting the PR's actual repo
(portfolio_repo), not the source release repo, a regression check for a
real bug found and fixed in this same change; auto-merge OFF never calls
github_merge_pr and leaves the PR open; a merge failure leaves the open PR
and post_package intact with merged=False; no portfolio configured (neither
Firestore nor env) skips publishing gracefully with the post still
succeeding; a next_build_suggester failure leaves everything built before
it (decision, post, PR, merge status) completely untouched; and — Tier 2's
hard safety invariant — an arbitrary-mode PR (pr["mode"] != "convention")
NEVER auto-merges even when auto_merge is on, and a Tier 2 exception
degrades exactly like a convention-path one (post_package survives, the
run still returns normally).
"""

from __future__ import annotations

from agent import config, memory, runner

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
    # config.get_portfolio_auto_merge() checks Firestore config/portfolio
    # first — without this, every test would hit a REAL firestore.Client().
    # None means "not configured in Firestore", so it falls through to the
    # PORTFOLIO_AUTO_MERGE constant, which individual tests still patch via
    # `monkeypatch.setattr(config, "PORTFOLIO_AUTO_MERGE", ...)` exactly as
    # before — that fallback lookup is a plain module-global read, so it
    # sees the patched value fine.
    monkeypatch.setattr(memory, "get_portfolio_config", lambda client=None: None)
    monkeypatch.setattr(
        memory,
        "save_decision",
        lambda delivery_id, record, client=None: saved.update(delivery_id=delivery_id, record=record),
    )
    monkeypatch.setattr(memory, "mark_delivery_processed", lambda delivery_id, client=None: None)
    return saved


def _patch_happy_content_pipeline(monkeypatch, pr_number=1):
    """Patches content_writer/image_tool/self_reviewer/portfolio_publisher/
    github_merge_pr/next_build_suggester to a working, non-network default —
    individual tests override one piece to exercise a failure path."""
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
        lambda repo, profile, decision, post_package, delivery_id, tag: {
            "mode": "convention",
            "url": f"https://github.com/owner/portfolio-demo/pull/{pr_number}",
            "number": pr_number,
            "portfolio_repo": "owner/portfolio-demo",
        },
    )
    monkeypatch.setattr(
        runner, "github_merge_pr", lambda repo, pr_number: {"merged": True, "sha": "merged-sha"}
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
        "github_merge_pr": False,
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
        lambda *a, **k: called.__setitem__("portfolio_publisher", True) or {"mode": "convention", "url": "", "number": 1, "portfolio_repo": ""},
    )
    monkeypatch.setattr(
        runner,
        "github_merge_pr",
        lambda *a, **k: called.__setitem__("github_merge_pr", True) or {"merged": True, "sha": ""},
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


def test_feature_new_with_auto_merge_on_produces_merged_pr_and_suggestions(monkeypatch):
    saved = _patch_memory(monkeypatch)
    monkeypatch.setattr(runner, "analyze_release", lambda event: dict(_PROFILE))
    monkeypatch.setattr(runner, "curate", lambda profile, memory_context, delivery_id=None: dict(_FEATURE_NEW_DECISION))
    monkeypatch.setattr(config, "PORTFOLIO_AUTO_MERGE", True)
    merge_calls = []
    _patch_happy_content_pipeline(monkeypatch, pr_number=1)
    monkeypatch.setattr(
        runner,
        "github_merge_pr",
        lambda repo, pr_number: merge_calls.append((repo, pr_number)) or {"merged": True, "sha": "merged-sha"},
    )

    result = runner.run_agent({"delivery_id": "d2", "repo": "owner/repo", "tag": "v1.0"})

    assert result["action"] == "feature_new"
    # Regression check for the merge-repo bug: this must target the PR's
    # actual repo (owner/portfolio-demo), NOT `repo` (owner/repo, the
    # source release repo the webhook fired for) — those are two different
    # repos, and merging against the wrong one is exactly what shipped
    # before this fix.
    assert merge_calls == [("owner/portfolio-demo", 1)]
    assert result["artifacts"]["portfolio_pr"] == "https://github.com/owner/portfolio-demo/pull/1"
    assert result["artifacts"]["portfolio_pr_merged"] is True
    assert result["artifacts"]["portfolio_pr_sha"] == "merged-sha"
    assert result["artifacts"]["next_builds"] == [
        {"title": "Hosted API", "one_line_reason": "Extends the pipeline work."}
    ]
    # The Firestore-bound copy carries the real "ts" write; the returned
    # dict must stay JSON-serializable (a plain ISO string, not the
    # SERVER_TIMESTAMP sentinel).
    assert isinstance(result["ts"], str)
    assert saved["record"]["artifacts"] == result["artifacts"]


def test_no_portfolio_configured_skips_publish_gracefully_post_still_succeeds(monkeypatch):
    """Neither Firestore config/portfolio nor the PORTFOLIO_REPO env is
    set — publish_to_portfolio returns None (not an exception), per
    portfolio_publisher's own contract. The decision and post_package must
    succeed exactly as if nothing about the portfolio had ever run, and
    github_merge_pr must never even be attempted (there's no PR number to
    merge)."""
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
    monkeypatch.setattr(runner, "publish_to_portfolio", lambda *a, **k: None)
    merge_called = {"value": False}
    monkeypatch.setattr(runner, "github_merge_pr", lambda *a, **k: merge_called.__setitem__("value", True) or {})
    monkeypatch.setattr(runner, "suggest_next_builds", lambda *a, **k: [])

    result = runner.run_agent({"delivery_id": "d10", "repo": "owner/repo", "tag": "v1.0"})

    assert result["action"] == "feature_new"
    assert result["artifacts"]["post_package"] == {
        "text": "Shipped a thing.",
        "hashtags": ["python"],
        "image_url": "data:x",
    }
    assert "portfolio_pr" not in result["artifacts"]
    assert "portfolio_pr_merged" not in result["artifacts"]
    assert merge_called["value"] is False
    assert saved["record"]["artifacts"] == result["artifacts"]


def test_auto_merge_off_never_calls_merge_and_leaves_pr_open(monkeypatch):
    _patch_memory(monkeypatch)
    monkeypatch.setattr(runner, "analyze_release", lambda event: dict(_PROFILE))
    monkeypatch.setattr(runner, "curate", lambda profile, memory_context, delivery_id=None: dict(_FEATURE_NEW_DECISION))
    monkeypatch.setattr(config, "PORTFOLIO_AUTO_MERGE", False)
    _patch_happy_content_pipeline(monkeypatch, pr_number=2)
    merge_called = {"value": False}
    monkeypatch.setattr(
        runner, "github_merge_pr", lambda *a, **k: merge_called.__setitem__("value", True) or {"merged": True, "sha": "x"}
    )

    result = runner.run_agent({"delivery_id": "d3", "repo": "owner/repo", "tag": "v1.0"})

    assert merge_called["value"] is False
    assert result["artifacts"]["portfolio_pr"] == "https://github.com/owner/portfolio-demo/pull/2"
    assert result["artifacts"]["portfolio_pr_merged"] is False
    assert "portfolio_pr_sha" not in result["artifacts"]


def test_merge_failure_preserves_open_pr_and_post_package(monkeypatch):
    _patch_memory(monkeypatch)
    monkeypatch.setattr(runner, "analyze_release", lambda event: dict(_PROFILE))
    monkeypatch.setattr(runner, "curate", lambda profile, memory_context, delivery_id=None: dict(_FEATURE_NEW_DECISION))
    monkeypatch.setattr(config, "PORTFOLIO_AUTO_MERGE", True)
    _patch_happy_content_pipeline(monkeypatch, pr_number=3)

    def _boom(*a, **k):
        raise RuntimeError("not mergeable — branch protection")

    monkeypatch.setattr(runner, "github_merge_pr", _boom)

    result = runner.run_agent({"delivery_id": "d4", "repo": "owner/repo", "tag": "v1.0"})

    assert result["action"] == "feature_new"  # webhook did not error
    assert result["artifacts"]["portfolio_pr"] == "https://github.com/owner/portfolio-demo/pull/3"
    assert result["artifacts"]["portfolio_pr_merged"] is False
    assert "portfolio_pr_sha" not in result["artifacts"]
    assert result["artifacts"]["post_package"]["text"] == "Shipped a thing."


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
        runner,
        "publish_to_portfolio",
        lambda *a, **k: {"mode": "convention", "url": "https://github.com/owner/portfolio-demo/pull/4", "number": 4, "portfolio_repo": "owner/portfolio-demo"},
    )
    monkeypatch.setattr(runner, "github_merge_pr", lambda repo, pr_number: {"merged": True, "sha": "s"})
    monkeypatch.setattr(runner, "suggest_next_builds", lambda *a, **k: [])

    result = runner.run_agent({"delivery_id": "d5", "repo": "owner/repo", "tag": "v1.0"})

    assert result["action"] == "feature_new"
    assert "post_package" not in result["artifacts"]
    # Nothing to review without a post_package.
    assert self_reviewer_called["value"] is False
    # But the portfolio card is an independent artifact — it still runs (and merges).
    assert result["artifacts"]["portfolio_pr"] == "https://github.com/owner/portfolio-demo/pull/4"
    assert result["artifacts"]["portfolio_pr_merged"] is True


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
    monkeypatch.setattr(
        runner,
        "publish_to_portfolio",
        lambda *a, **k: {"mode": "convention", "url": "https://github.com/owner/portfolio-demo/pull/5", "number": 5, "portfolio_repo": "owner/portfolio-demo"},
    )
    monkeypatch.setattr(runner, "github_merge_pr", lambda repo, pr_number: {"merged": True, "sha": "s"})
    monkeypatch.setattr(runner, "suggest_next_builds", lambda *a, **k: [])

    result = runner.run_agent({"delivery_id": "d6", "repo": "owner/repo", "tag": "v1.0"})

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
    monkeypatch.setattr(
        runner,
        "publish_to_portfolio",
        lambda *a, **k: {"mode": "convention", "url": "https://github.com/owner/portfolio-demo/pull/6", "number": 6, "portfolio_repo": "owner/portfolio-demo"},
    )
    monkeypatch.setattr(runner, "github_merge_pr", lambda repo, pr_number: {"merged": True, "sha": "s"})
    monkeypatch.setattr(runner, "suggest_next_builds", lambda *a, **k: [])

    result = runner.run_agent({"delivery_id": "d7", "repo": "owner/repo", "tag": "v1.0"})

    assert result["artifacts"]["post_package"]["text"] == "Shipped a thing."
    assert result["self_review"] is None
    assert result["artifacts"]["portfolio_pr"] == "https://github.com/owner/portfolio-demo/pull/6"


def test_portfolio_publisher_failure_preserves_post_package_and_skips_merge(monkeypatch):
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
    merge_called = {"value": False}
    monkeypatch.setattr(runner, "github_merge_pr", lambda *a, **k: merge_called.__setitem__("value", True) or {})
    monkeypatch.setattr(runner, "suggest_next_builds", lambda *a, **k: [])

    result = runner.run_agent({"delivery_id": "d8", "repo": "owner/repo", "tag": "v1.0"})

    assert result["artifacts"]["post_package"] == {
        "text": "Shipped a thing.",
        "hashtags": ["python"],
        "image_url": "data:x",
    }
    assert "portfolio_pr" not in result["artifacts"]
    assert "portfolio_pr_merged" not in result["artifacts"]
    assert merge_called["value"] is False  # nothing to merge — never attempted


def test_next_build_suggester_failure_preserves_everything_else(monkeypatch):
    """The specific guarantee this feature was built around: a
    next_build_suggester failure — its own try/except, last step — must
    leave the decision, the post_package, and the portfolio PR/merge state
    completely intact, and simply omit artifacts["next_builds"]."""
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
    monkeypatch.setattr(
        runner,
        "publish_to_portfolio",
        lambda *a, **k: {"mode": "convention", "url": "https://github.com/owner/portfolio-demo/pull/9", "number": 9, "portfolio_repo": "owner/portfolio-demo"},
    )
    monkeypatch.setattr(runner, "github_merge_pr", lambda repo, pr_number: {"merged": True, "sha": "final-sha"})

    def _boom(*a, **k):
        raise RuntimeError("next build suggester exploded")

    monkeypatch.setattr(runner, "suggest_next_builds", _boom)

    result = runner.run_agent({"delivery_id": "d9", "repo": "owner/repo", "tag": "v1.0"})

    assert result["action"] == "feature_new"
    assert result["reasoning"] == _FEATURE_NEW_DECISION["reasoning"]
    assert result["artifacts"]["post_package"] == {
        "text": "Shipped a thing.",
        "hashtags": ["python"],
        "image_url": "data:x",
    }
    assert result["artifacts"]["portfolio_pr"] == "https://github.com/owner/portfolio-demo/pull/9"
    assert result["artifacts"]["portfolio_pr_merged"] is True
    assert result["artifacts"]["portfolio_pr_sha"] == "final-sha"
    assert "next_builds" not in result["artifacts"]
    assert result["self_review"] == {"passed": True, "issues": [], "revised": False}
    # And the Firestore-bound record matches exactly what was returned.
    assert saved["record"]["artifacts"] == result["artifacts"]


def test_arbitrary_mode_never_auto_merges_even_with_auto_merge_true(monkeypatch):
    """Tier 2 hard safety invariant #2: an arbitrary-repo PR (this run
    returns "arbitrary_high") must NEVER be auto-merged, regardless of
    config.get_portfolio_auto_merge() — github_merge_pr must not even be
    called."""
    _patch_memory(monkeypatch)
    monkeypatch.setattr(runner, "analyze_release", lambda event: dict(_PROFILE))
    monkeypatch.setattr(runner, "curate", lambda profile, memory_context, delivery_id=None: dict(_FEATURE_NEW_DECISION))
    monkeypatch.setattr(config, "PORTFOLIO_AUTO_MERGE", True)
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
    monkeypatch.setattr(
        runner,
        "publish_to_portfolio",
        lambda *a, **k: {
            "mode": "arbitrary_high",
            "url": "https://github.com/owner/portfolio-demo/pull/10",
            "number": 10,
            "portfolio_repo": "owner/portfolio-demo",
            "auto_merge_suppressed": True,
        },
    )
    merge_called = {"value": False}
    monkeypatch.setattr(
        runner, "github_merge_pr", lambda *a, **k: merge_called.__setitem__("value", True) or {"merged": True, "sha": "x"}
    )
    monkeypatch.setattr(runner, "suggest_next_builds", lambda *a, **k: [])

    result = runner.run_agent({"delivery_id": "d11", "repo": "owner/repo", "tag": "v1.0"})

    assert merge_called["value"] is False  # never even attempted
    assert result["artifacts"]["portfolio_pr"] == "https://github.com/owner/portfolio-demo/pull/10"
    assert result["artifacts"]["portfolio_mode"] == "arbitrary_high"
    assert result["artifacts"]["portfolio_pr_merged"] is False
    assert "portfolio_pr_sha" not in result["artifacts"]


def test_tier2_exception_preserves_post_package_and_returns_normally(monkeypatch):
    """A Tier 2 failure (structure detection or format-matched generation
    raising) reaches runner.py through the exact same publish_to_portfolio
    exception path as a convention-path failure — post_package must
    survive and the run must complete normally (no 500, no crash)."""
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
        raise RuntimeError("Tier 2 structure detection exploded")

    monkeypatch.setattr(runner, "publish_to_portfolio", _boom)
    merge_called = {"value": False}
    monkeypatch.setattr(runner, "github_merge_pr", lambda *a, **k: merge_called.__setitem__("value", True) or {})
    monkeypatch.setattr(runner, "suggest_next_builds", lambda *a, **k: [])

    result = runner.run_agent({"delivery_id": "d12", "repo": "owner/repo", "tag": "v1.0"})

    assert result["action"] == "feature_new"  # the run completed normally, no crash
    assert result["artifacts"]["post_package"] == {
        "text": "Shipped a thing.",
        "hashtags": ["python"],
        "image_url": "data:x",
    }
    assert "portfolio_pr" not in result["artifacts"]
    assert "portfolio_mode" not in result["artifacts"]
    assert merge_called["value"] is False
