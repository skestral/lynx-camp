from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time as clock
import math
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from dateutil.relativedelta import relativedelta

from .cart_assist import CartAssistant
from .db import Store
from .notifications import Notifier
from .recreation import Campsite, RateLimitError
from .providers import CampgroundClient
from .goingtocamp import validate_watch_filters
from .provider_registry import is_goingtocamp
from .provider_ids import provider_key, provider_name
from .provider_errors import ProviderResponseError
from .request_limiter import ProviderRequestLimiter, request_cancel_check


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
    if filters.get("campsite_ids") and campsite.campsite_id not in filters["campsite_ids"]:
        return False
    equipment = filters.get("equipment")
    if equipment and equipment not in campsite.equipment:
        return False
    length = filters.get("vehicle_length_ft")
    maximum = campsite.equipment_lengths_ft.get(equipment, campsite.max_vehicle_length_ft)
    if length is not None and (maximum is None or float(length) > maximum):
        return False
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


def campsite_booking_url(campsite_id: str, arrival_date: date) -> str:
    return f"https://www.recreation.gov/camping/campsites/{campsite_id}?startDate={arrival_date.isoformat()}"


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
    if provider_key(watch.get("campground_id", "")) != "recreation":
        return []
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
    if provider_key(watch.get("campground_id", "")) != "recreation":
        return normal_interval
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
        client: CampgroundClient,
        notifier: Notifier,
        min_poll_interval_minutes: int,
        cart_assistant: CartAssistant | None = None,
        release_scan_before_minutes: int = 15,
        release_scan_after_minutes: int = 60,
        release_scan_interval_minutes: int = 2,
        availability_cache_minutes: int = 5,
        api_request_delay_seconds: float = 5,
        rate_limit_backoff_minutes: int = 60,
        max_notification_results: int = 5,
    ):
        self.store = store
        self.client = client
        self.notifier = notifier
        self.cart_assistant = cart_assistant
        self.min_poll_interval_minutes = min_poll_interval_minutes
        self.release_scan_before_minutes = release_scan_before_minutes
        self.release_scan_after_minutes = release_scan_after_minutes
        self.release_scan_interval_minutes = release_scan_interval_minutes
        self.availability_cache_minutes = max(0, int(availability_cache_minutes))
        self.api_request_delay_seconds = max(0.0, float(api_request_delay_seconds))
        self.rate_limit_backoff_minutes = max(1, int(rate_limit_backoff_minutes))
        self.max_notification_results = max(1, int(max_notification_results))
        self._availability_cache: dict[tuple[str, date], tuple[datetime, dict[str, Campsite]]] = {}
        self._trip_cache: dict[tuple[str, date, date], tuple[datetime, list[Campsite]]] = {}
        self._equipment_cache: dict[tuple[str, str], tuple[datetime, dict]] = {}
        self._provider_backoffs: dict[str, dict] = {}
        self._provider_last_request: dict[str, datetime] = {}
        self._api_backoff_until: datetime | None = None
        self._last_api_request_at: datetime | None = None
        self._lock = asyncio.Lock()
        self._cancel_requested = False
        self._active_run_id: int | None = None
        self._active_watch_id: int | None = None
        self._active_target_id: int | None = None
        self._sweep: dict = {}
        self._sweep_task: asyncio.Task | None = None
        self._adaptive_delay = 0.0
        self._rate_limit_streak = 0
        self._request_seconds = 1.0
        self._current_months_loaded = 0
        self._crawl_paused = False
        self.request_limiter = ProviderRequestLimiter(
            self._request_delay, self._rate_limit_remaining_seconds, self._start_rate_limit_backoff)
        self._shared_requests = hasattr(client, "set_request_limiter")
        if self._shared_requests:
            client.set_request_limiter(self.request_limiter)

    def _request_delay(self, provider: str) -> float:
        return (self.effective_request_delay if provider == "recreation" else
                max(5, self.api_request_delay_seconds, self._provider_backoffs.get(provider, {}).get("delay", 0)))

    def _date_progress(self, watch: dict, trips: list) -> dict:
        criteria = {key: watch.get(key) for key in (
            "campground_id", "mode", "pattern", "arrival_weekdays", "nights", "window_start", "window_end",
            "specific_ranges", "site_filters", "cart_assist_enabled")}
        fingerprint = hashlib.sha256(json.dumps(criteria, sort_keys=True).encode()).hexdigest()
        saved = self.store.scan_checkpoint(watch["id"])
        completed = saved.get("completed", {}) if saved.get("fingerprint") == fingerprint else {}
        # An interrupted alert must be revalidated, not sent from an old checkpoint.
        pending_stays = self.store.pending_notification_stays(watch["id"])
        valid = {f"{trip.arrival_date}/{trip.departure_date}" for trip in trips}
        return {"fingerprint": fingerprint, "completed": {
            key: value for key, value in completed.items() if key in valid and key not in pending_stays}}

    def restore_runtime_state(self) -> None:
        raw = self.store.get_app_settings(["scanner_runtime"]).get("scanner_runtime")
        if not raw:
            return
        state = json.loads(raw)
        self._sweep = state.get("sweep") or {}
        self._crawl_paused = bool(state.get("crawl_paused", False))
        self._adaptive_delay = float(state.get("adaptive_delay", 0))
        self._rate_limit_streak = int(state.get("rate_limit_streak", 0))
        self._provider_backoffs = state.get("provider_backoffs") or {}
        until = state.get("backoff_until")
        self._api_backoff_until = datetime.fromisoformat(until) if until else None
        if self._sweep.get("status") == "running":
            self._sweep["status"] = "queued"

    def _save_runtime(self) -> None:
        self.store.set_app_settings({"scanner_runtime": json.dumps({
            "sweep": self._sweep, "adaptive_delay": self._adaptive_delay,
            "crawl_paused": self._crawl_paused,
            "rate_limit_streak": self._rate_limit_streak,
            "backoff_until": self._api_backoff_until.isoformat() if self._api_backoff_until else None,
            "provider_backoffs": self._provider_backoffs,
        })})

    @property
    def effective_request_delay(self) -> float:
        return max(self.api_request_delay_seconds, self._adaptive_delay)

    @property
    def full_scan_pending(self) -> bool:
        return self._sweep.get("status") in {"queued", "running", "waiting"}

    def scan_status(self) -> dict:
        pending = self._sweep.get("pending", [])
        providers = self._sweep.get("providers", {})
        pending_providers = {providers.get(str(watch_id), "recreation") for watch_id in pending} or {"recreation", *self._provider_backoffs}
        remaining = {key: self._rate_limit_remaining_seconds(key) for key in pending_providers}
        waiting = all(remaining.values()) if pending else any(remaining.values())
        cooldown = min(value for value in remaining.values() if value > 0) if waiting else 0
        retry_at = (datetime.now(UTC) + timedelta(seconds=cooldown)).isoformat() if cooldown else None
        months = self._sweep.get("months", {})
        work = {key: 0 for key in pending_providers}
        completed_stays = 0
        checkpoints = self.store.scan_checkpoint_summaries() if pending else {}
        for watch_id in pending:
            progress = checkpoints.get(watch_id, {})
            completed_stays += progress.get("completed_stays", 0)
            key = providers.get(str(watch_id), "recreation")
            remaining_requests = progress.get("remaining_requests")
            work[key] += remaining_requests if remaining_requests is not None else months.get(str(watch_id), 0)
        requests = sum(work.values())
        delay = max(self._request_delay(key) for key in pending_providers)
        # Other providers can use a cooldown to make progress, but it still sets
        # a lower bound on when the final blocked provider can finish.
        durations = {key: count * (self._request_delay(key) + self._request_seconds) for key, count in work.items()}
        estimate = math.ceil(max(sum(durations.values()), max(
            (remaining[key] + duration for key, duration in durations.items()), default=0
        ))) if self.full_scan_pending else None
        return {
            "status": "waiting" if cooldown and self.full_scan_pending else self._sweep.get("status", "idle"),
            "crawl_paused": self._crawl_paused,
            "total_count": self._sweep.get("total_count", 0),
            "completed_count": self._sweep.get("completed_count", 0),
            "failed_count": self._sweep.get("failed_count", 0),
            "skipped_count": self._sweep.get("skipped_count", 0),
            "remaining_count": len(pending),
            "current_target": self._sweep.get("current_target"),
            "retry_at": retry_at,
            "cooldown_seconds": cooldown,
            "effective_request_delay_seconds": delay,
            "estimated_remaining_seconds": estimate,
            "estimated_requests_remaining": requests,
            "completed_stay_count": completed_stays,
        }

    def _begin_full_scan(self, watches: list[dict] | None = None) -> None:
        if watches is None:
            watches = [w for w in self.store.list_watches() if w.get("active") and w.get("target_active")]
        self._sweep = {"status": "queued", "pending": [w["id"] for w in watches],
                       "total_count": len(watches), "completed_count": 0, "failed_count": 0,
                       "skipped_count": 0, "available_count": 0, "missing_count": 0,
                       "providers": {str(w["id"]): provider_key(w["campground_id"]) for w in watches},
                       "months": {str(w["id"]): (len([t for t in generate_trip_windows(w) if t.arrival_date >= date.today()])
                                  if provider_key(w["campground_id"]) != "recreation" else len({month for trip in generate_trip_windows(w)
                                  if trip.arrival_date >= date.today()
                                  for month in months_for_trip(trip.arrival_date, trip.departure_date)})) for w in watches}}
        self._save_runtime()

    def start_full_scan(self) -> dict:
        if self.full_scan_pending:
            return self.scan_status()
        if self.is_busy:
            raise ValueError("A scan is already running. Wait or stop it before starting a full scan.")
        self._crawl_paused = False
        if self._sweep.get("status") == "cancelled" and self._sweep.get("pending"):
            self._sweep["status"] = "queued"
            self._save_runtime()
        else:
            self._begin_full_scan()
        self._sweep_task = asyncio.create_task(self._run_requested_scan())
        return self.scan_status()

    async def _run_requested_scan(self) -> None:
        try:
            async with self._lock:
                if self.full_scan_pending:
                    await self._continue_full_scan()
        except Exception:
            logging.getLogger(__name__).exception("Full scan interrupted")
            self._sweep["status"] = "incomplete"
            self._save_runtime()

    async def shutdown(self) -> None:
        if self._sweep_task and not self._sweep_task.done():
            self._sweep_task.cancel()
            try:
                await self._sweep_task
            except asyncio.CancelledError:
                pass

    def configure_scan_controls(
        self,
        *,
        min_poll_interval_minutes: int,
        release_scan_before_minutes: int,
        release_scan_after_minutes: int,
        release_scan_interval_minutes: int,
        availability_cache_minutes: int,
        api_request_delay_seconds: float,
        rate_limit_backoff_minutes: int,
    ) -> None:
        self.min_poll_interval_minutes = max(1, int(min_poll_interval_minutes))
        self.release_scan_before_minutes = max(0, int(release_scan_before_minutes))
        self.release_scan_after_minutes = max(0, int(release_scan_after_minutes))
        self.release_scan_interval_minutes = max(1, int(release_scan_interval_minutes))
        self.availability_cache_minutes = max(0, int(availability_cache_minutes))
        self.api_request_delay_seconds = max(0.0, float(api_request_delay_seconds))
        self.rate_limit_backoff_minutes = max(1, int(rate_limit_backoff_minutes))

    @property
    def is_busy(self) -> bool:
        return self._lock.locked()

    @property
    def active_watch_id(self) -> int | None:
        return self._active_watch_id

    async def delete_watches(self, watch_ids: list[int]) -> int:
        if self.is_busy:
            raise ValueError("Stop the current scan and wait for it to finish before deleting watches.")
        async with self._lock:
            task = asyncio.create_task(self._delete_watches_and_prune(watch_ids))
            cancelled = False
            # Cancelling an HTTP request cannot stop a SQLite worker. Keep the scan
            # lock until its transaction and queue update finish, even on disconnect.
            while True:
                try:
                    count = await asyncio.shield(task)
                    break
                except asyncio.CancelledError:
                    if task.cancelled():
                        raise
                    cancelled = True
            if cancelled:
                raise asyncio.CancelledError
            return count

    async def _delete_watches_and_prune(self, watch_ids: list[int]) -> int:
        count = await asyncio.to_thread(self.store.bulk_update_watches, watch_ids, "delete")
        deleted = set(watch_ids)
        pending = self._sweep.get("pending", [])
        remaining = [watch_id for watch_id in pending if watch_id not in deleted]
        if len(remaining) != len(pending):
            self._sweep["pending"] = remaining
            self._sweep["skipped_count"] = self._sweep.get("skipped_count", 0) + len(pending) - len(remaining)
            self._sweep["months"] = {
                key: value for key, value in self._sweep.get("months", {}).items() if int(key) not in deleted
            }
            self._sweep["current_target"] = None
            if not remaining and not self._crawl_paused:
                self._sweep["status"] = "incomplete" if self._sweep.get("failed_count") else "completed"
            await asyncio.to_thread(self._save_runtime)
        return count

    async def scan_watch(self, watch_id: int) -> dict:
        watch = self.store.get_watch(watch_id)
        if watch is None:
            raise ValueError(f"watch {watch_id} not found")

        if self.is_busy or self.full_scan_pending:
            raise ValueError("A background crawl is pending; wait or stop it before scanning one campground.")
        backoff = self._rate_limit_remaining_minutes(provider_key(watch["campground_id"]))
        if backoff:
            return {"status": "rate_limited", "message": f"Waiting for provider cooldown, about {backoff} minutes remaining.", "candidate_count": 0, "available_count": 0}
        async with self._lock:
            return await self._scan_watch(watch)

    async def scan_all_watches(self) -> dict:
        async with self._lock:
            if not self.full_scan_pending:
                self._begin_full_scan()
            return await self._continue_full_scan()

    async def _continue_full_scan(self) -> dict:
        summaries = []
        self._sweep["status"] = "running"
        while self._sweep["pending"]:
            # Keep throttled work queued while unrelated providers make progress.
            watch_id = None
            for candidate in self._sweep["pending"]:
                watch = self.store.get_watch(candidate)
                if not watch or self._rate_limit_remaining_minutes(provider_key(watch["campground_id"])) is None:
                    watch_id = candidate
                    break
            if watch_id is None:
                self._sweep["status"] = "waiting"
                self._sweep["current_target"] = None
                self._save_runtime()
                break
            self._current_months_loaded = 0
            self._sweep["current_target"] = watch.get("target_name") if watch else None
            try:
                result = await self._scan_watch(watch) if watch else {"status": "skipped"}
            except Exception as exc:
                result = {"status": "error", "message": str(exc)}
            latest = self.store.get_watch(watch_id)
            if result["status"] == "cancelled" and not self._crawl_paused and (not latest or not latest.get("active")):
                result["status"] = "skipped"
            summaries.append({"watch_id": watch_id, "watch_name": watch.get("name") if watch else "Removed watch", **result})
            if result["status"] == "rate_limited":
                self._current_months_loaded = 0
                self._save_runtime()
                continue
            if result["status"] == "cancelled" or self._sweep["status"] == "cancelled":
                self._sweep["status"] = "waiting" if result["status"] == "rate_limited" else "cancelled"
                self._current_months_loaded = 0
                self._save_runtime()
                break
            self._sweep["pending"].remove(watch_id)
            key = "completed_count" if result["status"] == "success" else "skipped_count" if result["status"] == "skipped" else "failed_count"
            self._sweep[key] += 1
            self._sweep["available_count"] += result.get("available_count", 0)
            self._sweep["missing_count"] += result.get("missing_count", 0)
            self._current_months_loaded = 0
            self._save_runtime()
        if not self._sweep["pending"]:
            self._sweep["status"] = "incomplete" if self._sweep["failed_count"] else "completed"
            if self._sweep["status"] == "completed":
                completed_providers = set(self._sweep.get("providers", {}).values())
                if "recreation" in completed_providers and not self._rate_limit_remaining_seconds("recreation"):
                    self._rate_limit_streak = 0
                    self._adaptive_delay = max(self.api_request_delay_seconds, round(self._adaptive_delay * 0.8, 2))
                for key, state in self._provider_backoffs.items():
                    if key not in completed_providers or self._rate_limit_remaining_seconds(key):
                        continue
                    state["streak"] = 0
                    state["delay"] = max(self.api_request_delay_seconds, round(state.get("delay", 0) * 0.8, 2))
            self._save_runtime()
        return {
            **self.scan_status(),
            "watch_count": len(summaries),
            "available_count": self._sweep["available_count"],
            "missing_count": self._sweep["missing_count"],
            "summaries": summaries,
        }

    async def scan_due_watches(self) -> None:
        async with self._lock:
            if self._crawl_paused:
                return
            if not self.full_scan_pending:
                due = self.store.due_watches(limit=10000)
                if not due:
                    return
                self._begin_full_scan(due)
            await self._continue_full_scan()

    def cancel_current_scan(self, pause_crawl: bool = True) -> dict:
        active_run_id = self._active_run_id
        if pause_crawl:
            self._crawl_paused = True
            self._save_runtime()
        sweep_cancelled = self.full_scan_pending and pause_crawl
        if sweep_cancelled:
            self._sweep["status"] = "cancelled"
            self._save_runtime()
        if active_run_id is not None:
            self._cancel_requested = True
            self.store.log_scan_event(
                active_run_id,
                self._active_watch_id,
                self._active_target_id,
                "warning",
                "cancel_requested",
                "Stop requested from the web UI. The scanner will stop at the next safe checkpoint.",
            )
        stale_count = self.store.cancel_running_scan_runs(
            "Scan was marked cancelled from the activity log.",
            exclude_run_ids=[active_run_id] if active_run_id is not None else [],
        )
        return {
            "cancel_requested": active_run_id is not None or sweep_cancelled,
            "active_run_id": active_run_id,
            "stale_cancelled_count": stale_count,
        }

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
        # A bulk pause may have changed a watch after the sweep was queued.
        current = self.store.get_watch(watch["id"])
        if not current or not current.get("active") or not current.get("target_active"):
            return {"status": "skipped", "candidate_count": 0, "available_count": 0}
        watch = current
        provider = provider_key(watch["campground_id"])
        provider_label = provider_name(watch["campground_id"])
        run_id = self.store.start_scan_run(watch)
        self._cancel_requested = False
        self._active_run_id = run_id
        self._active_watch_id = int(watch["id"])
        self._active_target_id = int(watch["target_id"])
        self._log_scan_event(
            run_id,
            watch,
            "info",
            "started",
            f"Started {watch['name']} for {watch['target_name']}.",
        )
        trips = [trip for trip in generate_trip_windows(watch) if trip.arrival_date >= date.today()]
        self._log_scan_event(
            run_id,
            watch,
            "info",
            "planned",
            f"Prepared {len(trips)} candidate stay(s) to check.",
        )
        available_count = 0
        missing_count = 0
        cart_attempt_count = 0
        new_results: list[dict] = []
        pending_results: dict[int, dict] = {}
        progress = self._date_progress(watch, trips)
        seen_dedupe_keys = {key for keys in progress["completed"].values() for key in keys}
        available_count = len(seen_dedupe_keys)
        if progress["completed"]:
            self._log_scan_event(run_id, watch, "info", "resumed",
                                 f"Resuming after {len(progress['completed'])} completed stay check(s).")
        monthly_cache: dict[date, dict[str, Campsite]] = {}

        backoff_minutes = self._rate_limit_remaining_minutes(provider)
        if backoff_minutes is not None:
            message = f"{provider_label} rate limit active; retrying in about {backoff_minutes} minute(s)."
            self.store.finish_scan_run(run_id, "rate_limited", message, 0, 0)
            self.store.update_target_scan_status(watch["target_id"], "rate_limited")
            self.store.schedule_next_scan(watch["id"], backoff_minutes)
            self._log_scan_event(run_id, watch, "warning", "rate_limited", message)
            self._clear_active_run(run_id)
            return {
                "status": "rate_limited",
                "message": message,
                "candidate_count": 0,
                "available_count": 0,
            }

        cancel_token = request_cancel_check.set(self._raise_if_cancel_requested)
        try:
            filters = watch.get("site_filters") or {}
            if (filters.get("equipment") or filters.get("vehicle_length_ft") is not None) and provider not in {"recreation", "ud_ca", "ud_metro"}:
                raise ProviderResponseError(f"{provider_label} cannot verify equipment compatibility. Remove the equipment filter for this target.")
            for trip_index, trip in enumerate(trips, start=1):
                stay_key = f"{trip.arrival_date}/{trip.departure_date}"
                if stay_key in progress["completed"]:
                    continue
                stay_dedupe_keys = []
                if is_goingtocamp(provider):
                    validate_watch_filters(watch.get("site_filters"), watch["campground_id"])
                self._raise_if_cancel_requested()
                if trip_index == 1 or trip_index % 25 == 0 or trip_index == len(trips):
                    self._log_scan_event(
                        run_id,
                        watch,
                        "info",
                        "progress",
                        (
                            f"Checking stay {trip_index} of {len(trips)}: "
                            f"{trip.arrival_date.isoformat()} to {trip.departure_date.isoformat()}."
                        ),
                    )
                month_maps = []
                for month in (months_for_trip(trip.arrival_date, trip.departure_date) if provider == "recreation" else []):
                    self._raise_if_cancel_requested()
                    if month not in monthly_cache:
                        self._log_scan_event(
                            run_id,
                            watch,
                            "info",
                            "fetch",
                            f"Fetching Recreation.gov availability for {month.strftime('%B %Y')}.",
                        )
                        monthly_cache[month] = await self._monthly_availability(watch["campground_id"], month)
                        self._current_months_loaded = len(monthly_cache)
                        self._log_scan_event(
                            run_id,
                            watch,
                            "info",
                            "fetched",
                            f"Loaded {len(monthly_cache[month])} campsite record(s) for {month.strftime('%B %Y')}.",
                        )
                    month_maps.append(monthly_cache[month])

                if provider == "recreation":
                    matching_sites = find_available_sites(month_maps, trip.arrival_date, trip.departure_date)
                else:
                    self._log_scan_event(run_id, watch, "info", "fetch", f"Searching {provider_label}: {trip.arrival_date} to {trip.departure_date}.")
                    matching_sites = await self._trip_availability(watch["campground_id"], trip)
                    self._current_months_loaded = trip_index
                self._raise_if_cancel_requested()
                filters = watch.get("site_filters") or {}
                if filters.get("equipment") or filters.get("vehicle_length_ft") is not None:
                    if provider == "recreation":
                        text_filters = {key: value for key, value in filters.items() if key not in {"equipment", "vehicle_length_ft"}}
                        matching_sites = [await self._with_equipment(watch["campground_id"], site)
                                          for site in matching_sites if site_matches_filters(site, text_filters)]
                sites = [
                    site
                    for site in matching_sites
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
                            "booking_url": site.booking_url or campsite_booking_url(site.campsite_id, trip.arrival_date),
                        }
                    )
                    seen_dedupe_keys.add(result["dedupe_key"])
                    stay_dedupe_keys.append(result["dedupe_key"])
                    available_count += 1
                    if is_new:
                        new_results.append({**result, "watch_name": watch["name"]})
                    if result["notification_pending"]:
                        pending_results[result["id"]] = {**result, "watch_name": watch["name"]}
                if sites:
                    self._log_scan_event(
                        run_id,
                        watch,
                        "info",
                        "available",
                        (
                            f"Found {len(sites)} available site(s) for "
                            f"{trip.arrival_date.isoformat()} to {trip.departure_date.isoformat()}."
                        ),
                    )

                progress["completed"][stay_key] = stay_dedupe_keys
                unfinished = [t for t in trips if f"{t.arrival_date}/{t.departure_date}" not in progress["completed"]]
                progress["remaining_requests"] = (len({month for t in unfinished
                    for month in months_for_trip(t.arrival_date, t.departure_date)})
                    if provider == "recreation" else len(unfinished))
                self.store.save_scan_checkpoint(watch["id"], progress)

            missing_count = self.store.mark_missing_results_booked(
                watch["id"],
                [(trip.arrival_date.isoformat(), trip.departure_date.isoformat()) for trip in trips],
                seen_dedupe_keys,
            )

            if new_results:
                if self.cart_assistant and provider == "recreation":
                    cart_attempts = await self.cart_assistant.handle_new_results(watch, new_results)
                    cart_attempt_count = len(cart_attempts)
                    if cart_attempts:
                        new_results = [
                            {
                                **result,
                                "cart_assist_message": (
                                    f"Cart Assist recorded {cart_attempt_count} attempt"
                                    f"{'' if cart_attempt_count == 1 else 's'} for this scan."
                                ),
                            }
                            for result in new_results
                        ]
                pending_results.update((result["id"], result) for result in new_results)
            if pending_results:
                notified_count = await self._notify_pending_results(pending_results)
                self._log_scan_event(
                    run_id,
                    watch,
                    "info",
                    "notified",
                    f"Prepared notifications for {notified_count} pending result(s).",
                )

            status = "available" if available_count else "clear"
            if available_count:
                message = f"Found {available_count} available site/date match(es), including {len(new_results)} new match(es)."
            else:
                message = "No matching availability found."
            if missing_count:
                message += f" Marked {missing_count} previous match(es) as booked because they were not returned again."
            if cart_attempt_count:
                message += f" Cart Assist recorded {cart_attempt_count} guarded attempt(s)."
            self.store.finish_scan_run(run_id, "success", message, len(trips), available_count)
            self.store.update_target_scan_status(watch["target_id"], status)
            next_delay = self._schedule_next_scan(watch)
            self.store.clear_scan_checkpoint(watch["id"])
            self._log_scan_event(
                run_id,
                watch,
                "info",
                "finished",
                f"{message} Next scan is scheduled in about {next_delay} minute(s).",
            )
            return {
                "status": "success",
                "message": message,
                "candidate_count": len(trips),
                "available_count": available_count,
                "missing_count": missing_count,
            }
        except ScanCancelled:
            message = "Scan stopped by user."
            self.store.finish_scan_run(run_id, "cancelled", message, len(trips), available_count)
            self.store.update_target_scan_status(watch["target_id"], "cancelled")
            next_delay = self._schedule_next_scan(watch)
            self._log_scan_event(
                run_id,
                watch,
                "warning",
                "cancelled",
                f"{message} Next scan is scheduled in about {next_delay} minute(s).",
            )
            return {
                "status": "cancelled",
                "message": message,
                "candidate_count": len(trips),
                "available_count": available_count,
                "missing_count": missing_count,
            }
        except RateLimitError as exc:
            self._start_rate_limit_backoff(exc, provider)
            backoff_minutes = self._rate_limit_remaining_minutes(provider) or self.rate_limit_backoff_minutes
            message = f"{provider_label} returned HTTP 429; pausing this provider for about {backoff_minutes} minute(s)."
            self.store.finish_scan_run(run_id, "rate_limited", message, len(trips), available_count)
            self.store.update_target_scan_status(watch["target_id"], "rate_limited")
            self.store.schedule_next_scan(watch["id"], backoff_minutes)
            self._log_scan_event(run_id, watch, "warning", "rate_limited", message)
            if pending_results:
                try:
                    await self._notify_pending_results(pending_results)
                except Exception:
                    logging.getLogger(__name__).exception("Notification failed for partial scan results")
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
            self._log_scan_event(run_id, watch, "error", "error", str(exc))
            raise
        finally:
            request_cancel_check.reset(cancel_token)
            self._clear_active_run(run_id)

    async def _notify_pending_results(self, results: dict[int, dict]) -> int:
        self._raise_if_cancel_requested()
        # Recheck user actions after fetching later stays or awaiting Cart Assist.
        pending_ids = self.store.pending_notification_ids(results)
        pending = [result for result_id, result in results.items() if result_id in pending_ids]
        if not pending:
            return 0
        notified = await self.notifier.notify_results(pending, self.store, self.max_notification_results)
        # A completed no-channel call consumes the alert too; later configuration
        # must not turn historical matches into a new notification backlog.
        self.store.complete_result_notifications(pending_ids)
        return notified if isinstance(notified, int) else len(pending)

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
        started = clock.monotonic()
        try:
            campsites = await self.client.monthly_availability(campground_id, month)
        finally:
            self._last_api_request_at = datetime.now(UTC)
            self._request_seconds = 0.8 * self._request_seconds + 0.2 * (clock.monotonic() - started)
        self._availability_cache[key] = (datetime.now(UTC), campsites)
        return campsites

    async def _with_equipment(self, campground_id: str, site: Campsite) -> Campsite:
        key = (campground_id, site.campsite_id)
        cached = self._equipment_cache.get(key)
        if cached and datetime.now(UTC) - cached[0] < timedelta(hours=24):
            return replace(site, **cached[1])
        await self._wait_for_api_slot("recreation")
        if self._active_run_id is not None:
            self.store.log_scan_event(self._active_run_id, self._active_watch_id, self._active_target_id,
                                      "info", "provider_request", "Checking Recreation.gov campsite equipment compatibility.")
        try:
            metadata = await self.client.campsite_equipment(campground_id, site.campsite_id)
        finally:
            self._last_api_request_at = datetime.now(UTC)
        if len(self._equipment_cache) >= 2000:
            self._equipment_cache.pop(next(iter(self._equipment_cache)))
        self._equipment_cache[key] = (datetime.now(UTC), metadata)
        return replace(site, **metadata)

    async def _trip_availability(self, campground_id: str, trip: TripWindow) -> list[Campsite]:
        provider = provider_key(campground_id)
        if hasattr(self.client, "ensure_provider_access"):
            await self.client.ensure_provider_access(campground_id)
        elif provider == "goingtocamp" and hasattr(self.client, "washington"):
            await self.client.washington.ensure_access()
        key = (campground_id, trip.arrival_date, trip.departure_date)
        cached = self._trip_cache.get(key)
        if cached and self.availability_cache_minutes > 0 and datetime.now(UTC) - cached[0] <= timedelta(minutes=self.availability_cache_minutes):
            return cached[1]
        async def before_request(stage: str = "Checking stay availability") -> None:
            await self._wait_for_api_slot(provider)
            if self._active_run_id is not None:
                self.store.log_scan_event(self._active_run_id, self._active_watch_id, self._active_target_id,
                                          "info", "provider_request", f"{provider_name(campground_id)}: {stage}.")
        started = clock.monotonic()
        try:
            sites = await self.client.trip_availability(campground_id, trip.arrival_date, trip.departure_date,
                                                        before_request=before_request)
        finally:
            self._provider_last_request[provider] = datetime.now(UTC)
            self._request_seconds = 0.8 * self._request_seconds + 0.2 * (clock.monotonic() - started)
        self._trip_cache[key] = (datetime.now(UTC), sites)
        return sites

    async def _wait_for_api_slot(self, provider: str = "recreation") -> None:
        self._raise_if_cancel_requested()
        if self._shared_requests:
            return
        delay = self.effective_request_delay if provider == "recreation" else max(self.api_request_delay_seconds, self._provider_backoffs.get(provider, {}).get("delay", 0))
        if delay <= 0:
            return
        now = datetime.now(UTC)
        last_request = self._last_api_request_at if provider == "recreation" else self._provider_last_request.get(provider)
        if last_request is not None:
            elapsed = (now - last_request).total_seconds()
            remaining = delay - elapsed
            while remaining > 0:
                await asyncio.sleep(min(remaining, 1))
                self._raise_if_cancel_requested()
                remaining = delay - (datetime.now(UTC) - last_request).total_seconds()
        self._raise_if_cancel_requested()
        if provider == "recreation":
            self._last_api_request_at = datetime.now(UTC)
        else:
            self._provider_last_request[provider] = datetime.now(UTC)

    def _raise_if_cancel_requested(self) -> None:
        if self._cancel_requested:
            raise ScanCancelled

    def _clear_active_run(self, run_id: int) -> None:
        if self._active_run_id != run_id:
            return
        self._active_run_id = None
        self._active_watch_id = None
        self._active_target_id = None
        self._cancel_requested = False

    def _log_scan_event(
        self,
        run_id: int,
        watch: dict,
        level: str,
        event_type: str,
        message: str,
    ) -> None:
        self.store.log_scan_event(run_id, watch["id"], watch["target_id"], level, event_type, message)

    def _start_rate_limit_backoff(self, exc: RateLimitError, provider: str = "recreation") -> None:
        if getattr(exc, "cooldown_recorded", False):
            return
        if provider != "recreation":
            state = self._provider_backoffs.setdefault(provider, {})
            state["streak"] = state.get("streak", 0) + 1
            state["delay"] = min(60, max(5, self.api_request_delay_seconds, state.get("delay", 0)) * 2)
            seconds = max(exc.retry_after_seconds or 0, min(86400, self.rate_limit_backoff_minutes * 60 * 2 ** min(state["streak"] - 1, 8)))
            state["until"] = (datetime.now(UTC) + timedelta(seconds=seconds)).isoformat()
            self._save_runtime()
            return
        self._rate_limit_streak += 1
        self._adaptive_delay = min(60, max(5, self.effective_request_delay * 2))
        seconds = max(exc.retry_after_seconds or 0, min(86400, self.rate_limit_backoff_minutes * 60 * 2 ** min(self._rate_limit_streak - 1, 8)))
        self._api_backoff_until = datetime.now(UTC) + timedelta(seconds=seconds)
        self._save_runtime()

    def _rate_limit_remaining_minutes(self, provider: str = "recreation") -> int | None:
        seconds = self._rate_limit_remaining_seconds(provider)
        return max(1, math.ceil(seconds / 60)) if seconds else None

    def _rate_limit_remaining_seconds(self, provider: str) -> int:
        if provider != "recreation":
            until = self._provider_backoffs.get(provider, {}).get("until")
            deadline = datetime.fromisoformat(until) if until else None
        else:
            deadline = self._api_backoff_until
        return max(0, math.ceil((deadline - datetime.now(UTC)).total_seconds())) if deadline else 0


class ScanCancelled(Exception):
    pass
