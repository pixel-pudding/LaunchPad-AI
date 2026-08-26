"""
LaunchPad-AI — Firestore Seeding Script (infra/seed_firestore.py)

Populates baseline career memory collections in Firestore:
  - targets/roles: Target roles and reference job descriptions
  - skill_map/current: Current skill coverage scores and identified gaps
  - voice/profile: Personal tone guidelines and sample snippets for LinkedIn posts
  - roadmap/current: Initial roadmap recommendation

Usage:
  python infra/seed_firestore.py
"""

from __future__ import annotations

import os
import sys
from google.cloud import firestore

PROJECT_ID = os.environ.get("GOOGLE_CLOUD_PROJECT", "launchpad-ai-506616")


def seed_firestore() -> None:
    print(f"Connecting to Firestore in project: {PROJECT_ID}...")
    db = firestore.Client(project=PROJECT_ID)

    # 1. targets/roles
    targets_data = {
        "target_roles": [
            "AI/ML Engineer",
            "Full-Stack Agentic Engineer",
            "Founding LLMOps Engineer",
        ],
        "target_jds": [
            {
                "source": "AI Startup Founding Engineer JD",
                "text": "Looking for an engineer to build autonomous agentic workflows using Google Gemini, multi-agent frameworks, Vertex AI, and modern serverless infra with automated CI/CD and production monitoring.",
                "required_skills": [
                    "Google ADK / Agent Frameworks",
                    "Vertex AI & Gemini Models",
                    "Cloud Run & Pub/Sub Eventing",
                    "Python / FastAPI",
                    "Firestore / NoSQL Memory",
                ],
            },
            {
                "source": "Staff LLMOps / Agent Systems JD",
                "text": "Architecting reliable agent evaluation pipelines, self-critique rubrics, and automated publishing systems with real-world tool use and security guardrails.",
                "required_skills": [
                    "LLM Evaluation & Canaries",
                    "OpenTelemetry & Cloud Trace",
                    "GitHub App & OAuth / OIDC Security",
                    "Imagen / Multimodal AI",
                ],
            },
        ],
    }
    print("Writing targets/roles...")
    db.collection("targets").document("roles").set(targets_data, merge=True)

    # 2. skill_map/current
    skill_map_data = {
        "skills": {
            "Python": 0.90,
            "FastAPI": 0.85,
            "Google Cloud Platform": 0.80,
            "Google ADK": 0.75,
            "Vertex AI / Gemini": 0.80,
            "Docker / Containers": 0.75,
            "Event-Driven Architecture": 0.80,
        },
        "gaps": [
            {
                "skill": "Multimodal Vision & Imagen Integration",
                "why": "Target JDs emphasize multimodal asset generation for user-facing production systems.",
                "priority": "high",
            },
            {
                "skill": "Automated Agentic Self-Critique & Rubric Evaluation",
                "why": "High-leverage differentiator for Staff / Lead AI Engineer roles.",
                "priority": "medium",
            },
        ],
    }
    print("Writing skill_map/current...")
    db.collection("skill_map").document("current").set(skill_map_data, merge=True)

    # 3. voice/profile
    voice_data = {
        "tone_notes": "First-person, humble yet technically sharp, builder-focused. Avoid excessive corporate buzzwords or hyperbole. Highlight architectural decisions, lessons learned, and why the project was built. Short punchy paragraphs with clear bullet points.",
        "sample_snippets": [
            "I got tired of updating my portfolio manually after every release, so I built an autonomous agent to do it for me.",
            "The hardest part wasn't the LLM reasoning — it was building a reliable, event-driven serverless pipeline on Google Cloud that handles async execution gracefully.",
        ],
    }
    print("Writing voice/profile...")
    db.collection("voice").document("profile").set(voice_data, merge=True)

    # 4. roadmap/current
    roadmap_data = {
        "next_recommendation": "Build an end-to-end multimodal agent evaluation pipeline with automated rubric critique and canary testing.",
        "rationale": "Closes the key hiring gap for Senior Agentic Engineer roles by demonstrating automated verification and hallucination reduction.",
        "issue_url": "",
    }
    print("Writing roadmap/current...")
    db.collection("roadmap").document("current").set(roadmap_data, merge=True)

    print("Firestore seeding complete! All baseline memory collections populated.")


if __name__ == "__main__":
    seed_firestore()
