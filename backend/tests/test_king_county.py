from __future__ import annotations

import asyncio
import json
from datetime import date
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from backend.app.activenet import CAMPGROUND_ID, KingCountyClient, parse_availability, reservation_allowed, stay_allowed
from backend.app.db import Store
from backend.app.provider_errors import ProviderResponseError
from backend.app.provider_ids import campground_url, provider_key
from backend.app.providers import CampgroundClient
from backend.app.recreation import RateLimitError
from backend.app.scanner import Scanner
from backend.app.schemas import ConfigBackup, TargetCreate
from backend.app.sources import import_source, list_source_definitions


ARRIVAL, DEPARTURE = date(2027, 6, 4), date(2027, 6, 6)


@pytest.fixture(autouse=True)
def calendar(monkeypatch):
    monkeypatch.setattr("backend.app.activenet.local_today", lambda: date(2026, 11, 17))
    class ScanDate(date):
        @classmethod
        def today(cls):
            return cls(2026, 11, 17)
    monkeypatch.setattr("backend.app.scanner.date", ScanDate)


def response(body):
    return {"headers": {"response_code": "0000"}, "body": body}


def item(site_id=124, name="Yurt 6", kind="Campground (Yurts/Container)", type_id=51):
    return {"id": site_id, "name": name, "type_name": kind, "type_id": type_id, "center_id": 66,
            "center_name": "Tolt MacDonald Park & Campground", "reserve_by": "overnight", "reservation_unit_id": 8,
            "max_capacity": 6, "no_internet_permits": False}


def detail(site_id=124, notice=10):
    return response({"resource_detail": {"general_information": {
        "facility_id": site_id, "center_id": 66, "reservation_period_unit": 8, "reserve_by": "overnight",
        "minimum_time": 2, "maximum_time": 7, "no_internet_permits": False,
    }, "advanced_restrictions": [
        f"{who} can make reservations at least {notice} day(s) in advance but not more than 365 day(s) in advance and which extend out to a maximum of 7 day(s)."
        for who in ("Residents", "Non-residents")
    ]}})


def available(ids, status="Available"):
    return response({"facilities": [{"facility_id": site_id, "availability": status} for site_id in ids]})


class Provider:
    def __init__(self):
        self.requests = []
        self.items = [item(), item(125, "Camping Container"), item(84, "Site 18 - Drive-up Tent", "Campground (Drive Up)", 73)]
        self.bad_page = False
        self.status = "Available"

    def respond(self, request):
        self.requests.append(request)
        path = request.url.path
        if path.endswith("/option/filteroptions"):
            data = response({"facility_types": [{"id": 51, "text": "Campground (Yurts/Container)"},
                                                {"id": 73, "text": "Campground (Drive Up)"}, {"id": 43, "text": "Picnics"}]})
        elif path.endswith("/resource"):
            payload = json.loads(request.content)
            assert payload["center_ids"] == [66]
            assert payload["facility_type_ids"] == [51, 73]
            start = payload["start_index"]
            if start:
                assert payload["search_client_id"] == "public-search"
            data = response({"items": self.items[start:start + 2] if not self.bad_page else [],
                             "total": len(self.items), "too_many_resources": False,
                             "next_start_index": start + 2, "search_client_id": "public-search"})
        elif path.endswith("/facilitiesavailability"):
            payload = json.loads(request.content)
            assert payload["datetime_periods"] == [{"from_date_time": "2027-06-04 23:59:00", "to_date_time": "2027-06-06 00:00:00"}]
            assert payload["reservation_unit"] == 8
            data = available(payload["facility_ids"], self.status)
        elif "/detail/" in path:
            data = detail(int(path.rsplit("/", 1)[-1]))
        else:
            raise AssertionError(f"Unexpected provider request: {path}")
        return httpx.Response(200, json=data)

    def client(self):
        return KingCountyClient(httpx.MockTransport(self.respond), request_spacing_seconds=0)


def test_discovery_paginates_all_overnight_types_as_one_target():
    provider = Provider()
    client = provider.client()
    targets = asyncio.run(client.discover())
    assert len(targets) == 1
    assert targets[0]["campground_id"] == CAMPGROUND_ID
    assert targets[0]["park_name"] == "King County Parks"
    assert targets[0]["latitude"] == 47.6451577
    assert len(client._inventory) == 3
    assert len(provider.requests) == 3


