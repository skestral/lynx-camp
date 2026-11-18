"""Read-only UseDirect catalogs and occupied-night calendars, based on Camply's contract."""
from __future__ import annotations

import asyncio
import json
import math
import re
import time
from datetime import UTC, date, datetime, timedelta

import httpx
from fake_useragent import UserAgent

from .goingtocamp import connection_state
from .provider_diagnostics import capture_diagnostic
from .provider_errors import ProviderResponseError
from .provider_ids import campground_url, usedirect_identity
from .provider_registry import USEDIRECT_TENANTS, gtc_state_key
from .recreation import Campsite, RateLimitError, _retry_after_seconds

NIGHTLY_CATEGORIES = {"camping", "group camping", "hook up camping", "lodging", "primitive camping", "remote camping"}
EQUIPMENT = {"tent": "tent", "tent only": "tent", "rv/motorhome": "rv", "trailer": "trailer",
             "trailer only": "trailer", "truck/suv/van": "vehicle"}


def require(condition, message):
    if not condition:
        raise ProviderResponseError(f"UseDirect: {message}; availability is unknown.")


def parse_catalog(places, facilities, tenant):
    require(isinstance(places, list) and isinstance(facilities, list), "incomplete catalog")
    config = USEDIRECT_TENANTS[tenant]
    parks = {p["PlaceId"]: p for p in places if isinstance(p, dict) and type(p.get("PlaceId")) is int
             and p.get("AllowWebBooking") is True and p.get("IsWebViewable") is True}
    targets = {}
    for facility in facilities:
        require(isinstance(facility, dict), "invalid facility")
        place = parks.get(facility.get("PlaceId"))
        name = facility.get("Name")
        if not place or not isinstance(name, str) or facility.get("AllowWebBooking") is not True:
            continue
        # The catalog mixes permits and overnight facilities under the same type.
        # Metro coverage is the two published Oxbow overnight facilities. California
        # discovery is conservative; its stay parser also rejects non-nightly units.
        if tenant == "metro":
            if (facility.get("PlaceId"), facility.get("FacilityId")) not in {(102, 107), (102, 110)}:
                continue
        elif (facility.get("PlaceId"), facility.get("FacilityId")) != (2, 327) and (
                not re.search(r"camp|cabin|cottage|yurt|bunkhouse|lodge", name, re.I) or re.search(r"day.use|permit|tour", name, re.I)):
            continue
        require(type(facility.get("FacilityId")) is int and facility["FacilityId"] > 0, "invalid facility identity")
        identity = f"ud:{tenant}:{place['PlaceId']}:{facility['FacilityId']}"
        require(identity not in targets, "duplicate facility identity")
        target = {"campground_id": identity, "name": name, "park_name": str(place.get("Name") or config["name"]),
                  "state_code": config["state"], "timezone": "America/Los_Angeles", "poll_interval_minutes": 60,
                  "booking_url": campground_url(identity)}
        lat, lng = place.get("Latitude"), place.get("Longitude")
        if type(lat) in (int, float) and type(lng) in (int, float) and -90 <= lat <= 90 and -180 <= lng <= 180:
            target.update(latitude=lat, longitude=lng)
        targets[identity] = target
    require(bool(targets), "no supported overnight facilities returned")
    return targets


