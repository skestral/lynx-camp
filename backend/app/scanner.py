from __future__ import annotations

import asyncio
import math
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from dateutil.relativedelta import relativedelta

from .db import Store
from .notifications import Notifier
from .recreation import Campsite, RateLimitError, RecreationClient


PATTERNS: dict[str, tuple[set[int], int]] = {
    "thu-sat": ({3}, 2),
    "fri-sun": ({4}, 2),
    "fri-sat-sun": ({4}, 2),
    "fri-mon": ({4}, 3),
    "sat-sun": ({5}, 1),
    "sat-mon": ({5}, 2),
    "sat-sun-mon": ({5}, 2),
    "sun-mon": ({6}, 1),
    "thu-sun": ({3}, 3),
}


@dataclass(frozen=True)
class TripWindow:
    arrival_date: date
    departure_date: date


def required_night_keys(arrival_date: date, departure_date: date) -> list[str]:
    nights = []
    current = arrival_date
    while current < departure_date:
        nights.append(f"{current.isoformat()}T00:00:00Z")
        current += timedelta(days=1)
    return nights


def months_for_trip(arrival_date: date, departure_date: date) -> list[date]:
    current = date(arrival_date.year, arrival_date.month, 1)
    last_night = departure_date - timedelta(days=1)
    end = date(last_night.year, last_night.month, 1)
    months = [current]
    while current < end:
        current = date(current.year, current.month, 1) + relativedelta(months=1)
        months.append(current)
    return months


def find_available_sites(
    campsite_maps: list[dict[str, Campsite]],
    arrival_date: date,
    departure_date: date,
) -> list[Campsite]:
    campsites: dict[str, Campsite] = {}
    for month_map in campsite_maps:
        for campsite_id, campsite in month_map.items():
            campsites[campsite_id] = campsite

    nights = required_night_keys(arrival_date, departure_date)
    available = []
    for campsite in campsites.values():
        if all(str(campsite.availabilities.get(night, "")).lower() == "available" for night in nights):
            available.append(campsite)
    return sorted(available, key=lambda site: site.site)


def site_matches_filters(campsite: Campsite, filters: dict | None) -> bool:
    filters = filters or {}
    site_type = str(filters.get("site_type") or "").strip().lower()
    loop = str(filters.get("loop") or "").strip().lower()
    site = str(filters.get("site") or "").strip().lower()
    min_people = filters.get("min_people")
    if site_type and site_type not in campsite.campsite_type.lower():
        return False
    if loop and loop not in campsite.loop.lower():
        return False
    if site and site not in campsite.site.lower():
        return False
    if min_people is not None and campsite.max_num_people is not None and campsite.max_num_people < int(min_people):
        return False
    return True


def generate_trip_windows(watch: dict) -> list[TripWindow]:
    if watch["mode"] == "specific":
        return [
            TripWindow(
                arrival_date=date.fromisoformat(item["arrival_date"]),
                departure_date=date.fromisoformat(item["departure_date"]),
            )
            for item in watch.get("specific_ranges", [])
        ]

    start = date.fromisoformat(watch["window_start"])
    end = date.fromisoformat(watch["window_end"])
    pattern_weekdays, default_nights = PATTERNS.get(watch.get("pattern") or "fri-sun", ({4}, 2))
    configured_weekdays = watch.get("arrival_weekdays")
    weekdays = set(configured_weekdays) if configured_weekdays else pattern_weekdays
    nights = int(watch.get("nights") or default_nights)
    trips: list[TripWindow] = []
    current = start
    while current + timedelta(days=nights) <= end:
        if current.weekday() in weekdays:
            trips.append(TripWindow(current, current + timedelta(days=nights)))
        current += timedelta(days=1)
    return trips


