from __future__ import annotations

import asyncio

from backend.app.notifications import Notifier
from backend.app.settings import Settings


class RecordingStore:
    def __init__(self) -> None:
        self.events = []

    def record_notification(self, result_id: int, channel: str, status: str, message: str) -> None:
        self.events.append(
            {
                "result_id": result_id,
                "channel": channel,
                "status": status,
                "message": message,
            }
        )


def test_notification_status_reports_missing_channels(tmp_path) -> None:
    notifier = Notifier(Settings(database_path=tmp_path / "db.sqlite"))

    status = notifier.status()

    assert status["channels"][0]["channel"] == "webhook"
    assert status["channels"][0]["configured"] is False
    assert status["channels"][1]["channel"] == "email"
    assert status["channels"][1]["configured"] is False
    assert status["channels"][2]["channel"] == "ntfy"
    assert status["channels"][2]["configured"] is False


def test_test_notification_skips_unconfigured_channels(tmp_path) -> None:
    notifier = Notifier(Settings(database_path=tmp_path / "db.sqlite"))

    result = asyncio.run(notifier.send_test())

    assert {item["channel"]: item["status"] for item in result["results"]} == {
        "webhook": "skipped",
        "email": "skipped",
        "ntfy": "skipped",
    }


def test_ntfy_status_reports_configured_topic(tmp_path) -> None:
    notifier = Notifier(
        Settings(
            database_path=tmp_path / "db.sqlite",
            ntfy_server="https://push.example.com/",
            ntfy_topic="campfinder-alerts",
        )
    )

    status = notifier.status()
    channels = {item["channel"]: item for item in status["channels"]}

    assert channels["ntfy"]["configured"] is True
    assert channels["ntfy"]["detail"] == "https://push.example.com/campfinder-alerts"


def test_bulk_notification_records_one_delivery_attempt_and_batched_followups(tmp_path) -> None:
    notifier = Notifier(Settings(database_path=tmp_path / "db.sqlite"))
    store = RecordingStore()

    notifier._record_batch_notifications(
        [{"id": 1}, {"id": 2}, {"id": 3}],
        "ntfy",
        "error",
        "HTTP 429",
        store,
    )

    assert store.events == [
        {"result_id": 1, "channel": "ntfy", "status": "error", "message": "HTTP 429"},
        {
            "result_id": 2,
            "channel": "ntfy",
            "status": "batched",
            "message": "Included in bulk availability alert.",
        },
        {
            "result_id": 3,
            "channel": "ntfy",
            "status": "batched",
            "message": "Included in bulk availability alert.",
        },
    ]
