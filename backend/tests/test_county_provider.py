from __future__ import annotations

import asyncio
from datetime import date
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from backend.app.camava import ProviderResponseError, SnohomishClient, parse_availability, parse_catalog
from backend.app.db import Store
from backend.app.provider_ids import campground_url, provider_key
from backend.app.recreation import Campsite, RateLimitError
from backend.app.scanner import Scanner, release_hints
from backend.app.schemas import ConfigBackup, TargetCreate
from backend.app.sources import discover_source, import_source, list_source_definitions


ARRIVAL = date(2027, 6, 4)
DEPARTURE = date(2027, 6, 6)
COUNTY_ID = "camava:snoco:112"


@pytest.fixture(autouse=True)
def scan_calendar(monkeypatch):
    class ScanDate(date):
        @classmethod
        def today(cls):
            return cls(2027, 6, 1)
    monkeypatch.setattr("backend.app.scanner.date", ScanDate)


def search_page(cards="", arrival=ARRIVAL, departure=DEPARTURE, park="112"):
    return f'''<select id="parent_idno"><option selected value="{park}">Flowing Lake</option></select>
    <input id="camping_arrive_date" value="{arrival:%m/%d/%Y}">
    <input id="camping_depart_date" value="{departure:%m/%d/%Y}">{cards}'''


def site_card(site_id="3", kind="Cabin", park="112", disabled=False):
    return f'''<div id="card_item_{site_id}">
    <button data-siteidno="{site_id}" data-parent_idno="{park}" {'disabled' if disabled else ''}>Reserve</button>
    <div class="siteNameStats"><span class="ghost_title_lg">{kind} {site_id}<span>Flowing Lake</span></span>
    <div>Max People: 5</div></div><span><b>Site Type:</b> {kind}</span></div>'''


def test_parse_exact_stay_includes_cabins_yurts_and_tent_sites():
    html = search_page(site_card() + site_card("4", "Yurt") + site_card("5", "Tent")
                       + site_card("6", "Cabin", disabled=True) + site_card("7", "Cabin", park="2001"))
    sites = parse_availability(html, COUNTY_ID, ARRIVAL, DEPARTURE)
    assert [s.campsite_type for s in sites] == ["Cabin", "Yurt", "Tent"]
    assert sites[0].site == "Cabin 3"
    assert sites[0].max_num_people == 5
    query = parse_qs(urlparse(sites[0].booking_url).query)
    assert query["parent_idno"] == ["112"]
    assert query["camping_arrive_date"] == ["06/04/2027"]
    assert query["camping_depart_date"] == ["06/06/2027"]


@pytest.mark.parametrize("html", ["Access denied", search_page(), search_page(site_card(), park="2001"),
                                 search_page(site_card(), arrival=date(2027, 6, 5)),
                                 search_page(site_card(park="2001")), search_page(site_card(site_id="unknown"))])
def test_unknown_or_changed_response_is_not_no_availability(html):
    with pytest.raises(ProviderResponseError):
        parse_availability(html, COUNTY_ID, ARRIVAL, DEPARTURE)


def test_explicit_no_results_is_recognized():
    html = search_page("No sites are available for an arrive date of 06/04/2027, and departing on 06/06/2027 at Flowing Lake")
    assert parse_availability(html, COUNTY_ID, ARRIVAL, DEPARTURE) == []


def test_catalog_uses_stable_namespaced_ids_and_full_names():
    html = '''<select id="parent_idno"><option value="">Select</option>
    <option value="112" title="Flowing Lake" data-lat="48" data-lng="-122">Flowing</option></select>
    <script>jsonPlaces = [{"idno":112,"name":"Flowing Lake","gps_lat":47.953,"gps_long":-121.99}];</script>'''
    target = parse_catalog(html)[0]
    assert target["campground_id"] == COUNTY_ID
    assert target["name"] == "Flowing Lake"
    assert target["latitude"] == 47.953
    assert target["poll_interval_minutes"] == 60
    with pytest.raises(ProviderResponseError):
        parse_catalog("Service unavailable")


