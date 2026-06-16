from __future__ import annotations

import asyncio
import smtplib
from email.message import EmailMessage
from typing import TYPE_CHECKING

import httpx

from .settings import Settings

if TYPE_CHECKING:
    from .db import Store


class Notifier:
    def __init__(self, settings: Settings):
        self.settings = settings

    def status(self) -> dict:
        email_missing = []
        for label, value in [
            ("CAMPFINDER_SMTP_HOST", self.settings.smtp_host),
            ("CAMPFINDER_SMTP_USERNAME", self.settings.smtp_username),
            ("CAMPFINDER_SMTP_PASSWORD", self.settings.smtp_password),
            ("CAMPFINDER_SMTP_FROM", self.settings.smtp_from),
            ("CAMPFINDER_SMTP_TO", self.settings.smtp_to),
        ]:
            if not value:
                email_missing.append(label)
        return {
            "channels": [
                {
                    "channel": "webhook",
                    "configured": bool(self.settings.webhook_url),
                    "detail": "Configured" if self.settings.webhook_url else "Set CAMPFINDER_WEBHOOK_URL",
                    "missing": [] if self.settings.webhook_url else ["CAMPFINDER_WEBHOOK_URL"],
                },
                {
                    "channel": "email",
                    "configured": self._smtp_enabled,
                    "detail": self.settings.smtp_to or "Set SMTP env vars",
                    "missing": email_missing,
                },
                {
                    "channel": "ntfy",
                    "configured": self._ntfy_enabled,
                    "detail": self._ntfy_url if self._ntfy_enabled else "Set CAMPFINDER_NTFY_TOPIC",
                    "missing": [] if self._ntfy_enabled else ["CAMPFINDER_NTFY_TOPIC"],
                },
            ]
        }

    async def notify_result(self, result: dict, store: "Store") -> None:
        await self.notify_results([result], store)

    async def notify_results(self, results: list[dict], store: "Store", max_items: int = 5) -> None:
        if not results:
            return
        message = self._format_results_message(results, max_items)
        click_url = results[0]["booking_url"] if len(results) == 1 else self.settings.app_base_url
        if self.settings.webhook_url:
            await self._send_webhook(results, message, store)
        if self._smtp_enabled:
            await asyncio.to_thread(self._send_email, results, message, store)
        if self._ntfy_enabled:
            await self._send_ntfy(results, message, click_url, store)

    async def send_test(self) -> dict:
        message = (
            "Camp Finder test notification\n"
            "If you received this, notifications are configured correctly."
        )
        results = []
        if self.settings.webhook_url:
            results.append(await self._post_webhook(message))
        else:
            results.append({"channel": "webhook", "status": "skipped", "message": "Webhook is not configured."})

        if self._smtp_enabled:
            results.append(await asyncio.to_thread(self._post_email, message))
        else:
            results.append({"channel": "email", "status": "skipped", "message": "Email is not configured."})

        if self._ntfy_enabled:
            results.append(await self._post_ntfy(message, self.settings.app_base_url))
        else:
            results.append({"channel": "ntfy", "status": "skipped", "message": "ntfy is not configured."})
        return {"results": results}

    @property
    def _smtp_enabled(self) -> bool:
        return all(
            [
                self.settings.smtp_host,
                self.settings.smtp_username,
                self.settings.smtp_password,
                self.settings.smtp_from,
                self.settings.smtp_to,
            ]
        )

    @property
    def _ntfy_enabled(self) -> bool:
        return bool(self.settings.ntfy_topic)

    @property
    def _ntfy_url(self) -> str:
        topic = (self.settings.ntfy_topic or "").strip().lstrip("/")
        return f"{self.settings.ntfy_server.rstrip('/')}/{topic}"

    async def _send_webhook(self, results: list[dict], message: str, store: "Store") -> None:
        result = await self._post_webhook(message)
        self._record_batch_notifications(results, "webhook", "sent" if result["status"] == "sent" else "error", result["message"], store)

    def _send_email(self, results: list[dict], message: str, store: "Store") -> None:
        result = self._post_email(message)
        self._record_batch_notifications(results, "email", "sent" if result["status"] == "sent" else "error", result["message"], store)

    async def _send_ntfy(self, results: list[dict], message: str, click_url: str, store: "Store") -> None:
        result = await self._post_ntfy(message, click_url)
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

    async def _post_webhook(self, message: str) -> dict:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.post(self.settings.webhook_url or "", json={"content": message})
                response.raise_for_status()
            return {"channel": "webhook", "status": "sent", "message": "Webhook notification sent."}
        except Exception as exc:
            return {"channel": "webhook", "status": "error", "message": str(exc)}

    def _post_email(self, message: str) -> dict:
        email = EmailMessage()
        email["Subject"] = "Camp Finder availability"
        email["From"] = self.settings.smtp_from or ""
        email["To"] = self.settings.smtp_to or ""
        email.set_content(message)
        try:
            with smtplib.SMTP(self.settings.smtp_host or "", self.settings.smtp_port) as smtp:
                smtp.starttls()
                smtp.login(self.settings.smtp_username or "", self.settings.smtp_password or "")
                smtp.send_message(email)
            return {"channel": "email", "status": "sent", "message": "Email notification sent."}
        except Exception as exc:
            return {"channel": "email", "status": "error", "message": str(exc)}

    async def _post_ntfy(self, message: str, click_url: str) -> dict:
        headers = {
            "Title": "Camp Finder availability",
            "Tags": "camping,tent",
            "Priority": self.settings.ntfy_priority,
            "Click": click_url,
        }
        if self.settings.ntfy_token:
            headers["Authorization"] = f"Bearer {self.settings.ntfy_token}"
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.post(self._ntfy_url, content=message.encode("utf-8"), headers=headers)
                response.raise_for_status()
            return {"channel": "ntfy", "status": "sent", "message": "ntfy notification sent."}
        except Exception as exc:
            return {"channel": "ntfy", "status": "error", "message": str(exc)}

    def _format_results_message(self, results: list[dict], max_items: int = 5) -> str:
        if len(results) == 1:
            return self._format_message(results[0])

        ordered = sorted(results, key=lambda item: (item["arrival_date"], item["site"]))
        first = ordered[0]
        lines = [
            f"Camp Finder found {len(results)} new availability matches:",
            f"{first['campground_name']} - {first.get('watch_name') or 'watch'}",
            "",
        ]
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

    @staticmethod
    def _format_message(result: dict) -> str:
        return (
            "Camp Finder found availability:\n"
            f"{result['campground_name']} site {result['site']}\n"
            f"{result['arrival_date']} to {result['departure_date']}\n"
            f"Book: {result['booking_url']}"
        )
