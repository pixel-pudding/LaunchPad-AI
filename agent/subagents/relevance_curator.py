"""
LaunchPad-AI — Relevance Curator (agent/subagents/relevance_curator.py).

This is CLAUDE.md's "agentic rule": a genuine LLM decision among
feature_new / update_existing / skip, using memory of what's already featured
plus the dev's interests/past projects, with written reasoning. It is a real
ADK LlmAgent executed through the ADK Runner — not a plain function pretending
to decide.

The Release Analyst runs BEFORE this, as ordinary deterministic Python (see
release_analyst.py); its output is passed in as context on the user turn,
not offered as a callable tool — this agent takes no tools and makes one
single-shot structured-output decision per call.

curate() never raises: any failure (LLM error, malformed output, auth/network
issues) is caught and mapped to a "skip" decision. Skip is the only safe
failure direction — defaulting to "feature" on an internal error would
silently publish something no one reviewed.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import uuid
from typing import Any, Literal

from google.adk.agents import LlmAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from pydantic import BaseModel

from agent import config

logger = logging.getLogger(__name__)


class CuratorDecision(BaseModel):
    action: Literal["feature_new", "update_existing", "skip"]
    reasoning: str
    target_project: str | None = None
    positioning: str
    next_build_suggestion: str | None = None


_CURATOR_INSTRUCTION = """\
You are the Relevance Curator for LaunchPad-AI, an agent that keeps a \
developer's portfolio site and LinkedIn presence in sync with what they \
actually ship. You make ONE decision per GitHub release: action = \
"feature_new", "update_existing", or "skip".

You will receive, as the user message, a JSON payload with three parts:
- release_profile: the shipped repo's name, summary, stack, skill_tags, \
readme, images.
- already_featured: projects already featured on the portfolio/LinkedIn \
(each has at least a repo and status).
- dev_context: the developer's stated interests and past projects — \
CONTEXT ONLY.

