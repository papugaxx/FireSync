"""Small standard-library client for the documented NASA FIRMS API."""

from datetime import date
import email.utils
import http.client
import json
import math
from pathlib import Path
import re
import ssl
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

from .errors import ConfigurationError, NetworkError, ProtocolError, QuotaError
from .parsing import parse_availability, validate_observation_header
from .types import Availability, FetchPayload, PRODUCTS, Scope, utc_now


_HOST = "firms.modaps.eosdis.nasa.gov"
_BASE = f"https://{_HOST}"


class _SameHostRedirect(HTTPRedirectHandler):
    max_redirections = 3

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        try:
            target = urlsplit(newurl)
            allowed = (target.scheme == "https" and target.hostname == _HOST
                       and target.port in (None, 443) and not target.username and not target.password)
        except ValueError:
            allowed = False
        if not allowed:
            raise ProtocolError("NASA redirected the request outside its allowed HTTPS host.") from None
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class FirmsClient:
    def __init__(self, api_key, timeout=30, max_response_bytes=64 * 1024 * 1024, retries=2):
        if not isinstance(api_key, str) or not api_key.strip():
            raise ConfigurationError("Set FIRMS_MAP_KEY before making NASA API requests.")
        key = api_key.strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,256}", key):
            raise ConfigurationError("FIRMS_MAP_KEY contains unsupported characters.")
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
            raise ConfigurationError("Request timeout must be a positive finite number.")
        if isinstance(max_response_bytes, bool) or not isinstance(max_response_bytes, int) or max_response_bytes < 1:
            raise ConfigurationError("Maximum response size must be a positive integer.")
        if isinstance(retries, bool) or not isinstance(retries, int) or not 0 <= retries <= 5:
            raise ConfigurationError("Retries must be an integer between zero and five.")
        self._api_key = key
        self.timeout = float(timeout)
        self.max_response_bytes = max_response_bytes
        self.retries = retries
        context = ssl.create_default_context()
        # Framework Python on macOS may not have its optional OpenSSL CA bundle.
        # Use the OS-provided bundle while retaining certificate and hostname checks.
        system_bundle = Path("/etc/ssl/cert.pem")
        if sys.platform == "darwin" and ssl.get_default_verify_paths().cafile is None and system_bundle.is_file():
            context.load_verify_locations(cafile=str(system_bundle))
        self._opener = build_opener(_SameHostRedirect(), HTTPSHandler(context=context))

    def __repr__(self):
        return f"FirmsClient(timeout={self.timeout}, max_response_bytes={self.max_response_bytes}, retries={self.retries})"

    def _redacted(self, value):
        return value.replace(quote(self._api_key, safe=""), "<MAP_KEY>").replace(self._api_key, "<MAP_KEY>")

    def _read_limited(self, response, deadline):
        length_text = response.headers.get("Content-Length")
        if length_text:
            try:
                length = int(length_text)
            except (TypeError, ValueError):
                length = None
            if length is not None and length > self.max_response_bytes:
                raise ProtocolError("NASA response exceeds the configured size limit; request a smaller window.")
        body = bytearray()
        while True:
            if time.monotonic() >= deadline:
                raise TimeoutError()
            chunk = response.read(min(64 * 1024, self.max_response_bytes + 1 - len(body)))
            if not chunk:
                break
            body.extend(chunk)
            if len(body) > self.max_response_bytes:
                raise ProtocolError("NASA response exceeds the configured size limit; request a smaller window.")
        return bytes(body)

    @staticmethod
    def _retry_after(headers):
        if not headers:
            return None
        value = headers.get("Retry-After")
        if not value:
            return None
        try:
            return max(0.0, float(value))
        except (TypeError, ValueError):
            try:
                stamp = email.utils.parsedate_to_datetime(value)
                return max(0.0, stamp.timestamp() - time.time())
            except (TypeError, ValueError, OverflowError):
                return None

    def _get(self, path, *, accept="text/csv, text/plain;q=0.9"):
        url = _BASE + path
        for attempt in range(self.retries + 1):
            request = Request(url, headers={"Accept": accept, "User-Agent": "FireSync-DataPipeline/0.1"})
            try:
                deadline = time.monotonic() + self.timeout
                with self._opener.open(request, timeout=self.timeout) as response:
                    status = response.status
                    if not 200 <= status < 300:
                        raise NetworkError(f"NASA returned unexpected HTTP status {status}.")
                    body = self._read_limited(response, deadline)
                    return body, self._redacted(response.geturl())
            except HTTPError as error:
                status = error.code
                retry_after = self._retry_after(error.headers)
                error.close()
                if status == 429:
                    if attempt >= self.retries or (retry_after is not None and retry_after > 2):
                        raise QuotaError("NASA rate limit was reached; pause and check the MAP_KEY quota.") from None
                    time.sleep(retry_after if retry_after is not None else 0.5 * (2 ** attempt))
                    continue
                if 500 <= status < 600 and attempt < self.retries:
                    time.sleep(min(2.0, 0.5 * (2 ** attempt)))
                    continue
                raise NetworkError(f"NASA request failed with HTTP {status}; check the key, quota and request parameters.") from None
            except (URLError, TimeoutError, OSError, http.client.HTTPException):
                if attempt < self.retries:
                    time.sleep(min(2.0, 0.5 * (2 ** attempt)))
                    continue
                raise NetworkError("NASA request failed or timed out; check the connection and retry later.") from None
        raise NetworkError("NASA request could not be completed.")

    def availability(self) -> dict[str, Availability]:
        key = quote(self._api_key, safe="")
        body, _ = self._get(f"/api/data_availability/csv/{key}/ALL")
        return parse_availability(body)

    def quota_status(self) -> dict:
        key = quote(self._api_key, safe="")
        body, _ = self._get(f"/mapserver/mapkey_status/?MAP_KEY={key}", accept="application/json")
        try:
            payload = json.loads(body.decode("utf-8-sig"))
        except (ValueError, UnicodeDecodeError):
            raise ProtocolError("NASA did not return a valid JSON quota status; check the key and quota.") from None
        if not isinstance(payload, dict):
            raise ProtocolError("NASA quota status is not an object.")
        result = {}
        for field in ("transaction_limit", "current_transactions"):
            value = payload.get(field)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ProtocolError("NASA quota status has missing or invalid counters.")
            result[field] = value
        if result["transaction_limit"] == 0:
            raise ProtocolError("NASA quota status has an invalid transaction limit.")
        interval = payload.get("transaction_interval")
        if isinstance(interval, int) and not isinstance(interval, bool) and interval > 0:
            result["transaction_interval"] = interval
        elif isinstance(interval, str) and 0 < len(interval.strip()) <= 80:
            result["transaction_interval"] = self._redacted(interval.strip())
        else:
            raise ProtocolError("NASA quota status has a missing or invalid interval.")
        return result

    def fetch_area(self, scope: Scope, source_code: str, start: date, end: date) -> FetchPayload:
        if source_code not in PRODUCTS:
            raise ConfigurationError("Choose a supported FIRMS source code.")
        if not isinstance(scope, Scope):
            raise ConfigurationError("A validated Scope is required.")
        if type(start) is not date or type(end) is not date:
            raise ConfigurationError("API dates must be date values.")
        days = (end - start).days + 1
        if not 1 <= days <= 5:
            raise ConfigurationError("One NASA Area request must cover between one and five inclusive days.")
        key = quote(self._api_key, safe="")
        path = f"/api/area/csv/{key}/{source_code}/{scope.api_area}/{days}/{start.isoformat()}"
        body, url_redacted = self._get(path)
        validate_observation_header(body)
        return FetchPayload(body, source_code, scope.id, start, end, utc_now(), url_redacted)
