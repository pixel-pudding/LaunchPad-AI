"""
LaunchPad-AI — unit tests for the three portfolio-repo-picker HTTP endpoints
added to server.py: GET /api/repos, POST /api/portfolio-config,
GET /api/portfolio-config.

No live GitHub/Firestore: server.py's route handlers do a LAZY import
(`from agent.subagents.portfolio_repo_picker import list_candidate_repos`,
`from agent import memory`) INSIDE each handler, re-executed on every
request — so patching the attribute on the originating module
(`portfolio_repo_picker.list_candidate_repos`, `memory.set_portfolio_config`,
`memory.get_portfolio_config`) is what actually takes effect here, same
reasoning as everywhere else lazy imports show up in this codebase.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from agent import memory
from agent.subagents import portfolio_repo_picker
from server import app

client = TestClient(app)


def test_api_repos_returns_wrapping_object_with_one_probable_portfolio(monkeypatch):
    monkeypatch.setattr(
        portfolio_repo_picker,
        "list_candidate_repos",
        lambda: [
            {"full_name": "octocat/some-project", "name": "some-project", "is_probable_portfolio": False},
            {"full_name": "octocat/octocat.github.io", "name": "octocat.github.io", "is_probable_portfolio": True},
        ],
    )

    resp = client.get("/api/repos")

    assert resp.status_code == 200
    body = resp.json()
    assert body["error"] is None
    assert len(body["repos"]) == 2
    flagged = [r for r in body["repos"] if r["is_probable_portfolio"]]
    assert len(flagged) == 1
    assert flagged[0]["full_name"] == "octocat/octocat.github.io"


def test_api_repos_failure_returns_empty_list_and_error_not_500(monkeypatch):
    def _boom():
        raise RuntimeError("GitHub App not installed on this account")

    monkeypatch.setattr(portfolio_repo_picker, "list_candidate_repos", _boom)

    resp = client.get("/api/repos")

    assert resp.status_code == 200  # never 500s, per the graceful-failure requirement
    body = resp.json()
    assert body["repos"] == []
    assert "GitHub App not installed" in body["error"]


def test_portfolio_config_post_then_get_roundtrips(monkeypatch):
    saved: dict = {}

    def fake_set(portfolio_repo, auto_merge, format=None, client=None):
        saved["portfolio_repo"] = portfolio_repo
        saved["auto_merge"] = auto_merge

    monkeypatch.setattr(memory, "set_portfolio_config", fake_set)
    monkeypatch.setattr(
        memory,
        "get_portfolio_config",
        lambda client=None: dict(saved, ts="2026-08-27T00:00:00+00:00") if saved else None,
    )

    post_resp = client.post(
        "/api/portfolio-config", json={"portfolio_repo": "owner/portfolio-demo", "auto_merge": False}
    )
    assert post_resp.status_code == 200
    assert post_resp.json() == {"ok": True, "error": None}

    get_resp = client.get("/api/portfolio-config")
    assert get_resp.status_code == 200
    assert get_resp.json() == {
        "portfolio_repo": "owner/portfolio-demo",
        "auto_merge": False,
        "ts": "2026-08-27T00:00:00+00:00",
    }


def test_portfolio_config_get_returns_null_when_never_configured(monkeypatch):
    monkeypatch.setattr(memory, "get_portfolio_config", lambda client=None: None)

    resp = client.get("/api/portfolio-config")

    assert resp.status_code == 200
    assert resp.json() is None


def test_portfolio_config_post_failure_returns_ok_false_not_500(monkeypatch):
    def _boom(portfolio_repo, auto_merge, format=None, client=None):
        raise RuntimeError("Firestore unavailable")

    monkeypatch.setattr(memory, "set_portfolio_config", _boom)

    resp = client.post("/api/portfolio-config", json={"portfolio_repo": "owner/repo", "auto_merge": True})

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert "Firestore unavailable" in body["error"]
