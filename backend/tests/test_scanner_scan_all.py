from __future__ import annotations

import asyncio
from datetime import date
from types import SimpleNamespace

from backend.app.cart_assist import CartAssistant
from backend.app.db import Store
from backend.app.recreation import Campsite, RateLimitError
from backend.app.scanner import Scanner


class EmptyAvailabilityClient:
    def __init__(self) -> None:
        self.calls = []

    async def monthly_availability(self, campground_id, month):
        self.calls.append((campground_id, month))
        return {}


class NoopNotifier:
    async def notify_results(self, results, store, max_items=5):
        return None

    async def notify_result(self, result, store):
        return None


class RecordingNotifier:
    def __init__(self) -> None:
        self.batches = []

    async def notify_results(self, results, store, max_items=5):
        self.batches.append((list(results), max_items))


class MultiSiteAvailabilityClient:
    async def monthly_availability(self, campground_id, month):
        return {
            "101": Campsite(
                campsite_id="101",
                site="A01",
                loop="A",
                campsite_type="Tent",
                max_num_people=4,
                availabilities={
                    "2026-07-03T00:00:00Z": "Available",
                    "2026-07-04T00:00:00Z": "Available",
                },
            ),
            "102": Campsite(
                campsite_id="102",
                site="A02",
                loop="A",
                campsite_type="Tent",
                max_num_people=4,
                availabilities={
                    "2026-07-03T00:00:00Z": "Available",
                    "2026-07-04T00:00:00Z": "Available",
                },
            ),
        }


class RateLimitedClient:
    def __init__(self) -> None:
        self.calls = 0

    async def monthly_availability(self, campground_id, month):
        self.calls += 1
        raise RateLimitError(retry_after_seconds=120)


def create_target_and_watch(
    store: Store,
    name: str = "Fri starts, 2 nights",
    cart_assist_enabled: bool = False,
) -> tuple[dict, dict]:
    existing_targets = store.list_targets()
    if existing_targets:
        target = existing_targets[0]
    else:
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
            "name": name,
            "mode": "weekend",
            "pattern": "4-2n",
            "arrival_weekdays": [4],
            "nights": 2,
            "window_start": "2026-07-01",
            "window_end": "2026-07-31",
            "site_filters": {},
            "specific_ranges": [],
            "cart_assist_enabled": cart_assist_enabled,
        }
    )
    return target, watch


def cart_settings(**overrides):
    defaults = {
        "cart_assist_enabled": True,
        "cart_assist_cooldown_minutes": 30,
        "cart_assist_max_attempts_per_scan": 1,
        "recreation_gov_username": "camper@example.com",
        "recreation_gov_password": "secret",
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_scan_all_watches_runs_each_active_watch(tmp_path) -> None:
    store = Store(tmp_path / "campfinder.db")
    store.init()
    create_target_and_watch(store)

    scanner = Scanner(store, EmptyAvailabilityClient(), NoopNotifier(), min_poll_interval_minutes=10)
    result = asyncio.run(scanner.scan_all_watches())

    assert result["watch_count"] == 1
    assert result["available_count"] == 0
    assert result["summaries"][0]["status"] == "success"


def test_scan_all_skips_paused_targets(tmp_path) -> None:
    store = Store(tmp_path / "campfinder.db")
    store.init()
    target, _watch = create_target_and_watch(store)
    store.update_target(target["id"], {"active": False})

    scanner = Scanner(store, EmptyAvailabilityClient(), NoopNotifier(), min_poll_interval_minutes=10)
    result = asyncio.run(scanner.scan_all_watches())

    assert result["watch_count"] == 0


def test_scan_batches_new_availability_notifications(tmp_path) -> None:
    store = Store(tmp_path / "campfinder.db")
    store.init()
    create_target_and_watch(store)
    notifier = RecordingNotifier()
    scanner = Scanner(
        store,
        MultiSiteAvailabilityClient(),
        notifier,
        min_poll_interval_minutes=10,
        api_request_delay_seconds=0,
        max_notification_results=3,
    )

    result = asyncio.run(scanner.scan_all_watches())

    assert result["available_count"] == 2
    assert len(notifier.batches) == 1
    batch, max_items = notifier.batches[0]
    assert len(batch) == 2
    assert max_items == 3
    saved_links = sorted(result["booking_url"] for result in store.list_results())
    assert saved_links == [
        "https://www.recreation.gov/camping/campsites/101?startDate=2026-07-03",
        "https://www.recreation.gov/camping/campsites/102?startDate=2026-07-03",
    ]


def test_scan_records_cart_attempts_for_high_priority_watches(tmp_path) -> None:
    store = Store(tmp_path / "campfinder.db")
    store.init()
    create_target_and_watch(store, cart_assist_enabled=True)
    notifier = RecordingNotifier()
    cart_assistant = CartAssistant(store, cart_settings())
    scanner = Scanner(
        store,
        MultiSiteAvailabilityClient(),
        notifier,
        min_poll_interval_minutes=10,
        cart_assistant=cart_assistant,
        api_request_delay_seconds=0,
        max_notification_results=3,
    )

    result = asyncio.run(scanner.scan_all_watches())

    assert result["available_count"] == 2
    assert "Cart Assist recorded 2 guarded attempt(s)." in result["summaries"][0]["message"]
    attempts = store.list_cart_attempts()
    assert [attempt["status"] for attempt in attempts] == ["skipped", "manual_required"]
    assert attempts[0]["message"].startswith("Skipped because this scan is limited")
    assert attempts[1]["site"] == "A01"


def test_scan_all_reuses_monthly_availability_between_watches(tmp_path) -> None:
    store = Store(tmp_path / "campfinder.db")
    store.init()
    create_target_and_watch(store, "First watch")
    create_target_and_watch(store, "Second watch")
    client = EmptyAvailabilityClient()
    scanner = Scanner(
        store,
        client,
        NoopNotifier(),
        min_poll_interval_minutes=10,
        api_request_delay_seconds=0,
        availability_cache_minutes=5,
    )

    asyncio.run(scanner.scan_all_watches())

    assert client.calls == [("232464", date(2026, 7, 1))]


def test_rate_limit_pauses_following_watches_without_more_api_calls(tmp_path) -> None:
    store = Store(tmp_path / "campfinder.db")
    store.init()
    create_target_and_watch(store, "First watch")
    create_target_and_watch(store, "Second watch")
    client = RateLimitedClient()
    scanner = Scanner(
        store,
        client,
        NoopNotifier(),
        min_poll_interval_minutes=10,
        api_request_delay_seconds=0,
        rate_limit_backoff_minutes=60,
    )

    result = asyncio.run(scanner.scan_all_watches())

    assert client.calls == 1
    assert [summary["status"] for summary in result["summaries"]] == ["rate_limited", "rate_limited"]
    assert result["summaries"][1]["candidate_count"] == 0
