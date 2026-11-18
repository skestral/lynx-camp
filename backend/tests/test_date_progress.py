"""Durable stay checkpoints, using synthetic availability and isolated databases."""
import asyncio
from datetime import UTC, date, datetime, timedelta

import pytest

from backend.app.db import Store
from backend.app.recreation import Campsite, RateLimitError
from backend.app.scanner import Scanner


DATES = [date(2027, 6, day) for day in (4, 11, 18)]


class Client:
    def __init__(self, failure=None):
        self.failure = failure
        self.calls = []

    async def trip_availability(self, campground_id, arrival, departure, before_request=None):
        self.calls.append(arrival)
        if self.failure == arrival:
            raise RateLimitError(3600)
        return [Campsite(f"{campground_id}:-100:-9", "Cabin", "", "Roofed", None, {})]


class Notifier:
    def __init__(self):
        self.arrivals = []

    async def notify_results(self, results, store, max_items):
        self.arrivals.extend(result["arrival_date"] for result in results)


@pytest.fixture
def setup(tmp_path, monkeypatch):
    class ScanDate(date):
        @classmethod
        def today(cls):
            return cls(2026, 11, 17)

    monkeypatch.setattr("backend.app.scanner.date", ScanDate)
    store = Store(tmp_path / "progress.db")
    store.init()
    target = store.create_target({"name": "Example Roofed", "campground_id": "gtc:wa:-1:1"})
    watch = store.create_watch({"target_id": target["id"], "name": "Weekends", "mode": "specific",
        "window_start": DATES[0].isoformat(), "window_end": "2027-06-20",
        "specific_ranges": [{"arrival_date": arrival.isoformat(),
                             "departure_date": (arrival + timedelta(days=2)).isoformat()} for arrival in DATES]})
    return store, watch


def scanner(store, client, notifier):
    return Scanner(store, client, notifier, 60, api_request_delay_seconds=0, availability_cache_minutes=0)


def expire_cooldown(scan):
    scan._provider_backoffs["goingtocamp"]["until"] = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    scan._provider_backoffs["goingtocamp"]["delay"] = 0
    scan._save_runtime()


def test_restart_resumes_unfinished_date_without_cache_and_preserves_prior_matches(setup):
    store, watch = setup
    notifier = Notifier()
    first = scanner(store, Client(DATES[2]), notifier)

    async def scenario():
        summary = await first.scan_all_watches()
        assert summary["status"] == "waiting", summary
        assert summary["completed_stay_count"] == 2
        assert summary["estimated_requests_remaining"] == 1
        assert first.client.calls == DATES
        assert len(notifier.arrivals) == 2
        seen_before = {r["id"]: r["last_seen_at"] for r in store.list_results()}
        expire_cooldown(first)
        restarted_store = Store(store.database_path)
        restarted_store.init()
        recovered = scanner(restarted_store, Client(), notifier)
        recovered.restore_runtime_state()
        result = await recovered.scan_all_watches()
        assert result["status"] == "completed" and result["available_count"] == 3
        assert recovered.client.calls == [DATES[2]]
        assert notifier.arrivals == [d.isoformat() for d in DATES]
        assert all(r["active"] for r in store.list_results())
        assert all(r["last_seen_at"] == seen_before[r["id"]] for r in store.list_results() if r["id"] in seen_before)
        assert not store.scan_checkpoint(watch["id"])
        await recovered.scan_all_watches()
        assert recovered.client.calls == [DATES[2], *DATES]
        assert len(notifier.arrivals) == 3

    asyncio.run(scenario())


@pytest.mark.parametrize("action", ["pause", "edit", "delete"])
def test_checkpoint_follows_watch_lifecycle(setup, action):
    store, watch = setup
    scan = scanner(store, Client(DATES[1]), Notifier())

    async def scenario():
        await scan.scan_all_watches()
        assert len(store.scan_checkpoint(watch["id"])["completed"]) == 1
        expire_cooldown(scan)
        if action == "delete":
            await scan.delete_watches([watch["id"]])
            assert store.scan_checkpoint_summaries() == {}
            assert scan.scan_status()["remaining_count"] == 0
            return
        if action == "edit":
            store.update_watch(watch["id"], {"site_filters": {"site_type": "Roofed"}})
            assert store.scan_checkpoint(watch["id"]) == {}
        else:
            scan.cancel_current_scan()
            store.update_watch(watch["id"], {"active": False})
            store.update_watch(watch["id"], {"active": True})
            assert store.scan_checkpoint(watch["id"])
        recovered = scanner(store, Client(), Notifier())
        recovered.restore_runtime_state()
        if action == "pause":
            await recovered.scan_due_watches()
            assert recovered.client.calls == []
            recovered.start_full_scan()
            await recovered._sweep_task
        else:
            await recovered.scan_all_watches()
        assert recovered.client.calls == (DATES if action == "edit" else DATES[1:])

    asyncio.run(scenario())


def test_existing_database_migrates_checkpoints_idempotently(setup):
    store, watch = setup
    with store.connect() as conn:
        conn.execute("DROP TABLE scan_checkpoints")
    store.init()
    store.init()
    assert store.get_watch(watch["id"])["specific_ranges"] == watch["specific_ranges"]
    assert store.scan_checkpoint(watch["id"]) == {}
    store.save_scan_checkpoint(watch["id"], {"completed": {}, "remaining_requests": 3})
    assert store.scan_checkpoint_summaries()[watch["id"]]["remaining_requests"] == 3


def test_midnight_does_not_shift_cursor_and_skip_the_next_stay(setup, monkeypatch):
    store, _ = setup
    first = scanner(store, Client(DATES[1]), Notifier())

    async def scenario():
        await first.scan_all_watches()
        expire_cooldown(first)

        class Tomorrow(date):
            @classmethod
            def today(cls):
                return cls(2027, 6, 5)

        monkeypatch.setattr("backend.app.scanner.date", Tomorrow)
        recovered = scanner(store, Client(), Notifier())
        recovered.restore_runtime_state()
        await recovered.scan_all_watches()
        assert recovered.client.calls == DATES[1:]

    asyncio.run(scenario())


def test_recreation_resume_does_not_fetch_an_already_completed_month(setup):
    store, watch = setup
    target = store.create_target({"name": "Federal example", "campground_id": "123"})
    store.update_watch(watch["id"], {"target_id": target["id"], "window_end": "2027-07-04", "specific_ranges": [
        {"arrival_date": "2027-06-04", "departure_date": "2027-06-06"},
        {"arrival_date": "2027-07-02", "departure_date": "2027-07-04"}]})

    class MonthlyClient:
        def __init__(self, fail=False):
            self.calls, self.fail = [], fail

        async def monthly_availability(self, campground_id, month):
            self.calls.append(month)
            if self.fail and month.month == 7:
                raise RateLimitError(3600)
            return {}

    async def scenario():
        first = scanner(store, MonthlyClient(True), Notifier())
        await first.scan_all_watches()
        assert first.scan_status()["completed_stay_count"] == 1
        first._api_backoff_until = datetime.now(UTC) - timedelta(seconds=1)
        first._save_runtime()
        recovered = scanner(store, MonthlyClient(), Notifier())
        recovered.restore_runtime_state()
        await recovered.scan_all_watches()
        assert recovered.client.calls == [date(2027, 7, 1)]

    asyncio.run(scenario())
