from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest

from backend.app.cart_assist import CartAssistant
from backend.app.db import Store
from backend.app.recreation import Campsite, RateLimitError
from backend.app.scanner import Scanner


@pytest.fixture(autouse=True)
def scan_calendar(monkeypatch):
    # Availability fixtures below describe July 2026, independent of the host clock.
    class ScanDate(date):
        @classmethod
        def today(cls):
            return cls(2026, 6, 17)

    monkeypatch.setattr("backend.app.scanner.date", ScanDate)


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


class CancelAfterFirstFetchClient:
    def __init__(self) -> None:
        self.calls = 0
        self.scanner = None

    async def monthly_availability(self, campground_id, month):
        self.calls += 1
        if self.scanner is not None:
            self.scanner.cancel_current_scan()
        return {}


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
    assert len(notifier.batches) == 1
    batch, _max_items = notifier.batches[0]
    assert {item["cart_assist_message"] for item in batch} == {"Cart Assist recorded 2 attempts for this scan."}
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
    assert [summary["status"] for summary in result["summaries"]] == ["rate_limited"]
    assert result["status"] == "waiting"
    assert result["completed_count"] == 0
    assert result["remaining_count"] == 2
    assert len(store.list_scan_runs()) == 1
    assert result["estimated_remaining_seconds"] >= 3600
    asyncio.run(scanner.scan_due_watches())
    assert client.calls == 1
    assert len(store.list_scan_runs()) == 1


def test_cancel_current_scan_marks_active_run_cancelled(tmp_path) -> None:
    store = Store(tmp_path / "campfinder.db")
    store.init()
    create_target_and_watch(store)
    client = CancelAfterFirstFetchClient()
    scanner = Scanner(
        store,
        client,
        NoopNotifier(),
        min_poll_interval_minutes=10,
        api_request_delay_seconds=0,
    )
    client.scanner = scanner

    result = asyncio.run(scanner.scan_all_watches())

    assert client.calls == 1
    assert result["summaries"][0]["status"] == "cancelled"
    assert store.list_scan_runs()[0]["status"] == "cancelled"
    event_types = [event["event_type"] for event in store.list_scan_events()]
    assert "cancel_requested" in event_types
    assert "cancelled" in event_types


def test_partial_matches_are_notified_before_rate_limit_cooldown(tmp_path):
    store = Store(tmp_path / "test.db")
    store.init()
    _, watch = create_target_and_watch(store)
    store.update_watch(watch["id"], {"window_end": "2026-08-31"})

    class LimitedNextMonth(MultiSiteAvailabilityClient):
        async def monthly_availability(self, campground_id, month):
            if month.month == 8:
                raise RateLimitError(120)
            return await super().monthly_availability(campground_id, month)

    notifier = RecordingNotifier()
    scanner = Scanner(store, LimitedNextMonth(), notifier, 60, api_request_delay_seconds=0)
    result = asyncio.run(scanner.scan_all_watches())
    assert result["status"] == "waiting"
    assert result["completed_count"] == 0
    assert result["remaining_count"] == 1
    assert len(notifier.batches) == 1
    assert len(notifier.batches[0][0]) == 2


async def no_wait():
    pass


def test_pausing_one_watch_does_not_pause_entire_crawl(tmp_path):
    store = Store(tmp_path / "test.db")
    store.init()
    create_target_and_watch(store, "One")
    create_target_and_watch(store, "Two")

    class PausingClient:
        calls = 0

        async def monthly_availability(self, *_):
            self.calls += 1
            if self.calls == 1:
                store.bulk_update_watches([scanner.active_watch_id], "pause")
                scanner.cancel_current_scan(pause_crawl=False)
            return {}

    scanner = Scanner(store, PausingClient(), NoopNotifier(), 60, api_request_delay_seconds=0)
    result = asyncio.run(scanner.scan_all_watches())
    assert result["status"] == "completed"
    assert result["skipped_count"] == 1
    assert result["completed_count"] == 1
    assert not result["crawl_paused"]


