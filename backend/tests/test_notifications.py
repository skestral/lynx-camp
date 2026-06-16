from __future__ import annotations

import asyncio

from backend.app.notifications import Notifier
from backend.app.settings import Settings


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
