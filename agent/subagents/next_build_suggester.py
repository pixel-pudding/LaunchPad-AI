"""
LaunchPad-AI — Next-Build Suggester (agent/subagents/next_build_suggester.py).

A SECONDARY, optional footnote to the main decision — the agent "finishes
the thought" about what the developer might naturally build next, grounded
ONLY in their own memory (already-featured projects + stated interests).
This is NOT career advice, NOT a skill-gap analysis, and NOT tied to any
job market or target role — see CLAUDE.md's scope boundary.

Plain Gemini call, same pattern as content_writer.py: a single-shot
structured-output call, no ADK Runner needed. Reads only already-fetched
memory (no new memory calls, no LinkedIn, no web) and is wired as the LAST
step in runner.py's pipeline, after portfolio_publisher, in its own
try/except — a failure here can never affect the decision, the post
package, or the portfolio PR.

suggest_next_builds() can raise (network/auth/malformed-output errors);
runner.py catches it and simply omits artifacts["next_builds"] for that run.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

from agent import config

_SUGGESTER_INSTRUCTION = """\
You are the Next-Build Suggester for LaunchPad-AI. This is a SECONDARY, \
optional footnote to the main decision — not career advice, not a \
skill-gap analysis, not tied to any job market or target role. You simply \
"finish the thought": given what the developer has already built, what \
would a natural next build be that extends or complements their existing \
work?

You will receive:
- featured_projects: the dev's currently-featured projects (name, summary, \
stack, skill_tags).
- context_profile: their stated interests and past projects — context only.

Suggest 1 to 3 concrete next-build ideas. Each must have:
- "title": a short, concrete project idea (an actual thing to build, not \
a skill to learn).
- "one_line_reason": ONE short sentence explicitly tying it to something \
they've ALREADY built or stated as an interest (e.g. "extends your \
local-rag-cli work with a hosted API", "complements your Discord bot with \
a web dashboard"). Never generic ("this would look good", "employers want \
this").

If there isn't enough real context here to ground a genuine suggestion, \
return an EMPTY suggestions list rather than inventing generic ideas. An \
honest empty result is always better than manufactured filler.

Return ONLY structured output matching the schema.
"""


class NextBuildSuggestion(BaseModel):
    title: str
    one_line_reason: str


class NextBuildSuggestions(BaseModel):
    suggestions: list[NextBuildSuggestion] = Field(min_length=0, max_length=3)


def _build_prompt(featured_projects: list[dict[str, Any]], context_profile: dict[str, Any]) -> str:
    payload = {
        "featured_projects": featured_projects,
        "context_profile": context_profile,
    }
    return "Suggest natural next builds, grounded only in this memory.\n\n" + json.dumps(
        payload, indent=2, default=str
    )


def _call_gemini(prompt: str) -> NextBuildSuggestions:
    from google import genai
    from google.genai import types

    client = genai.Client()
    response = client.models.generate_content(
        model=config.GEMINI_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=_SUGGESTER_INSTRUCTION,
            response_mime_type="application/json",
            response_schema=NextBuildSuggestions,
            temperature=0.4,
        ),
    )
    parsed = response.parsed
    if not isinstance(parsed, NextBuildSuggestions):
        raise RuntimeError(f"next-build suggester returned unparseable output: {response.text!r}")
    return parsed


def suggest_next_builds(
    featured_projects: list[dict[str, Any]],
    context_profile: dict[str, Any],
) -> list[dict[str, Any]]:
    """Returns 0-3 {title, one_line_reason} dicts. May raise — see module docstring."""
    prompt = _build_prompt(featured_projects, context_profile)
    result = _call_gemini(prompt)
    return [s.model_dump() for s in result.suggestions[:3]]
