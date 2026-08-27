"""
LaunchPad-AI — unit tests for agent/subagents/portfolio_publisher.py.

No live GitHub/Firestore: github_get_file/github_open_pr are patched as
`portfolio_publisher.<name>` (they're bound via `from ... import` at module
load, so patching the originating github_tool module wouldn't take effect —
same reasoning as elsewhere in this codebase), and memory.upsert_project is
patched on the memory module, which portfolio_publisher accesses via
`memory.<name>(...)`.

Confirms the two behaviors Scenario 5 exists for: an already-featured repo
gets its EXISTING entry edited (never duplicated), and a new repo gets a
new entry appended — both independent of decision["action"].
"""

from __future__ import annotations

import json

from agent import memory
from agent.subagents import portfolio_publisher

_PROFILE = {
    "name": "local-rag-cli",
    "summary": "A from-scratch RAG pipeline.",
    "stack": ["python"],
    "skill_tags": ["python", "ml"],
    "readme": "# local-rag-cli",
    "images": [],
}

_DECISION = {
    "action": "update_existing",
    "reasoning": "adds a real capability",
    "target_project": "owner/local-rag-cli",
    "positioning": "Lead with the new hybrid search module.",
    "next_build_suggestion": None,
}

_POST_PACKAGE = {"text": "t", "hashtags": ["python"], "image_url": "data:image/svg+xml;base64,ZmFrZQ=="}


def _patch_common(monkeypatch, existing_projects_json, existing_skills_json="[]", portfolio_format=None):
    monkeypatch.setenv("PORTFOLIO_REPO", "owner/portfolio-demo")
    # config.get_portfolio_repo()/get_portfolio_format() check Firestore
    # config/portfolio first — without this, every test below would hit a
    # REAL firestore.Client() (slow, and fails with no credentials in this
    # sandbox). portfolio_format=None (the default) means the "format" key
    # is absent entirely — matching a repo that's never been explicitly
    # configured, which is what most of this file's tests assume; routing
    # still resolves to "convention" (the default) in that case. Pass
    # portfolio_format="arbitrary"/"convention" to simulate an explicit
    # picker choice.
    config_doc = {"format": portfolio_format} if portfolio_format is not None else None
    monkeypatch.setattr(memory, "get_portfolio_config", lambda client=None: config_doc)

    def fake_get_file(repo, path):
        if path == "projects.json":
            return existing_projects_json
        if path == "skills.json":
            return existing_skills_json
        raise AssertionError(f"unexpected github_get_file path: {path}")

    monkeypatch.setattr(portfolio_publisher, "github_get_file", fake_get_file)

    opened: dict = {}

    def fake_open_pr(repo, branch, title, body, files):
        opened.update(repo=repo, branch=branch, title=title, body=body, files=files)
        return "https://github.com/owner/portfolio-demo/pull/7"

    monkeypatch.setattr(portfolio_publisher, "github_open_pr", fake_open_pr)

    upserted: dict = {}
    monkeypatch.setattr(
        memory, "upsert_project", lambda repo, data, client=None: upserted.update(repo=repo, data=data)
    )
    return opened, upserted


def test_new_repo_appends_a_card(monkeypatch):
    opened, upserted = _patch_common(monkeypatch, existing_projects_json="[]")

    result = portfolio_publisher.publish(
        "owner/local-rag-cli", _PROFILE, _DECISION, _POST_PACKAGE, "delivery-1"
    )

    assert result == {"mode": "convention", "url": "https://github.com/owner/portfolio-demo/pull/7", "number": 7, "portfolio_repo": "owner/portfolio-demo"}
    projects = json.loads(opened["files"]["projects.json"])
    assert len(projects) == 1
    assert projects[0]["repo"] == "owner/local-rag-cli"
    assert projects[0]["image_url"] == _POST_PACKAGE["image_url"]
    assert upserted["repo"] == "owner/local-rag-cli"
    assert upserted["data"]["status"] == "featured"