def test_rate_limit_honors_retry_after_without_retries():
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(429, headers={"Retry-After": "7200"})
    client = SnohomishClient(httpx.MockTransport(respond))
    with pytest.raises(RateLimitError) as error:
        asyncio.run(client.trip_availability(COUNTY_ID, ARRIVAL, DEPARTURE))
    assert error.value.retry_after_seconds == 7200
    assert "Snohomish" in str(error.value)
    assert len(requests) == 1
    assert requests[0].method == "GET"


@pytest.mark.parametrize("status", [302, 403, 500])
def test_provider_denial_and_errors_do_not_follow_or_retry(status):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, headers={"Location": "https://example.invalid"})
    with pytest.raises(ProviderResponseError):
        asyncio.run(SnohomishClient(httpx.MockTransport(respond)).trip_availability(COUNTY_ID, ARRIVAL, DEPARTURE))
    assert len(requests) == 1


def test_provider_network_failure_is_diagnostic_error():
    def respond(request):
        raise httpx.ConnectError("test connection failure", request=request)
    with pytest.raises(ProviderResponseError, match="could not be reached"):
        asyncio.run(SnohomishClient(httpx.MockTransport(respond)).discover())


class CountyClient:
    def __init__(self):
        self.calls = []

    async def discover_external(self, source_id):
        return [{"name": "Flowing Lake", "campground_id": COUNTY_ID, "park_name": "Snohomish County Parks", "state_code": "WA"}]

    async def monthly_availability(self, campground_id, month):
        self.calls.append(("recreation", campground_id))
        raise RateLimitError(120)

    async def trip_availability(self, campground_id, arrival, departure, before_request=None):
        if before_request:
            await before_request()
        self.calls.append(("snohomish", campground_id))
        return [Campsite("camava:snoco:3", "Cabin 3", "", "Cabin", 5, {},
                         booking_url=campground_url(campground_id, arrival.isoformat(), departure.isoformat()))]


class Recorder:
    def __init__(self):
        self.results = []

    async def notify_results(self, results, store, max_items=5):
        self.results.extend(results)


def make_watch(store, campground_id, name):
    target = store.create_target({"name": name, "campground_id": campground_id, "state_code": "WA"})
    return store.create_watch({"name": name, "target_id": target["id"], "mode": "specific",
                               "window_start": ARRIVAL.isoformat(), "window_end": DEPARTURE.isoformat(),
                               "specific_ranges": [{"arrival_date": ARRIVAL.isoformat(), "departure_date": DEPARTURE.isoformat()}]})


def test_mixed_provider_sweep_keeps_county_running_during_federal_cooldown(tmp_path):
    store = Store(tmp_path / "test.db")
    store.init()
    federal = make_watch(store, "112", "Federal")
    county = make_watch(store, COUNTY_ID, "County")
    client = CountyClient()
    recorder = Recorder()
    scanner = Scanner(store, client, recorder, 60, api_request_delay_seconds=0)
    scanner._begin_full_scan([federal, county])
    result = asyncio.run(scanner.scan_all_watches())
    assert result["status"] == "waiting"
    assert result["completed_count"] == 1
    assert result["remaining_count"] == 1
    assert result["available_count"] == 1
    assert len(recorder.results) == 1
    assert recorder.results[0]["booking_url"].startswith("https://reservations.snocoparks.org/")
    assert client.calls == [("recreation", "112"), ("snohomish", COUNTY_ID)]
    assert scanner._sweep["pending"] == [federal["id"]]
    assert release_hints(county) == []