def test_exact_stay_checks_rules_and_caches_metadata_but_not_availability():
    provider = Provider()
    client = provider.client()
    stages = []
    async def gate(stage):
        stages.append(stage)
    async def scenario():
        for _ in range(2):
            sites = await client.trip_availability(CAMPGROUND_ID, ARRIVAL, DEPARTURE, gate)
            assert [s.campsite_type for s in sites] == ["Yurt", "Camping Container", "Tent - Campground (Drive Up)"]
            assert parse_qs(urlparse(sites[0].booking_url).query)["facilityId"] == ["124"]
    asyncio.run(scenario())
    assert len(provider.requests) == 8  # three catalog, two availability, three rule checks
    assert len(stages) == len(provider.requests)
    assert stages.count("Checking campsite rules") == 3
    assert all("proceed" not in str(r.url) and "cart" not in str(r.url) for r in provider.requests)


@pytest.mark.parametrize("arrival,departure", [(date(2027, 6, 4), date(2027, 6, 5)),
                                               (date(2027, 6, 4), date(2027, 6, 12)),
                                               (date(2027, 3, 20), date(2027, 3, 22)),
                                               (date(2027, 10, 31), date(2027, 11, 2))])
def test_published_stay_limits_skip_unbookable_searches(arrival, departure):
    provider = Provider()
    assert not stay_allowed(arrival, departure)
    assert asyncio.run(provider.client().trip_availability(CAMPGROUND_ID, arrival, departure)) == []
    assert provider.requests == []


def test_live_per_site_notice_overrides_less_restrictive_general_policy(monkeypatch):
    monkeypatch.setattr("backend.app.activenet.local_today", lambda: date(2027, 5, 28))
    assert stay_allowed(ARRIVAL, DEPARTURE)
    assert not reservation_allowed(detail(notice=10), 124, ARRIVAL, DEPARTURE)
    assert reservation_allowed(detail(notice=5), 124, ARRIVAL, DEPARTURE)


@pytest.mark.parametrize("payload", [response({"facilities": []}), available([124, 124]), available([999]),
                                     available([124], "Unknown"), {"headers": {"response_code": "FAIL"}, "body": {}}])
def test_incomplete_or_unknown_status_is_not_empty_availability(payload):
    with pytest.raises(ProviderResponseError):
        parse_availability(payload, [item()], ARRIVAL, DEPARTURE)


@pytest.mark.parametrize("status", ["Unavailable", "Partial"])
def test_partial_or_unavailable_stays_are_not_hits(status):
    assert parse_availability(available([124], status), [item()], ARRIVAL, DEPARTURE) == []


def test_missing_rule_or_wrong_identity_fails_closed():
    payload = detail()
    payload["body"]["resource_detail"]["advanced_restrictions"].pop()
    with pytest.raises(ProviderResponseError):
        reservation_allowed(payload, 124, ARRIVAL, DEPARTURE)
    with pytest.raises(ProviderResponseError):
        reservation_allowed(detail(), 125, ARRIVAL, DEPARTURE)


def test_pagination_does_not_replace_cached_inventory_with_partial_data():
    provider = Provider()
    client = provider.client()
    asyncio.run(client.discover())
    provider.bad_page = True
    with pytest.raises(ProviderResponseError):
        asyncio.run(client.discover())
    assert len(client._inventory) == 3


@pytest.mark.parametrize("status", [302, 403, 429, 500])
def test_denied_or_rate_limited_requests_are_not_retried(status):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, headers={"Retry-After": "3600", "Location": "https://example.invalid"})
    client = KingCountyClient(httpx.MockTransport(respond), 0)
    with pytest.raises(RateLimitError if status == 429 else ProviderResponseError) as error:
        asyncio.run(client.discover())
    assert len(requests) == 1
    if status == 429:
        assert error.value.retry_after_seconds == 3600


def test_unreviewed_king_county_center_and_foreign_booking_ids_rejected():
    assert provider_key(CAMPGROUND_ID) == "king"
    with pytest.raises(ValueError):
        TargetCreate(name="Unknown", campground_id="activenet:king:99")
    with pytest.raises(ValueError):
        campground_url(CAMPGROUND_ID, campsite_id="camava:snoco:124")


