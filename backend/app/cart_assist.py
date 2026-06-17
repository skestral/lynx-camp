from __future__ import annotations

from typing import Any

from .db import Store


class CartAssistant:
    def __init__(self, store: Store, settings: Any):
        self.store = store
        self.settings = settings

    def status(self) -> dict[str, Any]:
        credentials_configured = bool(self.settings.recreation_gov_username and self.settings.recreation_gov_password)
        enabled = bool(self.settings.cart_assist_enabled)
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
            "cooldown_minutes": max(1, int(self.settings.cart_assist_cooldown_minutes)),
            "max_attempts_per_scan": max(1, int(self.settings.cart_assist_max_attempts_per_scan)),
            "detail": detail,
        }

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
