"""Alert links use the saved public URL without changing provider booking links."""
import asyncio
import json

import httpx
import pytest
from pydantic import ValidationError

from backend.app.db import Store
from backend.app.notifications import Notifier
from backend.app.schemas import ConfigBackup, NotificationConfigUpdate
from backend.app.settings import Settings


PUBLIC_URL = "https://campfinder.den.camp"


@pytest.fixture
def notifier(tmp_path):
    store = Store(tmp_path / "links.db")
    store.init()
    return Notifier(Settings(app_base_url="http://localhost:8094/"), store)


def test_public_url_persists_exports_and_clears_to_environment(notifier, tmp_path):
    assert notifier.notification_config()["values"]["app_base_url"] == "http://localhost:8094"
    saved = notifier.update_config({"app_base_url": f"  {PUBLIC_URL}/  "})
    assert saved["values"]["app_base_url"] == PUBLIC_URL
    assert saved["sources"]["app_base_url"] == "appdata"
    notifier.store.init()
    assert notifier.clear_notification_secrets()["values"]["app_base_url"] == PUBLIC_URL
    backup = ConfigBackup.model_validate(notifier.store.export_config()).model_dump(mode="json")
    assert backup["settings"]["app_settings"]["notification_app_base_url"] == PUBLIC_URL
    assert "notification_app_base_url" not in backup["settings"]["redacted_keys"]
    restored = Store(tmp_path / "restored.db")
    restored.init()
    restored.import_config(backup)
    assert Notifier(Settings(), restored).notification_config()["values"]["app_base_url"] == PUBLIC_URL
    cleared = notifier.update_config({"app_base_url": ""})
    assert cleared["values"]["app_base_url"] == "http://localhost:8094"
    assert cleared["sources"]["app_base_url"] == "environment"
    notifier.store.import_config(ConfigBackup.model_validate(
        {"settings": {"app_settings": {"notification_app_base_url": ""}}}).model_dump(mode="json"))
    assert notifier.notification_config()["values"]["app_base_url"] == "http://localhost:8094"


@pytest.mark.parametrize("url", ["campfinder.den.camp", "javascript:alert(1)", "ftp://example.test",
    "https://user:secret@example.test", "https://example.test/?token=secret", "https://example.test/#logs",
    "https://bad host.test", "https://example.test/\npath", "https://example.test:invalid", "https://example.test/\\bad"])
def test_bad_public_urls_rejected_by_settings_and_backup(url):
    with pytest.raises(ValidationError):
        NotificationConfigUpdate.model_validate({"app_base_url": url})
    with pytest.raises(ValidationError):
        ConfigBackup.model_validate({"settings": {"app_settings": {"notification_app_base_url": url}}})


@pytest.mark.parametrize("url", ["http://localhost:8080", "http://192.168.1.5:8080", "http://[::1]:8080", PUBLIC_URL])
def test_public_url_accepts_local_and_remote_servers(url):
    assert NotificationConfigUpdate(app_base_url=url + "/").app_base_url == url


def test_settings_api_roundtrip_does_not_echo_credentials(notifier, monkeypatch):
    from backend.app import main
    monkeypatch.setattr(main, "notifier", notifier)

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(main.app), base_url="http://test") as client:
            response = await client.patch("/api/notifications/config", json={"app_base_url": PUBLIC_URL})
            assert response.status_code == 200
            assert (await client.get("/api/notifications/config")).json()["values"]["app_base_url"] == PUBLIC_URL
            invalid = await client.patch("/api/notifications/config", json={"app_base_url": "https://user:secret@example.test"})
            assert invalid.status_code == 422 and "secret" not in invalid.text
            assert notifier.notification_config()["values"]["app_base_url"] == PUBLIC_URL

    asyncio.run(scenario())


def test_test_alerts_and_availability_links_share_public_url(notifier, monkeypatch):
    notifier.update_config({"app_base_url": PUBLIC_URL, "webhook_url": "https://example.test/discord",
                            "home_assistant_webhook_url": "https://example.test/ha", "ntfy_topic": "test-topic"})
    requests = []
    client_class = httpx.AsyncClient

    def receive(request):
        requests.append(request)
        return httpx.Response(200)

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: client_class(transport=httpx.MockTransport(receive), **kwargs))
    asyncio.run(notifier.send_test())
    by_path = {r.url.path: r for r in requests}
    assert PUBLIC_URL in json.loads(by_path["/discord"].content)["content"]
    assert json.loads(by_path["/ha"].content)["app_url"] == PUBLIC_URL
    assert by_path["/test-topic"].headers["Click"] == PUBLIC_URL
    assert "localhost" not in " ".join(r.content.decode() for r in requests)

    result = {"campground_name": "Example camp", "site": "1", "arrival_date": "2027-06-04",
              "departure_date": "2027-06-05", "cart_assist_message": "Manual checkout ready",
              "booking_url": "https://www.recreation.gov/camping/campsites/123?startDate=2027-06-04"}
    assert f"Queue: {PUBLIC_URL}" in notifier._format_results_message([result])
    assert result["booking_url"] in notifier._format_results_message([result])
    assert f"Review results: {PUBLIC_URL}" in notifier._format_results_message([result, {**result, "site": "2"}])
    assert notifier._home_assistant_payload([result], "Example")["app_url"] == PUBLIC_URL
    assert notifier._home_assistant_payload([result], "Example")["matches"][0]["booking_url"] == result["booking_url"]

    asyncio.run(notifier.send_event("ntfy", "Digest", {"event": "digest"}, notifier._effective_config()))
    assert requests[-1].headers["Click"] == PUBLIC_URL
