import json
import sqlite3
import time

import pytest
from fastapi.testclient import TestClient

from backend.app import main
from backend.app.db import Store
from backend.app.result_overview import dismiss_scope, read_overview
from backend.app.schemas import ResultFilters, ResultOverviewQuery
from backend.tests.test_result_groups import seed_results


@pytest.fixture
def saved(tmp_path):
    store = Store(tmp_path / "overview.db")
    return store, seed_results(store)


def copies(store, template_id, count):
    with store.connect() as conn:
        template = dict(conn.execute("SELECT * FROM results WHERE id = ?", (template_id,)).fetchone())
        template.pop("id")
        conn.executemany(f"INSERT INTO results ({','.join(template)}) VALUES ({','.join('?' for _ in template)})", [
            tuple({**template, "campsite_id": f"many-{i}", "site": f"Site {i:05}", "dedupe_key": f"many-{i}",
                   "discovered_at": "2027-01-01T00:00:00+00:00"}.values()) for i in range(count)])


def overview(store, **options):
    return read_overview(store, ResultOverviewQuery(**options))


def test_complete_rollup_is_small_with_over_fifteen_thousand_matches(saved):
    store, rows = saved
    copies(store, rows[0]["id"], 15000)
    started = time.monotonic()
    result = overview(store)
    assert result["summary"]["match_count"] == 15008
    assert result["summary"]["site_count"] == 15004
    assert result["summary"]["campground_count"] == 2
    assert result["summary"]["stay_count"] == 2
    assert len(result["groups"]) == 2 and not result["results"]
    assert len(json.dumps(result)) < 2500
    assert time.monotonic() - started < 5
    assert len(store.list_results()) == 2000
    assert not any(row["park_name"] == "Demo Rainier" for row in store.list_results())
    # Search/filter the database, including rows omitted from the legacy working set.
    rare = overview(store, search="Mountain", group_by="campground")
    assert rare["summary"]["match_count"] == 4
    last = overview(store, group_by="items", offset=15000)
    assert len(last["results"]) == 8 and not last["has_more"]
    assert last["total_groups"] == 15008


def test_levels_totals_statuses_and_scopes(saved):
    store, rows = saved
    store.update_result_status(rows[0]["id"], "opened")
    store.update_result_status(rows[1]["id"], "booked")
    store.update_result_status(rows[2]["id"], "dismissed")
    with store.connect() as conn:
        conn.execute("UPDATE results SET active = 0 WHERE id = ?", (rows[3]["id"],))
    assert overview(store)["summary"]["match_count"] == 5
    assert overview(store, view="all")["summary"]["match_count"] == 8
    assert overview(store, view="booked")["summary"]["active_count"] == 0
    assert overview(store, view="dismissed")["summary"]["match_count"] == 1
    assert overview(store, park_name="Demo Rainier", group_by="campground")["groups"][0]["campground_name"] == "Demo Mountain"
    stays = overview(store, campground_id="Demo Mountain", group_by="stay")
    assert len(stays["groups"]) == 2
    leaf = overview(store, campground_id="Demo Mountain", exact_arrival="2027-07-02", exact_departure="2027-07-04", group_by="items")
    assert len(leaf["results"]) == 2 and all(row["campground_id"] == "Demo Mountain" for row in leaf["results"])
    assert overview(store, group_by="stay")["groups"][0]["campground_count"] == 2


def test_covering_dates_never_combine_sites_or_nights(saved):
    store, _ = saved
    assert overview(store, arrival="2027-07-03", departure="2027-07-04")["summary"]["match_count"] == 4
    assert overview(store, arrival="2027-07-04", departure="2027-07-05")["summary"]["match_count"] == 0
    assert overview(store, arrival="2027-07-02", departure="2027-07-11")["summary"]["match_count"] == 0
    with store.connect() as conn:
        conn.execute("UPDATE results SET departure_date = '2027-07-03' WHERE site = 'A'")
        conn.execute("UPDATE results SET arrival_date = '2027-07-03' WHERE site = 'B'")
    assert overview(store, arrival="2027-07-02", departure="2027-07-04")["summary"]["match_count"] == 0


