-- 006 widens the forecast horizon set without changing any recorded value or identifier.
-- SQLite cannot drop a CHECK constraint, so both the parent and its outcome child are copied
-- inside the migration transaction before their immutability guards are restored.
CREATE TABLE forecast_results_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    input_id INTEGER NOT NULL REFERENCES forecast_inputs(id),
    horizon TEXT NOT NULL CHECK (horizon IN ('close_to_close', 'completed_5m_to_close', 'five_min_forward', 'daily_1', 'weekly_5', 'monthly_21', 'quarterly_63')),
    result_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (input_id, horizon)
);
CREATE TABLE outcomes_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    result_id INTEGER NOT NULL REFERENCES forecast_results_new(id),
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
INSERT INTO forecast_results_new (id, input_id, horizon, result_json, created_at)
    SELECT id, input_id, horizon, result_json, created_at FROM forecast_results;
INSERT INTO outcomes_new
    (id, result_id, observed_close, observed_return, observed_at, comparison_rule, state, note,
     created_at)
    SELECT id, result_id, observed_close, observed_return, observed_at, comparison_rule, state,
           note, created_at
    FROM outcomes;

DROP TRIGGER append_only_outcomes_update;
DROP TRIGGER append_only_outcomes_delete;
DROP TRIGGER append_only_outcomes_insert_conflict;
DROP TRIGGER immutable_forecast_results_update;
DROP TRIGGER immutable_forecast_results_delete;
DROP TRIGGER immutable_forecast_results_insert_conflict;
DROP TABLE outcomes;
DROP TABLE forecast_results;
ALTER TABLE forecast_results_new RENAME TO forecast_results;
ALTER TABLE outcomes_new RENAME TO outcomes;
CREATE INDEX idx_outcomes_result ON outcomes(result_id, id DESC);

CREATE TRIGGER immutable_forecast_results_update BEFORE UPDATE ON forecast_results BEGIN
    SELECT RAISE(ABORT, 'forecast_results are immutable');
END;
CREATE TRIGGER immutable_forecast_results_delete BEFORE DELETE ON forecast_results BEGIN
    SELECT RAISE(ABORT, 'forecast_results are immutable');
END;
CREATE TRIGGER immutable_forecast_results_insert_conflict BEFORE INSERT ON forecast_results
WHEN
    (NEW.id > 0 AND EXISTS (SELECT 1 FROM forecast_results WHERE id = NEW.id))
    OR EXISTS (
        SELECT 1 FROM forecast_results
        WHERE input_id = NEW.input_id AND horizon = NEW.horizon
    )
BEGIN
    SELECT RAISE(ABORT, 'forecast_results are immutable');
END;
CREATE TRIGGER append_only_outcomes_update BEFORE UPDATE ON outcomes BEGIN
    SELECT RAISE(ABORT, 'outcomes are append-only');
END;
CREATE TRIGGER append_only_outcomes_delete BEFORE DELETE ON outcomes BEGIN
    SELECT RAISE(ABORT, 'outcomes are append-only');
END;
CREATE TRIGGER append_only_outcomes_insert_conflict BEFORE INSERT ON outcomes
WHEN NEW.id > 0 AND EXISTS (SELECT 1 FROM outcomes WHERE id = NEW.id)
BEGIN
    SELECT RAISE(ABORT, 'outcomes are append-only');
END;
