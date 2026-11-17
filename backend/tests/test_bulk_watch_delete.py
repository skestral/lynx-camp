import asyncio
from datetime import UTC, datetime, timedelta
import sqlite3
import threading

import httpx
import pytest

from backend.app import main
from backend.app.db import Store
from backend.app.scanner import Scanner


TABLES = ("targets", "watches", "scan_runs", "scan_events", "results", "notification_events", "cart_attempts", "app_settings")


def populated_store(path, watch_count=3, results_per_watch=2):
    store = Store(path)
    store.init()
    target = store.create_target({"name": "Delete test", "campground_id": "demo"})
    now = datetime.now(UTC).isoformat()
    with store.connect() as conn:
        conn.executemany(
            """INSERT INTO watches (id, target_id, name, mode, window_start, window_end, active, created_at, updated_at)
               VALUES (?, ?, ?, 'weekend', '2027-07-01', '2027-07-31', 0, ?, ?)""",
            [(i, target["id"], f"Watch {i}", now, now) for i in range(1, watch_count + 1)],
        )
        conn.execute("""INSERT INTO scan_runs (id, watch_id, target_id, started_at, status)
                        SELECT id, id, target_id, created_at, 'success' FROM watches""")
        conn.execute("""INSERT INTO scan_events (run_id, watch_id, target_id, message, created_at)
                        SELECT id, watch_id, target_id, 'Completed check', started_at FROM scan_runs""")
        conn.executemany(
            """INSERT INTO results (watch_id, target_id, campground_id, campground_name, campsite_id, site,
                                    arrival_date, departure_date, booking_url, discovered_at, last_seen_at, dedupe_key)
               VALUES (?, ?, 'demo', 'Delete test', ?, ?, '2027-07-02', '2027-07-04', ?, ?, ?, ?)""",
            [(i, target["id"], str(site), str(site), f"https://example.invalid/{site}?startDate=2027-07-02", now, now, f"{i}-{site}")
             for i in range(1, watch_count + 1) for site in range(results_per_watch)],
        )
        conn.execute("""INSERT INTO notification_events (result_id, channel, status, message, sent_at)
                        SELECT id, 'webhook', 'sent', 'Demo record only', discovered_at FROM results""")
        conn.execute("""INSERT INTO cart_attempts (result_id, watch_id, target_id, campsite_id, site,
                                                  arrival_date, departure_date, booking_url, status, attempted_at)
                        SELECT id, watch_id, target_id, campsite_id, site, arrival_date, departure_date,
                               booking_url, 'manual_required', discovered_at FROM results""")
    store.set_app_settings({"notification_webhook_url": "https://example.invalid/private-demo"})
    return store


def table_counts(store):
    with store.connect() as conn:
        return {table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in TABLES}


def scanner_for(store):
    class OfflineClient:
        async def monthly_availability(self, *_):
            pytest.fail("Deletion must not make provider requests")

    return Scanner(store, OfflineClient(), None, 60)


def assert_foreign_keys_indexed(store):
    with store.connect() as conn:
        for table in TABLES:
            leading_columns = {
                conn.execute(f"PRAGMA index_info('{index['name']}')").fetchone()["name"]
                for index in conn.execute(f"PRAGMA index_list('{table}')").fetchall()
            }
            for foreign_key in conn.execute(f"PRAGMA foreign_key_list('{table}')").fetchall():
                column = foreign_key["from"]
                assert column in leading_columns, f"Missing child-key index for {table}.{column}"
                plan = conn.execute(f"EXPLAIN QUERY PLAN SELECT rowid FROM {table} WHERE {column} = ?", (1,)).fetchall()
                assert any("USING COVERING INDEX" in row["detail"] for row in plan)


def test_existing_populated_database_gets_indexes_without_data_loss(tmp_path):
    store = populated_store(tmp_path / "existing.db")
    before = table_counts(store)
    settings_before = store.get_app_settings()
    with store.connect() as conn:
        # Reproduce the previously shipped schema: only the group and UNIQUE indexes.
        indexes = conn.execute("SELECT name FROM sqlite_master WHERE type = 'index' AND sql IS NOT NULL AND name != 'watches_group_id'").fetchall()
        assert len(indexes) == 11
        for index in indexes:
            conn.execute(f"DROP INDEX {index['name']}")
    reopened = Store(store.database_path)
    reopened.init()
    assert_foreign_keys_indexed(reopened)
    reopened.init()  # Repeated startup is harmless.
    assert_foreign_keys_indexed(reopened)
    assert table_counts(reopened) == before
    assert reopened.get_app_settings() == settings_before
    with reopened.connect() as conn:
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_bulk_delete_cascades_across_chunks_and_preserves_unselected_data(tmp_path, monkeypatch):
    store = populated_store(tmp_path / "large.db", watch_count=550)
    scanner = scanner_for(store)
    monkeypatch.setattr(main, "store", store)
    monkeypatch.setattr(main, "scanner", scanner)

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://test") as client:
            response = await client.post("/api/watches/bulk", json={"action": "delete", "watch_ids": list(range(1, 526)) + [1, 9999]})
            assert response.status_code == 200
            assert response.json()["updated_count"] == 525
            assert table_counts(store) == {"targets": 1, "watches": 25, "scan_runs": 25, "scan_events": 25,
                                           "results": 50, "notification_events": 50, "cart_attempts": 50, "app_settings": 1}
            assert store.get_watch(526)
            assert store.get_app_settings()["notification_webhook_url"] == "https://example.invalid/private-demo"
            response = await client.delete("/api/watches/526")
            assert response.status_code == 200
            assert (await client.delete("/api/watches/526")).status_code == 404
            response = await client.post("/api/watches/bulk", json={"action": "delete", "watch_ids": list(range(527, 551))})
            assert response.json()["updated_count"] == 24
            assert table_counts(store) == {table: int(table in {"targets", "app_settings"}) for table in TABLES}
            with store.connect() as conn:
                assert conn.execute("PRAGMA foreign_key_check").fetchall() == []

    asyncio.run(scenario())


