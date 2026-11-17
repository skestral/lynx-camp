"""Synthetic contract tests, not recordings or proof of current provider access."""
from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import UTC, date, datetime, timedelta
import json
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from backend.app.db import Store
from backend.app.goingtocamp import GoingToCampClient, STATE_KEY, connection_state, identifier, parse_catalog
from backend.app.provider_errors import ProviderResponseError
from backend.app.provider_ids import campground_url, provider_key
from backend.app.providers import CampgroundClient
from backend.app.recreation import RateLimitError
from backend.app.scanner import Scanner
from backend.app.schemas import ConfigBackup, TargetCreate
from backend.app.sources import import_source, list_source_definitions


ARRIVAL, DEPARTURE = date(2027, 6, 4), date(2027, 6, 6)
CAMPING, ROOFED = "gtc:wa:-1:0", "gtc:wa:-1:1"
CATEGORIES = [
    {"resourceCategoryId": -10, "localizedValues": [{"name": "Campsite"}]},
    {"resourceCategoryId": -11, "localizedValues": [{"name": "Cabin"}]},
    {"resourceCategoryId": -12, "localizedValues": [{"name": "Yurt"}]},
    {"resourceCategoryId": -13, "localizedValues": [{"name": "Day use"}]},
]
LOCATIONS = [
    {"resourceLocationId": -1, "rootMapId": -100, "resourceCategoryIds": [-10, -11, -12],
     "localizedValues": [{"fullName": "Example State Park"}], "latitude": 47.7, "longitude": -122.8},
    {"resourceLocationId": -2, "rootMapId": -200, "resourceCategoryIds": [-13],
     "localizedValues": [{"fullName": "Day use only"}]},
]


class Provider:
    def __init__(self):
        self.requests = []
        self.code = 200
        self.retry_after = "7200"
        self.aggregate = {"-9": [0], "-8": [1]}
        self.daily = {"-9": [0, 0], "-8": [0, 1]}
        self.maps = {-100: [-101], -101: [-102], -102: []}
        self.mutate = lambda payload, request: payload

    def respond(self, request):
        self.requests.append(request)
        assert request.method == "GET"
        assert request.url.host == "washington.goingtocamp.com"
        assert request.headers["user-agent"] == "CampFinder/1.0 (availability monitor)"
        assert "cookie" not in request.headers and "authorization" not in request.headers
        if self.code != 200:
            return httpx.Response(self.code, headers={"Retry-After": self.retry_after}, text="Not available")
        if request.url.path == "/api/resourcelocation":
            payload = deepcopy(LOCATIONS)
        elif request.url.path == "/api/resourcecategory":
            payload = deepcopy(CATEGORIES)
        elif request.url.path == "/api/availability/map":
            params = request.url.params
            assert params["filterData"] == "[]"
            assert params["startDate"] == ARRIVAL.isoformat() and params["endDate"] == DEPARTURE.isoformat()
            assert params["resourceLocationId"] == "-1" and params["isReserving"] == "true"
            if params["bookingCategoryId"] == "0":
                assert params["equipmentCategoryId"] == "-32768" and params["numEquipment"] == "1"
            else:
                assert params["bookingCategoryId"] == "1"
                assert "equipmentCategoryId" not in params and "numEquipment" not in params
            map_id = int(params["mapId"])
            statuses = self.daily if params["getDailyAvailability"] == "true" else self.aggregate
            payload = {"mapId": map_id, "resourceLocationId": -1,
                       "resourceAvailabilities": {key: [{"availability": v} for v in values] for key, values in statuses.items()} if map_id == -102 else {},
                       "mapLinkAvailabilities": {str(child): [] for child in self.maps[map_id]}}
        else:
            raise AssertionError(f"Unexpected request: {request.url.path}")
        return httpx.Response(200, json=self.mutate(payload, request))

    def client(self, store=None):
        return GoingToCampClient(store, httpx.MockTransport(self.respond), request_spacing_seconds=0)


@pytest.fixture
def store(tmp_path):
    store = Store(tmp_path / "washington.db")
    store.init()
    return store


@pytest.fixture(autouse=True)
def calendar(monkeypatch):
    class ScanDate(date):
        @classmethod
        def today(cls):
            return cls(2026, 11, 17)
    monkeypatch.setattr("backend.app.scanner.date", ScanDate)


