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

from datetime import datetime, timezone

from google.cloud import firestore

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
        # Mimic real Firestore's server-side resolution of the
        # SERVER_TIMESTAMP sentinel, so tests can meaningfully assert the
        # ISO-string conversion in memory.get_portfolio_config() actually
        # runs against a real datetime, not the raw sentinel object.
        resolved = {
            k: (datetime.now(timezone.utc) if v is firestore.SERVER_TIMESTAMP else v)
            for k, v in data.items()
        }
        if merge and self._doc_id in self._store:
            self._store[self._doc_id].update(resolved)
        else:
            self._store[self._doc_id] = resolved


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


def test_portfolio_config_defaults_to_none():
    client = FakeFirestoreClient()
    assert memory.get_portfolio_config(client=client) is None


def test_portfolio_config_roundtrip_converts_ts_to_iso_string():
    client = FakeFirestoreClient()
    memory.set_portfolio_config("owner/portfolio-demo", True, client=client)

    result = memory.get_portfolio_config(client=client)

    assert result["portfolio_repo"] == "owner/portfolio-demo"
    assert result["auto_merge"] is True
    assert isinstance(result["ts"], str)
    datetime.fromisoformat(result["ts"])  # doesn't raise -> genuinely ISO-formatted


def test_portfolio_config_overwrite_replaces_previous_value():
    client = FakeFirestoreClient()
    memory.set_portfolio_config("owner/old-repo", True, client=client)
    memory.set_portfolio_config("owner/new-repo", False, client=client)

    result = memory.get_portfolio_config(client=client)

    assert result["portfolio_repo"] == "owner/new-repo"
    assert result["auto_merge"] is False


def test_portfolio_config_merge_preserves_explicit_format_across_auto_merge_only_update():
    """set_portfolio_config uses .set(data, merge=True) specifically so a
    later call that omits `format` (e.g. the dashboard just toggling
    auto_merge) doesn't wipe a previously-explicit format choice back to
    unset. A plain .set(data) replace would lose it."""
    client = FakeFirestoreClient()
    memory.set_portfolio_config("owner/portfolio-demo", True, format="convention", client=client)

    memory.set_portfolio_config("owner/portfolio-demo", False, client=client)

    result = memory.get_portfolio_config(client=client)
    assert result["auto_merge"] is False
    assert result["format"] == "convention"


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
