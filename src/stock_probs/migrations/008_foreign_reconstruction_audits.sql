-- M08 lets an inaccessible successful source remain audit context without creating a
-- cross-owner foreign-key edge.  The service already scopes the source lookup by owner;
-- this trigger keeps that distinction durable for failed reconstruction attempts.
DROP TRIGGER validate_search_event_analysis_contract_insert;

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
                AND NEW.source_event_id IS NOT NULL
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
