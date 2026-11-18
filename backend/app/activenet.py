"""King County's public catalog and availability queries, never reservation writes."""
from __future__ import annotations

import asyncio
import re
import time
from collections.abc import Awaitable, Callable
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
from dateutil.relativedelta import relativedelta

from .provider_errors import ProviderResponseError
from .request_limiter import limited_request
from .provider_ids import campground_url
from .recreation import Campsite, RateLimitError, _retry_after_seconds


BASE_URL = "https://anc.apm.activecommunities.com/kingcountyparks/rest/reservation/resource"
CAMPGROUND_ID = "activenet:king:66"
RequestGate = Callable[[str], Awaitable[None]]


def local_today() -> date:
    return datetime.now(ZoneInfo("America/Los_Angeles")).date()


def stay_allowed(arrival: date, departure: date) -> bool:
    # King County camping policy, reviewed 2026-11-17. These constraints are
    # not all enforced by the public calendar's Available/Unavailable response.
    today = local_today()
    return (2 <= (departure - arrival).days <= 7
            and arrival >= today + timedelta(days=5)
            and arrival <= today + relativedelta(years=1)
            and date(arrival.year, 4, 1) <= arrival <= date(arrival.year, 10, 31)
            and departure <= date(arrival.year, 11, 1))


def response_body(payload: object) -> dict:
    if (not isinstance(payload, dict) or not isinstance(payload.get("headers"), dict)
            or payload["headers"].get("response_code") != "0000" or not isinstance(payload.get("body"), dict)):
        raise ProviderResponseError("King County returned an unsuccessful or unrecognized response; availability is unknown.")
    return payload["body"]


def reservation_allowed(payload: object, site_id: int, arrival: date, departure: date) -> bool:
    detail = response_body(payload).get("resource_detail")
    general = detail.get("general_information") if isinstance(detail, dict) else None
    if (not isinstance(general, dict) or general.get("facility_id") != site_id or general.get("center_id") != 66
            or general.get("reservation_period_unit") != 8 or general.get("reserve_by") != "overnight"
            or not isinstance(general.get("minimum_time"), int) or not isinstance(general.get("maximum_time"), int)
            or not isinstance(general.get("no_internet_permits"), bool)):
        raise ProviderResponseError("King County overnight reservation rules changed; availability is unknown.")
    restrictions = detail.get("advanced_restrictions")
    if not isinstance(restrictions, list):
        raise ProviderResponseError("King County did not return reservation window restrictions.")
    # Booking lead times are only published as generated text in this response.
    # Require both resident/non-resident rules instead of assuming their values.
    windows = {}
    pattern = (r"(Residents|Non-residents) can make reservations at least (\d+) day\(s\) in advance "
               r"but not more than (\d+) day\(s\) in advance and which extend out to a maximum of (\d+) day\(s\)\.")
    for rule in restrictions:
        if not isinstance(rule, str):
            raise ProviderResponseError("King County returned unrecognized reservation restrictions.")
        match = re.fullmatch(pattern, rule)
        if match:
            windows[match[1]] = tuple(int(match[i]) for i in (2, 3, 4))
    if set(windows) != {"Residents", "Non-residents"}:
        raise ProviderResponseError("King County booking windows could not be verified; availability is unknown.")
    lead_days = (arrival - local_today()).days
    nights = (departure - arrival).days
    return (not general["no_internet_permits"]
            and general["minimum_time"] <= nights <= general["maximum_time"]
            and all(low <= lead_days <= high and nights <= length for low, high, length in windows.values()))