DECISION RULES (follow these; they are not suggestions):
1. If the release's repo already appears in already_featured, you may NEVER \
return "feature_new" for it. Your only choices for an already-featured repo \
are "update_existing" or "skip".
2. Return "skip" when the release is not notable: trivial version bumps, \
dependency or lockfile-only bumps, typo/doc-only fixes, empty or boilerplate \
READMEs, or a README that explicitly signals WIP/experimental/tutorial-clone/ \
learning-exercise. This applies EVEN IF the repo is already featured — a \
trivial patch to a featured project is still "skip", not an automatic \
"update_existing".
3. Return "update_existing" only when an already-featured repo's release \
adds something genuinely new (a real capability, a meaningful expansion) — \
set target_project to the repo key of the existing entry being updated.
4. Return "feature_new" for a new (not-yet-featured), substantial, complete \
piece of shipped work — a real README, real functionality, not a stub.
5. dev_context (interests/past projects) informs "positioning" — how to \
frame the project — and may tip a genuinely borderline case, but it NEVER \
disqualifies an otherwise-substantial, complete project just because it's \
outside stated interests. A well-built project outside the dev's usual \
focus is still "feature_new" if it's real and complete.
6. "positioning" is the angle to emphasize in the eventual post/portfolio \
entry (1-2 sentences). For "skip", set it to "".
7. "next_build_suggestion" is a secondary, optional footnote — a brief idea \
for what to build next, grounded in dev_context. Omit it (null) unless \
something genuinely obvious comes to mind; do not force one.
8. Always write specific "reasoning" that references the actual content you \
were given (repo name, what changed, what's already featured) — never \
generic boilerplate like "this seems like a good fit."

EXAMPLES (input summarized, output shown):

Example A — trivial release, not yet featured:
  release_profile: repo "utils-bump", summary "Bump lodash to 4.17.21", \
stack: [javascript], readme has nothing beyond a changelog line.
  already_featured: [] (not featured)
  -> {"action": "skip", "reasoning": "A dependency version bump with no new \
capability or documentation — not notable enough to feature.", \
"target_project": null, "positioning": "", "next_build_suggestion": null}

Example B — already featured, but this release is trivial:
  release_profile: repo "rag-pipeline", tag v2.3.1, summary "Fix typo in \
README".
  already_featured: [{"repo": "dev/rag-pipeline", "status": "featured"}]
  -> {"action": "skip", "reasoning": "rag-pipeline is already featured, but \
this release only fixes a typo — no new capability to update the entry \
with.", "target_project": null, "positioning": "", \
"next_build_suggestion": null}

Example C — substantial new project, matches interests:
  release_profile: repo "local-rag-cli", summary "A from-scratch retrieval \
pipeline with a CLI and eval harness", stack: [python], readme is thorough.
  dev_context: interests include "LLM tooling", "developer tools".
  already_featured: [] (not featured)
  -> {"action": "feature_new", "reasoning": "A complete, well-documented RAG \
pipeline with its own eval harness — substantial, original work that lines \
up directly with the dev's stated LLM-tooling focus.", "target_project": \
null, "positioning": "Lead with the from-scratch retrieval pipeline and the \
eval harness — ties directly to their LLM tooling focus.", \
"next_build_suggestion": null}

Example D — already featured, this release adds something real:
  release_profile: repo "rag-pipeline", tag v3.0.0, summary "Added \
real-time streaming responses and a new evaluation dashboard".
  already_featured: [{"repo": "dev/rag-pipeline", "status": "featured"}]
  -> {"action": "update_existing", "reasoning": "rag-pipeline is already \
featured, and this release adds real-time streaming plus a new eval \
dashboard — a genuine capability worth updating the existing entry with, \
not a new post.", "target_project": "dev/rag-pipeline", "positioning": \
"Update the existing entry to highlight the new streaming support and eval \
dashboard.", "next_build_suggestion": null}

Return ONLY the decision as structured output matching the schema.
"""

curator_agent = LlmAgent(
    name="relevance_curator",
    model=config.GEMINI_MODEL,
    description=(
        "Decides whether a shipped GitHub release should be featured on the "
        "portfolio/LinkedIn as a new entry, folded into an existing one, or skipped."
    ),
    instruction=_CURATOR_INSTRUCTION,
    output_schema=CuratorDecision,
    output_key="decision",
    generate_content_config=types.GenerateContentConfig(temperature=0.2),
)

_APP_NAME = "launchpad-ai-curator"
_USER_ID = "launchpad-ai"
_session_service = InMemorySessionService()
_runner = Runner(app_name=_APP_NAME, agent=curator_agent, session_service=_session_service)

_FAILURE_DECISION: dict[str, Any] = {
    "action": "skip",
    "reasoning": "curator error — failed closed to skip",
    "target_project": None,
    "positioning": "",
    "next_build_suggestion": None,
}


def _run_sync(coro):
    """Runs a coroutine to completion from a plain sync call, safe even when
    called from inside an already-running event loop (e.g. FastAPI's
    /process, or ADK's own loop when curate() is invoked as a root_agent
    tool). Mirrors the thread-isolation trick ADK's own Runner.run() uses
    internally (verified against the installed ADK 2.7.1 source).
    """
    box: dict[str, Any] = {}

    def _target() -> None:
        try:
            box["result"] = asyncio.run(coro)
        except BaseException as exc:  # re-raised on the caller's thread below
            box["error"] = exc

    thread = threading.Thread(target=_target)
    thread.start()
    thread.join()
    if "error" in box:
        raise box["error"]
    return box["result"]


def _build_prompt(profile: dict[str, Any], memory_context: dict[str, Any]) -> str:
    payload = {
        "release_profile": profile,
        "already_featured": memory_context.get("featured_projects", []),
        "dev_context": memory_context.get("context_profile", {}),
    }
    return (
        "A new GitHub release just shipped. Decide: feature_new, "
        "update_existing, or skip.\n\n" + json.dumps(payload, indent=2, default=str)
    )


async def _invoke_curator_async(prompt: str, session_id: str) -> dict[str, Any]:
    await _session_service.create_session(
        app_name=_APP_NAME, user_id=_USER_ID, session_id=session_id
    )
    decision: dict[str, Any] = {}
    async for event in _runner.run_async(
        user_id=_USER_ID,
        session_id=session_id,
        new_message=types.Content(role="user", parts=[types.Part(text=prompt)]),
    ):
        if "decision" in event.actions.state_delta:
            decision = event.actions.state_delta["decision"]
    return decision


def curate(
    profile: dict[str, Any],
    memory_context: dict[str, Any],
    delivery_id: str | None = None,
) -> dict[str, Any]:
    """Runs the real relevance decision through the ADK Runner.

    Returns {action, reasoning, target_project, positioning, next_build_suggestion}.
    Never raises — see module docstring on why skip is the failure direction.
    """
    session_id = f"curator-{delivery_id}" if delivery_id else f"curator-{uuid.uuid4()}"
    prompt = _build_prompt(profile, memory_context)
    try:
        raw = _run_sync(_invoke_curator_async(prompt, session_id))
        if not raw:
            raise RuntimeError("curator returned no structured decision")
        return {
            "action": raw.get("action", "skip"),
            "reasoning": raw.get("reasoning", ""),
            "target_project": raw.get("target_project"),
            "positioning": raw.get("positioning", ""),
            "next_build_suggestion": raw.get("next_build_suggestion"),
        }
    except Exception:
        logger.error("Relevance Curator failed — falling back to skip", exc_info=True)
        return dict(_FAILURE_DECISION)
