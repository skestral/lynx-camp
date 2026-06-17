from __future__ import annotations

from typing import Any

from .db import Store


SETTING_KEYS = [
    "cart_assist_enabled",
    "cart_assist_cooldown_minutes",
    "cart_assist_max_attempts_per_scan",
    "recreation_gov_username",
    "recreation_gov_password",
]
CREDENTIAL_KEYS = ["recreation_gov_username", "recreation_gov_password"]


def _bool_setting(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int_setting(value: str | None, default: int, *, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value) if value is not None else int(default)
    except (TypeError, ValueError):
        parsed = int(default)
    return max(minimum, min(maximum, parsed))


class CartAssistant:
    def __init__(self, store: Store, settings: Any):
        self.store = store
        self.settings = settings

    def config(self) -> dict[str, Any]:
        stored = self.store.get_app_settings(SETTING_KEYS)
        enabled = _bool_setting(stored.get("cart_assist_enabled"), bool(self.settings.cart_assist_enabled))
        cooldown_minutes = _int_setting(
            stored.get("cart_assist_cooldown_minutes"),
            int(self.settings.cart_assist_cooldown_minutes),
            minimum=1,
            maximum=1440,
        )
        max_attempts_per_scan = _int_setting(
            stored.get("cart_assist_max_attempts_per_scan"),
            int(self.settings.cart_assist_max_attempts_per_scan),
            minimum=1,
            maximum=25,
        )
        username = stored.get("recreation_gov_username", self.settings.recreation_gov_username or "")
        password = stored.get("recreation_gov_password", self.settings.recreation_gov_password or "")
        return {
            "enabled": enabled,
            "cooldown_minutes": cooldown_minutes,
            "max_attempts_per_scan": max_attempts_per_scan,
            "username": username,
            "password": password,
            "config_source": "appdata" if any(key in stored for key in SETTING_KEYS[:3]) else "environment",
            "credential_source": (
                "appdata"
                if any(key in stored for key in CREDENTIAL_KEYS)
                else "environment"
                if self.settings.recreation_gov_username or self.settings.recreation_gov_password
                else "none"
            ),
        }

    def status(self) -> dict[str, Any]:
        config = self.config()
        credentials_configured = bool(config["username"] and config["password"])
        enabled = bool(config["enabled"])
        ready = enabled and credentials_configured
        if not enabled:
            detail = "Server-side Cart Assist is disabled."
        elif not credentials_configured:
            detail = "Server-side Cart Assist is enabled, but Recreation.gov credentials are missing."
        else:
            detail = "Server-side Cart Assist is configured for high-priority watch rules."

        return {
            "enabled": enabled,
            "ready": ready,
            "credentials_configured": credentials_configured,
            "username_configured": bool(config["username"]),
            "password_configured": bool(config["password"]),
            "cooldown_minutes": config["cooldown_minutes"],
            "max_attempts_per_scan": config["max_attempts_per_scan"],
            "config_source": config["config_source"],
            "credential_source": config["credential_source"],
            "detail": detail,
        }

    def update_config(self, data: dict[str, Any]) -> dict[str, Any]:
        updates: dict[str, str] = {}
        if data.get("enabled") is not None:
            updates["cart_assist_enabled"] = "true" if data["enabled"] else "false"
        if data.get("cooldown_minutes") is not None:
            updates["cart_assist_cooldown_minutes"] = str(
                _int_setting(str(data["cooldown_minutes"]), 30, minimum=1, maximum=1440)
            )
        if data.get("max_attempts_per_scan") is not None:
            updates["cart_assist_max_attempts_per_scan"] = str(
                _int_setting(str(data["max_attempts_per_scan"]), 1, minimum=1, maximum=25)
            )
        if data.get("username") is not None:
            username = str(data["username"]).strip()
            if username:
                updates["recreation_gov_username"] = username
        if data.get("password") is not None:
            password = str(data["password"])
            if password:
                updates["recreation_gov_password"] = password
        self.store.set_app_settings(updates)
        return self.status()

    def clear_credentials(self) -> dict[str, Any]:
        self.store.delete_app_settings(CREDENTIAL_KEYS)
        return self.status()

    async def handle_new_results(self, watch: dict[str, Any], results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not watch.get("cart_assist_enabled") or not results:
            return []

        status = self.status()
        max_attempts = status["max_attempts_per_scan"]
        attempts: list[dict[str, Any]] = []

        for index, result in enumerate(results):
            if index >= max_attempts:
                attempt, created = self.store.record_cart_attempt(
                    result,
                    "skipped",
                    f"Skipped because this scan is limited to {max_attempts} cart assist attempt(s).",
                )
                if created:
                    attempts.append(attempt)
                continue

            if not status["enabled"]:
                attempt_status = "disabled"
                message = "Watch requested Cart Assist, but CAMPFINDER_CART_ASSIST_ENABLED is not true on the server."
            elif not status["credentials_configured"]:
                attempt_status = "needs_credentials"
                message = (
                    "Watch requested Cart Assist, but Recreation.gov credentials are not configured on the server."
                )
            elif self.store.count_recent_cart_attempts(status["cooldown_minutes"]) > 0:
                attempt_status = "cooldown"
                message = (
                    f"Cart Assist cooldown is active; only one attempt is allowed per "
                    f"{status['cooldown_minutes']} minute(s)."
                )
            else:
                attempt_status = "manual_required"
                message = (
                    "High-priority match is ready for manual checkout. Automated add-to-cart is intentionally "
                    "not performed until a guarded browser worker is configured."
                )

            attempt, created = self.store.record_cart_attempt(result, attempt_status, message)
            if created:
                attempts.append(attempt)

        return attempts
