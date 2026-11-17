from __future__ import annotations

import asyncio
import copy
import json
from datetime import date, timedelta
from uuid import UUID

import httpx
import pytest

from backend.app.cedar import (CAMPGROUND_ID, FACILITY_ID, ORGANIZATION_ID, SkagitCountyClient,
                               is_holiday, parse_venue, query_window, reservation_allowed)
from backend.app.db import Store
from backend.app.provider_errors import ProviderResponseError
from backend.app.provider_ids import campground_url, provider_key
from backend.app.providers import CampgroundClient
from backend.app.recreation import RateLimitError
from backend.app.scanner import Scanner
from backend.app.schemas import ConfigBackup, TargetCreate
from backend.app.sources import import_source, list_source_definitions


ARRIVAL, DEPARTURE = date(2026, 11, 20), date(2026, 11, 22)


@pytest.fixture(autouse=True)
def calendar(monkeypatch):
    monkeypatch.setattr("backend.app.cedar.local_today", lambda: date(2026, 11, 17))
    class ScanDate(date):
        @classmethod
        def today(cls):
            return cls(2026, 11, 17)
    monkeypatch.setattr("backend.app.scanner.date", ScanDate)


def uid(number):
    return str(UUID(int=number))


def facility():
    return {"id": FACILITY_ID, "title": "Howard Miller Steelhead Park Campground", "type": "CAMPGROUND",
            "is_hidden_from_public": False, "settings": {"minDaysInAdvance": 1, "maxDaysInAdvance": None,
            "noLimitConsecutiveNights": True, "maxConsecutiveNightsLimit": 14,
            "enableResidentOnlyBookingSetting": False, "requireMinimumStayWeekendsHolidays": True,
            "allowCheckoutBeyondMaxDaysInAdvance": False}, "facility_booking_info_overrides": [
                {"id": uid(i), "facility_id": FACILITY_ID, "organization_id": ORGANIZATION_ID,
                 "override_condition": condition, "override_min_booking_time": minimum,
                 "override_min_booking_time_units": "DAY", "override_start_date": None, "override_end_date": None}
                for i, condition, minimum in [(1, "WEEKEND", 2), (2, "HOLIDAY", 3)]]}


def catalog():
    return {**{k: v for k, v in facility().items() if k not in {"settings", "facility_booking_info_overrides"}},
            "organization_id": ORGANIZATION_ID, "archived_at": None}


def venue(index=1, name="Cabin 1", hidden=False, available=True):
    return {"info": {"id": uid(index + 10), "facility_id": FACILITY_ID, "organization_id": ORGANIZATION_ID,
                     "name": name, "type": "CAMPSITE", "capacity": 4, "is_hidden_from_public": hidden,
                     "settings": {}, "requires_household_members": False},
            "venue_portions": [{"info": {"id": uid(index + 100), "venue_id": uid(index + 10),
                "organization_id": ORGANIZATION_ID, "name": name, "type": "CAMPSITE", "capacity": None,
                "user_booking_info_id": uid(index + 1000), "venue_portion_to_user_booking_info": {
                    "id": uid(index + 1000), "min_booking_time": 1, "min_booking_time_units": "DAY",
                    "max_booking_time": 14, "max_booking_time_units": "DAY", "max_bookings_per_day": None,
                    "user_booking_info_overrides": []}},
                "available_dates": ["2026-11-20", "2026-11-21"] if available else ["2026-11-20"],
                "all_dates_available": available, "all_dates_available_or_pending": True}]}


