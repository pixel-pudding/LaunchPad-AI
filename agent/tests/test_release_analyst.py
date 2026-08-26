"""
LaunchPad-AI — unit tests for agent/subagents/release_analyst.py.

No live network: analyze_release() is tested with github_get_repo
monkeypatched to a recorded fixture; build_profile() (the pure derivation)
is tested directly against that same fixture.
"""

from __future__ import annotations

from agent.subagents import release_analyst

_SAMPLE_REPO_DATA = {
    "name": "launchpad-ai-demo",
    "description": "A demo Gemini + ADK agent.",
    "readme": "# LaunchPad AI Demo\n\nA small ADK agent built with Python and Gemini.\n",
    "langs": ["Python", "Dockerfile"],
    "tree": ["agent", "Dockerfile", "pyproject.toml", "README.md"],
    "images": ["https://example.com/preview.png"],
}


def test_build_profile_maps_fields():
    profile = release_analyst.build_profile(_SAMPLE_REPO_DATA)
    assert profile["name"] == "launchpad-ai-demo"
    assert profile["summary"] == "A demo Gemini + ADK agent."
    assert profile["stack"] == ["python", "dockerfile"]
    assert profile["readme"] == _SAMPLE_REPO_DATA["readme"]
    assert profile["images"] == ["https://example.com/preview.png"]


def test_build_profile_derives_skill_tags_from_marker_files():
    profile = release_analyst.build_profile(_SAMPLE_REPO_DATA)
    assert "docker" in profile["skill_tags"]
    assert "python-packaging" in profile["skill_tags"]


def test_build_profile_falls_back_to_readme_when_no_description():
    repo_data = dict(_SAMPLE_REPO_DATA, description="")
    profile = release_analyst.build_profile(repo_data)
    assert profile["summary"] == "LaunchPad AI Demo"


def test_analyze_release_calls_github_get_repo_with_event_repo(monkeypatch):
    captured = {}

    def fake_github_get_repo(repo: str) -> dict:
        captured["repo"] = repo
        return _SAMPLE_REPO_DATA

    monkeypatch.setattr(release_analyst, "github_get_repo", fake_github_get_repo)

    event = {
        "delivery_id": "d1",
        "event_type": "release",
        "repo": "owner/launchpad-ai-demo",
        "tag": "v1.0",
        "release_name": "v1.0",
    }
    profile = release_analyst.analyze_release(event)

    assert captured["repo"] == "owner/launchpad-ai-demo"
    assert profile["name"] == "launchpad-ai-demo"
