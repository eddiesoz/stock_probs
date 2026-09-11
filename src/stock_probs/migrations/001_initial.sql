-- M02 stores each submission separately while immutable forecast runs may serve exact repeats.
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);

CREATE TABLE forecast_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    asset_type TEXT NOT NULL CHECK (asset_type IN ('stock', 'etf')),
    content_fingerprint TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (symbol, asset_type, content_fingerprint)
);

CREATE TABLE search_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id TEXT NOT NULL UNIQUE,
    submitted_symbol TEXT NOT NULL,
    normalized_symbol TEXT,
    asset_type TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('successful', 'failed', 'repeated')),
    is_repeat INTEGER NOT NULL DEFAULT 0 CHECK (is_repeat IN (0, 1)),
    error_code TEXT,
    error_message TEXT,
    run_id INTEGER REFERENCES forecast_runs(id),
    submitted_at TEXT NOT NULL,
    completed_at TEXT NOT NULL,
    -- Failure and forecast references are mutually exclusive; repetition is orthogonal to failure.
    CHECK (
        (status = 'failed' AND run_id IS NULL AND error_code IS NOT NULL)
        OR
        (status IN ('successful', 'repeated') AND run_id IS NOT NULL AND error_code IS NULL)
    ),
    CHECK (status != 'repeated' OR is_repeat = 1)
);

CREATE INDEX idx_search_events_recent ON search_events(id DESC);
CREATE INDEX idx_search_events_symbol ON search_events(normalized_symbol, id DESC);
CREATE INDEX idx_search_events_status ON search_events(status, id DESC);
CREATE INDEX idx_search_events_asset ON search_events(asset_type, id DESC);

CREATE TABLE forecast_inputs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL UNIQUE REFERENCES forecast_runs(id),
    snapshot_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE forecast_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    input_id INTEGER NOT NULL REFERENCES forecast_inputs(id),
    horizon TEXT NOT NULL CHECK (horizon IN ('close_to_close', 'completed_5m_to_close')),
    result_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (input_id, horizon)
);

CREATE TABLE outcomes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    result_id INTEGER NOT NULL REFERENCES forecast_results(id),
    observed_close REAL,
    observed_return REAL,
    observed_at TEXT NOT NULL,
    comparison_rule TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('observed', 'unavailable', 'provisional', 'corrected')),
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    CHECK (observed_close IS NULL OR observed_close > 0),
    CHECK (
        (state = 'unavailable' AND observed_close IS NULL AND observed_return IS NULL)
        OR
        (state != 'unavailable' AND observed_close IS NOT NULL AND observed_return IS NOT NULL)
    )
);
CREATE INDEX idx_outcomes_result ON outcomes(result_id, id DESC);

-- These triggers turn accidental repository UPDATE/DELETE calls into hard failures.
CREATE TRIGGER immutable_forecast_runs_update BEFORE UPDATE ON forecast_runs BEGIN
    SELECT RAISE(ABORT, 'forecast_runs are immutable');
END;
CREATE TRIGGER immutable_forecast_runs_delete BEFORE DELETE ON forecast_runs BEGIN
    SELECT RAISE(ABORT, 'forecast_runs are immutable');
END;
CREATE TRIGGER immutable_search_events_update BEFORE UPDATE ON search_events BEGIN
    SELECT RAISE(ABORT, 'search_events are append-only');
END;
CREATE TRIGGER immutable_search_events_delete BEFORE DELETE ON search_events BEGIN
    SELECT RAISE(ABORT, 'search_events are append-only');
END;
CREATE TRIGGER immutable_forecast_inputs_update BEFORE UPDATE ON forecast_inputs BEGIN
    SELECT RAISE(ABORT, 'forecast_inputs are immutable');
END;
CREATE TRIGGER immutable_forecast_inputs_delete BEFORE DELETE ON forecast_inputs BEGIN
    SELECT RAISE(ABORT, 'forecast_inputs are immutable');
END;
CREATE TRIGGER immutable_forecast_results_update BEFORE UPDATE ON forecast_results BEGIN
    SELECT RAISE(ABORT, 'forecast_results are immutable');
END;
CREATE TRIGGER immutable_forecast_results_delete BEFORE DELETE ON forecast_results BEGIN
    SELECT RAISE(ABORT, 'forecast_results are immutable');
END;
CREATE TRIGGER append_only_outcomes_update BEFORE UPDATE ON outcomes BEGIN
    SELECT RAISE(ABORT, 'outcomes are append-only');
END;
CREATE TRIGGER append_only_outcomes_delete BEFORE DELETE ON outcomes BEGIN
    SELECT RAISE(ABORT, 'outcomes are append-only');
END;
