import copy
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.app import main
from backend.app.db import Store
from backend.app.regions import RegionScope
from backend.app.schemas import ConfigBackup


WA = {"kind": "state", "state_code": "WA"}
BOUNDS = {"kind": "bounds", "south": 47.0, "west": -124.0, "north": 49.0, "east": -121.0}
RULE = {"name": "WA weekends", "mode": "weekend", "window_start": "2027-06-01",
        "window_end": "2027-08-31", "arrival_weekdays": [4], "nights": 2,
        "site_filters": {"site_type": "tent"}, "active": True}


@pytest.fixture
def store(tmp_path):
    result = Store(tmp_path / "regions.db")
    result.init()
    return result


def target(store, campground_id="123", **overrides):
    return store.create_target({"name": "Camp " + campground_id, "campground_id": campground_id,
                                "state_code": "WA", "park_name": "Test park", **overrides})


def region(store, scope=WA, **overrides):
    first = target(store, latitude=48, longitude=-122)
    return store.create_watch_group([first["id"]], {**RULE, **overrides}, scope)


def test_old_database_migrates_without_enabling_old_groups(store):
    first = target(store)
    members = store.create_watch_group([first["id"]], RULE)
    with store.connect() as conn:
        conn.execute("DROP TABLE watch_regions")
    store.init()
    store.init()
    target(store, "456")
    assert len(store.list_watches()) == 1
    assert store.get_watch(members[0]["id"])["region_scope"] is None


def test_state_cross_provider_imports_inherit_rules_once(store):
    members = region(store)
    group_id = members[0]["group_id"]
    for campground_id in ("camava:snoco:1", "activenet:king:66", "456"):
        target(store, campground_id)
        target(store, campground_id)
    target(store, "789", state_code="OR")
    watches = store.list_watches()
    assert len(watches) == 4
    assert {item["group_id"] for item in watches} == {group_id}
    assert all(item["region_scope"]["state_code"] == "WA" for item in watches)
    assert all(item["site_filters"] == RULE["site_filters"] and item["arrival_weekdays"] == [4] for item in watches)
    assert len([event for event in store.list_scan_events() if event["event_type"] == "region_expanded"]) == 3


def test_paused_groups_partial_pause_and_edit_template(store):
    members = region(store, active=False)
    group_id = members[0]["group_id"]
    target(store, "456")
    assert all(not item["active"] for item in store.list_watches())
    store.bulk_update_watches([members[0]["id"]], "resume")
    target(store, "789")
    assert store.get_watch_by_target_and_name(3, RULE["name"], group_id)["active"]
    store.update_watch_group(group_id, {"name": "Yurt weekends", "site_filters": {"site_type": "yurt"}, "nights": 3})
    imported = target(store, "999")
    watch = store.get_watch_by_target_and_name(imported["id"], "Yurt weekends", group_id)
    assert watch["nights"] == 3 and watch["site_filters"] == {"site_type": "yurt"}
    ids = [item["id"] for item in store.list_watches()]
    store.bulk_update_watches(ids, "pause")
    target(store, "777")
    assert all(not item["active"] for item in store.list_watches())


def test_deleted_members_stay_excluded_after_reimport_edit_restart_and_backup(store, tmp_path):
    first = region(store)[0]
    second = target(store, "456")
    member = store.get_watch_by_target_and_name(second["id"], RULE["name"], first["group_id"])
    assert store.delete_watch(member["id"])
    target(store, "456")
    store.update_watch_group(first["group_id"], {"nights": 3})
    store.init()
    assert len(store.list_watches()) == 1
    backup = ConfigBackup.model_validate(store.export_config()).model_dump(mode="json")
    assert backup["regions"][0]["excluded_campgrounds"] == ["456"]
    restored = Store(tmp_path / "restored.db")
    restored.init()
    restored.import_config(backup)
    restored.import_config(backup)
    target(restored, "456")
    assert len(restored.list_watches()) == 1
    target(restored, "789")
    assert len(restored.list_watches()) == 2


