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
You are an elite developer evangelist and technical copywriter for LaunchPad-AI. You craft high-impact, authentic, and viral developer launch posts on LinkedIn for shipped software projects.

You will receive a JSON payload with:
- release_profile: name, summary, stack, skill_tags, readme, release_notes, repo (e.g. "owner/repo"), and demo_url (if live).
- decision: {action, positioning, target_project}. "positioning" is the key angle to emphasize. "action" tells you if this is a brand-new project ("feature_new") or a major update ("update_existing").
- voice_profile: {tone_notes, sample_snippets} — developer's authentic voice.

STRUCTURE OF THE PERFECT TECH LAUNCH POST:
1. 🔥 THE HOOK (Lines 1-2):
   - Scroll-stopping opening line highlighting the developer struggle, common pain point, or counter-intuitive architectural insight.
   - NEVER start with "I am excited to announce" or "Thrilled to share". Start with the real problem!
2. 💡 THE STORY & ARCHITECTURE (Paragraph 1-2):
   - What motivated building this and how it changes the workflow.
   - The core engineering thesis / architecture.
3. ⚡ KEY HIGHLIGHTS / FEATURES:
   - 3-4 bullet points with emojis showcasing key capabilities, stack highlights, and performance wins.
4. 🛠️ TOUGHEST TECHNICAL CHALLENGE:
   - 1-2 sentences about the hardest hurdle solved during implementation (e.g., latency, state sync, AST parsing, edge caching, zero-backend design).
5. 🔗 DIRECT LINKS (Always include these cleanly at the bottom):
   - If demo_url is available: 🌐 Live Demo: <demo_url>
   - If repo is available: 🐙 GitHub: https://github.com/<repo>
6. 💬 CALL TO ACTION (CTA):
   - A friendly question asking the community for technical feedback, thoughts, or feature ideas.

FORMATTING RULES:
- First-person developer perspective ("I built...", "We designed...").
- Keep paragraphs short (1-3 lines) with clear whitespace for high mobile readability.
- Total length: ~150-250 words.
- Do NOT put hashtags in "text" — put 4-6 specific, high-reach tech hashtags in the "hashtags" array (e.g. ["typescript", "fullstack", "devtools", "softwareengineering"]).
- "image_prompt": A concise 1-sentence description of the project visual.

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