def test_existing_repo_is_edited_not_duplicated(monkeypatch):
    existing = json.dumps(
        [
            {"repo": "owner/other-project", "name": "other-project"},
            {"repo": "owner/local-rag-cli", "name": "local-rag-cli", "summary": "stale summary"},
        ]
    )
    opened, _ = _patch_common(monkeypatch, existing_projects_json=existing)

    portfolio_publisher.publish("owner/local-rag-cli", _PROFILE, _DECISION, _POST_PACKAGE, "delivery-2")

    projects = json.loads(opened["files"]["projects.json"])
    assert len(projects) == 2  # not 3 — no duplicate
    matching = [p for p in projects if p["repo"] == "owner/local-rag-cli"]
    assert len(matching) == 1
    assert matching[0]["summary"] == _PROFILE["summary"]  # updated, not stale
    other = [p for p in projects if p["repo"] == "owner/other-project"]
    assert other[0]["name"] == "other-project"  # untouched


def test_publish_uses_delivery_id_in_branch_name(monkeypatch):
    opened, _ = _patch_common(monkeypatch, existing_projects_json="[]")

    portfolio_publisher.publish("owner/repo", _PROFILE, _DECISION, _POST_PACKAGE, "my-delivery-id")

    assert opened["branch"] == "launchpad-ai/my-delivery-id"


def test_defaulted_bootstrap_still_uses_convention_not_tier_2_but_suppresses_auto_merge(monkeypatch):
    """The exact scenario the format-routing fix exists for: a repo meant
    to use the convention (format never explicitly set — e.g. a fresh demo
    repo) whose projects.json simply hasn't been written yet. Routing keys
    off the RESOLVED format (defaults to "convention"), not file existence
    — so this must bootstrap via convention, NOT Tier 2. But since format
    was never explicitly confirmed, this specific first write isn't
    trusted with auto-merge — a review PR, not silence."""
    opened, _ = _patch_common(monkeypatch, existing_projects_json=None)

    result = portfolio_publisher.publish("owner/repo", _PROFILE, _DECISION, _POST_PACKAGE, "d")

    assert result["mode"] == "convention"
    assert "projects.json" in opened["files"]
    projects = json.loads(opened["files"]["projects.json"])
    assert len(projects) == 1
    assert result["auto_merge_suppressed"] is True


def test_explicit_convention_bootstrap_is_not_suppressed(monkeypatch):
    """Format explicitly confirmed "convention" via the picker — even on
    the very first write (projects.json absent), this counts as real
    evidence, not a guess, so auto-merge is NOT suppressed."""
    opened, _ = _patch_common(monkeypatch, existing_projects_json=None, portfolio_format="convention")

    result = portfolio_publisher.publish("owner/repo", _PROFILE, _DECISION, _POST_PACKAGE, "d")

    assert result["mode"] == "convention"
    assert "auto_merge_suppressed" not in result


def test_post_bootstrap_release_is_not_suppressed_regardless_of_format(monkeypatch):
    """Once projects.json exists, is_bootstrap is False — confident is True
    regardless of whether format was ever explicitly set. Every release
    after the first auto-merges normally with no further configuration."""
    opened, _ = _patch_common(monkeypatch, existing_projects_json="[]")  # format defaulted, file exists

    result = portfolio_publisher.publish("owner/repo", _PROFILE, _DECISION, _POST_PACKAGE, "d")

    assert result["mode"] == "convention"
    assert "auto_merge_suppressed" not in result


def test_explicit_arbitrary_format_routes_to_tier_2_even_if_projects_json_would_be_absent(monkeypatch):
    """format explicitly "arbitrary" is the ONLY thing that routes to Tier
    2 now — not file absence."""
    opened, _ = _patch_common(monkeypatch, existing_projects_json=None, portfolio_format="arbitrary")
    monkeypatch.setattr(
        portfolio_publisher,
        "detect_structure",
        lambda portfolio_repo: {"confidence": "low", "projects_location": None, "reasoning": "n/a"},
    )

    result = portfolio_publisher.publish("owner/repo", _PROFILE, _DECISION, _POST_PACKAGE, "d")

    assert result["mode"] == "arbitrary_low"
    assert "projects.json" not in opened["files"]


