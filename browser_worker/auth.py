"""Console authentication without putting a password in process arguments."""
import base64
import binascii
import hmac
import os
from urllib.parse import urlsplit

from websockify.auth_plugins import BasicHTTPAuth


def console_password() -> str:
    password = os.environ.get("CAMPFINDER_BROWSER_PASSWORD", "")
    if len(password) < 16 or not password.isascii() or any(not 32 <= ord(char) <= 126 for char in password):
        raise ValueError("Browser console password must contain at least 16 printable ASCII characters")
    return password


class ConsoleAuth(BasicHTTPAuth):
    def __init__(self, src=None):
        self.password = console_password()

    def validate_creds(self, username, password):
        return (hmac.compare_digest(username.encode(), b"campfinder")
                & hmac.compare_digest(password.encode(), self.password.encode()))

    def authenticate(self, headers, target_host, target_port):
        # Browsers attach cached Basic credentials to WebSockets too. Reject
        # cross-origin control attempts even when the password is correct.
        origin = headers.get("Origin")
        if origin or headers.get("Upgrade", "").lower() == "websocket":
            try:
                parsed = urlsplit(origin or "")
                if (parsed.scheme not in {"http", "https"} or parsed.netloc != headers.get("Host")
                        or parsed.path or parsed.query or parsed.fragment):
                    self.auth_error()
            except ValueError:
                self.auth_error()
        header = headers.get("Authorization", "")
        if not header.startswith("Basic ") or len(header) > 8192:
            self.demand_auth()
        try:
            raw = base64.b64decode(header[6:], validate=True).decode("ascii")
            username, password = raw.split(":", 1)
        except (ValueError, UnicodeDecodeError, binascii.Error):
            self.demand_auth()
        if not self.validate_creds(username, password):
            self.demand_auth()
