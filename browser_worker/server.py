import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException

from .contracts import ExpectedSearch, InspectionError
from .session import BrowserSession


def create_app(session=None):
    browser = session or BrowserSession(Path("/profile"))

    @asynccontextmanager
    async def lifespan(app):
        try:
            await browser.start()
            yield
        finally:
            await browser.close()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/health")
    async def health():
        if not browser.status()["browser_running"]:
            raise HTTPException(503, "Browser is not running")
        return {"status": "ok", "scanner_enabled": False}

    @app.get("/status")
    async def status():
        return browser.status()

    async def operation(fn):
        if browser.lock.locked():
            raise HTTPException(409, "Another browser inspection is active")
        async with browser.lock:
            try:
                return await asyncio.wait_for(fn(), timeout=10)
            except InspectionError as exc:
                raise HTTPException(409, str(exc)) from exc
            except TimeoutError as exc:
                raise HTTPException(504, "Browser inspection timed out; availability is unknown") from exc
            except Exception as exc:
                # Browser exceptions can include URLs or page contents. Keep
                # diagnostics bounded without logging a potentially private page.
                raise HTTPException(502, "Browser inspection failed; availability is unknown") from exc

    @app.post("/inspect")
    async def inspect(expected: ExpectedSearch):
        return await operation(lambda: browser.inspect(expected))

    @app.post("/acknowledge")
    async def acknowledge():
        return await operation(browser.acknowledge)

    return app
