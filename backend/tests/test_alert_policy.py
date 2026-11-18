"""Notification policy tests use fake clocks, isolated stores, and no delivery network."""
import asyncio
from datetime import UTC, datetime, timedelta
import json

import httpx
import pytest
from pydantic import ValidationError

from backend.app.alert_dispatcher import AlertDispatcher, RUNTIME_KEY
from backend.app.alert_schedule import digest_schedule
from backend.app.db import Store
from backend.app.notifications import Notifier
from backend.app.schemas import ConfigBackup, NotificationConfigUpdate
from backend.app.settings import Settings


def stamp(value):
    return datetime.fromisoformat(value).astimezone(UTC)


@pytest.fixture
def setup(tmp_path, monkeypatch):
    clock = [stamp("2027-01-11T07:00:00-08:00")]
    monkeypatch.setattr("backend.app.db.utc_now", lambda: clock[0].replace(microsecond=0).isoformat())
    store = Store(tmp_path / "alerts.db")
    store.init()
    target = store.create_target({"name": "Example Camp", "campground_id": "123", "park_name": "Example Park"})
    watch = store.create_watch({"target_id": target["id"], "name": "Weekend", "mode": "specific",
        "window_start": "2027-06-04", "window_end": "2027-06-06",
        "specific_ranges": [{"arrival_date": "2027-06-04", "departure_date": "2027-06-06"}]})
    notifier = Notifier(Settings(database_path=store.database_path, webhook_url="https://example.test/discord",
                                home_assistant_webhook_url="https://example.test/ha"), store)
    deliveries = []

    async def deliver(channel, message, payload, config):
        deliveries.append({"channel": channel, "message": message, "payload": payload})
        return {"status": "sent", "message": "Synthetic delivery"}

    monkeypatch.setattr(notifier, "send_event", deliver)
    return store, watch, notifier, clock, deliveries


def finding(store, watch, site="1"):
    return store.upsert_result({"watch_id": watch["id"], "target_id": watch["target_id"],
        "campground_id": "123", "campground_name": "Example Camp", "campsite_id": site,
        "site": site, "arrival_date": "2027-06-04", "departure_date": "2027-06-06"})[0]


def config(**overrides):
    return {"digest_frequency": "daily", "digest_time": "08:00", "digest_timezone": "America/Los_Angeles",
            "digest_weekday": 0, **overrides}


@pytest.mark.parametrize("when,expected", [("2027-01-11T07:00:00-08:00", "2027-01-11T16:00:00+00:00"),
                                         ("2027-07-11T07:00:00-07:00", "2027-07-11T15:00:00+00:00")])
def test_pacific_default_tracks_dst(when, expected):
    schedule = digest_schedule(config(), stamp(when))
    assert stamp(schedule["next_digest_at"]) == stamp(expected)


@pytest.mark.parametrize("when,hours", [("2027-03-15T08:00:00-07:00", 23), ("2027-11-08T08:00:00-08:00", 25)])
def test_calendar_periods_are_not_fixed_24_hour_windows(when, hours):
    schedule = digest_schedule(config(), stamp(when))
    assert (stamp(schedule["period_end"]) - stamp(schedule["period_start"])).total_seconds() == hours * 3600


def test_weekly_server_and_disabled(monkeypatch):
    monkeypatch.setenv("TZ", "America/Los_Angeles")
    schedule = digest_schedule(config(digest_frequency="weekly", digest_timezone="server"), stamp("2027-01-11T08:00:00-08:00"))
    assert schedule["period_start"].startswith("2027-01-04T00:00")
    assert schedule["period_end"].startswith("2027-01-11T00:00")
    assert schedule["next_digest_at"].startswith("2027-01-18T08:00")
    assert "PST" in schedule["timezone_label"]
    assert digest_schedule(config(digest_frequency="disabled"), datetime.now(UTC))["next_digest_at"] is None


