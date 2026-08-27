"""
LaunchPad-AI — Portfolio Structure Detector (agent/subagents/
portfolio_structure_detector.py).

Tier 2 support for portfolio repos that don't follow the projects.json
convention (see portfolio_publisher.py's convention path). detect_structure()
is READ-ONLY: it fetches a shallow, capped file listing and the contents of
a few likely candidates to figure out WHERE (if anywhere) project entries
live and in what format — it never writes, commits, or opens anything.
portfolio_publisher.py decides what to DO with the result.

Two plain Gemini calls (not ADK sub-agents — same reasoning as
content_writer.py: single-shot structured tasks, no delegation):
  - detect_structure(): classifies confidence + location + format.
  - generate_format_matched_file(): only called on high confidence, returns
    the full edited file content in the repo's own existing format.

A deterministic guardrail sits on top of the model's own confidence claim
in detect_structure(): if it names a file_path that wasn't actually in the
listing fetched, "high" is forced down to "low". The model's self-report is
never trusted alone for something this consequential — a wrong
high-confidence answer means editing the wrong file in someone's live site.
"""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel

from agent import config
from agent.tools.github_tool import github_get_file, github_list_repo_shallow

_MAX_FILES_LISTED = 40
_MAX_CANDIDATE_CONTENTS = 5
_MAX_CONTENT_CHARS_PER_FILE = 4000
_CONTENT_PRIORITY_KEYWORDS = ("project", "portfolio", "work")

_DETECTOR_INSTRUCTION = """\
You are the Portfolio Structure Detector for LaunchPad-AI. This repo does \
NOT use the projects.json convention. Given a listing of its files and the \
contents of a few likely candidates, decide: where (if anywhere) do this \
site's project/portfolio entries live, and in what format?

Only claim "high" confidence if you can point to a SPECIFIC file, already \
present in the listing you were given, that clearly holds a list of \
projects (an array of objects, a set of markdown cards, repeated JSX/HTML \
blocks, etc.) — not a component or config file that merely renders \
projects from elsewhere. If you are not genuinely sure, or the file you \
would name isn't one of the files given to you, say confidence "low" and \
leave projects_location null. A wrong high-confidence answer means editing \
the wrong file in someone's live site — "low" is always the safer honest \
answer when in doubt.

If confidence is "high", also describe (insertion_notes) exactly how a NEW \
project entry should be shaped to match this file's existing pattern — \
field names, structure, surrounding syntax.

Return ONLY structured output matching the schema.
"""

_EDIT_INSTRUCTION = """\
You are editing a portfolio site file to add ONE new project entry, in \
this file's OWN existing format — do not change the file's structure, \
styling, other entries, or anything unrelated. Match the exact conventions \
(quoting, indentation, field names) already used in the file. Return the \
COMPLETE new file content, not a diff or a snippet.

Return ONLY structured output matching the schema.
"""


class ProjectsLocation(BaseModel):
    file_path: str
    format: Literal["json_array", "jsx_array", "html_cards", "markdown_frontmatter", "other"]
    insertion_notes: str


class StructureDetection(BaseModel):
    confidence: Literal["high", "low"]
    projects_location: ProjectsLocation | None = None
    reasoning: str


class FormatMatchedEdit(BaseModel):
    file_content: str


def _pick_candidate_files_for_content(listing: list[str], limit: int) -> list[str]:
    """Deterministic heuristic, not a model call: files whose path mentions
    project/portfolio/work are more likely to hold project entries."""

    def score(path: str) -> int:
        lower = path.lower()
        return sum(1 for kw in _CONTENT_PRIORITY_KEYWORDS if kw in lower)

    return sorted(listing, key=score, reverse=True)[:limit]


def _build_detection_prompt(listing: list[str], candidate_contents: dict[str, str]) -> str:
    payload = {"file_listing": listing, "candidate_file_contents": candidate_contents}
    return "Where do this repo's project entries live, if anywhere?\n\n" + json.dumps(
        payload, indent=2, default=str
    )


