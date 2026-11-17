from types import SimpleNamespace
import sqlite3

import pytest
from fastapi.testclient import TestClient

from backend.app import main
from backend.app.db import Store


@pytest.fixture
def store(tmp_path):
    store = Store(tmp_path / "test.db")
    store.init()
    target = store.create_target({"name": "Test", "campground_id": "123"})
    for name in ("Weekend", "Holiday", "Summer"):
        store.create_watch({"target_id": target["id"], "name": name, "mode": "weekend",
                            "window_start": "2027-07-01", "window_end": "2027-07-31"})
    return store


def test_bulk_actions_preserve_unselected_watches_and_targets(store):
    ids = [watch["id"] for watch in store.list_watches()]
    assert store.bulk_update_watches([ids[0], ids[0], ids[1], 999], "pause") == 2
    assert not store.get_watch(ids[0])["active"]
    assert store.get_watch(ids[2])["active"]
    assert store.bulk_update_watches(ids[:2], "resume") == 2
    assert store.get_watch(ids[0])["active"]
    assert store.bulk_update_watches(ids[:2], "delete") == 2
    assert [watch["id"] for watch in store.list_watches()] == [ids[2]]
    assert len(store.list_targets()) == 1


def test_wal_read_during_write_and_rollback(store):
    with pytest.raises(RuntimeError):
        with store.connect() as writer:
            assert writer.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
            writer.execute("UPDATE watches SET active = 0")
            assert all(watch["active"] for watch in store.list_watches())
            raise RuntimeError("roll back")
    assert all(watch["active"] for watch in store.list_watches())


def test_bulk_api_validates_and_blocks_delete_during_scans(store, monkeypatch):
    monkeypatch.setattr(main, "store", store)
    cancelled = []
    watch_id = store.list_watches()[0]["id"]
    monkeypatch.setattr(main, "scanner", SimpleNamespace(
        is_busy=True, active_watch_id=watch_id,
        cancel_current_scan=lambda: cancelled.append(True)))
    client = TestClient(main.app)
    assert client.post("/api/watches/bulk", json={"action": "pause", "watch_ids": []}).status_code == 422
    assert client.post("/api/watches/bulk", json={"action": "delete", "watch_ids": [watch_id]}).status_code == 409
    assert store.get_watch(watch_id)
    response = client.post("/api/watches/bulk", json={"action": "pause", "watch_ids": [watch_id]})
    assert response.json()["updated_count"] == 1
    assert cancelled == [True]
    assert not store.get_watch(watch_id)["active"]


def test_health_checks_database_and_reports_lock_errors(store, monkeypatch):
    monkeypatch.setattr(main, "store", store)
    client = TestClient(main.app)
    assert client.get("/api/health").status_code == 200

    def locked():
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(store, "connect", locked)
    response = client.get("/api/health")
    assert response.status_code == 503
    assert response.headers["Retry-After"] == "5"
    assert "Database is busy" in response.json()["detail"]
