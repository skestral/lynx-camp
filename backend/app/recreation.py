from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date
from typing import Any

import httpx
from dateutil.relativedelta import relativedelta


BASE_URL = "https://www.recreation.gov/api"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_4) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/81.0.4044.138 Safari/537.36"
)


class RateLimitError(RuntimeError):
    def __init__(self, retry_after_seconds: int | None = None):
        self.retry_after_seconds = retry_after_seconds
        message = "Recreation.gov returned HTTP 429 Too Many Requests"
        if retry_after_seconds is not None:
            message = f"{message}; retry after {retry_after_seconds} seconds"
        super().__init__(message)


@dataclass(frozen=True)
class Campsite:
    campsite_id: str
    site: str
    loop: str
    campsite_type: str
    max_num_people: int | None
    availabilities: dict[str, str]
    reservation_window_value: int | None = None
    reservation_window_unit: str = ""

    @classmethod
    def from_api(cls, payload: dict[str, Any]) -> "Campsite":
        return cls(
            campsite_id=str(payload.get("campsite_id") or ""),
            site=str(payload.get("site") or ""),
            loop=str(payload.get("loop") or ""),
            campsite_type=str(payload.get("campsite_type") or ""),
            max_num_people=_optional_int(payload.get("max_num_people")),
            reservation_window_value=_optional_int(_reservation_window(payload).get("value")),
            reservation_window_unit=_normalize_release_window_unit(_reservation_window(payload).get("units")),
            availabilities=dict(payload.get("availabilities") or {}),
        )


class RecreationClient:
    def __init__(self, timeout_seconds: float = 15):
        self.timeout_seconds = timeout_seconds

    async def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        async with httpx.AsyncClient(
            base_url=BASE_URL,
            timeout=self.timeout_seconds,
            headers={"User-Agent": USER_AGENT},
        ) as client:
            response = await client.get(path, params=params)
            if response.status_code == 429:
                raise RateLimitError(_retry_after_seconds(response.headers.get("Retry-After")))
            response.raise_for_status()
            return response.json()

    async def suggest_campgrounds(self, query: str, size: int = 10) -> list[dict[str, Any]]:
        payload = await self._get(
            "/search/suggest",
            {"q": query, "geocoder": "true", "size": str(size)},
        )
        suggestions = payload.get("inventory_suggestions") or []
        campgrounds = []
        for item in suggestions:
            if str(item.get("entity_type", "")).lower() != "campground":
                continue
            campgrounds.append(
                {
                    "name": _title_name(item.get("name")),
                    "campground_id": str(item.get("entity_id") or item.get("id") or ""),
                    "park_name": _title_name(item.get("parent_name")),
                    "state_code": _state_code(item.get("state_code")),
                    "latitude": item.get("lat") or item.get("latitude"),
                    "longitude": item.get("lng") or item.get("longitude"),
                }
            )
        return [campground for campground in campgrounds if campground["campground_id"]]

    async def search_campgrounds(self, query: str, size: int = 100, start: int = 0) -> list[dict[str, Any]]:
        payload = await self._get(
            "/search",
            {
                "fq": ["entity_type:campground"],
                "q": query,
                "size": str(size),
                "start": str(start),
            },
        )
        campgrounds = []
        for item in payload.get("results") or []:
            if str(item.get("entity_type", "")).lower() != "campground":
                continue
            campground = _campground_from_search_result(item)
            if campground["campground_id"]:
                campgrounds.append(campground)
        return campgrounds

    async def campground_by_id(self, campground_id: str) -> dict[str, Any] | None:
        payload = await self._get(
            "/search",
            {"fq": ["entity_type:campground", f"entity_id:{campground_id}"]},
        )
        results = payload.get("results") or []
        if not results:
            return None
        campground = _campground_from_search_result(results[0], fallback_id=campground_id)
        campground["booking_url"] = f"https://www.recreation.gov/camping/campgrounds/{campground_id}"
        return campground

    async def monthly_availability(self, campground_id: str, month: date) -> dict[str, Campsite]:
        start_date = f"{month.year:04d}-{month.month:02d}-01T00:00:00.000Z"
        payload = await self._get(
            f"/camps/availability/campground/{campground_id}/month",
            {"start_date": start_date},
        )
        campsites = payload.get("campsites") or {}
        return {key: Campsite.from_api(value) for key, value in campsites.items()}

    async def detect_release_window(self, campground_id: str, start_month: date | None = None) -> dict[str, Any] | None:
        month = start_month or date.today().replace(day=1)
        for offset in range(3):
            sampled_month = month + relativedelta(months=offset)
            campsites = await self.monthly_availability(campground_id, sampled_month)
            windows = [
                (site.reservation_window_value, site.reservation_window_unit)
                for site in campsites.values()
                if site.reservation_window_value is not None and site.reservation_window_unit
            ]
            if not windows:
                continue
            (value, unit), count = Counter(windows).most_common(1)[0]
            return {
                "release_window_value": value,
                "release_window_unit": unit,
                "sampled_month": sampled_month.isoformat(),
                "source_campsite_count": count,
                "total_campsite_count": len(campsites),
            }
        return None

    async def release_window_profiles(self, campground_id: str, start_month: date | None = None) -> dict[str, Any]:
        month = start_month or date.today().replace(day=1)
        sampled_month = month
        campsites: dict[str, Campsite] = {}
        for offset in range(3):
            sampled_month = month + relativedelta(months=offset)
            campsites = await self.monthly_availability(campground_id, sampled_month)
            if campsites:
                break

        profiles: Counter[tuple[str, str, int | None, str]] = Counter()
        for site in campsites.values():
            profiles[
                (
                    site.loop or "",
                    site.campsite_type or "",
                    site.reservation_window_value,
                    site.reservation_window_unit or "",
                )
            ] += 1

        return {
            "sampled_month": sampled_month.isoformat(),
            "total_campsite_count": len(campsites),
            "profiles": [
                {
                    "loop": loop,
                    "campsite_type": campsite_type,
                    "release_window_value": value,
                    "release_window_unit": unit,
                    "campsite_count": count,
                }
                for (loop, campsite_type, value, unit), count in profiles.most_common()
            ],
        }


