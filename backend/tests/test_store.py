from __future__ import annotations

from copy import deepcopy

from backend.app.db import Store


def test_create_watch_returns_committed_watch(tmp_path) -> None:
    store = Store(tmp_path / "campfinder.db")
    store.init()
    target = store.create_target(
        {
            "name": "Kalaloch",
            "campground_id": "232464",
            "park_name": "Olympic National Park",
            "state_code": "WA",
            "release_months": 6,
            "release_window_value": 14,
            "release_window_unit": "Days",
            "release_time": "07:00",
            "timezone": "America/Los_Angeles",
            "poll_interval_minutes": 10,
        }
    )

    watch = store.create_watch(
        {
            "target_id": target["id"],
            "name": "Fri starts, 2 nights",
            "mode": "weekend",
            "pattern": "4-2n",
            "arrival_weekdays": [4],
            "nights": 2,
            "window_start": "2026-07-01",
            "window_end": "2026-08-31",
            "specific_ranges": [],
        }
    )

    assert watch["name"] == "Fri starts, 2 nights"
    assert watch["mode"] == "weekend"
    assert watch["arrival_weekdays"] == [4]
    assert watch["cart_assist_enabled"] == 0


def test_export_config_includes_only_durable_configuration(tmp_path) -> None:
    store = Store(tmp_path / "campfinder.db")
    store.init()
    target = store.create_target(
        {
            "name": "Kalaloch",
            "campground_id": "232464",
            "park_name": "Olympic National Park",
            "state_code": "WA",
            "release_months": 6,
            "release_window_value": 14,
            "release_window_unit": "Days",
            "release_time": "07:00",
            "timezone": "America/Los_Angeles",
            "poll_interval_minutes": 10,
        }
    )
    watch = store.create_watch(
        {
            "target_id": target["id"],
            "name": "Fri starts, 2 nights",
            "mode": "weekend",
            "pattern": "4-2n",
            "arrival_weekdays": [4],
            "nights": 2,
            "window_start": "2026-07-01",
            "window_end": "2026-08-31",
            "site_filters": {"site_type": "tent", "loop": "A", "site": "", "min_people": 4},
            "specific_ranges": [],
            "cart_assist_enabled": True,
        }
    )
    run_id = store.start_scan_run(watch)
    store.finish_scan_run(run_id, "success", "No matching availability found.", candidate_count=3, available_count=0)
    store.upsert_result(
        {
            "watch_id": watch["id"],
            "target_id": target["id"],
            "campground_id": "232464",
            "campground_name": "Kalaloch",
            "campsite_id": "101",
            "site": "A01",
            "loop": "A",
            "campsite_type": "Tent",
            "arrival_date": "2026-07-03",
            "departure_date": "2026-07-05",
            "booking_url": "https://www.recreation.gov/camping/campsites/101",
        }
    )
    store.update_target(target["id"], {"active": False})
    store.update_watch(watch["id"], {"active": False})

    backup = store.export_config()

    assert backup["version"] == 1
    assert backup["exported_at"]
    assert "results" not in backup
    assert "scan_runs" not in backup
    exported_target = backup["targets"][0]
    assert exported_target["name"] == "Kalaloch"
    assert exported_target["campground_id"] == "232464"
    assert exported_target["release_window_value"] == 14
    assert exported_target["release_window_unit"] == "Days"
    assert exported_target["active"] is False
    assert "id" not in exported_target
    assert "last_status" not in exported_target
    exported_watch = exported_target["watches"][0]
    assert exported_watch["name"] == "Fri starts, 2 nights"
    assert exported_watch["site_filters"] == {"site_type": "tent", "loop": "A", "site": "", "min_people": 4}
    assert exported_watch["cart_assist_enabled"] is True
    assert exported_watch["active"] is False
    assert "id" not in exported_watch
    assert "next_scan_at" not in exported_watch


