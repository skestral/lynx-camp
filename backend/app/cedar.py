"""Read-only Skagit County calendar queries. No account, hold, or booking writes."""
from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from uuid import UUID
from zoneinfo import ZoneInfo

import httpx

from .provider_errors import ProviderResponseError
from .provider_ids import campground_url
from .recreation import Campsite, RateLimitError, _retry_after_seconds


BASE_URL = "https://hasura-production-07um.onrender.com/v1/graphql"
CAMPGROUND_ID = "cedar:skagit:hmsp"
FACILITY_ID = "e43b2789-e411-426f-9d75-b53a499c11ba"
ORGANIZATION_ID = "f667d1c8-0053-4acf-b69e-bd0ac44a7373"
TIMEZONE = ZoneInfo("America/Los_Angeles")
RequestGate = Callable[[str], Awaitable[None]]

CATALOG_QUERY = """query FetchFacilityCore($facilityId: uuid!) {
  facility: facilities_by_pk(id: $facilityId) {
    id organization_id title type is_hidden_from_public archived_at
  }
}"""

# Deliberately omit bookings, customers, and checkout holds from this public query.
AVAILABILITY_QUERY = """query GetAvailableNightlyFacilitiesAndVenues($input_object: GetAvailableNightlyFacilitiesAndVenuesInput!, $facilityId: uuid!) {
  facility: facilities_by_pk(id: $facilityId) {
    id organization_id title type is_hidden_from_public archived_at
  }
  getAvailableNightlyFacilitiesAndVenues(input_object: $input_object) {
    results {
      info { id title type is_hidden_from_public settings
        facility_booking_info_overrides {
          id facility_id organization_id override_condition override_min_booking_time
          override_min_booking_time_units override_start_date override_end_date
        }
      }
      venues {
        info { id facility_id organization_id name type capacity is_hidden_from_public settings requires_household_members }
        venue_portions {
          info { id venue_id organization_id name type capacity user_booking_info_id
            venue_portion_to_user_booking_info {
              id min_booking_time min_booking_time_units max_booking_time max_booking_time_units max_bookings_per_day
              user_booking_info_overrides {
                id organization_id user_booking_info_id override_condition override_min_booking_time
                override_min_booking_time_units override_max_booking_time override_max_booking_time_units
                override_start_date override_end_date
              }
            }
          }
          available_dates all_dates_available all_dates_available_or_pending
        }
      }
    }
    total_venue_portions has_more next_offset
  }
}"""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ProviderResponseError(f"Skagit County {message}; availability is unknown.")


def local_today() -> date:
    return datetime.now(TIMEZONE).date()


def valid_uuid(value: object) -> bool:
    try:
        return isinstance(value, str) and str(UUID(value)) == value
    except ValueError:
        return False


def number(value: object, *, nullable: bool = False) -> int | None:
    require((nullable and value is None) or (type(value) is int and value >= 0), "returned an invalid booking limit")
    return value


def flag(settings: dict, key: str, *, optional: bool = False) -> bool:
    value = settings.get(key, False if optional else None)
    require(type(value) is bool, "returned an unrecognized booking setting")
    return value


@lru_cache(maxsize=1)
def holiday_calendar() -> dict:
    return json.loads(Path(__file__).with_name("cedar_holidays.json").read_text(encoding="utf-8"))["years"]


def is_holiday(day: date) -> bool:
    dates = holiday_calendar().get(str(day.year))
    require(isinstance(dates, list), "holiday rules need a calendar update for this year")
    return day.isoformat() in dates


def stay_allowed(arrival: date, departure: date) -> bool:
    # The county's published release policy opens each calendar year in January.
    # Do not report next-year empty cells as released inventory before then.
    today = local_today()
    return (1 <= (departure - arrival).days <= 14 and arrival > today
            and arrival.year == today.year and departure <= date(today.year + 1, 1, 1))


def query_window(arrival: date, departure: date) -> dict:
    start = datetime.combine(arrival, datetime.min.time(), TIMEZONE).astimezone(UTC)
    end = datetime.combine(departure, datetime.min.time(), TIMEZONE).astimezone(UTC) - timedelta(milliseconds=1)
    return {"iso_start_datetime": start.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "iso_end_datetime": end.isoformat(timespec="milliseconds").replace("+00:00", "Z")}


