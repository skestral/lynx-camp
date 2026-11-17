"""Offline guard tests. No provider or notification traffic."""
from datetime import UTC, date, datetime, timedelta
import json
import unittest
from unittest.mock import patch

import requests

from probe import GuardedSession, ProbeStopped, USER_AGENT, run


URL = "https://washington.goingtocamp.com/api/resourceLocation"


def response(status=200, body="[]", headers=None):
    result = requests.Response()
    result.status_code = status
    result._content = body.encode()
    result.headers.update(headers or {"Content-Type": "application/json"})
    result.request = requests.Request("GET", URL).prepare()
    return result


class ProbeTests(unittest.TestCase):
    def test_offline_initialization(self):
        report = run()
        self.assertEqual(report["status"], "ready")
        self.assertEqual(report["hostname"], "washington.goingtocamp.com")
        self.assertEqual(report["requests"], [])

    def test_cooldown_blocks_before_initialization(self):
        with self.assertRaises(ValueError):
            run(True, date(2027, 6, 4), date(2027, 6, 6), datetime.now(UTC) + timedelta(hours=1))

    def test_guards_reject_unsafe_requests(self):
        for method, url, kwargs in [("POST", URL, {}), ("GET", URL.replace("https:", "http:"), {}),
            ("GET", "https://other.test/api/maps", {}), ("GET", URL + "?token=secret", {}),
            ("GET", URL, {"params": {"cartUid": "secret"}}),
            ("GET", "https://washington.goingtocamp.com/api/cart/add", {})]:
            with self.subTest(url=url, method=method):
                session = GuardedSession(live=True, spacing=0, sender=lambda *a, **k: self.fail("Unexpected request"))
                with self.assertRaises(ProbeStopped):
                    session.request(method, url, **kwargs)
                self.assertEqual(session.records, [])

    def test_denial_stops_and_redacts(self):
        secret = "never-store-this"
        calls = []
        def sender(*args, **kwargs):
            calls.append(kwargs)
            return response(403, f"Access denied {secret}", {"Content-Type": "text/html", "Set-Cookie": secret})
        session = GuardedSession(live=True, spacing=0, sender=sender)
        for _ in range(2):
            with self.assertRaises(ProbeStopped):
                session.get(URL, headers={"User-Agent": "browser", "Authorization": secret, "Cookie": secret})
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["headers"]["User-Agent"], USER_AGENT)
        self.assertFalse(calls[0]["allow_redirects"])
        self.assertTrue(calls[0]["verify"])
        self.assertEqual(calls[0]["timeout"], 20)
        self.assertNotIn(secret, json.dumps(session.records))
        self.assertEqual(session.records[0]["status"], 403)

    def test_request_limit(self):
        session = GuardedSession(live=True, limit=1, spacing=0, sender=lambda *a, **k: response())
        session.get(URL)
        with self.assertRaises(ProbeStopped):
            session.get(URL)
        self.assertEqual(len(session.records), 1)

    def test_spacing(self):
        session = GuardedSession(live=True, sender=lambda *a, **k: response())
        with patch("probe.time.sleep") as sleep, patch("probe.time.monotonic", return_value=100):
            session.get(URL)
            session.get(URL)
        self.assertEqual(sleep.call_args.args[0], 5)

    def test_transport_error_is_redacted(self):
        def sender(*args, **kwargs):
            raise requests.ConnectTimeout("secret proxy credentials")
        session = GuardedSession(live=True, spacing=0, sender=sender)
        with self.assertRaises(ProbeStopped):
            session.get(URL)
        self.assertNotIn("secret", json.dumps(session.records))
        self.assertEqual(session.records[0]["error_type"], "ConnectTimeout")

    def test_bad_responses_stop(self):
        for status, body in [(302, "[]"), (429, "[]"), (200, "invalid json")]:
            with self.subTest(status=status, body=body):
                session = GuardedSession(live=True, spacing=0, sender=lambda *a, **k: response(status, body))
                with self.assertRaises(ProbeStopped):
                    session.get(URL)
                self.assertTrue(session.stopped)

    def test_actual_camply_workflow_with_synthetic_responses(self):
        catalog = [{"resourceLocationId": -1, "resourceCategoryIds": [-2147483648],
                    "localizedValues": [{"fullName": "Bogachiel"}]}]
        fixtures = {"/api/resourceLocation": catalog, "/api/maps": [{"resourceLocationId": -1, "mapId": -100}],
                    "/api/availability/map": {"resourceAvailabilities": {}, "mapLinkAvailabilities": {}}}
        def sender(method, url, **kwargs):
            self.assertEqual(kwargs["headers"]["User-Agent"], USER_AGENT)
            return response(body=json.dumps(fixtures[url.removeprefix("https://washington.goingtocamp.com")]))
        session = GuardedSession(live=True, spacing=0, sender=sender)
        arrival = datetime.now(UTC).date() + timedelta(days=12)
        with patch("probe.GuardedSession", return_value=session):
            report = run(True, arrival, arrival + timedelta(days=1))
        self.assertEqual(report["status"], "provider_returned_results")
        self.assertEqual(report["campground_count"], 1)
        self.assertEqual(report["candidate_count"], 0)
        self.assertEqual(len(session.records), 3)

    def test_library_schema_failure_is_distinct_from_denial(self):
        catalog = [{"resourceLocationId": -1, "resourceCategoryIds": [-2147483648],
                    "localizedValues": [{"fullName": "Bogachiel"}]}]
        def sender(method, url, **kwargs):
            return response(body=json.dumps(catalog if url.endswith("resourceLocation") else [{"mapId": -100}]))
        session = GuardedSession(live=True, spacing=0, sender=sender)
        arrival = datetime.now(UTC).date() + timedelta(days=12)
        with patch("probe.GuardedSession", return_value=session):
            report = run(True, arrival, arrival + timedelta(days=1))
        self.assertEqual(report["status"], "library_error")
        self.assertEqual(report["error_type"], "KeyError")
        self.assertEqual(report["stage"], "discovery")
        self.assertEqual([entry["status"] for entry in session.records], [200, 200])


if __name__ == "__main__":
    unittest.main()
