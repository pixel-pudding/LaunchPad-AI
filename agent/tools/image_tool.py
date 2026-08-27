"""
LaunchPad-AI — Project Visual & Screenshot Resolver (agent/tools/image_tool.py).

Resolves high-engagement project visuals and screenshots across a 4-tier hierarchy:
  1. Tier 1: Real UI screenshot from repository README.md (png/jpg/webp previews).
  2. Tier 2: Live deployment snapshot (if repository has a live demo link / Vercel / GitHub Pages).
  3. Tier 3: Official GitHub OpenGraph social card (https://opengraph.githubassets.com/1/{repo}).
  4. Tier 4: Clean, deterministic SVG badge placeholder.
"""

from __future__ import annotations

import base64
import logging
from typing import Any

logger = logging.getLogger(__name__)


def resolve_project_image(repo: str, profile: dict[str, Any] | None = None) -> str:
    """Returns a direct, browser-loadable image URL or data URI for the project."""
    if not repo:
        return _default_svg_badge("Project Release")

    profile = profile or {}

    # Tier 1: Real UI Screenshot from README
    readme_images = profile.get("images", [])
    for img in readme_images:
        lower = img.lower()
        if any(kw in lower for kw in ["screenshot", "demo", "preview", "ui", "app"]):
            if img.startswith("http://") or img.startswith("https://"):
                return img
            clean_path = img.lstrip("./").lstrip("/")
            return f"https://raw.githubusercontent.com/{repo}/main/{clean_path}"

    for img in readme_images:
        if "shields.io" not in img and "badge" not in img.lower() and not img.endswith(".svg"):
            if img.startswith("http://") or img.startswith("https://"):
                return img
            clean_path = img.lstrip("./").lstrip("/")
            return f"https://raw.githubusercontent.com/{repo}/main/{clean_path}"

    # Tier 2: Live Deployment Snapshot (if demo_url exists)
    demo_url = profile.get("demo_url", "")
    if demo_url and (demo_url.startswith("http://") or demo_url.startswith("https://")):
        return f"https://image.thum.io/get/width/1200/{demo_url}"

    # Tier 3: GitHub OpenGraph Social Card (100% reliable for all repos)
    if "/" in repo:
        return f"https://opengraph.githubassets.com/1/{repo}"

    # Tier 4: Fallback SVG Badge
    return _default_svg_badge(profile.get("name", repo))


def generate_image(prompt: str, repo: str = "", profile: dict[str, Any] | None = None) -> str:
    """Convenience wrapper for runner / announcer pipelines."""
    if repo:
        return resolve_project_image(repo, profile)
    return _default_svg_badge(prompt)


def _default_svg_badge(label: str) -> str:
    display_text = (label[:35] + "…") if len(label) > 35 else label
    display_text = display_text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="420" viewBox="0 0 800 420">'
        '<defs>'
        '<linearGradient id="bg" x1="0%" y1="0%" x2="100%" y2="100%">'
        '<stop offset="0%" stop-color="#18181b"/>'
        '<stop offset="100%" stop-color="#09090b"/>'
        '</linearGradient>'
        '</defs>'
        '<rect width="100%" height="100%" fill="url(#bg)" rx="12"/>'
        '<rect x="2" y="2" width="796" height="416" fill="none" stroke="#27272a" stroke-width="2" rx="10"/>'
        '<circle cx="40" cy="40" r="6" fill="#ef4444"/>'
        '<circle cx="60" cy="40" r="6" fill="#f59e0b"/>'
        '<circle cx="80" cy="40" r="6" fill="#10b981"/>'
        '<text x="400" y="220" font-family="system-ui, -apple-system, sans-serif" font-size="28" font-weight="600" '
        f'fill="#f4f4f5" text-anchor="middle" dominant-baseline="middle">{display_text}</text>'
        '</svg>'
    )
    encoded = base64.b64encode(svg.encode("utf-8")).decode("ascii")
    return f"data:image/svg+xml;base64,{encoded}"
