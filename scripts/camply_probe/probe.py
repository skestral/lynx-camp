"""One-shot Washington compatibility probe, isolated from Camp Finder state."""
from __future__ import annotations

import argparse
from datetime import UTC, date, datetime
from importlib.metadata import version
import json
import logging
import time
import traceback
from urllib.parse import urlsplit
from urllib.request import getproxies

import requests


HOST = "washington.goingtocamp.com"
USER_AGENT = "CampFinder/1.0 (availability monitor)"
PATHS = {"/api/resourceLocation", "/api/maps", "/api/availability/map",
         "/api/resource/details", "/api/attribute/filterable"}
QUERY_KEYS = {"mapId", "resourceLocationId", "resourceId", "bookingCategoryId", "startDate", "endDate",
              "isReserving", "getDailyAvailability", "partySize", "numEquipment", "equipmentCategoryId",
              "subEquipmentCategoryId", "filterData"}


class ProbeStopped(RuntimeError):
    """A local guard or provider failure ended the probe."""


class GuardedSession(requests.Session):
    def __init__(self, live=False, limit=12, spacing=5, sender=None, emit=None):
        super().__init__()
        self.live, self.limit, self.spacing = live, limit, spacing
        self.sender, self.emit = sender, emit
        self.records = []
        self.stopped = False
        self.last_response = 0.0

    def request(self, method, url, **kwargs):
        parsed = urlsplit(url)
        if (self.stopped or not self.live or len(self.records) >= self.limit or method.upper() != "GET"
                or parsed.scheme != "https" or parsed.netloc != HOST or parsed.path not in PATHS
                or parsed.query or parsed.fragment or set(kwargs.get("params") or {}) - QUERY_KEYS
                or kwargs.get("data") or kwargs.get("json") or kwargs.get("auth") or kwargs.get("cookies")):
            self.stopped = True
            raise ProbeStopped("request_guard")
        time.sleep(max(0, self.spacing - (time.monotonic() - self.last_response)))
        # Preserve Camply's parsers/query generation, but not browser impersonation,
        # redirects, unbounded waits, or verbose response-body logging.
        headers = dict(kwargs.pop("headers", {}) or {})
        headers = {key: value for key, value in headers.items()
                   if key.lower() not in {"user-agent", "cookie", "authorization", "proxy-authorization"}}
        headers["User-Agent"] = USER_AGENT
        kwargs.update(headers=headers, timeout=20, allow_redirects=False, verify=True)
        started = time.monotonic()
        entry = {"method": "GET", "endpoint": parsed.path, "recorded_at": datetime.now(UTC).isoformat()}
        try:
            response = (self.sender or super().request)(method, url, **kwargs)
        except requests.RequestException as exc:
            entry.update(status=None, outcome="transport_error", error_type=type(exc).__name__)
            self.stopped = True
            raise ProbeStopped("transport_error") from None
        else:
            content_type = response.headers.get("Content-Type", "").split(";", 1)[0].lower()
            prefix = response.content[:16384].decode("utf-8", errors="replace").lower()
            entry.update(status=response.status_code, response_bytes=len(response.content),
                content_type=content_type if content_type in {"application/json", "text/html", "text/plain"} else "other",
                azure_edge_header_present="X-Azure-Ref" in response.headers,
                via_present="Via" in response.headers, cache_header_present="X-Cache" in response.headers,
                set_cookie_present="Set-Cookie" in response.headers,
                request_cookie_present="Cookie" in response.request.headers if response.request else False,
                markers=[name for name, phrases in {
                    "access_denied": ("access denied", "forbidden", "request blocked"),
                    "human_verification": ("captcha", "verify you are human"),
                    "proxy_policy": ("proxy access denied", "blocked by proxy", "proxy policy"),
                }.items() if any(phrase in prefix for phrase in phrases)])
            if response.status_code != 200 or content_type != "application/json":
                entry["outcome"] = "access_denied" if response.status_code in {401, 403} else "http_failure"
                self.stopped = True
                raise ProbeStopped(entry["outcome"])
            if len(response.content) > 8_000_000:
                entry["outcome"] = "response_too_large"
                self.stopped = True
                raise ProbeStopped("response_too_large")
            try:
                payload = response.json()
            except ValueError:
                entry["outcome"] = "invalid_json"
                self.stopped = True
                raise ProbeStopped("invalid_json") from None
            entry["outcome"] = "json_response"
            if isinstance(payload, list):
                entry["item_count"] = len(payload)
                if parsed.path == "/api/maps":
                    entry["missing_location_ids"] = sum(not isinstance(item, dict) or item.get("resourceLocationId") is None for item in payload)
            elif isinstance(payload, dict):
                entry["known_fields"] = sorted(set(payload) & {"mapId", "mapAvailabilities", "mapLinkAvailabilities", "resourceAvailabilities"})
            return response
        finally:
            self.last_response = time.monotonic()
            entry["elapsed_ms"] = round((self.last_response - started) * 1000)
            self.records.append(entry)
            if self.emit:
                self.emit({"request": entry})


