import json
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from browser_worker.session import BrowserSession, retry_deadline


def response(status, retry=None, url="https://washington.goingtocamp.com/public", resource="fetch"):
    return SimpleNamespace(status=status, url=url, headers={"retry-after": retry},
                           request=SimpleNamespace(resource_type=resource))


class GuardTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.profile = Path(directory.name)
        self.session = BrowserSession(self.profile)

    def test_retry_after_never_shortens_the_minimum_cooldown(self):
        now = datetime(2026, 11, 17, tzinfo=UTC)
        for value in (None, "", "invalid", "0", "-1", "60", "9" * 100):
            self.assertEqual(retry_deadline(value, now), now + timedelta(hours=1))
        self.assertEqual(retry_deadline("7200", now), now + timedelta(hours=2))
        self.assertEqual(retry_deadline("Tue, 17 Nov 2026 03:00:00 GMT", now), now + timedelta(hours=3))

    def test_rate_limit_persists_and_cannot_replace_denial(self):
        self.session.observe_response(response(429, "7200"))
        first = self.session.guard["retry_at"]
        self.session.observe_response(response(429, "1"))
        self.assertEqual(self.session.guard["retry_at"], first)
        self.assertEqual(BrowserSession(self.profile).guard, self.session.guard)
        self.session.observe_response(response(403))
        self.assertEqual(self.session.guard["retry_at"], first)
        self.session.observe_response(response(429))
        self.assertEqual(self.session.guard["state"], "access_denied")
        self.assertEqual(self.session.guard["retry_at"], first)
        self.assertNotIn("public", (self.profile / "guard.json").read_text())

    def test_unrelated_hosts_assets_and_success_do_not_stop_inspection(self):
        for item in (response(200), response(403, url="https://other.test"), response(403, resource="image")):
            self.session.observe_response(item)
        self.assertIsNone(self.session.guard)

    def test_corrupt_or_incomplete_saved_guard_fails_closed(self):
        for value in ("not json", "[]", '{"state":"unknown"}', '{"state":"rate_limited"}',
                      '{"state":"rate_limited","retry_at":null}',
                      '{"state":"rate_limited","retry_at":"2026-11-17T00:00:00"}'):
            (self.profile / "guard.json").write_text(value)
            self.assertEqual(BrowserSession(self.profile).guard["state"], "access_denied")
        (self.profile / "guard.json").write_text(json.dumps(None))
        self.assertIsNone(BrowserSession(self.profile).guard)