def test_nonexistent_and_repeated_local_delivery_times():
    spring = digest_schedule(config(digest_time="02:30"), stamp("2027-03-14T03:31:00-07:00"))
    assert spring["due_at"] == "2027-03-14T03:30:00-07:00"
    fall = digest_schedule(config(digest_time="01:30"), stamp("2027-11-07T01:45:00-08:00"))
    assert fall["due_at"] == "2027-11-07T01:30:00-07:00"


def test_digest_delivers_previous_day_once_per_channel_after_restart(setup):
    store, watch, notifier, clock, sent = setup
    clock[0] += timedelta(hours=2)
    dispatcher = AlertDispatcher(store, notifier)
    dispatcher.initialize(clock[0])
    finding(store, watch)
    clock[0] += timedelta(hours=22)
    # A still-available match is not a new discovery today.
    finding(store, watch)
    finding(store, watch, "2")

    async def scenario():
        await dispatcher.dispatch_due(clock[0])
        assert not sent
        clock[0] += timedelta(hours=1)
        await dispatcher.dispatch_due(clock[0])
        assert len(sent) == 2
        assert sent[0]["payload"]["match_count"] == 1
        assert sent[0]["payload"]["period_start"] == "2027-01-11T00:00:00-08:00"
        assert sent[0]["payload"]["type"] == "alert" and sent[0]["payload"]["alert_type"] == "digest"
        recovered = AlertDispatcher(Store(store.database_path), notifier)
        recovered.initialize(clock[0])
        await recovered.dispatch_due(clock[0] + timedelta(minutes=1))
        assert len(sent) == 2
        assert {event["event_type"] for event in store.list_notifications()} == {"digest"}
        assert all(event["status"] == "sent" for event in store.list_notifications())

    asyncio.run(scenario())


def test_digest_new_reappeared_deduped_across_watches_and_not_manual_actions(setup):
    store, watch, _, clock, _ = setup
    first = finding(store, watch)
    duplicate = store.create_watch({**watch, "name": "Overlapping watch"})
    finding(store, duplicate)
    summary = store.digest_summary("2027-01-11", "2027-01-12", 5)
    assert summary["match_count"] == 1
    clock[0] += timedelta(days=1)
    store.mark_missing_results_booked(watch["id"], [("2027-06-04", "2027-06-06")], set())
    finding(store, watch)
    finding(store, watch)
    assert store.digest_summary("2027-01-12", "2027-01-13", 5)["match_count"] == 1
    store.update_result_status(first["id"], "dismissed")
    clock[0] += timedelta(days=1)
    finding(store, watch)
    assert store.digest_summary("2027-01-13", "2027-01-14", 5)["match_count"] == 0


def test_watch_alerts_are_opt_in_and_rechecked_before_send(setup, monkeypatch):
    store, watch, notifier, _, _ = setup
    sent = []

    async def webhook(message, url):
        sent.append(message)
        return {"status": "sent", "message": "Synthetic"}

    async def ha(url, payload):
        sent.append(payload)
        return {"status": "sent", "message": "Synthetic"}

    monkeypatch.setattr(notifier, "_post_webhook", webhook)
    monkeypatch.setattr(notifier, "_post_home_assistant", ha)
    result = finding(store, watch)

    async def scenario():
        assert watch["alerts_enabled"] == 0
        assert await notifier.notify_results([result], store) == 0
        assert not sent
        store.update_watch(watch["id"], {"alerts_enabled": True})
        assert await notifier.notify_results([result], store) == 1
        assert len(sent) == 2 and sent[1]["type"] == "alert" and sent[1]["alert_type"] == "availability"
        store.update_watch(watch["id"], {"alerts_enabled": False})
        await notifier.notify_results([result], store)
        assert len(sent) == 2

    asyncio.run(scenario())