class Provider:
    def __init__(self):
        self.requests = []
        self.items = [venue(), venue(2, "Tent 1"), venue(3, "RV 1"),
                      venue(4, "Admin only", hidden=True), venue(5, "Cabin 2", available=False)]
        self.mutate = lambda data, offset: None

    def respond(self, request):
        self.requests.append(request)
        payload = json.loads(request.content)
        assert request.method == "POST"
        assert request.url.host == "hasura-production-07um.onrender.com"
        assert payload["query"].startswith("query ")
        assert "bookings {" not in payload["query"] and "user_email" not in payload["query"]
        assert payload["variables"]["facilityId"] == FACILITY_ID
        if payload["operationName"] == "FetchFacilityCore":
            return httpx.Response(200, json={"data": {"facility": catalog()}})
        args = payload["variables"]["input_object"]
        assert args["organization_id"] == ORGANIZATION_ID
        assert args["facility_ids"] == [FACILITY_ID]
        assert args["venue_types"] == ["CAMPGROUND_SECTION", "CAMPSITE"]
        assert args["iso_start_datetime"] == "2026-11-20T08:00:00.000Z"
        assert args["iso_end_datetime"] == "2026-11-22T07:59:59.999Z"
        offset = args["offset"]
        more = offset + 2 < len(self.items)
        page = {"results": [{"info": facility(), "venues": copy.deepcopy(self.items[offset:offset + 2])}],
                "total_venue_portions": len(self.items), "has_more": more, "next_offset": offset + 2 if more else None}
        data = {"facility": catalog(), "getAvailableNightlyFacilitiesAndVenues": page}
        self.mutate(data, offset)
        return httpx.Response(200, json={"data": data})

    def client(self):
        return SkagitCountyClient(httpx.MockTransport(self.respond), 0)


def test_live_catalog_is_one_regional_target_and_pagination_includes_cabins():
    provider = Provider()
    client = provider.client()
    stages = []
    async def gate(stage):
        stages.append(stage)
    async def scenario():
        targets = await client.discover()
        assert len(targets) == 1
        assert targets[0]["campground_id"] == CAMPGROUND_ID
        assert targets[0]["state_code"] == "WA" and targets[0]["latitude"] == 48.48414
        sites = await client.trip_availability(CAMPGROUND_ID, ARRIVAL, DEPARTURE, gate)
        assert [site.campsite_type for site in sites] == ["Cabin", "Tent", "RV"]
        assert len({site.campsite_id for site in sites}) == 3
        assert all(site.booking_url == campground_url(CAMPGROUND_ID) for site in sites)
    asyncio.run(scenario())
    assert len(provider.requests) == 4 and len(stages) == 3


@pytest.mark.parametrize("arrival,departure", [(date(2027, 6, 4), date(2027, 6, 6)),
    (date(2026, 11, 17), date(2026, 11, 19)), (ARRIVAL, ARRIVAL), (ARRIVAL, ARRIVAL + timedelta(days=15)),
    (date(2026, 12, 31), date(2027, 1, 2))])
def test_unreleased_or_invalid_stays_do_not_make_requests(arrival, departure):
    provider = Provider()
    assert asyncio.run(provider.client().trip_availability(CAMPGROUND_ID, arrival, departure)) == []
    assert not provider.requests


def test_midnight_queries_respect_daylight_saving_and_exclusive_checkout():
    assert query_window(date(2026, 3, 7), date(2026, 3, 9)) == {
        "iso_start_datetime": "2026-03-07T08:00:00.000Z", "iso_end_datetime": "2026-03-09T06:59:59.999Z"}
    assert query_window(date(2026, 10, 31), date(2026, 11, 2))["iso_end_datetime"] == "2026-11-02T07:59:59.999Z"


def allowed(item=None, info=None, arrival=ARRIVAL, departure=DEPARTURE):
    item = item or venue()
    return reservation_allowed(info or facility(), item["info"], item["venue_portions"][0]["info"], arrival, departure)


def test_weekend_holiday_base_rules_and_checkout_night():
    assert allowed()
    assert not allowed(departure=ARRIVAL + timedelta(days=1))
    assert allowed(arrival=date(2026, 11, 23), departure=date(2026, 11, 24))
    assert not allowed(arrival=date(2026, 11, 25), departure=date(2026, 11, 27))
    assert allowed(arrival=date(2026, 11, 25), departure=date(2026, 11, 28))
    assert allowed(arrival=date(2026, 11, 25), departure=date(2026, 11, 26))
    item = venue()
    item["venue_portions"][0]["info"]["venue_portion_to_user_booking_info"]["min_booking_time"] = 4
    assert not allowed(item)


