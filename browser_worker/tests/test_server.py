import asyncio
import unittest
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from browser_worker.contracts import InspectionError
from browser_worker.server import create_app
from browser_worker.tests.test_contracts import search


class FakeSession:
    def __init__(self):
        self.lock = asyncio.Lock()
        self.start = AsyncMock()
        self.close = AsyncMock()
        self.inspect = AsyncMock(return_value={"complete_scan": False, "scanner_enabled": False})
        self.acknowledge = AsyncMock()

    def status(self):
        return {"browser_running": True, "scanner_enabled": False}


class ServerTests(unittest.TestCase):
    def test_inspect_and_cleanup(self):
        session = FakeSession()
        with TestClient(create_app(session)) as client:
            self.assertEqual(client.get("/health").status_code, 200)
            response = client.post("/inspect", json=search().model_dump(mode="json"))
            self.assertFalse(response.json()["complete_scan"])
            self.assertEqual(client.get("/docs").status_code, 404)
        session.close.assert_awaited_once()

    def test_failures_never_return_success_or_private_exception_text(self):
        for error, code in ((InspectionError("Search mismatch"), 409), (TimeoutError("private URL"), 504),
                            (RuntimeError("private URL"), 502)):
            session = FakeSession()
            session.inspect.side_effect = error
            with TestClient(create_app(session)) as client:
                response = client.post("/inspect", json=search().model_dump(mode="json"))
                self.assertEqual(response.status_code, code)
                self.assertNotIn("private URL", response.text)

    def test_startup_failure_still_closes_browser(self):
        session = FakeSession()
        session.start.side_effect = RuntimeError("startup failed")
        with self.assertRaises(RuntimeError), TestClient(create_app(session)):
            pass
        session.close.assert_awaited_once()

    def test_browser_crash_fails_health_check(self):
        session = FakeSession()
        session.status = lambda: {"browser_running": False}
        with TestClient(create_app(session)) as client:
            self.assertEqual(client.get("/health").status_code, 503)