def _title_name(value: Any) -> str:
    text = str(value or "").strip()
    return " ".join(part.capitalize() for part in text.split())


def _campground_from_search_result(item: dict[str, Any], fallback_id: str = "") -> dict[str, Any]:
    campground_id = str(item.get("entity_id") or item.get("id") or fallback_id or "")
    return {
        "name": _title_name(item.get("name")),
        "campground_id": campground_id,
        "park_name": _title_name(item.get("parent_name")),
        "state_code": _state_code(item.get("state_code")),
        "latitude": item.get("latitude") or item.get("lat"),
        "longitude": item.get("longitude") or item.get("lng"),
    }


STATE_ABBREVIATIONS = {
    "alabama": "AL",
    "alaska": "AK",
    "arizona": "AZ",
    "arkansas": "AR",
    "california": "CA",
    "colorado": "CO",
    "connecticut": "CT",
    "delaware": "DE",
    "district of columbia": "DC",
    "florida": "FL",
    "georgia": "GA",
    "hawaii": "HI",
    "idaho": "ID",
    "illinois": "IL",
    "indiana": "IN",
    "iowa": "IA",
    "kansas": "KS",
    "kentucky": "KY",
    "louisiana": "LA",
    "maine": "ME",
    "maryland": "MD",
    "massachusetts": "MA",
    "michigan": "MI",
    "minnesota": "MN",
    "mississippi": "MS",
    "missouri": "MO",
    "montana": "MT",
    "nebraska": "NE",
    "nevada": "NV",
    "new hampshire": "NH",
    "new jersey": "NJ",
    "new mexico": "NM",
    "new york": "NY",
    "north carolina": "NC",
    "north dakota": "ND",
    "ohio": "OH",
    "oklahoma": "OK",
    "oregon": "OR",
    "pennsylvania": "PA",
    "rhode island": "RI",
    "south carolina": "SC",
    "south dakota": "SD",
    "tennessee": "TN",
    "texas": "TX",
    "utah": "UT",
    "vermont": "VT",
    "virginia": "VA",
    "washington": "WA",
    "west virginia": "WV",
    "wisconsin": "WI",
    "wyoming": "WY",
}


def _state_code(value: Any) -> str:
    text = str(value or "").strip()
    if len(text) == 2:
        return text.upper()
    return STATE_ABBREVIATIONS.get(text.lower(), text)


def _optional_int(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _retry_after_seconds(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return max(1, int(float(str(value).strip())))
    except (TypeError, ValueError):
        return None


def _reservation_window(payload: dict[str, Any]) -> dict[str, Any]:
    rules = payload.get("campsite_rules") or {}
    window = rules.get("reservationWindow") or {}
    return window if isinstance(window, dict) else {}


def _normalize_release_window_unit(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"day", "days"}:
        return "Days"
    if normalized in {"week", "weeks"}:
        return "Weeks"
    if normalized in {"month", "months"}:
        return "Months"
    return ""