def test_holiday_calendar_is_bounded_and_handles_observed_dates():
    assert is_holiday(date(2026, 7, 3)) and is_holiday(date(2026, 7, 4))
    assert is_holiday(date(2026, 11, 26))
    assert not is_holiday(ARRIVAL)
    with pytest.raises(ProviderResponseError, match="calendar update"):
        is_holiday(date(2036, 7, 4))


@pytest.mark.parametrize("settings", [
    {"overrideFacilityMinDaysInAdvance": True, "minDaysInAdvance": 5},
    {"overrideFacilityMaxDaysInAdvance": True, "maxDaysInAdvance": 4, "allowCheckoutBeyondMaxDaysInAdvance": False},
    {"overrideFacilityResidentOnlyBookingSetting": True, "enableResidentOnlyBookingSetting": True},
    {"overrideFacilityCallToBookSetting": True, "enableCallToBookSetting": True},
    {"overrideFacilityMaxConsecutiveDaysSettings": True, "noLimitConsecutiveNights": False, "maxConsecutiveNightsLimit": 1},
])
def test_venue_overrides_are_enforced(settings):
    item = venue()
    item["info"]["settings"] = settings
    assert not allowed(item)


def test_missing_override_inherits_but_malformed_flag_is_not_ignored():
    assert allowed()
    item = venue()
    item["info"]["settings"]["overrideFacilityMinDaysInAdvance"] = "false"
    with pytest.raises(ProviderResponseError):
        allowed(item)


@pytest.mark.parametrize("mutation", [
    lambda p: p.update(available_dates=["2026-11-20", "2026-11-21", "2026-11-22"]),
    lambda p: p.update(available_dates=["2026-11-20"]),
    lambda p: p.update(all_dates_available="true"),
    lambda p: p["info"].update(organization_id=uid(999)),
    lambda p: p["info"].update(venue_id=uid(999)),
    lambda p: p["info"]["venue_portion_to_user_booking_info"].update(min_booking_time_units="HOUR"),
    lambda p: p["info"]["venue_portion_to_user_booking_info"].pop("user_booking_info_overrides"),
])
def test_bad_site_data_fails_closed(mutation):
    item = venue()
    mutation(item["venue_portions"][0])
    with pytest.raises(ProviderResponseError):
        parse_venue(item, facility(), ARRIVAL, DEPARTURE)


@pytest.mark.parametrize("mutation", [
    lambda p: p.update(total_venue_portions=6),
    lambda p: p.update(has_more=False),
    lambda p: p.update(next_offset=0),
    lambda p: p["results"][0].update(venues=[]),
    lambda p: p["results"][0].update(venues=[venue()]),
    lambda p: p["results"][0]["info"]["settings"].update(minDaysInAdvance=2),
])
def test_second_page_failure_does_not_return_partial_matches(mutation):
    provider = Provider()
    provider.mutate = lambda data, offset: mutation(data["getAvailableNightlyFacilitiesAndVenues"]) if offset else None
    with pytest.raises(ProviderResponseError):
        asyncio.run(provider.client().trip_availability(CAMPGROUND_ID, ARRIVAL, DEPARTURE))
    assert len(provider.requests) == 2


def test_unknown_rule_and_foreign_or_archived_facility_are_not_empty_availability():
    info = facility()
    info["facility_booking_info_overrides"][0]["override_condition"] = "CUSTOM"
    with pytest.raises(ProviderResponseError):
        allowed(info=info)
    provider = Provider()
    provider.mutate = lambda data, offset: data["facility"].update(archived_at="2026-11-17")
    with pytest.raises(ProviderResponseError):
        asyncio.run(provider.client().trip_availability(CAMPGROUND_ID, ARRIVAL, DEPARTURE))
    with pytest.raises(ValueError):
        TargetCreate(name="Unknown", campground_id="cedar:skagit:other")
    assert provider_key(CAMPGROUND_ID) == "skagit"


