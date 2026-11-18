"""Calendar-based digest windows; Pacific time follows PST/PDT transitions."""
from datetime import UTC, datetime, time, timedelta
import os
from pathlib import Path
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def validate_schedule(values: dict) -> None:
    if values.get("digest_frequency") is not None and values["digest_frequency"] not in {"daily", "weekly", "disabled"}:
        raise ValueError("Digest frequency must be daily, weekly, or disabled")
    if values.get("digest_timezone") is not None and values["digest_timezone"] not in {"America/Los_Angeles", "server", "UTC"}:
        raise ValueError("Digest timezone must be Pacific, server, or UTC")
    if values.get("digest_time") is not None and not re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", str(values["digest_time"])):
        raise ValueError("Digest time must use HH:MM in 24-hour time")
    for key, low, high in (("digest_weekday", 0, 6), ("home_assistant_error_cooldown_minutes", 1, 10080)):
        if values.get(key) is not None:
            try:
                number = int(values[key])
                if not low <= number <= high:
                    raise ValueError()
            except (ValueError, TypeError):
                raise ValueError(f"{key} is outside its allowed range") from None
    if values.get("home_assistant_errors_enabled") is not None and str(values["home_assistant_errors_enabled"]).lower() not in {"true", "false", "1", "0"}:
        raise ValueError("Home Assistant error reporting must be enabled or disabled")


def schedule_zone(name: str):
    if name != "server":
        return ZoneInfo(name)
    if os.environ.get("TZ"):
        try:
            return ZoneInfo(os.environ["TZ"].lstrip(":"))
        except ZoneInfoNotFoundError:
            pass
    localtime = Path("/etc/localtime")
    if localtime.is_file():
        with localtime.open("rb") as source:
            return ZoneInfo.from_file(source, key="server")
    return datetime.now().astimezone().tzinfo or UTC


def digest_schedule(config: dict, now: datetime) -> dict:
    validate_schedule(config)
    zone = schedule_zone(config["digest_timezone"])
    local = now.astimezone(zone)
    label = (f"Server ({local.tzname()})" if config["digest_timezone"] == "server" else config["digest_timezone"])
    if config["digest_frequency"] == "disabled":
        return {"timezone_label": label, "next_digest_at": None}
    days = 7 if config["digest_frequency"] == "weekly" else 1
    day = local.date()
    if days == 7:
        day -= timedelta(days=(day.weekday() - int(config["digest_weekday"])) % 7)

    def occurrence(day):
        requested = datetime.combine(day, time.fromisoformat(config["digest_time"]), zone)
        # Spring gaps move forward by the DST gap; fall repeats use the first occurrence.
        return requested.astimezone(UTC).astimezone(zone)

    due = occurrence(day)
    if due.astimezone(UTC) > now.astimezone(UTC):
        day -= timedelta(days=days)
        due = occurrence(day)
    next_due = occurrence(day + timedelta(days=days))
    end = datetime.combine(day, time.min, zone)
    start = datetime.combine(day - timedelta(days=days), time.min, zone)
    return {"timezone_label": label, "next_digest_at": next_due.isoformat(),
            "due_at": due.isoformat(), "period_start": start.isoformat(), "period_end": end.isoformat()}