def test_import_watch_scan_backup_and_restart_keep_provider_identity(tmp_path):
    store = Store(tmp_path / "king.db")
    store.init()
    provider = Provider()
    client = CampgroundClient()
    client.king = provider.client()
    notifications = []
    class Notifier:
        async def notify_results(self, results, store, max_items):
            notifications.extend(results)
    scanner = Scanner(store, client, Notifier(), 60, api_request_delay_seconds=0)
    async def scenario():
        imported = await import_source(store, client, "king-county-parks", 60)
        target = imported["targets"][0]
        watch = store.create_watch({"name": "King weekend", "target_id": target["id"], "mode": "specific",
                                    "window_start": ARRIVAL.isoformat(), "window_end": DEPARTURE.isoformat(),
                                    "specific_ranges": [{"arrival_date": ARRIVAL.isoformat(), "departure_date": DEPARTURE.isoformat()}]})
        result = await scanner.scan_watch(watch["id"])
        assert result["available_count"] == 3
        await scanner.scan_watch(watch["id"])
        assert len(notifications) == 3
    asyncio.run(scenario())
    links = [r["booking_url"] for r in store.list_results()]
    assert all("activecommunities.com/kingcountyparks/" in link for link in links)
    assert len(set(links)) == 3
    store.init()
    assert [r["booking_url"] for r in store.list_results()] == links
    backup = ConfigBackup.model_validate(store.export_config()).model_dump(mode="json")
    restored = Store(tmp_path / "restored.db")
    restored.init()
    restored.import_config(backup)
    assert restored.list_targets()[0]["campground_id"] == CAMPGROUND_ID
    sources = {s["id"]: s for s in list_source_definitions(store)}
    assert sources["king-county-parks"]["imported_count"] == 1
    assert sources["washington-recreation-gov-region"]["imported_count"] == 0
    assert any(e["event_type"] == "provider_request" for e in store.list_scan_events())


def test_cancel_during_rule_checks_stops_before_more_requests_or_alerts(tmp_path):
    store = Store(tmp_path / "cancel.db")
    store.init()
    target = store.create_target({"campground_id": CAMPGROUND_ID, "name": "Tolt-MacDonald"})
    watch = store.create_watch({"name": "King weekend", "target_id": target["id"], "mode": "specific",
                               "window_start": ARRIVAL.isoformat(), "window_end": DEPARTURE.isoformat(),
                               "specific_ranges": [{"arrival_date": ARRIVAL.isoformat(), "departure_date": DEPARTURE.isoformat()}]})
    provider = Provider()
    client = CampgroundClient()
    notifications = []
    class Notifier:
        async def notify_results(self, results, store, max_items):
            notifications.extend(results)
    scanner = Scanner(store, client, Notifier(), 60, api_request_delay_seconds=0)
    def respond(request):
        if request.url.path.endswith("/detail/124"):
            scanner.cancel_current_scan()
        return provider.respond(request)
    client.king = KingCountyClient(httpx.MockTransport(respond), 0)
    result = asyncio.run(scanner.scan_watch(watch["id"]))
    assert result["status"] == "cancelled"
    assert store.list_results() == []
    assert notifications == []
    assert sum("/detail/" in r.url.path for r in provider.requests) == 1


def test_bad_rule_response_does_not_return_half_verified_matches():
    provider = Provider()
    def respond(request):
        if request.url.path.endswith("/detail/125"):
            return httpx.Response(200, json=response({"resource_detail": {}}))
        return provider.respond(request)
    client = KingCountyClient(httpx.MockTransport(respond), 0)
    with pytest.raises(ProviderResponseError):
        asyncio.run(client.trip_availability(CAMPGROUND_ID, ARRIVAL, DEPARTURE))
    assert set(client._details) == {124}


def test_group_camping_respects_memorial_weekend():
    group = item(117, "Large Group Campsite", "Campground (Group)", 67)
    assert parse_availability(available([117]), [group], date(2027, 5, 21), date(2027, 5, 23)) == []
    assert len(parse_availability(available([117]), [group], date(2027, 5, 28), date(2027, 5, 30))) == 1


def test_day_use_or_foreign_catalog_item_fails_closed():
    provider = Provider()
    provider.items[0]["reserve_by"] = "hour"
    with pytest.raises(ProviderResponseError):
        asyncio.run(provider.client().discover())
    provider.items[0]["reserve_by"] = "overnight"
    provider.items[0]["center_id"] = 99
    with pytest.raises(ProviderResponseError):
        asyncio.run(provider.client().discover())
