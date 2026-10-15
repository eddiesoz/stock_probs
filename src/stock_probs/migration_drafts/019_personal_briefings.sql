-- Draft-only R4 persistence. Do not add this file to packaged migrations until its
-- backup/restore, export, and migration-registry integration have independent review.
CREATE TABLE briefing_preferences (
    owner_user_id INTEGER NOT NULL REFERENCES users(id),
    revision INTEGER NOT NULL CHECK(revision > 0),
    threshold_bps INTEGER NOT NULL CHECK(threshold_bps BETWEEN 50 AND 1000),
    updated_at TEXT NOT NULL CHECK(length(updated_at) BETWEEN 20 AND 40),
    PRIMARY KEY(owner_user_id, revision)
);
CREATE TRIGGER briefing_preferences_no_update BEFORE UPDATE ON briefing_preferences
BEGIN SELECT RAISE(ABORT, 'briefing preferences are append-only'); END;
CREATE TRIGGER briefing_preferences_no_delete BEFORE DELETE ON briefing_preferences
BEGIN SELECT RAISE(ABORT, 'briefing preferences are append-only'); END;
CREATE TRIGGER briefing_preferences_no_replace BEFORE INSERT ON briefing_preferences
WHEN EXISTS(SELECT 1 FROM briefing_preferences
           WHERE owner_user_id=NEW.owner_user_id AND revision=NEW.revision)
BEGIN SELECT RAISE(ABORT, 'briefing preferences are append-only'); END;

CREATE TABLE briefing_price_observations (
    owner_user_id INTEGER NOT NULL REFERENCES users(id),
    source_ref TEXT NOT NULL CHECK(length(source_ref) BETWEEN 1 AND 128),
    payload_sha256 TEXT NOT NULL
        CHECK(length(payload_sha256)=64 AND payload_sha256 NOT GLOB '*[^0-9a-f]*'),
    symbol TEXT NOT NULL CHECK(length(symbol) BETWEEN 1 AND 20),
    asset_type TEXT NOT NULL CHECK(length(asset_type) BETWEEN 1 AND 32),
    provider TEXT CHECK(provider IS NULL OR length(provider) BETWEEN 1 AND 80),
    currency TEXT CHECK(currency IS NULL OR currency GLOB '[A-Z][A-Z][A-Z]'),
    price_text TEXT CHECK(price_text IS NULL OR length(price_text) BETWEEN 1 AND 64),
    observed_at TEXT CHECK(observed_at IS NULL OR length(observed_at) BETWEEN 20 AND 40),
    received_at TEXT CHECK(received_at IS NULL OR length(received_at) BETWEEN 20 AND 40),
    state TEXT NOT NULL CHECK(state IN ('initial','observed','unavailable')),
    reason TEXT CHECK(reason IS NULL OR reason IN (
        'invalid_price','missing_currency','missing_price','provider_unavailable',
        'source_mismatch','source_unavailable','timestamp_unavailable'
    )),
    created_at TEXT NOT NULL CHECK(length(created_at) BETWEEN 20 AND 40),
    PRIMARY KEY(owner_user_id, source_ref),
    CHECK((observed_at IS NULL) = (received_at IS NULL)),
    CHECK((state='unavailable' AND reason IS NOT NULL) OR
          (state!='unavailable' AND reason IS NULL))
);
CREATE INDEX briefing_prices_owner_time
    ON briefing_price_observations(owner_user_id, observed_at DESC, source_ref DESC);
CREATE TRIGGER briefing_prices_no_update BEFORE UPDATE ON briefing_price_observations
BEGIN SELECT RAISE(ABORT, 'briefing price observations are immutable'); END;
CREATE TRIGGER briefing_prices_no_delete BEFORE DELETE ON briefing_price_observations
BEGIN SELECT RAISE(ABORT, 'briefing price observations are immutable'); END;
CREATE TRIGGER briefing_prices_no_replace BEFORE INSERT ON briefing_price_observations
WHEN EXISTS(SELECT 1 FROM briefing_price_observations
           WHERE owner_user_id=NEW.owner_user_id AND source_ref=NEW.source_ref)
