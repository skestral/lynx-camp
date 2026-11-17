"""Native Washington adapter derived from GoCamp's discovery/search workflow.

Uses the newer resourceLocation/availability/map contract, not the retired
mapdatabyid or resource/details calls. See third_party/gocamp for provenance.
"""
from __future__ import annotations

import asyncio
import json
import math
import time
from datetime import UTC, date, datetime, timedelta

import httpx

from .activenet import RequestGate
from .provider_errors import ProviderResponseError
from .provider_ids import campground_url, goingtocamp_identity
from .recreation import Campsite, RateLimitError, _retry_after_seconds


BASE_URL = "https://washington.goingtocamp.com/api"
STATE_KEY = "goingtocamp_connection"
MAX_MAPS = 200
KINDS = {0: "Camping", 1: "Roofed"}


def unknown(message: str) -> ProviderResponseError:
    return ProviderResponseError(f"Washington State Parks: {message}; availability is unknown.")


def validate_watch_filters(filters: dict | None):
    filters = filters or {}
    if (filters.get("min_people") is not None or str(filters.get("loop") or "").strip()
            or str(filters.get("site_type") or "").strip().casefold() not in {"", "camping", "roofed"}):
        raise unknown("the experimental API cannot verify capacity, loop, or specific accommodation filters. Use Camping or Roofed without those filters")


def identifier(value) -> int:
    try:
        parsed = int(value)
    except (ValueError, TypeError, OverflowError) as exc:
        raise unknown("unrecognized resource identity") from exc
    if (isinstance(value, bool) or not isinstance(value, (str, int))
            or str(value) != str(parsed) or not -(2 ** 31) <= parsed < 2 ** 31):
        raise unknown("unrecognized resource identity")
    return parsed


def localized(record: dict, field: str) -> str:
    values = record.get("localizedValues")
    if not isinstance(values, list):
        raise unknown("missing localized catalog metadata")
    for item in values:
        if isinstance(item, dict) and isinstance(item.get(field), str) and item[field].strip():
            return item[field].strip()
    raise unknown("missing catalog name")


def connection_state(store) -> dict:
    if store is None:
        return {"state": "unverified"}
    raw = store.get_app_settings([STATE_KEY]).get(STATE_KEY)
    if raw is None:
        return {"state": "unverified"}
    try:
        state = json.loads(raw)
        if not isinstance(state, dict) or state.get("state") not in {"unverified", "catalog_loaded", "access_denied", "rate_limited"}:
            raise ValueError("Unknown state")
        if any(key in state and not isinstance(state[key], str) for key in ("message", "checked_at", "retry_at")):
            raise ValueError("Invalid state metadata")
        if state.get("retry_at"):
            deadline = datetime.fromisoformat(state["retry_at"])
            if deadline.tzinfo is None:
                raise ValueError("Missing timezone")
        elif state["state"] == "rate_limited":
            raise ValueError("Missing cooldown")
        return {key: state[key] for key in ("state", "message", "checked_at", "retry_at") if key in state}
    except (ValueError, TypeError):
        return {"state": "access_denied", "message": "Saved API connection state needs review."}


def parse_catalog(locations, categories) -> dict[str, dict]:
    if not isinstance(locations, list) or not locations or not isinstance(categories, list) or not categories:
        raise unknown("incomplete park or accommodation catalog")
    kinds = {}
    seen_categories = set()
    for item in categories:
        if not isinstance(item, dict):
            raise unknown("invalid accommodation catalog")
        category_id = identifier(item.get("resourceCategoryId"))
        if category_id in seen_categories:
            raise unknown("duplicate accommodation identity")
        seen_categories.add(category_id)
        name = localized(item, "name").casefold().replace(" ", "")
        if name in {"campsite", "campsites", "overflow", "overflowsite", "tentsite", "rvsite"}:
            kinds[category_id] = 0
        elif name in {"cabin", "cabins", "yurt", "yurts", "rusticcabin", "deluxecabin", "roofedaccommodation"}:
            kinds[category_id] = 1
    if not {0, 1}.issubset(set(kinds.values())):
        raise unknown("camping and roofed accommodation categories could not both be identified")
    targets = {}
    seen_locations = set()
    for item in locations:
        if not isinstance(item, dict):
            raise unknown("invalid park catalog")
        location_id = identifier(item.get("resourceLocationId"))
        if location_id in seen_locations:
            raise unknown("duplicate park identity")
        seen_locations.add(location_id)
        resource_categories = item.get("resourceCategoryIds")
        if not isinstance(resource_categories, list):
            raise unknown("missing park accommodation categories")
        categories_present = {kinds[value] for raw in resource_categories if (value := identifier(raw)) in kinds}
        if not categories_present:
            continue
        root_map = identifier(item.get("rootMapId"))
        name = localized(item, "fullName")
        for category in sorted(categories_present):
            target_id = f"gtc:wa:{location_id}:{category}"
            target = {"campground_id": target_id, "name": f"{name} - {KINDS[category]}",
                      "park_name": "Washington State Parks", "state_code": "WA", "timezone": "America/Los_Angeles",
                      "poll_interval_minutes": 60, "booking_url": campground_url(target_id), "root_map_id": root_map}
            coordinates = [item.get("latitude"), item.get("longitude")]
            if all(type(value) in (int, float) and math.isfinite(value) for value in coordinates):
                if -90 <= coordinates[0] <= 90 and -180 <= coordinates[1] <= 180:
                    target.update(latitude=coordinates[0], longitude=coordinates[1])
            targets[target_id] = target
    if not targets:
        raise unknown("no supported overnight parks returned")
    return targets


