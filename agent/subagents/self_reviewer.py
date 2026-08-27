"""
LaunchPad-AI — Self-Reviewer (agent/subagents/self_reviewer.py).

Critiques the generated post package against a short rubric before it's
staged for the human's one-tap review, and allows ONE revision pass. Runs
BEFORE portfolio_publisher (see runner.py's wiring), so "card well-formed"
is judged against the CARD INPUTS (profile fields + positioning) that will
become the card, not a rendered card — no card exists yet at this point.

Plain Gemini call, same reasoning as content_writer.py: a single-shot
structured critique, no delegation, no ADK Runner needed.

Non-blocking by design: review() never prevents the pipeline from
continuing — a failed rubric just gets recorded (and the pipeline continues
with the original or revised post), since publishing is human-gated anyway.
review() CAN raise on a hard failure (network/auth/malformed output);
runner.py decides how to degrade, matching content_writer/image_tool.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel

from agent import config

_REVIEWER_INSTRUCTION = """\
You are the Self-Reviewer for LaunchPad-AI. Critique a LinkedIn post that's \
about to be staged for a human's one-tap review, against this rubric:
1. No unverifiable claims — nothing in the post text should assert facts \
not supported by the release profile (readme/summary/stack). Flag hype \
like specific performance numbers or user counts that aren't in the profile.
2. Hashtags are relevant to the actual technology/domain, not generic filler.
3. Voice is consistent with the given voice_profile's tone_notes.
4. The card inputs (profile name and summary, and the decision's \
positioning) are non-empty and coherent enough to build a portfolio card \
from. No rendered card exists yet at this point in the pipeline — judge \
only these inputs, not a finished card.

If ANYTHING fails, set passed=false, list the specific issues, and ALSO \
produce a revised_text and/or revised_hashtags that fixes them — this is \
the ONLY revision pass; there is no second review. If it already passes, \
leave revised_text and revised_hashtags null.

Return ONLY structured output matching the schema.
"""


class ReviewOutcome(BaseModel):
    passed: bool
    issues: list[str]
    revised_text: str | None = None
    revised_hashtags: list[str] | None = None


def _build_prompt(
    post_package: dict[str, Any],
    profile: dict[str, Any],
    decision: dict[str, Any],
    voice_profile: dict[str, Any],
) -> str:
    payload = {
        "post_package": post_package,
        "release_profile": {
            "name": profile.get("name"),
            "summary": profile.get("summary"),
            "stack": profile.get("stack"),
            "readme": profile.get("readme"),
        },
        "decision_positioning": decision.get("positioning"),
        "voice_profile": voice_profile,
    }
    return "Review this post package against the rubric.\n\n" + json.dumps(payload, indent=2, default=str)


def _call_gemini(prompt: str) -> ReviewOutcome:
    from google import genai
    from google.genai import types

    client = genai.Client()
    response = client.models.generate_content(
        model=config.GEMINI_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=_REVIEWER_INSTRUCTION,
            response_mime_type="application/json",
            response_schema=ReviewOutcome,
            temperature=0.2,
        ),
    )
    parsed = response.parsed
    if not isinstance(parsed, ReviewOutcome):
        raise RuntimeError(f"self-reviewer returned unparseable output: {response.text!r}")
    return parsed


def review(
    post_package: dict[str, Any],
    profile: dict[str, Any],
    decision: dict[str, Any],
    voice_profile: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Returns (final_post_package, review_outcome). May raise — see module docstring."""
    prompt = _build_prompt(post_package, profile, decision, voice_profile)
    outcome = _call_gemini(prompt)

    final_package = dict(post_package)
    revised = False
    if not outcome.passed:
        if outcome.revised_text:
            final_package["text"] = outcome.revised_text
            revised = True
        if outcome.revised_hashtags:
            final_package["hashtags"] = [tag.lstrip("#") for tag in outcome.revised_hashtags]
            revised = True

    review_outcome = {
        "passed": outcome.passed,
        "issues": outcome.issues,
        "revised": revised,
    }
    return final_package, review_outcome