def parse_grid(payload, campground_id, arrival, departure, filters):
    _, _, facility_id = usedirect_identity(campground_id)
    nights = (departure - arrival).days
    last_night = departure - timedelta(days=1)
    require(isinstance(payload, dict) and payload.get("StartDate") == arrival.isoformat()
            and payload.get("EndDate") == last_night.isoformat()
            and payload.get("NightsRequested") == nights and payload.get("NightsActual") == nights,
            "calendar does not cover the requested occupied nights")
    facility = payload.get("Facility")
    require(isinstance(facility, dict) and facility.get("FacilityId") == facility_id, "mismatched facility")
    rules = facility.get("Restrictions")
    require(isinstance(rules, dict) and type(rules.get("IsRestrictionValid")) is bool, "missing booking rules")
    require(type(rules.get("MinimumStay")) is int and type(rules.get("MaximumStay")) is int, "missing stay limits")
    try:
        first = date.fromisoformat(rules["FutureBookingStarts"][:10])
        last = date.fromisoformat(rules["FutureBookingEnds"][:10])
    except (ValueError, TypeError, KeyError) as exc:
        raise ProviderResponseError("UseDirect booking window is unknown.") from exc
    if not rules["IsRestrictionValid"] or not rules["MinimumStay"] <= nights <= rules["MaximumStay"] or not first <= arrival <= last_night <= last:
        return []
    require(isinstance(filters, dict) and isinstance(filters.get("UnitCategories"), list)
            and isinstance(filters.get("NightlySleepingUnits"), list), "missing equipment/category metadata")
    categories = {item["UnitCategoryId"]: item["UnitCategoryName"] for item in filters["UnitCategories"]
                  if isinstance(item, dict) and str(item.get("UnitCategoryName", "")).casefold() in NIGHTLY_CATEGORIES}
    equipment = {item["SleepingUnitId"]: EQUIPMENT[item["SleepingUnitName"].casefold()]
                 for item in filters["NightlySleepingUnits"] if isinstance(item, dict)
                 and str(item.get("SleepingUnitName", "")).casefold() in EQUIPMENT}
    groups = {(item.get("UnitCategoryId"), item.get("UnitTypesGroupId")): item["UnitTypesGroupName"]
              for item in filters.get("UnitTypesGroups", []) if isinstance(item, dict)
              and isinstance(item.get("UnitTypesGroupName"), str)}
    require(bool(categories), "unrecognized overnight categories")
    units = facility.get("Units")
    require(isinstance(units, dict) and bool(units) and len(units) <= 10000, "missing campsite calendar")
    dates = {(arrival + timedelta(days=i)).isoformat() for i in range(nights)}
    require(type(facility.get("UnitCount")) is int and facility["UnitCount"] == len(units), "incomplete campsite list")
    season = facility.get("SeasonDates")
    require(isinstance(season, dict) and all(type(season.get(day + "T00:00:00")) is bool for day in dates)
            and type(facility.get("IsReservationDraw")) is bool, "missing season rules")
    if facility["IsReservationDraw"] or not all(season[day + "T00:00:00"] for day in dates):
        return []
    seen, sites = set(), []
    # Dictionary keys are provider sort keys (often decimals), not UnitId.
    for unit in units.values():
        require(isinstance(unit, dict) and type(unit.get("UnitId")) is int and unit["UnitId"] > 0, "invalid campsite")
        require(unit["UnitId"] not in seen, "duplicate campsite identity")
        seen.add(unit["UnitId"])
        if unit.get("UnitCategoryId") not in categories:
            continue
        require(unit.get("UseType") == 4, "unsupported overnight use type")
        require(all(type(unit.get(key)) is bool for key in ("AllowWebBooking", "IsWebViewable", "IsFiltered")), "missing campsite eligibility")
        if not unit["AllowWebBooking"] or not unit["IsWebViewable"] or unit["IsFiltered"]:
            continue
        slices = unit.get("Slices")
        require(isinstance(slices, dict), "missing night records")
        records = list(slices.values())
        require(all(isinstance(s, dict) for s in records) and len(records) == nights
                and {s.get("Date") for s in records} == dates, "incomplete campsite stay")
        for record in records:
            require(all(type(record.get(key)) is bool for key in ("IsFree", "IsBlocked", "IsWalkin", "IsReservationDraw"))
                    and type(record.get("MinStay")) is int and "Lock" in record and "ReservationId" in record, "unknown nightly rules")
        if not all(s["IsFree"] and not any(s[key] for key in ("IsBlocked", "IsWalkin", "IsReservationDraw", "Lock", "ReservationId"))
                   and nights >= s["MinStay"] for s in records):
            continue
        require(isinstance(unit.get("Name"), str) and bool(unit["Name"]), "missing campsite name")
        length = unit.get("VehicleLength")
        length = float(length) if type(length) in (int, float) and math.isfinite(length) and 0 < length <= 200 else None
        sleeping = unit.get("SleepingUnitIds")
        kinds = tuple(sorted({equipment[key] for key in sleeping if key in equipment})) if isinstance(sleeping, list) else ()
        kind = groups.get((unit["UnitCategoryId"], unit.get("UnitTypeGroupId")), categories[unit["UnitCategoryId"]])
        sites.append(Campsite(f"{campground_id}:{unit['UnitId']}", unit["Name"], "", kind, None, {},
                              booking_url=campground_url(campground_id), equipment=kinds, max_vehicle_length_ft=length))
    return sites


