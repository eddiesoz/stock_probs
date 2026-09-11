-- M02 adds an explicit audit identity for fresh historical-cutoff analyses without
-- rewriting the shipped initial schema or changing any previously recorded row.
ALTER TABLE search_events
    ADD COLUMN analysis_kind TEXT NOT NULL DEFAULT 'submitted_forecast';
ALTER TABLE search_events
    ADD COLUMN source_event_id INTEGER REFERENCES search_events(id);
ALTER TABLE search_events
    ADD COLUMN requested_cutoff TEXT;

CREATE INDEX idx_search_events_analysis
    ON search_events(analysis_kind, id DESC);
CREATE INDEX idx_search_events_source
    ON search_events(source_event_id, id DESC);

-- ALTER TABLE cannot add a table CHECK in supported SQLite versions. This insert
-- trigger gives upgraded and clean databases the same cross-column guarantees.
CREATE TRIGGER validate_search_event_analysis_insert BEFORE INSERT ON search_events
WHEN
    NEW.analysis_kind NOT IN ('submitted_forecast', 'fresh_historical_reconstruction')
    OR (
        NEW.analysis_kind = 'submitted_forecast'
        AND (NEW.source_event_id IS NOT NULL OR NEW.requested_cutoff IS NOT NULL)
    )
    OR (
        NEW.analysis_kind = 'fresh_historical_reconstruction'
        AND NEW.status != 'failed'
        AND NEW.requested_cutoff IS NULL
    )
    OR (
        NEW.analysis_kind = 'fresh_historical_reconstruction'
        AND NEW.status != 'failed'
        AND (
            NEW.source_event_id IS NULL
            OR NOT EXISTS (
                SELECT 1 FROM search_events AS source
                WHERE source.id = NEW.source_event_id AND source.run_id IS NOT NULL
            )
        )
    )
BEGIN
    SELECT RAISE(ABORT, 'invalid search event analysis provenance');
END;

-- Migration receipts are operational evidence and must not be rewritten to make a
-- changed or partially applied schema appear current. Future upgrades only append.
CREATE TRIGGER immutable_schema_migrations_update BEFORE UPDATE ON schema_migrations BEGIN
    SELECT RAISE(ABORT, 'schema_migrations are append-only');
END;
CREATE TRIGGER immutable_schema_migrations_delete BEFORE DELETE ON schema_migrations BEGIN
    SELECT RAISE(ABORT, 'schema_migrations are append-only');
END;