def validate_facility(info: object, *, catalog: bool = True) -> dict:
    require(isinstance(info, dict), "omitted the campground")
    require(info.get("id") == FACILITY_ID and info.get("type") == "CAMPGROUND" and info.get("is_hidden_from_public") is False
            and isinstance(info.get("title"), str) and bool(info["title"].strip()), "returned an unrecognized or closed campground")
    if catalog:
        require(info.get("organization_id") == ORGANIZATION_ID and "archived_at" in info and info["archived_at"] is None,
                "returned an unrecognized or archived campground")
    return info


def duration(rule: dict, key: str, *, nullable: bool = False) -> int | None:
    require(key in rule and f"{key}_units" in rule, "omitted a stay-length rule")
    value = number(rule[key], nullable=nullable)
    require(rule[f"{key}_units"] == ("DAY" if value is not None else None), "returned unsupported stay-length units")
    return value


def override_minimum(overrides: object, arrival: date, departure: date, parent_key: str, parent_id: str) -> int:
    require(isinstance(overrides, list), "omitted booking-rule overrides")
    minimum = 0
    for rule in overrides:
        require(isinstance(rule, dict) and valid_uuid(rule.get("id")) and rule.get(parent_key) == parent_id
                and rule.get("organization_id") == ORGANIZATION_ID, "returned an unrecognized booking override")
        require(rule.get("override_condition") in {"WEEKEND", "HOLIDAY"}
                and "override_start_date" in rule and rule["override_start_date"] is None
                and "override_end_date" in rule and rule["override_end_date"] is None,
                "returned a booking override that needs review")
        value = duration(rule, "override_min_booking_time")
        if "override_max_booking_time" in rule:
            require(duration(rule, "override_max_booking_time", nullable=True) is None,
                    "returned a new maximum-stay override")
        # Apply declared minimums conservatively to any occupied night. Checkout
        # is not occupied and must not trigger a holiday/weekend restriction.
        days = [arrival + timedelta(days=i) for i in range((departure - arrival).days)]
        applies = any(day.weekday() in {4, 5} if rule["override_condition"] == "WEEKEND" else is_holiday(day) for day in days)
        if applies:
            minimum = max(minimum, value)
    return minimum


def reservation_allowed(facility: dict, venue: dict, portion: dict, arrival: date, departure: date) -> bool:
    settings, own = facility.get("settings"), venue.get("settings")
    require(isinstance(settings, dict) and isinstance(own, dict), "omitted campground booking settings")

    def effective(override: str, key: str, *, optional: bool = False):
        # Older site records omit override flags; Cedar inherits the facility
        # setting in that case. An explicitly malformed flag still fails closed.
        selected = own if flag(own, override, optional=True) else settings
        require(key in selected or optional, "omitted an inherited booking rule")
        return selected.get(key, False)

    min_lead = number(effective("overrideFacilityMinDaysInAdvance", "minDaysInAdvance"), nullable=True)
    max_lead = number(effective("overrideFacilityMaxDaysInAdvance", "maxDaysInAdvance"), nullable=True)
    resident_only = effective("overrideFacilityResidentOnlyBookingSetting", "enableResidentOnlyBookingSetting")
    call_only = effective("overrideFacilityCallToBookSetting", "enableCallToBookSetting", optional=True)
    weekend_minimum = effective("overrideFacilityWeekendsHolidaysSettings", "requireMinimumStayWeekendsHolidays")
    require(all(type(value) is bool for value in (resident_only, call_only, weekend_minimum)), "returned invalid eligibility rules")
    require(type(venue.get("requires_household_members")) is bool, "omitted campsite eligibility")
    rule = portion.get("venue_portion_to_user_booking_info")
    require(isinstance(rule, dict) and valid_uuid(rule.get("id")) and rule["id"] == portion.get("user_booking_info_id"),
            "omitted campsite stay rules")
    minimum, maximum = duration(rule, "min_booking_time"), duration(rule, "max_booking_time", nullable=True)
    require("max_bookings_per_day" in rule and rule["max_bookings_per_day"] is None,
            "returned a per-day booking restriction that needs review")
    minimum = max(minimum, override_minimum(facility.get("facility_booking_info_overrides"), arrival, departure, "facility_id", FACILITY_ID),
                  override_minimum(rule.get("user_booking_info_overrides"), arrival, departure, "user_booking_info_id", rule["id"]))
    if weekend_minimum and (arrival.weekday() in {4, 5} or is_holiday(arrival)):
        minimum = max(minimum, 2)
    limit_settings = own if flag(own, "overrideFacilityMaxConsecutiveDaysSettings", optional=True) else settings
    unlimited = flag(limit_settings, "noLimitConsecutiveNights")
    consecutive = number(limit_settings.get("maxConsecutiveNightsLimit"), nullable=unlimited)
    nights, lead = (departure - arrival).days, (arrival - local_today()).days
    checkout_allowed = effective("overrideFacilityMaxDaysInAdvance", "allowCheckoutBeyondMaxDaysInAdvance")
    require(type(checkout_allowed) is bool, "omitted the checkout-window rule")
    return (not resident_only and not call_only and not venue["requires_household_members"]
            and lead >= (min_lead or 0) and (max_lead is None or (lead <= max_lead and (checkout_allowed or lead + nights <= max_lead)))
            and nights >= minimum and (maximum is None or nights <= maximum)
            and (unlimited or nights <= consecutive))


