"""Allowlisted HTTP evidence; never persist raw bodies, headers, or URLs."""
from __future__ import annotations

from datetime import UTC, date, datetime
import json
import logging
import os
import re
from typing import Literal
from urllib.request import getproxies
from uuid import uuid4

import httpx
from pydantic import BaseModel, ConfigDict, Field
from .provider_registry import gtc_state_key


STATE_KEY = "goingtocamp_diagnostics"
HISTORY_LIMIT = 30
BODY_MARKERS = {
    "access_denied": ("access denied", "access is denied", "request blocked", "request was blocked"),
    "forbidden": ("forbidden",),
    "human_verification": ("captcha", "verify you are human", "verify that you are human"),
    "proxy_policy": ("proxy access denied", "blocked by proxy", "proxy policy"),
    "login_required": ("login required", "authentication required", "sign in to continue"),
}
QUERY_KEYS = {"mapId", "resourceLocationId", "bookingCategoryId", "startDate", "endDate", "isReserving",
              "getDailyAvailability", "partySize", "filterData", "equipmentCategoryId", "numEquipment"}
REQUEST_ID_HEADERS = ("x-request-id", "x-correlation-id", "x-amzn-requestid", "cf-ray")
ID_PATTERN = re.compile(r"(?:[0-9a-f]{32}|[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}|[0-9a-f]{16}-[A-Z]{3})", re.I)


class DiagnosticRecord(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)
    id: str = Field(pattern=r"^[0-9a-f]{32}$")
    recorded_at: str = Field(max_length=40)
    endpoint: Literal["/resourceLocation", "/resourcelocation", "/resourcecategory", "/availability/map", "/rdr/fd/places", "/rdr/fd/facilities", "/rdr/search/filters", "/rdr/search/grid"]
    method: Literal["GET", "POST"] = "GET"
    query: dict[str, str] = Field(default_factory=dict)
    status: int | None = Field(default=None, ge=100, le=599)
    outcome: Literal["json_response", "access_denied", "rate_limited", "http_error", "invalid_json", "response_too_large", "transport_error"]
    elapsed_ms: int = Field(ge=0, le=86_400_000)
    response_bytes: int = Field(default=0, ge=0)
    content_type: Literal["application/json", "text/html", "text/plain", "other", "missing"] = "missing"
    server_family: Literal["cloudflare", "akamai", "azure", "nginx", "envoy", "varnish", "iis", "other", "missing"] = "missing"
    markers: list[str] = Field(default_factory=list)
    request_ids: dict[str, str] = Field(default_factory=dict)
    via_present: bool = False
    cache_header_present: bool = False
    azure_edge_header_present: bool = False
    set_cookie_present: bool = False
    request_cookie_present: bool = False
    authenticate_header_present: bool = False
    redirect: Literal["none", "same_origin", "other_origin", "unparseable"] = "none"
    transport_error: Literal["timeout", "proxy", "connection", "protocol", "other"] | None = None
    proxy_configured: bool = False
    no_proxy_configured: bool = False
    custom_ca_configured: bool = False


def safe_query(params) -> dict[str, str]:
    result = {}
    for key, value in dict(params or {}).items():
        value = str(value)
        if key not in QUERY_KEYS:
            continue
        if key in {"startDate", "endDate"}:
            try:
                if date.fromisoformat(value).isoformat() == value:
                    result[key] = value
            except ValueError:
                pass
        elif key in {"isReserving", "getDailyAvailability"}:
            if value in {"true", "false"}:
                result[key] = value
        elif key == "filterData":
            if value == "[]":
                result[key] = value
        elif re.fullmatch(r"-?(?:0|[1-9][0-9]{0,9})", value) and -(2**31) <= int(value) < 2**31:
            result[key] = value
    return result


def sanitize_record(value) -> dict | None:
    try:
        record = DiagnosticRecord.model_validate(value).model_dump()
        timestamp = datetime.fromisoformat(record["recorded_at"])
        if timestamp.tzinfo is None:
            return None
        record["query"] = safe_query(record["query"])
        record["markers"] = sorted(set(record["markers"]) & BODY_MARKERS.keys())
        record["request_ids"] = {key: val for key, val in record["request_ids"].items()
                                 if key in REQUEST_ID_HEADERS and ID_PATTERN.fullmatch(val)}
        return record
    except (ValueError, TypeError):
        return None


