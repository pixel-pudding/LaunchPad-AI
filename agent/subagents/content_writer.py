"""
LaunchPad-AI — Content Writer (agent/subagents/content_writer.py).

Given the project profile, the Relevance Curator's decision (action,
positioning, target_project), and the dev's voice profile from memory,
writes the DRAFT post content: LinkedIn-length text with a hook in the
first two lines, hashtags, and an image prompt for Imagen. The final
{text, hashtags, image_url} shape is assembled downstream by announcer.py
once image_tool has turned the image_prompt into an actual image_url.

DESIGN CHOICE — plain Gemini call, not an ADK sub-agent (unlike the
Relevance Curator):
- The curator had to be a real ADK LlmAgent through the Runner — that's
  CLAUDE.md's frozen agentic rule, specifically about the multi-way
  DECISION. Content generation is a downstream, single-shot "write
  structured text from a prompt" task: no memory across turns, no
  delegation, nothing that needs ADK's session/Runner machinery to be
  genuine.
- google-genai's plain generate_content(..., response_schema=...) gives the
  same structured-output guarantee (via response.parsed) as ADK's
  output_schema, without a Runner, a SessionService, or the thread-isolation
  wrapper the curator needs just to call async ADK code synchronously —
  this call is synchronous already. Less code, less surface area, in the
  "keep it small" spirit of this change.
- ADK's framework requirement for the hackathon is already satisfied by
  root_agent + the curator; not every LLM call needs to go through it.

write_content() can raise (network/auth/malformed-output errors) — it does
NOT swallow its own failures the way curate() does. runner.py decides how to
degrade per step (log and skip the rest of content generation for this run)
rather than every subagent independently deciding "fail to X is always
safe", which was specifically true for the curator's skip default but isn't
a meaningful default here (there's no safe fallback post to write).
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel

from agent import config

_WRITER_INSTRUCTION = """\
You are the Content Writer for LaunchPad-AI. You write ONE LinkedIn post \
announcing a developer's shipped project, in the developer's own voice.

You will receive a JSON payload with:
- release_profile: the shipped repo's name, summary, stack, skill_tags, readme.
- decision: {action, positioning, target_project} from the Relevance \
Curator. "positioning" is the angle to emphasize. "action" tells you \
whether this is a brand-new project (feature_new) or an update to an \
already-featured entry (update_existing) — if it's an update, frame the \
post as an update/expansion, not as if the project is brand new.
- voice_profile: {tone_notes, sample_snippets} — the developer's actual \
voice. Match this tone. If it's empty, default to a genuine, specific, \
professional-but-personal voice — never generic corporate-marketing copy.

Write:
- "text": the LinkedIn post body. The FIRST ONE TO TWO LINES must hook the \
reader before LinkedIn's "see more" fold — lead with the interesting \
detail or outcome, not "Excited to announce...". Aim for roughly 100-200 \
words total, first person, as the developer. Do NOT include hashtags in \
this field — they go in "hashtags" only.
- "hashtags": 3-6 relevant hashtags as bare words with NO "#" prefix, \
specific to the actual technology/domain — not generic filler like \
"coding" or "technology" alone.
- "image_prompt": a short (1-2 sentence), concrete, specific visual \
description for an image generator, matching the project's theme and the \
positioning — not an abstract cliché like "a laptop with code".

Return ONLY structured output matching the schema.
"""


class ContentDraft(BaseModel):
    text: str
    hashtags: list[str]
    image_prompt: str


def _build_prompt(profile: dict[str, Any], decision: dict[str, Any], voice_profile: dict[str, Any]) -> str:
    payload = {
        "release_profile": profile,
        "decision": {
            "action": decision.get("action"),
            "positioning": decision.get("positioning"),
            "target_project": decision.get("target_project"),
        },
        "voice_profile": voice_profile,
    }
    return "Write the LinkedIn post package for this shipped release.\n\n" + json.dumps(
        payload, indent=2, default=str
    )


def _call_gemini(prompt: str) -> ContentDraft:
    from google import genai
    from google.genai import types

    client = genai.Client()
    response = client.models.generate_content(
        model=config.GEMINI_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=_WRITER_INSTRUCTION,
            response_mime_type="application/json",
            response_schema=ContentDraft,
            temperature=0.7,
        ),
    )
    parsed = response.parsed
    if not isinstance(parsed, ContentDraft):
        raise RuntimeError(f"content writer returned unparseable output: {response.text!r}")
    return parsed


def write_content(
    profile: dict[str, Any],
    decision: dict[str, Any],
    voice_profile: dict[str, Any],
) -> dict[str, Any]:
    """Returns {text, hashtags, image_prompt}. May raise — see module docstring."""
    prompt = _build_prompt(profile, decision, voice_profile)
    draft = _call_gemini(prompt)
    return {
        "text": draft.text,
        "hashtags": [tag.lstrip("#") for tag in draft.hashtags],
        "image_prompt": draft.image_prompt,
    }