def test_no_historical_digest_on_enable_and_disabled_does_not_send(setup):
    store, watch, notifier, clock, sent = setup
    finding(store, watch)
    clock[0] += timedelta(days=1, hours=2)
    dispatcher = AlertDispatcher(store, notifier)
    dispatcher.initialize(clock[0])

    async def scenario():
        await dispatcher.dispatch_due(clock[0])
        assert not sent
        notifier.update_config({"digest_frequency": "disabled"})
        clock[0] += timedelta(days=1)
        await dispatcher.dispatch_due(clock[0])
        assert not sent
        clock[0] += timedelta(days=1)
        notifier.update_config({"digest_frequency": "daily"})
        await dispatcher.dispatch_due(clock[0])
        assert not sent

    asyncio.run(scenario())


def test_error_types_cooldown_restart_and_no_raw_exception_leak(setup):
    store, watch, notifier, clock, sent = setup
    notifier.update_config({"digest_frequency": "disabled"})
    dispatcher = AlertDispatcher(store, notifier)
    dispatcher.initialize(clock[0])

    def error(kind):
        store.log_scan_event(None, watch["id"], watch["target_id"], "error", kind,
                             "secret URL https://example.test/api/webhook/do-not-send")

    async def scenario():
        error("rate_limited")
        error("rate_limited")
        error("error")
        await dispatcher.dispatch_due(clock[0])
        assert len(sent) == 2 and all(item["channel"] == "home_assistant" for item in sent)
        assert {item["payload"]["error_type"] for item in sent} == {"provider_rate_limited", "scan_failed"}
        assert all(item["payload"]["type"] == "error" for item in sent)
        assert "do-not-send" not in json.dumps(sent)
        recovered = AlertDispatcher(store, notifier)
        recovered.initialize(clock[0])
        error("error")
        await recovered.dispatch_due(clock[0] + timedelta(minutes=30))
        assert len(sent) == 2
        clock[0] += timedelta(hours=1, minutes=1)
        error("error")
        await recovered.dispatch_due(clock[0])
        assert len(sent) == 3
        notifier.update_config({"home_assistant_errors_enabled": False})
        error("error")
        await recovered.dispatch_due(clock[0] + timedelta(hours=2))
        assert len(sent) == 3

    asyncio.run(scenario())


def test_failed_or_interrupted_delivery_is_not_duplicated(setup, monkeypatch):
    store, _, notifier, clock, _ = setup
    dispatcher = AlertDispatcher(store, notifier)
    dispatcher.initialize(clock[0])
    attempts = []

    async def fail(channel, message, payload, config):
        attempts.append(channel)
        raise RuntimeError("secret password must not enter history")

    monkeypatch.setattr(notifier, "send_event", fail)

    async def scenario():
        clock[0] += timedelta(hours=1)
        await dispatcher.dispatch_due(clock[0])
        await dispatcher.dispatch_due(clock[0] + timedelta(minutes=1))
        assert len(attempts) == 2
        events = store.list_notifications()
        assert all(event["status"] == "error" for event in events)
        assert "secret password" not in json.dumps(events)
        store.claim_notification_dispatch("interrupted", "home_assistant", "digest", "Pending", clock[0].isoformat())
        dispatcher.initialize(clock[0])
        assert store.list_notifications()[0]["status"] in {"error", "unknown"}
        assert any(event["status"] == "unknown" for event in store.list_notifications())

    asyncio.run(scenario())