def parse_availability(payload: object, inventory: list[dict], arrival: date, departure: date) -> list[Campsite]:
    facilities = response_body(payload).get("facilities")
    expected = {item["id"]: item for item in inventory}
    if not isinstance(facilities, list) or not expected:
        raise ProviderResponseError("King County did not return a complete availability response.")
    seen = set()
    sites = []
    for facility in facilities:
        if not isinstance(facility, dict):
            raise ProviderResponseError("King County availability format changed.")
        site_id = facility.get("facility_id")
        status = facility.get("availability")
        if (not isinstance(site_id, int) or site_id not in expected or site_id in seen or not isinstance(status, str)
                or status not in {"Available", "Unavailable", "Partial"}):
            raise ProviderResponseError("King County returned an unknown site or availability status.")
        seen.add(site_id)
        if status != "Available":
            continue
        item = expected[site_id]
        kind = item["type_name"]
        if "group" in kind.lower():
            last_may_day = date(arrival.year, 5, 31)
            memorial_weekend = last_may_day - timedelta(days=last_may_day.weekday() + 3)
            if arrival < memorial_weekend:
                continue
        # The provider combines yurts/container under one type. Keep filters
        # faithful to the actual accommodation instead of calling both yurts.
        if item["name"].lower().startswith("yurt "):
            kind = "Yurt"
        elif item["name"] == "Camping Container":
            kind = "Camping Container"
        elif "tent" in item["name"].lower():
            kind = f"Tent - {kind}"
        campsite_id = f"activenet:king:{site_id}"
        sites.append(Campsite(campsite_id, item["name"], "", kind, item["max_capacity"], {},
                              booking_url=campground_url(CAMPGROUND_ID, campsite_id=campsite_id)))
    if seen != set(expected):
        raise ProviderResponseError("King County omitted requested sites; availability is unknown.")
    return sites


