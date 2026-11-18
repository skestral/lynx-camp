from copy import deepcopy

import pytest

from backend.app.coordinates import CANADIAN_LOCATIONS, coordinate_pair, target_coordinates
from backend.app.db import Store
from backend.app.goingtocamp import parse_catalog
from scripts.refresh_canadian_coordinates import resolve


BC = next(key for key in CANADIAN_LOCATIONS if key.startswith("gtc:bc:"))
PC = "gtc:pc:-2147483644:0"  # Tunnel Mountain Trailer Court


@pytest.mark.parametrize("point", [(None, None), (None, -123), ("", ""), (" ", -123),
    (0, 0), ("0", "0"), (True, -123), (50, False), (float("nan"), -123),
    (50, float("inf")), (91, -123), (50, -181), ([], {}), ("bad", -123)])
def test_invalid_coordinates_remain_unknown(point):
    assert coordinate_pair(*point) is None


@pytest.mark.parametrize("point,expected", [(("50.1", "-123.2"), (50.1, -123.2)),
    ((0, 40), (0, 40)), ((50, 0), (50, 0)), ((-90, 180), (-90, 180))])
def test_valid_coordinates_including_equator_and_meridian(point, expected):
    assert coordinate_pair(*point) == expected


@pytest.mark.parametrize("key", [BC, PC])
def test_catalog_uses_reference_but_preserves_provider_gps(key):
    _, tenant, location, category = key.split(":")
    locations = [{"resourceLocationId": int(location), "rootMapId": -100, "resourceCategoryIds": [-10],
                  "localizedValues": [{"fullName": "Example Park"}], "gpsCoordinates": "0,0"}]
    categories = [{"resourceCategoryId": -10, "localizedValues": [{"name": "Campsite"}]}]
    target = parse_catalog(locations, categories, tenant)[key]
    assert target_coordinates(target) == target_coordinates({"campground_id": key})
    assert target["location_source_url"] == CANADIAN_LOCATIONS[key]["source_url"]
    locations[0]["gpsCoordinates"] = "51.25,-120.5"
    target = parse_catalog(locations, categories, tenant)[key]
    assert (target["latitude"], target["longitude"]) == (51.25, -120.5)
    assert "location_precision" not in target
    locations[0]["resourceLocationId"] = -99
    locations[0]["gpsCoordinates"] = "0,0"
    target = next(iter(parse_catalog(locations, categories, tenant).values()))
    assert "latitude" not in target and "longitude" not in target


def test_existing_database_backfill_is_idempotent_and_preserves_user_data(tmp_path):
    store = Store(tmp_path / "existing.db")
    store.init()
    targets = [store.create_target({"campground_id": key, "name": key, "active": False,
               "poll_interval_minutes": 120}) for key in (BC, PC, "gtc:pc:-99:0", "gtc:pc:-98:0")]
    store.create_watch({"target_id": targets[0]["id"], "name": "Canadian weekend", "mode": "weekend",
                        "window_start": "2027-06-01", "window_end": "2027-08-31"})
    store.set_app_settings({"crawl_paused": "true"})
    with store.connect() as conn:
        conn.execute("UPDATE targets SET latitude = NULL, longitude = NULL WHERE campground_id = ?", (BC,))
        conn.execute("UPDATE targets SET latitude = 0, longitude = 0 WHERE campground_id IN (?, ?)", (PC, "gtc:pc:-99:0"))
        conn.execute("UPDATE targets SET latitude = 51.25, longitude = -120.5 WHERE campground_id = ?", ("gtc:pc:-98:0",))
        before = {row["id"]: dict(row) for row in conn.execute("SELECT * FROM targets")}
    watches = store.list_watches()
    store.init()
    store.init()
    with store.connect() as conn:
        after = {row["id"]: dict(row) for row in conn.execute("SELECT * FROM targets")}
    assert before.keys() == after.keys()
    for key, row in after.items():
        assert {k: v for k, v in row.items() if k not in {"latitude", "longitude"}} == {
            k: v for k, v in before[key].items() if k not in {"latitude", "longitude"}}
    for target in targets[:2]:
        row = after[target["id"]]
        assert (row["latitude"], row["longitude"]) == target_coordinates({"campground_id": target["campground_id"]})
    assert (after[targets[2]["id"]]["latitude"], after[targets[2]["id"]]["longitude"]) == (None, None)
    assert after[targets[3]["id"]] == before[targets[3]["id"]]
    assert store.list_watches() == watches
    assert store.get_app_settings(["crawl_paused"])["crawl_paused"] == "true"


def test_custom_reference_coordinates_and_catalog_repair(tmp_path):
    store = Store(tmp_path / "custom.db")
    store.init()
    target = store.create_target({"campground_id": BC, "name": "Custom", "latitude": 52, "longitude": -125})
    store.init()
    assert store.get_target(target["id"])["latitude"] == 52
    assert "location_precision" not in store.get_target(target["id"])
    store.fill_missing_target_coordinates([{"campground_id": BC, "latitude": 0, "longitude": 0}])
    assert store.get_target(target["id"])["latitude"] == 52
    unknown = store.create_target({"campground_id": "gtc:pc:-99:0", "name": "Unknown", "latitude": 0, "longitude": 0})
    assert unknown["latitude"] is None
    store.fill_missing_target_coordinates([{"campground_id": "gtc:pc:-99:0", "latitude": 0, "longitude": 0}])
    assert store.get_target(unknown["id"])["latitude"] is None


def park(name, west, south, east, north):
    return {"attributes": {"Park_Name_": name}, "geometry": {"rings": [
        [[west, south], [east, south], [east, north], [west, north], [west, south]]]}}


def test_reference_matching_uses_park_identity_not_just_campground_name():
    catalogs = {"pc": [{"campground_id": "west", "name": "Pacific Rim - Green Point - Camping"},
                       {"campground_id": "east", "name": "Gros Morne - Green Point - Camping"}]}
    pc = [{"attributes": {"Name_e": "Green Point", "Accommodation_Type": 1}, "geometry": {"y": 49.6, "x": -57.9}}]
    parks = [park("Pacific Rim NPR", -126, 48, -124, 50), park("Gros Morne NP", -60, 48, -56, 51)]
    matched, unmatched = resolve(catalogs, [], pc, parks)
    assert set(matched) == {"east"}
    assert unmatched[0]["campground_id"] == "west"
    # Refreshing a catalog already enriched by this app must not erase its reference.
    enriched = deepcopy(catalogs)
    enriched["pc"][1].update(matched["east"], location_precision="campground")
    assert resolve(enriched, [], pc, parks)[0] == matched
    # Missing park identity or dispersed sites never become guessed coordinates.
    assert resolve(catalogs, [], pc, [])[0] == {}
    pc.append({"attributes": pc[0]["attributes"], "geometry": {"y": 50.5, "x": -57.9}})
    assert resolve(catalogs, [], pc, parks)[0] == {}


def test_shipped_reference_is_canadian_and_excludes_wrong_coast_collision():
    assert PC in CANADIAN_LOCATIONS
    assert "gtc:pc:-2147483565:0" not in CANADIAN_LOCATIONS  # Pacific Rim, not Gros Morne
    for key, entry in CANADIAN_LOCATIONS.items():
        assert key.startswith(("gtc:bc:", "gtc:pc:"))
        assert coordinate_pair(entry["latitude"], entry["longitude"])
        assert 41 <= entry["latitude"] <= 84 and -142 <= entry["longitude"] <= -50
        assert entry["precision"] in {"park", "campground"}
        assert entry["source_url"].startswith("https://")
