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
        cancel_current_scan=lambda **kwargs: cancelled.append(True)))
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


def group_targets_and_payload(store):
    first = store.list_targets()[0]
    second = store.create_target({"name": "Other", "campground_id": "456"})
    return [first["id"], second["id"]], {
        "name": "Regional weekends", "mode": "weekend", "target_id": first["id"],
        "window_start": "2027-07-01", "window_end": "2027-07-31", "active": False,
    }


def test_region_create_edit_and_backup_preserve_membership(store, tmp_path):
    ids, payload = group_targets_and_payload(store)
    members = store.create_watch_group(ids + ids, payload)
    assert len(members) == 2
    group_id = members[0]["group_id"]
    assert group_id and {watch["group_id"] for watch in members} == {group_id}
    updated = store.update_watch_group(group_id, {"name": "Summer weekends", "nights": 3})
    assert all(watch["name"] == "Summer weekends" and watch["nights"] == 3 for watch in updated)
    # An independently created group with the same name must not collapse on import.
    store.create_watch_group(ids, {**payload, "name": "Summer weekends"})
    from backend.app.schemas import ConfigBackup
    backup = ConfigBackup.model_validate(store.export_config()).model_dump(mode="json")
    restored = Store(tmp_path / "restored.db")
    restored.init()
    restored.import_config(backup)
    restored.import_config(backup)
    grouped = [watch for watch in restored.list_watches() if watch["group_id"]]
    assert len(grouped) == 4
    assert len({watch["group_id"] for watch in grouped}) == 2
    assert len(restored.list_watches()) == len(store.list_watches())


def test_region_creation_rolls_back_on_partial_failure(store, monkeypatch):
    ids, payload = group_targets_and_payload(store)
    original = store.create_watch
    before = len(store.list_watches())
    calls = []

    def fail_second(data, conn=None):
        calls.append(data)
        if len(calls) == 2:
            raise RuntimeError("injected write failure")
        return original(data, conn)

    monkeypatch.setattr(store, "create_watch", fail_second)
    with pytest.raises(RuntimeError):
        store.create_watch_group(ids, payload)
    assert len(store.list_watches()) == before


def test_region_api_validation_and_edit(store, monkeypatch):
    ids, payload = group_targets_and_payload(store)
    monkeypatch.setattr(main, "store", store)
    monkeypatch.setattr(main, "scanner", SimpleNamespace(is_busy=False))
    client = TestClient(main.app)
    assert client.post("/api/watch-groups", json={"target_ids": [], "watch": payload}).status_code == 422
    assert client.post("/api/watch-groups", json={"target_ids": [9999], "watch": payload}).status_code == 400
    response = client.post("/api/watch-groups", json={"target_ids": ids, "watch": payload})
    assert response.status_code == 200
    group_id = response.json()[0]["group_id"]
    response = client.patch(f"/api/watch-groups/{group_id}", json={"nights": 3})
    assert response.status_code == 200
    assert all(watch["nights"] == 3 for watch in response.json())
    assert client.patch(f"/api/watch-groups/{group_id}", json={"target_id": ids[0]}).status_code == 400
    assert client.patch("/api/watch-groups/missing", json={"nights": 3}).status_code == 404
    main.scanner.is_busy = True
    assert client.patch(f"/api/watch-groups/{group_id}", json={"nights": 4}).status_code == 409
