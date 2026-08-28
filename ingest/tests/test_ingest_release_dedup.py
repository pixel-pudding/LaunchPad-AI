"""
LaunchPad-AI — unit test for ingest/__init__.py's release-level idempotency
safety net (_claim_release_once).

GitHub sends up to three webhooks per release (published/released/created),
each with a different X-GitHub-Delivery id, so the pre-existing
delivery_id-based idempotency (server.py's /process handler) can't dedupe
them on its own. This test drives the actual /webhook route (not just the
helper function) to prove the fix end-to-end: three deliveries for the same
{repo, tag}, three different delivery_ids, but exactly one Pub/Sub publish.

No live GitHub/Firestore/Pub/Sub: _verify_signature, _get_publisher, and
_get_firestore_client are patched as `ingest.<name>` — webhook() looks them
up in its own module globals at call time, so patching the originating
module is what actually takes effect here, same reasoning as elsewhere in
this codebase (e.g. agent/tests/test_portfolio_publisher.py).
"""

from __future__ import annotations

from google.api_core.exceptions import AlreadyExists
from fastapi import FastAPI
from fastapi.testclient import TestClient

import ingest

app = FastAPI()
app.include_router(ingest.router)
client = TestClient(app)


class _FakeDocRef:
    def __init__(self, store: dict, doc_id: str):
        self._store = store
        self._doc_id = doc_id

    def create(self, data: dict) -> None:
        if self._doc_id in self._store:
            raise AlreadyExists("document already exists")
        self._store[self._doc_id] = data


class _FakeCollection:
    def __init__(self, store: dict):
        self._store = store

    def document(self, doc_id: str) -> _FakeDocRef:
        return _FakeDocRef(self._store, doc_id)


class FakeFirestoreClient:
    """Minimal stand-in exercising the same atomic create()/AlreadyExists
    semantics as the real google.cloud.firestore.Client, so the race-safe
    behavior of _claim_release_once is actually verified, not assumed."""

    def __init__(self):
        self.collections: dict[str, dict] = {}

    def collection(self, name: str) -> _FakeCollection:
        return _FakeCollection(self.collections.setdefault(name, {}))


def _patch_common(monkeypatch):
    monkeypatch.setattr(ingest, "_verify_signature", lambda payload, sig: None)
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "test-project")

    published: list[bytes] = []

    class _FakeFuture:
        def result(self):
            return None

    class _FakePublisher:
        def publish(self, topic, data):
            published.append(data)
            return _FakeFuture()

    monkeypatch.setattr(ingest, "_get_publisher", lambda: _FakePublisher())

    fake_firestore = FakeFirestoreClient()
    monkeypatch.setattr(ingest, "_get_firestore_client", lambda: fake_firestore)

    return published


_PAYLOAD = {
    "action": "published",
    "repository": {"full_name": "owner/repo"},
    "release": {"tag_name": "v1.0.0", "name": "v1.0.0", "body": "", "id": 999},
}


def test_three_release_webhooks_same_release_produce_exactly_one_pubsub_publish(monkeypatch):
    published = _patch_common(monkeypatch)

    for delivery_id in ("delivery-1", "delivery-2", "delivery-3"):
        resp = client.post(
            "/webhook",
            json=_PAYLOAD,
            headers={
                "X-Hub-Signature-256": "sha256=fake",
                "X-GitHub-Event": "release",
                "X-GitHub-Delivery": delivery_id,
            },
        )
        assert resp.status_code == 200

    assert len(published) == 1
