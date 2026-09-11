-- M02 closes REPLACE and reconstruction-provenance gaps without rewriting prior migrations.
ALTER TABLE search_events
    ADD COLUMN requested_source_event_id INTEGER;

-- A requested source is audit context; source_event_id is an FK only when that source is a
-- real successful event. Failed unknown-source attempts therefore remain appendable and honest.
CREATE TRIGGER validate_search_event_analysis_contract_insert BEFORE INSERT ON search_events
WHEN
    (
        NEW.analysis_kind = 'submitted_forecast'
        AND (
            NEW.source_event_id IS NOT NULL
            OR NEW.requested_source_event_id IS NOT NULL
            OR NEW.requested_cutoff IS NOT NULL
        )
    )
    OR (
        NEW.analysis_kind = 'fresh_historical_reconstruction'
        AND (
            typeof(NEW.requested_source_event_id) != 'integer'
            OR NEW.requested_source_event_id < 1
            OR NEW.requested_cutoff IS NULL
            OR length(NEW.requested_cutoff) = 0
            OR (
                EXISTS (
                    SELECT 1 FROM search_events AS requested_source
                    WHERE requested_source.id = NEW.requested_source_event_id
                      AND requested_source.run_id IS NOT NULL
                )
                AND NEW.source_event_id IS NOT NEW.requested_source_event_id
            )
            OR (
                NOT EXISTS (
                    SELECT 1 FROM search_events AS requested_source
                    WHERE requested_source.id = NEW.requested_source_event_id
                      AND requested_source.run_id IS NOT NULL
                )
                AND NEW.source_event_id IS NOT NULL
            )
            OR (
                NEW.status != 'failed'
                AND NEW.source_event_id IS NULL
            )
        )
    )
BEGIN
    SELECT RAISE(ABORT, 'invalid search event analysis contract');
END;

-- SQLite suppresses the DELETE half of REPLACE when recursive_triggers is OFF. Rejecting every
-- existing primary or natural key in BEFORE INSERT makes immutability connection-independent.
CREATE TRIGGER immutable_forecast_runs_insert_conflict BEFORE INSERT ON forecast_runs
WHEN
    (NEW.id > 0 AND EXISTS (SELECT 1 FROM forecast_runs WHERE id = NEW.id))
    OR EXISTS (
        SELECT 1 FROM forecast_runs
        WHERE symbol = NEW.symbol
          AND asset_type = NEW.asset_type
          AND content_fingerprint = NEW.content_fingerprint
    )
BEGIN
    SELECT RAISE(ABORT, 'forecast_runs are immutable');
END;

CREATE TRIGGER immutable_search_events_insert_conflict BEFORE INSERT ON search_events
WHEN
    (NEW.id > 0 AND EXISTS (SELECT 1 FROM search_events WHERE id = NEW.id))
    OR EXISTS (SELECT 1 FROM search_events WHERE request_id = NEW.request_id)
BEGIN
    SELECT RAISE(ABORT, 'search_events are append-only');
END;

CREATE TRIGGER immutable_forecast_inputs_insert_conflict BEFORE INSERT ON forecast_inputs
WHEN
    (NEW.id > 0 AND EXISTS (SELECT 1 FROM forecast_inputs WHERE id = NEW.id))
    OR EXISTS (SELECT 1 FROM forecast_inputs WHERE run_id = NEW.run_id)
BEGIN
    SELECT RAISE(ABORT, 'forecast_inputs are immutable');
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

CREATE TRIGGER append_only_outcomes_insert_conflict BEFORE INSERT ON outcomes
WHEN NEW.id > 0 AND EXISTS (SELECT 1 FROM outcomes WHERE id = NEW.id)
BEGIN
    SELECT RAISE(ABORT, 'outcomes are append-only');
END;

CREATE TRIGGER immutable_schema_migrations_insert_conflict BEFORE INSERT ON schema_migrations
WHEN EXISTS (SELECT 1 FROM schema_migrations WHERE version = NEW.version)
BEGIN
    SELECT RAISE(ABORT, 'schema_migrations are append-only');
END;