def test_deleting_last_members_removes_region_and_never_resurrects(store):
    region(store)
    target(store, "456")
    ids = [watch["id"] for watch in store.list_watches()]
    assert store.bulk_update_watches(ids, "delete") == 2
    assert store.export_config()["regions"] == []
    target(store, "789")
    assert store.list_watches() == []


def test_enabling_existing_snapshot_adds_matching_targets_and_disable_keeps_members(store):
    first = target(store)
    target(store, "456")
    target(store, "789", state_code="OR")
    group_id = store.create_watch_group([first["id"]], RULE)[0]["group_id"]
    updated = store.update_watch_group(group_id, {"region_scope": WA})
    assert len(updated) == 2
    store.update_watch_group(group_id, {"region_scope": None})
    target(store, "999")
    assert len(store.list_watches()) == 2
    assert all(watch["region_scope"] is None for watch in store.list_watches())


def test_bounds_persist_and_ignore_missing_coordinates(store):
    region(store, BOUNDS)
    target(store, "456", latitude=47, longitude=-124)
    target(store, "789", latitude=49.1, longitude=-122)
    missing = target(store, "999")
    assert len(store.list_watches()) == 2
    store.init()
    store.update_target(missing["id"], {"latitude": 48, "longitude": -123})
    assert len(store.list_watches()) == 3
    assert all(watch["region_scope"]["west"] == -124 for watch in store.list_watches())


def test_park_membership_uses_exact_names_across_providers(store):
    region(store, {"kind": "parks", "park_names": ["Test park"]})
    target(store, "activenet:king:66")
    target(store, "456", park_name="Test park annex")
    assert len(store.list_watches()) == 2


def test_inactive_target_is_enrolled_only_after_activation(store):
    region(store)
    paused = target(store, "456", active=False)
    assert len(store.list_watches()) == 1
    store.update_target(paused["id"], {"active": True})
    assert len(store.list_watches()) == 2


@pytest.mark.parametrize("scope", [
    {"kind": "state"}, {"kind": "state", "state_code": "washington"},
    {"kind": "parks", "park_names": []}, {"kind": "parks", "park_names": [""]},
    {**WA, "south": 1}, {**BOUNDS, "north": 45}, {**BOUNDS, "west": 180},
    {**BOUNDS, "south": float("nan")}, {**BOUNDS, "east": 181}, {"kind": "all"},
])
def test_invalid_scope_is_rejected(scope):
    with pytest.raises(ValidationError):
        RegionScope.model_validate(scope)


def test_scope_failure_rolls_back_and_wrong_target_rejected(store, monkeypatch):
    first = target(store)
    target(store, "456")
    with pytest.raises(ValueError):
        store.create_watch_group([first["id"]], RULE, {"kind": "state", "state_code": "OR"})
    original = store.create_watch
    calls = []

    def fail_second(data, conn=None):
        calls.append(data)
        if len(calls) == 2:
            raise RuntimeError("write failure")
        return original(data, conn)

    monkeypatch.setattr(store, "create_watch", fail_second)
    with pytest.raises(RuntimeError):
        store.create_watch_group([first["id"]], RULE, WA)
    assert not store.list_watches()
    assert not store.export_config()["regions"]


def test_api_updates_legacy_group_and_rejects_individual_rule_edits(store, monkeypatch):
    first = target(store)
    monkeypatch.setattr(main, "store", store)
    monkeypatch.setattr(main, "scanner", SimpleNamespace(is_busy=False))
    client = TestClient(main.app)
    payload = {"target_ids": [first["id"]], "watch": {**RULE, "target_id": first["id"]}, "region_scope": WA}
    response = client.post("/api/watch-groups", json=payload)
    assert response.status_code == 200
    watch = response.json()[0]
    assert client.get("/api/watches").json()[0]["region_scope"]["state_code"] == "WA"
    assert client.patch(f"/api/watches/{watch['id']}", json={"nights": 4}).status_code == 400
    assert client.patch(f"/api/watches/{watch['id']}", json={"active": False}).status_code == 200
    response = client.patch(f"/api/watch-groups/{watch['group_id']}", json={"nights": 4})
    assert response.status_code == 200 and response.json()[0]["region_scope"]["state_code"] == "WA"
    assert client.patch(f"/api/watch-groups/{watch['group_id']}", json={"region_scope": {"kind": "bounds"}}).status_code == 422