def test_stable_pages_and_snapshot_boundary_exclude_later_inserts(saved):
    store, rows = saved
    copies(store, rows[0]["id"], 53)
    first = overview(store, group_by="items", limit=25)
    # Insert another row after page one was read.
    with store.connect() as conn:
        template = dict(conn.execute("SELECT * FROM results WHERE id = ?", (rows[0]["id"],)).fetchone())
        template.pop("id")
        template["dedupe_key"] = "later"
        conn.execute(f"INSERT INTO results ({','.join(template)}) VALUES ({','.join('?' for _ in template)})", tuple(template.values()))
    all_ids = [row["id"] for row in first["results"]]
    for offset in (25, 50):
        page = overview(store, group_by="items", limit=25, offset=offset, max_result_id=first["snapshot_max_id"])
        all_ids.extend(row["id"] for row in page["results"])
        assert page["total_groups"] == 61
    assert len(all_ids) == len(set(all_ids)) == 61
    assert overview(store)["summary"]["match_count"] == 62
    # Group pagination has the same complete counts as unpaged aggregation.
    assert overview(store, group_by="park", limit=1, offset=1)["groups"][0]["park_name"] == "Demo Rainier"


def test_search_is_literal_and_group_names_do_not_collide(saved):
    store, rows = saved
    with store.connect() as conn:
        conn.execute("UPDATE targets SET name = 'Same name' ")
        conn.execute("UPDATE targets SET park_name = '' WHERE id = ?", (rows[0]["target_id"],))
        conn.execute("UPDATE results SET site = '100%_exact' WHERE id = ?", (rows[0]["id"],))
    assert len(overview(store, group_by="campground")["groups"]) == 2
    assert overview(store, park_name="Unassigned park")["summary"]["match_count"] == 4
    assert overview(store, search="%_")["summary"]["match_count"] == 1
    assert overview(store, search="' OR 1=1 --")["summary"]["match_count"] == 0


def test_overlapping_watches_count_matches_separately_from_distinct_sites(saved):
    store, rows = saved
    watch = store.get_watch(rows[0]["watch_id"])
    duplicate = store.create_watch({**watch, "name": "Overlapping"})
    store.upsert_result({**rows[0], "watch_id": duplicate["id"]})
    result = overview(store)
    assert result["summary"]["match_count"] == 9
    assert result["summary"]["site_count"] == 4
    assert result["summary"]["stay_count"] == 2


def test_unicode_search_and_filtered_dismissal_use_the_same_scope(saved):
    store, rows = saved
    with store.connect() as conn:
        conn.execute("UPDATE results SET site = ? WHERE id = ?", ("\u00c9TOILE", rows[0]["id"]))
    filters = ResultFilters(search="\u00e9toile", park_name="Demo Olympic", max_result_id=8)
    assert overview(store, **filters.model_dump())["summary"]["match_count"] == 1
    assert dismiss_scope(store, filters) == 1
    assert overview(store)["summary"]["match_count"] == 7


def test_dismiss_scope_covers_unloaded_rows_but_keeps_new_and_unrelated_matches(saved):
    store, rows = saved
    copies(store, rows[0]["id"], 2100)
    store.update_result_status(rows[1]["id"], "booked")
    snapshot = overview(store, park_name="Demo Olympic")
    filters = ResultFilters(park_name="Demo Olympic", exact_arrival="2027-07-02", exact_departure="2027-07-04",
                            max_result_id=snapshot["snapshot_max_id"])
    with store.connect() as conn:
        conn.execute("UPDATE results SET notification_pending = 1, auto_missing = 1 WHERE active = 1")
    assert dismiss_scope(store, filters) == 2101
    assert dismiss_scope(store, filters) == 0
    assert store.get_watch(rows[0]["watch_id"]) is not None
    all_rows = overview(store, view="all", group_by="items", search="100%")
    assert all_rows["summary"]["match_count"] == 0
    assert overview(store, view="booked")["summary"]["match_count"] == 1
    assert overview(store, park_name="Demo Rainier")["summary"]["match_count"] == 4
    with store.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM results WHERE status='dismissed' AND (notification_pending != 0 OR auto_missing != 0)").fetchone()[0] == 0
    assert overview(store, exact_arrival="2027-07-09", exact_departure="2027-07-11")["summary"]["match_count"] == 4


