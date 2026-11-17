import base64
import os
import unittest
from unittest.mock import patch

from websockify.auth_plugins import AuthenticationError

from browser_worker.auth import ConsoleAuth, console_password


class AuthTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {"CAMPFINDER_BROWSER_PASSWORD": "test-only-long-password"})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.auth = ConsoleAuth()
        self.headers = {"Authorization": "Basic " + base64.b64encode(b"campfinder:test-only-long-password").decode(),
                        "Host": "127.0.0.1:6080"}

    def test_correct_credentials_and_same_origin_websocket(self):
        self.auth.authenticate(self.headers, "127.0.0.1", 5900)
        self.auth.authenticate({**self.headers, "Origin": "http://127.0.0.1:6080", "Upgrade": "websocket"}, "127.0.0.1", 5900)

    def test_missing_bad_and_malformed_credentials_are_rejected(self):
        for value in ("", "Bearer value", "Basic !!!", "Basic a", "Basic " + "x" * 9000,
                      "Basic " + base64.b64encode(b"campfinder:wrong").decode()):
            with self.subTest(value=value[:30]), self.assertRaises(AuthenticationError):
                self.auth.authenticate({**self.headers, "Authorization": value}, "127.0.0.1", 5900)

    def test_cross_origin_or_missing_origin_websocket_is_rejected(self):
        for origin in (None, "null", "https://evil.test", "http://127.0.0.1:6080/path", "http://[bad"):
            with self.subTest(origin=origin), self.assertRaises(AuthenticationError):
                headers = {**self.headers, "Upgrade": "websocket"}
                if origin:
                    headers["Origin"] = origin
                self.auth.authenticate(headers, "127.0.0.1", 5900)

    def test_password_requirements(self):
        for value in ("", "short", "long-enough-but-\ninvalid", "long-enough-but-\x7finvalid", "unicode-password-\u00e9"):
            with patch.dict(os.environ, {"CAMPFINDER_BROWSER_PASSWORD": value}), self.assertRaises(ValueError):
                console_password()
