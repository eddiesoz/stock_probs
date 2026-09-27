-- M07 adds account state and ownership indexes without rewriting the immutable v6 audit tables.
-- Existing audit rows are explicitly assigned to the single designated legacy owner (id 1).
-- The sidecars keep their original row bytes and primary keys intact while making every read
-- owner-aware. A later user may safely reuse an identical immutable run through another mapping.
CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    github_user_id INTEGER UNIQUE,
    login TEXT UNIQUE,
    email TEXT,
    display_name TEXT NOT NULL CHECK (length(trim(display_name)) BETWEEN 1 AND 200),
    password_hash TEXT,
    role TEXT NOT NULL CHECK (role IN ('admin', 'member')),
    status TEXT NOT NULL CHECK (status IN ('active', 'invited', 'disabled')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_login_at TEXT,
    legacy_owner_claimed_at TEXT
);

-- This account is an explicit import target for data created before account ownership existed.
-- It is not a login credential and must be replaced or disabled by production provisioning.
INSERT INTO users
    (id, login, display_name, role, status, created_at, updated_at)
VALUES
    (1, 'legacy-owner', 'Legacy owner', 'admin', 'active',
     '1970-01-01T00:00:00+00:00', '1970-01-01T00:00:00+00:00');

CREATE TABLE invitations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    github_user_id INTEGER NOT NULL,
    github_login TEXT,
    token_hash TEXT NOT NULL UNIQUE
        CHECK (length(token_hash) = 64 AND token_hash GLOB '[0-9a-f]*'),
    invited_by_user_id INTEGER NOT NULL REFERENCES users(id),
    expires_at TEXT NOT NULL,
    used_at TEXT,
    created_at TEXT NOT NULL,
    CHECK (used_at IS NULL OR used_at >= created_at)
);
CREATE INDEX idx_invitations_github ON invitations(github_user_id, id DESC);
CREATE INDEX idx_invitations_expiry ON invitations(expires_at, used_at);

CREATE TABLE sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    session_id TEXT NOT NULL UNIQUE CHECK (length(session_id) BETWEEN 16 AND 128),
    token_hash TEXT NOT NULL UNIQUE
        CHECK (length(token_hash) = 64 AND token_hash GLOB '[0-9a-f]*'),
    csrf_token_hash TEXT NOT NULL
        CHECK (length(csrf_token_hash) = 64 AND csrf_token_hash GLOB '[0-9a-f]*'),
    issued_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    idle_expires_at TEXT NOT NULL,
    absolute_expires_at TEXT NOT NULL,
    auth_method TEXT NOT NULL CHECK (auth_method IN ('local', 'github', 'passkey')),
    last_passkey_at TEXT,
    revoked_at TEXT,
    revocation_reason TEXT,
    CHECK (last_seen_at >= issued_at),
    CHECK (idle_expires_at >= last_seen_at),
    CHECK (absolute_expires_at >= issued_at),
    CHECK (revoked_at IS NULL OR revoked_at >= issued_at)
);
CREATE INDEX idx_sessions_user ON sessions(user_id, id DESC);
CREATE INDEX idx_sessions_expiry ON sessions(idle_expires_at, absolute_expires_at, revoked_at);

-- OAuth state and PKCE verifier remain server-side and are consumed exactly once.
CREATE TABLE oauth_states (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    state_hash TEXT NOT NULL UNIQUE
        CHECK (length(state_hash) = 64 AND state_hash GLOB '[0-9a-f]*'),
    code_verifier TEXT NOT NULL CHECK (length(code_verifier) BETWEEN 16 AND 256),
    redirect_uri TEXT NOT NULL CHECK (length(redirect_uri) BETWEEN 1 AND 2048),
    invitation_code_hash TEXT
        CHECK (invitation_code_hash IS NULL OR
               (length(invitation_code_hash) = 64 AND invitation_code_hash GLOB '[0-9a-f]*')),
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    consumed_at TEXT,
    CHECK (expires_at > created_at),
    CHECK (consumed_at IS NULL OR consumed_at >= created_at)
);
CREATE INDEX idx_oauth_states_expiry ON oauth_states(expires_at, consumed_at);

