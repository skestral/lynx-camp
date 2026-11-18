"""Notification recovery with isolated stores and no provider or delivery traffic."""
from __future__ import annotations

import asyncio
from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from backend.app.db import Store
from backend.app.notifications import Notifier
from backend.app.provider_errors import ProviderResponseError
from backend.app.provider_ids import campground_url
from backend.app.recreation import Campsite, RateLimitError
from backend.app.scanner import Scanner
from backend.app.settings import Settings


CAMPGROUND = "gtc:wa:-1:1"
ARRIVAL = date(2027, 6, 4)


@pytest.fixture(autouse=True)
def calendar(monkeypatch):
    class ScanDate(date):
        @classmethod
        def today(cls):
            return cls(2026, 11, 17)

    monkeypatch.setattr("backend.app.scanner.date", ScanDate)


@pytest.fixture
def store(tmp_path):
    result = Store(tmp_path / "notifications.db")
    result.init()
    return result


def create_watch(store, *, two_stays=False):
    target = store.get_target_by_campground_id(CAMPGROUND) or store.create_target(
        {"name": "Example Roofed", "campground_id": CAMPGROUND})
    arrivals = [ARRIVAL, ARRIVAL + timedelta(days=7)] if two_stays else [ARRIVAL]
    ranges = [{"arrival_date": arrival.isoformat(), "departure_date": (arrival + timedelta(days=2)).isoformat()}
              for arrival in arrivals]
    return store.create_watch({"target_id": target["id"], "name": "Roofed stays", "mode": "specific",
                               "window_start": ranges[0]["arrival_date"], "window_end": ranges[-1]["departure_date"],
                               "specific_ranges": ranges})


class RecordingNotifier:
    def __init__(self):
        self.batches = []
        self.error = None

    async def notify_results(self, results, store, max_items):
        if self.error:
            raise self.error
        self.batches.append(list(results))


class AvailabilityClient:
    def __init__(self):
        self.calls = 0
        self.failure = None
        self.available = True
        self.booking_url = None
        self.scanner = None
        self.on_second_request = None

    async def trip_availability(self, campground_id, arrival, departure, before_request=None):
        self.calls += 1
        if before_request:
            await before_request()
        if self.calls == 2:
            if self.on_second_request:
                self.on_second_request()
            if self.failure == "cancel":
                self.scanner.cancel_current_scan()
            elif self.failure == "error":
                raise ProviderResponseError("Synthetic later-stay failure")
            elif self.failure == "task_cancel":
                raise asyncio.CancelledError()
            elif self.failure == "rate_limit":
                raise RateLimitError(3600)
        if not self.available:
            return []
        return [Campsite(f"{campground_id}:-100:-9", "Site -9", "", "Roofed", None, {},
                         booking_url=self.booking_url)]


def make_scanner(store, client, notifier, *, cache_minutes=0):
    scanner = Scanner(store, client, notifier, 60, api_request_delay_seconds=0,
                      availability_cache_minutes=cache_minutes)
    client.scanner = scanner
    return scanner


async def interrupt(scanner, watch_id, mode):
    if mode == "error":
        with pytest.raises(ProviderResponseError, match="later-stay"):
            await scanner.scan_watch(watch_id)
    elif mode == "task_cancel":
        with pytest.raises(asyncio.CancelledError):
            await scanner.scan_watch(watch_id)
    else:
        assert (await scanner.scan_watch(watch_id))["status"] == "cancelled"