class KingCountyClient:
    def __init__(self, transport: httpx.AsyncBaseTransport | None = None, request_spacing_seconds: float = 5):
        self.transport = transport
        self.request_spacing_seconds = request_spacing_seconds
        self._last_request = 0.0
        self._lock = asyncio.Lock()
        self._inventory_lock = asyncio.Lock()
        self._inventory: list[dict] = []
        self._inventory_at = 0.0
        self._center_name = "Tolt MacDonald Park & Campground"
        self._details: dict[int, tuple[float, dict]] = {}

    @limited_request("king")
    async def _request(self, path: str, payload: dict | None = None, before_request: RequestGate | None = None) -> dict:
        # Serialize discovery and scans too. Public metadata pagination should
        # not produce a burst ahead of the scanner's configured request spacing.
        async with self._lock:
            await asyncio.sleep(max(0, self.request_spacing_seconds - (time.monotonic() - self._last_request)))
            if before_request:
                stage = "Checking campsite rules" if path.startswith("/detail/") else "Checking stay availability" if path == "/facilitiesavailability" else "Loading campground catalog"
                await before_request(stage)
            try:
                async with httpx.AsyncClient(timeout=30, transport=self.transport, follow_redirects=False,
                                             headers={"User-Agent": "CampFinder/1.0 (availability monitor)"}) as client:
                    url = BASE_URL + path
                    response = (await client.get(url, params={"locale": "en-US"}) if payload is None else
                                await client.post(url, params={"locale": "en-US"}, json=payload))
            except httpx.RequestError as exc:
                raise ProviderResponseError("King County could not be reached; availability is unknown.") from exc
            finally:
                self._last_request = time.monotonic()
        if response.status_code == 429:
            raise RateLimitError(_retry_after_seconds(response.headers.get("Retry-After")), "King County Parks")
        if response.status_code != 200:
            raise ProviderResponseError(f"King County returned HTTP {response.status_code}. No automatic retry or access workaround was attempted.")
        try:
            data = response.json()
        except ValueError as exc:
            raise ProviderResponseError("King County returned a web page instead of availability data.") from exc
        response_body(data)
        return data

    async def inventory(self, before_request: RequestGate | None = None, refresh: bool = False) -> list[dict]:
        async with self._inventory_lock:
            if not refresh and self._inventory and time.monotonic() - self._inventory_at < 86400:
                return self._inventory
            options = response_body(await self._request("/option/filteroptions", before_request=before_request))
            types = options.get("facility_types")
            if not isinstance(types, list):
                raise ProviderResponseError("King County's campground category list changed.")
            type_ids = [item["id"] for item in types if isinstance(item, dict) and isinstance(item.get("id"), int)
                        and str(item.get("text", "")).startswith("Campground (")]
            if not type_ids:
                raise ProviderResponseError("King County did not return overnight campground categories.")
            start, search_id, expected_total = 0, "", None
            records: dict[int, dict] = {}
            for _ in range(50):
                payload = {
                    "name": "", "attendee": 0, "date_times": [], "event_type_ids": [], "facility_type_ids": type_ids,
                    "reservation_group_ids": [], "amenity_ids": [], "facility_id": 0, "equipment_id": 0,
                    "center_id": 66, "resource_type": 0, "client_coordinate": "", "order_by_field": "name",
                    "order_direction": "asc", "page_size": 20, "start_index": start, "search_client_id": search_id,
                    "date_time_length": None, "full_day_booking": False, "center_ids": [66],
                    "specify_start_and_end_times": False,
                }
                body = response_body(await self._request("", payload, before_request))
                items, total, next_start = body.get("items"), body.get("total"), body.get("next_start_index")
                if (not isinstance(items, list) or not isinstance(total, int) or total <= 0 or total > 1000
                        or body.get("too_many_resources") is not False
                        or (expected_total is not None and total != expected_total)):
                    raise ProviderResponseError("King County's campground catalog is incomplete or changed during discovery.")
                expected_total = total
                for item in items:
                    if (not isinstance(item, dict) or not isinstance(item.get("id"), int) or item["id"] <= 0
                            or item["id"] in records or item.get("center_id") != 66 or item.get("type_id") not in type_ids
                            or item.get("reserve_by") != "overnight" or item.get("reservation_unit_id") != 8
                            or any(not isinstance(item.get(key), str) or not item[key].strip()
                                   for key in ("name", "type_name", "center_name"))
                            or not isinstance(item.get("max_capacity"), int) or item["max_capacity"] <= 0
                            or not isinstance(item.get("no_internet_permits"), bool)):
                        raise ProviderResponseError("King County returned unrecognized overnight campsite metadata.")
                    records[item["id"]] = item
                if len(records) == total:
                    break
                if not items or not isinstance(next_start, int) or next_start <= start or not body.get("search_client_id"):
                    raise ProviderResponseError("King County's campground catalog pagination is incomplete.")
                start, search_id = next_start, body["search_client_id"]
            else:
                raise ProviderResponseError("King County's campground catalog exceeded the discovery limit.")
            inventory = [item for item in records.values() if not item["no_internet_permits"]]
            if not inventory:
                raise ProviderResponseError("King County did not return online-reservable overnight campsites.")
            self._inventory = inventory
            self._center_name = inventory[0]["center_name"]
            self._inventory_at = time.monotonic()
            return inventory

    async def discover(self) -> list[dict]:
        await self.inventory(refresh=True)
        return [{"campground_id": CAMPGROUND_ID, "name": self._center_name, "park_name": "King County Parks",
                 "state_code": "WA", "timezone": "America/Los_Angeles", "poll_interval_minutes": 60,
                 # Address point linked from King County's official camping page.
                 "latitude": 47.6451577, "longitude": -121.9216052,
                 "booking_url": campground_url(CAMPGROUND_ID)}]

    async def trip_availability(self, campground_id: str, arrival: date, departure: date,
                                before_request: RequestGate | None = None) -> list[Campsite]:
        if campground_id != CAMPGROUND_ID:
            raise ValueError("Only Tolt-MacDonald has verified King County overnight coverage.")
        if not stay_allowed(arrival, departure):
            return []
        inventory = await self.inventory(before_request)
        # Match the public overnight map search, not a union of individual days.
        payload = {"facility_ids": [item["id"] for item in inventory],
                   "datetime_periods": [{"from_date_time": f"{arrival.isoformat()} 23:59:00",
                                         "to_date_time": f"{departure.isoformat()} 00:00:00"}],
                   "datetime_length": {"hours_per_day": -1, "start_time": "", "dates": []}, "reservation_unit": 8}
        response = await self._request("/facilitiesavailability", payload, before_request)
        candidates = parse_availability(response, inventory, arrival, departure)
        sites = []
        for site in candidates:
            site_id = int(site.campsite_id.split(":")[-1])
            cached = self._details.get(site_id)
            if cached and time.monotonic() - cached[0] < 86400:
                detail = cached[1]
            else:
                detail = await self._request(f"/detail/{site_id}", before_request=before_request)
            allowed = reservation_allowed(detail, site_id, arrival, departure)
            self._details[site_id] = (cached[0] if cached and detail is cached[1] else time.monotonic(), detail)
            if allowed:
                sites.append(site)
        return sites