def parse_map(payload, arrival: date, departure: date, map_id: int, location: int, *, daily: bool) -> tuple[dict, set[int]]:
    if not isinstance(payload, dict):
        raise unknown("invalid availability map")
    for key, expected in {"startDate": arrival.isoformat(), "endDate": departure.isoformat(),
                          "mapId": map_id, "resourceLocationId": location}.items():
        if key in payload and str(payload[key]) != str(expected):
            raise unknown("availability response does not match the requested stay")
    resources, links = payload.get("resourceAvailabilities"), payload.get("mapLinkAvailabilities")
    if not isinstance(resources, dict) or not isinstance(links, dict) or len(links) > MAX_MAPS or len(resources) > 10000:
        raise unknown("incomplete availability map")
    expected_count = (departure - arrival).days if daily else 1
    statuses = {}
    for resource, records in resources.items():
        resource_id = identifier(resource)
        if not isinstance(records, list) or len(records) != expected_count:
            raise unknown("availability does not cover the complete requested stay")
        values = []
        for index, record in enumerate(records):
            if not isinstance(record, dict) or type(record.get("availability")) is not int or record["availability"] < 0:
                raise unknown("unrecognized availability status")
            if daily and "date" in record and str(record["date"])[:10] != (arrival + timedelta(days=index)).isoformat():
                raise unknown("daily availability dates are incomplete or out of order")
            values.append(record["availability"])
        statuses[resource_id] = tuple(values)
    return statuses, {identifier(value) for value in links}