def test_catalog_categories_root_identity_and_no_day_use():
    targets = parse_catalog(LOCATIONS, CATEGORIES)
    assert set(targets) == {CAMPING, ROOFED}
    assert targets[ROOFED]["root_map_id"] == -100
    assert targets[ROOFED]["name"] == "Example State Park - Roofed"
    assert targets[CAMPING]["latitude"] == 47.7


@pytest.mark.parametrize("value", [None, True, 1.5, "bad", "01", "-0", "1.0", 2**31, [], {}])
def test_invalid_id_fails_with_provider_error(value):
    with pytest.raises(ProviderResponseError):
        identifier(value)


@pytest.mark.parametrize("change", ["root", "duplicate", "missing_roofed", "category_shape", "empty"])
def test_unrecognized_or_incomplete_catalog_is_not_imported(change):
    locations, categories = deepcopy(LOCATIONS), deepcopy(CATEGORIES)
    if change == "root":
        locations[0].pop("rootMapId")
    elif change == "duplicate":
        locations.append(locations[0])
    elif change == "missing_roofed":
        categories = categories[:1]
    elif change == "category_shape":
        locations[0]["resourceCategoryIds"] = None
    else:
        locations = []
    with pytest.raises(ProviderResponseError):
        parse_catalog(locations, categories)


@pytest.mark.parametrize("target", [CAMPING, ROOFED])
def test_nested_maps_full_stay_cache_and_booking_link(target):
    provider = Provider()
    client = provider.client()
    stages = []
    async def gate(stage):
        stages.append(stage)
    async def scenario():
        for _ in range(2):
            sites = await client.trip_availability(target, ARRIVAL, DEPARTURE, gate)
            assert len(sites) == 1
            site = sites[0]
            assert site.campsite_id == f"{target}:-102:-9" and site.max_num_people is None
            assert site.campsite_type == ("Camping" if target == CAMPING else "Roofed")
            query = parse_qs(urlparse(site.booking_url).query)
            assert query["startDate"] == ["2027-06-04"] and query["endDate"] == ["2027-06-06"]
            assert query["mapId"] == ["-102"] and query["bookingCategoryId"] == [target[-1]]
    asyncio.run(scenario())
    assert len(provider.requests) == 14  # catalog once; three maps, two requests each, twice
    assert len(stages) == len(provider.requests)


@pytest.mark.parametrize("aggregate,daily", [([0], [0, 1]), ([1], [0, 0]), ([1], [1, 1])])
def test_partial_or_restricted_full_stay_is_not_a_hit(aggregate, daily):
    provider = Provider()
    provider.aggregate, provider.daily = {"-9": aggregate}, {"-9": daily}
    assert asyncio.run(provider.client().trip_availability(CAMPING, ARRIVAL, DEPARTURE)) == []


@pytest.mark.parametrize("change", ["short", "type", "negative", "empty", "different_ids", "wrong_date", "wrong_map", "missing_links", "daily_order"])
def test_malformed_or_partial_response_never_returns_empty_success(change):
    provider = Provider()
    if change == "short":
        provider.daily["-9"] = [0]
    elif change == "type":
        provider.daily["-9"] = [True, 0]
    elif change == "negative":
        provider.daily["-9"] = [-1, 0]
    elif change == "empty":
        provider.aggregate, provider.daily = {}, {}
    elif change == "different_ids":
        provider.daily["-7"] = [0, 0]
    else:
        def mutate(payload, request):
            if request.url.path.endswith("/map"):
                if change == "wrong_date":
                    payload["startDate"] = "2027-06-05"
                elif change == "wrong_map":
                    payload["mapId"] = -999
                elif change == "missing_links":
                    payload.pop("mapLinkAvailabilities")
                elif payload["resourceAvailabilities"] and request.url.params["getDailyAvailability"] == "true":
                    payload["resourceAvailabilities"]["-9"][0]["date"] = "2027-06-05"
            return payload
        provider.mutate = mutate
    with pytest.raises(ProviderResponseError):
        asyncio.run(provider.client().trip_availability(CAMPING, ARRIVAL, DEPARTURE))


