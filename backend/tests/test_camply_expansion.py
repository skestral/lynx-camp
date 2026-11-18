"""Synthetic provider contracts. Unit tests never contact reservation or alert services."""
import asyncio
from copy import deepcopy
from dataclasses import replace
from datetime import date
import json

import httpx
import pytest

from backend.app import apprise_alerts
from backend.app.db import Store
from backend.app.goingtocamp import GoingToCampClient, parse_catalog as gtc_catalog
from backend.app.notifications import Notifier
from backend.app.provider_diagnostics import read_diagnostics
from backend.app.provider_errors import ProviderResponseError
from backend.app.provider_ids import campground_url, provider_key
from backend.app.providers import CampgroundClient
from backend.app.recreation import Campsite, RateLimitError, RecreationClient
from backend.app.scanner import Scanner, site_matches_filters
from backend.app.schemas import ConfigBackup, NotificationConfigUpdate, SiteFilters
from backend.app.settings import Settings
from backend.app.sources import import_source, list_source_definitions
from backend.app.usedirect import UseDirectClient, parse_catalog, parse_grid

A, D = date(2027, 2, 5), date(2027, 2, 7)
ID = "ud:metro:102:107"
PLACES = [{"PlaceId": 102, "Name": "Oxbow", "AllowWebBooking": True, "IsWebViewable": True}]
FACILITIES = [{"FacilityId": 107, "PlaceId": 102, "Name": "Oxbow Campground", "AllowWebBooking": True}]
FILTERS = {"UnitCategories": [{"UnitCategoryId": 1, "UnitCategoryName": "Camping"}, {"UnitCategoryId": 2, "UnitCategoryName": "Day Use Areas"}],
           "NightlySleepingUnits": [{"SleepingUnitId": 3, "SleepingUnitName": "RV/Motorhome"}]}


def grid():
    nights = ["2027-02-05", "2027-02-06"]
    return {"StartDate": nights[0], "EndDate": nights[1], "NightsRequested": 2, "NightsActual": 2,
            "Facility": {"FacilityId": 107, "UnitCount": 1, "SeasonDates": {day + "T00:00:00": True for day in nights},
                         "IsReservationDraw": False,
                         "Restrictions": {"IsRestrictionValid": True, "MinimumStay": 2, "MaximumStay": 14,
                                          "FutureBookingStarts": "2027-01-01", "FutureBookingEnds": "2027-08-01"},
                         "Units": {"9": {"UnitId": 9, "Name": "Site 9", "UseType": 4, "UnitCategoryId": 1,
                                         "AllowWebBooking": True, "IsWebViewable": True, "IsFiltered": False,
                                         "VehicleLength": 30, "SleepingUnitIds": [3],
                                         "Slices": {day + "T00:00:00": {"Date": day, "IsFree": True, "IsBlocked": False,
                                            "IsWalkin": False, "IsReservationDraw": False, "Lock": None, "ReservationId": 0, "MinStay": 2}
                                                    for day in nights}}}}}


def unit(payload):
    return payload["Facility"]["Units"]["9"]


@pytest.fixture
def store(tmp_path):
    result = Store(tmp_path / "test.db")
    result.init()
    return result


def test_occupied_nights_equipment_and_day_use():
    payload = grid()
    payload["Facility"]["Units"] = {"6054.1": unit(payload)}
    site, = parse_grid(payload, ID, A, D, FILTERS)
    assert site.equipment == ("rv",) and site.max_vehicle_length_ft == 30
    assert site_matches_filters(site, {"equipment": "rv", "vehicle_length_ft": 30})
    assert not site_matches_filters(site, {"equipment": "trailer"})
    assert not site_matches_filters(site, {"equipment": "rv", "vehicle_length_ft": 31})
    assert not site_matches_filters(replace(site, max_vehicle_length_ft=None), {"vehicle_length_ft": 10})
    next(iter(payload["Facility"]["Units"].values()))["UnitCategoryId"] = 2
    assert parse_grid(payload, ID, A, D, FILTERS) == []


@pytest.mark.parametrize("field,value", [("IsFree", False), ("IsBlocked", True), ("IsWalkin", True),
                                        ("IsReservationDraw", True), ("Lock", {"token": "never-persist"}),
                                        ("ReservationId", 999), ("MinStay", 3)])
def test_no_partial_or_ineligible_stays(field, value):
    payload = grid()
    next(iter(unit(payload)["Slices"].values()))[field] = value
    assert parse_grid(payload, ID, A, D, FILTERS) == []


