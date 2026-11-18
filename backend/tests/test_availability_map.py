import pytest
from fastapi.testclient import TestClient

from backend.app import main
from backend.app.db import Store
from backend.tests.test_result_groups import seed_results


@pytest.fixture
def saved(tmp_path):
    store = Store(tmp_path / "map.db")
    return store, seed_results(store)


def test_calendar_counts_all_active_windows_and_dismissal(saved):
    store, rows = saved
    store.update_result_status(rows[0]["id"], "opened")
    store.update_result_status(rows[1]["id"], "booked")
    store.update_result_status(rows[2]["id"], "dismissed")
    with store.connect() as conn:
        conn.execute("UPDATE results SET active = 0 WHERE id = ?", (rows[3]["id"],))
    windows = store.availability_calendar()
    assert sum(window["match_count"] for window in windows) == 5
    assert len(windows) == 3
    assert all(window["last_seen_at"] for window in windows)
    assert all(set(window) == {"campground_id", "arrival_date", "departure_date", "match_count", "last_seen_at"} for window in windows)
    store.clear_active_results()
    assert store.availability_calendar() == []


def test_stay_requires_one_result_covering_all_occupied_nights(saved):
    store, _ = saved
    assert store.results_for_stay("2027-07-02", "2027-07-04")["total_count"] == 4
    assert store.results_for_stay("2027-07-03", "2027-07-04")["total_count"] == 4
    assert store.results_for_stay("2027-07-04", "2027-07-05")["total_count"] == 0
    assert store.results_for_stay("2027-07-01", "2027-07-03")["total_count"] == 0
    assert store.results_for_stay("2027-07-02", "2027-07-11")["total_count"] == 0
    # Neighbouring sites cannot combine into a two-night stay.
    with store.connect() as conn:
        conn.execute("UPDATE results SET departure_date = '2027-07-03' WHERE site = 'A'")
        conn.execute("UPDATE results SET arrival_date = '2027-07-03' WHERE site = 'B'")
    assert store.results_for_stay("2027-07-02", "2027-07-04")["total_count"] == 0


def test_stay_filters_before_limit_and_preserves_original_dates(saved):
    store, rows = saved
    store.update_result_status(rows[0]["id"], "dismissed")
    response = store.results_for_stay("2027-07-03", "2027-07-04", park_name="Demo Rainier", limit=1)
    assert response["total_count"] == 2
    assert len(response["results"]) == 1
    assert response["results"][0]["arrival_date"] == "2027-07-02"
    assert response["results"][0]["park_name"] == "Demo Rainier"
    assert store.results_for_stay("2027-07-02", "2027-07-04", campground_id="Demo Coast")["total_count"] == 1
    assert store.results_for_stay("2027-07-02", "2027-07-04", campground_id="' OR 1=1 --")["total_count"] == 0
    with store.connect() as conn:
        conn.execute("UPDATE targets SET park_name = '' WHERE name = 'Demo Mountain'")
    assert store.results_for_stay("2027-07-02", "2027-07-04", park_name="Unassigned park")["total_count"] == 2


def test_calendar_not_limited_to_dashboard_working_set(saved):
    store, rows = saved
    with store.connect() as conn:
        template = dict(conn.execute("SELECT * FROM results WHERE id = ?", (rows[0]["id"],)).fetchone())
        template.pop("id")
        copies = [{**template, "campsite_id": f"many-{n}", "dedupe_key": f"many-{n}"} for n in range(2005)]
        conn.executemany(f"INSERT INTO results ({','.join(template)}) VALUES ({','.join('?' for _ in template)})",
                         [tuple(row.values()) for row in copies])
    assert len(store.list_results()) == 2000
    assert sum(window["match_count"] for window in store.availability_calendar()) == 2013
    response = store.results_for_stay("2027-07-02", "2027-07-04")
    assert response["total_count"] == 2009
    assert len(response["results"]) == 2000
    assert store.results_for_stay("2027-07-02", "2027-07-04", campground_id="Demo Mountain")["total_count"] == 2


def test_new_index_installed_on_existing_database(saved):
    store, _ = saved
    with store.connect() as conn:
        conn.execute("DROP INDEX results_active_stay")
    store.init()
    store.init()
    with store.connect() as conn:
        indexes = {row["name"] for row in conn.execute("PRAGMA index_list(results)")}
    assert "results_active_stay" in indexes
    assert store.result_summary()["total_count"] == 8


def test_map_api_validation_and_read_only_behavior(saved, monkeypatch):
    store, _ = saved
    monkeypatch.setattr(main, "store", store)
    client = TestClient(main.app)
    assert client.get("/api/results/availability").status_code == 200
    response = client.get("/api/results/for-stay", params={"arrival": "2027-07-02", "departure": "2027-07-04", "campground_id": "Demo Coast"})
    assert response.status_code == 200
    assert response.json()["total_count"] == 2
    for params in ({}, {"arrival": "bad", "departure": "2027-07-04"},
                   {"arrival": "2027-02-30", "departure": "2027-07-04"},
                   {"arrival": "2027-07-04", "departure": "2027-07-04"},
                   {"arrival": "2027-07-05", "departure": "2027-07-04"},
                   {"arrival": "2027-07-02", "departure": "2027-07-04", "limit": 2001}):
        assert client.get("/api/results/for-stay", params=params).status_code == 422
    assert store.result_summary()["active_count"] == 8