def test_import_config_restores_and_updates_idempotently(tmp_path) -> None:
    store = Store(tmp_path / "campfinder.db")
    store.init()
    backup = {
        "version": 1,
        "targets": [
            {
                "name": "Kalaloch",
                "campground_id": "232464",
                "park_name": "Olympic National Park",
                "state_code": "WA",
                "booking_url": "https://www.recreation.gov/camping/campgrounds/232464",
                "release_months": 6,
                "release_window_value": 14,
                "release_window_unit": "Days",
                "release_time": "07:00",
                "timezone": "America/Los_Angeles",
                "poll_interval_minutes": 5,
                "active": False,
                "watches": [
                    {
                        "name": "Fri starts, 2 nights",
                        "mode": "weekend",
                        "pattern": "4-2n",
                        "arrival_weekdays": [4],
                        "nights": 2,
                        "window_start": "2026-07-01",
                        "window_end": "2026-08-31",
                        "site_filters": {"site_type": "tent", "loop": "A", "site": "", "min_people": 4},
                        "specific_ranges": [],
                        "cart_assist_enabled": True,
                        "active": True,
                    }
                ],
            }
        ],
    }

    first = store.import_config(backup, min_poll_interval_minutes=10)
    second = store.import_config(backup, min_poll_interval_minutes=10)

    assert first == {
        "target_count": 1,
        "imported_targets": 1,
        "updated_targets": 0,
        "created_watches": 1,
        "updated_watches": 0,
    }
    assert second == {
        "target_count": 1,
        "imported_targets": 0,
        "updated_targets": 1,
        "created_watches": 0,
        "updated_watches": 1,
    }
    targets = store.list_targets()
    watches = store.list_watches()
    assert len(targets) == 1
    assert len(watches) == 1
    assert targets[0]["active"] == 0
    assert targets[0]["release_window_value"] == 14
    assert targets[0]["release_window_unit"] == "Days"
    assert targets[0]["poll_interval_minutes"] == 10
    assert watches[0]["name"] == "Fri starts, 2 nights"
    assert watches[0]["site_filters"] == {"site_type": "tent", "loop": "A", "site": "", "min_people": 4}
    assert watches[0]["cart_assist_enabled"] == 1

    changed = deepcopy(backup)
    changed["targets"][0]["active"] = True
    changed["targets"][0]["watches"][0]["nights"] = 3
    changed["targets"][0]["watches"][0]["active"] = False
    updated = store.import_config(changed, min_poll_interval_minutes=10)

    assert updated["created_watches"] == 0
    assert updated["updated_watches"] == 1
    assert len(store.list_watches()) == 1
    assert store.list_targets()[0]["active"] == 1
    assert store.list_watches()[0]["nights"] == 3
    assert store.list_watches()[0]["active"] == 0


def test_delete_target_cascades_watches(tmp_path) -> None:
    store = Store(tmp_path / "campfinder.db")
    store.init()
    target = store.create_target(
        {
            "name": "Kalaloch",
            "campground_id": "232464",
            "park_name": "Olympic National Park",
            "state_code": "WA",
            "release_months": 6,
            "release_time": "07:00",
            "timezone": "America/Los_Angeles",
            "poll_interval_minutes": 10,
        }
    )
    watch = store.create_watch(
        {
            "target_id": target["id"],
            "name": "Fri starts, 2 nights",
            "mode": "weekend",
            "pattern": "4-2n",
            "arrival_weekdays": [4],
            "nights": 2,
            "window_start": "2026-07-01",
            "window_end": "2026-08-31",
            "specific_ranges": [],
        }
    )

    assert store.delete_target(target["id"]) is True
    assert store.get_watch(watch["id"]) is None


def test_update_target_release_settings(tmp_path) -> None:
    store = Store(tmp_path / "campfinder.db")
    store.init()
    target = store.create_target(
        {
            "name": "Kalaloch",
            "campground_id": "232464",
            "park_name": "Olympic National Park",
            "state_code": "WA",
            "release_months": 6,
            "release_time": "07:00",
            "timezone": "America/Los_Angeles",
            "poll_interval_minutes": 10,
        }
    )

    updated = store.update_target(
        target["id"],
        {
            "release_months": 5,
            "release_window_value": 14,
            "release_window_unit": "Days",
            "release_time": "08:30",
            "timezone": "America/Denver",
            "poll_interval_minutes": 3,
        },
        min_poll_interval_minutes=10,
    )

    assert updated is not None
    assert updated["release_months"] == 5
    assert updated["release_window_value"] == 14
    assert updated["release_window_unit"] == "Days"
    assert updated["release_time"] == "08:30"
    assert updated["timezone"] == "America/Denver"
    assert updated["poll_interval_minutes"] == 10