@pytest.mark.parametrize("mutation", [
    lambda p: p.update(EndDate=D.isoformat()), lambda p: p.update(NightsActual=1),
    lambda p: p["Facility"].update(FacilityId=108), lambda p: p["Facility"].update(UnitCount=2),
    lambda p: p["Facility"].pop("Restrictions"), lambda p: p["Facility"].pop("SeasonDates"),
    lambda p: unit(p).update(UseType=1), lambda p: unit(p).update(Slices={}),
    lambda p: next(iter(unit(p)["Slices"].values())).pop("Lock"),
])
def test_unknown_calendar_is_error_not_empty(mutation):
    payload = grid()
    mutation(payload)
    with pytest.raises(ProviderResponseError):
        parse_grid(payload, ID, A, D, FILTERS)


def test_catalog_excludes_permits_hidden_and_unknown():
    facilities = FACILITIES + [{**FACILITIES[0], "FacilityId": 999, "Name": "Day use permit"}]
    assert list(parse_catalog(PLACES, facilities, "metro")) == [ID]
    with pytest.raises(ProviderResponseError):
        parse_catalog([{**PLACES[0], "AllowWebBooking": False}], facilities, "metro")


def test_lodging_retains_provider_accommodation_label():
    payload, filters = grid(), deepcopy(FILTERS)
    unit(payload).update(UnitCategoryId=1008, UnitTypeGroupId=1009)
    filters["UnitCategories"].append({"UnitCategoryId": 1008, "UnitCategoryName": "Lodging"})
    filters["UnitTypesGroups"] = [{"UnitCategoryId": 1008, "UnitTypesGroupId": 1009, "UnitTypesGroupName": "Cabin"}]
    site, = parse_grid(payload, ID, A, D, filters)
    assert site_matches_filters(site, {"site_type": "Cabin"})


def test_native_request_contract_cache_and_cancel(store):
    calls, gates = [], []
    def respond(request):
        calls.append(request)
        assert request.url.host == "oregonrdr.usedirect.com"
        if request.method == "POST":
            body = json.loads(request.content)
            assert body["EndDate"] == "02-06-2027" and body["StartDate"] == "02-05-2027"
            assert body["FacilityId"] == 107 and body["WebOnly"] is True
            return httpx.Response(200, json=grid())
        return httpx.Response(200, json={"places": PLACES, "facilities": FACILITIES, "filters": FILTERS}[request.url.path.split("/")[-1]])
    async def gate(stage):
        gates.append(stage)
    client = UseDirectClient("metro", store, httpx.MockTransport(respond), 0)
    async def run():
        assert len(await client.trip_availability(ID, A, D, gate)) == 1
        assert len(await client.trip_availability(ID, A, D, gate)) == 1
        async def cancel(stage):
            raise asyncio.CancelledError()
        with pytest.raises(asyncio.CancelledError):
            await client.trip_availability(ID, A, D, cancel)
    asyncio.run(run())
    assert len(calls) == len(gates) == 5
    records = read_diagnostics(store, "ud_metro")
    assert records[0]["method"] == "POST" and records[0]["query"] == {}
    assert read_diagnostics(store) == []


@pytest.mark.parametrize("status", [403, 429, 302])
def test_access_stop_persists_isolated_from_other_tenants(store, status):
    calls = []
    def respond(request):
        calls.append(request)
        return httpx.Response(status, text="denied", headers={"Retry-After": "7200"})
    async def run():
        for _ in range(2):
            client = UseDirectClient("metro", store, httpx.MockTransport(respond), 0)
            with pytest.raises(RateLimitError if status == 429 else ProviderResponseError):
                await client.discover()
        await UseDirectClient("ca", store).ensure_access()
        await GoingToCampClient(store).ensure_access()
    asyncio.run(run())
    assert len(calls) == 1


@pytest.mark.parametrize("tenant,host,provider", [("tacoma", "tacomapower.goingtocamp.com", "gtc_tacoma"),
    ("bc", "camping.bcparks.ca", "gtc_bc"), ("pc", "reservation.pc.gc.ca", "gtc_pc")])
