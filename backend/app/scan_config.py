from __future__ import annotations

from typing import Any

from .db import Store


SCAN_CONFIG_FIELDS: dict[str, dict[str, Any]] = {
    "min_poll_interval_minutes": {
        "setting_key": "scan_min_poll_interval_minutes",
        "kind": "int",
        "minimum": 1,
        "maximum": 1440,
    },
    "release_scan_before_minutes": {
        "setting_key": "scan_release_scan_before_minutes",
        "kind": "int",
        "minimum": 0,
        "maximum": 1440,
    },
    "release_scan_after_minutes": {
        "setting_key": "scan_release_scan_after_minutes",
        "kind": "int",
        "minimum": 0,
        "maximum": 1440,
    },
    "release_scan_interval_minutes": {
        "setting_key": "scan_release_scan_interval_minutes",
        "kind": "int",
        "minimum": 1,
        "maximum": 1440,
    },
    "availability_cache_minutes": {
        "setting_key": "scan_availability_cache_minutes",
        "kind": "int",
        "minimum": 0,
        "maximum": 1440,
    },
    "api_request_delay_seconds": {
        "setting_key": "scan_api_request_delay_seconds",
        "kind": "float",
        "minimum": 0.0,
        "maximum": 60.0,
    },
    "rate_limit_backoff_minutes": {
        "setting_key": "scan_rate_limit_backoff_minutes",
        "kind": "int",
        "minimum": 1,
        "maximum": 1440,
    },
}

SCAN_CONFIG_SETTING_KEYS = [str(field["setting_key"]) for field in SCAN_CONFIG_FIELDS.values()]


def _clamp_number(value: int | float, minimum: int | float, maximum: int | float) -> int | float:
    return max(minimum, min(maximum, value))


def _coerce_value(raw: Any, field: dict[str, Any], default: int | float) -> int | float:
    try:
        if field["kind"] == "float":
            value = float(raw)
        else:
            value = int(raw)
    except (TypeError, ValueError):
        value = default
    value = _clamp_number(value, field["minimum"], field["maximum"])
    if field["kind"] == "float":
        return round(float(value), 2)
    return int(value)


def _format_value(value: int | float, field: dict[str, Any]) -> str:
    if field["kind"] == "float":
        return str(round(float(value), 2))
    return str(int(value))


def scan_config(store: Store, settings: Any) -> dict[str, Any]:
    stored = store.get_app_settings(SCAN_CONFIG_SETTING_KEYS)
    values: dict[str, int | float] = {}
    environment: dict[str, int | float] = {}
    sources: dict[str, str] = {}

    for public_key, field in SCAN_CONFIG_FIELDS.items():
        default = _coerce_value(getattr(settings, public_key), field, 0)
        environment[public_key] = default
        setting_key = str(field["setting_key"])
        if setting_key in stored:
            values[public_key] = _coerce_value(stored[setting_key], field, default)
            sources[public_key] = "appdata"
        else:
            values[public_key] = default
            sources[public_key] = "environment"

    return {"values": values, "sources": sources, "environment": environment}


def update_scan_config(store: Store, settings: Any, updates: dict[str, Any]) -> dict[str, Any]:
    persisted: dict[str, str] = {}
    for public_key, raw_value in updates.items():
        if public_key not in SCAN_CONFIG_FIELDS or raw_value is None:
            continue
        field = SCAN_CONFIG_FIELDS[public_key]
        default = _coerce_value(getattr(settings, public_key), field, 0)
        value = _coerce_value(raw_value, field, default)
        persisted[str(field["setting_key"])] = _format_value(value, field)

    store.set_app_settings(persisted)
    return scan_config(store, settings)


def reset_scan_config(store: Store, settings: Any) -> dict[str, Any]:
    store.delete_app_settings(SCAN_CONFIG_SETTING_KEYS)
    return scan_config(store, settings)