def test_parse_pr_number_handles_multi_digit_numbers():
    assert portfolio_publisher._parse_pr_number("https://github.com/owner/repo/pull/142") == 142


def test_detection_is_independent_of_decision_action(monkeypatch):
    """decision.action says feature_new, but the repo is ALREADY in
    projects.json — ground truth (the actual file) must win, editing in
    place rather than trusting the (possibly stale) decision label."""
    existing = json.dumps([{"repo": "owner/already-there", "name": "already-there"}])
    opened, _ = _patch_common(monkeypatch, existing_projects_json=existing)
    feature_new_decision = dict(_DECISION, action="feature_new", target_project=None)

    portfolio_publisher.publish(
        "owner/already-there", _PROFILE, feature_new_decision, _POST_PACKAGE, "d"
    )

    projects = json.loads(opened["files"]["projects.json"])
    assert len(projects) == 1  # edited, not appended as a duplicate


def test_new_skills_are_merged_and_deduped_case_insensitively(monkeypatch):
    profile = dict(_PROFILE, stack=["python", "PYTHON", "rust"])  # dup within the release itself too
    opened, _ = _patch_common(
        monkeypatch,
        existing_projects_json="[]",
        existing_skills_json=json.dumps(["Python", "Docker"]),
    )

    portfolio_publisher.publish("owner/local-rag-cli", profile, _DECISION, _POST_PACKAGE, "d")

    skills = json.loads(opened["files"]["skills.json"])
    assert skills == ["Python", "Docker", "Rust"]  # existing untouched, one new entry, no dup


def test_casing_map_applied_to_new_skills_only(monkeypatch):
    profile = dict(_PROFILE, stack=["python", "javascript", "fastapi", "css", "obscure-thing"])
    opened, _ = _patch_common(monkeypatch, existing_projects_json="[]", existing_skills_json="[]")

    portfolio_publisher.publish("owner/repo", profile, _DECISION, _POST_PACKAGE, "d")

    skills = json.loads(opened["files"]["skills.json"])
    assert skills == ["Python", "JavaScript", "FastAPI", "CSS", "Obscure-Thing"]  # map hits + .title() fallback


def test_no_new_skills_leaves_skills_json_out_of_the_pr(monkeypatch):
    """Every stack entry already present (case-insensitively) — no-op, so
    skills.json shouldn't even be part of this PR's files."""
    profile = dict(_PROFILE, stack=["python", "PYTHON"])
    opened, _ = _patch_common(
        monkeypatch, existing_projects_json="[]", existing_skills_json=json.dumps(["Python"])
    )

    portfolio_publisher.publish("owner/repo", profile, _DECISION, _POST_PACKAGE, "d")

    assert "skills.json" not in opened["files"]
    assert "projects.json" in opened["files"]  # the card update still happens


def test_missing_skills_json_bootstraps_from_empty_list(monkeypatch):
    opened, _ = _patch_common(monkeypatch, existing_projects_json="[]", existing_skills_json=None)

    portfolio_publisher.publish("owner/repo", _PROFILE, _DECISION, _POST_PACKAGE, "d")

    assert json.loads(opened["files"]["skills.json"]) == ["Python"]


def test_skills_update_failure_preserves_card_and_pr(monkeypatch):
    """A skills.json bug (or a transient GitHub error fetching it) must
    never cost the project card or the PR itself."""
    opened, upserted = _patch_common(monkeypatch, existing_projects_json="[]")

    def _boom(portfolio_repo):
        raise RuntimeError("transient GitHub error")

    monkeypatch.setattr(portfolio_publisher, "_load_skills", _boom)

    result = portfolio_publisher.publish("owner/repo", _PROFILE, _DECISION, _POST_PACKAGE, "d")

    assert result == {"mode": "convention", "url": "https://github.com/owner/portfolio-demo/pull/7", "number": 7, "portfolio_repo": "owner/portfolio-demo"}
    assert "skills.json" not in opened["files"]
    assert "projects.json" in opened["files"]
    assert json.loads(opened["files"]["projects.json"])[0]["repo"] == "owner/repo"
    assert upserted["repo"] == "owner/repo"  # Firestore backfill still happened