def compute_release_at(arrival_date: date, target: dict) -> datetime:
    value = int(target.get("release_window_value") or target.get("release_months") or 6)
    unit = str(target.get("release_window_unit") or "Months").strip().lower()
    if unit in {"day", "days"}:
        release_date = arrival_date - timedelta(days=value)
    elif unit in {"week", "weeks"}:
        release_date = arrival_date - timedelta(weeks=value)
    else:
        release_date = arrival_date - relativedelta(months=value)
    hour, minute = [int(part) for part in str(target.get("release_time") or "07:00").split(":", 1)]
    zone = ZoneInfo(target.get("timezone") or "America/Los_Angeles")
    return datetime.combine(release_date, time(hour=hour, minute=minute), tzinfo=zone)


def release_hints(watch: dict, limit: int = 5) -> list[dict]:
    now = datetime.now(UTC)
    upcoming = []
    already_open = []
    for trip in [trip for trip in generate_trip_windows(watch) if trip.arrival_date >= date.today()]:
        release_at = compute_release_at(trip.arrival_date, watch)
        hint = {
            "arrival_date": trip.arrival_date.isoformat(),
            "departure_date": trip.departure_date.isoformat(),
            "release_at": release_at.isoformat(),
            "release_status": "upcoming" if release_at.astimezone(UTC) >= now else "open",
        }
        if hint["release_status"] == "upcoming":
            upcoming.append(hint)
        else:
            already_open.append(hint)
    upcoming = sorted(upcoming, key=lambda item: item["release_at"])
    already_open = sorted(already_open, key=lambda item: item["arrival_date"])
    return (upcoming + already_open)[:limit]


def release_scan_delay_minutes(
    watch: dict,
    normal_interval_minutes: int,
    min_poll_interval_minutes: int,
    *,
    now: datetime | None = None,
    before_minutes: int = 15,
    after_minutes: int = 60,
    boost_interval_minutes: int = 2,
) -> int:
    normal_interval = max(int(normal_interval_minutes or 10), min_poll_interval_minutes)
    if before_minutes <= 0 or after_minutes <= 0 or boost_interval_minutes <= 0:
        return normal_interval

    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    current = current.astimezone(UTC)
    boost_start_delta = timedelta(minutes=before_minutes)
    boost_end_delta = timedelta(minutes=after_minutes)

    release_times = sorted(
        compute_release_at(trip.arrival_date, watch).astimezone(UTC)
        for trip in generate_trip_windows(watch)
        if trip.arrival_date >= current.date()
    )
    for release_at in release_times:
        boost_start = release_at - boost_start_delta
        boost_end = release_at + boost_end_delta
        if boost_start <= current <= boost_end:
            return max(1, int(boost_interval_minutes))
        if current < boost_start:
            minutes_until_boost = max(1, math.ceil((boost_start - current).total_seconds() / 60))
            return min(normal_interval, minutes_until_boost)

    return normal_interval