CREATE TABLE passkeys (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    credential_id TEXT NOT NULL UNIQUE CHECK (length(credential_id) BETWEEN 16 AND 1024),
    public_key TEXT NOT NULL CHECK (length(public_key) BETWEEN 16 AND 16384),
    sign_count INTEGER NOT NULL DEFAULT 0 CHECK (sign_count >= 0),
    transports TEXT,
    created_at TEXT NOT NULL,
    last_used_at TEXT,
    revoked_at TEXT
);
CREATE INDEX idx_passkeys_user ON passkeys(user_id, id DESC);

-- An immutable mapping makes owner checks cheap without adding mutable ownership columns to
-- historical audit rows. A run may have one mapping per user when identical content is reused.
CREATE TABLE forecast_run_owners (
    run_id INTEGER NOT NULL REFERENCES forecast_runs(id),
    owner_user_id INTEGER NOT NULL REFERENCES users(id),
    assigned_at TEXT NOT NULL,
    PRIMARY KEY (run_id, owner_user_id)
);
CREATE INDEX idx_forecast_run_owners_user ON forecast_run_owners(owner_user_id, run_id DESC);

CREATE TABLE forecast_result_owners (
    result_id INTEGER NOT NULL REFERENCES forecast_results(id),
    owner_user_id INTEGER NOT NULL REFERENCES users(id),
    assigned_at TEXT NOT NULL,
    PRIMARY KEY (result_id, owner_user_id)
);
CREATE INDEX idx_forecast_result_owners_user
    ON forecast_result_owners(owner_user_id, result_id DESC);

CREATE TABLE outcome_owners (
    outcome_id INTEGER PRIMARY KEY REFERENCES outcomes(id),
    owner_user_id INTEGER NOT NULL REFERENCES users(id),
    assigned_at TEXT NOT NULL
);
CREATE INDEX idx_outcome_owners_user ON outcome_owners(owner_user_id, outcome_id DESC);

CREATE TABLE search_event_owners (
    event_id INTEGER PRIMARY KEY REFERENCES search_events(id),
    owner_user_id INTEGER NOT NULL REFERENCES users(id),
    assigned_at TEXT NOT NULL
);
CREATE INDEX idx_search_event_owners_user ON search_event_owners(owner_user_id, event_id DESC);

CREATE TRIGGER immutable_forecast_run_owners_update BEFORE UPDATE ON forecast_run_owners BEGIN
    SELECT RAISE(ABORT, 'forecast run ownership is immutable');
END;
CREATE TRIGGER immutable_forecast_run_owners_delete BEFORE DELETE ON forecast_run_owners BEGIN
    SELECT RAISE(ABORT, 'forecast run ownership is append-only');
END;
CREATE TRIGGER immutable_forecast_result_owners_update BEFORE UPDATE ON forecast_result_owners BEGIN
    SELECT RAISE(ABORT, 'forecast result ownership is immutable');
END;
CREATE TRIGGER immutable_forecast_result_owners_delete BEFORE DELETE ON forecast_result_owners BEGIN
    SELECT RAISE(ABORT, 'forecast result ownership is append-only');
END;
CREATE TRIGGER immutable_outcome_owners_update BEFORE UPDATE ON outcome_owners BEGIN
    SELECT RAISE(ABORT, 'outcome ownership is immutable');
END;
CREATE TRIGGER immutable_outcome_owners_delete BEFORE DELETE ON outcome_owners BEGIN
    SELECT RAISE(ABORT, 'outcome ownership is append-only');
END;
CREATE TRIGGER immutable_search_event_owners_update BEFORE UPDATE ON search_event_owners BEGIN
    SELECT RAISE(ABORT, 'search event ownership is immutable');
