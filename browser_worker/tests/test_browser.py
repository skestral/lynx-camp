import asyncio
import html
import os
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from browser_worker.contracts import InspectionError
from browser_worker.session import BrowserSession
from browser_worker.tests.test_contracts import search, search_url


def results_html(category="Camping", selected=True, populated=True):
    expected = search(category)
    results = f"""<ul aria-label="{html.escape(expected.results_label())}">
        <li><button id="mapLink-button-1">Example loop</button></li>
        <li>Site 2: Available <button id="reserveButton-2">Reserve</button></li>
        </ul><button id="loadMoreButton">View more</button>""" if populated else "<p>Loading</p>"
    return f"""<!doctype html><html lang="en"><title>Synthetic reservation fixture</title><body>
        <input id="park-autocomplete-input" value="Example Park">
        <button role="tab" aria-selected="{str(selected).lower()}">{category}</button>
        <button id="actionSearch">Search</button>{results}
        </body></html>"""


@unittest.skipUnless(os.environ.get("CAMPFINDER_BROWSER_TESTS") == "1", "Run in the isolated Docker test workspace")
class BrowserTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.session = BrowserSession(Path(self.directory.name))
        self.addAsyncCleanup(self.session.close)
        await self.session.start()
        self.page = self.session.context.pages[0]
        self.body = results_html()
        self.status_code = 200

        async def fixture(route):
            await route.fulfill(status=self.status_code, content_type="text/html", body=self.body)

        # Every HTTP(S) navigation is fulfilled locally. No live provider requests.
        await self.session.context.route("**/*", fixture)

    async def test_blank_start_and_sandbox(self):
        self.assertEqual(self.page.url, "about:blank")
        self.assertTrue(self.session.status()["browser_running"])
        self.assertFalse(self.session.status()["scanner_enabled"])
        await self.page.goto("chrome://sandbox")
        text = await self.page.locator("body").inner_text()
        self.assertRegex(text, r"Layer 1 Sandbox\s+Namespace")
        self.assertRegex(text, r"PID namespaces\s+Yes")
        self.assertRegex(text, r"Network namespaces\s+Yes")
        self.assertRegex(text, r"Seccomp-BPF sandbox\s+Yes")
        await self.session.close()
        self.assertFalse(self.session.status()["browser_running"])

    async def test_camping_and_roofed_inspection_never_claim_a_complete_scan(self):
        for category in ("Camping", "Roofed"):
            self.body = results_html(category)
            await self.page.goto(search_url(search(category)))
            result = await self.session.inspect(search(category))
            self.assertFalse(result["complete_scan"])
            self.assertFalse(result["scanner_enabled"])
            self.assertEqual(result["child_map_count"], 1)
            self.assertTrue(result["more_pages"])
            self.assertIn("Site 2", result["rendered_results"])

    async def test_changed_category_and_park_are_rejected(self):
        await self.page.goto(search_url())
        await self.page.locator("#park-autocomplete-input").fill("Different Park")
        with self.assertRaisesRegex(InspectionError, "Park form"):
            await self.session.inspect(search())
        await self.page.locator("#park-autocomplete-input").fill("Example Park")
        self.body = results_html(selected=False)
        await self.page.reload()
        with self.assertRaisesRegex(InspectionError, "category"):
            await self.session.inspect(search())

    async def test_loading_is_not_empty_availability(self):
        self.body = results_html(populated=False)
        await self.page.goto(search_url())
        with self.assertRaisesRegex(InspectionError, "not an empty"):
            await self.session.inspect(search())

    async def test_wrong_dates_and_multiple_tabs_are_rejected(self):
        await self.page.goto(search_url(startDate="2026-11-27"))
        with self.assertRaisesRegex(InspectionError, "does not match"):
            await self.session.inspect(search())
        second = await self.session.context.new_page()
        await second.goto(search_url())
        with self.assertRaisesRegex(InspectionError, "exactly one"):
            await self.session.inspect(search())

    async def test_account_pages_are_not_inspected(self):
        await self.page.goto("https://washington.goingtocamp.com/account")
        with self.assertRaisesRegex(InspectionError, "account pages are not inspected"):
            await self.session.inspect(search())

    async def test_challenge_page_persists_a_stop(self):
        self.body = "<p>Verify you are human</p>"
        await self.page.goto(search_url())
        with self.assertRaisesRegex(InspectionError, "manual attention"):
            await self.session.inspect(search())
        self.assertEqual(BrowserSession(Path(self.directory.name)).guard["state"], "access_denied")

    async def test_rate_limit_cannot_be_acknowledged_early(self):
        self.status_code = 429
        await self.page.goto(search_url())
        await asyncio.sleep(0)
        self.assertEqual(self.session.guard["state"], "rate_limited")
        with self.assertRaisesRegex(InspectionError, "cooldown"):
            await self.session.acknowledge()
        with self.assertRaisesRegex(InspectionError, "guard is active"):
            await self.session.inspect(search())
        self.status_code = 200
        await self.page.reload()
        self.session.guard["retry_at"] = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
        await self.session.acknowledge()
        self.assertIsNone(BrowserSession(Path(self.directory.name)).guard)

    async def test_context_closed_event_marks_worker_unhealthy(self):
        await self.session.context.close()
        self.assertFalse(self.session.status()["browser_running"])

    async def test_dedicated_profile_survives_restart_without_restoring_a_provider_page(self):
        await self.page.goto("about:blank")
        await self.session.context.add_cookies([{"name": "test_marker", "value": "synthetic",
                                               "domain": "example.invalid", "path": "/",
                                               "expires": (datetime.now(UTC) + timedelta(days=1)).timestamp()}])
        await self.session.close()
        await self.session.start()
        self.assertTrue(all(page.url == "about:blank" for page in self.session.context.pages))
        cookies = await self.session.context.cookies("https://example.invalid")
        self.assertEqual([(cookie["name"], cookie["value"]) for cookie in cookies], [("test_marker", "synthetic")])
