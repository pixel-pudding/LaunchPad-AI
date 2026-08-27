"""
LaunchPad-AI — unit tests for agent/tools/github_tool.py.

No live network: requests.get/post/put and _auth_headers are all
monkeypatched. Focuses on the two behaviors added for portfolio
publishing: github_get_file's 404-vs-200 handling, and github_open_pr's
create-vs-update (sha) logic — GitHub's Contents API requires the current
file's sha to overwrite an existing file and rejects it for a new one.
"""

from __future__ import annotations

import base64

from agent.tools import github_tool


class _FakeResponse:
    def __init__(self, status_code=200, json_data=None):
        self.status_code = status_code
        self._json_data = json_data or {}

    def json(self):
        return self._json_data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def _b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def test_github_get_file_returns_none_on_404(monkeypatch):
    monkeypatch.setattr(github_tool, "_auth_headers", lambda: {})
    monkeypatch.setattr(github_tool.requests, "get", lambda *a, **k: _FakeResponse(status_code=404))

    assert github_tool.github_get_file("owner/repo", "projects.json") is None


def test_github_get_file_decodes_base64_content(monkeypatch):
    monkeypatch.setattr(github_tool, "_auth_headers", lambda: {})
    monkeypatch.setattr(
        github_tool.requests,
        "get",
        lambda *a, **k: _FakeResponse(status_code=200, json_data={"content": _b64("[]")}),
    )

    assert github_tool.github_get_file("owner/repo", "projects.json") == "[]"


def _fake_get_for_open_pr(existing_file_status: int, existing_file_json: dict | None = None):
    def fake_get(url, headers=None, params=None, timeout=None):
        if url.endswith("/repos/owner/repo"):
            return _FakeResponse(json_data={"default_branch": "main"})
        if "git/ref/heads/main" in url:
            return _FakeResponse(json_data={"object": {"sha": "base-sha"}})
        if "/contents/projects.json" in url:
            return _FakeResponse(status_code=existing_file_status, json_data=existing_file_json)
        raise AssertionError(f"unexpected GET {url}")

    return fake_get


def _fake_post_for_open_pr(pr_url: str):
    def fake_post(url, headers=None, json=None, timeout=None):
        if "git/refs" in url:
            return _FakeResponse()
        if "/pulls" in url:
            return _FakeResponse(json_data={"html_url": pr_url})
        raise AssertionError(f"unexpected POST {url}")

    return fake_post


def test_github_open_pr_omits_sha_for_new_file(monkeypatch):
    monkeypatch.setattr(github_tool, "_auth_headers", lambda: {})
    put_calls = []

    monkeypatch.setattr(github_tool.requests, "get", _fake_get_for_open_pr(existing_file_status=404))
    monkeypatch.setattr(
        github_tool.requests, "post", _fake_post_for_open_pr("https://github.com/owner/repo/pull/1")
    )
    monkeypatch.setattr(
        github_tool.requests, "put", lambda url, headers=None, json=None, timeout=None: put_calls.append(json) or _FakeResponse()
    )

    url = github_tool.github_open_pr("owner/repo", "branch", "title", "body", {"projects.json": "[]"})

    assert url == "https://github.com/owner/repo/pull/1"
    assert "sha" not in put_calls[0]


def test_github_open_pr_includes_sha_for_existing_file(monkeypatch):
    monkeypatch.setattr(github_tool, "_auth_headers", lambda: {})
    put_calls = []

    monkeypatch.setattr(
        github_tool.requests,
        "get",
        _fake_get_for_open_pr(existing_file_status=200, existing_file_json={"sha": "existing-sha"}),
    )
    monkeypatch.setattr(
        github_tool.requests, "post", _fake_post_for_open_pr("https://github.com/owner/repo/pull/2")
    )
    monkeypatch.setattr(
        github_tool.requests, "put", lambda url, headers=None, json=None, timeout=None: put_calls.append(json) or _FakeResponse()
    )

    github_tool.github_open_pr("owner/repo", "branch", "title", "body", {"projects.json": "[]"})

    assert put_calls[0]["sha"] == "existing-sha"


def test_github_merge_pr_returns_merged_and_sha_on_success(monkeypatch):
    monkeypatch.setattr(github_tool, "_auth_headers", lambda: {})
    monkeypatch.setattr(
        github_tool.requests,
        "put",
        lambda url, headers=None, timeout=None: _FakeResponse(json_data={"merged": True, "sha": "abc123"}),
    )

    result = github_tool.github_merge_pr("owner/repo", 7)

    assert result == {"merged": True, "sha": "abc123"}


def test_github_merge_pr_raises_on_failure(monkeypatch):
    """Not mergeable / branch protection / permissions all surface as an
    HTTP error status — raise_for_status() must actually raise, not swallow
    it, so the caller (runner.py) can catch it and leave the PR open."""
    monkeypatch.setattr(github_tool, "_auth_headers", lambda: {})
    monkeypatch.setattr(
        github_tool.requests,
        "put",
        lambda url, headers=None, timeout=None: _FakeResponse(status_code=405, json_data={"message": "not mergeable"}),
    )

    import pytest

    with pytest.raises(RuntimeError):
        github_tool.github_merge_pr("owner/repo", 7)
