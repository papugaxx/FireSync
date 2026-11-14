CREATE TABLE IF NOT EXISTS products (
    source_code TEXT PRIMARY KEY,
    sensor TEXT NOT NULL CHECK (sensor IN ('MODIS', 'VIIRS')),
    family TEXT NOT NULL,
    processing TEXT NOT NULL CHECK (processing IN ('SP', 'NRT')),
    priority INTEGER NOT NULL,
    expected_platform TEXT
);

CREATE TABLE IF NOT EXISTS scopes (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    west REAL NOT NULL CHECK (west >= -180),
    south REAL NOT NULL CHECK (south >= -90),
    east REAL NOT NULL CHECK (east <= 180),
    north REAL NOT NULL CHECK (north <= 90),
    created_at TEXT NOT NULL,
    CHECK (west < east AND south < north),
    UNIQUE (west, south, east, north)
);

CREATE TABLE IF NOT EXISTS availability (
    source_code TEXT PRIMARY KEY REFERENCES products(source_code),
    min_date TEXT NOT NULL,
    max_date TEXT NOT NULL,
    checked_at TEXT NOT NULL,
    CHECK (min_date <= max_date)
);

CREATE TABLE IF NOT EXISTS fetch_windows (
    id INTEGER PRIMARY KEY,
    scope_id TEXT NOT NULL REFERENCES scopes(id),
    source_code TEXT NOT NULL REFERENCES products(source_code),
    day TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'loaded', 'failed')),
    row_count INTEGER NOT NULL DEFAULT 0 CHECK (row_count >= 0),
    checksum TEXT,
    fetched_at TEXT,
    last_attempt_at TEXT,
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    last_error TEXT,
    request_url_redacted TEXT,
    UNIQUE (scope_id, source_code, day),
    CHECK (status != 'loaded' OR (checksum IS NOT NULL AND fetched_at IS NOT NULL))
);

CREATE INDEX IF NOT EXISTS fetch_windows_scope_day
    ON fetch_windows(scope_id, day, status);

CREATE TABLE IF NOT EXISTS detections (
    id INTEGER PRIMARY KEY,
    window_id INTEGER NOT NULL REFERENCES fetch_windows(id) ON DELETE CASCADE,
    observed_at TEXT NOT NULL,
    sensor TEXT NOT NULL CHECK (sensor IN ('MODIS', 'VIIRS')),
    satellite TEXT NOT NULL,
    latitude REAL NOT NULL CHECK (latitude BETWEEN -90 AND 90),
    longitude REAL NOT NULL CHECK (longitude BETWEEN -180 AND 180),
    brightness_k REAL CHECK (brightness_k >= 0),
    frp_mw REAL CHECK (frp_mw >= 0),
    confidence_raw TEXT,
    daynight TEXT CHECK (daynight IN ('D', 'N') OR daynight IS NULL),
    product_version TEXT NOT NULL,
    processing TEXT NOT NULL CHECK (processing IN ('SP', 'NRT', 'RT', 'URT')),
    scan_km REAL CHECK (scan_km >= 0),
    track_km REAL CHECK (track_km >= 0),
    type_code INTEGER,
    raw_json TEXT NOT NULL,
    record_hash TEXT NOT NULL,
    UNIQUE (window_id, record_hash)
);

CREATE INDEX IF NOT EXISTS detections_time ON detections(observed_at);

CREATE TABLE IF NOT EXISTS sync_jobs (
    id TEXT PRIMARY KEY,
    scope_id TEXT NOT NULL REFERENCES scopes(id),
    sources_json TEXT NOT NULL,
    start TEXT NOT NULL,
    end TEXT NOT NULL,
    total_units INTEGER NOT NULL CHECK (total_units >= 0),
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'running', 'completed', 'paused', 'failed')),
    completed_units INTEGER NOT NULL DEFAULT 0 CHECK (completed_units >= 0),
    skipped_units INTEGER NOT NULL DEFAULT 0 CHECK (skipped_units >= 0),
    failed_units INTEGER NOT NULL DEFAULT 0 CHECK (failed_units >= 0),
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK (start <= end)
);

CREATE INDEX IF NOT EXISTS sync_jobs_created ON sync_jobs(created_at DESC);
