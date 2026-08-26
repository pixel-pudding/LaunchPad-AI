"""
LaunchPad-AI — root ADK agent (agent/agent.py).

ENTRY POINT for `adk web` / `adk run`. Model + framework are frozen in
CLAUDE.md and enforced loudly by agent/config.py on import (Gemini >= 3.5,
Vertex AI only).

analyze_release (release_analyst) is a plain deterministic function; curate
(relevance_curator) is a plain function too, but internally runs a real ADK
LlmAgent through its own Runner + session — see relevance_curator.py. Both
are wired here as `tools=` rather than `sub_agents=`, since `sub_agents` is
for LLM-driven delegation between BaseAgent instances in one conversation,
which isn't the shape of either call here. Production runs (agent/runner.py)
call analyze_release/curate directly and don't go through this root_agent at
all; this root_agent exists for interactive use via `adk web`.
"""

from __future__ import annotations

from google.adk.agents import Agent

from agent.config import GEMINI_MODEL
from agent.subagents.relevance_curator import curate
from agent.subagents.release_analyst import analyze_release

root_agent = Agent(
    name="launchpad_orchestrator",
    model=GEMINI_MODEL,
    description=(
        "Root orchestrator for LaunchPad-AI: on each GitHub release, decides "
        "whether to feature it, update an existing entry, or skip it, and "
        "keeps a developer's portfolio site and LinkedIn presence in sync."
    ),
    instruction=(
        "You are the orchestrator for LaunchPad-AI, an agent that keeps a "
        "developer's portfolio site and LinkedIn presence in sync with what "
        "they ship. You have two tools: analyze_release (fetches and profiles "
        "a GitHub repo) and curate (the real featuring decision — feature_new, "
        "update_existing, or skip, with reasoning). Use analyze_release first "
        "on a repo, then pass its output into curate along with any known "
        "memory context."
    ),
    tools=[analyze_release, curate],
)
