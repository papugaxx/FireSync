"""Validated parsing of NASA FIRMS CSV responses without framework dependencies."""

import csv
from collections.abc import Iterator
from datetime import date, datetime, time, timezone
from hashlib import sha256
import io
import json
import math
import re

from .errors import ProtocolError
from .types import Availability, Observation, PRODUCTS, Scope


_OBSERVATION_COLUMNS = {
    "latitude", "longitude", "acq_date", "acq_time", "satellite", "confidence", "version",
}
_AVAILABILITY_COLUMNS = {"data_id", "min_date", "max_date"}
_DATE_PATTERN = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}\Z")
_VERSION_PATTERN = re.compile(r"[0-9]+(?:\.[0-9]+)*(?:URT|NRT|RT)?\Z")


def _reader(body: bytes, required: set[str]):
    if not isinstance(body, bytes) or not body.strip():
        raise ProtocolError("NASA returned an empty response instead of CSV.")
    try:
        text = body.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ProtocolError("NASA response is not valid UTF-8 CSV.") from None
    if not text.strip() or text.lstrip().startswith(("<", "{", "[")):
        raise ProtocolError("NASA returned a non-CSV response; no data was accepted.")
    reader = csv.DictReader(io.StringIO(text, newline=""), strict=True)
    try:
        headers = reader.fieldnames
    except csv.Error:
        raise ProtocolError("NASA CSV header is malformed.") from None
    if not headers:
        raise ProtocolError("NASA response has no CSV header.")
    headers = [header.strip().lower() for header in headers]
    if any(not header for header in headers) or len(headers) != len(set(headers)):
        raise ProtocolError("NASA CSV has duplicate or empty column names.")
    missing = required - set(headers)
    if missing:
        raise ProtocolError("NASA CSV is missing required columns: " + ", ".join(sorted(missing)))
    reader.fieldnames = headers
    return reader


def _rows(reader):
    try:
        for row in reader:
            if None in row or any(value is None for value in row.values()):
                raise ProtocolError(f"CSV line {reader.line_num} has an incorrect number of values.")
            yield reader.line_num, row
    except csv.Error:
        raise ProtocolError(f"CSV parsing failed near line {reader.line_num}.") from None


def validate_observation_header(body: bytes):
    """Reject error pages immediately, leaving row validation to the iterator."""
    _reader(body, _OBSERVATION_COLUMNS)


def _date(value: str, field: str):
    value = value.strip()
    if not _DATE_PATTERN.fullmatch(value):
        raise ValueError(f"{field} must use YYYY-MM-DD")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ValueError(f"{field} is not a valid calendar date") from None


def parse_availability(body: bytes) -> dict[str, Availability]:
    reader = _reader(body, _AVAILABILITY_COLUMNS)
    result = {}
    for line, row in _rows(reader):
        code = row["data_id"].strip().upper()
        if code not in PRODUCTS:
            continue
        first, last = row["min_date"].strip(), row["max_date"].strip()
        if not first and not last:
            continue
        try:
            item = Availability(code, _date(first, "min_date"), _date(last, "max_date"))
        except ValueError:
            raise ProtocolError(f"Availability CSV line {line} has an invalid date interval.") from None
        if code in result and result[code] != item:
            raise ProtocolError(f"Availability CSV contains conflicting intervals for {code}.")
        result[code] = item
    return result


def _number(raw: str, field: str, *, optional=False, minimum=None, maximum=None):
    text = raw.strip()
    if not text and optional:
        return None
    try:
        value = float(text)
    except (TypeError, ValueError):
        raise ValueError(f"{field} must be numeric") from None
    if not math.isfinite(value):
        raise ValueError(f"{field} must be finite")
    if minimum is not None and value < minimum:
        raise ValueError(f"{field} is below its allowed minimum")
    if maximum is not None and value > maximum:
        raise ValueError(f"{field} is above its allowed maximum")
    return value


def _satellite(raw: str, sensor: str):
    value = raw.strip().upper().replace("_", "-")
    if sensor == "MODIS":
        aliases = {"T": "Terra", "TERRA": "Terra", "A": "Aqua", "AQUA": "Aqua"}
    else:
        aliases = {
            "N": "S-NPP", "SNPP": "S-NPP", "S-NPP": "S-NPP",
            "SUOMI NPP": "S-NPP", "SUOMI-NPP": "S-NPP",
            "N20": "NOAA-20", "NOAA20": "NOAA-20", "NOAA-20": "NOAA-20",
            "J1": "NOAA-20", "JPSS-1": "NOAA-20", "1": "NOAA-20",
            "N21": "NOAA-21", "NOAA21": "NOAA-21", "NOAA-21": "NOAA-21",
            "J2": "NOAA-21", "JPSS-2": "NOAA-21", "2": "NOAA-21",
        }
    if value not in aliases:
        raise ValueError("satellite is not a recognized platform for this sensor")
    return aliases[value]