def test_cycles_and_map_limit_fail_closed(monkeypatch):
    provider = Provider()
    provider.maps[-102] = [-100]
    with pytest.raises(ProviderResponseError, match="cyclic"):
        asyncio.run(provider.client().trip_availability(CAMPING, ARRIVAL, DEPARTURE))
    provider.maps[-102] = []
    monkeypatch.setattr("backend.app.goingtocamp.MAX_MAPS", 2)
    with pytest.raises(ProviderResponseError, match="safety limit"):
        asyncio.run(provider.client().trip_availability(CAMPING, ARRIVAL, DEPARTURE))


@pytest.mark.parametrize("code", [302, 401, 403])
def test_access_denial_persists_and_stops_checks_scans_and_import_after_restart(store, code):
    provider = Provider()
    provider.code = code
    with pytest.raises(ProviderResponseError, match="access stopped"):
        asyncio.run(provider.client(store).discover())
    restarted = provider.client(store)
    async def scenario():
        for action in (restarted.discover, lambda: restarted.trip_availability(CAMPING, ARRIVAL, DEPARTURE)):
            with pytest.raises(ProviderResponseError, match="access is stopped"):
                await action()
        with pytest.raises(ProviderResponseError, match="cooldown"):
            await restarted.reset_access_stop()
    asyncio.run(scenario())
    assert len(provider.requests) == 1
    assert connection_state(store)["state"] == "access_denied"
    assert STATE_KEY not in json.dumps(store.export_config(include_secrets=True))


def test_html_challenge_is_stopped_and_never_logged(store):
    calls = []
    def respond(request):
        calls.append(request)
        return httpx.Response(200, text="<html>private challenge token</html>")
    client = GoingToCampClient(store, httpx.MockTransport(respond), 0)
    with pytest.raises(ProviderResponseError, match="access stopped"):
        asyncio.run(client.discover())
    assert len(calls) == 1 and "private" not in json.dumps(connection_state(store))


def test_retry_after_survives_restart_and_manual_reset_cannot_skip_it(store):
    provider = Provider()
    provider.code = 429
    with pytest.raises(RateLimitError) as error:
        asyncio.run(provider.client(store).discover())
    assert error.value.retry_after_seconds == 7200
    with pytest.raises(RateLimitError):
        asyncio.run(provider.client(store).discover())
    with pytest.raises(ProviderResponseError, match="cooldown"):
        asyncio.run(provider.client(store).reset_access_stop())
    assert len(provider.requests) == 1


def test_access_stop_requires_explicit_reset_even_after_cooldown(store):
    store.set_app_settings({STATE_KEY: json.dumps({"state": "access_denied", "retry_at": (datetime.now(UTC) - timedelta(hours=1)).isoformat()})})
    provider = Provider()
    client = provider.client(store)
    async def scenario():
        with pytest.raises(ProviderResponseError):
            await client.discover()
        await client.reset_access_stop()
        assert provider.requests == []
        assert len(await client.discover()) == 2
    asyncio.run(scenario())


@pytest.mark.parametrize("saved", ["not json", '{"state":"access_denied","message":{}}'])
def test_corrupt_saved_state_fails_closed(store, saved):
    store.set_app_settings({STATE_KEY: saved})
    provider = Provider()
    with pytest.raises(ProviderResponseError):
        asyncio.run(provider.client(store).discover())
    assert provider.requests == []


@pytest.mark.parametrize("value", ["gtc:wa:1:2", "gtc:wa:01:0", "gtc:wa:-0:0", "gtc:or:1:0", "gtc:wa:2147483648:0"])
def test_noncanonical_or_foreign_target_identity_is_rejected(value):
    with pytest.raises(ValueError):
        TargetCreate(name="Invalid", campground_id=value)


def test_foreign_campsite_id_cannot_change_booking_destination():
    assert provider_key(ROOFED) == "goingtocamp"
    with pytest.raises(ValueError):
        campground_url(CAMPING, campsite_id=f"{ROOFED}:-102:-9")


def watch_data():
    return {"name": "WA weekends", "mode": "specific", "window_start": ARRIVAL.isoformat(),
            "window_end": DEPARTURE.isoformat(), "specific_ranges": [{"arrival_date": ARRIVAL.isoformat(),
            "departure_date": DEPARTURE.isoformat()}]}


class Recorder:
    def __init__(self):
        self.results = []

    async def notify_results(self, results, store, max_items):
        self.results.extend(results)


