"""
LaunchPad-AI — unit tests for agent/memory.py.

Every accessor in memory.py takes an injectable `client`, so these tests
exercise the real Firestore-facing logic (doc-id sanitization, merge
semantics, defaults) against a minimal in-memory fake instead of a live
google.cloud.firestore.Client().

NOTE: this machine has no `gcloud` install, so the real Firestore emulator
(`gcloud emulators firestore start`) isn't available to run against here.
This fake stands in for it — swap in emulator-backed fixtures once the
emulator is available (e.g. in CI, where [AG]'s infra already assumes it).
"""

from __future__ import annotations

from agent import memory


class _FakeDoc:
    def __init__(self, data: dict | None):
        self._data = data

    @property
    def exists(self) -> bool:
        return self._data is not None

    def to_dict(self) -> dict:
        return dict(self._data) if self._data else {}


class _FakeDocumentRef:
    def __init__(self, store: dict, doc_id: str):
        self._store = store
        self._doc_id = doc_id

    def get(self) -> _FakeDoc:
        return _FakeDoc(self._store.get(self._doc_id))

    def set(self, data: dict, merge: bool = False) -> None:
        if merge and self._doc_id in self._store:
            self._store[self._doc_id].update(data)
        else:
            self._store[self._doc_id] = dict(data)


class _FakeCollection:
    def __init__(self, store: dict):
        self._store = store

    def document(self, doc_id: str) -> _FakeDocumentRef:
        return _FakeDocumentRef(self._store, doc_id)

    def stream(self):
        return [_FakeDoc(data) for data in self._store.values()]


class FakeFirestoreClient:
    """Minimal stand-in for google.cloud.firestore.Client — only the surface
    memory.py actually calls."""

    def __init__(self):
        self.collections: dict[str, dict] = {}

    def collection(self, name: str) -> _FakeCollection:
        return _FakeCollection(self.collections.setdefault(name, {}))


def test_get_project_missing_returns_none():
    client = FakeFirestoreClient()
    assert memory.get_project("owner/repo", client=client) is None


def test_upsert_and_get_project_roundtrip():
    client = FakeFirestoreClient()
    memory.upsert_project("owner/repo", {"name": "repo", "status": "featured"}, client=client)
    assert memory.get_project("owner/repo", client=client) == {"name": "repo", "status": "featured"}


def test_upsert_project_merges_not_overwrites():
    client = FakeFirestoreClient()
    memory.upsert_project("owner/repo", {"name": "repo"}, client=client)
    memory.upsert_project("owner/repo", {"status": "featured"}, client=client)
    assert memory.get_project("owner/repo", client=client) == {"name": "repo", "status": "featured"}


def test_doc_id_sanitizes_slash_in_repo_name():
    client = FakeFirestoreClient()
    memory.upsert_project("owner/repo", {"name": "repo"}, client=client)
    assert list(client.collections["projects"].keys()) == ["owner__repo"]


def test_list_projects_returns_all():
    client = FakeFirestoreClient()
    memory.upsert_project("a/one", {"name": "one"}, client=client)
    memory.upsert_project("b/two", {"name": "two"}, client=client)
    names = {p["name"] for p in memory.list_projects(client=client)}
    assert names == {"one", "two"}


def test_context_profile_defaults_to_empty_dict():
    client = FakeFirestoreClient()
    assert memory.get_context_profile(client=client) == {}


def test_voice_profile_defaults_to_empty_dict():
    client = FakeFirestoreClient()
    assert memory.get_voice_profile(client=client) == {}


def test_idempotency_roundtrip():
    client = FakeFirestoreClient()
    assert memory.is_duplicate_delivery("delivery-1", client=client) is False
    memory.mark_delivery_processed("delivery-1", client=client)
    assert memory.is_duplicate_delivery("delivery-1", client=client) is True


def test_save_decision_stores_full_record():
    client = FakeFirestoreClient()
    record = {"repo": "owner/repo", "action": "skip", "reasoning": "trivial release"}
    memory.save_decision("delivery-1", record, client=client)
    assert client.collection("decisions").document("delivery-1").get().to_dict() == record
