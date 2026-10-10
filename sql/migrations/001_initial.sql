-- Immutable snapshot-scoped metadata; values are never joined to a newer definition.
CREATE TABLE IF NOT EXISTS snapshots (
    snapshot_id TEXT PRIMARY KEY,
    manifest_schema_version INTEGER NOT NULL CHECK (manifest_schema_version > 0),
    state TEXT NOT NULL CHECK (state IN ('partial', 'complete')),
    active BOOLEAN NOT NULL DEFAULT FALSE,
    manifest JSONB NOT NULL,
    content_sha256 TEXT NOT NULL,
    imported_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (NOT active OR state = 'complete')
);
CREATE UNIQUE INDEX IF NOT EXISTS one_active_snapshot ON snapshots (active) WHERE active;

CREATE TABLE IF NOT EXISTS ingestion_runs (
    run_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    snapshot_id TEXT NOT NULL REFERENCES snapshots(snapshot_id),
    state TEXT NOT NULL CHECK (state IN ('partial', 'complete')),
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    metadata JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS units (
    unit_id TEXT PRIMARY KEY CHECK (unit_id ~ '^[0-9]{12}$')
);
CREATE TABLE IF NOT EXISTS unit_versions (
    snapshot_id TEXT NOT NULL REFERENCES snapshots(snapshot_id),
    unit_id TEXT NOT NULL REFERENCES units(unit_id),
    name TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('1', '2', '3')),
    parent_id TEXT,
    powiat TEXT,
    valid_from INTEGER,
    valid_to INTEGER,
    teryt TEXT CHECK (teryt IS NULL OR teryt ~ '^[0-9]{7}$'),
    metadata JSONB NOT NULL,
    PRIMARY KEY (snapshot_id, unit_id),
    CHECK (valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from)
);

CREATE TABLE IF NOT EXISTS indicator_definitions (
    snapshot_id TEXT NOT NULL REFERENCES snapshots(snapshot_id),
    indicator_id TEXT NOT NULL,
    definition_version TEXT NOT NULL,
    metadata JSONB NOT NULL,
    PRIMARY KEY (snapshot_id, indicator_id)
);

CREATE TABLE IF NOT EXISTS attribute_definitions (
    snapshot_id TEXT NOT NULL REFERENCES snapshots(snapshot_id),
    attr_id TEXT NOT NULL,
    metadata JSONB NOT NULL,
    PRIMARY KEY (snapshot_id, attr_id)
);

CREATE TABLE IF NOT EXISTS observations (
    snapshot_id TEXT NOT NULL,
    unit_id TEXT NOT NULL,
    year INTEGER NOT NULL CHECK (year BETWEEN 1900 AND 2200),
    indicator_id TEXT NOT NULL,
    raw_value TEXT,
    raw_attr_id TEXT,
    semantic_value DOUBLE PRECISION,
    quality_status TEXT NOT NULL CHECK (quality_status IN
        ('valid','true_zero','preliminary','missing','unavailable','below_precision',
         'incomplete','definition_mismatch','comparability_break','low_precision','unknown_attribute')),
    reason_code TEXT NOT NULL,
    source_file TEXT NOT NULL,
    source_record TEXT NOT NULL,
    PRIMARY KEY (snapshot_id, unit_id, year, indicator_id),
    FOREIGN KEY (snapshot_id, unit_id) REFERENCES unit_versions(snapshot_id, unit_id),
    FOREIGN KEY (snapshot_id, indicator_id)
        REFERENCES indicator_definitions(snapshot_id, indicator_id),
    FOREIGN KEY (snapshot_id, raw_attr_id)
        REFERENCES attribute_definitions(snapshot_id, attr_id),
    CHECK (semantic_value IS NULL OR
        (semantic_value >= 0 AND semantic_value < 'Infinity'::DOUBLE PRECISION))
);
CREATE INDEX IF NOT EXISTS observations_comparison
    ON observations(snapshot_id, year, indicator_id, unit_id);
CREATE INDEX IF NOT EXISTS observations_trends
    ON observations(snapshot_id, unit_id, indicator_id, year);