class UseDirectClient:
    def __init__(self, tenant, store=None, transport=None, request_spacing_seconds=5):
        self.config, self.tenant = USEDIRECT_TENANTS[tenant], tenant
        self.state_tenant = f"ud_{tenant}"
        self.store, self.transport = store, transport
        self.request_spacing_seconds = request_spacing_seconds
        self._lock, self._catalog_lock = asyncio.Lock(), asyncio.Lock()
        self._last_request, self._catalog_at = 0., 0.
        self._catalog, self._filters, self._state = None, None, None
        self._user_agent = UserAgent(browsers=["chrome"]).random

    async def _save_state(self, state):
        self._state = state
        if self.store:
            await asyncio.to_thread(self.store.set_app_settings, {gtc_state_key(self.state_tenant): json.dumps(state)})

    async def _check_state(self):
        if self._state is None:
            self._state = await asyncio.to_thread(connection_state, self.store, self.state_tenant)
        require(self._state["state"] != "access_denied", "API access stopped after a denial; review access in Sources")
        if self._state["state"] == "rate_limited":
            remaining = (datetime.fromisoformat(self._state["retry_at"]) - datetime.now(UTC)).total_seconds()
            if remaining > 0:
                raise RateLimitError(math.ceil(remaining), self.config["name"])

    async def ensure_access(self):
        async with self._lock:
            await self._check_state()

    async def reset_access_stop(self):
        async with self._lock:
            require(not self._catalog_lock.locked(), "catalog check is still in progress")
            state = self._state or await asyncio.to_thread(connection_state, self.store, self.state_tenant)
            require(not state.get("retry_at") or datetime.fromisoformat(state["retry_at"]) <= datetime.now(UTC), "cooldown has not elapsed")
            self._catalog = None
            await self._save_state({"state": "unverified"})

    async def _request(self, path, body=None, before_request=None):
        require(path in {"/rdr/fd/places", "/rdr/fd/facilities", "/rdr/search/filters", "/rdr/search/grid"}, "unsupported API operation")
        async with self._lock:
            await self._check_state()
            await asyncio.sleep(max(0, self.request_spacing_seconds - (time.monotonic() - self._last_request)))
            if before_request:
                await before_request("Checking calendar" if body else "Loading catalog")
            started = time.monotonic()
            async def record(outcome, response=None, error=None):
                await asyncio.to_thread(capture_diagnostic, self.store, path, None, time.monotonic() - started,
                                        tenant=self.state_tenant, outcome=outcome, response=response, error=error)
            try:
                async with httpx.AsyncClient(timeout=25, transport=self.transport, follow_redirects=False,
                                             headers={"User-Agent": self._user_agent}) as client:
                    url = self.config["base"] + path
                    response = await client.post(url, json=body) if body else await client.get(url)
            except httpx.RequestError as exc:
                await record("transport_error", error=exc)
                raise ProviderResponseError(f"{self.config['name']} could not be reached; availability is unknown.") from exc
            finally:
                self._last_request = time.monotonic()
            now = datetime.now(UTC)
            if response.status_code == 429:
                delay = max(3600, _retry_after_seconds(response.headers.get("Retry-After")) or 0)
                await self._save_state({"state": "rate_limited", "retry_at": (now + timedelta(seconds=delay)).isoformat()})
                await record("rate_limited", response)
                raise RateLimitError(delay, self.config["name"])
            if response.status_code in {401, 403} or 300 <= response.status_code < 400 or response.status_code == 200 and "json" not in response.headers.get("content-type", ""):
                await self._save_state({"state": "access_denied", "retry_at": (now + timedelta(hours=1)).isoformat(),
                                        "message": f"API access stopped (HTTP {response.status_code}); manual review required."})
                await record("access_denied", response)
                require(False, "API access denied; no automatic retry")
            if response.status_code != 200:
                await record("http_error", response)
                require(False, f"API returned HTTP {response.status_code}")
            if len(response.content) > 8_000_000:
                await record("response_too_large", response)
                require(False, "response size limit exceeded")
            try:
                data = response.json()
            except ValueError as exc:
                await record("invalid_json", response)
                raise ProviderResponseError("UseDirect returned invalid JSON; availability is unknown.") from exc
            await record("json_response", response)
            return data

    async def catalog(self, before_request=None, refresh=False):
        async with self._catalog_lock:
            await self.ensure_access()
            if not refresh and self._catalog is not None and time.monotonic() - self._catalog_at < 86400:
                return self._catalog
            places = await self._request("/rdr/fd/places", before_request=before_request)
            facilities = await self._request("/rdr/fd/facilities", before_request=before_request)
            filters = await self._request("/rdr/search/filters", before_request=before_request)
            catalog = parse_catalog(places, facilities, self.tenant)
            async with self._lock:
                await self._check_state()
                self._catalog, self._filters, self._catalog_at = catalog, filters, time.monotonic()
                await self._save_state({"state": "catalog_loaded", "checked_at": datetime.now(UTC).isoformat()})
            return catalog

    async def discover(self):
        return list((await self.catalog(refresh=True)).values())

    async def trip_availability(self, campground_id, arrival, departure, before_request=None):
        tenant, _, facility = usedirect_identity(campground_id)
        require(tenant == self.tenant and 1 <= (departure - arrival).days <= 31, "invalid stay or tenant")
        require(campground_id in await self.catalog(before_request), "target absent from overnight catalog")
        # Grid EndDate is inclusive; checkout is not an occupied night.
        payload = await self._request("/rdr/search/grid", {
            "StartDate": arrival.strftime("%m-%d-%Y"), "EndDate": (departure - timedelta(days=1)).strftime("%m-%d-%Y"),
            "FacilityId": facility, "WebOnly": True, "UnitSort": "orderby", "InSeasonOnly": True,
        }, before_request)
        return parse_grid(payload, campground_id, arrival, departure, self._filters)