@pytest.mark.parametrize("mode", ["cancel", "error", "task_cancel"])
@pytest.mark.parametrize("restart", [False, True])
def test_interrupted_matches_are_notified_once_after_revalidation(store, mode, restart):
    watch = create_watch(store, two_stays=True)
    client, notifier = AvailabilityClient(), RecordingNotifier()
    client.failure = mode
    scanner = make_scanner(store, client, notifier)

    async def scenario():
        await interrupt(scanner, watch["id"], mode)
        saved = store.list_results()
        assert len(saved) == 1 and saved[0]["notification_pending"] == 1
        assert notifier.batches == []
        resumed_store = Store(store.database_path) if restart else store
        resumed_store.init()
        resumed = make_scanner(resumed_store, AvailabilityClient(), notifier) if restart else scanner
        resumed.client.failure = None
        resumed.client.calls = 0
        assert (await resumed.scan_watch(watch["id"]))["status"] == "success"
        await resumed.scan_watch(watch["id"])
        assert len(notifier.batches) == 1
        assert len(notifier.batches[0]) == 2
        assert saved[0]["id"] in {result["id"] for result in notifier.batches[0]}
        assert all(result["notification_pending"] == 0 for result in resumed_store.list_results())
        assert not resumed.is_busy

    asyncio.run(scenario())


def test_notifier_exception_leaves_pending_work_for_restart(store):
    watch = create_watch(store)
    notifier = RecordingNotifier()
    notifier.error = RuntimeError("Synthetic delivery interruption")
    scanner = make_scanner(store, AvailabilityClient(), notifier)

    async def scenario():
        with pytest.raises(RuntimeError, match="delivery interruption"):
            await scanner.scan_watch(watch["id"])
        assert store.list_results()[0]["notification_pending"] == 1
        resumed_store = Store(store.database_path)
        resumed_store.init()
        notifier.error = None
        resumed = make_scanner(resumed_store, AvailabilityClient(), notifier)
        await resumed.scan_watch(watch["id"])
        await resumed.scan_watch(watch["id"])
        assert len(notifier.batches) == 1
        assert resumed_store.list_results()[0]["notification_pending"] == 0

    asyncio.run(scenario())


def test_notification_recovery_retains_leaf_url_with_stable_root_identity(store):
    watch = create_watch(store)
    client, notifier = AvailabilityClient(), RecordingNotifier()
    leaf_url = campground_url(CAMPGROUND, ARRIVAL.isoformat(), (ARRIVAL + timedelta(days=2)).isoformat(),
                              campsite_id=f"{CAMPGROUND}:-101:-9")
    client.booking_url = leaf_url
    notifier.error = RuntimeError("Synthetic delivery interruption")

    async def scenario():
        with pytest.raises(RuntimeError, match="delivery interruption"):
            await make_scanner(store, client, notifier).scan_watch(watch["id"])
        resumed_store = Store(store.database_path)
        resumed_store.init()
        assert resumed_store.list_results()[0]["booking_url"] == leaf_url
        notifier.error = None
        await make_scanner(resumed_store, client, notifier).scan_watch(watch["id"])
        result = resumed_store.list_results()[0]
        assert result["campsite_id"] == f"{CAMPGROUND}:-100:-9"
        assert result["booking_url"] == notifier.batches[0][0]["booking_url"] == leaf_url

    asyncio.run(scenario())


def test_rate_limited_partial_scan_consumes_its_notifications(store):
    watch = create_watch(store, two_stays=True)
    client, notifier = AvailabilityClient(), RecordingNotifier()
    client.failure = "rate_limit"
    result = asyncio.run(make_scanner(store, client, notifier).scan_watch(watch["id"]))
    assert result["status"] == "rate_limited"
    assert len(notifier.batches) == 1 and len(notifier.batches[0]) == 1
    assert store.list_results()[0]["notification_pending"] == 0


def test_reappearance_reuses_result_and_alerts_once_after_restart(store):
    watch = create_watch(store)
    client, notifier = AvailabilityClient(), RecordingNotifier()
    scanner = make_scanner(store, client, notifier)

    async def scenario():
        await scanner.scan_watch(watch["id"])
        original = store.list_results()[0]
        client.available = False
        assert (await scanner.scan_watch(watch["id"]))["missing_count"] == 1
        missing = store.list_results()[0]
        assert missing["status"] == "booked" and missing["auto_missing"] == 1
        assert missing["notification_pending"] == 0 and missing["active"] == 0
        resumed_store = Store(store.database_path)
        resumed_store.init()
        resumed = make_scanner(resumed_store, AvailabilityClient(), notifier)
        await resumed.scan_watch(watch["id"])
        await resumed.scan_watch(watch["id"])
        result = resumed_store.list_results()[0]
        assert result["id"] == original["id"] and result["dedupe_key"] == original["dedupe_key"]
        assert result["status"] == "available" and result["active"] == 1
        assert result["booked_at"] is None and result["auto_missing"] == 0
        assert result["notification_pending"] == 0
        assert len(notifier.batches) == 2

    asyncio.run(scenario())