def test_create_watch_stores_site_filters(tmp_path) -> None:
    store = Store(tmp_path / "campfinder.db")
    store.init()
    target = store.create_target(
        {
            "name": "Kalaloch",
            "campground_id": "232464",
            "park_name": "Olympic National Park",
            "state_code": "WA",
            "release_months": 6,
            "release_time": "07:00",
            "timezone": "America/Los_Angeles",
            "poll_interval_minutes": 10,
        }
    )

    watch = store.create_watch(
        {
            "target_id": target["id"],
            "name": "Tent loop",
            "mode": "weekend",
            "pattern": "4-2n",
            "arrival_weekdays": [4],
            "nights": 2,
            "window_start": "2026-07-01",
            "window_end": "2026-08-31",
            "site_filters": {"site_type": "tent", "loop": "A", "site": "", "min_people": 4},
            "specific_ranges": [],
        }
    )

    assert watch["site_filters"] == {"site_type": "tent", "loop": "A", "site": "", "min_people": 4}


def test_update_watch_active_state_and_resume_scan_time(tmp_path) -> None:
    store = Store(tmp_path / "campfinder.db")
    store.init()
    target = store.create_target(
        {
            "name": "Kalaloch",
            "campground_id": "232464",
            "park_name": "Olympic National Park",
            "state_code": "WA",
            "release_months": 6,
            "release_time": "07:00",
            "timezone": "America/Los_Angeles",
            "poll_interval_minutes": 10,
        }
    )
    watch = store.create_watch(
        {
            "target_id": target["id"],
            "name": "Fri starts, 2 nights",
            "mode": "weekend",
            "pattern": "4-2n",
            "arrival_weekdays": [4],
            "nights": 2,
            "window_start": "2026-07-01",
            "window_end": "2026-08-31",
            "specific_ranges": [],
        }
    )

    paused = store.update_watch(watch["id"], {"active": False})
    resumed = store.update_watch(watch["id"], {"active": True})

    assert paused is not None
    assert paused["active"] == 0
    assert resumed is not None
    assert resumed["active"] == 1
    assert resumed["next_scan_at"] is not None


def test_update_watch_rules_and_filters(tmp_path) -> None:
    store = Store(tmp_path / "campfinder.db")
    store.init()
    target = store.create_target(
        {
            "name": "Kalaloch",
            "campground_id": "232464",
            "park_name": "Olympic National Park",
            "state_code": "WA",
            "release_months": 6,
            "release_time": "07:00",
            "timezone": "America/Los_Angeles",
            "poll_interval_minutes": 10,
        }
    )
    watch = store.create_watch(
        {
            "target_id": target["id"],
            "name": "Fri starts, 2 nights",
            "mode": "weekend",
            "pattern": "4-2n",
            "arrival_weekdays": [4],
            "nights": 2,
            "window_start": "2026-07-01",
            "window_end": "2026-08-31",
            "site_filters": {},
            "specific_ranges": [],
        }
    )

    updated = store.update_watch(
        watch["id"],
        {
            "name": "Thu/Sat tent loop",
            "arrival_weekdays": [3, 5],
            "nights": 3,
            "window_start": "2026-07-02",
            "window_end": "2026-08-15",
            "site_filters": {"site_type": "tent", "loop": "A", "site": "", "min_people": 4},
        },
    )

    assert updated is not None
    assert updated["name"] == "Thu/Sat tent loop"
    assert updated["arrival_weekdays"] == [3, 5]
    assert updated["nights"] == 3
    assert updated["window_start"] == "2026-07-02"
    assert updated["window_end"] == "2026-08-15"
    assert updated["site_filters"] == {"site_type": "tent", "loop": "A", "site": "", "min_people": 4}
    assert updated["next_scan_at"] is not None


