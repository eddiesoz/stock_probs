-- M04 adds a compact immutable search projection so dashboard filters never parse every
-- forecast snapshot or issue one detail query per event. Existing audit rows are not rewritten.
CREATE TABLE history_facets (
    event_id INTEGER PRIMARY KEY REFERENCES search_events(id),
    canonical_symbol TEXT,
    display_name TEXT,
    company_name TEXT,
    exchange TEXT,
    quote_type TEXT,
    model_name TEXT,
    model_version TEXT,
    forecast_contract_version TEXT,
    submitted_at_us INTEGER NOT NULL
);

-- SQLite's %f truncates to milliseconds. Isolate and right-pad the original ISO fraction instead,
-- while %s normalizes Z and standard numeric offsets to the corresponding whole UTC second.
WITH legacy_events AS (
    SELECT
        event.*,
        CASE
            WHEN instr(event.submitted_at, '.') = 0 THEN ''
            WHEN substr(event.submitted_at, -1) = 'Z' THEN
                substr(
                    event.submitted_at,
                    instr(event.submitted_at, '.') + 1,
                    length(event.submitted_at) - instr(event.submitted_at, '.') - 1
                )
            WHEN substr(event.submitted_at, -6, 1) IN ('+', '-') THEN
                substr(
                    event.submitted_at,
                    instr(event.submitted_at, '.') + 1,
                    length(event.submitted_at) - instr(event.submitted_at, '.') - 6
                )
            ELSE substr(event.submitted_at, instr(event.submitted_at, '.') + 1)
        END AS fractional_digits
    FROM search_events AS event
)
INSERT INTO history_facets (
    event_id, canonical_symbol, display_name, company_name, exchange, quote_type,
    model_name, model_version, forecast_contract_version, submitted_at_us
)
SELECT
    event.id,
    COALESCE(json_extract(input.snapshot_json, '$.canonical_symbol'), event.normalized_symbol),
    json_extract(input.snapshot_json, '$.display_name'),
    json_extract(input.snapshot_json, '$.company_name'),
    json_extract(input.snapshot_json, '$.exchange'),
    json_extract(input.snapshot_json, '$.quote_type'),
    json_extract(input.snapshot_json, '$.model.name'),
    json_extract(input.snapshot_json, '$.model.version'),
    json_extract(input.snapshot_json, '$.forecast_contract_version'),
    CAST(strftime('%s', event.submitted_at) AS INTEGER) * 1000000
        + CAST(substr(event.fractional_digits || '000000', 1, 6) AS INTEGER)
FROM legacy_events AS event
LEFT JOIN forecast_inputs AS input ON input.run_id = event.run_id;

-- Measurements at 100,000 audit events showed date/model/company filtering otherwise scans the
-- projection. These indexes retain event_id as a deterministic newest-first tie-break key.
CREATE INDEX idx_history_facets_submitted
    ON history_facets(submitted_at_us DESC, event_id DESC);
CREATE INDEX idx_history_facets_company
    ON history_facets(company_name COLLATE NOCASE, event_id DESC);
CREATE INDEX idx_history_facets_model
    ON history_facets(model_name COLLATE NOCASE, model_version COLLATE NOCASE, event_id DESC);

CREATE TRIGGER immutable_history_facets_update BEFORE UPDATE ON history_facets BEGIN
    SELECT RAISE(ABORT, 'history facets are immutable');
END;
CREATE TRIGGER immutable_history_facets_delete BEFORE DELETE ON history_facets BEGIN
    SELECT RAISE(ABORT, 'history facets are append-only');
END;
CREATE TRIGGER immutable_history_facets_insert_conflict BEFORE INSERT ON history_facets
WHEN EXISTS (SELECT 1 FROM history_facets WHERE event_id = NEW.event_id)
BEGIN
    SELECT RAISE(ABORT, 'history facets are append-only');
END;
