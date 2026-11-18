"""Native GoingToCamp adapters derived from GoCamp and Camply's search workflows.

Uses the resourceLocation/availability/map contract and Camply's Chrome header
generation with anonymous session cookies. No retired site-details calls.
"""
from __future__ import annotations

import asyncio
import json
import math
import time
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from fake_useragent import UserAgent

from .activenet import RequestGate
from .coordinates import coordinate_pair, location_reference, target_coordinates
from .request_limiter import limited_request
from .provider_errors import ProviderResponseError
from .provider_diagnostics import capture_diagnostic
from .provider_ids import campground_url, goingtocamp_identity
from .provider_registry import GTC_TENANTS, gtc_state_key
from .recreation import Campsite, RateLimitError, _retry_after_seconds


BASE_URL = "https://washington.goingtocamp.com/api"
STATE_KEY = "goingtocamp_connection"
MAX_MAPS = 200
KINDS = {0: "Camping", 1: "Roofed"}


def unknown(message: str) -> ProviderResponseError:
    return ProviderResponseError(f"GoingToCamp: {message}; availability is unknown.")


def validate_watch_filters(filters: dict | None, campground_id: str | None = None):
    filters = filters or {}
    site_type = str(filters.get("site_type") or "").strip().casefold()
    if (filters.get("equipment") or filters.get("vehicle_length_ft") is not None
            or filters.get("min_people") is not None or str(filters.get("loop") or "").strip()
            or str(filters.get("site") or "").strip() or site_type not in {"", "camping", "roofed"}):
        raise unknown("the API cannot verify equipment, length, site names, capacity, loop, or specific accommodation filters. Select Camping or Roofed targets and leave these filters empty")
    if campground_id and site_type and site_type != KINDS[goingtocamp_identity(campground_id)[1]].casefold():
        raise unknown("the site-type filter does not match this target's Camping or Roofed category")


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
    values = sorted(values, key=lambda item: 0 if isinstance(item, dict) and str(item.get("cultureCode", item.get("culture", ""))).startswith("en") else 1)
    for item in values:
        if isinstance(item, dict) and isinstance(item.get(field), str) and item[field].strip():
            return item[field].strip()
    raise unknown("missing catalog name")


def connection_state(store, tenant="wa") -> dict:
    if store is None:
        return {"state": "unverified"}
    key = gtc_state_key(tenant)
    raw = store.get_app_settings([key]).get(key)
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


def parse_catalog(locations, categories, tenant="wa") -> dict[str, dict]:
    config = GTC_TENANTS[tenant]
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
    if not set(config["categories"]).issubset(set(kinds.values())):
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
        categories_present = {kinds[value] for raw in resource_categories if (value := identifier(raw)) in kinds} & set(config["categories"])
        if not categories_present:
            continue
        root_map = identifier(item.get("rootMapId"))
        name = localized(item, "fullName")
        timezone = item.get("ianaTimeZone") or config["timezone"]
        try:
            ZoneInfo(timezone)
        except (ZoneInfoNotFoundError, TypeError, ValueError) as exc:
            raise unknown("invalid park timezone") from exc
        for category in sorted(categories_present):
            target_id = f"gtc:{tenant}:{location_id}:{category}"
            target = {"campground_id": target_id, "name": f"{name} - {KINDS[category]}",
                      "park_name": config["name"], "state_code": config["state"], "timezone": timezone,
                      "poll_interval_minutes": 60, "booking_url": campground_url(target_id), "root_map_id": root_map}
            coordinates = coordinate_pair(item.get("latitude"), item.get("longitude"))
            # Camis also publishes a decimal latitude/longitude pair as one field.
            if coordinates is None and isinstance(item.get("gpsCoordinates"), str):
                parts = item["gpsCoordinates"].split(",")
                if len(parts) == 2:
                    coordinates = coordinate_pair(*parts)
            coordinates = coordinates or target_coordinates(target)
            if coordinates:
                target.update(latitude=coordinates[0], longitude=coordinates[1])
                target.update(location_reference(target))
            targets[target_id] = target
    if not targets:
        raise unknown("no supported overnight parks returned")
    return targets