def test_regional_import_scan_notification_dedupe_backup_and_denial_preserve_matches(store, tmp_path):
    federal = store.create_target({"name": "Federal", "campground_id": "123", "state_code": "WA"})
    group = store.create_watch_group([federal["id"]], watch_data(), {"kind": "state", "state_code": "WA"})[0]["group_id"]
    provider, client, notifier = Provider(), CampgroundClient(store), Recorder()
    client.washington = provider.client(store)
    scanner = Scanner(store, client, notifier, 60, api_request_delay_seconds=0, availability_cache_minutes=0)
    async def scenario():
        result = await import_source(store, client, "washington-state-parks", 60)
        assert result["imported_count"] == 2
        watches = [w for w in store.list_watches() if w["campground_id"].startswith("gtc:")]
        assert len(watches) == 2 and all(w["group_id"] == group for w in watches)
        for watch in watches:
            assert (await scanner.scan_watch(watch["id"]))["available_count"] == 1
            await scanner.scan_watch(watch["id"])
        assert len(notifier.results) == 2
        provider.code = 403
        for watch in watches:
            with pytest.raises(ProviderResponseError):
                await scanner.scan_watch(watch["id"])
        assert len(notifier.results) == 2
        assert len(store.list_results()) == 2 and all(r["status"] == "available" and r["active"] for r in store.list_results())
    asyncio.run(scenario())
    links = [r["booking_url"] for r in store.list_results()]
    store.init()
    assert links == [r["booking_url"] for r in store.list_results()]
    assert all(parse_qs(urlparse(link).query)["mapId"] == ["-102"] for link in links)
    restored = Store(tmp_path / "restore.db")
    restored.init()
    restored.import_config(ConfigBackup.model_validate(store.export_config()).model_dump(mode="json"))
    assert len(restored.list_watches()) == 3
    sources = {s["id"]: s for s in list_source_definitions(store)}
    assert sources["washington-state-parks"]["imported_count"] == 2
    assert sources["washington-state-parks"]["connection"]["state"] == "access_denied"
    assert sources["washington-recreation-gov-region"]["imported_count"] == 1
    assert any(e["event_type"] == "provider_request" for e in store.list_scan_events())


def test_cancellation_stops_at_next_request_without_matches_or_notifications(store):
    target = store.create_target({"name": "Example Camping", "campground_id": CAMPING})
    watch = store.create_watch({**watch_data(), "target_id": target["id"]})
    provider, client, notifier = Provider(), CampgroundClient(store), Recorder()
    scanner = Scanner(store, client, notifier, 60, api_request_delay_seconds=0)
    def respond(request):
        if request.url.path.endswith("/map"):
            scanner.cancel_current_scan()
        return provider.respond(request)
    client.washington = GoingToCampClient(store, httpx.MockTransport(respond), 0)
    assert asyncio.run(scanner.scan_watch(watch["id"]))["status"] == "cancelled"
    assert len(provider.requests) == 3 and store.list_results() == [] and notifier.results == []


def test_api_exposes_persisted_failure_and_reset_does_not_call_provider(store, monkeypatch):
    from backend.app import main
    provider, client = Provider(), CampgroundClient(store)
    provider.code = 403
    client.washington = provider.client(store)
    monkeypatch.setattr(main, "store", store)
    monkeypatch.setattr(main, "client", client)
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://test") as api:
            assert (await api.post("/api/sources/washington-state-parks/import")).status_code == 502
            assert store.list_targets() == []
            source = next(s for s in (await api.get("/api/sources")).json() if s["id"] == "washington-state-parks")
            assert source["status"] == "experimental" and source["connection"]["state"] == "access_denied"
            assert (await api.post("/api/sources/washington-state-parks/reset-access")).status_code == 502
            assert (await api.post("/api/sources/king-county-parks/reset-access")).status_code == 400
            client.washington._state["retry_at"] = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
            assert (await api.post("/api/sources/washington-state-parks/reset-access")).json() == {"reset": True}
    asyncio.run(scenario())
    assert len(provider.requests) == 1