def test_gtc_tenant_identity_and_category_safety(tenant, host, provider):
    categories = [{"resourceCategoryId": 1, "localizedValues": [{"name": "Campsite"}]},
                  {"resourceCategoryId": 2, "localizedValues": [{"name": "Cabin"}]}]
    locations = [{"resourceLocationId": -1, "rootMapId": -100, "ianaTimeZone": "America/Vancouver",
                  "resourceCategoryIds": [1, 2], "localizedValues": [{"fullName": "Park"}]}]
    identity = f"gtc:{tenant}:-1:0"
    assert list(gtc_catalog(locations, categories, tenant)) == [identity]
    assert provider_key(identity) == provider and host in campground_url(identity)
    with pytest.raises(ValueError):
        provider_key(f"gtc:{tenant}:-1:1")


def test_new_sources_import_and_backup_preserve_filters(store):
    class Client:
        async def discover_external(self, source_id):
            assert source_id == "oregon-metro"
            return list(parse_catalog(PLACES, FACILITIES, "metro").values())
    imported = asyncio.run(import_source(store, Client(), "oregon-metro", 60))
    target = imported["targets"][0]
    assert next(source for source in list_source_definitions(store) if source["id"] == "oregon-metro")["imported_count"] == 1
    store.create_watch({"target_id": target["id"], "name": "RV weekend", "mode": "specific", "window_start": A.isoformat(),
                        "window_end": D.isoformat(), "nights": 2, "specific_ranges": [{"arrival_date": A.isoformat(), "departure_date": D.isoformat()}],
                        "site_filters": {"equipment": "rv", "vehicle_length_ft": 25, "campsite_ids": [ID + ":9"]}})
    backup = ConfigBackup.model_validate(store.export_config())
    assert backup.targets[0].watches[0].site_filters.vehicle_length_ft == 25
    assert backup.targets[0].watches[0].site_filters.campsite_ids == [ID + ":9"]


def test_equipment_schema_unknown_and_specific_id():
    for filters in [{"equipment": "tent", "vehicle_length_ft": 10}, {"vehicle_length_ft": 10}, {"equipment": "boat"}]:
        with pytest.raises(ValueError):
            SiteFilters(**filters)
    site = Campsite("1", "A1", "", "RV", None, {}, equipment=("rv",), equipment_lengths_ft={"rv": 20})
    assert not site_matches_filters(site, {"equipment": "rv", "vehicle_length_ft": 21})
    assert not site_matches_filters(site, {"campsite_ids": ["2"]})
    assert site_matches_filters(site, {"campsite_ids": ["1"]})


def test_recreation_equipment_identity_and_cache(store):
    client = RecreationClient()
    calls = []
    async def get(path, params):
        calls.append(path)
        return {"campsite": {"campsite_id": "9", "facility_id": "123", "permitted_equipment": [
            {"equipment_name": "RV", "is_deactivated": False, "max_length": 24},
            {"equipment_name": "Trailer", "is_deactivated": False, "max_length": 0}]}}
    client._get = get
    scanner = Scanner(store, client, Notifier(Settings()), 60, api_request_delay_seconds=0)
    site = Campsite("9", "A9", "", "Standard", None, {})
    async def run():
        first = await scanner._with_equipment("123", site)
        second = await scanner._with_equipment("123", site)
        assert first == second and first.equipment_lengths_ft == {"rv": 24}
        assert not site_matches_filters(first, {"equipment": "trailer", "vehicle_length_ft": 1})
        with pytest.raises(ProviderResponseError):
            await client.campsite_equipment("other", "9")
    asyncio.run(run())
    assert len(calls) == 2


def test_apprise_validation_redaction_and_backup(store):
    value = "tgram://123456789:" + "a" * 35 + "/12345"
    NotificationConfigUpdate(apprise_urls=value)
    for bad in ["file:///tmp/secret", "json://localhost/token", value + "\nexec://cmd"]:
        with pytest.raises(ValueError):
            NotificationConfigUpdate(apprise_urls=bad)
    notifier = Notifier(Settings(), store)
    config = notifier.update_config({"apprise_urls": value})
    assert config["values"]["apprise_urls"] == "" and config["configured"]["apprise_urls"]
    assert value not in json.dumps(notifier.status()) and value not in json.dumps(store.export_config())
    assert store.export_config(include_secrets=True)["settings"]["app_settings"]["notification_apprise_urls"] == value
    assert not notifier.clear_notification_secrets()["configured"]["apprise_urls"]


