from __future__ import annotations

import asyncio

from backend.app.db import Store
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
    assert status["channels"][1]["channel"] == "home_assistant"
    assert status["channels"][1]["configured"] is False
    assert status["channels"][2]["channel"] == "email"
    assert status["channels"][2]["configured"] is False
    assert status["channels"][3]["channel"] == "ntfy"
    assert status["channels"][3]["configured"] is False


def test_test_notification_skips_unconfigured_channels(tmp_path) -> None:
    notifier = Notifier(Settings(database_path=tmp_path / "db.sqlite"))

    result = asyncio.run(notifier.send_test())

    assert {item["channel"]: item["status"] for item in result["results"]} == {
        "webhook": "skipped",
        "home_assistant": "skipped",
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


def test_home_assistant_webhook_can_use_appdata_and_clear_to_environment(tmp_path) -> None:
    store = Store(tmp_path / "campfinder.db")
    store.init()
    notifier = Notifier(
        Settings(
            database_path=tmp_path / "campfinder.db",
            home_assistant_webhook_url="https://ha.example.com/api/webhook/env",
        ),
        store,
    )

    saved = notifier.update_config({"home_assistant_webhook_url": "https://ha.example.com/api/webhook/stored"})

    assert saved["home_assistant_webhook_configured"] is True
    assert saved["home_assistant_webhook_source"] == "appdata"
    assert notifier.status()["channels"][1]["configured"] is True
    assert store.get_app_settings(["home_assistant_webhook_url"]) == {
        "home_assistant_webhook_url": "https://ha.example.com/api/webhook/stored"
    }

    cleared = notifier.clear_home_assistant_webhook()

    assert cleared["home_assistant_webhook_configured"] is True
    assert cleared["home_assistant_webhook_source"] == "environment"
    assert store.get_app_settings(["home_assistant_webhook_url"]) == {}


def test_notification_config_can_use_appdata_smtp_settings(tmp_path) -> None:
    store = Store(tmp_path / "campfinder.db")
    store.init()
    notifier = Notifier(Settings(database_path=tmp_path / "campfinder.db"), store)

    saved = notifier.update_config(
        {
            "smtp_host": "smtp.example.com",
            "smtp_port": 465,
            "smtp_username": "camper@example.com",
            "smtp_password": "secret",
            "smtp_from": "campfinder@example.com",
            "smtp_to": "camper@example.com",
            "max_notification_results": 9,
        }
    )
    status = notifier.status()
    channels = {item["channel"]: item for item in status["channels"]}

    assert saved["sources"]["smtp_host"] == "appdata"
    assert saved["configured"]["smtp_password"] is True
    assert saved["values"]["smtp_password"] == ""
    assert saved["values"]["max_notification_results"] == 9
    assert channels["email"]["configured"] is True
    assert notifier._effective_config()["smtp_port"] == 465


def test_clear_notification_secrets_preserves_non_secret_notification_settings(tmp_path) -> None:
    store = Store(tmp_path / "campfinder.db")
    store.init()
    notifier = Notifier(Settings(database_path=tmp_path / "campfinder.db"), store)
    notifier.update_config(
        {
            "home_assistant_webhook_url": "https://ha.example.com/api/webhook/stored",
            "ntfy_topic": "campfinder-alerts",
            "smtp_host": "smtp.example.com",
        }
    )

    cleared = notifier.clear_notification_secrets()

    assert cleared["configured"]["home_assistant_webhook_url"] is False
    assert cleared["configured"]["ntfy_topic"] is False
    assert cleared["values"]["smtp_host"] == "smtp.example.com"
    assert store.get_app_settings(["smtp_host"]) == {}
    assert store.get_app_settings(["notification_smtp_host"]) == {
        "notification_smtp_host": "smtp.example.com"
    }


def test_home_assistant_payload_is_structured_and_bounded(tmp_path) -> None:
    notifier = Notifier(Settings(database_path=tmp_path / "db.sqlite", app_base_url="http://campfinder.local"))

    payload = notifier._home_assistant_payload(
        [
            {
                "id": 1,
                "park_name": "Olympic National Park",
                "campground_name": "Kalaloch",
                "watch_name": "Weekend",
                "site": "A01",
                "loop": "A",
                "campsite_type": "Tent",
                "arrival_date": "2026-07-03",
                "departure_date": "2026-07-05",
                "booking_url": "https://www.recreation.gov/camping/campsites/101?startDate=2026-07-03",
            },
            {
                "id": 2,
                "park_name": "Olympic National Park",
                "campground_name": "Kalaloch",
                "watch_name": "Weekend",
                "site": "A02",
                "arrival_date": "2026-07-04",
                "departure_date": "2026-07-06",
                "booking_url": "https://www.recreation.gov/camping/campsites/102?startDate=2026-07-04",
            },
        ],
        "Camp Finder found availability.",
        max_items=1,
    )

    assert payload["source"] == "camp_finder"
    assert payload["event"] == "availability"
    assert payload["app_url"] == "http://campfinder.local"
    assert payload["match_count"] == 2
    assert payload["included_match_count"] == 1
    assert payload["matches"][0]["site"] == "A01"


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


def test_single_notification_includes_cart_assist_queue_handoff(tmp_path) -> None:
    notifier = Notifier(Settings(database_path=tmp_path / "db.sqlite", app_base_url="http://campfinder.local"))

    message = notifier._format_results_message(
        [
            {
                "id": 1,
                "campground_name": "Kalaloch",
                "site": "A01",
                "arrival_date": "2026-07-03",
                "departure_date": "2026-07-05",
                "booking_url": "https://www.recreation.gov/camping/campsites/101?startDate=2026-07-03",
                "cart_assist_message": "Cart Assist recorded 1 attempt for this scan.",
            }
        ]
    )

    assert "Cart Assist: Cart Assist recorded 1 attempt for this scan." in message
    assert "Queue: http://campfinder.local" in message


def test_bulk_notification_includes_cart_assist_queue_handoff(tmp_path) -> None:
    notifier = Notifier(Settings(database_path=tmp_path / "db.sqlite", app_base_url="http://campfinder.local"))

    message = notifier._format_results_message(
        [
            {
                "id": 1,
                "campground_name": "Kalaloch",
                "watch_name": "Weekend",
                "site": "A01",
                "loop": "A",
                "campsite_type": "Tent",
                "arrival_date": "2026-07-03",
                "departure_date": "2026-07-05",
                "booking_url": "https://www.recreation.gov/camping/campsites/101?startDate=2026-07-03",
                "cart_assist_message": "Cart Assist recorded 2 attempts for this scan.",
            },
            {
                "id": 2,
                "campground_name": "Kalaloch",
                "watch_name": "Weekend",
                "site": "A02",
                "loop": "A",
                "campsite_type": "Tent",
                "arrival_date": "2026-07-03",
                "departure_date": "2026-07-05",
                "booking_url": "https://www.recreation.gov/camping/campsites/102?startDate=2026-07-03",
                "cart_assist_message": "Cart Assist recorded 2 attempts for this scan.",
            },
        ],
        max_items=1,
    )

    assert "Cart Assist: Cart Assist recorded 2 attempts for this scan." in message
    assert "Open queue: http://campfinder.local" in message