def test_cart_attempts_are_logged_once_per_result(tmp_path) -> None:
    store = Store(tmp_path / "campfinder.db")
    store.init()
    target = store.create_target(
        {
            "name": "Kalaloch",
            "campground_id": "232464",
            "park_name": "Olympic National Park",
            "state_code": "WA",
            "release_months": 6,
            "release_time": "07:00",
            "timezone": "America/Los_Angeles",
            "poll_interval_minutes": 10,
        }
    )
    watch = store.create_watch(
        {
            "target_id": target["id"],
            "name": "High priority weekend",
            "mode": "weekend",
            "pattern": "4-2n",
            "arrival_weekdays": [4],
            "nights": 2,
            "window_start": "2026-07-01",
            "window_end": "2026-08-31",
            "specific_ranges": [],
            "cart_assist_enabled": True,
        }
    )
    result, _created = store.upsert_result(
        {
            "watch_id": watch["id"],
            "target_id": target["id"],
            "campground_id": "232464",
            "campground_name": "Kalaloch",
            "campsite_id": "101",
            "site": "A01",
            "loop": "A",
            "campsite_type": "Tent",
            "arrival_date": "2026-07-03",
            "departure_date": "2026-07-05",
            "booking_url": "https://www.recreation.gov/camping/campsites/101",
        }
    )

    first, first_created = store.record_cart_attempt(result, "manual_required", "Ready for manual checkout.")
    second, second_created = store.record_cart_attempt(result, "manual_required", "Duplicate should be ignored.")

    assert first_created is True
    assert second_created is False
    assert second["id"] == first["id"]
    attempts = store.list_cart_attempts()
    assert len(attempts) == 1
    assert attempts[0]["watch_name"] == "High priority weekend"
    assert attempts[0]["target_name"] == "Kalaloch"
    assert attempts[0]["status"] == "manual_required"
    assert store.count_recent_cart_attempts(minutes=30) == 1


def test_app_settings_are_persisted_and_deleted(tmp_path) -> None:
    store = Store(tmp_path / "campfinder.db")
    store.init()

    store.set_app_settings({"cart_assist_enabled": "true", "recreation_gov_username": "camper@example.com"})
    store.set_app_settings({"cart_assist_enabled": "false"})

    assert store.get_app_settings(["cart_assist_enabled"]) == {"cart_assist_enabled": "false"}
    assert store.get_app_settings(["recreation_gov_username"]) == {
        "recreation_gov_username": "camper@example.com"
    }

    deleted = store.delete_app_settings(["recreation_gov_username"])

    assert deleted == 1
    assert store.get_app_settings(["recreation_gov_username"]) == {}


def test_list_scan_runs_includes_watch_and_target_names(tmp_path) -> None:
    store = Store(tmp_path / "campfinder.db")
    store.init()
    target = store.create_target(
        {
            "name": "Kalaloch",
            "campground_id": "232464",
            "park_name": "Olympic National Park",
            "state_code": "WA",
            "release_months": 6,
            "release_time": "07:00",
            "timezone": "America/Los_Angeles",
            "poll_interval_minutes": 10,
        }
    )
    watch = store.create_watch(
        {
            "target_id": target["id"],
            "name": "Fri starts, 2 nights",
            "mode": "weekend",
            "pattern": "4-2n",
            "arrival_weekdays": [4],
            "nights": 2,
            "window_start": "2026-07-01",
            "window_end": "2026-08-31",
            "specific_ranges": [],
        }
    )

    run_id = store.start_scan_run(watch)
    store.finish_scan_run(run_id, "success", "No matching availability found.", candidate_count=3, available_count=0)

    runs = store.list_scan_runs()

    assert len(runs) == 1
    assert runs[0]["watch_name"] == "Fri starts, 2 nights"
    assert runs[0]["target_name"] == "Kalaloch"
    assert runs[0]["candidate_count"] == 3
    assert runs[0]["available_count"] == 0