def test_apprise_send_success_and_exception_are_redacted(monkeypatch):
    class Fake:
        async def async_notify(self, **kwargs):
            assert kwargs["timeout"] == 30
            return True
    monkeypatch.setattr(apprise_alerts, "build_client", lambda value: Fake())
    assert asyncio.run(apprise_alerts.send("secret", "match"))["status"] == "sent"
    class Fail:
        async def async_notify(self, **kwargs):
            raise RuntimeError("secret")
    monkeypatch.setattr(apprise_alerts, "build_client", lambda value: Fail())
    report = asyncio.run(apprise_alerts.send("secret", "match"))
    assert report["status"] == "error" and "secret" not in json.dumps(report)


def test_secret_validation_errors_and_provider_diagnostics_api(store, monkeypatch):
    from backend.app import main
    monkeypatch.setattr(main, "store", store)
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(main.app), base_url="http://test") as client:
            response = await client.patch("/api/notifications/config", json={"apprise_urls": "exec://private-token"})
            assert response.status_code == 422 and "private-token" not in response.text
            for source in ("tacoma-power-parks", "bc-parks", "parks-canada", "oregon-metro", "reserve-california"):
                response = await client.get(f"/api/sources/{source}/diagnostics")
                assert response.status_code == 200 and response.json()["records"] == []
                assert response.json()["source_id"] == source
    asyncio.run(run())


def test_watch_scan_alert_dedup_and_restoration(store, tmp_path, monkeypatch):
    def respond(request):
        if request.method == "POST":
            return httpx.Response(200, json=grid())
        return httpx.Response(200, json={"places": PLACES, "facilities": FACILITIES, "filters": FILTERS}[request.url.path.split("/")[-1]])
    client = CampgroundClient(store)
    client.usedirect["metro"] = UseDirectClient("metro", store, httpx.MockTransport(respond), 0)
    imported = asyncio.run(import_source(store, client, "oregon-metro", 60))
    target = imported["targets"][0]
    watch = store.create_watch({"target_id": target["id"], "name": "Weekend", "mode": "specific",
        "window_start": A.isoformat(), "window_end": D.isoformat(), "nights": 2,
        "specific_ranges": [{"arrival_date": A.isoformat(), "departure_date": D.isoformat()}],
        "site_filters": {"equipment": "rv", "vehicle_length_ft": 25}})
    alerts = []
    async def send(urls, message):
        alerts.append(message)
        return {"channel": "apprise", "status": "sent", "message": "Synthetic delivery"}
    monkeypatch.setattr(apprise_alerts, "send", send)
    notifier = Notifier(Settings(apprise_urls="tgram://123456789:" + "a" * 35 + "/12345"), store)
    scanner = Scanner(store, client, notifier, 60, api_request_delay_seconds=0)
    async def run():
        await scanner.scan_watch(watch["id"])
        await scanner.scan_watch(watch["id"])
    asyncio.run(run())
    assert len(store.list_results()) == len(alerts) == 1
    assert "Oxbow" in alerts[0] and "Site 9" in alerts[0]
    backup = ConfigBackup.model_validate(store.export_config()).model_dump(mode="json")
    restored = Store(tmp_path / "restored.db")
    restored.init()
    restored.import_config(backup, 60)
    assert restored.list_watches()[0]["site_filters"]["equipment"] == "rv"
    assert restored.list_targets()[0]["campground_id"] == ID


@pytest.mark.parametrize("tenant", ["tacoma", "bc", "pc"])
def test_additional_gtc_trip_routing(tenant):
    def respond(request):
        if request.url.path.endswith("resourceLocation"):
            payload = [{"resourceLocationId": -1, "rootMapId": -100, "resourceCategoryIds": [1],
                        "localizedValues": [{"fullName": "Park"}]}]
        elif request.url.path.endswith("resourcecategory"):
            payload = [{"resourceCategoryId": 1, "localizedValues": [{"name": "Campsite"}]}]
        else:
            assert request.url.params["getDailyAvailability"] == "false"
            payload = {"resourceAvailabilities": {"-9": [{"availability": 0}]}, "mapLinkAvailabilities": {}}
        return httpx.Response(200, json=payload)
    client = CampgroundClient()
    client.gtc[tenant] = GoingToCampClient(tenant=tenant, transport=httpx.MockTransport(respond), request_spacing_seconds=0)
    sites = asyncio.run(client.trip_availability(f"gtc:{tenant}:-1:0", A, D))
    assert sites[0].campsite_id == f"gtc:{tenant}:-1:0:-100:-9"
