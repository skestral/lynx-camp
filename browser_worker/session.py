"""Passive UI inspection. This module never searches, logs in, or reserves a site."""
import asyncio
import json
import os
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlsplit

from .contracts import ExpectedSearch, InspectionError, is_provider_url, validate_submitted_search


def retry_deadline(value: str | None, now: datetime) -> datetime:
    floor = now + timedelta(hours=1)
    try:
        if value and value.isdigit():
            return max(floor, now + timedelta(seconds=int(value)))
        if value:
            deadline = parsedate_to_datetime(value)
            if deadline.tzinfo:
                return max(floor, deadline.astimezone(UTC))
    except (ValueError, OverflowError, TypeError):
        pass
    return floor


class BrowserSession:
    def __init__(self, profile: Path):
        self.profile = profile
        self.context = None
        self.playwright = None
        self.lock = asyncio.Lock()
        self.guard = None
        self.running = False
        try:
            guard = json.loads((profile / "guard.json").read_text(encoding="utf-8"))
            if guard is not None and (not isinstance(guard, dict) or guard.get("state") not in {"access_denied", "rate_limited"}):
                raise ValueError("Invalid guard state")
            if guard and guard["state"] == "rate_limited":
                deadline = datetime.fromisoformat(guard.get("retry_at", ""))
                if deadline.tzinfo is None:
                    raise ValueError("Invalid guard deadline")
                guard["retry_at"] = deadline.astimezone(UTC).isoformat()
            self.guard = guard
        except FileNotFoundError:
            pass
        except (ValueError, TypeError, OSError):
            self.guard = {"state": "access_denied", "reason": "Saved browser guard needs review"}

    async def start(self):
        from playwright.async_api import async_playwright

        self.playwright = await async_playwright().start()
        self.context = await self.playwright.chromium.launch_persistent_context(
            str(self.profile / "chromium"), headless=False, chromium_sandbox=True,
            viewport={"width": 1280, "height": 900},
            env={key: value for key, value in os.environ.items() if key != "CAMPFINDER_BROWSER_PASSWORD"},
        )
        self.context.on("response", self.observe_response)
        self.context.on("close", lambda _: setattr(self, "running", False))
        self.running = True
        # Persistent cookies stay in this dedicated profile, but never restore a
        # provider page or issue a provider request automatically at startup.
        for page in self.context.pages:
            await page.goto("about:blank")
        if not self.context.pages:
            await self.context.new_page()

    def observe_response(self, response):
        if (not is_provider_url(response.url) or response.status not in {401, 403, 429}
                or response.request.resource_type not in {"document", "xhr", "fetch"}):
            return
        now = datetime.now(UTC)
        if response.status == 429:
            guard = {"state": "rate_limited", "observed_at": now.isoformat(),
                     "retry_at": retry_deadline(response.headers.get("retry-after"), now).isoformat()}
        else:
            guard = {"state": "access_denied", "observed_at": now.isoformat()}
        # Denial takes precedence, but must not erase a pending cooldown.
        if self.guard:
            if self.guard["state"] == "access_denied":
                guard["state"] = "access_denied"
            deadline = max(guard.get("retry_at", ""), self.guard.get("retry_at", ""))
            if deadline:
                guard["retry_at"] = deadline
        self.guard = guard
        self.save_guard()

    def save_guard(self):
        self.profile.mkdir(parents=True, exist_ok=True)
        temporary = self.profile / "guard.json.tmp"
        temporary.write_text(json.dumps(self.guard), encoding="utf-8")
        temporary.replace(self.profile / "guard.json")

    def status(self):
        pages = [] if self.context is None else [page for page in self.context.pages if is_provider_url(page.url)]
        return {"browser_running": self.running, "provider_tabs": len(pages),
                "state": self.guard["state"] if self.guard else "manual_setup",
                "guard": self.guard, "scanner_enabled": False}

    async def provider_page(self):
        pages = [] if self.context is None else [page for page in self.context.pages if is_provider_url(page.url)]
        if len(pages) != 1:
            raise InspectionError("Open exactly one Washington reservation tab in the private browser console")
        page = pages[0]
        if urlsplit(page.url).path != "/create-booking/results":
            raise InspectionError("Open the public reservation results page first; account pages are not inspected")
        # Do not read any unrelated page, account record, browser storage, or cookies.
        body = (await page.locator("body").inner_text(timeout=3000)).lower()
        if any(text in body for text in ("access denied", "verify you are human", "request blocked", "unusual traffic")):
            self.guard = {"state": "access_denied", "observed_at": datetime.now(UTC).isoformat()}
            self.save_guard()
            raise InspectionError("Browser requires manual attention; no inspection was performed")
        return page

    async def inspect(self, expected: ExpectedSearch):
        if self.guard:
            raise InspectionError("Browser guard is active; inspect status and resolve it manually first")
        page = await self.provider_page()
        before = page.url
        submitted = validate_submitted_search(before, expected)
        if await page.locator("#park-autocomplete-input").input_value() != expected.park:
            raise InspectionError("Park form has changed since the submitted search")
        tab = page.get_by_role("tab", name=expected.category, exact=True)
        if await tab.get_attribute("aria-selected") != "true":
            raise InspectionError("Accommodation category has changed since the submitted search")
        results = page.get_by_role("list", name=expected.results_label(), exact=True)
        if await results.count() != 1 or not await results.is_visible():
            raise InspectionError("Matching results have not loaded; this is not an empty availability result")
        snapshot = await results.aria_snapshot(timeout=3000)
        if len(snapshot) > 40000:
            raise InspectionError("Result page exceeds the diagnostic output limit")
        child_maps = await results.locator('[id^="mapLink-button-"]').count()
        more = await page.locator("#loadMoreButton").is_visible()
        if page.url != before or self.guard:
            raise InspectionError("Page changed during inspection; discard this snapshot")
        return {"state": "inspection_only", "scanner_enabled": False, "complete_scan": False,
                "submitted_search": submitted, "child_map_count": child_maps,
                "more_pages": more, "rendered_results": snapshot}

    async def acknowledge(self):
        if self.guard and self.guard.get("retry_at"):
            try:
                deadline = datetime.fromisoformat(self.guard["retry_at"])
            except (ValueError, TypeError) as exc:
                raise InspectionError("Saved cooldown needs review") from exc
            if deadline.tzinfo is None:
                raise InspectionError("Saved cooldown needs review")
            if deadline > datetime.now(UTC):
                raise InspectionError("Provider cooldown has not elapsed")
        page = await self.provider_page()
        if not await page.locator("#actionSearch").is_visible():
            raise InspectionError("Resolve the browser state manually before acknowledging it")
        self.guard = None
        self.save_guard()
        return self.status()

    async def close(self):
        self.running = False
        try:
            if self.context:
                await self.context.close()
        finally:
            self.context = None
            if self.playwright:
                await self.playwright.stop()
                self.playwright = None