def parse_map(payload, arrival: date, departure: date, map_id: int, location: int, category: int) -> tuple[dict, set[int]]:
    if not isinstance(payload, dict):
        raise unknown("invalid availability map")
    for key, expected in {"startDate": arrival.isoformat(), "endDate": departure.isoformat(),
                          "mapId": map_id, "resourceLocationId": location, "bookingCategoryId": category}.items():
        if key in payload and str(payload[key]) != str(expected):
            raise unknown("availability response does not match the requested stay")
    resources, links = payload.get("resourceAvailabilities"), payload.get("mapLinkAvailabilities")
    if not isinstance(resources, dict) or not isinstance(links, dict) or len(links) > MAX_MAPS or len(resources) > 10000:
        raise unknown("incomplete availability map")
    statuses = {}
    for resource, records in resources.items():
        resource_id = identifier(resource)
        if not isinstance(records, list) or len(records) != 1:
            raise unknown("availability does not cover the complete requested stay")
        record = records[0]
        if not isinstance(record, dict) or type(record.get("availability")) is not int or record["availability"] < 0:
            raise unknown("unrecognized availability status")
        statuses[resource_id] = record["availability"]
    return statuses, {identifier(value) for value in links}


class GoingToCampClient:
    def __init__(self, store=None, transport: httpx.AsyncBaseTransport | None = None, request_spacing_seconds: float = 5, *, tenant="wa"):
        self.tenant, self.config = tenant, GTC_TENANTS[tenant]
        self.state_key = gtc_state_key(tenant)
        self.store, self.transport = store, transport
        self.request_spacing_seconds = request_spacing_seconds
        self._request_lock = asyncio.Lock()
        self._catalog_lock = asyncio.Lock()
        self._last_request = 0.0
        self._state = None
        self._catalog = None
        self._catalog_at = 0.0
        self._user_agents = UserAgent(browsers=["chrome"])
        self._cookies = httpx.Cookies()

    async def _save_state(self, state: dict):
        self._state = state
        if self.store is not None:
            await asyncio.to_thread(self.store.set_app_settings, {self.state_key: json.dumps(state)})

    async def _check_state(self):
        if self._state is None:
            self._state = await asyncio.to_thread(connection_state, self.store, self.tenant)
        if self._state["state"] == "access_denied":
            raise unknown("API access is stopped after a denial. Resolve provider access, then reset the stop in Sources")
        if self._state["state"] == "rate_limited":
            remaining = (datetime.fromisoformat(self._state["retry_at"]) - datetime.now(UTC)).total_seconds()
            if remaining > 0:
                raise RateLimitError(math.ceil(remaining), self.config["name"])
            await self._save_state({"state": "unverified"})

    async def reset_access_stop(self):
        async with self._request_lock:
            if self._catalog_lock.locked():
                raise unknown("a catalog check is still in progress")
            if self._state is None:
                self._state = await asyncio.to_thread(connection_state, self.store, self.tenant)
            if self._state.get("retry_at") and datetime.fromisoformat(self._state["retry_at"]) > datetime.now(UTC):
                raise unknown("the recorded cooldown has not elapsed")
            self._catalog = None
            self._cookies = httpx.Cookies()
            await self._save_state({"state": "unverified"})

    async def ensure_access(self):
        """Check persisted access state before serving scanner-cached results."""
        async with self._request_lock:
            await self._check_state()

    @limited_request()
    async def _request(self, path: str, params: dict | None = None, before_request: RequestGate | None = None):
        if path not in {"/resourceLocation", "/resourcecategory", "/availability/map"}:
            raise ValueError("Unsupported Washington API operation")
        async with self._request_lock:
            await self._check_state()
            await asyncio.sleep(max(0, self.request_spacing_seconds - (time.monotonic() - self._last_request)))
            if before_request:
                await before_request(f"{self.config['name']}: " + ("checking stay" if path == "/availability/map" else "loading catalog"))
            started = time.monotonic()

            async def record(outcome, response=None, error=None):
                await asyncio.to_thread(capture_diagnostic, self.store, path, params, time.monotonic() - started,
                                        outcome=outcome, response=response, error=error, tenant=self.tenant)
            try:
                async with httpx.AsyncClient(timeout=20, transport=self.transport, follow_redirects=False,
                                             cookies=self._cookies,
                                             headers={"User-Agent": self._user_agents.random,
                                                      "Accept-Language": "en-US,en;q=0.9"}) as client:
                    response = await client.get(f"https://{self.config['host']}/api" + path, params=params)
                    self._cookies = client.cookies
            except httpx.RequestError as exc:
                await record("transport_error", error=exc)
                raise unknown("API could not be reached") from exc
            finally:
                self._last_request = time.monotonic()
            now = datetime.now(UTC)
            if response.status_code == 429:
                delay = max(3600, _retry_after_seconds(response.headers.get("Retry-After")) or 0)
                await self._save_state({"state": "rate_limited", "checked_at": now.isoformat(),
                                        "retry_at": (now + timedelta(seconds=delay)).isoformat(),
                                        "message": "API rate limit; waiting for provider cooldown."})
                await record("rate_limited", response)
                raise RateLimitError(delay, self.config["name"])
            if (response.status_code in {401, 403} or 300 <= response.status_code < 400
                    or response.status_code == 200 and "json" not in response.headers.get("content-type", "")):
                await self._save_state({"state": "access_denied", "checked_at": now.isoformat(),
                                        "retry_at": (now + timedelta(hours=1)).isoformat(),
                                        "message": f"API access stopped (HTTP {response.status_code}); manual review required."})
                await record("access_denied", response)
                raise unknown(f"API access stopped (HTTP {response.status_code}); no automatic retry or browser fallback")
            if response.status_code != 200:
                await record("http_error", response)
                raise unknown(f"API returned HTTP {response.status_code}")
            if len(response.content) > 8_000_000:
                await record("response_too_large", response)
                raise unknown("API response exceeded the size limit")
            try:
                payload = response.json()
            except ValueError as exc:
                await record("invalid_json", response)
                raise unknown("API returned invalid JSON") from exc
            await record("json_response", response)
            return payload

    async def catalog(self, before_request: RequestGate | None = None, *, refresh=False):
        async with self._catalog_lock:
            async with self._request_lock:
                await self._check_state()
                if not refresh and self._catalog is not None and time.monotonic() - self._catalog_at < 86400:
                    return self._catalog
            locations = await self._request("/resourceLocation", before_request=before_request)
            categories = await self._request("/resourcecategory", before_request=before_request)
            catalog = parse_catalog(locations, categories, self.tenant)
            async with self._request_lock:
                # A concurrent stay request may have stopped access while parsing.
                await self._check_state()
                self._catalog, self._catalog_at = catalog, time.monotonic()
                await self._save_state({"state": "catalog_loaded", "checked_at": datetime.now(UTC).isoformat(),
                                        "message": "Overnight catalog loaded. Watches check exact-stay availability."})
            if self.store:
                await asyncio.to_thread(self.store.fill_missing_target_coordinates, list(catalog.values()))
            return catalog

    async def discover(self):
        catalog = await self.catalog(refresh=True)
        return [{key: value for key, value in target.items() if key != "root_map_id"} for target in catalog.values()]

    async def trip_availability(self, campground_id: str, arrival: date, departure: date,
                                before_request: RequestGate | None = None) -> list[Campsite]:
        location, category = goingtocamp_identity(campground_id)
        if campground_id.split(":")[1] != self.tenant or category not in self.config["categories"]:
            raise unknown("target does not match this provider's supported categories")
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
            # Exact-stay status includes the requested departure and booking rules.
            # Daily calendar statuses are not occupied-night inventory: requiring
            # each day to be reservable incorrectly rejects valid cabin stays.
            aggregate, children = parse_map(full, arrival, departure, map_id, location, category)
            graph[map_id] = children
            queue.extend((child, (*ancestors, map_id)) for child in sorted(children))
            for resource_id, status in aggregate.items():
                if resource_id in seen:
                    if seen[resource_id] != status:
                        raise unknown("conflicting duplicate campsite availability")
                    continue
                seen[resource_id] = status
                if status != 0:
                    continue
                # A resource may be returned on both parent and leaf maps. Keep
                # its result identity stable; the booking URL still uses the leaf.
                site_id = f"{campground_id}:{catalog[campground_id]['root_map_id']}:{resource_id}"
                booking_site_id = f"{campground_id}:{map_id}:{resource_id}"
                # The removed details endpoint cannot establish name, capacity,
                # or eligibility. Keep those unknown rather than invent values.
                available.append(Campsite(site_id, f"Site {resource_id}", "", KINDS[category], None, {},
                                           booking_url=campground_url(campground_id, arrival.isoformat(),
                                                                       departure.isoformat(), campsite_id=booking_site_id)))
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
