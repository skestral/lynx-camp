"""Synthetic diagnostics, including deliberate secret-bearing inputs."""
import asyncio
from datetime import datetime
import json

import httpx
import pytest

from backend.app import provider_diagnostics as diagnostics
from backend.app.db import Store
from backend.app.goingtocamp import GoingToCampClient, connection_state
from backend.app.provider_errors import ProviderResponseError
from backend.app.recreation import RateLimitError


@pytest.fixture
def store(tmp_path):
    result = Store(tmp_path / "diagnostics.db")
    result.init()
    return result


def record(**kwargs):
    return diagnostics.diagnostic_record("/resourceLocation", None, 0.123, outcome="access_denied", **kwargs)


def test_allowlist_excludes_secrets_from_every_input(monkeypatch, store):
    secret = "DO-NOT-STORE-THIS-SECRET"
    monkeypatch.setattr(diagnostics, "getproxies", lambda: {"https": f"http://user:{secret}@private-host", "no": secret})
    monkeypatch.setenv("SSL_CERT_FILE", secret)
    response = httpx.Response(403, text=f"<html>Access denied. Verify you are human. {secret}</html>",
                             headers={"Content-Type": "text/html; charset=utf-8", "Set-Cookie": secret,
                                      "Via": secret, "Server": f"nginx {secret}", "X-Cache": secret,
                                      "X-Azure-Ref": secret, "WWW-Authenticate": secret,
                                      "Location": f"https://private-host/{secret}", "Authorization": secret,
                                      "X-Request-ID": secret, "X-Correlation-ID": "a" * 32},
                             request=httpx.Request("GET", f"https://example.test/?token={secret}"))
    entry = diagnostics.diagnostic_record("/availability/map", {"startDate": "2027-06-04", "endDate": secret,
        "mapId": "-12", "filterData": secret, "cartUid": secret, "token": secret, "partySize": secret},
        0.123, response=response, outcome="access_denied")
    diagnostics.save_diagnostic(store, entry)
    saved = diagnostics.read_diagnostics(store)[0]
    assert secret not in json.dumps(saved)
    assert "private-host" not in json.dumps(saved)
    assert saved["query"] == {"startDate": "2027-06-04", "mapId": "-12"}
    assert saved["markers"] == ["access_denied", "human_verification"]
    assert saved["request_ids"] == {"x-correlation-id": "a" * 32}
    assert saved["server_family"] == "nginx"
    assert saved["redirect"] == "other_origin"
    assert saved["elapsed_ms"] == 123
    assert all(saved[key] for key in ("proxy_configured", "no_proxy_configured", "custom_ca_configured",
                                      "via_present", "cache_header_present", "set_cookie_present",
                                      "azure_edge_header_present", "authenticate_header_present"))
    assert secret not in store.get_app_settings([diagnostics.STATE_KEY])[diagnostics.STATE_KEY]
    assert diagnostics.STATE_KEY not in json.dumps(store.export_config(include_secrets=True))


def test_bounded_history_survives_restart(store):
    entries = [record() for _ in range(35)]
    for entry in entries:
        diagnostics.save_diagnostic(store, entry)
    restored = Store(store.database_path)
    assert [r["id"] for r in diagnostics.read_diagnostics(restored)] == [r["id"] for r in entries[-30:][::-1]]


@pytest.mark.parametrize("raw", ['null', '{}', 'not json', '[null, 1, {}]'])
def test_corrupt_history_is_safe(store, raw):
    store.set_app_settings({diagnostics.STATE_KEY: raw})
    assert diagnostics.read_diagnostics(store) == []


def test_existing_records_are_sanitized_again(store):
    entry = record()
    entry.update(cookie="secret", markers=["secret", "forbidden"], query={"token": "secret"},
                 request_ids={"authorization": "secret"})
    store.set_app_settings({diagnostics.STATE_KEY: json.dumps([entry])})
    assert "secret" not in json.dumps(diagnostics.read_diagnostics(store))
    entry["endpoint"] = "https://private-host/secret"
    assert diagnostics.sanitize_record(entry) is None
    entry = record()
    entry["recorded_at"] = datetime.now().isoformat()
    assert diagnostics.sanitize_record(entry) is None


@pytest.mark.parametrize("error,kind", [(httpx.ConnectTimeout("secret"), "timeout"),
    (httpx.ProxyError("secret"), "proxy"), (httpx.ConnectError("secret"), "connection"),
    (httpx.RemoteProtocolError("secret"), "protocol")])
def test_transport_errors_do_not_store_exception_text(error, kind):
    entry = diagnostics.diagnostic_record("/resourceLocation", None, 1, error=error, outcome="transport_error")
    assert entry["transport_error"] == kind
    assert entry["status"] is None
    assert "secret" not in json.dumps(entry)


@pytest.mark.parametrize("status,outcome", [(403, "access_denied"), (429, "rate_limited"), (500, "http_error"), (200, "json_response")])
def test_requests_record_once_without_extra_traffic(store, status, outcome):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json={"example": True})
    client = GoingToCampClient(store, httpx.MockTransport(respond), request_spacing_seconds=0)
    async def run():
        if status == 200:
            assert await client._request("/resourceLocation") == {"example": True}
        else:
            with pytest.raises((ProviderResponseError, RateLimitError)):
                await client._request("/resourceLocation")
        if status in {403, 429}:
            with pytest.raises((ProviderResponseError, RateLimitError)):
                await client._request("/resourceLocation")
    asyncio.run(run())
    assert len(requests) == 1
    history = diagnostics.read_diagnostics(store)
    assert len(history) == 1 and history[0]["outcome"] == outcome


def test_diagnostic_failure_cannot_disable_access_stop(monkeypatch, store):
    def fail(*args, **kwargs):
        raise RuntimeError("secret")
    monkeypatch.setattr(diagnostics, "diagnostic_record", fail)
    client = GoingToCampClient(store, httpx.MockTransport(lambda request: httpx.Response(403)), request_spacing_seconds=0)
    with pytest.raises(ProviderResponseError, match="HTTP 403"):
        asyncio.run(client._request("/resourceLocation"))
    assert connection_state(store)["state"] == "access_denied"


def test_diagnostics_endpoint_is_read_only(monkeypatch, store):
    from backend.app import main
    monkeypatch.setattr(main, "store", store)
    diagnostics.save_diagnostic(store, record())
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(main.app), base_url="http://test") as client:
            response = await client.get("/api/sources/washington-state-parks/diagnostics")
            assert response.status_code == 200
            report = response.json()
            assert len(report["records"]) == 1
            assert report["client"]["browser_required"] is False
            assert report["connection"]["state"] == "unverified"
            assert (await client.get("/api/sources/unknown/diagnostics")).status_code == 404
    asyncio.run(run())
