"""Exercise shared request lanes without contacting reservation services."""
import asyncio
from datetime import UTC, date, datetime, timedelta
from time import monotonic

import httpx
import pytest

from backend.app.db import Store
from backend.app.providers import CampgroundClient
from backend.app.recreation import RateLimitError
from backend.app.request_limiter import ProviderRequestLimiter, request_cancel_check
from backend.app.scanner import Scanner, ScanCancelled


@pytest.fixture
def setup(tmp_path):
    store = Store(tmp_path / "limiter.db")
    store.init()
    client = CampgroundClient(store)
    scanner = Scanner(store, client, None, 60, api_request_delay_seconds=0)
    return store, client, scanner


def test_serializes_same_provider_from_completion_but_other_provider_can_run():
    async def scenario():
        limiter = ProviderRequestLimiter(lambda _: 0.04, lambda _: 0, lambda *_: None)
        started, release = asyncio.Event(), asyncio.Event()
        times = {}

        async def first():
            started.set()
            await release.wait()
            times["finished"] = monotonic()

        async def second():
            times["second"] = monotonic()

        task = asyncio.create_task(limiter.run("recreation", first))
        await started.wait()
        queued = asyncio.create_task(limiter.run("recreation", second))
        await limiter.run("goingtocamp", second)
        assert not queued.done()
        release.set()
        await asyncio.gather(task, queued)
        assert times["second"] - times["finished"] >= 0.035

    asyncio.run(scenario())


def test_cancelled_waiter_does_not_issue_request_or_leave_lock_held():
    async def scenario():
        limiter = ProviderRequestLimiter(lambda _: 0, lambda _: 0, lambda *_: None)
        started, release = asyncio.Event(), asyncio.Event()
        cancelled = False

        async def first():
            started.set()
            await release.wait()

        def check():
            if cancelled:
                raise ScanCancelled()

        async def forbidden():
            pytest.fail("Cancelled request reached provider")

        task = asyncio.create_task(limiter.run("recreation", first))
        await started.wait()
        token = request_cancel_check.set(check)
        queued = asyncio.create_task(limiter.run("recreation", forbidden))
        request_cancel_check.reset(token)
        await asyncio.sleep(0.01)
        cancelled = True
        with pytest.raises(ScanCancelled):
            await queued
        release.set()
        await task
        await limiter.run("recreation", lambda: asyncio.sleep(0))

    asyncio.run(scenario())


def test_search_rate_limit_blocks_scan_and_survives_restart(setup, monkeypatch):
    store, client, scanner = setup
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(429, headers={"Retry-After": "120"})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: real_client(
        **{**kwargs, "transport": httpx.MockTransport(respond)}))

    async def scenario():
        with pytest.raises(RateLimitError) as failure:
            await client.suggest_campgrounds("Olympic")
        assert failure.value.retry_after_seconds >= 3599
        assert scanner._rate_limit_streak == 1
        scanner._start_rate_limit_backoff(failure.value)
        assert scanner._rate_limit_streak == 1
        recovered = Scanner(store, CampgroundClient(store), None, 60)
        recovered.restore_runtime_state()
        with pytest.raises(RateLimitError):
            await recovered.client.monthly_availability("232464", date(2027, 6, 1))
        with pytest.raises(RateLimitError):
            await recovered.client.suggest_campgrounds("Rainier")
        assert len(requests) == 1 and recovered._rate_limit_streak == 1
        recovered._api_backoff_until = datetime.now(UTC) - timedelta(seconds=1)
        with pytest.raises(RateLimitError):
            await recovered.client.suggest_campgrounds("Rainier")
        assert len(requests) == 2 and recovered._rate_limit_streak == 2
        assert recovered._rate_limit_remaining_seconds("recreation") >= 7199

    asyncio.run(scenario())


def test_every_adapter_discovery_uses_same_gate_and_cooldown(setup, monkeypatch):
    _, client, scanner = setup
    calls = []
    real_client = httpx.AsyncClient

    def respond(request):
        calls.append(request)
        return httpx.Response(429)

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: real_client(
        **{**kwargs, "transport": httpx.MockTransport(respond)}))
    adapters = [client.washington, *client.gtc.values(), *client.usedirect.values(),
                client.king, client.skagit, client.snohomish]

    async def scenario():
        for adapter in adapters:
            assert adapter.request_limiter is scanner.request_limiter
            with pytest.raises(RateLimitError):
                await adapter.discover()
            count = len(calls)
            with pytest.raises(RateLimitError):
                await adapter.discover()
            assert len(calls) == count
            assert scanner._provider_backoffs[adapter.limiter_key]["streak"] == 1
        assert len(calls) == len(adapters)

    asyncio.run(scenario())


def test_live_settings_reconfigure_shared_gate_without_shortening_cooldown(setup):
    _, client, scanner = setup
    scanner._start_rate_limit_backoff(RateLimitError(8000), "goingtocamp")
    scanner.configure_scan_controls(min_poll_interval_minutes=90, release_scan_before_minutes=0,
        release_scan_after_minutes=0, release_scan_interval_minutes=10, availability_cache_minutes=30,
        api_request_delay_seconds=25, rate_limit_backoff_minutes=1)
    assert client.request_limiter.delay("recreation") == 25
    assert client.washington.request_limiter.delay("goingtocamp") == 25
    assert scanner._rate_limit_remaining_seconds("goingtocamp") >= 7999