def test_dismissal_is_atomic_and_bounded_to_read_snapshot(saved):
    store, rows = saved
    boundary = rows[1]["id"]
    filters = ResultFilters(park_name="Demo Olympic", max_result_id=boundary)
    with store.connect() as conn:
        conn.execute(f"""CREATE TRIGGER reject_overview BEFORE UPDATE ON results
            WHEN NEW.id = {boundary} AND NEW.status = 'dismissed'
            BEGIN SELECT RAISE(ABORT, 'injected failure'); END""")
    with pytest.raises(sqlite3.IntegrityError):
        dismiss_scope(store, filters)
    assert overview(store)["summary"]["match_count"] == 8
    with store.connect() as conn:
        conn.execute("DROP TRIGGER reject_overview")
    assert dismiss_scope(store, filters) == 2
    assert overview(store)["summary"]["match_count"] == 6


def test_api_validation_and_existing_database_index(saved, monkeypatch):
    store, _ = saved
    monkeypatch.setattr(main, "store", store)
    client = TestClient(main.app)
    response = client.get("/api/results/overview")
    assert response.status_code == 200 and response.json()["summary"]["match_count"] == 8
    for params in ({"limit": 101}, {"offset": -1}, {"group_by": "sql"}, {"sort": "other"},
                   {"view": "unknown"}, {"arrival": "2027-02-30", "departure": "2027-03-01"},
                   {"arrival": "2027-07-02"}, {"arrival": "2027-07-04", "departure": "2027-07-02"},
                   {"exact_departure": "2027-07-04"}, {"max_result_id": -1}, {"search": "x" * 301}, {"unknown": "field"}):
        assert client.get("/api/results/overview", params=params).status_code == 422
    for filters in ({}, {"park_name": "Demo Olympic"}, {"max_result_id": 8}, {"park_name": "Demo Olympic", "max_result_id": -1}):
        assert client.post("/api/results/dismiss-scope", json={"filters": filters}).status_code == 422
    dismissed = client.post("/api/results/dismiss-scope", json={"filters": {"park_name": "Demo Olympic", "max_result_id": 8}})
    assert dismissed.json() == {"dismissed_count": 4}
    with store.connect() as conn:
        conn.execute("DROP INDEX results_campground_stay")
    store.init(); store.init()
    with store.connect() as conn:
        assert "results_campground_stay" in {row["name"] for row in conn.execute("PRAGMA index_list(results)")}
    assert store.result_summary()["total_count"] == 8


def test_combined_location_filters_and_dismissal_keep_provider_identity(saved, monkeypatch):
    store, _ = saved
    monkeypatch.setattr(main, "store", store)
    client = TestClient(main.app)
    ids = ["Demo Coast", "Demo Mountain"]
    params = [("campground_ids", item) for item in ids]
    response = client.get("/api/results/overview", params=[*params, ("limit", "1")])
    assert response.status_code == 200
    assert response.json()["summary"]["match_count"] == 8
    assert len(response.json()["groups"]) == 1
    narrowed = client.get("/api/results/overview", params=[*params, ("campground_id", "Demo Coast")])
    assert narrowed.json()["summary"]["match_count"] == 4
    assert overview(store, campground_ids=["' OR 1=1 --"])["summary"]["match_count"] == 0
    dismissed = client.post("/api/results/dismiss-scope", json={"filters": {
        "campground_ids": ids, "exact_arrival": "2027-07-02", "exact_departure": "2027-07-04", "max_result_id": 8}})
    assert dismissed.json() == {"dismissed_count": 4}
    assert overview(store)["summary"]["match_count"] == 4
    assert overview(store, exact_arrival="2027-07-09", exact_departure="2027-07-11")["summary"]["match_count"] == 4


def test_combined_location_ids_are_bounded_and_cannot_dismiss_everything(saved, monkeypatch):
    store, _ = saved
    monkeypatch.setattr(main, "store", store)
    client = TestClient(main.app)
    for ids in ([""], ["x" * 201], [str(index) for index in range(21)]):
        assert client.get("/api/results/overview", params=[("campground_ids", item) for item in ids]).status_code == 422
    assert client.post("/api/results/dismiss-scope", json={"filters": {"campground_ids": [], "max_result_id": 8}}).status_code == 422
    response = client.post("/api/results/dismiss-scope", json={"filters": {"campground_ids": ["Demo Coast"], "max_result_id": 8}})
    assert response.json() == {"dismissed_count": 4}
    assert overview(store, campground_id="Demo Mountain")["summary"]["match_count"] == 4
