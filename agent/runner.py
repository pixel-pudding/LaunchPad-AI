"""
LaunchPad-AI — Agent runner (the seam).

This module is OWNED BY Claude Code [CC]. [AG] calls run_agent() from
the /process route but NEVER modifies this file.

This is a STUB so server.py can import it before the real agent is built.
[CC] will replace this with the real implementation.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def run_agent(event: dict) -> dict:
    """
    The seam function from WORK_SPLIT.md §1.

    event = the Pub/Sub message:
    {
        "delivery_id": "str",
        "repo": "owner/name",
        "default_branch": "main",
        "commits": [{"message": "str"}],
        "pusher": "str"
    }

    Returns the decision record that also gets written to Firestore.

    THIS IS A STUB — [CC] replaces this with the real ADK agent pipeline.
    """
    logger.info(
        "STUB run_agent called: repo=%s delivery=%s",
        event.get("repo"),
        event.get("delivery_id"),
    )
    return {
        "status": "stub",
        "delivery_id": event.get("delivery_id"),
        "repo": event.get("repo"),
        "action": "skip",
        "reasoning": "Agent not implemented yet — stub response",
    }
