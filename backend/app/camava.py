"""Read-only Snohomish County searches. Never submits a reservation or cart form."""
from __future__ import annotations

import json
from datetime import date
from typing import Any

import httpx
from bs4 import BeautifulSoup

from .provider_ids import campground_url
from .provider_errors import ProviderResponseError
from .request_limiter import limited_request
from .recreation import Campsite, RateLimitError, _retry_after_seconds


SEARCH_URL = "https://reservations.snocoparks.org/reservation/camping/index.asp"


def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


def parse_catalog(html: str) -> list[dict[str, Any]]:
    soup = _soup(html)
    options = soup.select("select#parent_idno option[value]")
    if not options:
        raise ProviderResponseError("Snohomish campground directory format changed; no parks found.")
    # The public page includes structured location metadata for its map. Decode
    # JSON, not JavaScript, and never execute code supplied by a remote site.
    places: dict[str, dict] = {}
    for script in soup.find_all("script"):
        text = script.string or ""
        marker = "jsonPlaces = "
        if marker in text:
            try:
                records, _ = json.JSONDecoder().raw_decode(text.split(marker, 1)[1].lstrip())
                places = {str(item["idno"]): item for item in records}
            except (ValueError, KeyError, TypeError) as exc:
                raise ProviderResponseError("Snohomish location metadata could not be read.") from exc
            break
    targets = []
    for option in options:
        raw_id = option.get("value", "")
        if not raw_id.isdigit():
            continue
        place = places.get(raw_id, {})
        campground_id = f"camava:snoco:{raw_id}"
        lat = place.get("gps_lat", option.get("data-lat"))
        lon = place.get("gps_long", option.get("data-lng"))
        # Several directory coordinates are rounded to whole degrees. Do not put
        # those campgrounds at a misleading precise point on the map.
        if lat is not None and lon is not None:
            try:
                lat, lon = float(lat), float(lon)
            except (TypeError, ValueError):
                lat = lon = None
            if lat is not None and (not (-90 <= lat <= 90 and -180 <= lon <= 180)
                                    or (lat.is_integer() and lon.is_integer())):
                lat = lon = None
        targets.append({
            "campground_id": campground_id,
            "name": place.get("name") or option.get("title") or option.get_text(" ", strip=True),
            "park_name": "Snohomish County Parks", "state_code": "WA",
            "latitude": lat, "longitude": lon,
            "booking_url": campground_url(campground_id),
            "timezone": "America/Los_Angeles", "poll_interval_minutes": 60,
            "description": _soup(place.get("description") or "").get_text(" ", strip=True),
        })
    if not targets:
        raise ProviderResponseError("Snohomish directory returned no campground IDs.")
    return targets


def parse_availability(html: str, campground_id: str, arrival: date, departure: date) -> list[Campsite]:
    soup = _soup(html)
    raw_id = campground_id.split(":")[-1]
    selected = soup.select_one("#parent_idno option[selected]")
    arrive_input = soup.select_one("#camping_arrive_date")
    depart_input = soup.select_one("#camping_depart_date")
    if (not selected or selected.get("value") != raw_id or not arrive_input or not depart_input
            or arrive_input.get("value") != arrival.strftime("%m/%d/%Y")
            or depart_input.get("value") != departure.strftime("%m/%d/%Y")):
        raise ProviderResponseError("Snohomish did not confirm the requested park and dates; availability is unknown.")
    cards = soup.select('[id^="card_item_"]')
    if not cards:
        # An empty/challenge/error page must not expire previously found matches.
        expected = (f"No sites are available for an arrive date of {arrival.strftime('%m/%d/%Y')}, "
                    f"and departing on {departure.strftime('%m/%d/%Y')}")
        if expected not in soup.get_text(" ", strip=True):
            raise ProviderResponseError("Snohomish returned no recognizable search results; availability is unknown.")
        return []
    sites = []
    for card in cards:
        button = card.select_one('button[data-siteidno][data-parent_idno]')
        if (not button or button.has_attr("disabled") or button.get("data-parent_idno") != raw_id
                or button.get_text(strip=True).lower() != "reserve"):
            continue
        heading = card.select_one(".siteNameStats .ghost_title_lg")
        kind = next((b.parent.get_text(" ", strip=True).split(":", 1)[1].strip()
                     for b in card.select("b") if b.get_text(strip=True) == "Site Type:"), "")
        if not heading or not kind:
            raise ProviderResponseError("Snohomish site details changed; refusing an incomplete availability result.")
        name = " ".join(heading.find_all(string=True, recursive=False)).strip()
        if not name or not button["data-siteidno"].isdigit():
            raise ProviderResponseError("Snohomish returned an unrecognized campsite identity; availability is unknown.")
        people = None
        for node in card.select(".siteNameStats div"):
            text = node.get_text(" ", strip=True)
            if text.startswith("Max People:"):
                try:
                    people = int(text.split(":", 1)[1].strip())
                except ValueError:
                    pass
        sites.append(Campsite(
            campsite_id=f"camava:snoco:{button['data-siteidno']}", site=name, loop="",
            campsite_type=kind, max_num_people=people, availabilities={},
            booking_url=campground_url(campground_id, arrival.isoformat(), departure.isoformat()),
        ))
    if not sites:
        raise ProviderResponseError("Snohomish returned site cards without matching reservable sites; availability is unknown.")
    return sites


class SnohomishClient:
    def __init__(self, transport: httpx.AsyncBaseTransport | None = None):
        self.transport = transport

    @limited_request("snohomish")
    async def _get(self, url: str) -> str:
        try:
            async with httpx.AsyncClient(timeout=30, transport=self.transport, follow_redirects=False,
                                         headers={"User-Agent": "CampFinder/1.0 (availability monitor)"}) as client:
                response = await client.get(url)
        except httpx.RequestError as exc:
            raise ProviderResponseError("Snohomish County could not be reached. Check network access and try again later.") from exc
        if response.status_code == 429:
            raise RateLimitError(_retry_after_seconds(response.headers.get("Retry-After")), "Snohomish County Parks")
        if response.status_code in {401, 403}:
            raise ProviderResponseError("Snohomish County denied access. No bypass or repeated immediate retry was attempted.")
        if response.status_code != 200:
            raise ProviderResponseError(f"Snohomish County returned HTTP {response.status_code}; availability is unknown.")
        return response.text

    async def discover(self) -> list[dict[str, Any]]:
        return parse_catalog(await self._get(SEARCH_URL))

    async def trip_availability(self, campground_id: str, arrival: date, departure: date) -> list[Campsite]:
        html = await self._get(campground_url(campground_id, arrival.isoformat(), departure.isoformat()))
        return parse_availability(html, campground_id, arrival, departure)
