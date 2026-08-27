"""
LaunchPad-AI — unit tests for agent/subagents/portfolio_publisher.py.

Tests native framework portfolio publishing:
  - Structure detection invocation
  - Format-matched source code generation
  - PR opening with exact target files
  - Firestore project upsert
  - Auto-merge flag resolution
"""

from __future__ import annotations

from agent import memory
from agent.subagents import portfolio_publisher

_PROFILE = {
    "name": "postmortem-ai",
    "summary": "Autonomous AI incident analysis tool.",
    "demo_url": "https://postmortem-ai.vercel.app",
    "stack": ["typescript", "react"],
    "skill_tags": ["typescript", "react"],
    "readme": "# postmortem-ai",
    "images": [],
}

_DECISION = {
    "action": "feature_new",
    "reasoning": "Substantial full-stack incident tool.",
    "target_project": None,
    "positioning": "Highlight seven-step incident reasoning pipeline.",
    "next_build_suggestion": None,
}

_POST_PACKAGE = {"text": "Shipped PostMortem AI.", "hashtags": ["typescript"], "image_url": "https://img.png"}


def test_publish_returns_none_if_no_portfolio_repo(monkeypatch):
    monkeypatch.delenv("PORTFOLIO_REPO", raising=False)
    monkeypatch.setattr(memory, "get_portfolio_config", lambda client=None: None)
    result = portfolio_publisher.publish("owner/repo", _PROFILE, _DECISION, _POST_PACKAGE, "d1")
    assert result is None


def test_publish_high_confidence_creates_pr_and_upserts_project(monkeypatch):
    monkeypatch.setenv("PORTFOLIO_REPO", "owner/personal-portfolio")
    monkeypatch.setattr(memory, "get_portfolio_config", lambda client=None: {"auto_merge": True})

    monkeypatch.setattr(
        portfolio_publisher,
        "detect_structure",
        lambda repo: {
            "confidence": "high",
            "projects_location": {
                "file_path": "index.html",
                "format": "html_cards",
                "insertion_notes": "Add project card",
            },
            "reasoning": "Found index.html with HTML cards.",
        },
    )

    monkeypatch.setattr(
        portfolio_publisher,
        "generate_format_matched_file",
        lambda *a, **k: "<html><div class='project-card'>PostMortem AI</div></html>",
    )

    captured_pr = {}

    def fake_open_pr(repo, branch, title, body, files):
        captured_pr["repo"] = repo
        captured_pr["branch"] = branch
        captured_pr["title"] = title
        captured_pr["files"] = files
        return "https://github.com/owner/personal-portfolio/pull/10"

    monkeypatch.setattr(portfolio_publisher, "github_open_pr", fake_open_pr)

    upserted = {}
    monkeypatch.setattr(memory, "upsert_project", lambda repo, doc: upserted.update(doc))

    result = portfolio_publisher.publish("owner/postmortem-ai", _PROFILE, _DECISION, _POST_PACKAGE, "deliv-10")

    assert result["mode"] == "arbitrary_high"
    assert result["url"] == "https://github.com/owner/personal-portfolio/pull/10"
    assert result["number"] == 10
    assert result["portfolio_repo"] == "owner/personal-portfolio"
    assert result["auto_merge_suppressed"] is False

    assert captured_pr["repo"] == "owner/personal-portfolio"
    assert "index.html" in captured_pr["files"]
    assert "PostMortem AI" in captured_pr["files"]["index.html"]
    assert upserted["repo"] == "owner/postmortem-ai"
    assert upserted["status"] == "featured"


def test_publish_low_confidence_creates_markdown_pr(monkeypatch):
    monkeypatch.setenv("PORTFOLIO_REPO", "owner/personal-portfolio")
    monkeypatch.setattr(memory, "get_portfolio_config", lambda client=None: {"auto_merge": True})

    monkeypatch.setattr(
        portfolio_publisher,
        "detect_structure",
        lambda repo: {
            "confidence": "low",
            "projects_location": None,
            "reasoning": "Could not identify project section.",
        },
    )

    captured_pr = {}

    def fake_open_pr(repo, branch, title, body, files):
        captured_pr["repo"] = repo
        captured_pr["files"] = files
        return "https://github.com/owner/personal-portfolio/pull/11"

    monkeypatch.setattr(portfolio_publisher, "github_open_pr", fake_open_pr)
    monkeypatch.setattr(memory, "upsert_project", lambda *a, **k: None)

    result = portfolio_publisher.publish("owner/cli-tool", _PROFILE, _DECISION, _POST_PACKAGE, "deliv-11")

    assert result["mode"] == "arbitrary_low"
    assert result["number"] == 11
    assert any(k.endswith(".md") for k in captured_pr["files"].keys())