END;
CREATE TRIGGER immutable_search_event_owners_delete BEFORE DELETE ON search_event_owners BEGIN
    SELECT RAISE(ABORT, 'search event ownership is append-only');
END;
CREATE TRIGGER validate_search_event_owner_insert BEFORE INSERT ON search_event_owners
WHEN NOT EXISTS (SELECT 1 FROM search_events WHERE id = NEW.event_id)
BEGIN
    SELECT RAISE(ABORT, 'search event ownership requires an audit event');
END;

-- Mutable lists are copied into an owner-keyed table. The v5 table remains intact as an
-- immutable legacy source so upgrade parity can be audited without rewriting old user state.
CREATE TABLE user_instrument_list_items (
    owner_user_id INTEGER NOT NULL REFERENCES users(id),
    kind TEXT NOT NULL CHECK (kind IN ('portfolio', 'watchlist')),
    provider TEXT NOT NULL CHECK (length(trim(provider)) BETWEEN 1 AND 80),
    canonical_symbol TEXT NOT NULL CHECK (length(trim(canonical_symbol)) BETWEEN 1 AND 15),
    asset_type TEXT NOT NULL CHECK (asset_type IN ('stock', 'etf')),
    exchange TEXT NOT NULL CHECK (length(trim(exchange)) BETWEEN 1 AND 40),
    display_name TEXT NOT NULL CHECK (length(trim(display_name)) BETWEEN 1 AND 200),
    quantity REAL CHECK (quantity IS NULL OR quantity >= 0),
    added_at TEXT NOT NULL,
    CHECK (kind = 'portfolio' OR quantity IS NULL),
    PRIMARY KEY (owner_user_id, kind, provider, canonical_symbol, asset_type)
);
CREATE INDEX idx_user_instrument_list_scan
    ON user_instrument_list_items(owner_user_id, kind, added_at, canonical_symbol);

-- Copy legacy mutable list state to the designated owner; subsequent writes use the new table.
INSERT INTO user_instrument_list_items
    (owner_user_id, kind, provider, canonical_symbol, asset_type, exchange, display_name,
     quantity, added_at)
SELECT 1, kind, provider, canonical_symbol, asset_type, exchange, display_name, quantity, added_at
FROM instrument_list_items;

-- Explicit migration mapping for every pre-auth immutable row. INSERT OR IGNORE is safe because
-- migration 007 runs once and keeps this copy idempotent for controlled migration retries.
INSERT INTO forecast_run_owners (run_id, owner_user_id, assigned_at)
SELECT id, 1, created_at FROM forecast_runs;
INSERT INTO forecast_result_owners (result_id, owner_user_id, assigned_at)
SELECT result.id, 1, result.created_at
FROM forecast_results AS result;
INSERT INTO search_event_owners (event_id, owner_user_id, assigned_at)
SELECT id, 1, submitted_at FROM search_events;
INSERT INTO outcome_owners (outcome_id, owner_user_id, assigned_at)
SELECT id, 1, created_at FROM outcomes;

CREATE TABLE history_exports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_user_id INTEGER NOT NULL REFERENCES users(id),
    format TEXT NOT NULL CHECK (format IN ('csv', 'json')),
    filters_json TEXT NOT NULL,
    row_count INTEGER NOT NULL CHECK (row_count >= 0),
    created_at TEXT NOT NULL
);
CREATE INDEX idx_history_exports_owner ON history_exports(owner_user_id, id DESC);
CREATE TRIGGER immutable_history_exports_update BEFORE UPDATE ON history_exports BEGIN
    SELECT RAISE(ABORT, 'history exports are immutable');
END;
CREATE TRIGGER immutable_history_exports_delete BEFORE DELETE ON history_exports BEGIN
    SELECT RAISE(ABORT, 'history exports are append-only');
END;