def _call_gemini_for_detection(prompt: str) -> StructureDetection:
    from google import genai
    from google.genai import types

    client = genai.Client()
    response = client.models.generate_content(
        model=config.GEMINI_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=_DETECTOR_INSTRUCTION,
            response_mime_type="application/json",
            response_schema=StructureDetection,
            temperature=0.2,
        ),
    )
    parsed = response.parsed
    if not isinstance(parsed, StructureDetection):
        raise RuntimeError(f"structure detector returned unparseable output: {response.text!r}")
    return parsed


def detect_structure(portfolio_repo: str) -> dict[str, Any]:
    """Returns {confidence, projects_location: {...} | None, reasoning}.

    READ-ONLY: only fetches (github_list_repo_shallow, github_get_file) —
    never writes, commits, or opens a PR. May raise (network/auth/malformed
    output) — portfolio_publisher.py decides how to degrade.
    """
    listing = github_list_repo_shallow(portfolio_repo, max_files=_MAX_FILES_LISTED)
    candidate_paths = _pick_candidate_files_for_content(listing, _MAX_CANDIDATE_CONTENTS)

    candidate_contents: dict[str, str] = {}
    for path in candidate_paths:
        content = github_get_file(portfolio_repo, path)
        if content is not None:
            candidate_contents[path] = content[:_MAX_CONTENT_CHARS_PER_FILE]

    prompt = _build_detection_prompt(listing, candidate_contents)
    result = _call_gemini_for_detection(prompt)

    # Deterministic guardrail: never trust a "high" claim naming a file we
    # didn't actually see in the fetched listing.
    if result.confidence == "high" and (
        result.projects_location is None or result.projects_location.file_path not in listing
    ):
        claimed = result.projects_location.file_path if result.projects_location else "none"
        result = StructureDetection(
            confidence="low",
            projects_location=None,
            reasoning=(
                f"Model claimed high confidence citing {claimed!r}, which isn't in the "
                "fetched listing — downgraded to low rather than trusting the self-report."
            ),
        )

    return result.model_dump()


def _build_edit_prompt(
    current_content: str,
    location: dict[str, Any],
    profile: dict[str, Any],
    decision: dict[str, Any],
    post_package: dict[str, Any],
    repo: str,
) -> str:
    payload = {
        "current_file_content": current_content,
        "format": location.get("format"),
        "insertion_notes": location.get("insertion_notes"),
        "new_project": {
            "name": profile.get("name"),
            "summary": profile.get("summary"),
            "stack": profile.get("stack"),
            "positioning": decision.get("positioning"),
            "image_url": post_package.get("image_url"),
            "url": f"https://github.com/{repo}",
        },
    }
    return "Add this new project entry to the file below, in its own format.\n\n" + json.dumps(
        payload, indent=2, default=str
    )


def _call_gemini_for_edit(prompt: str) -> FormatMatchedEdit:
    from google import genai
    from google.genai import types

    client = genai.Client()
    response = client.models.generate_content(
        model=config.GEMINI_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=_EDIT_INSTRUCTION,
            response_mime_type="application/json",
            response_schema=FormatMatchedEdit,
            temperature=0.3,
        ),
    )
    parsed = response.parsed
    if not isinstance(parsed, FormatMatchedEdit):
        raise RuntimeError(f"format-matched editor returned unparseable output: {response.text!r}")
    return parsed


def generate_format_matched_file(
    portfolio_repo: str,
    location: dict[str, Any],
    profile: dict[str, Any],
    decision: dict[str, Any],
    post_package: dict[str, Any],
    repo: str,
) -> str:
    """Returns the FULL edited content for location['file_path'], with a new
    project entry added per location['insertion_notes']. Only reads from
    GitHub itself (github_get_file) — portfolio_publisher.py is what
    actually writes the result, via github_open_pr. May raise.
    """
    current_content = github_get_file(portfolio_repo, location["file_path"]) or ""
    prompt = _build_edit_prompt(current_content, location, profile, decision, post_package, repo)
    result = _call_gemini_for_edit(prompt)
    return result.file_content
