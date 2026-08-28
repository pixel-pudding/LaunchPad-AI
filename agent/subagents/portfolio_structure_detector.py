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
You are an expert web developer updating a portfolio codebase with a release update.
The portfolio file format can be Vanilla HTML cards, React/Next.js JSX, Vue, Svelte, Markdown, or JavaScript/JSON arrays.

You must handle two actions based on the action field in the payload:

1. If action is "update_existing":
   - Find the EXISTING entry, card, JSX component, or object in current_file_content that corresponds to this project (matching by project name, repo name, or slug).
   - Set action_type = "update_existing".
   - Set target_to_replace: The EXACT multi-line character-for-character snippet from current_file_content representing ONLY that existing project entry.
   - Set entry_snippet: The updated entry in the exact same format and indentation, with the updated summary, new capabilities/version, tags, and screenshot image.
   - Do NOT add a duplicate card.

2. If action is "feature_new":
   - FIRST, scan current_file_content to check if this project already exists in the file (matching by project name, GitHub repo URL, or live URL — e.g. a legacy project built before LaunchPad-AI).
   - If it ALREADY exists: Do NOT create a duplicate card! Automatically treat it as "update_existing": set action_type = "update_existing", set target_to_replace to the exact existing project snippet, and provide the updated entry in entry_snippet.
   - If it is truly new and not present anywhere in current_file_content:
     - Set action_type = "feature_new".
     - Set anchor_context: An EXACT, UNIQUE 2-5 line excerpt from current_file_content right AFTER which the new project entry should be placed (such as the end of the preceding project card or array item, strictly INSIDE the projects container/list).
     - Set entry_snippet: The newly crafted project entry matching the codebase's existing style and structure.
     - If new_project.demo_url is provided and non-empty, include the Live link alongside GitHub repo. If demo_url is empty, only render the GitHub link.
     - If new_project.image_url is provided, use it directly as the image src in <img src="..." /> or image property.
     - In tags / stack chips, render 2 to 4 rich tags prioritizing meaningful frameworks, architectural concepts, and tools from project.stack (e.g., TypeScript, React, Next.js, WebSockets, OpenTelemetry) matching the style of existing cards in the file.

Also provide full_file_content as the complete updated file.
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
    action_type: Literal["update_existing", "feature_new"] = "feature_new"
    target_to_replace: str = ""
    anchor_context: str = ""
    target_anchor: str = ""
    entry_snippet: str = ""
    file_content: str = ""
    full_file_content: str = ""


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
    action = decision.get("action", "feature_new")
    raw_stack = profile.get("skill_tags") or profile.get("stack") or []
    clean_stack = []
    for s in raw_stack:
        if str(s).lower() in ("python-packaging", "ci-cd"):
            continue
        if str(s).lower() == "typescript":
            clean_stack.append("TypeScript")
        elif str(s).lower() == "javascript":
            clean_stack.append("JavaScript")
        elif str(s).lower() == "html":
            clean_stack.append("HTML")
        elif str(s).lower() == "css":
            clean_stack.append("CSS")
        elif str(s).lower() == "python":
            clean_stack.append("Python")
        elif str(s).lower() == "docker":
            clean_stack.append("Docker")
        elif str(s).lower() == "node":
            clean_stack.append("Node.js")
        else:
            clean_stack.append(s)

    payload = {
        "action": action,
        "current_file_content": current_content,
        "format": location.get("format"),
        "insertion_notes": location.get("insertion_notes"),
        "project": {
            "name": profile.get("name"),
            "summary": profile.get("summary"),
            "stack": clean_stack,
            "positioning": decision.get("positioning"),
            "image_url": post_package.get("image_url"),
            "demo_url": profile.get("demo_url"),
            "url": f"https://github.com/{repo}",
        },
    }
    instruction_text = (
        "Update the existing project entry in the file below in-place."
        if action == "update_existing"
        else "Add this new project entry to the file below, in its own format."
    )
    return instruction_text + "\n\n" + json.dumps(payload, indent=2, default=str)


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


def _splice_snippet(
    current_content: str, snippet: str, anchor: str = "", format_type: str = ""
) -> str:
    """Deterministically inserts `snippet` into `current_content` without
    rewriting or altering any other part of the file.
    """
    snippet = snippet.strip()
    if not snippet:
        return current_content

    # 1. Exact anchor match
    if anchor and anchor.strip() in current_content:
        anchor_clean = anchor.strip()
        idx = current_content.find(anchor_clean) + len(anchor_clean)
        return current_content[:idx] + "\n\n" + snippet + current_content[idx:]

    # 2. JSON/TS array fallback: find last '];' or ']'
    if "];" in current_content:
        idx = current_content.rfind("];")
        return current_content[:idx].rstrip().rstrip(",") + ",\n  " + snippet + "\n];" + current_content[idx + 2 :]

    if "]" in current_content:
        idx = current_content.rfind("]")
        return current_content[:idx].rstrip().rstrip(",") + ",\n  " + snippet + "\n]" + current_content[idx + 1 :]

    # 3. HTML / JSX fallback: find closing tag of previous project card
    markers = [
        "</div>\n                <div class=\"project-card-bar\"></div>\n            </div>",
        "</div>\n            </div>",
    ]
    for marker in markers:
        if marker in current_content:
            last_idx = current_content.rfind(marker) + len(marker)
            return current_content[:last_idx] + "\n\n" + snippet + current_content[last_idx:]

    return current_content + "\n\n" + snippet


def generate_format_matched_file(
    portfolio_repo: str,
    location: dict[str, Any],
    profile: dict[str, Any],
    decision: dict[str, Any],
    post_package: dict[str, Any],
    repo: str,
) -> str:
    """Returns the FULL edited content for location['file_path'], with a new
    or updated project entry spliced deterministically per location['insertion_notes'].
    """
    current_content = github_get_file(portfolio_repo, location["file_path"]) or ""
    if not current_content:
        return ""

    prompt = _build_edit_prompt(current_content, location, profile, decision, post_package, repo)
    result = _call_gemini_for_edit(prompt)

    action = decision.get("action", "feature_new")

    # 1. In-Place Update for UPDATE_EXISTING
    if (action == "update_existing" or result.action_type == "update_existing") and result.target_to_replace:
        target = result.target_to_replace.strip()
        if target and target in current_content and result.entry_snippet:
            return current_content.replace(target, result.entry_snippet.strip(), 1)

    # 2. Context Anchor Splicing for FEATURE_NEW
    if result.anchor_context and result.entry_snippet:
        anchor = result.anchor_context.strip()
        if anchor and anchor in current_content:
            idx = current_content.find(anchor) + len(anchor)
            return current_content[:idx] + "\n\n" + result.entry_snippet.strip() + current_content[idx:]

    # 3. Fallback: Check if Gemini returned full_file_content or file_content
    full_content = result.full_file_content or result.file_content
    if full_content and not result.entry_snippet:
        return full_content

    # 4. Deterministic Snippet Splice (Safe fallbacks)
    if result.entry_snippet:
        return _splice_snippet(
            current_content,
            result.entry_snippet,
            anchor=result.anchor_context or result.target_anchor,
            format_type=location.get("format", ""),
        )

    return full_content or current_content