def parse_venue(venue: object, facility: dict, arrival: date, departure: date) -> tuple[str, str, Campsite | None]:
    require(isinstance(venue, dict) and isinstance(venue.get("info"), dict), "returned an invalid campsite")
    info, portions = venue["info"], venue.get("venue_portions")
    require(valid_uuid(info.get("id")) and info.get("organization_id") == ORGANIZATION_ID and info.get("facility_id") == FACILITY_ID
            and info.get("type") == "CAMPSITE" and type(info.get("is_hidden_from_public")) is bool
            and isinstance(info.get("name"), str) and bool(info["name"].strip())
            and isinstance(portions, list) and len(portions) == 1, "returned an unrecognized campsite layout")
    portion = portions[0]
    require(isinstance(portion, dict) and isinstance(portion.get("info"), dict), "omitted campsite identity")
    unit = portion["info"]
    require(valid_uuid(unit.get("id")) and unit.get("venue_id") == info["id"] and unit.get("organization_id") == ORGANIZATION_ID
            and unit.get("type") == "CAMPSITE", "returned mismatched campsite identities")
    dates = portion.get("available_dates")
    nights = {(arrival + timedelta(days=i)).isoformat() for i in range((departure - arrival).days)}
    require(isinstance(dates, list) and all(isinstance(day, str) for day in dates)
            and len(set(dates)) == len(dates) and set(dates) <= nights
            and type(portion.get("all_dates_available")) is bool and type(portion.get("all_dates_available_or_pending")) is bool
            and portion["all_dates_available"] == (set(dates) == nights)
            and (not portion["all_dates_available"] or portion["all_dates_available_or_pending"]),
            "returned incomplete or contradictory stay dates")
    capacity = unit.get("capacity") if unit.get("capacity") is not None else info.get("capacity")
    require(type(capacity) is int and capacity > 0, "omitted campsite capacity")
    site = None
    if not info["is_hidden_from_public"]:
        allowed = reservation_allowed(facility, info, unit, arrival, departure)
        if allowed and portion["all_dates_available"]:
            name = info["name"].strip()
            kind = next((label for word, label in (("cabin", "Cabin"), ("adirondack", "Adirondack shelter"), ("tent", "Tent"), ("rv", "RV"))
                         if word in name.lower()), "Campsite")
            site = Campsite(f"cedar:skagit:{unit['id']}", name, "", kind, capacity, {}, booking_url=campground_url(CAMPGROUND_ID))
    return info["id"], unit["id"], site