def test_merge_skills_returns_none_when_nothing_new():
    assert portfolio_publisher._merge_skills(["Python", "Rust"], ["python", "RUST"]) is None


def test_display_case_uses_known_map_then_title_fallback():
    assert portfolio_publisher._display_case("python") == "Python"
    assert portfolio_publisher._display_case("sql") == "SQL"
    assert portfolio_publisher._display_case("go") == "Go"  # not in map -> .title() fallback


def test_publish_returns_none_when_no_portfolio_configured(monkeypatch, caplog):
    """No Firestore config/portfolio and no PORTFOLIO_REPO env — an
    expected "not set up yet" state, not a failure: publish() returns None
    (not raise), logged at INFO, and touches no GitHub API at all."""
    monkeypatch.delenv("PORTFOLIO_REPO", raising=False)
    monkeypatch.setattr(memory, "get_portfolio_config", lambda client=None: None)

    def _fail_if_called(*args, **kwargs):
        raise AssertionError("github_open_pr should never be called with no portfolio configured")

    monkeypatch.setattr(portfolio_publisher, "github_open_pr", _fail_if_called)

    import logging

    with caplog.at_level(logging.INFO):
        result = portfolio_publisher.publish(
            "owner/repo", _PROFILE, _DECISION, _POST_PACKAGE, "d"
        )

    assert result is None
    assert any(record.levelno == logging.INFO for record in caplog.records)
    assert not any(record.levelno >= logging.ERROR for record in caplog.records)


def test_publish_uses_firestore_configured_repo_over_env(monkeypatch):
    """Firestore config/portfolio wins over PORTFOLIO_REPO env — the UI
    choice, once made, takes priority over the deployment default."""
    monkeypatch.setenv("PORTFOLIO_REPO", "owner/env-repo")
    monkeypatch.setattr(
        memory, "get_portfolio_config", lambda client=None: {"portfolio_repo": "owner/firestore-repo"}
    )
    monkeypatch.setattr(portfolio_publisher, "github_get_file", lambda repo, path: "[]")

    opened: dict = {}

    def fake_open_pr(repo, branch, title, body, files):
        opened["repo"] = repo
        return "https://github.com/owner/firestore-repo/pull/1"

    monkeypatch.setattr(portfolio_publisher, "github_open_pr", fake_open_pr)
    monkeypatch.setattr(memory, "upsert_project", lambda repo, data, client=None: None)

    result = portfolio_publisher.publish("owner/repo", _PROFILE, _DECISION, _POST_PACKAGE, "d")

    assert opened["repo"] == "owner/firestore-repo"
    assert result["portfolio_repo"] == "owner/firestore-repo"


# ── Tier 2: arbitrary-portfolio support ──────────────────────────────────
#
# detect_structure/generate_format_matched_file are patched as
# `portfolio_publisher.<name>` — bound via `from ... import` at module
# load, same reasoning as github_get_file/github_open_pr above. The
# detector's own confidence-downgrade guardrail is tested directly in
# test_portfolio_structure_detector.py; these tests confirm publish()
# correctly ROUTES based on whatever detect_structure() reports.


def test_arbitrary_high_confidence_opens_format_matched_pr(monkeypatch):
    opened, _ = _patch_common(monkeypatch, existing_projects_json=None, portfolio_format="arbitrary")
    monkeypatch.setattr(
        portfolio_publisher,
        "detect_structure",
        lambda portfolio_repo: {
            "confidence": "high",
            "projects_location": {
                "file_path": "src/data/projects.json",
                "format": "json_array",
                "insertion_notes": "append an object",
            },
            "reasoning": "found it",
        },
    )
    monkeypatch.setattr(
        portfolio_publisher,
        "generate_format_matched_file",
        lambda portfolio_repo, location, profile, decision, post_package, repo: '[{"title": "new"}]',
    )

    result = portfolio_publisher.publish("owner/repo", _PROFILE, _DECISION, _POST_PACKAGE, "d")

    assert result["mode"] == "arbitrary_high"
    assert result["auto_merge_suppressed"] is True
    assert opened["files"] == {"src/data/projects.json": '[{"title": "new"}]'}
    assert "review before merging" in opened["body"].lower()
    assert "src/data/projects.json" in opened["body"]