def test_catalog_publication_cannot_overwrite_concurrent_access_stop(monkeypatch):
    provider = Provider()
    client = provider.client()
    def parse_then_stop(*args):
        catalog = parse_catalog(*args)
        client._state = {"state": "access_denied"}
        return catalog
    monkeypatch.setattr("backend.app.goingtocamp.parse_catalog", parse_then_stop)
    with pytest.raises(ProviderResponseError, match="access is stopped"):
        asyncio.run(client.discover())
    assert client._catalog is None and client._state["state"] == "access_denied"


def test_every_request_is_paced_including_catalog(monkeypatch):
    waits = []
    async def sleep(delay):
        waits.append(delay)
    monkeypatch.setattr("backend.app.goingtocamp.asyncio.sleep", sleep)
    monkeypatch.setattr("backend.app.goingtocamp.time.monotonic", lambda: 100)
    provider = Provider()
    client = GoingToCampClient(transport=httpx.MockTransport(provider.respond))
    asyncio.run(client.discover())
    assert waits == [0, 5]


def test_provider_cooldown_does_not_block_federal_and_survives_scanner_restart(store):
    target = store.create_target({"name": "Example Camping", "campground_id": CAMPING})
    watch = store.create_watch({**watch_data(), "target_id": target["id"]})
    provider, client = Provider(), CampgroundClient(store)
    provider.code = 429
    client.washington = provider.client(store)
    scanner = Scanner(store, client, Recorder(), 60, api_request_delay_seconds=0)
    result = asyncio.run(scanner.scan_watch(watch["id"]))
    assert result["status"] == "rate_limited"
    restarted = Scanner(store, client, Recorder(), 60)
    restarted.restore_runtime_state()
    assert restarted._rate_limit_remaining_minutes("goingtocamp") >= 119
    assert restarted._rate_limit_remaining_minutes("recreation") is None
    assert len(provider.requests) == 1


@pytest.mark.parametrize("conflict", [False, True])
def test_repeated_resource_is_deduplicated_or_rejected_when_inconsistent(conflict):
    provider = Provider()
    def mutate(payload, request):
        if request.url.path.endswith("/map") and request.url.params["mapId"] == "-101":
            count = 2 if request.url.params["getDailyAvailability"] == "true" else 1
            payload["resourceAvailabilities"] = {"-9": [{"availability": 1 if conflict else 0}] * count}
        return payload
    provider.mutate = mutate
    if conflict:
        with pytest.raises(ProviderResponseError, match="conflicting"):
            asyncio.run(provider.client().trip_availability(CAMPING, ARRIVAL, DEPARTURE))
    else:
        assert len(asyncio.run(provider.client().trip_availability(CAMPING, ARRIVAL, DEPARTURE))) == 1


@pytest.mark.parametrize("mode", ["timeout", "invalid_json", "server_error"])
def test_transport_or_response_failure_is_unknown_not_sold_out(mode):
    calls = []
    def respond(request):
        calls.append(request)
        if mode == "timeout":
            raise httpx.ReadTimeout("Timed out", request=request)
        if mode == "invalid_json":
            return httpx.Response(200, content="{", headers={"Content-Type": "application/json"})
        return httpx.Response(500)
    client = GoingToCampClient(transport=httpx.MockTransport(respond), request_spacing_seconds=0)
    with pytest.raises(ProviderResponseError):
        asyncio.run(client.discover())
    assert len(calls) == 1


@pytest.mark.parametrize("filters", [{"site_type": "cabin"}, {"min_people": 2}, {"loop": "A"}])
def test_unverifiable_watch_filters_report_error_without_requesting_provider(store, filters):
    target = store.create_target({"name": "Example Roofed", "campground_id": ROOFED})
    watch = store.create_watch({**watch_data(), "target_id": target["id"], "site_filters": filters})
    provider, client = Provider(), CampgroundClient(store)
    client.washington = provider.client(store)
    scanner = Scanner(store, client, Recorder(), 60, api_request_delay_seconds=0)
    with pytest.raises(ProviderResponseError, match="cannot verify"):
        asyncio.run(scanner.scan_watch(watch["id"]))
    assert provider.requests == []


def test_cycle_through_shared_child_is_not_hidden_by_visited_set():
    provider = Provider()
    provider.maps = {-100: [-101, -103], -101: [-102], -102: [-103], -103: [-102]}
    with pytest.raises(ProviderResponseError, match="cyclic"):
        asyncio.run(provider.client().trip_availability(CAMPING, ARRIVAL, DEPARTURE))