class SkagitCountyClient:
    def __init__(self, transport: httpx.AsyncBaseTransport | None = None, request_spacing_seconds: float = 5):
        self.transport = transport
        self.request_spacing_seconds = request_spacing_seconds
        self._last_request = 0.0
        self._lock = asyncio.Lock()

    async def _request(self, operation: str, query: str, variables: dict, before_request: RequestGate | None = None) -> dict:
        async with self._lock:
            await asyncio.sleep(max(0, self.request_spacing_seconds - (time.monotonic() - self._last_request)))
            if before_request:
                await before_request("Checking campground availability page" if operation.startswith("GetAvailable") else "Loading campground catalog")
            try:
                async with httpx.AsyncClient(timeout=30, transport=self.transport, follow_redirects=False,
                                             headers={"User-Agent": "CampFinder/1.0 (availability monitor)"}) as client:
                    response = await client.post(BASE_URL, json={"operationName": operation, "query": query, "variables": variables})
            except httpx.RequestError as exc:
                raise ProviderResponseError("Skagit County could not be reached; availability is unknown.") from exc
            finally:
                self._last_request = time.monotonic()
        if response.status_code == 429:
            raise RateLimitError(_retry_after_seconds(response.headers.get("Retry-After")), "Skagit County Parks")
        require(response.status_code == 200, f"returned HTTP {response.status_code}. No automatic retry or access workaround was attempted")
        try:
            payload = response.json()
        except ValueError as exc:
            raise ProviderResponseError("Skagit County returned a web page instead of calendar data.") from exc
        require(isinstance(payload, dict) and not payload.get("errors") and isinstance(payload.get("data"), dict),
                "returned an unsuccessful calendar response")
        return payload["data"]

    async def discover(self) -> list[dict]:
        info = validate_facility((await self._request("FetchFacilityCore", CATALOG_QUERY, {"facilityId": FACILITY_ID})).get("facility"))
        return [{"campground_id": CAMPGROUND_ID, "name": info["title"], "park_name": "Skagit County Parks", "state_code": "WA",
                 "timezone": "America/Los_Angeles", "poll_interval_minutes": 60,
                 # OSM campground entrance, node 4360829121. Provider coordinates are null.
                 "latitude": 48.48414, "longitude": -121.59992, "booking_url": campground_url(CAMPGROUND_ID)}]

    async def trip_availability(self, campground_id: str, arrival: date, departure: date,
                                before_request: RequestGate | None = None) -> list[Campsite]:
        if campground_id != CAMPGROUND_ID:
            raise ValueError("Only Howard Miller Steelhead Park has verified Skagit County coverage.")
        if not stay_allowed(arrival, departure):
            return []
        offset, expected_total, facility = 0, None, None
        venues, portions, sites = set(), set(), []
        for _ in range(34):
            data = await self._request("GetAvailableNightlyFacilitiesAndVenues", AVAILABILITY_QUERY, {"facilityId": FACILITY_ID, "input_object": {
                "organization_id": ORGANIZATION_ID, "facility_ids": [FACILITY_ID], "venue_types": ["CAMPGROUND_SECTION", "CAMPSITE"],
                **query_window(arrival, departure), "limit": 30, "offset": offset,
            }}, before_request)
            catalog_info = validate_facility(data.get("facility"))
            page = data.get("getAvailableNightlyFacilitiesAndVenues")
            require(isinstance(page, dict), "omitted the availability page")
            total = page.get("total_venue_portions")
            require(type(total) is int and 0 < total <= 1000 and (expected_total is None or expected_total == total)
                    and type(page.get("has_more")) is bool and isinstance(page.get("results"), list) and len(page["results"]) == 1,
                    "returned an incomplete or changing campground catalog")
            expected_total = total
            result = page["results"][0]
            require(isinstance(result, dict), "returned an invalid campground page")
            info = validate_facility(result.get("info"), catalog=False)
            require(info["title"] == catalog_info["title"], "returned inconsistent campground metadata")
            require(facility is None or facility == info, "changed campground rules during pagination")
            facility = info
            batch = result.get("venues")
            require(isinstance(batch, list) and 0 < len(batch) <= 30, "returned an empty or invalid campsite page")
            for venue in batch:
                venue_id, portion_id, site = parse_venue(venue, facility, arrival, departure)
                require(venue_id not in venues and portion_id not in portions, "returned duplicate campsite pages")
                venues.add(venue_id)
                portions.add(portion_id)
                if site:
                    sites.append(site)
            require(len(portions) <= total and page["has_more"] == (len(portions) < total), "omitted campsite pages")
            if not page["has_more"]:
                require(page.get("next_offset") is None, "returned contradictory pagination")
                return sites
            require(type(page.get("next_offset")) is int and page["next_offset"] == offset + len(batch), "returned an invalid page cursor")
            offset = page["next_offset"]
        raise ProviderResponseError("Skagit County exceeded the campground pagination limit.")