class Scanner:
    def __init__(
        self,
        store: Store,
        client: RecreationClient,
        notifier: Notifier,
        min_poll_interval_minutes: int,
        release_scan_before_minutes: int = 15,
        release_scan_after_minutes: int = 60,
        release_scan_interval_minutes: int = 2,
        availability_cache_minutes: int = 5,
        api_request_delay_seconds: float = 1,
        rate_limit_backoff_minutes: int = 60,
        max_notification_results: int = 5,
    ):
        self.store = store
        self.client = client
        self.notifier = notifier
        self.min_poll_interval_minutes = min_poll_interval_minutes
        self.release_scan_before_minutes = release_scan_before_minutes
        self.release_scan_after_minutes = release_scan_after_minutes
        self.release_scan_interval_minutes = release_scan_interval_minutes
        self.availability_cache_minutes = max(0, int(availability_cache_minutes))
        self.api_request_delay_seconds = max(0.0, float(api_request_delay_seconds))
        self.rate_limit_backoff_minutes = max(1, int(rate_limit_backoff_minutes))
        self.max_notification_results = max(1, int(max_notification_results))
        self._availability_cache: dict[tuple[str, date], tuple[datetime, dict[str, Campsite]]] = {}
        self._api_backoff_until: datetime | None = None
        self._last_api_request_at: datetime | None = None
        self._lock = asyncio.Lock()

    async def scan_watch(self, watch_id: int) -> dict:
        watch = self.store.get_watch(watch_id)
        if watch is None:
            raise ValueError(f"watch {watch_id} not found")

        async with self._lock:
            return await self._scan_watch(watch)

    async def scan_all_watches(self) -> dict:
        async with self._lock:
            summaries = []
            for watch in [item for item in self.store.list_watches() if item.get("active") and item.get("target_active")]:
                try:
                    result = await self._scan_watch(watch)
                    summaries.append({"watch_id": watch["id"], "watch_name": watch["name"], **result})
                except Exception as exc:
                    summaries.append(
                        {
                            "watch_id": watch["id"],
                            "watch_name": watch["name"],
                            "status": "error",
                            "message": str(exc),
                            "candidate_count": 0,
                            "available_count": 0,
                        }
                    )
            return {
                "watch_count": len(summaries),
                "available_count": sum(item.get("available_count", 0) for item in summaries),
                "missing_count": sum(item.get("missing_count", 0) for item in summaries),
                "summaries": summaries,
            }

    async def scan_due_watches(self) -> None:
        async with self._lock:
            for watch in self.store.due_watches():
                try:
                    await self._scan_watch(watch)
                except Exception as exc:
                    self.store.update_target_scan_status(watch["target_id"], f"error: {exc}")
                    self._schedule_next_scan(watch)

    def _schedule_next_scan(self, watch: dict) -> int:
        interval = release_scan_delay_minutes(
            watch,
            int(watch.get("poll_interval_minutes") or 10),
            self.min_poll_interval_minutes,
            before_minutes=self.release_scan_before_minutes,
            after_minutes=self.release_scan_after_minutes,
            boost_interval_minutes=self.release_scan_interval_minutes,
        )
        self.store.schedule_next_scan(watch["id"], interval)
        return interval

    async def _scan_watch(self, watch: dict) -> dict:
        run_id = self.store.start_scan_run(watch)
        trips = [trip for trip in generate_trip_windows(watch) if trip.arrival_date >= date.today()]
        available_count = 0
        missing_count = 0
        new_results: list[dict] = []
        seen_dedupe_keys: set[str] = set()
        monthly_cache: dict[date, dict[str, Campsite]] = {}

        backoff_minutes = self._rate_limit_remaining_minutes()
        if backoff_minutes is not None:
            message = f"Recreation.gov rate limit active; retrying in about {backoff_minutes} minute(s)."
            self.store.finish_scan_run(run_id, "rate_limited", message, 0, 0)
            self.store.update_target_scan_status(watch["target_id"], "rate_limited")
            self.store.schedule_next_scan(watch["id"], backoff_minutes)
            return {
                "status": "rate_limited",
                "message": message,
                "candidate_count": 0,
                "available_count": 0,
            }

        try:
            for trip in trips:
                month_maps = []
                for month in months_for_trip(trip.arrival_date, trip.departure_date):
                    if month not in monthly_cache:
                        monthly_cache[month] = await self._monthly_availability(watch["campground_id"], month)
                    month_maps.append(monthly_cache[month])

                sites = [
                    site
                    for site in find_available_sites(month_maps, trip.arrival_date, trip.departure_date)
                    if site_matches_filters(site, watch.get("site_filters"))
                ]
                for site in sites:
                    result, is_new = self.store.upsert_result(
                        {
                            "watch_id": watch["id"],
                            "target_id": watch["target_id"],
                            "campground_id": watch["campground_id"],
                            "campground_name": watch["target_name"],
                            "campsite_id": site.campsite_id,
                            "site": site.site,
                            "loop": site.loop,
                            "campsite_type": site.campsite_type,
                            "arrival_date": trip.arrival_date.isoformat(),
                            "departure_date": trip.departure_date.isoformat(),
                            "booking_url": f"https://www.recreation.gov/camping/campsites/{site.campsite_id}",
                        }
                    )
                    seen_dedupe_keys.add(result["dedupe_key"])
                    available_count += 1
                    if is_new:
                        new_results.append({**result, "watch_name": watch["name"]})

            missing_count = self.store.mark_missing_results_booked(
                watch["id"],
                [(trip.arrival_date.isoformat(), trip.departure_date.isoformat()) for trip in trips],
                seen_dedupe_keys,
            )

            if new_results:
                await self.notifier.notify_results(new_results, self.store, self.max_notification_results)

            status = "available" if available_count else "clear"
            if available_count:
                message = f"Found {available_count} available site/date match(es), including {len(new_results)} new match(es)."
            else:
                message = "No matching availability found."
            if missing_count:
                message += f" Marked {missing_count} previous match(es) as booked because they were not returned again."
            self.store.finish_scan_run(run_id, "success", message, len(trips), available_count)
            self.store.update_target_scan_status(watch["target_id"], status)
            self._schedule_next_scan(watch)
            return {
                "status": "success",
                "message": message,
                "candidate_count": len(trips),
                "available_count": available_count,
                "missing_count": missing_count,
            }
        except RateLimitError as exc:
            self._start_rate_limit_backoff(exc)
            backoff_minutes = self._rate_limit_remaining_minutes() or self.rate_limit_backoff_minutes
            message = f"Recreation.gov returned HTTP 429; pausing scans for about {backoff_minutes} minute(s)."
            self.store.finish_scan_run(run_id, "rate_limited", message, len(trips), available_count)
            self.store.update_target_scan_status(watch["target_id"], "rate_limited")
            self.store.schedule_next_scan(watch["id"], backoff_minutes)
            return {
                "status": "rate_limited",
                "message": message,
                "candidate_count": len(trips),
                "available_count": available_count,
            }
        except Exception as exc:
            self.store.finish_scan_run(run_id, "error", str(exc), len(trips), available_count)
            self.store.update_target_scan_status(watch["target_id"], f"error: {exc}")
            self._schedule_next_scan(watch)
            raise

    async def _monthly_availability(self, campground_id: str, month: date) -> dict[str, Campsite]:
        key = (campground_id, month)
        cached = self._availability_cache.get(key)
        if cached is not None:
            fetched_at, campsites = cached
            if self.availability_cache_minutes > 0 and datetime.now(UTC) - fetched_at <= timedelta(
                minutes=self.availability_cache_minutes
            ):
                return campsites

        await self._wait_for_api_slot()
        campsites = await self.client.monthly_availability(campground_id, month)
        self._availability_cache[key] = (datetime.now(UTC), campsites)
        return campsites

    async def _wait_for_api_slot(self) -> None:
        if self.api_request_delay_seconds <= 0:
            return
        now = datetime.now(UTC)
        if self._last_api_request_at is not None:
            elapsed = (now - self._last_api_request_at).total_seconds()
            if elapsed < self.api_request_delay_seconds:
                await asyncio.sleep(self.api_request_delay_seconds - elapsed)
        self._last_api_request_at = datetime.now(UTC)

    def _start_rate_limit_backoff(self, exc: RateLimitError) -> None:
        seconds = exc.retry_after_seconds or self.rate_limit_backoff_minutes * 60
        self._api_backoff_until = datetime.now(UTC) + timedelta(seconds=seconds)

    def _rate_limit_remaining_minutes(self) -> int | None:
        if self._api_backoff_until is None:
            return None
        remaining = self._api_backoff_until - datetime.now(UTC)
        if remaining.total_seconds() <= 0:
            self._api_backoff_until = None
            return None
        return max(1, math.ceil(remaining.total_seconds() / 60))