def read_diagnostics(store, tenant="wa") -> list[dict]:
    if store is None:
        return []
    key = gtc_state_key(tenant, "diagnostics")
    raw = store.get_app_settings([key]).get(key, "[]")
    try:
        values = json.loads(raw)
        if not isinstance(values, list):
            return []
        return [record for value in values[:HISTORY_LIMIT] if (record := sanitize_record(value))]
    except (ValueError, TypeError):
        return []


def diagnostic_record(path: str, params: dict | None, elapsed: float, *, response: httpx.Response | None = None,
                      error: httpx.RequestError | None = None, outcome: str) -> dict:
    proxies = getproxies()
    record = {
        "id": uuid4().hex, "recorded_at": datetime.now(UTC).isoformat(), "endpoint": path,
        "query": safe_query(params), "outcome": outcome, "method": "POST" if path == "/rdr/search/grid" else "GET",
        "elapsed_ms": max(0, min(86_400_000, int(elapsed * 1000))),
        "proxy_configured": any(proxies.get(key) for key in ("http", "https", "all")),
        "no_proxy_configured": bool(proxies.get("no")),
        "custom_ca_configured": bool(os.getenv("SSL_CERT_FILE") or os.getenv("SSL_CERT_DIR")),
    }
    if error is not None:
        record["transport_error"] = ("timeout" if isinstance(error, httpx.TimeoutException) else
                                     "proxy" if isinstance(error, httpx.ProxyError) else
                                     "connection" if isinstance(error, httpx.ConnectError) else
                                     "protocol" if isinstance(error, httpx.ProtocolError) else "other")
    if response is not None:
        headers = response.headers
        content_type = headers.get("content-type", "").split(";", 1)[0].strip().lower()
        server = headers.get("server", "").lower()
        server_family = next((family for family in ("cloudflare", "akamai", "azure", "nginx", "envoy", "varnish", "iis") if family in server), "other" if server else "missing")
        # Only classify a small prefix. Free-form text and tokens never leave memory.
        prefix = response.content[:16384].decode("utf-8", errors="replace").lower()
        markers = [name for name, phrases in BODY_MARKERS.items() if any(phrase in prefix for phrase in phrases)]
        redirect = "none"
        if "location" in headers:
            try:
                target = response.request.url.join(headers["location"])
                origin = response.request.url
                redirect = "same_origin" if (target.scheme, target.host, target.port) == (origin.scheme, origin.host, origin.port) else "other_origin"
            except (ValueError, httpx.InvalidURL, RuntimeError):
                redirect = "unparseable"
        record.update(status=response.status_code, response_bytes=len(response.content),
                      content_type=content_type if content_type in {"application/json", "text/html", "text/plain"} else "other" if content_type else "missing",
                      server_family=server_family, markers=markers, redirect=redirect,
                      via_present="via" in headers, cache_header_present="x-cache" in headers,
                      azure_edge_header_present="x-azure-ref" in headers,
                      set_cookie_present="set-cookie" in headers, authenticate_header_present="www-authenticate" in headers,
                      request_ids={key: headers[key] for key in REQUEST_ID_HEADERS
                                   if key in headers and ID_PATTERN.fullmatch(headers[key])})
        try:
            record["request_cookie_present"] = "cookie" in response.request.headers
        except RuntimeError:
            pass
    return DiagnosticRecord.model_validate(record).model_dump()


def save_diagnostic(store, record: dict, tenant="wa") -> None:
    if store is None:
        return
    # Called under the provider request lock: there is one serialized writer.
    try:
        record = sanitize_record(record)
        if record is None:
            return
        history = read_diagnostics(store, tenant)
        store.set_app_settings({gtc_state_key(tenant, "diagnostics"): json.dumps([record, *history][:HISTORY_LIMIT])})
    except Exception:
        logging.getLogger(__name__).warning("Could not persist Washington HTTP diagnostics.")


def capture_diagnostic(store, path, params, elapsed, *, tenant="wa", **kwargs) -> None:
    if store is None:
        return
    try:
        save_diagnostic(store, diagnostic_record(path, params, elapsed, **kwargs), tenant)
    except Exception:
        # Diagnostics must not mask a provider error or disable its access stop.
        logging.getLogger(__name__).warning("Could not capture Washington HTTP diagnostics.")
