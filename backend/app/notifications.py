from __future__ import annotations

import asyncio
import smtplib
from email.message import EmailMessage
from typing import TYPE_CHECKING, Any

import httpx

from .app_settings import (
    HOME_ASSISTANT_WEBHOOK_KEY,
    NOTIFICATION_APP_SETTING_KEYS,
    NOTIFICATION_CONFIG_FIELDS,
    NOTIFICATION_SECRET_SETTING_KEYS,
)
from .settings import Settings

if TYPE_CHECKING:
    from .db import Store


class Notifier:
    def __init__(self, settings: Settings, store: "Store | None" = None):
        self.settings = settings
        self.store = store

    def status(self) -> dict:
        config = self._effective_config()
        home_assistant = self.home_assistant_config(config)
        email_missing = []
        for field_name, value in [
            ("smtp_host", config["smtp_host"]),
            ("smtp_username", config["smtp_username"]),
            ("smtp_password", config["smtp_password"]),
            ("smtp_from", config["smtp_from"]),
            ("smtp_to", config["smtp_to"]),
        ]:
            if not value:
                email_missing.append(str(NOTIFICATION_CONFIG_FIELDS[field_name]["env_name"]))
        return {
            "channels": [
                {
                    "channel": "webhook",
                    "configured": bool(config["webhook_url"]),
                    "detail": self._field_detail("webhook_url", config),
                    "missing": [] if config["webhook_url"] else ["CAMPFINDER_WEBHOOK_URL"],
                },
                {
                    "channel": "home_assistant",
                    "configured": home_assistant["configured"],
                    "detail": home_assistant["detail"],
                    "missing": [] if home_assistant["configured"] else ["CAMPFINDER_HOME_ASSISTANT_WEBHOOK_URL"],
                },
                {
                    "channel": "email",
                    "configured": self._smtp_enabled_for(config),
                    "detail": config["smtp_to"] or "Set SMTP in Settings or env vars",
                    "missing": email_missing,
                },
                {
                    "channel": "ntfy",
                    "configured": self._ntfy_enabled_for(config),
                    "detail": self._ntfy_url_for(config) if self._ntfy_enabled_for(config) else "Set ntfy topic in Settings or CAMPFINDER_NTFY_TOPIC",
                    "missing": [] if self._ntfy_enabled_for(config) else ["CAMPFINDER_NTFY_TOPIC"],
                },
            ]
        }

    async def notify_result(self, result: dict, store: "Store") -> None:
        await self.notify_results([result], store)

    async def notify_results(self, results: list[dict], store: "Store", max_items: int = 5) -> None:
        if not results:
            return
        config = self._effective_config()
        max_items = int(config.get("max_notification_results") or max_items)
        message = self._format_results_message(results, max_items)
        click_url = results[0]["booking_url"] if len(results) == 1 else self.settings.app_base_url
        home_assistant = self.home_assistant_config(config)
        if config["webhook_url"]:
            await self._send_webhook(results, message, store, config["webhook_url"])
        if home_assistant["url"]:
            await self._send_home_assistant(results, message, max_items, store, home_assistant["url"])
        if self._smtp_enabled_for(config):
            await asyncio.to_thread(self._send_email, results, message, store, config)
        if self._ntfy_enabled_for(config):
            await self._send_ntfy(results, message, click_url, store, config)

    async def send_test(self) -> dict:
        message = (
            "Camp Finder test notification\n"
            "If you received this, notifications are configured correctly."
        )
        results = []
        config = self._effective_config()
        home_assistant = self.home_assistant_config(config)
        if config["webhook_url"]:
            results.append(await self._post_webhook(message, config["webhook_url"]))
        else:
            results.append({"channel": "webhook", "status": "skipped", "message": "Webhook is not configured."})

        if home_assistant["url"]:
            results.append(
                await self._post_home_assistant(
                    home_assistant["url"],
                    {
                        "source": "camp_finder",
                        "event": "test",
                        "message": message,
                        "app_url": self.settings.app_base_url,
                    },
                )
            )
        else:
            results.append(
                {
                    "channel": "home_assistant",
                    "status": "skipped",
                    "message": "Home Assistant webhook is not configured.",
                }
            )

        if self._smtp_enabled_for(config):
            results.append(await asyncio.to_thread(self._post_email, message, config))
        else:
            results.append({"channel": "email", "status": "skipped", "message": "Email is not configured."})

        if self._ntfy_enabled_for(config):
            results.append(await self._post_ntfy(message, self.settings.app_base_url, config))
        else:
            results.append({"channel": "ntfy", "status": "skipped", "message": "ntfy is not configured."})
        return {"results": results}

    def home_assistant_config(self, config: dict[str, Any] | None = None) -> dict:
        config = config or self._effective_config()
        url = str(config.get("home_assistant_webhook_url") or "").strip()
        source = str(config.get("_sources", {}).get("home_assistant_webhook_url") or "none")
        detail = self._field_detail("home_assistant_webhook_url", config)
        return {
            "configured": bool(url),
            "url": url,
            "source": source,
            "detail": detail,
        }

    def notification_config(self) -> dict:
        config = self._effective_config()
        home_assistant = self.home_assistant_config(config)
        values: dict[str, Any] = {}
        configured: dict[str, bool] = {}
        for public_key, field in NOTIFICATION_CONFIG_FIELDS.items():
            value = config.get(public_key)
            configured[public_key] = bool(value)
            if field.get("secret"):
                values[public_key] = ""
            else:
                values[public_key] = value if value is not None else ""
        return {
            "home_assistant_webhook_configured": home_assistant["configured"],
            "home_assistant_webhook_source": home_assistant["source"],
            "home_assistant_detail": home_assistant["detail"],
            "values": values,
            "sources": config["_sources"],
            "configured": configured,
            "secret_fields": [
                public_key
                for public_key, field in NOTIFICATION_CONFIG_FIELDS.items()
                if field.get("secret")
            ],
        }

    def update_config(self, data: dict) -> dict:
        if not self.store:
            return self.notification_config()
        updates: dict[str, str] = {}
        deletes: list[str] = []
        for public_key, raw_value in data.items():
            field = NOTIFICATION_CONFIG_FIELDS.get(public_key)
            if field is None or raw_value is None:
                continue
            setting_key = str(field["setting_key"])
            if field["kind"] == "int":
                if raw_value == "":
                    deletes.append(setting_key)
                    continue
                updates[setting_key] = str(
                    self._coerce_int(
                        raw_value,
                        int(getattr(self.settings, public_key)),
                        int(field["minimum"]),
                        int(field["maximum"]),
                    )
                )
                continue

            value = str(raw_value).strip()
            if value:
                updates[setting_key] = value
            elif not field.get("secret"):
                deletes.append(setting_key)
        self.store.set_app_settings(updates)
        if deletes:
            self.store.delete_app_settings(deletes)
        return self.notification_config()

    def clear_home_assistant_webhook(self) -> dict:
        if self.store:
            self.store.delete_app_settings([HOME_ASSISTANT_WEBHOOK_KEY])
        return self.notification_config()

    def clear_notification_secrets(self) -> dict:
        if self.store:
            self.store.delete_app_settings(NOTIFICATION_SECRET_SETTING_KEYS)
        return self.notification_config()

    def _effective_config(self) -> dict[str, Any]:
        stored = self.store.get_app_settings(NOTIFICATION_APP_SETTING_KEYS) if self.store else {}
        values: dict[str, Any] = {}
        sources: dict[str, str] = {}
        for public_key, field in NOTIFICATION_CONFIG_FIELDS.items():
            setting_key = str(field["setting_key"])
            default = getattr(self.settings, public_key)
            if field["kind"] == "int":
                default = self._coerce_int(
                    default,
                    int(default),
                    int(field["minimum"]),
                    int(field["maximum"]),
                )
            if setting_key in stored:
                raw_value = stored[setting_key]
                if field["kind"] == "int":
                    values[public_key] = self._coerce_int(
                        raw_value,
                        int(default),
                        int(field["minimum"]),
                        int(field["maximum"]),
                    )
                else:
                    values[public_key] = str(raw_value).strip()
                sources[public_key] = "appdata"
            else:
                if field["kind"] == "int":
                    values[public_key] = default
                    sources[public_key] = "environment"
                else:
                    value = str(default or "").strip()
                    values[public_key] = value
                    sources[public_key] = "environment" if value else "none"
        values["_sources"] = sources
        return values

    def _field_detail(self, public_key: str, config: dict[str, Any]) -> str:
        field = NOTIFICATION_CONFIG_FIELDS[public_key]
        source = config.get("_sources", {}).get(public_key, "none")
        if config.get(public_key):
            return f"Configured from {source}."
        return f"Set in Settings or {field['env_name']}."

    @staticmethod
    def _coerce_int(raw_value: Any, default: int, minimum: int, maximum: int) -> int:
        try:
            value = int(raw_value)
        except (TypeError, ValueError):
            value = default
        return max(minimum, min(maximum, value))

    @property
    def _smtp_enabled(self) -> bool:
        return self._smtp_enabled_for(self._effective_config())

    @staticmethod
    def _smtp_enabled_for(config: dict[str, Any]) -> bool:
        return all([config["smtp_host"], config["smtp_username"], config["smtp_password"], config["smtp_from"], config["smtp_to"]])

    @property
    def _ntfy_enabled(self) -> bool:
        return self._ntfy_enabled_for(self._effective_config())

    @staticmethod
    def _ntfy_enabled_for(config: dict[str, Any]) -> bool:
        return bool(config["ntfy_topic"])

    @property
    def _ntfy_url(self) -> str:
        return self._ntfy_url_for(self._effective_config())

    @staticmethod
    def _ntfy_url_for(config: dict[str, Any]) -> str:
        topic = str(config.get("ntfy_topic") or "").strip().lstrip("/")
        server = str(config.get("ntfy_server") or "https://ntfy.sh").rstrip("/")
        return f"{server}/{topic}"

    async def _send_webhook(self, results: list[dict], message: str, store: "Store", webhook_url: str) -> None:
        result = await self._post_webhook(message, webhook_url)
        self._record_batch_notifications(results, "webhook", "sent" if result["status"] == "sent" else "error", result["message"], store)

    async def _send_home_assistant(
        self,
        results: list[dict],
        message: str,
        max_items: int,
        store: "Store",
        webhook_url: str,
    ) -> None:
        result = await self._post_home_assistant(webhook_url, self._home_assistant_payload(results, message, max_items))
        self._record_batch_notifications(
            results,
            "home_assistant",
            "sent" if result["status"] == "sent" else "error",
            result["message"],
            store,
        )

    def _send_email(self, results: list[dict], message: str, store: "Store", config: dict[str, Any]) -> None:
        result = self._post_email(message, config)
        self._record_batch_notifications(results, "email", "sent" if result["status"] == "sent" else "error", result["message"], store)

    async def _send_ntfy(self, results: list[dict], message: str, click_url: str, store: "Store", config: dict[str, Any]) -> None:
        result = await self._post_ntfy(message, click_url, config)
        self._record_batch_notifications(results, "ntfy", "sent" if result["status"] == "sent" else "error", result["message"], store)

    @staticmethod
    def _record_batch_notifications(
        results: list[dict],
        channel: str,
        first_status: str,
        message: str,
        store: "Store",
    ) -> None:
        if not results:
            return
        store.record_notification(results[0]["id"], channel, first_status, message)
        for result in results[1:]:
            store.record_notification(result["id"], channel, "batched", "Included in bulk availability alert.")

    async def _post_webhook(self, message: str, webhook_url: str | None = None) -> dict:
        webhook_url = webhook_url or str(self._effective_config().get("webhook_url") or "")
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.post(webhook_url, json={"content": message})
                response.raise_for_status()
            return {"channel": "webhook", "status": "sent", "message": "Webhook notification sent."}
        except Exception as exc:
            return {"channel": "webhook", "status": "error", "message": str(exc)}

    async def _post_home_assistant(self, webhook_url: str, payload: dict) -> dict:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.post(webhook_url, json=payload)
                response.raise_for_status()
            return {
                "channel": "home_assistant",
                "status": "sent",
                "message": "Home Assistant webhook notification sent.",
            }
        except Exception as exc:
            return {"channel": "home_assistant", "status": "error", "message": str(exc)}

    def _post_email(self, message: str, config: dict[str, Any] | None = None) -> dict:
        config = config or self._effective_config()
        email = EmailMessage()
        email["Subject"] = "Camp Finder availability"
        email["From"] = str(config["smtp_from"] or "")
        email["To"] = str(config["smtp_to"] or "")
        email.set_content(message)
        try:
            with smtplib.SMTP(str(config["smtp_host"] or ""), int(config["smtp_port"])) as smtp:
                smtp.starttls()
                smtp.login(str(config["smtp_username"] or ""), str(config["smtp_password"] or ""))
                smtp.send_message(email)
            return {"channel": "email", "status": "sent", "message": "Email notification sent."}
        except Exception as exc:
            return {"channel": "email", "status": "error", "message": str(exc)}

    async def _post_ntfy(self, message: str, click_url: str, config: dict[str, Any] | None = None) -> dict:
        config = config or self._effective_config()
        headers = {
            "Title": "Camp Finder availability",
            "Tags": "camping,tent",
            "Priority": str(config["ntfy_priority"] or "high"),
            "Click": click_url,
        }
        if config["ntfy_token"]:
            headers["Authorization"] = f"Bearer {config['ntfy_token']}"
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.post(self._ntfy_url_for(config), content=message.encode("utf-8"), headers=headers)
                response.raise_for_status()
            return {"channel": "ntfy", "status": "sent", "message": "ntfy notification sent."}
        except Exception as exc:
            return {"channel": "ntfy", "status": "error", "message": str(exc)}

    def _format_results_message(self, results: list[dict], max_items: int = 5) -> str:
        if len(results) == 1:
            return self._format_message(results[0])

        ordered = sorted(results, key=lambda item: (item["arrival_date"], item["site"]))
        first = ordered[0]
        cart_assist_message = next((result.get("cart_assist_message") for result in ordered if result.get("cart_assist_message")), None)
        lines = [
            f"Camp Finder found {len(results)} new availability matches:",
            f"{first['campground_name']} - {first.get('watch_name') or 'watch'}",
            "",
        ]
        if cart_assist_message:
            lines.extend([f"Cart Assist: {cart_assist_message}", f"Open queue: {self.settings.app_base_url}", ""])
        for result in ordered[:max_items]:
            details = [f"site {result['site']}"]
            if result.get("loop"):
                details.append(result["loop"])
            if result.get("campsite_type"):
                details.append(result["campsite_type"])
            lines.append(
                f"- {result['arrival_date']} to {result['departure_date']}: "
                f"{' / '.join(details)}"
            )
        remaining = len(results) - max_items
        if remaining > 0:
            lines.append(f"...and {remaining} more match(es).")
        lines.extend(["", f"Review results: {self.settings.app_base_url}"])
        return "\n".join(lines)

    def _home_assistant_payload(self, results: list[dict], message: str, max_items: int = 5) -> dict:
        ordered = sorted(results, key=lambda item: (item["arrival_date"], item["site"]))
        matches = []
        for result in ordered[:max_items]:
            matches.append(
                {
                    "park_name": result.get("park_name") or "",
                    "campground_name": result.get("campground_name") or "",
                    "watch_name": result.get("watch_name") or "",
                    "site": result.get("site") or "",
                    "loop": result.get("loop") or "",
                    "campsite_type": result.get("campsite_type") or "",
                    "arrival_date": result.get("arrival_date") or "",
                    "departure_date": result.get("departure_date") or "",
                    "booking_url": result.get("booking_url") or "",
                    "cart_assist_message": result.get("cart_assist_message") or "",
                }
            )
        return {
            "source": "camp_finder",
            "event": "availability",
            "message": message,
            "app_url": self.settings.app_base_url,
            "match_count": len(results),
            "included_match_count": len(matches),
            "matches": matches,
        }

    def _format_message(self, result: dict) -> str:
        lines = [
            "Camp Finder found availability:",
            f"{result['campground_name']} site {result['site']}",
            f"{result['arrival_date']} to {result['departure_date']}",
        ]
        if result.get("cart_assist_message"):
            lines.extend([f"Cart Assist: {result['cart_assist_message']}", f"Queue: {self.settings.app_base_url}"])
        lines.append(f"Book: {result['booking_url']}")
        return "\n".join(lines)
