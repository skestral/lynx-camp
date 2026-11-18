"""Selected Apprise destinations; URLs and provider errors never enter app logs."""
import logging
from urllib.parse import urlsplit

from apprise import Apprise, AppriseAsset

# Apprise's plugin diagnostics can contain destination tokens. The app records
# delivery status separately and never forwards the library's free-form logs.
logger = logging.getLogger("apprise")
logger.propagate = False
logger.addHandler(logging.NullHandler())
SCHEMES = {"pushover", "tgram", "twilio"}


def build_client(value: str):
    urls = list(dict.fromkeys(line.strip() for line in value.splitlines() if line.strip()))
    if not 1 <= len(urls) <= 10 or len(value) > 16000:
        raise ValueError("Enter one to ten Apprise destination URLs, one per line")
    client = Apprise(asset=AppriseAsset(app_id="Camp Finder", app_desc="Camp Finder"))
    for index, url in enumerate(urls, 1):
        try:
            supported = urlsplit(url).scheme in SCHEMES and not any(c.isspace() for c in url)
        except ValueError:
            supported = False
        if not supported or not client.add(url):
            raise ValueError(f"Apprise destination {index} is invalid; supported services are Pushover, Telegram, and Twilio")
    for service in client:
        service.socket_connect_timeout = 5
        service.socket_read_timeout = 15
    return client


def validate_urls(value: str):
    build_client(value)


async def send(value: str, message: str) -> dict:
    try:
        client = build_client(value)
        result = await client.async_notify(title="Camp Finder", body=message, timeout=30)
        success = bool(result)
    except Exception:
        success = False
    return {"channel": "apprise", "status": "sent" if success else "error",
            "message": "Apprise delivery completed." if success else "One or more Apprise destinations failed. Check the saved URLs and service credentials."}
