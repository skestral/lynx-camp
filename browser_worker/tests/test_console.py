import os
import unittest
from pathlib import Path


@unittest.skipUnless(os.environ.get("CAMPFINDER_BROWSER_TESTS") == "1", "Run in the isolated Docker test workspace")
class ConsoleBrowserTests(unittest.IsolatedAsyncioTestCase):
    async def test_console_connects_and_renders_browser_display(self):
        from playwright.async_api import async_playwright

        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(
                headless=True, chromium_sandbox=True,
                env={key: value for key, value in os.environ.items() if key != "CAMPFINDER_BROWSER_PASSWORD"})
            try:
                context = await browser.new_context(http_credentials={
                    "username": "campfinder", "password": os.environ["CAMPFINDER_BROWSER_PASSWORD"]})
                page = await context.new_page()
                await page.goto("http://127.0.0.1:6080/vnc.html?autoconnect=true&resize=scale")
                await page.wait_for_function("document.documentElement.classList.contains('noVNC_connected')", timeout=15000)
                canvas = page.locator("#noVNC_container canvas")
                await canvas.wait_for(state="visible")
                pixels = await canvas.evaluate("""canvas => {
                    const {width, height} = canvas;
                    const data = canvas.getContext('2d').getImageData(0, 0, width, height).data;
                    const colors = new Set();
                    for (let i = 0; i < data.length; i += 64) {
                        colors.add(`${data[i]},${data[i+1]},${data[i+2]}`);
                    }
                    return {width, height, colors: colors.size};
                }""")
                self.assertGreaterEqual(pixels["width"], 1000)
                self.assertGreaterEqual(pixels["height"], 700)
                self.assertGreater(pixels["colors"], 8, "Console framebuffer is blank")
                await page.screenshot(path="/tmp/test-browser-console.png")
            finally:
                await browser.close()

    async def test_chromium_does_not_inherit_console_password(self):
        found = 0
        for directory in Path("/proc").iterdir():
            if not directory.name.isdigit():
                continue
            try:
                command = (directory / "cmdline").read_bytes().split(b"\0")[0]
                if command.endswith(b"/chrome"):
                    found += 1
                    self.assertNotIn(b"CAMPFINDER_BROWSER_PASSWORD=", (directory / "environ").read_bytes())
            except (FileNotFoundError, PermissionError):
                continue
        self.assertGreater(found, 0)
