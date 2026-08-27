"""
LaunchPad-AI — unit tests for agent/subagents/portfolio_structure_detector.py.

No live GitHub/Vertex AI: github_list_repo_shallow/github_get_file are
patched as `portfolio_structure_detector.<name>` (bound via `from ...
import` at module load — same reasoning as elsewhere in this codebase), and
_call_gemini_for_detection/_call_gemini_for_edit are monkeypatched directly
to avoid any live model call.

The one behavior this module exists to guarantee: the model's own "high"
confidence claim is NEVER trusted alone — if it names a file outside the
listing actually fetched, it's forced down to "low" before
portfolio_publisher.py ever sees it.
"""

from __future__ import annotations

from agent.subagents import portfolio_structure_detector as detector


def test_high_confidence_passes_through_when_file_was_in_the_listing(monkeypatch):
    monkeypatch.setattr(detector, "github_list_repo_shallow", lambda repo, max_files=40: ["src/data/projects.json"])
    monkeypatch.setattr(detector, "github_get_file", lambda repo, path: "[]")
    monkeypatch.setattr(
        detector,
        "_call_gemini_for_detection",
        lambda prompt: detector.StructureDetection(
            confidence="high",
            projects_location=detector.ProjectsLocation(
                file_path="src/data/projects.json",
                format="json_array",
                insertion_notes="append an object with title/description/stack/link",
            ),
            reasoning="Found a clear array of project objects.",
        ),
    )

    result = detector.detect_structure("owner/repo")

    assert result["confidence"] == "high"
    assert result["projects_location"]["file_path"] == "src/data/projects.json"


def test_high_confidence_is_downgraded_when_model_names_an_unlisted_file(monkeypatch):
    """The guardrail this module exists for: the model's self-reported
    "high" confidence is never trusted alone."""
    monkeypatch.setattr(detector, "github_list_repo_shallow", lambda repo, max_files=40: ["src/App.jsx"])
    monkeypatch.setattr(detector, "github_get_file", lambda repo, path: "export default App;")
    monkeypatch.setattr(
        detector,
        "_call_gemini_for_detection",
        lambda prompt: detector.StructureDetection(
            confidence="high",
            projects_location=detector.ProjectsLocation(
                file_path="src/data/projects.json",  # NOT in the listing above
                format="json_array",
                insertion_notes="whatever",
            ),
            reasoning="I'm sure it's here.",
        ),
    )

    result = detector.detect_structure("owner/repo")

    assert result["confidence"] == "low"
    assert result["projects_location"] is None
    assert "src/data/projects.json" in result["reasoning"]


def test_low_confidence_passes_through_unchanged(monkeypatch):
    monkeypatch.setattr(detector, "github_list_repo_shallow", lambda repo, max_files=40: ["src/App.jsx"])
    monkeypatch.setattr(detector, "github_get_file", lambda repo, path: "export default App;")
    monkeypatch.setattr(
        detector,
        "_call_gemini_for_detection",
        lambda prompt: detector.StructureDetection(
            confidence="low", projects_location=None, reasoning="Nothing recognizable."
        ),
    )

    result = detector.detect_structure("owner/repo")

    assert result == {"confidence": "low", "projects_location": None, "reasoning": "Nothing recognizable."}


def test_pick_candidate_files_prioritizes_project_keyword_matches():
    listing = ["src/App.jsx", "src/data/projects.json", "README.md", "src/pages/portfolio.astro"]

    result = detector._pick_candidate_files_for_content(listing, limit=2)

    assert set(result) == {"src/data/projects.json", "src/pages/portfolio.astro"}


def test_generate_format_matched_file_returns_model_output(monkeypatch):
    monkeypatch.setattr(detector, "github_get_file", lambda repo, path: "[{\"title\": \"old\"}]")
    monkeypatch.setattr(
        detector,
        "_call_gemini_for_edit",
        lambda prompt: detector.FormatMatchedEdit(file_content='[{"title": "old"}, {"title": "new"}]'),
    )

    location = {
        "file_path": "src/data/projects.json",
        "format": "json_array",
        "insertion_notes": "append an object",
    }
    result = detector.generate_format_matched_file(
        "owner/portfolio", location, {"name": "new"}, {"positioning": "x"}, {"image_url": ""}, "owner/new"
    )

    assert result == '[{"title": "old"}, {"title": "new"}]'


def test_detect_structure_never_writes_anything():
    """detect_structure() must be read-only: this module never even imports
    a write-capable GitHub tool function — asserting that directly against
    its actual namespace, not just prose in a docstring."""
    assert not hasattr(detector, "github_open_pr")
    assert not hasattr(detector, "github_merge_pr")