def run(live=False, arrival=None, departure=None, not_before=None):
    if not_before and (not_before.tzinfo is None or datetime.now(UTC) < not_before):
        raise ValueError("The supplied cooldown has not elapsed or has no timezone.")
    if live and (arrival is None or departure is None or arrival < datetime.now(UTC).date()
                 or not 1 <= (departure - arrival).days <= 2):
        raise ValueError("Choose a future arrival and a one- or two-night stay.")
    logging.disable(logging.CRITICAL)
    from camply.providers import GoingToCamp

    report = {"camply_version": version("camply"), "pydantic_version": version("pydantic"),
              "live": live, "provider": "Washington State Parks", "recreation_area_id": 3,
              "user_agent": USER_AGENT, "browser_required": False, "automatic_retries": False,
              "request_limit": 12, "request_spacing_seconds": 5,
              "proxy_configured": any(getproxies().get(key) for key in ("http", "https", "all")),
              "roofed_supported": False, "stage": "initialization", "status": "unknown"}
    session = GuardedSession(live=live, emit=lambda entry: print(json.dumps(entry), flush=True))
    provider = GoingToCamp()
    provider.session.close()
    provider.session = session
    try:
        if not live:
            report.update(stage="offline", status="ready", hostname=provider._hostname_for(3))
            return report
        report.update(stage="discovery", arrival=arrival.isoformat(), departure=departure.isoformat())
        campgrounds = provider.find_campgrounds(search_string="Bogachiel", rec_area_id=[3])
        report["campground_count"] = len(campgrounds)
        if len(campgrounds) != 1 or "bogachiel" not in campgrounds[0].facility_name.lower():
            report["status"] = "ambiguous_or_missing_campground"
            return report
        report["stage"] = "availability"
        candidates = provider.list_site_availability(campgrounds[0], arrival, departure, equipment_type_id=None)
        report["candidate_count"] = len(candidates)
        if candidates:
            report["stage"] = "site_details"
            details = provider.get_site_details(3, candidates[0].resource_id)
            report["site_details_returned"] = isinstance(details, dict)
        report["status"] = "provider_returned_results"
    except ProbeStopped as exc:
        report.update(status="stopped", reason=str(exc))
    except Exception as exc:
        report.update(status="library_error", error_type=type(exc).__name__)
        report["library_frames"] = [
            {"file": frame.filename.rsplit("/camply/", 1)[-1], "line": frame.lineno, "function": frame.name}
            for frame in traceback.extract_tb(exc.__traceback__) if "/camply/" in frame.filename]
    finally:
        report["requests"] = session.records
        session.close()
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Allow the bounded public provider check.")
    parser.add_argument("--arrival", type=date.fromisoformat)
    parser.add_argument("--departure", type=date.fromisoformat)
    parser.add_argument("--not-before", type=datetime.fromisoformat, help="Honor an existing ISO timestamp with timezone.")
    args = parser.parse_args()
    try:
        report = run(args.live, args.arrival, args.departure, args.not_before)
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps({"report": report}, indent=2), flush=True)
    return 0 if report["status"] in {"ready", "provider_returned_results"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
