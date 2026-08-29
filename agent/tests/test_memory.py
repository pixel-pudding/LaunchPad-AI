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


class _FakeQuery:
    """Just enough of Firestore's order_by().limit().stream() chain for
    memory.get_agent_status()'s "most recently started run" query — real
    sorting, not a stub, so the test below is actually exercising the
    ordering logic rather than assuming it works."""

    def __init__(self, docs: list[dict]):
        self._docs = docs

    def order_by(self, field: str, direction: str | None = None):
        reverse = direction == firestore.Query.DESCENDING
        return _FakeQuery(sorted(self._docs, key=lambda d: d.get(field) or "", reverse=reverse))

    def limit(self, n: int) -> "_FakeQuery":
        return _FakeQuery(self._docs[:n])

    def stream(self):
        return [_FakeDoc(d) for d in self._docs]


class _FakeCollection:
    def __init__(self, store: dict):
        self._store = store

    def document(self, doc_id: str) -> _FakeDocumentRef:
        return _FakeDocumentRef(self._store, doc_id)

    def stream(self):
        return [_FakeDoc(data) for data in self._store.values()]

    def order_by(self, field: str, direction: str | None = None) -> _FakeQuery:
        return _FakeQuery(list(self._store.values())).order_by(field, direction)


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


def test_agent_status_defaults_to_idle_when_nothing_written():
    client = FakeFirestoreClient()
    assert memory.get_agent_status(client=client) == {"status": "idle"}


def test_agent_status_writes_land_in_a_per_delivery_doc_not_one_shared_doc():
    """The bug this replaces: every run overwrote the same config/agent_status
    doc, so a reload mid-run (or two overlapping runs) could read a status
    blended from two different deliveries. Each delivery_id must get its own
    doc under the agent_status collection."""
    client = FakeFirestoreClient()
    memory.set_agent_status(
        {"status": "running", "stage": 1, "delivery_id": "run-a", "started_at": "2026-08-29T10:00:00+00:00"},
        client=client,
    )
    memory.set_agent_status(
        {"status": "running", "stage": 1, "delivery_id": "run-b", "started_at": "2026-08-29T10:05:00+00:00"},
        client=client,
    )

    docs = client.collections["agent_status"]
    assert set(docs.keys()) == {"run-a", "run-b"}
    assert docs["run-a"]["stage"] == 1
    assert docs["run-b"]["stage"] == 1


def test_agent_status_returns_the_most_recently_started_run():
    """A page reload (or a poll landing between two runs) must always see
    the newest run's status, never an older one just because it was
    written to Firestore more recently in wall-clock terms — ordering is
    by started_at, not write order."""
    client = FakeFirestoreClient()
    # Write the OLDER run second, to prove this isn't just "last write wins".
    memory.set_agent_status(
        {"status": "idle", "delivery_id": "run-newer", "started_at": "2026-08-29T10:05:00+00:00"},
        client=client,
    )
    memory.set_agent_status(
        {"status": "running", "stage": 3, "delivery_id": "run-older", "started_at": "2026-08-29T10:00:00+00:00"},
        client=client,
    )

    result = memory.get_agent_status(client=client)
    assert result["delivery_id"] == "run-newer"


def test_agent_status_completion_write_keys_by_last_delivery_id():
    """The final idle/completed write from runner.py uses the field name
    "last_delivery_id" (it's describing a run that just finished, not one
    in progress) — this must still land in the SAME per-run doc as that
    run's earlier stage writes, not a doc keyed "unknown"."""
    client = FakeFirestoreClient()
    memory.set_agent_status(
        {"status": "running", "stage": 1, "delivery_id": "run-a", "started_at": "2026-08-29T10:00:00+00:00"},
        client=client,
    )
    memory.set_agent_status(
        {"status": "idle", "last_delivery_id": "run-a", "started_at": "2026-08-29T10:00:00+00:00"},
        client=client,
    )

    docs = client.collections["agent_status"]
    assert set(docs.keys()) == {"run-a"}
    assert docs["run-a"]["status"] == "idle"
    assert docs["run-a"]["stage"] == 1  # merge=True preserved the earlier field
