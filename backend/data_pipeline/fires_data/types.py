from dataclasses import dataclass
from datetime import date, datetime, timezone
from hashlib import sha256
import json
import math
import re
from typing import Mapping


@dataclass(frozen=True)
class Product:
    code: str
    sensor: str
    family: str
    processing: str
    priority: int
    expected_platform: str | None


PRODUCTS = {}
for family, sensor, platform in (
    ("MODIS", "MODIS", None),
    ("VIIRS_SNPP", "VIIRS", "S-NPP"),
    ("VIIRS_NOAA20", "VIIRS", "NOAA-20"),
    ("VIIRS_NOAA21", "VIIRS", "NOAA-21"),
):
    for processing, priority in (("SP", 2), ("NRT", 1)):
        code = f"{family}_{processing}"
        PRODUCTS[code] = Product(code, sensor, family, processing, priority, platform)


def utc_now():
    return datetime.now(timezone.utc)


def utc_text(value: datetime):
    if value.tzinfo is None:
        raise ValueError("UTC timestamps must be timezone aware.")
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


@dataclass(frozen=True)
class Scope:
    id: str
    name: str
    west: float
    south: float
    east: float
    north: float

    def __post_init__(self):
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", self.id):
            raise ValueError("Scope id must contain 1-80 ASCII letters, digits, _ or -.")
        if not self.name.strip():
            raise ValueError("Scope name cannot be empty.")
        if not all(math.isfinite(v) for v in self.bbox):
            raise ValueError("Bounding-box coordinates must be finite.")
        if not (-180 <= self.west < self.east <= 180 and -90 <= self.south < self.north <= 90):
            raise ValueError("Use west,south,east,north with west<east and south<north.")

    @property
    def bbox(self):
        return (self.west, self.south, self.east, self.north)

    @property
    def api_area(self):
        if self.bbox == (-180, -90, 180, 90):
            return "world"
        return ",".join(format(v, ".12g") for v in self.bbox)

    @classmethod
    def world(cls):
        return cls("world", "World", -180, -90, 180, 90)

    @classmethod
    def from_bbox(cls, bbox, scope_id=None, name=None):
        values = tuple(float(v) for v in bbox)
        if len(values) != 4:
            raise ValueError("A bounding box needs four coordinates.")
        if values == (-180, -90, 180, 90) and scope_id is None:
            return cls.world()
        digest = sha256(json.dumps(values).encode()).hexdigest()[:16]
        return cls(scope_id or f"bbox-{digest}", name or "Selected area", *values)


@dataclass(frozen=True)
class Availability:
    source_code: str
    min_date: date
    max_date: date

    def __post_init__(self):
        if self.source_code not in PRODUCTS:
            raise ValueError("Unsupported source code.")
        if self.max_date < self.min_date:
            raise ValueError("Availability end precedes its start.")


@dataclass(frozen=True)
class Observation:
    observed_at: datetime
    sensor: str
    satellite: str
    latitude: float
    longitude: float
    brightness_k: float | None
    frp_mw: float | None
    confidence_raw: str | None
    daynight: str | None
    product_version: str
    processing: str
    scan_km: float | None
    track_km: float | None
    type_code: int | None
    raw: Mapping[str, str]
    record_hash: str

    @property
    def day(self):
        return self.observed_at.astimezone(timezone.utc).date()


@dataclass(frozen=True)
class FetchPayload:
    body: bytes
    source_code: str
    scope_id: str
    start: date
    end: date
    fetched_at: datetime
    url_redacted: str

    @property
    def checksum(self):
        return sha256(self.body).hexdigest()


@dataclass(frozen=True)
class FetchTask:
    source_code: str
    day: date
