"""
LaunchPad-AI — Firestore Seeding Script (infra/seed_firestore.py)

Seeds only the baseline memory that the agent cannot bootstrap itself:
  - voice/profile: Personal tone guidelines for LinkedIn posts
    (the content writer and self-reviewer read this)

context/profile is deliberately NOT seeded — the profile_bootstrapper
synthesizes it live from the user's public GitHub on first release,
which is the "fully agentic" demo story.

The old targets/roles, skill_map/current, and roadmap/current seeds
have been removed — the curator never read them.

Usage:
  python infra/seed_firestore.py
"""

from __future__ import annotations

import os
from google.cloud import firestore

PROJECT_ID = os.environ.get("GOOGLE_CLOUD_PROJECT", "launchpad-ai-506616")


def seed_firestore() -> None:
    print(f"Connecting to Firestore in project: {PROJECT_ID}...")
    db = firestore.Client(project=PROJECT_ID)

    # voice/profile — tone guidelines for the content writer + self-reviewer
    voice_data = {
        "tone_notes": "First-person, humble yet technically sharp, builder-focused. Avoid excessive corporate buzzwords or hyperbole. Highlight architectural decisions, lessons learned, and why the project was built. Short punchy paragraphs with clear bullet points.",
        "sample_snippets": [
            "I got tired of updating my portfolio manually after every release, so I built an autonomous agent to do it for me.",
            "The hardest part wasn't the LLM reasoning — it was building a reliable, event-driven serverless pipeline on Google Cloud that handles async execution gracefully.",
        ],
    }
    print("Writing voice/profile...")
    db.collection("voice").document("profile").set(voice_data, merge=True)

    print("Firestore seeding complete! voice/profile populated.")
    print("Note: context/profile is NOT seeded — the agent bootstraps it from GitHub on first release.")


if __name__ == "__main__":
    seed_firestore()

