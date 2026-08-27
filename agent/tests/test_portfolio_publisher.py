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


def _patch_common(monkeypatch, existing_projects_json, existing_skills_json="[]"):
    monkeypatch.setenv("PORTFOLIO_REPO", "owner/portfolio-demo")

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

    pr_url = portfolio_publisher.publish(
        "owner/local-rag-cli", _PROFILE, _DECISION, _POST_PACKAGE, "delivery-1"
    )

    assert pr_url == "https://github.com/owner/portfolio-demo/pull/7"
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


def test_missing_projects_json_defaults_to_empty_list(monkeypatch):
    opened, _ = _patch_common(monkeypatch, existing_projects_json=None)

    portfolio_publisher.publish("owner/repo", _PROFILE, _DECISION, _POST_PACKAGE, "d")

    projects = json.loads(opened["files"]["projects.json"])
    assert len(projects) == 1


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

    pr_url = portfolio_publisher.publish("owner/repo", _PROFILE, _DECISION, _POST_PACKAGE, "d")

    assert pr_url == "https://github.com/owner/portfolio-demo/pull/7"
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