def test_failed_later_delete_chunk_rolls_back_history_and_keeps_queue(tmp_path):
    store = populated_store(tmp_path / "rollback.db", watch_count=501)
    scanner = scanner_for(store)
    scanner._begin_full_scan(store.list_watches())
    before = table_counts(store)
    runtime = store.get_app_settings(["scanner_runtime"])
    with store.connect() as conn:
        conn.execute("""CREATE TRIGGER reject_delete BEFORE DELETE ON watches
                        WHEN OLD.id = 501 BEGIN SELECT RAISE(ABORT, 'injected failure'); END""")
    with pytest.raises(sqlite3.IntegrityError, match="injected failure"):
        asyncio.run(scanner.delete_watches(list(range(1, 502))))
    assert table_counts(store) == before
    assert scanner.scan_status()["remaining_count"] == 501
    assert store.get_app_settings(["scanner_runtime"]) == runtime
    assert not scanner.is_busy


@pytest.mark.parametrize("paused", [False, True])
def test_delete_prunes_durable_queue_without_resetting_cooldown(tmp_path, paused):
    store = populated_store(tmp_path / "queue.db")
    scanner = scanner_for(store)
    scanner._begin_full_scan(store.list_watches())
    scanner._api_backoff_until = datetime.now(UTC) + timedelta(hours=1)
    scanner._adaptive_delay = 20
    if paused:
        scanner.cancel_current_scan()
    asyncio.run(scanner.delete_watches([1, 2]))
    restored = scanner_for(store)
    restored.restore_runtime_state()
    status = restored.scan_status()
    assert status["remaining_count"] == 1
    assert status["skipped_count"] == 2
    assert status["crawl_paused"] == paused
    assert status["cooldown_seconds"] > 3500
    assert status["effective_request_delay_seconds"] == 20
    asyncio.run(restored.delete_watches([3]))
    assert restored.scan_status()["remaining_count"] == 0
    assert restored.scan_status()["status"] == ("cancelled" if paused else "completed")
    again = scanner_for(store)
    again.restore_runtime_state()
    assert again.scan_status()["remaining_count"] == 0
    assert again.scan_status()["cooldown_seconds"] > 3500


def slow_delete(store, monkeypatch, entered, release):
    original = store.bulk_update_watches

    def blocked(ids, action):
        with store.connect() as conn:
            conn.execute("UPDATE watches SET active = 0")
            entered.set()
            assert release.wait(5), "The API event loop could not respond while deletion was waiting"
        return original(ids, action)

    monkeypatch.setattr(store, "bulk_update_watches", blocked)


@pytest.mark.parametrize("single", [False, True])
def test_api_stays_responsive_and_crawler_waits_during_deletion(tmp_path, monkeypatch, single):
    store = populated_store(tmp_path / "responsive.db", watch_count=1)
    scanner = scanner_for(store)
    scanner._begin_full_scan(store.list_watches())
    monkeypatch.setattr(main, "store", store)
    monkeypatch.setattr(main, "scanner", scanner)
    entered, release = threading.Event(), threading.Event()
    slow_delete(store, monkeypatch, entered, release)

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://test") as client:
            request = client.delete("/api/watches/1") if single else client.post("/api/watches/bulk", json={"action": "delete", "watch_ids": [1]})
            deletion = asyncio.create_task(request)
            scheduler = None
            try:
                assert await asyncio.to_thread(entered.wait, 2)
                assert not deletion.done()
                for path in ("/api/health", "/api/scans/status", "/api/targets", "/api/watches", "/api/results"):
                    assert (await asyncio.wait_for(client.get(path), timeout=1)).status_code == 200
                scheduler = asyncio.create_task(scanner.scan_due_watches())
                await asyncio.sleep(0)
                assert not scheduler.done()
                assert (await client.post("/api/watches/bulk", json={"action": "delete", "watch_ids": [1]})).status_code == 409
            finally:
                release.set()
                response = await deletion
                if scheduler:
                    await scheduler
            assert response.status_code == 200
            assert store.list_watches() == []
            assert scanner.scan_status()["remaining_count"] == 0

    asyncio.run(scenario())


def test_request_cancellation_keeps_scan_lock_until_delete_finishes(tmp_path, monkeypatch):
    store = populated_store(tmp_path / "disconnect.db", watch_count=1)
    scanner = scanner_for(store)
    scanner._begin_full_scan(store.list_watches())
    entered, release = threading.Event(), threading.Event()
    slow_delete(store, monkeypatch, entered, release)

    async def scenario():
        deletion = asyncio.create_task(scanner.delete_watches([1]))
        try:
            assert await asyncio.to_thread(entered.wait, 2)
            for _ in range(2):
                deletion.cancel()
                await asyncio.sleep(0)
                assert scanner.is_busy
                assert not deletion.done()
        finally:
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await deletion
        assert not scanner.is_busy
        assert store.list_watches() == []
        restored = scanner_for(store)
        restored.restore_runtime_state()
        assert restored.scan_status()["remaining_count"] == 0

    asyncio.run(scenario())
