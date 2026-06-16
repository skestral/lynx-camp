from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {key: row[key] for key in row.keys()}


def _normalize_release_window_unit(value: Any) -> str:
    normalized = str(value or "Months").strip().lower()
    if normalized in {"day", "days"}:
        return "Days"
    if normalized in {"week", "weeks"}:
        return "Weeks"
    return "Months"


class Store:
    def __init__(self, database_path: Path):
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self) -> Iterable[sqlite3.Connection]:
        conn = sqlite3.connect(self.database_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def init(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS targets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    campground_id TEXT NOT NULL UNIQUE,
                    park_name TEXT NOT NULL DEFAULT '',
                    state_code TEXT NOT NULL DEFAULT '',
                    booking_url TEXT NOT NULL,
                    release_months INTEGER NOT NULL DEFAULT 6,
                    release_window_value INTEGER NOT NULL DEFAULT 6,
                    release_window_unit TEXT NOT NULL DEFAULT 'Months',
                    release_time TEXT NOT NULL DEFAULT '07:00',
                    timezone TEXT NOT NULL DEFAULT 'America/Los_Angeles',
                    poll_interval_minutes INTEGER NOT NULL DEFAULT 10,
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_checked_at TEXT,
                    last_status TEXT NOT NULL DEFAULT 'pending'
                );

                CREATE TABLE IF NOT EXISTS watches (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    target_id INTEGER NOT NULL REFERENCES targets(id) ON DELETE CASCADE,
                    name TEXT NOT NULL,
                    mode TEXT NOT NULL CHECK(mode IN ('weekend', 'specific')),
                    pattern TEXT NOT NULL DEFAULT 'fri-sun',
                    arrival_weekdays_json TEXT,
                    site_filters_json TEXT,
                    nights INTEGER NOT NULL DEFAULT 2,
                    window_start TEXT NOT NULL,
                    window_end TEXT NOT NULL,
                    specific_ranges_json TEXT NOT NULL DEFAULT '[]',
                    active INTEGER NOT NULL DEFAULT 1,
                    next_scan_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS scan_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    watch_id INTEGER NOT NULL REFERENCES watches(id) ON DELETE CASCADE,
                    target_id INTEGER NOT NULL REFERENCES targets(id) ON DELETE CASCADE,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    status TEXT NOT NULL,
                    message TEXT NOT NULL DEFAULT '',
                    candidate_count INTEGER NOT NULL DEFAULT 0,
                    available_count INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    watch_id INTEGER NOT NULL REFERENCES watches(id) ON DELETE CASCADE,
                    target_id INTEGER NOT NULL REFERENCES targets(id) ON DELETE CASCADE,
                    campground_id TEXT NOT NULL,
                    campground_name TEXT NOT NULL,
                    campsite_id TEXT NOT NULL,
                    site TEXT NOT NULL,
                    loop TEXT NOT NULL DEFAULT '',
                    campsite_type TEXT NOT NULL DEFAULT '',
                    arrival_date TEXT NOT NULL,
                    departure_date TEXT NOT NULL,
                    booking_url TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'available',
                    opened_at TEXT,
                    booked_at TEXT,
                    dismissed_at TEXT,
                    discovered_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1,
                    dedupe_key TEXT NOT NULL UNIQUE
                );

                CREATE TABLE IF NOT EXISTS notification_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    result_id INTEGER NOT NULL REFERENCES results(id) ON DELETE CASCADE,
                    channel TEXT NOT NULL,
                    status TEXT NOT NULL,
                    message TEXT NOT NULL,
                    sent_at TEXT NOT NULL
                );
                """
            )
            self._ensure_column(conn, "watches", "arrival_weekdays_json", "TEXT")
            self._ensure_column(conn, "watches", "site_filters_json", "TEXT")
            self._ensure_column(conn, "targets", "release_window_value", "INTEGER NOT NULL DEFAULT 6")
            self._ensure_column(conn, "targets", "release_window_unit", "TEXT NOT NULL DEFAULT 'Months'")
            self._ensure_column(conn, "results", "opened_at", "TEXT")
            self._ensure_column(conn, "results", "booked_at", "TEXT")
            self._ensure_column(conn, "results", "dismissed_at", "TEXT")

    @staticmethod
    def _ensure_column(conn: sqlite3.Connection, table_name: str, column_name: str, definition: str) -> None:
        columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}
        if column_name not in columns:
            conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")

    def list_targets(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM targets ORDER BY active DESC, name").fetchall()
            return [_row_to_dict(row) for row in rows if row is not None]

    def delete_target(self, target_id: int) -> bool:
        with self.connect() as conn:
            cursor = conn.execute("DELETE FROM targets WHERE id = ?", (target_id,))
            return cursor.rowcount > 0

    def update_target(self, target_id: int, data: dict[str, Any], min_poll_interval_minutes: int = 10) -> dict[str, Any] | None:
        current = self.get_target(target_id)
        if current is None:
            return None
        merged = {**current, **{key: value for key, value in data.items() if value is not None}}
        if "release_months" in data and "release_window_value" not in data:
            merged["release_window_value"] = data["release_months"]
            merged["release_window_unit"] = data.get("release_window_unit") or "Months"
        if "release_window_value" not in merged or merged.get("release_window_value") is None:
            merged["release_window_value"] = merged.get("release_months") or 6
        merged["release_window_unit"] = _normalize_release_window_unit(merged.get("release_window_unit") or "Months")
        if merged["release_window_unit"] == "Months":
            merged["release_months"] = int(merged.get("release_window_value") or 6)
        merged["poll_interval_minutes"] = max(int(merged.get("poll_interval_minutes") or 10), min_poll_interval_minutes)
        now = utc_now()
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE targets
                SET name = ?, park_name = ?, state_code = ?, booking_url = ?, release_months = ?,
                    release_window_value = ?, release_window_unit = ?,
                    release_time = ?, timezone = ?, poll_interval_minutes = ?, active = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    merged["name"],
                    merged.get("park_name") or "",
                    merged.get("state_code") or "",
                    merged.get("booking_url") or f"https://www.recreation.gov/camping/campgrounds/{merged['campground_id']}",
                    int(merged.get("release_months") or 6),
                    int(merged.get("release_window_value") or 6),
                    merged["release_window_unit"],
                    merged.get("release_time") or "07:00",
                    merged.get("timezone") or "America/Los_Angeles",
                    int(merged.get("poll_interval_minutes") or 10),
                    1 if merged.get("active", True) else 0,
                    now,
                    target_id,
                ),
            )
        return self.get_target(target_id)

    def get_target(self, target_id: int) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM targets WHERE id = ?", (target_id,)).fetchone()
            return _row_to_dict(row)

    def get_target_by_campground_id(self, campground_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM targets WHERE campground_id = ?", (campground_id,)).fetchone()
            return _row_to_dict(row)

    def create_target(self, data: dict[str, Any], min_poll_interval_minutes: int = 10) -> dict[str, Any]:
        now = utc_now()
        poll_interval = max(int(data.get("poll_interval_minutes") or 10), min_poll_interval_minutes)
        booking_url = data.get("booking_url") or f"https://www.recreation.gov/camping/campgrounds/{data['campground_id']}"
        release_window_value = int(data.get("release_window_value") or data.get("release_months") or 6)
        release_window_unit = _normalize_release_window_unit(data.get("release_window_unit") or "Months")
        release_months = release_window_value if release_window_unit == "Months" else int(data.get("release_months") or 6)
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO targets (
                    name, campground_id, park_name, state_code, booking_url, release_months,
                    release_window_value, release_window_unit, release_time, timezone, poll_interval_minutes,
                    active, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(campground_id) DO UPDATE SET
                    name = excluded.name,
                    park_name = excluded.park_name,
                    state_code = excluded.state_code,
                    booking_url = excluded.booking_url,
                    release_months = excluded.release_months,
                    release_window_value = excluded.release_window_value,
                    release_window_unit = excluded.release_window_unit,
                    release_time = excluded.release_time,
                    timezone = excluded.timezone,
                    poll_interval_minutes = excluded.poll_interval_minutes,
                    active = 1,
                    updated_at = excluded.updated_at
                """,
                (
                    data["name"],
                    data["campground_id"],
                    data.get("park_name") or "",
                    data.get("state_code") or "",
                    booking_url,
                    release_months,
                    release_window_value,
                    release_window_unit,
                    data.get("release_time") or "07:00",
                    data.get("timezone") or "America/Los_Angeles",
                    poll_interval,
                    1 if data.get("active", True) else 0,
                    now,
                    now,
                ),
            )
            row = conn.execute("SELECT * FROM targets WHERE campground_id = ?", (data["campground_id"],)).fetchone()
            return _row_to_dict(row) or {}

    def list_watches(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    watches.*,
                    targets.name AS target_name,
                    targets.campground_id,
                    targets.park_name,
                    targets.state_code,
                    targets.release_months,
                    targets.release_window_value,
                    targets.release_window_unit,
                    targets.release_time,
                    targets.timezone,
                    targets.poll_interval_minutes,
                    targets.active AS target_active,
                    targets.last_checked_at,
                    targets.last_status
                FROM watches
                JOIN targets ON targets.id = watches.target_id
                ORDER BY watches.active DESC, watches.created_at DESC
                """
            ).fetchall()
            return [self._inflate_watch(_row_to_dict(row) or {}) for row in rows]

    def create_watch(self, data: dict[str, Any]) -> dict[str, Any]:
        now = utc_now()
        specific_ranges = data.get("specific_ranges") or []
        arrival_weekdays = data.get("arrival_weekdays")
        site_filters = data.get("site_filters") or {}
        with self.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO watches (
                    target_id, name, mode, pattern, nights, window_start, window_end,
                    arrival_weekdays_json, site_filters_json, specific_ranges_json,
                    active, next_scan_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(data["target_id"]),
                    data["name"],
                    data["mode"],
                    data.get("pattern") or "fri-sun",
                    int(data.get("nights") or 2),
                    data["window_start"],
                    data["window_end"],
                    json.dumps(arrival_weekdays) if arrival_weekdays is not None else None,
                    json.dumps(site_filters),
                    json.dumps(specific_ranges),
                    1 if data.get("active", True) else 0,
                    now,
                    now,
                    now,
                ),
            )
            watch_id = int(cursor.lastrowid)
        return self.get_watch(watch_id) or {}

    def get_watch_by_target_and_name(self, target_id: int, name: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT id FROM watches WHERE target_id = ? AND name = ? ORDER BY id LIMIT 1",
                (target_id, name),
            ).fetchone()
        return self.get_watch(int(row["id"])) if row else None

    def get_watch(self, watch_id: int) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT
                    watches.*,
                    targets.name AS target_name,
                    targets.campground_id,
                    targets.park_name,
                    targets.state_code,
                    targets.booking_url AS target_booking_url,
                    targets.release_months,
                    targets.release_window_value,
                    targets.release_window_unit,
                    targets.release_time,
                    targets.timezone,
                    targets.poll_interval_minutes,
                    targets.active AS target_active,
                    targets.last_checked_at,
                    targets.last_status
                FROM watches
                JOIN targets ON targets.id = watches.target_id
                WHERE watches.id = ?
                """,
                (watch_id,),
            ).fetchone()
            return self._inflate_watch(_row_to_dict(row) or {}) if row else None

    def delete_watch(self, watch_id: int) -> bool:
        with self.connect() as conn:
            cursor = conn.execute("DELETE FROM watches WHERE id = ?", (watch_id,))
            return cursor.rowcount > 0

    def export_config(self) -> dict[str, Any]:
        target_fields = [
            "name",
            "campground_id",
            "park_name",
            "state_code",
            "booking_url",
            "release_months",
            "release_window_value",
            "release_window_unit",
            "release_time",
            "timezone",
            "poll_interval_minutes",
        ]
        watch_fields = [
            "name",
            "mode",
            "pattern",
            "arrival_weekdays",
            "nights",
            "window_start",
            "window_end",
            "site_filters",
            "specific_ranges",
        ]
        targets = {
            target["id"]: {
                **{field: target.get(field) for field in target_fields},
                "active": bool(target.get("active", True)),
                "watches": [],
            }
            for target in self.list_targets()
        }
        for watch in self.list_watches():
            target = targets.get(watch["target_id"])
            if target is None:
                continue
            target["watches"].append(
                {
                    **{field: watch.get(field) for field in watch_fields},
                    "active": bool(watch.get("active", True)),
                }
            )
        return {"version": 1, "exported_at": utc_now(), "targets": list(targets.values())}

    def import_config(self, config: dict[str, Any], min_poll_interval_minutes: int = 10) -> dict[str, int]:
        targets = config.get("targets") if isinstance(config, dict) else None
        if not isinstance(targets, list):
            raise ValueError("config must include a targets list")

        imported_targets = 0
        updated_targets = 0
        created_watches = 0
        updated_watches = 0

        for target_config in targets:
            if not isinstance(target_config, dict):
                raise ValueError("each target must be an object")
            watches = target_config.get("watches", [])
            if not isinstance(watches, list):
                raise ValueError("target watches must be a list")

            campground_id = str(target_config.get("campground_id") or "").strip()
            name = str(target_config.get("name") or "").strip()
            if not campground_id or not name:
                raise ValueError("each target must include name and campground_id")

            target_payload = {
                "name": name,
                "campground_id": campground_id,
                "park_name": target_config.get("park_name") or "",
                "state_code": target_config.get("state_code") or "",
                "booking_url": target_config.get("booking_url")
                or f"https://www.recreation.gov/camping/campgrounds/{campground_id}",
                "release_months": target_config.get("release_months", 6),
                "release_window_value": target_config.get(
                    "release_window_value", target_config.get("release_months", 6)
                ),
                "release_window_unit": target_config.get("release_window_unit") or "Months",
                "release_time": target_config.get("release_time") or "07:00",
                "timezone": target_config.get("timezone") or "America/Los_Angeles",
                "poll_interval_minutes": target_config.get("poll_interval_minutes", 10),
                "active": bool(target_config.get("active", True)),
            }
            existing_target = self.get_target_by_campground_id(campground_id)
            target = self.create_target(target_payload, min_poll_interval_minutes)
            target = self.update_target(target["id"], target_payload, min_poll_interval_minutes) or target
            if existing_target:
                updated_targets += 1
            else:
                imported_targets += 1

            for watch_config in watches:
                if not isinstance(watch_config, dict):
                    raise ValueError("each watch must be an object")
                watch_name = str(watch_config.get("name") or "").strip()
                if not watch_name:
                    raise ValueError("each watch must include name")
                watch_payload = {
                    "target_id": target["id"],
                    "name": watch_name,
                    "mode": watch_config.get("mode") or "weekend",
                    "pattern": watch_config.get("pattern") or "fri-sun",
                    "arrival_weekdays": watch_config.get("arrival_weekdays"),
                    "nights": watch_config.get("nights", 2),
                    "window_start": watch_config.get("window_start"),
                    "window_end": watch_config.get("window_end"),
                    "site_filters": watch_config.get("site_filters") or {},
                    "specific_ranges": watch_config.get("specific_ranges") or [],
                    "active": bool(watch_config.get("active", True)),
                }
                existing_watch = self.get_watch_by_target_and_name(target["id"], watch_name)
                if existing_watch:
                    self.update_watch(existing_watch["id"], watch_payload)
                    updated_watches += 1
                else:
                    self.create_watch(watch_payload)
                    created_watches += 1

        return {
            "target_count": len(targets),
            "imported_targets": imported_targets,
            "updated_targets": updated_targets,
            "created_watches": created_watches,
            "updated_watches": updated_watches,
        }

    def update_watch(self, watch_id: int, data: dict[str, Any]) -> dict[str, Any] | None:
        current = self.get_watch(watch_id)
        if current is None:
            return None
        updates = dict(data)
        if not updates:
            return current

        window_start = updates.get("window_start", current["window_start"])
        window_end = updates.get("window_end", current["window_end"])
        if date.fromisoformat(str(window_end)) < date.fromisoformat(str(window_start)):
            raise ValueError("window_end must be on or after window_start")

        set_parts = []
        values: list[Any] = []
        scalar_fields = [
            "target_id",
            "name",
            "mode",
            "pattern",
            "nights",
            "window_start",
            "window_end",
        ]
        for field_name in scalar_fields:
            if field_name in updates:
                set_parts.append(f"{field_name} = ?")
                values.append(updates[field_name])
        if "arrival_weekdays" in updates:
            set_parts.append("arrival_weekdays_json = ?")
            value = updates["arrival_weekdays"]
            values.append(json.dumps(value) if value is not None else None)
        if "site_filters" in updates:
            set_parts.append("site_filters_json = ?")
            values.append(json.dumps(updates["site_filters"] or {}))
        if "specific_ranges" in updates:
            set_parts.append("specific_ranges_json = ?")
            values.append(json.dumps(updates["specific_ranges"] or []))
        if "active" in updates:
            set_parts.append("active = ?")
            values.append(1 if updates["active"] else 0)
        should_rescan = bool(set(updates) - {"active"}) and bool(updates.get("active", current["active"]))
        if updates.get("active") is True or should_rescan:
            set_parts.append("next_scan_at = ?")
            values.append(utc_now())
        set_parts.append("updated_at = ?")
        values.append(utc_now())
        values.append(watch_id)

        with self.connect() as conn:
            conn.execute(f"UPDATE watches SET {', '.join(set_parts)} WHERE id = ?", values)
        return self.get_watch(watch_id)

    def due_watches(self, limit: int = 5) -> list[dict[str, Any]]:
        now = utc_now()
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT watches.id
                FROM watches
                JOIN targets ON targets.id = watches.target_id
                WHERE watches.active = 1
                  AND targets.active = 1
                  AND (watches.next_scan_at IS NULL OR watches.next_scan_at <= ?)
                ORDER BY watches.next_scan_at IS NULL DESC, watches.next_scan_at ASC
                LIMIT ?
                """,
                (now, limit),
            ).fetchall()
            return [watch for row in rows if (watch := self.get_watch(int(row["id"])))]

    def schedule_next_scan(self, watch_id: int, minutes: int) -> None:
        next_scan = (datetime.now(UTC).replace(microsecond=0) + timedelta(minutes=minutes)).isoformat()
        with self.connect() as conn:
            conn.execute(
                "UPDATE watches SET next_scan_at = ?, updated_at = ? WHERE id = ?",
                (next_scan, utc_now(), watch_id),
            )

    def start_scan_run(self, watch: dict[str, Any]) -> int:
        with self.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO scan_runs (watch_id, target_id, started_at, status)
                VALUES (?, ?, ?, 'running')
                """,
                (watch["id"], watch["target_id"], utc_now()),
            )
            return int(cursor.lastrowid)

    def finish_scan_run(
        self,
        run_id: int,
        status: str,
        message: str,
        candidate_count: int,
        available_count: int,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE scan_runs
                SET finished_at = ?, status = ?, message = ?, candidate_count = ?, available_count = ?
                WHERE id = ?
                """,
                (utc_now(), status, message, candidate_count, available_count, run_id),
            )

    def list_scan_runs(self, limit: int = 25) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    scan_runs.*,
                    watches.name AS watch_name,
                    targets.name AS target_name,
                    targets.campground_id
                FROM scan_runs
                JOIN watches ON watches.id = scan_runs.watch_id
                JOIN targets ON targets.id = scan_runs.target_id
                ORDER BY scan_runs.started_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [_row_to_dict(row) for row in rows if row is not None]

    def update_target_scan_status(self, target_id: int, status: str) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE targets
                SET last_checked_at = ?, last_status = ?, updated_at = ?
                WHERE id = ?
                """,
                (utc_now(), status, utc_now(), target_id),
            )

    def upsert_result(self, data: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        now = utc_now()
        dedupe_key = "|".join(
            [
                str(data["watch_id"]),
                data["campsite_id"],
                data["arrival_date"],
                data["departure_date"],
            ]
        )
        with self.connect() as conn:
            existing = conn.execute("SELECT * FROM results WHERE dedupe_key = ?", (dedupe_key,)).fetchone()
            if existing:
                active = 0 if existing["status"] in {"booked", "dismissed"} else 1
                conn.execute(
                    """
                    UPDATE results
                    SET last_seen_at = ?, active = ?
                    WHERE dedupe_key = ?
                    """,
                    (now, active, dedupe_key),
                )
                row = conn.execute("SELECT * FROM results WHERE dedupe_key = ?", (dedupe_key,)).fetchone()
                return _row_to_dict(row) or {}, False

            conn.execute(
                """
                INSERT INTO results (
                    watch_id, target_id, campground_id, campground_name, campsite_id, site, loop,
                    campsite_type, arrival_date, departure_date, booking_url, discovered_at,
                    last_seen_at, dedupe_key
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    data["watch_id"],
                    data["target_id"],
                    data["campground_id"],
                    data["campground_name"],
                    data["campsite_id"],
                    data["site"],
                    data.get("loop") or "",
                    data.get("campsite_type") or "",
                    data["arrival_date"],
                    data["departure_date"],
                    data["booking_url"],
                    now,
                    now,
                    dedupe_key,
                ),
            )
            row = conn.execute("SELECT * FROM results WHERE dedupe_key = ?", (dedupe_key,)).fetchone()
            return _row_to_dict(row) or {}, True

    def list_results(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    results.*,
                    watches.name AS watch_name,
                    targets.name AS target_name,
                    targets.park_name AS park_name,
                    targets.state_code AS state_code
                FROM results
                JOIN watches ON watches.id = results.watch_id
                JOIN targets ON targets.id = results.target_id
                ORDER BY results.active DESC, results.discovered_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [_row_to_dict(row) for row in rows if row is not None]

    def clear_active_results(self) -> int:
        now = utc_now()
        with self.connect() as conn:
            cursor = conn.execute(
                """
                UPDATE results
                SET status = 'dismissed',
                    active = 0,
                    dismissed_at = COALESCE(dismissed_at, ?)
                WHERE active = 1
                """,
                (now,),
            )
            return cursor.rowcount

    def update_result_status(self, result_id: int, status: str) -> dict[str, Any] | None:
        timestamp_column = {
            "available": None,
            "opened": "opened_at",
            "booked": "booked_at",
            "dismissed": "dismissed_at",
        }.get(status)
        if status not in {"available", "opened", "booked", "dismissed"}:
            raise ValueError(f"unsupported result status {status}")

        active = 1 if status in {"available", "opened"} else 0
        now = utc_now()
        with self.connect() as conn:
            if timestamp_column:
                cursor = conn.execute(
                    f"""
                    UPDATE results
                    SET status = ?,
                        active = ?,
                        {timestamp_column} = COALESCE({timestamp_column}, ?)
                    WHERE id = ?
                    """,
                    (status, active, now, result_id),
                )
            else:
                cursor = conn.execute(
                    """
                    UPDATE results
                    SET status = ?, active = ?, booked_at = NULL, dismissed_at = NULL
                    WHERE id = ?
                    """,
                    (status, active, result_id),
                )
            if cursor.rowcount == 0:
                return None
            row = conn.execute("SELECT * FROM results WHERE id = ?", (result_id,)).fetchone()
            return _row_to_dict(row)

    def record_notification(self, result_id: int, channel: str, status: str, message: str) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO notification_events (result_id, channel, status, message, sent_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (result_id, channel, status, message, utc_now()),
            )

    def list_notifications(self, limit: int = 25) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT notification_events.*, results.site, results.arrival_date, results.departure_date
                FROM notification_events
                JOIN results ON results.id = notification_events.result_id
                ORDER BY notification_events.sent_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [_row_to_dict(row) for row in rows if row is not None]

    @staticmethod
    def _inflate_watch(watch: dict[str, Any]) -> dict[str, Any]:
        if not watch:
            return watch
        try:
            watch["specific_ranges"] = json.loads(watch.get("specific_ranges_json") or "[]")
        except json.JSONDecodeError:
            watch["specific_ranges"] = []
        try:
            watch["arrival_weekdays"] = json.loads(watch.get("arrival_weekdays_json") or "null")
        except json.JSONDecodeError:
            watch["arrival_weekdays"] = None
        try:
            watch["site_filters"] = json.loads(watch.get("site_filters_json") or "{}")
        except json.JSONDecodeError:
            watch["site_filters"] = {}
        watch.pop("specific_ranges_json", None)
        watch.pop("arrival_weekdays_json", None)
        watch.pop("site_filters_json", None)
        return watch