def test_existing_database_and_backup_keep_county_ids_and_booking_urls(tmp_path):
    store = Store(tmp_path / "existing.db")
    store.init()
    make_watch(store, "112", "Federal")
    make_watch(store, COUNTY_ID, "County")
    scanner = Scanner(store, CountyClient(), Recorder(), 60, api_request_delay_seconds=0)
    asyncio.run(scanner.scan_all_watches())
    original_url = store.list_results()[0]["booking_url"]
    store.init()
    store.init()
    assert store.list_results()[0]["booking_url"] == original_url
    backup = ConfigBackup.model_validate(store.export_config()).model_dump(mode="json")
    restored = Store(tmp_path / "restore.db")
    restored.init()
    restored.import_config(backup)
    assert {t["campground_id"] for t in restored.list_targets()} == {"112", COUNTY_ID}
    assert len(restored.list_watches()) == 2
    assert restored.get_target_by_campground_id(COUNTY_ID)["booking_url"].startswith("https://reservations.snocoparks.org/")


def test_county_discovery_deduplicates_and_federal_pack_does_not_count_county(tmp_path):
    store = Store(tmp_path / "catalog.db")
    store.init()
    client = CountyClient()
    assert asyncio.run(discover_source(store, client, "snohomish-county-parks"))["new_count"] == 1
    for _ in range(2):
        asyncio.run(import_source(store, client, "snohomish-county-parks", 60))
    assert len(store.list_targets()) == 1
    sources = {s["id"]: s for s in list_source_definitions(store)}
    assert sources["snohomish-county-parks"]["imported_count"] == 1
    assert sources["washington-recreation-gov-region"]["imported_count"] == 0
    assert sources["washington-state-parks"]["status"] == "experimental"


def test_new_county_import_joins_state_watch_and_notifies_in_mixed_crawl(tmp_path):
    store = Store(tmp_path / "expanding.db")
    store.init()
    federal = store.create_target({"name": "Federal", "campground_id": "112", "state_code": "WA"})
    members = store.create_watch_group([federal["id"]], {
        "name": "WA weekend", "mode": "specific", "window_start": ARRIVAL.isoformat(),
        "window_end": DEPARTURE.isoformat(), "specific_ranges": [{"arrival_date": ARRIVAL.isoformat(),
        "departure_date": DEPARTURE.isoformat()}], "site_filters": {"site_type": "cabin"},
    }, {"kind": "state", "state_code": "WA"})
    client = CountyClient()
    recorder = Recorder()
    scanner = Scanner(store, client, recorder, 60, api_request_delay_seconds=0)
    async def scenario():
        await import_source(store, client, "snohomish-county-parks", 60)
        assert len(store.list_watches()) == 2
        assert {watch["group_id"] for watch in store.list_watches()} == {members[0]["group_id"]}
        result = await scanner.scan_all_watches()
        assert result["status"] == "waiting"
        assert result["completed_count"] == 1
        assert len(recorder.results) == 1
        assert recorder.results[0]["campground_id"] == COUNTY_ID
    asyncio.run(scenario())


def test_county_backoff_survives_restart_without_blocking_federal(tmp_path):
    store = Store(tmp_path / "cooldown.db")
    store.init()
    scanner = Scanner(store, CountyClient(), Recorder(), 60)
    scanner._start_rate_limit_backoff(RateLimitError(7200, "Snohomish"), "snohomish")
    restored = Scanner(store, CountyClient(), Recorder(), 60)
    restored.restore_runtime_state()
    assert restored._rate_limit_remaining_minutes("snohomish") >= 119
    assert restored._rate_limit_remaining_minutes("recreation") is None


def test_eta_includes_blocked_provider_while_other_provider_is_eligible(tmp_path):
    store = Store(tmp_path / "eta.db")
    store.init()
    federal = make_watch(store, "112", "Federal")
    county = make_watch(store, COUNTY_ID, "County")
    scanner = Scanner(store, CountyClient(), Recorder(), 60)
    scanner._begin_full_scan([federal, county])
    scanner._start_rate_limit_backoff(RateLimitError(7200, "Snohomish"), "snohomish")
    status = scanner.scan_status()
    assert status["status"] == "queued"
    assert status["cooldown_seconds"] == 0
    assert status["estimated_remaining_seconds"] >= 7200
    assert status["estimated_requests_remaining"] == 2


