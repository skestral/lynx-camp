from __future__ import annotations

import asyncio

from backend.app.db import Store
from backend.app.scanner import Scanner


class EmptyAvailabilityClient:
    async def monthly_availability(self, campground_id, month):
        return {}


class NoopNotifier:
    async def notify_result(self, result, store):
        return None


def test_scan_all_watches_runs_each_active_watch(tmp_path) -> None:
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
    store.create_watch(
        {
            "target_id": target["id"],
            "name": "Fri starts, 2 nights",
            "mode": "weekend",
            "pattern": "4-2n",
            "arrival_weekdays": [4],
            "nights": 2,
            "window_start": "2026-07-01",
            "window_end": "2026-07-31",
            "site_filters": {},
            "specific_ranges": [],
        }
    )

    scanner = Scanner(store, EmptyAvailabilityClient(), NoopNotifier(), min_poll_interval_minutes=10)
    result = asyncio.run(scanner.scan_all_watches())

    assert result["watch_count"] == 1
    assert result["available_count"] == 0
    assert result["summaries"][0]["status"] == "success"


def test_scan_all_skips_paused_targets(tmp_path) -> None:
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
    store.create_watch(
        {
            "target_id": target["id"],
            "name": "Fri starts, 2 nights",
            "mode": "weekend",
            "pattern": "4-2n",
            "arrival_weekdays": [4],
            "nights": 2,
            "window_start": "2026-07-01",
            "window_end": "2026-07-31",
            "site_filters": {},
            "specific_ranges": [],
        }
    )
    store.update_target(target["id"], {"active": False})

    scanner = Scanner(store, EmptyAvailabilityClient(), NoopNotifier(), min_poll_interval_minutes=10)
    result = asyncio.run(scanner.scan_all_watches())

    assert result["watch_count"] == 0
