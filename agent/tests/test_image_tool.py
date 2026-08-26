"""
LaunchPad-AI — unit tests for agent/tools/image_tool.py.

Mock mode (the default) is exercised for real — no network, no credentials
needed. Real mode is exercised too, but with google.genai's Client attribute
patched to a fake, so it never actually calls Vertex AI/Imagen.

NOTE: image_tool.py does `from google import genai` lazily, inside
generate_image(), and google.genai is already imported for real elsewhere
in this codebase (relevance_curator.py imports it at module level) by the
time tests run — so patching sys.modules["google.genai"] wouldn't work
(the `google` package's cached `genai` attribute would still point at the
real module). Patching the real module's `Client`/`GenerateImagesConfig`
attributes directly is what actually intercepts the lazy import.
"""

from __future__ import annotations

import base64

import google.genai as real_genai
import google.genai.types as real_genai_types

from agent.tools import image_tool


def test_mock_mode_is_default_on(monkeypatch):
    monkeypatch.delenv("IMAGE_MOCK_MODE", raising=False)
    assert image_tool._mock_mode_enabled() is True


def test_mock_mode_can_be_disabled(monkeypatch):
    monkeypatch.setenv("IMAGE_MOCK_MODE", "0")
    assert image_tool._mock_mode_enabled() is False


def test_generate_image_mock_mode_returns_data_uri(monkeypatch):
    monkeypatch.setenv("IMAGE_MOCK_MODE", "1")
    url = image_tool.generate_image("a retrieval pipeline diagram")
    assert url.startswith("data:image/svg+xml;base64,")


def test_mock_image_is_deterministic_shape():
    url_a = image_tool._mock_image("same prompt")
    url_b = image_tool._mock_image("same prompt")
    assert url_a == url_b


def test_generate_image_real_mode_calls_imagen_and_encodes_bytes(monkeypatch):
    """Fakes out google.genai entirely (no real import, no network) to prove
    the real-mode code path builds the data: URI correctly from
    image_bytes + mime_type, per the installed SDK's Imagen response shape."""
    monkeypatch.setenv("IMAGE_MOCK_MODE", "0")

    raw_bytes = b"not-a-real-png"
    captured = {}

    class FakeImage:
        image_bytes = raw_bytes
        mime_type = "image/png"

    class FakeGeneratedImage:
        image = FakeImage()

    class FakeResponse:
        generated_images = [FakeGeneratedImage()]

    class FakeModels:
        def generate_images(self, *, model, prompt, config):
            captured["model"] = model
            captured["prompt"] = prompt
            return FakeResponse()

    class FakeClient:
        def __init__(self):
            self.models = FakeModels()

    monkeypatch.setattr(real_genai, "Client", FakeClient)
    monkeypatch.setattr(real_genai_types, "GenerateImagesConfig", lambda **kwargs: kwargs)

    url = image_tool.generate_image("a retrieval pipeline diagram")

    assert captured["prompt"] == "a retrieval pipeline diagram"
    assert captured["model"] == image_tool.IMAGEN_MODEL
    expected = f"data:image/png;base64,{base64.b64encode(raw_bytes).decode('ascii')}"
    assert url == expected
