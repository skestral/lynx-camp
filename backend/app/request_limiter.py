"""One request lane per provider, shared by discovery and background scans."""
from __future__ import annotations

import asyncio
from contextvars import ContextVar
from functools import wraps
from time import monotonic


request_cancel_check: ContextVar = ContextVar("request_cancel_check", default=lambda: None)


class ProviderRequestLimiter:
    def __init__(self, delay, remaining, on_rate_limit):
        self.delay = delay
        self.remaining = remaining
        self.on_rate_limit = on_rate_limit
        self._locks: dict[str, asyncio.Lock] = {}
        self._finished: dict[str, float] = {}

    async def run(self, provider, operation):
        # Import lazily because RecreationClient also uses the request decorator.
        from .recreation import RateLimitError

        check_cancel = request_cancel_check.get()

        def check():
            check_cancel()
            seconds = self.remaining(provider)
            if seconds:
                error = RateLimitError(seconds, provider)
                error.cooldown_recorded = True
                raise error

        check()
        lock = self._locks.setdefault(provider, asyncio.Lock())
        # A stopped scan must not wait behind a long discovery request.
        while True:
            check()
            try:
                await asyncio.wait_for(lock.acquire(), timeout=0.25)
                break
            except TimeoutError:
                pass
        try:
            while True:
                check()
                last = self._finished.get(provider)
                wait = self.delay(provider) - (monotonic() - last) if last is not None else 0
                if wait <= 0:
                    break
                await asyncio.sleep(min(wait, 0.25))
            try:
                return await operation()
            except RateLimitError as exc:
                if not getattr(exc, "cooldown_recorded", False):
                    self.on_rate_limit(exc, provider)
                    exc.cooldown_recorded = True
                    exc.retry_after_seconds = max(exc.retry_after_seconds or 0, self.remaining(provider))
                raise
            finally:
                self._finished[provider] = monotonic()
        finally:
            lock.release()


def limited_request(provider=None):
    """Apply at the HTTP boundary, including paginated and metadata requests."""
    def decorate(method):
        @wraps(method)
        async def wrapped(self, *args, **kwargs):
            limiter = getattr(self, "request_limiter", None)
            if limiter is None:
                return await method(self, *args, **kwargs)
            return await limiter.run(provider or self.limiter_key, lambda: method(self, *args, **kwargs))
        return wrapped
    return decorate
