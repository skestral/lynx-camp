"""Keep slow SQLite work off the API loop without abandoning active writes."""
import asyncio
import logging
import time


logger = logging.getLogger(__name__)


async def database_call(function, *args, **kwargs):
    started = time.monotonic()
    task = asyncio.create_task(asyncio.to_thread(function, *args, **kwargs))
    cancelled = False
    try:
        # A cancelled coroutine cannot stop SQLite in a worker. Keep the caller's
        # scan lock held until the transaction commits or rolls back.
        while True:
            try:
                result = await asyncio.shield(task)
                break
            except asyncio.CancelledError:
                if task.cancelled():
                    raise
                cancelled = True
        if cancelled:
            raise asyncio.CancelledError
        return result
    finally:
        elapsed = time.monotonic() - started
        if elapsed >= 2:
            logger.warning("Slow database operation: %s took %.2fs", function.__name__, elapsed)


async def monitor_event_loop(interval=1.0, warning_after=2.0):
    loop = asyncio.get_running_loop()
    while True:
        expected = loop.time() + interval
        await asyncio.sleep(interval)
        lag = loop.time() - expected
        if lag >= warning_after:
            logger.warning("API event loop stalled for %.2fs; dashboard requests may have timed out", lag)