def test_arbitrary_low_confidence_adds_standalone_file_touches_nothing_existing(monkeypatch):
    opened, _ = _patch_common(monkeypatch, existing_projects_json=None, portfolio_format="arbitrary")
    monkeypatch.setattr(
        portfolio_publisher,
        "detect_structure",
        lambda portfolio_repo: {"confidence": "low", "projects_location": None, "reasoning": "unsure"},
    )

    result = portfolio_publisher.publish("owner/local-rag-cli", _PROFILE, _DECISION, _POST_PACKAGE, "d")

    assert result["mode"] == "arbitrary_low"
    assert result["auto_merge_suppressed"] is True
    assert len(opened["files"]) == 1
    ((path, content),) = opened["files"].items()
    assert path.startswith("launchpad-ai/")
    assert path.endswith(".md")
    assert "local-rag-cli" in content
    assert "nothing in your existing site was changed" in opened["body"].lower()


def test_confidence_downgrade_result_routes_through_content_only_path(monkeypatch):
    """detect_structure() forces confidence to "low" when the model names a
    file outside the fetched listing (tested directly in
    test_portfolio_structure_detector.py). This confirms publish() honors
    whatever detect_structure() reports — a downgraded result routes
    through the exact same content-only path as a genuinely low confidence,
    with no special-casing that could accidentally still edit a file."""
    opened, _ = _patch_common(monkeypatch, existing_projects_json=None, portfolio_format="arbitrary")
    monkeypatch.setattr(
        portfolio_publisher,
        "detect_structure",
        lambda portfolio_repo: {
            "confidence": "low",
            "projects_location": None,
            "reasoning": "Model claimed high confidence citing an unlisted file — downgraded.",
        },
    )

    result = portfolio_publisher.publish("owner/repo", _PROFILE, _DECISION, _POST_PACKAGE, "d")

    assert result["mode"] == "arbitrary_low"
    assert len(opened["files"]) == 1  # only the standalone content file — nothing else touched


def test_arbitrary_path_uses_tag_in_content_filename(monkeypatch):
    opened, _ = _patch_common(monkeypatch, existing_projects_json=None, portfolio_format="arbitrary")
    monkeypatch.setattr(
        portfolio_publisher,
        "detect_structure",
        lambda portfolio_repo: {"confidence": "low", "projects_location": None, "reasoning": "n/a"},
    )

    portfolio_publisher.publish("owner/repo", _PROFILE, _DECISION, _POST_PACKAGE, "d", tag="v2.0")

    (path,) = opened["files"].keys()
    assert path == "launchpad-ai/owner-repo-v2.0.md"


def test_arbitrary_path_falls_back_to_delivery_id_when_tag_missing(monkeypatch):
    opened, _ = _patch_common(monkeypatch, existing_projects_json=None, portfolio_format="arbitrary")
    monkeypatch.setattr(
        portfolio_publisher,
        "detect_structure",
        lambda portfolio_repo: {"confidence": "low", "projects_location": None, "reasoning": "n/a"},
    )

    portfolio_publisher.publish("owner/repo", _PROFILE, _DECISION, _POST_PACKAGE, "delivery-xyz")

    (path,) = opened["files"].keys()
    assert path == "launchpad-ai/owner-repo-delivery-xyz.md"


def test_build_standalone_markdown_includes_title_description_stack_link():
    md = portfolio_publisher._build_standalone_markdown("owner/repo", _PROFILE, _DECISION, _POST_PACKAGE)

    assert _PROFILE["name"] in md
    assert _PROFILE["summary"] in md
    for skill in _PROFILE["stack"]:
        assert skill in md
    assert "https://github.com/owner/repo" in md