@pytest.mark.parametrize("status", [302, 403, 429, 500])
def test_denied_requests_are_not_retried(status):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, headers={"Retry-After": "3600", "Location": "https://example.invalid"})
    with pytest.raises(RateLimitError if status == 429 else ProviderResponseError) as error:
        asyncio.run(SkagitCountyClient(httpx.MockTransport(respond), 0).discover())
    assert len(requests) == 1
    if status == 429:
        assert error.value.retry_after_seconds == 3600


@pytest.mark.parametrize("payload", [{"data": None}, {"data": {"facility": catalog()}, "errors": [{"message": "failure"}]}])
def test_graphql_errors_never_count_as_success(payload):
    client = SkagitCountyClient(httpx.MockTransport(lambda request: httpx.Response(200, json=payload)), 0)
    with pytest.raises(ProviderResponseError):
        asyncio.run(client.discover())


def test_import_regional_watch_scan_backup_restart_and_cancel(tmp_path):
    store = Store(tmp_path / "skagit.db")
    store.init()
    original = store.create_target({"campground_id": "123", "name": "Federal", "state_code": "WA"})
    members = store.create_watch_group([original["id"]], {
        "name": "WA weekend", "mode": "specific", "window_start": ARRIVAL.isoformat(), "window_end": DEPARTURE.isoformat(),
        "specific_ranges": [{"arrival_date": ARRIVAL.isoformat(), "departure_date": DEPARTURE.isoformat()}]},
        {"kind": "state", "state_code": "WA"})
    provider = Provider()
    client = CampgroundClient()
    client.skagit = provider.client()
    notifications = []
    class Notifier:
        async def notify_results(self, results, store, max_items):
            notifications.extend(results)
    scanner = Scanner(store, client, Notifier(), 60, api_request_delay_seconds=0, availability_cache_minutes=0)
    async def scenario():
        await import_source(store, client, "skagit-county-parks", 60)
        target = store.get_target_by_campground_id(CAMPGROUND_ID)
        watch = store.get_watch_by_target_and_name(target["id"], "WA weekend", members[0]["group_id"])
        assert watch is not None
        assert (await scanner.scan_watch(watch["id"]))["available_count"] == 3
        await scanner.scan_watch(watch["id"])
        assert len(notifications) == 3
        provider.mutate = lambda data, offset: data["getAvailableNightlyFacilitiesAndVenues"].update(has_more=False)
        with pytest.raises(ProviderResponseError):
            await scanner.scan_watch(watch["id"])
        assert max(store.list_scan_runs(), key=lambda run: run["id"])["status"] == "error"
        assert len(store.list_results()) == 3
        provider.mutate = lambda data, offset: scanner.cancel_current_scan() if offset == 0 else None
        assert (await scanner.scan_watch(watch["id"]))["status"] == "cancelled"
        assert len(notifications) == 3
    asyncio.run(scenario())
    store.init()
    assert len(store.list_results()) == 3
    assert all("explore.skagitcounty.org" in r["booking_url"] for r in store.list_results())
    restored = Store(tmp_path / "restored.db")
    restored.init()
    restored.import_config(ConfigBackup.model_validate(store.export_config()).model_dump(mode="json"))
    assert restored.get_target_by_campground_id(CAMPGROUND_ID) is not None
    assert len(restored.list_watches()) == 2
    source = next(s for s in list_source_definitions(store) if s["id"] == "skagit-county-parks")
    assert source["imported_count"] == 1 and source["discover_supported"]
    assert any(e["event_type"] == "provider_request" for e in store.list_scan_events())
