"""Slow local storage must not monopolize the API event loop."""
import asyncio
from datetime import date, timedelta
import threading
import time
import sqlite3

import httpx
import pytest

from backend.app.db import Store
from backend.app.background_io import monitor_event_loop
from backend.app.recreation import Campsite
from backend.app.scanner import Scanner


class Client:
    async def trip_availability(self, campground_id, arrival, departure, before_request=None):
        return [Campsite(f"{campground_id}:-100:{i}", str(i), "", "Roofed", None, {}) for i in range(200)]


class Notifier:
    async def notify_results(self, *args):
        return 0


@pytest.fixture
def setup(tmp_path, monkeypatch):
    store = Store(tmp_path / "responsive.db")
    store.init()
    target = store.create_target({"campground_id": "gtc:wa:-1:1", "name": "Synthetic cabins"})
    arrival = date.today() + timedelta(days=30)
    watch = store.create_watch({"target_id": target["id"], "name": "One stay", "mode": "specific",
        "window_start": arrival.isoformat(), "window_end": (arrival + timedelta(days=1)).isoformat(),
        "specific_ranges": [{"arrival_date": arrival.isoformat(), "departure_date": (arrival + timedelta(days=1)).isoformat()}]})
    scanner = Scanner(store, Client(), Notifier(), 60, api_request_delay_seconds=0)
    from backend.app import main
    monkeypatch.setattr(main, "store", store)
    monkeypatch.setattr(main, "scanner", scanner)
    return store, scanner, watch, main.app


def test_health_responds_while_results_are_being_saved(setup, monkeypatch):
    store, scanner, watch, app = setup
    writing = threading.Event()
    original = store.upsert_result

    def slow_write(*args, **kwargs):
        writing.set()
        time.sleep(0.005)
        return original(*args, **kwargs)

    monkeypatch.setattr(store, "upsert_result", slow_write)

    async def scenario():
        scan = asyncio.create_task(scanner.scan_watch(watch["id"]))
        await asyncio.to_thread(writing.wait, 5)
        still_scanning = not scan.done()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
            started = time.monotonic()
            response = await client.get("/api/health")
            elapsed = time.monotonic() - started
        await scan
        assert still_scanning, "Result persistence blocked the event loop until the entire scan finished"
        assert response.status_code == 200 and elapsed < 0.5
        assert len(store.list_results()) == 200

    asyncio.run(scenario())


def test_task_cancellation_keeps_scan_lock_until_database_worker_finishes(setup, monkeypatch):
    store, scanner, watch, app = setup
    entered, release = threading.Event(), threading.Event()
    original = store.upsert_results

    def held_batch(items):
        entered.set()
        assert release.wait(5)
        return original(items)

    monkeypatch.setattr(store, "upsert_results", held_batch)

    async def scenario():
        scan = asyncio.create_task(scanner.scan_watch(watch["id"]))
        try:
            assert await asyncio.to_thread(entered.wait, 2)
            for _ in range(2):
                scan.cancel()
                await asyncio.sleep(0.01)
                assert scanner.is_busy and not scan.done()
            with pytest.raises(ValueError, match="Stop the current scan"):
                await scanner.delete_watches([watch["id"]])
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
                for path in ("/api/health", "/api/scans/status", "/api/targets", "/api/results"):
                    assert (await asyncio.wait_for(client.get(path), 1)).status_code == 200
        finally:
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await scan
        assert not scanner.is_busy
        assert len(store.list_results()) == 100
        assert store.scan_checkpoint(watch["id"]) == {}
        assert store.list_scan_runs()[0]["status"] == "interrupted"

    asyncio.run(scenario())


def test_stop_between_batches_preserves_matches_without_completing_the_stay(setup, monkeypatch):
    store, scanner, watch, _ = setup
    original = store.upsert_results

    def stop_after_batch(items):
        saved = original(items)
        scanner._cancel_requested = True
        return saved

    monkeypatch.setattr(store, "upsert_results", stop_after_batch)

    async def scenario():
        assert (await scanner.scan_watch(watch["id"]))["status"] == "cancelled"
        assert len(store.list_results()) == 100
        assert store.scan_checkpoint(watch["id"]) == {}
        monkeypatch.setattr(store, "upsert_results", original)
        assert (await scanner.scan_watch(watch["id"]))["status"] == "success"
        assert len(store.list_results()) == 200
        assert all(row["active"] for row in store.list_results())
        with store.connect() as conn:
            assert conn.execute("SELECT COUNT(*) FROM availability_findings").fetchone()[0] == 200

    asyncio.run(scenario())


def result_data(watch, site):
    return {"watch_id": watch["id"], "target_id": watch["target_id"], "campground_id": watch["campground_id"],
        "campground_name": "Synthetic cabins", "campsite_id": f"{watch['campground_id']}:-100:{site}", "site": str(site),
        "arrival_date": watch["window_start"], "departure_date": watch["window_end"]}


def test_result_batch_is_atomic_and_bounded(setup):
    store, _, watch, _ = setup
    valid = result_data(watch, 1)
    invalid = {**result_data(watch, 2), "watch_id": -999}
    with pytest.raises(sqlite3.IntegrityError):
        store.upsert_results([valid, invalid])
    assert store.list_results() == []
    with store.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM availability_findings").fetchone()[0] == 0
    with pytest.raises(ValueError, match="too large"):
        store.upsert_results([valid] * 101)
    assert store.upsert_results([]) == []


def test_batch_preserves_dismissals_and_journals_only_new_or_returning_matches(setup):
    store, _, watch, _ = setup
    items = [result_data(watch, i) for i in (1, 2)]
    first = store.upsert_results(items)
    assert all(is_new for _, is_new in first)
    store.update_result_status(first[0][0]["id"], "dismissed")
    store.mark_missing_results_booked(watch["id"], [(watch["window_start"], watch["window_end"])], set())
    second = store.upsert_results(items)
    assert second[0][0]["status"] == "dismissed" and not second[0][0]["notification_pending"]
    assert second[1][0]["status"] == "available" and second[1][0]["notification_pending"]
    store.upsert_results(items)
    with store.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM availability_findings").fetchone()[0] == 3


def test_event_loop_stall_is_logged_without_request_or_secret_data(caplog):
    async def scenario():
        monitor = asyncio.create_task(monitor_event_loop(interval=0.01, warning_after=0.01))
        await asyncio.sleep(0)
        time.sleep(0.05)
        await asyncio.sleep(0.02)
        monitor.cancel()
        with pytest.raises(asyncio.CancelledError):
            await monitor

    asyncio.run(scenario())
    assert "API event loop stalled" in caplog.text