def test_settings_watch_flag_backup_migration_and_regional_inheritance(setup, tmp_path):
    store, watch, notifier, _, _ = setup
    with store.connect() as conn:
        conn.execute("ALTER TABLE watches DROP COLUMN alerts_enabled")
    store.init()
    store.init()
    assert store.get_watch(watch["id"])["alerts_enabled"] == 0
    store.update_watch(watch["id"], {"alerts_enabled": True})
    notifier.update_config({"digest_frequency": "weekly", "digest_time": "09:15", "digest_timezone": "server",
                            "digest_weekday": 6, "home_assistant_errors_enabled": False})
    backup = ConfigBackup.model_validate(store.export_config()).model_dump(mode="json")
    assert backup["targets"][0]["watches"][0]["alerts_enabled"] is True
    assert RUNTIME_KEY not in backup["settings"]["app_settings"]
    restored = Store(tmp_path / "restored.db")
    restored.init()
    restored.import_config(backup)
    values = Notifier(Settings(), restored).notification_config()["values"]
    assert values["digest_time"] == "09:15" and values["digest_weekday"] == 6
    assert values["home_assistant_errors_enabled"] is False
    assert restored.list_watches()[0]["alerts_enabled"] == 1
    # Explicit regional edits propagate the notification choice like the date criteria.
    store.update_target(watch["target_id"], {"state_code": "WA"})
    group = store.create_watch_group([watch["target_id"]], {**watch, "alerts_enabled": False},
                                     {"kind": "state", "state_code": "WA"})
    updated = store.update_watch_group(group[0]["group_id"], {"alerts_enabled": True})
    assert all(row["alerts_enabled"] for row in updated)
    added = store.create_target({"name": "Second Camp", "campground_id": "456", "state_code": "WA"})
    inherited = next(row for row in store.list_watches() if row["target_id"] == added["id"])
    assert inherited["alerts_enabled"] == 1


@pytest.mark.parametrize("values", [{"digest_time": "25:00"}, {"digest_frequency": "hourly"},
                                  {"digest_timezone": "PST"}, {"digest_weekday": 7}])
def test_invalid_schedule_rejected_in_api_and_backup(values):
    with pytest.raises(ValidationError):
        NotificationConfigUpdate.model_validate(values)
    with pytest.raises(ValidationError):
        ConfigBackup.model_validate({"settings": {"app_settings": {f"notification_{key}": str(value) for key, value in values.items()}}})


def test_delivery_errors_redact_webhook_url():
    request = httpx.Request("POST", "https://example.test/secret-webhook")
    response = httpx.Response(403, request=request)
    message = Notifier._delivery_error(httpx.HTTPStatusError("secret-webhook", request=request, response=response))
    assert "403" in message and "secret-webhook" not in message


def test_schedule_save_before_delivery_survives_late_tick(setup):
    store, _, notifier, clock, sent = setup
    notifier.update_config({"digest_time": "09:00"})
    dispatcher = AlertDispatcher(store, notifier)
    dispatcher.initialize(clock[0])
    clock[0] = stamp("2027-01-11T07:59:55-08:00")
    notifier.update_config({"digest_time": "08:00"})
    clock[0] += timedelta(seconds=10)
    asyncio.run(dispatcher.dispatch_due(clock[0]))
    assert len(sent) == 2
    assert sent[0]["payload"]["match_count"] == 0


def test_enabling_errors_captures_events_before_next_worker_tick(setup):
    store, watch, notifier, clock, sent = setup
    notifier.update_config({"home_assistant_errors_enabled": False, "digest_frequency": "disabled"})
    dispatcher = AlertDispatcher(store, notifier)
    dispatcher.initialize(clock[0])
    store.log_scan_event(None, watch["id"], watch["target_id"], "error", "error", "Historical")
    clock[0] += timedelta(minutes=1)
    notifier.update_config({"home_assistant_errors_enabled": True})
    store.log_scan_event(None, watch["id"], watch["target_id"], "error", "error", "After enable")
    clock[0] += timedelta(seconds=30)
    asyncio.run(dispatcher.dispatch_due(clock[0]))
    assert len(sent) == 1
    assert sent[0]["payload"]["event_id"] == "scan-error:2"


def test_opt_in_change_does_not_reschedule_or_discard_scan_progress(setup):
    store, watch, _, _, _ = setup
    store.schedule_next_scan(watch["id"], 60)
    store.save_scan_checkpoint(watch["id"], {"completed_stays": ["2027-06-04/2027-06-06"]})
    before = store.get_watch(watch["id"])
    progress = store.scan_checkpoint(watch["id"])
    store.update_watch(watch["id"], {**before, "active": True, "alerts_enabled": True})
    assert store.get_watch(watch["id"])["next_scan_at"] == before["next_scan_at"]
    assert store.scan_checkpoint(watch["id"]) == progress


