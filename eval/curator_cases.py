"""
LaunchPad-AI — labeled eval cases for the Relevance Curator.

10 hand-authored cases spanning all three actions (4 skip / 3 feature_new /
3 update_existing). Two are canaries — the specific "never becomes a script"
guardrails from CLAUDE.md's agentic rule — and are asserted as HARD pytest
failures in test_curator_canaries.py:
  - already_featured_trivial_patch_skip: proves update isn't automatic just
    because a repo is already featured.
  - already_featured_major_new_capability_update_existing: proves a genuine
    new capability on a featured repo updates rather than skips.

The full set is scored as a reported pass rate by run_curator_eval.py, since
LLM output is probabilistic even at low temperature and a single flaky case
isn't a build break.

All cases are self-contained (hand-crafted profile + memory_context) — no
live GitHub or Firestore calls.
"""

from __future__ import annotations

from typing import Any, TypedDict


class Case(TypedDict):
    name: str
    profile: dict[str, Any]
    memory_context: dict[str, Any]
    expected_action: str
    canary: bool


def _profile(
    name: str,
    summary: str,
    stack: list[str],
    skill_tags: list[str],
    readme: str,
    images: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "name": name,
        "summary": summary,
        "stack": stack,
        "skill_tags": skill_tags,
        "readme": readme,
        "images": images or [],
    }


_DEV_CONTEXT = {
    "interests": ["LLM tooling", "developer tools", "ML infrastructure"],
    "past_projects": ["a small CLI note-taking tool", "a Discord bot"],
}


CASES: list[Case] = [
    {
        "name": "trivial_patch_new_repo_skip",
        "profile": _profile(
            "utils-bump",
            "Bump lodash to 4.17.21",
            ["javascript"],
            ["javascript"],
            "# utils-bump\n\nSee CHANGELOG.\n",
        ),
        "memory_context": {"featured_projects": [], "context_profile": _DEV_CONTEXT},
        "expected_action": "skip",
        "canary": False,
    },
    {
        "name": "toy_tutorial_clone_skip",
        "profile": _profile(
            "todo-app-tutorial",
            "",
            ["javascript"],
            ["javascript"],
            "# Todo App\n\nFollowed a tutorial to build a todo app.\n",
        ),
        "memory_context": {"featured_projects": [], "context_profile": _DEV_CONTEXT},
        "expected_action": "skip",
        "canary": False,
    },
    {
        "name": "already_featured_trivial_patch_skip",
        "profile": _profile(
            "rag-pipeline",
            "Fix typo in README",
            ["python"],
            ["python", "ml"],
            "# RAG Pipeline\n\nFix typo.\n",
        ),
        "memory_context": {
            "featured_projects": [
                {"repo": "dev/rag-pipeline", "name": "rag-pipeline", "status": "featured"}
            ],
            "context_profile": _DEV_CONTEXT,
        },
        "expected_action": "skip",
        "canary": True,
    },
    {
        "name": "wip_experimental_new_repo_skip",
        "profile": _profile(
            "new-idea-experiment",
            "An experiment I'm playing with, WIP, not ready.",
            ["python"],
            ["python"],
            "# new-idea-experiment\n\nWIP — experimental, half-finished, do not use yet.\n",
        ),
        "memory_context": {"featured_projects": [], "context_profile": _DEV_CONTEXT},
        "expected_action": "skip",
        "canary": False,
    },
    {
        "name": "substantial_new_project_matches_interests_feature_new",
        "profile": _profile(
            "local-rag-cli",
            "A from-scratch retrieval-augmented generation pipeline with a CLI and eval harness.",
            ["python"],
            ["python", "ml", "rag", "cli"],
            "# local-rag-cli\n\nA complete RAG pipeline built from scratch: chunking, "
            "embedding, retrieval, a CLI, and an eval harness comparing retrieval "
            "strategies.\n",
            images=["https://example.com/demo.png"],
        ),
        "memory_context": {"featured_projects": [], "context_profile": _DEV_CONTEXT},
        "expected_action": "feature_new",
        "canary": False,
    },
    {
        "name": "substantial_new_project_outside_interests_still_feature_new",
        "profile": _profile(
            "trailrun-tracker",
            "A full-stack mobile app for tracking trail runs with GPS maps and elevation charts.",
            ["swift", "python"],
            ["swift", "ios", "mobile", "python"],
            "# trailrun-tracker\n\nA complete iOS app: GPS tracking, elevation charts, a "
            "Python backend for route sync, and a polished onboarding flow.\n",
        ),
        "memory_context": {"featured_projects": [], "context_profile": _DEV_CONTEXT},
        "expected_action": "feature_new",
        "canary": False,
    },
    {
        "name": "well_documented_new_release_feature_new",
        "profile": _profile(
            "config-doctor",
            "A CLI that lints and auto-fixes common misconfigurations in dotfiles and CI configs.",
            ["rust"],
            ["rust", "cli", "dev-tools"],
            "# config-doctor\n\nA polished Rust CLI with a plugin system, 40+ built-in "
            "checks, colored diff output, and a full test suite.\n",
        ),
        "memory_context": {"featured_projects": [], "context_profile": _DEV_CONTEXT},
        "expected_action": "feature_new",
        "canary": False,
    },
    {
        "name": "already_featured_major_new_capability_update_existing",
        "profile": _profile(
            "rag-pipeline",
            "Added real-time streaming responses and a new evaluation dashboard.",
            ["python"],
            ["python", "ml", "rag"],
            "# RAG Pipeline\n\nv3.0: real-time streaming responses, plus a new web "
            "dashboard for comparing eval runs side by side.\n",
        ),
        "memory_context": {
            "featured_projects": [
                {"repo": "dev/rag-pipeline", "name": "rag-pipeline", "status": "featured"}
            ],
            "context_profile": _DEV_CONTEXT,
        },
        "expected_action": "update_existing",
        "canary": True,
    },
    {
        "name": "already_featured_modest_genuine_improvement_update_existing",
        "profile": _profile(
            "config-doctor",
            "Added a new plugin for Docker Compose linting.",
            ["rust"],
            ["rust", "cli"],
            "# config-doctor\n\nv1.4: added a Docker Compose linting plugin with 8 new "
            "checks.\n",
        ),
        "memory_context": {
            "featured_projects": [
                {"repo": "dev/config-doctor", "name": "config-doctor", "status": "featured"}
            ],
            "context_profile": _DEV_CONTEXT,
        },
        "expected_action": "update_existing",
        "canary": False,
    },
    {
        "name": "already_featured_significant_new_module_update_existing",
        "profile": _profile(
            "local-rag-cli",
            "Added a new hybrid search module combining BM25 and vector search.",
            ["python"],
            ["python", "ml", "rag"],
            "# local-rag-cli\n\nv2.0: new hybrid search module (BM25 + vector), roughly "
            "20% better retrieval accuracy in the built-in eval harness.\n",
        ),
        "memory_context": {
            "featured_projects": [
                {"repo": "dev/local-rag-cli", "name": "local-rag-cli", "status": "featured"}
            ],
            "context_profile": _DEV_CONTEXT,
        },
        "expected_action": "update_existing",
        "canary": False,
    },
]
