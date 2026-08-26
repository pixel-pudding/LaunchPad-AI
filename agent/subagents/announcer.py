"""
LaunchPad-AI — Announcer (agent/subagents/announcer.py).

Assembles the FINAL post package from the Content Writer's draft plus the
generated image, in the EXACT shape the dashboard reads:
server.py's /api/latest-post -> dashboard.js -> {text, hashtags[], image_url}.

No auto-posting — this is staged for the human's one-tap review only
(the dashboard's "Copy all" + prefilled LinkedIn share link).

Pure and defensive on purpose: this is the last step before the shape hits
Firestore and then the dashboard, so it never trusts the draft blindly
(re-strips any stray "#" on hashtags, coerces missing fields to safe
defaults) even though content_writer should already produce clean output.
"""

from __future__ import annotations

from typing import Any


def assemble_post_package(draft: dict[str, Any], image_url: str) -> dict[str, Any]:
    """Returns {text, hashtags, image_url} — exactly what dashboard.js reads."""
    hashtags = [str(tag).lstrip("#").strip() for tag in draft.get("hashtags", []) if str(tag).strip()]
    return {
        "text": str(draft.get("text", "")).strip(),
        "hashtags": hashtags,
        "image_url": image_url or "",
    }
