import sqlite3

import pytest
from fastapi.testclient import TestClient

from backend.app import main
from backend.app.db import Store


def seed_results(store):
    store.init()
    rows = []
    for park, campground in (("Demo Olympic", "Demo Coast"), ("Demo Rainier", "Demo Mountain")):
        target = store.create_target({"name": campground, "park_name": park, "campground_id": campground})
        watch = store.create_watch({"name": "Demo weekend", "target_id": target["id"], "mode": "weekend",
                                    "window_start": "2027-07-01", "window_end": "2027-08-01", "active": False})
        for day in (2, 9):
            for site in ("A", "B"):
                result, _ = store.upsert_result({
                    "watch_id": watch["id"], "target_id": target["id"], "campground_id": campground,
                    "campground_name": campground, "campsite_id": f"{campground}-{site}",
                    "site": site, "loop": "Demo", "campsite_type": "Tent",
                    "arrival_date": f"2027-07-{day:02d}", "departure_date": f"2027-07-{day+2:02d}",
                })
                rows.append(result)
    return rows


@pytest.fixture
def results_store(tmp_path):
    store = Store(tmp_path / "results.db")
    return store, seed_results(store)


def test_dismiss_group_preserves_other_dates_parks_and_bookings(results_store):
    store, rows = results_store
    store.update_result_status(rows[1]["id"], "opened")
    store.update_result_status(rows[2]["id"], "booked")
    ids = [row["id"] for row in rows[:3]]
    assert store.dismiss_result_group(ids + ids + [999]) == 2
    saved = {row["id"]: row for row in store.list_results()}
    assert all(saved[row["id"]]["status"] == "dismissed" and saved[row["id"]]["dismissed_at"] for row in rows[:2])
    assert saved[rows[2]["id"]]["status"] == "booked"
    assert all(saved[row["id"]]["active"] for row in rows[3:])
    assert len(store.list_watches()) == 2
    assert store.dismiss_result_group(ids) == 0
    assert store.update_result_status(rows[0]["id"], "available")["active"] == 1


def test_dismiss_group_rolls_back_on_failure(results_store):
    store, rows = results_store
    with store.connect() as conn:
        conn.execute(f"""CREATE TRIGGER reject_dismiss BEFORE UPDATE ON results
            WHEN NEW.id = {rows[1]['id']} AND NEW.status = 'dismissed'
            BEGIN SELECT RAISE(ABORT, 'injected write failure'); END""")
    with pytest.raises(sqlite3.IntegrityError):
        store.dismiss_result_group([row["id"] for row in rows[:2]])
    assert store.result_summary()["active_count"] == 8


def test_dismiss_group_api_validates_and_counts(results_store, monkeypatch):
    store, rows = results_store
    monkeypatch.setattr(main, "store", store)
    client = TestClient(main.app)
    for ids in ([], [0], [-1], list(range(1, 2002))):
        assert client.post("/api/results/dismiss-group", json={"result_ids": ids}).status_code == 422
    response = client.post("/api/results/dismiss-group", json={"result_ids": [row["id"] for row in rows[:4]]})
    assert response.status_code == 200
    assert response.json() == {"dismissed_count": 4}
    assert store.result_summary()["active_count"] == 4
