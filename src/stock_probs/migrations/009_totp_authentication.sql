-- Schema v9 adds an authenticator-app second factor without rewriting legacy passkey state.
-- Secrets arrive here only after the auth layer has encrypted them with its deployment key.
-- The factor row id is the immutable generation. Replacing a factor deletes and inserts a
-- row, so a proof captured for the previous generation cannot satisfy a later CAS.

CREATE TABLE totp_factors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL UNIQUE REFERENCES users(id),
    secret_ciphertext TEXT NOT NULL
        CHECK (length(trim(secret_ciphertext)) BETWEEN 16 AND 16384),
    created_at TEXT NOT NULL,
    confirmed_at TEXT NOT NULL,
    last_accepted_step INTEGER NOT NULL DEFAULT -1
        CHECK (last_accepted_step >= -1),
    updated_at TEXT NOT NULL,
    CHECK (confirmed_at >= created_at),
    CHECK (updated_at >= created_at)
);
CREATE INDEX idx_totp_factors_user ON totp_factors(user_id);

-- Factor identity is immutable. Mutable replay state is updated through the monotonic CAS
-- in the repository; changing the secret or owner requires a new generation row.
CREATE TRIGGER totp_factors_identity_immutable
BEFORE UPDATE OF id, user_id, secret_ciphertext, created_at, confirmed_at ON totp_factors
BEGIN
    SELECT RAISE(ABORT, 'TOTP factor identity is immutable');
END;

CREATE TABLE totp_enrollments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL UNIQUE REFERENCES users(id),
    secret_ciphertext TEXT NOT NULL
        CHECK (length(trim(secret_ciphertext)) BETWEEN 16 AND 16384),
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    expected_factor_id INTEGER,
    origin_token_hash TEXT NOT NULL
        CHECK (length(origin_token_hash) = 64 AND origin_token_hash NOT GLOB '*[^0-9a-f]*'),
    CHECK (expires_at > created_at)
);
CREATE INDEX idx_totp_enrollments_expiry ON totp_enrollments(expires_at);

CREATE TABLE recovery_codes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    code_hash TEXT NOT NULL UNIQUE
        CHECK (length(code_hash) = 64 AND code_hash NOT GLOB '*[^0-9a-f]*'),
    created_at TEXT NOT NULL,
    consumed_at TEXT,
    revoked_at TEXT,
    CHECK (consumed_at IS NULL OR consumed_at >= created_at),
    CHECK (revoked_at IS NULL OR revoked_at >= created_at)
);
CREATE INDEX idx_recovery_codes_user ON recovery_codes(user_id, id DESC);
CREATE INDEX idx_recovery_codes_available
    ON recovery_codes(user_id, consumed_at, revoked_at, id DESC);

-- A consumed code is never reusable or reset, including through a direct SQLite connection.
CREATE TRIGGER recovery_codes_consume_once BEFORE UPDATE OF consumed_at ON recovery_codes
WHEN OLD.consumed_at IS NOT NULL OR NEW.consumed_at IS NULL
BEGIN
    SELECT RAISE(ABORT, 'recovery codes are single-use');
END;

CREATE TRIGGER recovery_codes_identity_immutable
BEFORE UPDATE OF user_id, code_hash ON recovery_codes
BEGIN
    SELECT RAISE(ABORT, 'recovery code identity is immutable');
END;

CREATE TABLE totp_attempt_throttles (
    user_id INTEGER PRIMARY KEY REFERENCES users(id),
    window_started_at TEXT NOT NULL,
    attempt_count INTEGER NOT NULL CHECK (attempt_count BETWEEN 0 AND 100),
    last_attempt_at TEXT NOT NULL,
    locked_until TEXT,
    CHECK (last_attempt_at >= window_started_at),
    CHECK (locked_until IS NULL OR locked_until >= last_attempt_at)
);
CREATE INDEX idx_totp_attempt_throttles_lock ON totp_attempt_throttles(locked_until);

-- Add factor generation metadata only after the referenced table exists. Existing rows keep
-- NULL and old auth_method/passkey data unchanged. The generation marker is retained even
-- after replacement so a stale session remains visibly bound to the old factor id.
ALTER TABLE sessions ADD COLUMN mfa_method TEXT
    CHECK (mfa_method IS NULL OR mfa_method IN ('totp', 'recovery'));
ALTER TABLE sessions ADD COLUMN mfa_verified_at TEXT
    CHECK (
        (mfa_method IS NULL AND mfa_verified_at IS NULL)
        OR (mfa_method IS NOT NULL AND mfa_verified_at IS NOT NULL)
    );
ALTER TABLE sessions ADD COLUMN mfa_factor_id INTEGER
    CHECK (mfa_factor_id IS NULL OR mfa_factor_id > 0);