def apply_user_action(store, result, action):
    if action.startswith("cart_"):
        attempt, _ = store.record_cart_attempt(result, "manual_required", "Synthetic handoff")
        store.update_cart_attempt_status(attempt["id"], action.removeprefix("cart_"))
    elif action == "group_dismissed":
        store.dismiss_result_group([result["id"]])
    elif action == "clear":
        store.clear_active_results()
    else:
        store.update_result_status(result["id"], action)


@pytest.mark.parametrize("action", ["dismissed", "booked", "cart_booked", "cart_dismissed", "group_dismissed", "clear"])
def test_user_action_clears_pending_work_before_later_stay_finishes(store, action):
    watch = create_watch(store, two_stays=True)
    client, notifier = AvailabilityClient(), RecordingNotifier()
    scanner = make_scanner(store, client, notifier)
    client.on_second_request = lambda: apply_user_action(store, store.list_results()[0], action)

    async def scenario():
        await scanner.scan_watch(watch["id"])
        await scanner.scan_watch(watch["id"])
        first = next(result for result in store.list_results() if result["arrival_date"] == ARRIVAL.isoformat())
        expected = "booked" if action in {"booked", "cart_booked"} else "dismissed"
        assert first["status"] == expected and first["active"] == 0
        assert first["auto_missing"] == 0 and first["notification_pending"] == 0
        assert len(notifier.batches) == 1 and len(notifier.batches[0]) == 1
        assert notifier.batches[0][0]["id"] != first["id"]

    asyncio.run(scenario())


@pytest.mark.parametrize("action", ["booked", "dismissed", "cart_booked", "cart_dismissed"])
def test_explicit_action_overrides_automatic_disappearance(store, action):
    watch = create_watch(store)
    client, notifier = AvailabilityClient(), RecordingNotifier()
    scanner = make_scanner(store, client, notifier)

    async def scenario():
        await scanner.scan_watch(watch["id"])
        client.available = False
        await scanner.scan_watch(watch["id"])
        apply_user_action(store, store.list_results()[0], action)
        resumed_store = Store(store.database_path)
        resumed_store.init()
        resumed = make_scanner(resumed_store, AvailabilityClient(), notifier)
        await resumed.scan_watch(watch["id"])
        result = resumed_store.list_results()[0]
        assert result["status"] == action.removeprefix("cart_")
        assert result["active"] == 0 and result["auto_missing"] == 0
        assert result["notification_pending"] == 0 and len(notifier.batches) == 1

    asyncio.run(scenario())


def test_pending_match_not_returned_after_restart_is_not_notified(store):
    watch = create_watch(store, two_stays=True)
    client, notifier = AvailabilityClient(), RecordingNotifier()
    client.failure = "cancel"

    async def scenario():
        await interrupt(make_scanner(store, client, notifier), watch["id"], "cancel")
        resumed_store = Store(store.database_path)
        resumed_store.init()
        resumed_client = AvailabilityClient()
        resumed_client.available = False
        await make_scanner(resumed_store, resumed_client, notifier).scan_watch(watch["id"])
        assert notifier.batches == []
        result = resumed_store.list_results()[0]
        assert result["auto_missing"] == 1 and result["notification_pending"] == 0

    asyncio.run(scenario())


def test_overlapping_windows_do_not_duplicate_pending_notifications(store):
    watch = create_watch(store)
    store.update_watch(watch["id"], {"specific_ranges": watch["specific_ranges"] * 2})
    notifier = RecordingNotifier()
    asyncio.run(make_scanner(store, AvailabilityClient(), notifier).scan_watch(watch["id"]))
    assert len(notifier.batches) == 1 and len(notifier.batches[0]) == 1


