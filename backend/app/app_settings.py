from __future__ import annotations

from typing import Any


HOME_ASSISTANT_WEBHOOK_KEY = "home_assistant_webhook_url"

SCAN_APP_SETTING_KEYS = [
    "scan_min_poll_interval_minutes",
    "scan_release_scan_before_minutes",
    "scan_release_scan_after_minutes",
    "scan_release_scan_interval_minutes",
    "scan_availability_cache_minutes",
    "scan_api_request_delay_seconds",
    "scan_rate_limit_backoff_minutes",
]

CART_ASSIST_APP_SETTING_KEYS = [
    "cart_assist_enabled",
    "cart_assist_cooldown_minutes",
    "cart_assist_max_attempts_per_scan",
    "recreation_gov_username",
    "recreation_gov_password",
]

NOTIFICATION_CONFIG_FIELDS: dict[str, dict[str, Any]] = {
    "webhook_url": {
        "setting_key": "notification_webhook_url",
        "env_name": "CAMPFINDER_WEBHOOK_URL",
        "kind": "string",
        "secret": True,
    },
    "home_assistant_webhook_url": {
        "setting_key": HOME_ASSISTANT_WEBHOOK_KEY,
        "env_name": "CAMPFINDER_HOME_ASSISTANT_WEBHOOK_URL",
        "kind": "string",
        "secret": True,
    },
    "ntfy_server": {
        "setting_key": "notification_ntfy_server",
        "env_name": "CAMPFINDER_NTFY_SERVER",
        "kind": "string",
        "secret": False,
    },
    "ntfy_topic": {
        "setting_key": "notification_ntfy_topic",
        "env_name": "CAMPFINDER_NTFY_TOPIC",
        "kind": "string",
        "secret": True,
    },
    "ntfy_token": {
        "setting_key": "notification_ntfy_token",
        "env_name": "CAMPFINDER_NTFY_TOKEN",
        "kind": "string",
        "secret": True,
    },
    "ntfy_priority": {
        "setting_key": "notification_ntfy_priority",
        "env_name": "CAMPFINDER_NTFY_PRIORITY",
        "kind": "string",
        "secret": False,
    },
    "smtp_host": {
        "setting_key": "notification_smtp_host",
        "env_name": "CAMPFINDER_SMTP_HOST",
        "kind": "string",
        "secret": False,
    },
    "smtp_port": {
        "setting_key": "notification_smtp_port",
        "env_name": "CAMPFINDER_SMTP_PORT",
        "kind": "int",
        "minimum": 1,
        "maximum": 65535,
        "secret": False,
    },
    "smtp_username": {
        "setting_key": "notification_smtp_username",
        "env_name": "CAMPFINDER_SMTP_USERNAME",
        "kind": "string",
        "secret": True,
    },
    "smtp_password": {
        "setting_key": "notification_smtp_password",
        "env_name": "CAMPFINDER_SMTP_PASSWORD",
        "kind": "string",
        "secret": True,
    },
    "smtp_from": {
        "setting_key": "notification_smtp_from",
        "env_name": "CAMPFINDER_SMTP_FROM",
        "kind": "string",
        "secret": False,
    },
    "smtp_to": {
        "setting_key": "notification_smtp_to",
        "env_name": "CAMPFINDER_SMTP_TO",
        "kind": "string",
        "secret": False,
    },
    "max_notification_results": {
        "setting_key": "notification_max_notification_results",
        "env_name": "CAMPFINDER_MAX_NOTIFICATION_RESULTS",
        "kind": "int",
        "minimum": 1,
        "maximum": 100,
        "secret": False,
    },
}

NOTIFICATION_APP_SETTING_KEYS = [
    str(field["setting_key"]) for field in NOTIFICATION_CONFIG_FIELDS.values()
]
NOTIFICATION_SECRET_SETTING_KEYS = [
    str(field["setting_key"])
    for field in NOTIFICATION_CONFIG_FIELDS.values()
    if bool(field.get("secret"))
]

EXPORTABLE_APP_SETTING_KEYS = sorted(
    set(SCAN_APP_SETTING_KEYS + CART_ASSIST_APP_SETTING_KEYS + NOTIFICATION_APP_SETTING_KEYS)
)

SECRET_APP_SETTING_KEYS = sorted(
    {
        "recreation_gov_username",
        "recreation_gov_password",
        *NOTIFICATION_SECRET_SETTING_KEYS,
    }
)