def test_restore_does_not_enroll_before_restoring_inactive_flags(store):
    region(store)
    backup = store.export_config()
    extra = copy.deepcopy(backup["targets"][0])
    extra.update(campground_id="456", name="Inactive", active=False, watches=[])
    backup["targets"].append(extra)
    store.import_config(backup)
    assert len(store.list_watches()) == 1
    # Restoring a fixed-membership backup disables the matching saved region.
    backup.pop("regions")
    store.import_config(backup)
    target(store, "789")
    assert len(store.list_watches()) == 1


def test_region_backup_without_members_rejected_before_changes(store):
    backup = {"targets": [], "regions": [{"group_id": "unknown", "scope": WA}]}
    with pytest.raises(ValueError):
        store.import_config(backup)
    assert not store.list_targets()


def test_renamed_group_restore_updates_members_instead_of_duplicating(store):
    group_id = region(store)[0]["group_id"]
    target(store, "456")
    backup = store.export_config()
    store.update_watch_group(group_id, {"name": "Renamed"})
    store.import_config(backup)
    assert len(store.list_watches()) == 2
    assert all(watch["name"] == RULE["name"] for watch in store.list_watches())


def test_inconsistent_region_backup_is_rejected_before_any_writes(store):
    region(store)
    target(store, "456")
    backup = store.export_config()
    backup["targets"][0]["name"] = "Do not save"
    backup["targets"][0]["watches"][0]["nights"] = 9
    with pytest.raises(ValueError):
        store.import_config(backup)
    assert all(item["name"] != "Do not save" for item in store.list_targets())


def test_bulk_delete_expanding_group_across_chunks_preserves_unselected(store):
    group_id = region(store)[0]["group_id"]
    for number in range(600):
        target(store, str(1000 + number))
    watches = store.list_watches()
    keep = watches[0]
    assert store.bulk_update_watches([item["id"] for item in watches[1:]], "delete") == 600
    store.update_watch_group(group_id, {"nights": 3})
    assert [item["id"] for item in store.list_watches()] == [keep["id"]]
    assert store.delete_watch(keep["id"])
    assert store.export_config()["regions"] == []


def test_target_deletion_excludes_reimport_and_cleans_empty_groups(store):
    first = region(store)[0]
    second = target(store, "456")
    store.delete_target(second["id"])
    target(store, "456")
    assert len(store.list_watches()) == 1
    store.delete_target(first["target_id"])
    assert store.export_config()["regions"] == []


def test_restore_old_region_backup_keeps_new_members_with_restored_criteria(store):
    group_id = region(store)[0]["group_id"]
    backup = store.export_config()
    target(store, "456")
    store.update_watch_group(group_id, {"nights": 3, "name": "Changed"})
    store.import_config(backup)
    assert len(store.list_watches()) == 2
    assert all(watch["nights"] == 2 and watch["name"] == RULE["name"] for watch in store.list_watches())


def test_enabling_divergent_legacy_group_requires_shared_criteria(store):
    first = target(store)
    second = target(store, "456")
    members = store.create_watch_group([first["id"], second["id"]], RULE)
    store.update_watch(members[1]["id"], {"nights": 3})
    with pytest.raises(ValueError, match="shared dates"):
        store.update_watch_group(members[0]["group_id"], {"region_scope": WA})
    assert store.export_config()["regions"] == []
    updated = store.update_watch_group(members[0]["group_id"], {"nights": 2, "region_scope": WA})
    assert all(watch["region_scope"] and watch["nights"] == 2 for watch in updated)