BEGIN SELECT RAISE(ABORT, 'briefing price observations are immutable'); END;

CREATE TABLE briefing_snapshots (
    id TEXT PRIMARY KEY CHECK(length(id)=36),
    owner_user_id INTEGER NOT NULL REFERENCES users(id),
    idempotency_key TEXT NOT NULL CHECK(length(idempotency_key)=36),
    request_sha256 TEXT NOT NULL
        CHECK(length(request_sha256)=64 AND request_sha256 NOT GLOB '*[^0-9a-f]*'),
    window TEXT NOT NULL CHECK(window IN ('since_last_visit','last_24_hours','last_7_days')),
    baseline_at TEXT CHECK(baseline_at IS NULL OR length(baseline_at) BETWEEN 20 AND 40),
    observed_as_of TEXT NOT NULL CHECK(length(observed_as_of) BETWEEN 20 AND 40),
    baseline_anchor_revision INTEGER NOT NULL CHECK(baseline_anchor_revision >= 0),
    preference_revision INTEGER NOT NULL CHECK(preference_revision >= 0),
    threshold_bps INTEGER NOT NULL CHECK(threshold_bps BETWEEN 50 AND 1000),
    payload_json TEXT NOT NULL CHECK(length(CAST(payload_json AS BLOB)) <= 65536),
    created_at TEXT NOT NULL CHECK(length(created_at) BETWEEN 20 AND 40),
    UNIQUE(id, owner_user_id),
    UNIQUE(owner_user_id, idempotency_key)
);
CREATE INDEX briefing_snapshots_owner_page
    ON briefing_snapshots(owner_user_id, created_at DESC, id DESC);
CREATE TRIGGER briefing_snapshots_no_update BEFORE UPDATE ON briefing_snapshots
BEGIN SELECT RAISE(ABORT, 'briefing snapshots are immutable'); END;
CREATE TRIGGER briefing_snapshots_no_delete BEFORE DELETE ON briefing_snapshots
BEGIN SELECT RAISE(ABORT, 'briefing snapshots are immutable'); END;
CREATE TRIGGER briefing_snapshots_no_replace BEFORE INSERT ON briefing_snapshots
WHEN EXISTS(SELECT 1 FROM briefing_snapshots
           WHERE id=NEW.id OR
                 (owner_user_id=NEW.owner_user_id AND idempotency_key=NEW.idempotency_key))
BEGIN SELECT RAISE(ABORT, 'briefing snapshots are immutable'); END;

CREATE TABLE briefing_visit_anchors (
    owner_user_id INTEGER NOT NULL REFERENCES users(id),
    revision INTEGER NOT NULL CHECK(revision > 0),
    snapshot_id TEXT NOT NULL,
    baseline_at TEXT NOT NULL CHECK(length(baseline_at) BETWEEN 20 AND 40),
    visited_at TEXT NOT NULL CHECK(length(visited_at) BETWEEN 20 AND 40),
    PRIMARY KEY(owner_user_id, revision),
    UNIQUE(owner_user_id, snapshot_id),
    FOREIGN KEY(snapshot_id, owner_user_id) REFERENCES briefing_snapshots(id, owner_user_id)
);
CREATE TRIGGER briefing_anchors_no_update BEFORE UPDATE ON briefing_visit_anchors
BEGIN SELECT RAISE(ABORT, 'briefing visit anchors are append-only'); END;
CREATE TRIGGER briefing_anchors_no_delete BEFORE DELETE ON briefing_visit_anchors
BEGIN SELECT RAISE(ABORT, 'briefing visit anchors are append-only'); END;
CREATE TRIGGER briefing_anchors_no_replace BEFORE INSERT ON briefing_visit_anchors
WHEN EXISTS(SELECT 1 FROM briefing_visit_anchors
           WHERE owner_user_id=NEW.owner_user_id AND revision=NEW.revision)
  OR EXISTS(SELECT 1 FROM briefing_visit_anchors
            WHERE owner_user_id=NEW.owner_user_id AND snapshot_id=NEW.snapshot_id)
BEGIN SELECT RAISE(ABORT, 'briefing visit anchors are append-only'); END;
