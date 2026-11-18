"""Digest and Home Assistant error delivery, independent of long-running scans."""
import asyncio
from datetime import UTC, datetime, timedelta
import json

from .alert_schedule import digest_schedule
from .provider_ids import provider_key


RUNTIME_KEY = "notification_dispatch_runtime"


class AlertDispatcher:
    def __init__(self, store, notifier):
        self.store, self.notifier = store, notifier
        self._lock = asyncio.Lock()

    def initialize(self, now=None):
        self.store.recover_notification_dispatches()
        config = self.notifier._effective_config()
        self._prepare_runtime(config, self.notifier.configured_channels(config), now or datetime.now(UTC))

    def _prepare_runtime(self, config, channels, now):
        raw = self.store.get_app_settings([RUNTIME_KEY]).get(RUNTIME_KEY)
        runtime = json.loads(raw) if raw else {}
        updated_at = self.store.notification_settings_updated_at()
        changed_at = None
        if runtime and updated_at and updated_at > (runtime.get("settings_updated_at") or ""):
            changed_at = min(datetime.fromisoformat(updated_at), now).isoformat()
        signature = [config[key] for key in ("digest_frequency", "digest_time", "digest_timezone", "digest_weekday")]
        signature.append(channels)
        if runtime.get("schedule") != signature:
            # A save just before delivery remains eligible on the next worker tick.
            runtime.update(schedule=signature, schedule_since=changed_at or now.isoformat())
        errors_enabled = bool(config["home_assistant_errors_enabled"] and "home_assistant" in channels)
        if "error_cursor" not in runtime or errors_enabled != runtime.get("errors_enabled"):
            runtime["error_cursor"] = self.store.latest_scan_event_id(before=changed_at if errors_enabled else None)
        runtime["errors_enabled"] = errors_enabled
        runtime["settings_updated_at"] = updated_at
        self._save(runtime)
        return runtime

    async def dispatch_due(self, now=None):
        async with self._lock:
            now = now or datetime.now(UTC)
            config = self.notifier._effective_config()
            channels = self.notifier.configured_channels(config)
            runtime = self._prepare_runtime(config, channels, now)

            if runtime["errors_enabled"]:
                await self._errors(runtime, config, now)
            else:
                runtime["error_cursor"] = self.store.latest_scan_event_id()

            schedule = digest_schedule(config, now)
            if channels and schedule.get("due_at") and datetime.fromisoformat(schedule["due_at"]) >= datetime.fromisoformat(runtime["schedule_since"]):
                await self._digest(config, channels, schedule, now)
            if runtime.get("pruned_on") != now.date().isoformat():
                await asyncio.to_thread(self.store.prune_alert_history, (now - timedelta(days=90)).isoformat())
                runtime["pruned_on"] = now.date().isoformat()
            self._save(runtime)

    def _save(self, runtime):
        self.store.set_app_settings({RUNTIME_KEY: json.dumps(runtime)})

    async def _digest(self, config, channels, schedule, now):
        start, end = (datetime.fromisoformat(schedule[key]) for key in ("period_start", "period_end"))
        key = f"digest:{config['digest_frequency']}:{config['digest_timezone']}:{end.date()}"
        attempted = self.store.notification_dispatch_channels(key)
        channels = [channel for channel in channels if channel not in attempted]
        if not channels:
            return
        summary = await asyncio.to_thread(self.store.digest_summary, start.astimezone(UTC).isoformat(),
                                          end.astimezone(UTC).isoformat(), int(config["max_notification_results"]))
        label = f"{start.date()} to {(end - timedelta(days=1)).date()}"
        lines = [f"Camp Finder {config['digest_frequency']} digest: {label}",
                 f"{summary['match_count']} new or returning matches at {summary['campground_count']} campgrounds."]
        included = 0
        for group in summary["groups"]:
            line = f"- {group['park_name'][:100]} / {group['campground_name'][:120]}: {group['arrival_date']} to {group['departure_date']} ({group['match_count']} matches)"
            if sum(map(len, lines)) + len(line) > 1500:
                break
            lines.append(line)
            included += 1
        if summary["group_count"] > included:
            lines.append(f"...and {summary['group_count'] - included} more date/campground groups.")
        lines.extend(["Availability may have changed since discovery.", f"Review: {config['app_base_url']}"])
        message = "\n".join(lines)
        payload = {"source": "camp_finder", "event": "digest", "type": "alert", "alert_type": "digest",
                   "severity": "info", "event_id": key, "frequency": config["digest_frequency"],
                   "occurred_at": now.isoformat(), "period_start": schedule["period_start"],
                   "period_end": schedule["period_end"], "timezone": schedule["timezone_label"],
                   "message": message, "app_url": config["app_base_url"], **summary}
        for channel in channels:
            await self._deliver(key, channel, "digest", message, payload, config, now)

    async def _errors(self, runtime, config, now):
        events = self.store.error_events_after(runtime["error_cursor"])
        for event in events:
            provider = provider_key(event["campground_id"]) if event["campground_id"] else "server"
            kind = "provider_rate_limited" if event["event_type"] == "rate_limited" else "scan_failed"
            reason = "Provider rate limit; crawling is waiting for cooldown." if kind == "provider_rate_limited" else "Campground scan failed; availability is unknown. Check Logs for diagnostics."
            message = f"Camp Finder: {event['target_name'] or provider}. {reason}"
            key = f"scan-error:{event['id']}"
            payload = {"source": "camp_finder", "event": "error", "type": "error", "error_type": kind,
                       "severity": "warning" if kind == "provider_rate_limited" else "error",
                       "event_id": key, "occurred_at": event["created_at"], "provider": provider,
                       "watch_id": event["watch_id"], "target_id": event["target_id"],
                       "message": message, "app_url": config["app_base_url"],
                       "logs_url": config["app_base_url"].rstrip("/") + "/#logs"}
            await self._deliver(key, "home_assistant", kind, message, payload, config, now,
                                f"{provider}:{kind}", (now - timedelta(minutes=config["home_assistant_error_cooldown_minutes"])).isoformat())
            runtime["error_cursor"] = event["id"]
            self._save(runtime)

    async def _deliver(self, key, channel, kind, message, payload, config, now, group="", since=None):
        dispatch_id = self.store.claim_notification_dispatch(key, channel, kind, message, now.isoformat(), group, since)
        if dispatch_id is None:
            return
        try:
            result = await self.notifier.send_event(channel, message, payload, config)
        except Exception as exc:
            result = {"status": "error", "message": self.notifier._delivery_error(exc)}
        self.store.finish_notification_dispatch(dispatch_id, result["status"], f"{kind}: {result['message']}")
