"""
LaunchPad-AI — unit tests for agent/subagents/portfolio_repo_picker.py.

No live GitHub: github_list_installation_repos/github_get_file are patched
as `portfolio_repo_picker.<name>` (bound via `from ... import` at module
load, same reasoning as elsewhere in this codebase). Confirms the priority
order picks exactly ONE candidate, and that failing gracefully to "nothing
matches" is a valid, non-error outcome.
"""

from __future__ import annotations

from agent.subagents import portfolio_repo_picker


def _repo(full_name: str) -> dict:
    return {"full_name": full_name, "name": full_name.split("/", 1)[1]}


def test_github_io_repo_wins_top_priority(monkeypatch):
    repos = [_repo("octocat/some-project"), _repo("octocat/octocat.github.io"), _repo("octocat/portfolio")]
    monkeypatch.setattr(portfolio_repo_picker, "github_list_installation_repos", lambda: repos)

    result = portfolio_repo_picker.list_candidate_repos()

    flagged = [r for r in result if r["is_probable_portfolio"]]
    assert len(flagged) == 1
    assert flagged[0]["full_name"] == "octocat/octocat.github.io"
    assert len(result) == 3  # every repo still listed, just one flagged


def test_common_name_wins_when_no_github_io_repo(monkeypatch):
    repos = [_repo("octocat/some-project"), _repo("octocat/portfolio"), _repo("octocat/other")]
    monkeypatch.setattr(portfolio_repo_picker, "github_list_installation_repos", lambda: repos)

    result = portfolio_repo_picker.list_candidate_repos()

    flagged = [r for r in result if r["is_probable_portfolio"]]
    assert len(flagged) == 1
    assert flagged[0]["full_name"] == "octocat/portfolio"


def test_index_html_at_root_is_the_last_resort(monkeypatch):
    repos = [_repo("octocat/some-project"), _repo("octocat/other-project")]
    monkeypatch.setattr(portfolio_repo_picker, "github_list_installation_repos", lambda: repos)

    def fake_get_file(repo, path):
        return "<html></html>" if repo == "octocat/other-project" else None

    monkeypatch.setattr(portfolio_repo_picker, "github_get_file", fake_get_file)

    result = portfolio_repo_picker.list_candidate_repos()

    flagged = [r for r in result if r["is_probable_portfolio"]]
    assert len(flagged) == 1
    assert flagged[0]["full_name"] == "octocat/other-project"


def test_no_match_flags_nothing_not_an_error(monkeypatch):
    repos = [_repo("octocat/some-project"), _repo("octocat/other-project")]
    monkeypatch.setattr(portfolio_repo_picker, "github_list_installation_repos", lambda: repos)
    monkeypatch.setattr(portfolio_repo_picker, "github_get_file", lambda repo, path: None)

    result = portfolio_repo_picker.list_candidate_repos()

    assert len(result) == 2
    assert all(r["is_probable_portfolio"] is False for r in result)


def test_index_html_check_failure_on_one_repo_does_not_block_checking_the_rest(monkeypatch):
    repos = [_repo("octocat/broken"), _repo("octocat/has-index")]
    monkeypatch.setattr(portfolio_repo_picker, "github_list_installation_repos", lambda: repos)

    def fake_get_file(repo, path):
        if repo == "octocat/broken":
            raise RuntimeError("transient GitHub error")
        return "<html></html>"

    monkeypatch.setattr(portfolio_repo_picker, "github_get_file", fake_get_file)

    result = portfolio_repo_picker.list_candidate_repos()

    flagged = [r for r in result if r["is_probable_portfolio"]]
    assert len(flagged) == 1
    assert flagged[0]["full_name"] == "octocat/has-index"