def test_crawl_resumes_pending_work_after_restart(tmp_path):
    store = Store(tmp_path / "test.db")
    store.init()
    create_target_and_watch(store, "First")
    create_target_and_watch(store, "Second")

    class LimitedSecondRequest:
        calls = 0

        async def monthly_availability(self, *_):
            self.calls += 1
            if self.calls == 2:
                raise RateLimitError(120)
            return {}

    client = LimitedSecondRequest()
    scanner = Scanner(store, client, NoopNotifier(), 60, api_request_delay_seconds=0, availability_cache_minutes=0)
    result = asyncio.run(scanner.scan_all_watches())
    assert result["status"] == "waiting"
    assert result["completed_count"] == 1
    assert result["remaining_count"] == 1
    recovered_client = EmptyAvailabilityClient()
    recovered = Scanner(store, recovered_client, NoopNotifier(), 60)
    recovered.restore_runtime_state()
    assert recovered.scan_status()["completed_count"] == 1
    assert recovered.effective_request_delay >= 5
    asyncio.run(recovered.scan_due_watches())
    assert recovered_client.calls == []
    recovered._api_backoff_until = datetime.now(UTC) - timedelta(seconds=1)
    recovered._wait_for_api_slot = no_wait
    asyncio.run(recovered.scan_due_watches())
    assert len(recovered_client.calls) == 1
    assert recovered.scan_status()["status"] == "completed"
    assert recovered.scan_status()["completed_count"] == 2
    asyncio.run(recovered.scan_due_watches())
    assert len(recovered_client.calls) == 1  # Poll intervals prevent an immediate repeat.


def test_pause_during_cooldown_survives_restart(tmp_path):
    store = Store(tmp_path / "test.db")
    store.init()
    create_target_and_watch(store)
    scanner = Scanner(store, RateLimitedClient(), NoopNotifier(), 60, api_request_delay_seconds=0)
    asyncio.run(scanner.scan_all_watches())
    assert scanner.cancel_current_scan()["cancel_requested"]
    restored = Scanner(store, EmptyAvailabilityClient(), NoopNotifier(), 60)
    restored.restore_runtime_state()
    restored._api_backoff_until = datetime.now(UTC) - timedelta(seconds=1)
    asyncio.run(restored.scan_due_watches())
    assert restored.client.calls == []
    assert restored.scan_status()["crawl_paused"]
    assert restored.scan_status()["remaining_count"] == 1


def test_backoff_honors_retry_after_and_adapts_spacing(tmp_path):
    store = Store(tmp_path / "test.db")
    store.init()
    scanner = Scanner(store, EmptyAvailabilityClient(), NoopNotifier(), 60, api_request_delay_seconds=5)
    scanner._start_rate_limit_backoff(RateLimitError(7200))
    assert scanner.scan_status()["cooldown_seconds"] >= 7199
    assert scanner.effective_request_delay == 10
    scanner._start_rate_limit_backoff(RateLimitError(1))
    assert scanner.scan_status()["cooldown_seconds"] >= 7199
    assert scanner.effective_request_delay == 20


def test_failed_crawl_is_not_reported_as_complete(tmp_path):
    store = Store(tmp_path / "test.db")
    store.init()
    create_target_and_watch(store)

    class FailingClient:
        async def monthly_availability(self, *_):
            raise RuntimeError("provider unavailable")

    scanner = Scanner(store, FailingClient(), NoopNotifier(), 60, api_request_delay_seconds=0)
    result = asyncio.run(scanner.scan_all_watches())
    assert result["status"] == "incomplete"
    assert result["completed_count"] == 0
    assert result["failed_count"] == 1


def test_start_api_returns_before_scan_finishes_and_deduplicates(tmp_path, monkeypatch):
    import httpx
    from backend.app import main

    store = Store(tmp_path / "test.db")
    store.init()
    create_target_and_watch(store)

    async def scenario():
        release = asyncio.Event()

        class SlowClient:
            calls = 0

            async def monthly_availability(self, *_):
                self.calls += 1
                await release.wait()
                return {}

        scanner = Scanner(store, SlowClient(), NoopNotifier(), 60, api_request_delay_seconds=0)
        monkeypatch.setattr(main, "scanner", scanner)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://test") as client:
            response = await asyncio.wait_for(client.post("/api/scans/run-all"), timeout=1)
            assert response.status_code == 202
            assert response.json()["remaining_count"] == 1
            task = scanner._sweep_task
            await client.post("/api/scans/run-all")
            assert scanner._sweep_task is task
            status = (await client.get("/api/scans/status")).json()
            assert status["status"] in {"queued", "running"}
            release.set()
            await task
            assert scanner.client.calls == 1
            assert scanner.scan_status()["status"] == "completed"

    asyncio.run(scenario())
