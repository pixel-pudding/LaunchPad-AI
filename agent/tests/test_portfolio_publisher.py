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


def _patch_common(monkeypatch, existing_projects_json):
    monkeypatch.setenv("PORTFOLIO_REPO", "owner/portfolio-demo")
    monkeypatch.setattr(portfolio_publisher, "github_get_file", lambda repo, path: existing_projects_json)

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