class GoingToCampClient:
    def __init__(self, store=None, transport: httpx.AsyncBaseTransport | None = None, request_spacing_seconds: float = 5):
        self.store, self.transport = store, transport
        self.request_spacing_seconds = request_spacing_seconds
        self._request_lock = asyncio.Lock()
        self._catalog_lock = asyncio.Lock()
        self._last_request = 0.0
        self._state = None
        self._catalog = None
        self._catalog_at = 0.0

    async def _save_state(self, state: dict):
        self._state = state
        if self.store is not None:
            await asyncio.to_thread(self.store.set_app_settings, {STATE_KEY: json.dumps(state)})

    async def _check_state(self):
        if self._state is None:
            self._state = await asyncio.to_thread(connection_state, self.store)
        if self._state["state"] == "access_denied":
            raise unknown("API access is stopped after a denial. Resolve provider access, then reset the stop in Sources")
        if self._state["state"] == "rate_limited":
            remaining = (datetime.fromisoformat(self._state["retry_at"]) - datetime.now(UTC)).total_seconds()
            if remaining > 0:
                raise RateLimitError(math.ceil(remaining), "Washington State Parks")
            await self._save_state({"state": "unverified"})

    async def reset_access_stop(self):
        async with self._request_lock:
            if self._catalog_lock.locked():
                raise unknown("a catalog check is still in progress")
            if self._state is None:
                self._state = await asyncio.to_thread(connection_state, self.store)
            if self._state.get("retry_at") and datetime.fromisoformat(self._state["retry_at"]) > datetime.now(UTC):
                raise unknown("the recorded cooldown has not elapsed")
            self._catalog = None
            await self._save_state({"state": "unverified"})

    async def _request(self, path: str, params: dict | None = None, before_request: RequestGate | None = None):
        if path not in {"/resourcelocation", "/resourcecategory", "/availability/map"}:
            raise ValueError("Unsupported Washington API operation")
        async with self._request_lock:
            await self._check_state()
            await asyncio.sleep(max(0, self.request_spacing_seconds - (time.monotonic() - self._last_request)))
            if before_request:
                await before_request("Checking Washington stay" if path == "/availability/map" else "Loading Washington catalog")
            try:
                async with httpx.AsyncClient(timeout=20, transport=self.transport, follow_redirects=False,
                                             headers={"User-Agent": "CampFinder/1.0 (availability monitor)", "Accept": "application/json"}) as client:
                    response = await client.get(BASE_URL + path, params=params)
            except httpx.RequestError as exc:
                raise unknown("API could not be reached") from exc
            finally:
                self._last_request = time.monotonic()
            now = datetime.now(UTC)
            if response.status_code == 429:
                delay = max(3600, _retry_after_seconds(response.headers.get("Retry-After")) or 0)
                await self._save_state({"state": "rate_limited", "checked_at": now.isoformat(),
                                        "retry_at": (now + timedelta(seconds=delay)).isoformat(),
                                        "message": "API rate limit; waiting for provider cooldown."})
                raise RateLimitError(delay, "Washington State Parks")
            if (response.status_code in {401, 403} or 300 <= response.status_code < 400
                    or response.status_code == 200 and "json" not in response.headers.get("content-type", "")):
                await self._save_state({"state": "access_denied", "checked_at": now.isoformat(),
                                        "retry_at": (now + timedelta(hours=1)).isoformat(),
                                        "message": f"API access stopped (HTTP {response.status_code}); manual review required."})
                raise unknown(f"API access stopped (HTTP {response.status_code}); no automatic retry or browser fallback")
            if response.status_code != 200:
                raise unknown(f"API returned HTTP {response.status_code}")
            try:
                if len(response.content) > 8_000_000:
                    raise ValueError("Response too large")
                return response.json()
            except ValueError as exc:
                raise unknown("API returned invalid JSON") from exc

    async def catalog(self, before_request: RequestGate | None = None, *, refresh=False):
        async with self._catalog_lock:
            async with self._request_lock:
                await self._check_state()
                if not refresh and self._catalog is not None and time.monotonic() - self._catalog_at < 86400:
                    return self._catalog
            locations = await self._request("/resourcelocation", before_request=before_request)
            categories = await self._request("/resourcecategory", before_request=before_request)
            catalog = parse_catalog(locations, categories)
            async with self._request_lock:
                # A concurrent stay request may have stopped access while parsing.
                await self._check_state()
                self._catalog, self._catalog_at = catalog, time.monotonic()
                await self._save_state({"state": "catalog_loaded", "checked_at": datetime.now(UTC).isoformat(),
                                        "message": "Park catalog loaded; live stay compatibility is still experimental."})
            return catalog

    async def discover(self):
        catalog = await self.catalog(refresh=True)
        return [{key: value for key, value in target.items() if key != "root_map_id"} for target in catalog.values()]

    async def trip_availability(self, campground_id: str, arrival: date, departure: date,
                                before_request: RequestGate | None = None) -> list[Campsite]:
        location, category = goingtocamp_identity(campground_id)
        if not 1 <= (departure - arrival).days <= 31:
            raise ValueError("Washington stays must be between one and 31 nights")
        catalog = await self.catalog(before_request)
        if campground_id not in catalog:
            raise unknown("saved park/category is absent from the current catalog")
        queue = [(catalog[campground_id]["root_map_id"], ())]
        visited, seen, available, graph = set(), {}, [], {}
        while queue:
            map_id, ancestors = queue.pop(0)
            if map_id in ancestors:
                raise unknown("cyclic campground map hierarchy")
            if map_id in visited:
                continue
            if len(visited) >= MAX_MAPS:
                raise unknown("campground map traversal exceeded its safety limit")
            visited.add(map_id)
            params = {"mapId": map_id, "resourceLocationId": location, "bookingCategoryId": category,
                      "startDate": arrival.isoformat(), "endDate": departure.isoformat(), "isReserving": "true",
                      "getDailyAvailability": "false", "partySize": 1, "filterData": "[]"}
            if category == 0:
                params.update(equipmentCategoryId=-32768, numEquipment=1)
            full = await self._request("/availability/map", params, before_request)
            aggregate, children = parse_map(full, arrival, departure, map_id, location, daily=False)
            params["getDailyAvailability"] = "true"
            days = await self._request("/availability/map", params, before_request)
            daily, daily_children = parse_map(days, arrival, departure, map_id, location, daily=True)
            if set(aggregate) != set(daily) or children != daily_children:
                raise unknown("inventory changed between full-stay and nightly checks")
            graph[map_id] = children
            queue.extend((child, (*ancestors, map_id)) for child in sorted(children))
            for resource_id, statuses in daily.items():
                signature = (aggregate[resource_id], statuses)
                if resource_id in seen:
                    if seen[resource_id] != signature:
                        raise unknown("conflicting duplicate campsite availability")
                    continue
                seen[resource_id] = signature
                if aggregate[resource_id] != (0,) or any(status != 0 for status in statuses):
                    continue
                site_id = f"{campground_id}:{map_id}:{resource_id}"
                # The removed details endpoint cannot establish name, capacity,
                # or eligibility. Keep those unknown rather than invent values.
                available.append(Campsite(site_id, f"Site {resource_id}", "", KINDS[category], None, {},
                                           booking_url=campground_url(campground_id, arrival.isoformat(),
                                                                       departure.isoformat(), campsite_id=site_id)))
        # Shared children can hide cycles from the breadth-first ancestry path.
        checked, checking = set(), set()
        def check_cycle(map_id):
            if map_id in checking:
                raise unknown("cyclic campground map hierarchy")
            if map_id in checked:
                return
            checking.add(map_id)
            for child in graph[map_id]:
                check_cycle(child)
            checking.remove(map_id)
            checked.add(map_id)
        check_cycle(catalog[campground_id]["root_map_id"])
        if not seen:
            raise unknown("no campsite records were returned for the requested category")
        return available
