"""
LaunchPad-AI — Image tool (agent/tools/image_tool.py).

generate_image(prompt) -> image_url, per the CLAUDE.md tool contract.

Mock mode is ON by default (env IMAGE_MOCK_MODE, default "1") — it returns a
small, self-contained placeholder as a data: URI, with no network call and
no Imagen quota burned. This is deliberate: dev and tests should never
accidentally spend real image-generation quota. Production Cloud Run must
explicitly set IMAGE_MOCK_MODE=0 to get real Imagen output.

Real mode uses Vertex AI Imagen via google-genai's generate_images(), which
returns raw image bytes (not a URL) — verified against the installed
google-genai SDK source (GeneratedImage.image.image_bytes/mime_type). Those
bytes are base64-encoded into a data: URI here, since the dashboard's
<img src=...> needs something directly browser-loadable, not an opaque
reference. This path is unverified against a live Vertex AI call (no
credentials in the dev sandbox) — flagged for a live check before relying
on it in a demo.
"""

from __future__ import annotations

import base64
import logging
import os

logger = logging.getLogger(__name__)

IMAGEN_MODEL = os.environ.get("IMAGEN_MODEL", "imagen-3.0-generate-002")


def _mock_mode_enabled() -> bool:
    return os.environ.get("IMAGE_MOCK_MODE", "1").strip().lower() in ("1", "true")


def _mock_image(prompt: str) -> str:
    """A small, deterministic, self-contained placeholder — no network, no quota."""
    label = (prompt[:40] + "…") if len(prompt) > 40 else prompt
    label = label.replace("&", "and").replace("<", "").replace(">", "").replace('"', "'")
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="512" height="512">'
        '<rect width="100%" height="100%" fill="#e2e8f0"/>'
        '<text x="50%" y="50%" font-family="sans-serif" font-size="20" '
        f'fill="#475569" text-anchor="middle" dominant-baseline="middle">{label}</text>'
        "</svg>"
    )
    encoded = base64.b64encode(svg.encode("utf-8")).decode("ascii")
    return f"data:image/svg+xml;base64,{encoded}"


def generate_image(prompt: str) -> str:
    """Returns an image_url usable directly as an <img src> (a data: URI).

    Mock mode (default ON — see IMAGE_MOCK_MODE) never calls Vertex AI.
    """
    if _mock_mode_enabled():
        return _mock_image(prompt)

    from google import genai
    from google.genai import types

    client = genai.Client()
    response = client.models.generate_images(
        model=IMAGEN_MODEL,
        prompt=prompt,
        config=types.GenerateImagesConfig(number_of_images=1),
    )
    image = response.generated_images[0].image
    mime_type = image.mime_type or "image/png"
    encoded = base64.b64encode(image.image_bytes).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"