def test_restart_catches_up_only_latest_period_and_concurrent_ticks_do_not_duplicate(setup):
    store, watch, notifier, clock, sent = setup
    dispatcher = AlertDispatcher(store, notifier)
    dispatcher.initialize(clock[0])
    finding(store, watch)
    clock[0] += timedelta(days=4, hours=2)
    recovered = AlertDispatcher(store, notifier)
    recovered.initialize(clock[0])

    async def scenario():
        await asyncio.gather(recovered.dispatch_due(clock[0]), dispatcher.dispatch_due(clock[0]))

    asyncio.run(scenario())
    assert len(sent) == 2
    assert sent[0]["payload"]["period_start"].startswith("2027-01-14")
    assert sent[0]["payload"]["match_count"] == 0


def test_digest_routes_through_all_configured_channels(setup, monkeypatch):
    store, _, _, _, _ = setup
    notifier = Notifier(Settings(webhook_url="https://example.test/discord",
        home_assistant_webhook_url="https://example.test/ha", ntfy_server="https://example.test", ntfy_topic="camp",
        smtp_host="example.test", smtp_username="user", smtp_password="secret", smtp_from="a@example.test",
        smtp_to="b@example.test", apprise_urls="json://example.test/alerts"), store)
    requests, emails, apprise = [], [], []
    client_class = httpx.AsyncClient

    def receive(request):
        requests.append(request)
        return httpx.Response(200)

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: client_class(transport=httpx.MockTransport(receive), **kwargs))

    class Mail:
        def __init__(self, host, port, timeout):
            assert timeout == 10

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def starttls(self):
            pass

        def login(self, user, password):
            pass

        def send_message(self, email):
            emails.append(email)

    async def send_apprise(urls, message):
        apprise.append(message)
        return {"status": "sent"}

    monkeypatch.setattr("backend.app.notifications.smtplib.SMTP", Mail)
    monkeypatch.setattr("backend.app.notifications.apprise_alerts.send", send_apprise)

    async def scenario():
        config = notifier._effective_config()
        channels = notifier.configured_channels(config)
        assert len(channels) == 5
        payload = {"event": "digest", "type": "alert", "alert_type": "digest", "match_count": 4}
        for channel in channels:
            result = await notifier.send_event(channel, "Daily digest: 4 matches", payload, config)
            assert result["status"] == "sent"

    asyncio.run(scenario())
    by_path = {request.url.path: request for request in requests}
    assert json.loads(by_path["/discord"].content)["content"] == "Daily digest: 4 matches"
    assert json.loads(by_path["/ha"].content)["alert_type"] == "digest"
    assert by_path["/camp"].headers["Title"] == "Camp Finder digest"
    assert emails[0]["Subject"] == "Camp Finder digest"
    assert len(apprise) == 1


def test_api_roundtrip_and_invalid_stored_schedule_fails_closed(setup, monkeypatch):
    from backend.app import main
    store, _, notifier, _, _ = setup
    monkeypatch.setattr(main, "notifier", notifier)

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://test") as client:
            response = await client.patch("/api/notifications/config", json={"digest_frequency": "weekly",
                "digest_time": "10:45", "digest_weekday": 0, "digest_timezone": "server", "home_assistant_errors_enabled": False})
            assert response.status_code == 200
            values = (await client.get("/api/notifications/config")).json()["values"]
            assert values["digest_time"] == "10:45" and values["digest_weekday"] == 0
            assert values["home_assistant_errors_enabled"] is False
            assert (await client.patch("/api/notifications/config", json={"digest_timezone": "Not/AZone"})).status_code == 422
            store.set_app_settings({"notification_digest_time": "bad"})
            response = await client.get("/api/notifications/config")
            assert response.status_code == 200
            assert response.json()["configuration_error"]
            assert response.json()["schedule"]["next_digest_at"] is None

    asyncio.run(scenario())