def test_configuring_channel_later_does_not_notify_historical_matches(store, monkeypatch):
    watch = create_watch(store)
    notifier = Notifier(Settings(database_path=store.database_path), store)
    deliveries = []

    async def post(message, url):
        deliveries.append(message)
        return {"status": "sent", "message": "Synthetic delivery"}

    monkeypatch.setattr(notifier, "_post_webhook", post)

    async def scenario():
        await make_scanner(store, AvailabilityClient(), notifier).scan_watch(watch["id"])
        assert store.list_results()[0]["notification_pending"] == 0
        notifier.update_config({"webhook_url": "https://example.test/notifications"})
        resumed_store = Store(store.database_path)
        resumed_store.init()
        scanner = make_scanner(resumed_store, AvailabilityClient(), notifier)
        await scanner.scan_watch(watch["id"])
        assert deliveries == []
        scanner.client.available = False
        await scanner.scan_watch(watch["id"])
        scanner.client.available = True
        await scanner.scan_watch(watch["id"])
        assert len(deliveries) == 1

    asyncio.run(scenario())


@pytest.mark.parametrize("status", ["available", "opened", "booked", "dismissed"])
def test_migration_does_not_guess_old_bookings_or_queue_old_matches(store, status):
    watch = create_watch(store)
    notifier = RecordingNotifier()
    asyncio.run(make_scanner(store, AvailabilityClient(), notifier).scan_watch(watch["id"]))
    original = store.list_results()[0]
    store.update_result_status(original["id"], status)
    with store.connect() as conn:
        conn.execute("ALTER TABLE results DROP COLUMN notification_pending")
        conn.execute("ALTER TABLE results DROP COLUMN auto_missing")
    migrated = Store(store.database_path)
    migrated.init()
    migrated.init()
    before = migrated.list_results()[0]
    assert before["auto_missing"] == 0 and before["notification_pending"] == 0
    asyncio.run(make_scanner(migrated, AvailabilityClient(), notifier).scan_watch(watch["id"]))
    result = migrated.list_results()[0]
    assert result["status"] == status and result["id"] == original["id"]
    assert result["active"] == (1 if status in {"available", "opened"} else 0)
    assert result["notification_pending"] == 0 and len(notifier.batches) == 1


def test_denial_is_checked_before_reusing_cached_stay(store):
    first, second = create_watch(store), create_watch(store)
    client, notifier = AvailabilityClient(), RecordingNotifier()
    denied = False
    access_checks = []

    async def ensure_access():
        access_checks.append(True)
        if denied:
            raise ProviderResponseError("Synthetic persisted access stop")

    client.washington = SimpleNamespace(ensure_access=ensure_access)
    scanner = make_scanner(store, client, notifier, cache_minutes=5)

    async def scenario():
        nonlocal denied
        await scanner.scan_watch(first["id"])
        denied = True
        with pytest.raises(ProviderResponseError, match="access stop"):
            await scanner.scan_watch(second["id"])
        assert len(access_checks) == 2 and client.calls == 1
        assert len(notifier.batches) == 1 and len(store.list_results()) == 1
        assert store.list_results()[0]["active"] == 1

    asyncio.run(scenario())


def test_filter_validation_receives_category_before_fetching(store, monkeypatch):
    watch = create_watch(store)
    store.update_watch(watch["id"], {"site_filters": {"site_type": "Camping"}})
    calls = []

    def validate(filters, campground_id):
        calls.append((filters, campground_id))
        raise ProviderResponseError("Synthetic category mismatch")

    monkeypatch.setattr("backend.app.scanner.validate_watch_filters", validate)
    client, notifier = AvailabilityClient(), RecordingNotifier()
    with pytest.raises(ProviderResponseError, match="category mismatch"):
        asyncio.run(make_scanner(store, client, notifier).scan_watch(watch["id"]))
    assert calls == [({"site_type": "Camping"}, CAMPGROUND)]
    assert client.calls == 0 and notifier.batches == []