def test_result_status_updates_and_preserves_dismissal_on_rescan(tmp_path) -> None:
    store = Store(tmp_path / "campfinder.db")
    store.init()
    target = store.create_target(
        {
            "name": "Kalaloch",
            "campground_id": "232464",
            "park_name": "Olympic National Park",
            "state_code": "WA",
            "release_months": 6,
            "release_time": "07:00",
            "timezone": "America/Los_Angeles",
            "poll_interval_minutes": 10,
        }
    )
    watch = store.create_watch(
        {
            "target_id": target["id"],
            "name": "Fri starts, 2 nights",
            "mode": "weekend",
            "pattern": "4-2n",
            "arrival_weekdays": [4],
            "nights": 2,
            "window_start": "2026-07-01",
            "window_end": "2026-08-31",
            "specific_ranges": [],
        }
    )
    result_payload = {
        "watch_id": watch["id"],
        "target_id": target["id"],
        "campground_id": "232464",
        "campground_name": "Kalaloch",
        "campsite_id": "101",
        "site": "A01",
        "loop": "A",
        "campsite_type": "Tent",
        "arrival_date": "2026-07-03",
        "departure_date": "2026-07-05",
        "booking_url": "https://www.recreation.gov/camping/campsites/101",
    }

    result, created = store.upsert_result(result_payload)
    assert created is True
    assert result["status"] == "available"
    listed = store.list_results()
    assert listed[0]["park_name"] == "Olympic National Park"
    assert listed[0]["state_code"] == "WA"

    opened = store.update_result_status(result["id"], "opened")
    assert opened is not None
    assert opened["status"] == "opened"
    assert opened["opened_at"] is not None
    assert opened["active"] == 1

    dismissed = store.update_result_status(result["id"], "dismissed")
    assert dismissed is not None
    assert dismissed["status"] == "dismissed"
    assert dismissed["dismissed_at"] is not None
    assert dismissed["active"] == 0

    rescanned, created = store.upsert_result(result_payload)
    assert created is False
    assert rescanned["status"] == "dismissed"
    assert rescanned["active"] == 0

    second_result, created = store.upsert_result({**result_payload, "campsite_id": "102", "site": "A02"})
    assert created is True
    assert second_result["active"] == 1

    assert store.clear_active_results() == 1
    cleared = store.list_results()
    assert all(result["active"] == 0 for result in cleared)
    assert {result["status"] for result in cleared} == {"dismissed"}


def test_missing_active_results_are_marked_booked_after_successful_rescan(tmp_path) -> None:
    store = Store(tmp_path / "campfinder.db")
    store.init()
    target = store.create_target(
        {
            "name": "Kalaloch",
            "campground_id": "232464",
            "park_name": "Olympic National Park",
            "state_code": "WA",
            "release_months": 6,
            "release_time": "07:00",
            "timezone": "America/Los_Angeles",
            "poll_interval_minutes": 10,
        }
    )
    watch = store.create_watch(
        {
            "target_id": target["id"],
            "name": "Fri starts, 2 nights",
            "mode": "weekend",
            "pattern": "4-2n",
            "arrival_weekdays": [4],
            "nights": 2,
            "window_start": "2026-07-01",
            "window_end": "2026-08-31",
            "specific_ranges": [],
        }
    )
    base_payload = {
        "watch_id": watch["id"],
        "target_id": target["id"],
        "campground_id": "232464",
        "campground_name": "Kalaloch",
        "loop": "A",
        "campsite_type": "Tent",
        "arrival_date": "2026-07-03",
        "departure_date": "2026-07-05",
        "booking_url": "https://www.recreation.gov/camping/campsites/101",
    }
    still_available, _ = store.upsert_result({**base_payload, "campsite_id": "101", "site": "A01"})
    no_longer_available, _ = store.upsert_result({**base_payload, "campsite_id": "102", "site": "A02"})
    future_result, _ = store.upsert_result(
        {
            **base_payload,
            "campsite_id": "103",
            "site": "A03",
            "arrival_date": "2026-07-10",
            "departure_date": "2026-07-12",
        }
    )

    marked = store.mark_missing_results_booked(
        watch["id"],
        [("2026-07-03", "2026-07-05")],
        {still_available["dedupe_key"]},
    )

    assert marked == 1
    results = {result["site"]: result for result in store.list_results(limit=10)}
    assert results["A01"]["status"] == "available"
    assert results["A01"]["active"] == 1
    assert results["A02"]["status"] == "booked"
    assert results["A02"]["active"] == 0
    assert results["A02"]["booked_at"] is not None
    assert results["A03"]["id"] == future_result["id"]
    assert results["A03"]["active"] == 1
