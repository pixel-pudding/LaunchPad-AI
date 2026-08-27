"""
LaunchPad-AI — unit tests for agent/tools/image_tool.py.

Exercises the 4-tier project image resolver:
  1. Tier 1: README UI screenshots
  2. Tier 2: Live deployment snapshot
  3. Tier 3: GitHub OpenGraph social preview
  4. Tier 4: Fallback SVG badge
"""

from __future__ import annotations

from agent.tools import image_tool


def test_tier_1_resolves_readme_ui_screenshot():
    profile = {
        "images": ["https://raw.githubusercontent.com/user/repo/main/docs/ui-screenshot.png"],
        "demo_url": "https://myapp.vercel.app",
    }
    url = image_tool.resolve_project_image("user/repo", profile)
    assert url == "https://raw.githubusercontent.com/user/repo/main/docs/ui-screenshot.png"


def test_tier_1_resolves_relative_readme_screenshot():
    profile = {
        "images": ["screenshots/demo.png"],
        "demo_url": "https://myapp.vercel.app",
    }
    url = image_tool.resolve_project_image("user/repo", profile)
    assert url == "https://raw.githubusercontent.com/user/repo/main/screenshots/demo.png"


def test_tier_2_resolves_live_deployment_snapshot():
    profile = {
        "images": [],
        "demo_url": "https://postmortem-ai.vercel.app",
    }
    url = image_tool.resolve_project_image("AmeyaSingh23/postmortem-ai", profile)
    assert url == "https://image.thum.io/get/width/1200/https://postmortem-ai.vercel.app"


def test_tier_3_resolves_github_opengraph_card():
    profile = {
        "images": [],
        "demo_url": "",
    }
    url = image_tool.resolve_project_image("pixel-pudding/Coachline", profile)
    assert url == "https://opengraph.githubassets.com/1/pixel-pudding/Coachline"


def test_tier_4_resolves_default_svg_badge():
    url = image_tool.resolve_project_image("")
    assert url.startswith("data:image/svg+xml;base64,")