def test_unknown_provider_rejected():
    with pytest.raises(ValueError):
        TargetCreate(name="Unknown", campground_id="example:123")
    assert provider_key("232464") == "recreation"


def test_county_api_import_watch_scan_and_result(tmp_path, monkeypatch):
    from backend.app import main

    store = Store(tmp_path / "api.db")
    store.init()
    provider = CountyClient()
    recorder = Recorder()
    scanner = Scanner(store, provider, recorder, 60, api_request_delay_seconds=0)
    monkeypatch.setattr(main, "store", store)
    monkeypatch.setattr(main, "client", provider)
    monkeypatch.setattr(main, "scanner", scanner)

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://test") as client:
            imported = await client.post("/api/sources/snohomish-county-parks/import")
            assert imported.status_code == 200
            target = imported.json()["targets"][0]
            created = await client.post("/api/watches", json={
                "name": "County weekend", "target_id": target["id"], "mode": "specific",
                "window_start": ARRIVAL.isoformat(), "window_end": DEPARTURE.isoformat(),
                "specific_ranges": [{"arrival_date": ARRIVAL.isoformat(), "departure_date": DEPARTURE.isoformat()}],
                "site_filters": {"site_type": "cabin"},
            })
            assert created.status_code == 200
            watch_id = created.json()["id"]
            scanned = await client.post(f"/api/watches/{watch_id}/scan")
            assert scanned.status_code == 200
            assert scanned.json()["available_count"] == 1
            results = (await client.get("/api/results")).json()
            assert len(results) == 1
            assert "snocoparks.org" in results[0]["booking_url"]
            assert (await client.post(f"/api/targets/{target['id']}/detect-release-window")).status_code == 400
            # A second check reuses the exact-stay cache and does not notify twice.
            await client.post(f"/api/watches/{watch_id}/scan")
            assert provider.calls == [("snohomish", COUNTY_ID)]
            assert len(recorder.results) == 1
            assert (await client.post("/api/watches/bulk", json={"action": "delete", "watch_ids": [watch_id]})).status_code == 200
            assert (await client.get("/api/results")).json() == []

    asyncio.run(scenario())


def test_provider_error_does_not_expire_existing_match(tmp_path):
    store = Store(tmp_path / "failure.db")
    store.init()
    watch = make_watch(store, COUNTY_ID, "County")
    provider = CountyClient()
    scanner = Scanner(store, provider, Recorder(), 60, api_request_delay_seconds=0, availability_cache_minutes=0)
    asyncio.run(scanner.scan_watch(watch["id"]))

    async def changed(*args, **kwargs):
        raise ProviderResponseError("Provider page changed")
    provider.trip_availability = changed
    with pytest.raises(ProviderResponseError):
        asyncio.run(scanner.scan_watch(watch["id"]))
    assert store.list_results()[0]["active"] == 1
    assert store.list_results()[0]["status"] == "available"


def test_stop_after_county_request_does_not_save_unprocessed_results(tmp_path):
    store = Store(tmp_path / "cancel.db")
    store.init()
    watch = make_watch(store, COUNTY_ID, "County")
    provider = CountyClient()
    recorder = Recorder()
    scanner = Scanner(store, provider, recorder, 60, api_request_delay_seconds=0)
    original = provider.trip_availability

    async def stop(*args, **kwargs):
        sites = await original(*args, **kwargs)
        scanner.cancel_current_scan()
        return sites
    provider.trip_availability = stop
    assert asyncio.run(scanner.scan_watch(watch["id"]))["status"] == "cancelled"
    assert store.list_results() == []
    assert recorder.results == []