def _processing(version: str):
    upper = version.upper()
    if not _VERSION_PATTERN.fullmatch(upper):
        raise ValueError("version has an unsupported format")
    # NRT and URT also end with RT, so these checks must be ordered.
    for suffix in ("URT", "NRT", "RT"):
        if upper.endswith(suffix):
            return suffix
    return "SP"


def parse_observations(body: bytes, source_code: str, scope: Scope, start: date, end: date) -> Iterator[Observation]:
    """Yield valid rows; any invalid or out-of-request row fails the whole batch.

    The caller must consume this iterator inside an atomic replacement so a late
    malformed line cannot leave a partially accepted snapshot in the database.
    """
    if source_code not in PRODUCTS:
        raise ProtocolError("Unsupported NASA source code.")
    if type(start) is not date or type(end) is not date or end < start:
        raise ProtocolError("Invalid requested date interval.")
    product = PRODUCTS[source_code]
    reader = _reader(body, _OBSERVATION_COLUMNS)
    for line, row in _rows(reader):
        try:
            latitude = _number(row["latitude"], "latitude", minimum=-90, maximum=90)
            longitude = _number(row["longitude"], "longitude", minimum=-180, maximum=180)
            if not (scope.south <= latitude <= scope.north and scope.west <= longitude <= scope.east):
                raise ValueError("coordinates are outside the requested bounding box")

            observed_date = _date(row["acq_date"], "acq_date")
            if not start <= observed_date <= end:
                raise ValueError("acq_date is outside the requested interval")
            hhmm = row["acq_time"].strip()
            if not re.fullmatch(r"[0-9]{1,4}", hhmm):
                raise ValueError("acq_time must contain one to four HHMM digits")
            hhmm = hhmm.zfill(4)
            try:
                clock = time(int(hhmm[:2]), int(hhmm[2:]))
            except ValueError:
                raise ValueError("acq_time is not a valid UTC time") from None
            observed_at = datetime.combine(observed_date, clock, tzinfo=timezone.utc)

            instrument = row.get("instrument", "").strip().upper()
            if instrument and instrument != product.sensor:
                raise ValueError("instrument does not match the requested source")
            satellite = _satellite(row["satellite"], product.sensor)
            if product.expected_platform and satellite != product.expected_platform:
                raise ValueError("satellite does not match the requested source")

            version = row["version"].strip()
            processing = _processing(version)
            if product.processing == "SP" and processing != "SP":
                raise ValueError("an operational version was returned for an SP source")
            if product.processing == "NRT" and processing == "SP":
                raise ValueError("a standard version was returned for an NRT source")

            confidence = row["confidence"].strip() or None
            if confidence is not None:
                if product.sensor == "MODIS":
                    _number(confidence, "confidence", minimum=0, maximum=100)
                elif confidence.lower() not in {"l", "n", "h", "low", "nominal", "high"}:
                    raise ValueError("confidence is not a recognized VIIRS category")
            daynight = row.get("daynight", "").strip().upper() or None
            if daynight not in (None, "D", "N"):
                raise ValueError("daynight must be D, N or empty")

            brightness_name = "brightness" if product.sensor == "MODIS" else "bright_ti4"
            brightness = _number(row.get(brightness_name, ""), brightness_name, optional=True, minimum=0)
            frp = _number(row.get("frp", ""), "frp", optional=True, minimum=0)
            scan = _number(row.get("scan", ""), "scan", optional=True, minimum=0)
            track = _number(row.get("track", ""), "track", optional=True, minimum=0)
            type_text = row.get("type", "").strip()
            if type_text:
                try:
                    type_code = int(type_text)
                except ValueError:
                    raise ValueError("type must be an integer or empty") from None
                if type_code not in (0, 1, 2, 3):
                    raise ValueError("type has an unsupported classification")
            else:
                type_code = None
        except (ValueError, TypeError, KeyError) as error:
            # The validated field messages never include raw values or URLs.
            message = str(error) if isinstance(error, ValueError) else "invalid field value"
            raise ProtocolError(f"Observation CSV line {line}: {message}.") from None

        record_hash = sha256(json.dumps(row, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()
        yield Observation(
            observed_at=observed_at, sensor=product.sensor, satellite=satellite,
            latitude=latitude, longitude=longitude, brightness_k=brightness,
            frp_mw=frp, confidence_raw=confidence, daynight=daynight,
            product_version=version, processing=processing, scan_km=scan,
            track_km=track, type_code=type_code, raw=dict(row), record_hash=record_hash,
        )
