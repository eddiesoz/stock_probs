-- Schema 18: restart-safe, one-use notification-address verification delivery.
-- Immutable events and bounded pending recipients preserve recovery and redaction semantics.

CREATE TABLE notification_address_verifications (
    id TEXT PRIMARY KEY CHECK(length(id) = 36 AND id NOT GLOB '*[^0-9a-f-]*'
        AND substr(id,9,1)='-' AND substr(id,14,1)='-'
        AND substr(id,19,1)='-' AND substr(id,24,1)='-'),
    owner_user_id INTEGER NOT NULL REFERENCES users(id),
    address_id TEXT NOT NULL CHECK(length(address_id) = 36 AND address_id NOT GLOB '*[^0-9a-f-]*'
        AND substr(address_id,9,1)='-' AND substr(address_id,14,1)='-'
        AND substr(address_id,19,1)='-' AND substr(address_id,24,1)='-'),
    idempotency_sha256 TEXT NOT NULL CHECK(length(idempotency_sha256) = 64
        AND idempotency_sha256 NOT GLOB '*[^0-9a-f]*'),
    request_sha256 TEXT NOT NULL CHECK(length(request_sha256) = 64
        AND request_sha256 NOT GLOB '*[^0-9a-f]*'),
    token_sha256 TEXT NOT NULL CHECK(length(token_sha256) = 64
        AND token_sha256 NOT GLOB '*[^0-9a-f]*'),
    state TEXT NOT NULL CHECK(state IN ('queued','submitting','accepted','failed','uncertain','verified','expired','already_verified')),
    revision INTEGER NOT NULL CHECK(revision BETWEEN 1 AND 12),
    attempts INTEGER NOT NULL DEFAULT 0 CHECK(attempts BETWEEN 0 AND 5),
    requested_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    submission_started_at TEXT,
    accepted_at TEXT,
    completed_at TEXT,
    failure_code TEXT CHECK(failure_code IS NULL OR failure_code IN
        ('smtp_prepare_failed','smtp_rejected','smtp_outcome_unknown','challenge_expired','attempts_exhausted')),
    invalidated_at TEXT,
    UNIQUE(id, owner_user_id),
    UNIQUE(owner_user_id, idempotency_sha256),
    CHECK(expires_at > requested_at),
    CHECK(state != 'submitting' OR
        (submission_started_at IS NOT NULL AND accepted_at IS NULL)),
    CHECK(state NOT IN ('uncertain','verified') OR submission_started_at IS NOT NULL),
    CHECK(state != 'accepted' OR accepted_at IS NOT NULL),
    CHECK(state NOT IN ('failed','uncertain','verified','expired','already_verified')
        OR completed_at IS NOT NULL)
);
CREATE INDEX notification_address_verifications_owner_time
    ON notification_address_verifications(owner_user_id, requested_at DESC, id DESC);
CREATE INDEX notification_address_verifications_state_time
    ON notification_address_verifications(state, submission_started_at);

CREATE TABLE notification_address_verification_recipients (
    verification_id TEXT PRIMARY KEY,
    owner_user_id INTEGER NOT NULL,
    address TEXT NOT NULL CHECK(length(address) BETWEEN 3 AND 320),
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    FOREIGN KEY(verification_id, owner_user_id)
        REFERENCES notification_address_verifications(id, owner_user_id),
    CHECK(expires_at > created_at)
);
CREATE INDEX notification_address_verification_recipients_expiry
    ON notification_address_verification_recipients(expires_at, verification_id);

CREATE TRIGGER notification_address_verification_recipients_insert_guard
BEFORE INSERT ON notification_address_verification_recipients
WHEN NOT EXISTS(
    SELECT 1 FROM notification_address_verifications v
    WHERE v.id=NEW.verification_id AND v.owner_user_id=NEW.owner_user_id
      AND v.state='queued' AND v.invalidated_at IS NULL
)
BEGIN SELECT RAISE(ABORT,'recipient must belong to a queued challenge'); END;
CREATE TRIGGER notification_address_verification_recipients_no_update
BEFORE UPDATE ON notification_address_verification_recipients
BEGIN SELECT RAISE(ABORT,'pending recipient identity is immutable'); END;
CREATE TRIGGER notification_address_verification_recipients_delete_guard
BEFORE DELETE ON notification_address_verification_recipients
WHEN EXISTS(
    SELECT 1 FROM notification_address_verifications v
    WHERE v.id=OLD.verification_id AND v.owner_user_id=OLD.owner_user_id
      AND v.state IN ('queued','submitting','accepted','uncertain')
      AND v.invalidated_at IS NULL
)
BEGIN SELECT RAISE(ABORT,'pending recipient is retained until challenge completion'); END;
CREATE TRIGGER notification_address_verification_recipients_no_replace
BEFORE INSERT ON notification_address_verification_recipients
WHEN EXISTS(SELECT 1 FROM notification_address_verification_recipients
    WHERE verification_id=NEW.verification_id)
BEGIN SELECT RAISE(ABORT,'pending recipient already exists'); END;

CREATE TABLE notification_address_verification_events (
    event_id INTEGER PRIMARY KEY,
    verification_id TEXT NOT NULL,
    owner_user_id INTEGER NOT NULL,
    revision INTEGER NOT NULL CHECK(revision BETWEEN 1 AND 12),
    event_kind TEXT NOT NULL CHECK(event_kind IN
        ('queued','already_verified','submission_started','accepted','failed','uncertain',
         'attempt_failed','verified','expired','invalidated')),
    occurred_at TEXT NOT NULL,
    failure_code TEXT CHECK(failure_code IS NULL OR failure_code IN
        ('smtp_prepare_failed','smtp_rejected','smtp_outcome_unknown','challenge_expired','attempts_exhausted')),
    FOREIGN KEY(verification_id, owner_user_id)
        REFERENCES notification_address_verifications(id, owner_user_id),
    UNIQUE(verification_id, revision)
);
CREATE INDEX notification_address_verification_events_owner
    ON notification_address_verification_events(owner_user_id, event_id DESC);

CREATE TRIGGER notification_address_verifications_preserve_identity
BEFORE UPDATE ON notification_address_verifications
WHEN NEW.id IS NOT OLD.id OR NEW.owner_user_id IS NOT OLD.owner_user_id
  OR NEW.address_id IS NOT OLD.address_id
  OR NEW.idempotency_sha256 IS NOT OLD.idempotency_sha256
  OR NEW.request_sha256 IS NOT OLD.request_sha256
  OR NEW.token_sha256 IS NOT OLD.token_sha256
  OR NEW.requested_at IS NOT OLD.requested_at OR NEW.expires_at IS NOT OLD.expires_at
BEGIN SELECT RAISE(ABORT,'verification challenge identity is immutable'); END;

CREATE TRIGGER notification_address_verifications_transition_guard
BEFORE UPDATE ON notification_address_verifications
WHEN NEW.revision != OLD.revision + 1 OR NOT (
    (NEW.state = OLD.state AND NEW.invalidated_at IS NOT NULL AND OLD.invalidated_at IS NULL
      AND NEW.attempts = OLD.attempts)
 OR (NEW.state = OLD.state AND NEW.attempts = OLD.attempts + 1
      AND NEW.attempts <= 5 AND NEW.invalidated_at IS OLD.invalidated_at)
 OR (OLD.state = 'queued' AND NEW.state IN ('submitting','failed','expired')
      AND NEW.attempts = OLD.attempts AND NEW.invalidated_at IS OLD.invalidated_at)
 OR (OLD.state = 'submitting' AND NEW.state IN ('accepted','failed','uncertain')
      AND NEW.attempts = OLD.attempts AND NEW.invalidated_at IS OLD.invalidated_at)
 OR (OLD.state IN ('accepted','uncertain') AND NEW.state IN ('verified','expired')
      AND NEW.attempts = OLD.attempts AND NEW.invalidated_at IS OLD.invalidated_at)
 OR (OLD.state IN ('accepted','uncertain') AND NEW.state = 'expired'
      AND NEW.attempts = OLD.attempts + 1 AND NEW.attempts <= 5
      AND NEW.invalidated_at IS OLD.invalidated_at)
)
BEGIN SELECT RAISE(ABORT,'verification challenge transition is invalid'); END;

CREATE TRIGGER notification_address_verifications_no_delete
BEFORE DELETE ON notification_address_verifications
BEGIN SELECT RAISE(ABORT,'verification challenge history is retained'); END;
CREATE TRIGGER notification_address_verifications_insert_guard
BEFORE INSERT ON notification_address_verifications
WHEN NEW.revision != 1 OR NEW.attempts != 0 OR NEW.submission_started_at IS NOT NULL
  OR NEW.accepted_at IS NOT NULL OR NEW.invalidated_at IS NOT NULL
  OR NEW.state NOT IN ('queued','already_verified')
BEGIN SELECT RAISE(ABORT,'verification challenge must begin in a typed initial state'); END;
CREATE TRIGGER notification_address_verifications_owner_cap
BEFORE INSERT ON notification_address_verifications
WHEN (SELECT COUNT(*) FROM notification_address_verifications
      WHERE owner_user_id=NEW.owner_user_id) >= 100
BEGIN SELECT RAISE(ABORT,'verification challenge owner limit reached'); END;
CREATE TRIGGER notification_address_verifications_no_replace
BEFORE INSERT ON notification_address_verifications
WHEN EXISTS(SELECT 1 FROM notification_address_verifications WHERE id=NEW.id
    OR (owner_user_id=NEW.owner_user_id AND idempotency_sha256=NEW.idempotency_sha256))
BEGIN SELECT RAISE(ABORT,'verification challenge history is retained'); END;
CREATE TRIGGER notification_address_verification_events_no_update
BEFORE UPDATE ON notification_address_verification_events
BEGIN SELECT RAISE(ABORT,'verification events are immutable'); END;
CREATE TRIGGER notification_address_verification_events_no_delete
BEFORE DELETE ON notification_address_verification_events
BEGIN SELECT RAISE(ABORT,'verification events are immutable'); END;
CREATE TRIGGER notification_address_verification_events_no_replace
BEFORE INSERT ON notification_address_verification_events
WHEN EXISTS(SELECT 1 FROM notification_address_verification_events
    WHERE event_id=NEW.event_id OR
          (verification_id=NEW.verification_id AND revision=NEW.revision))
BEGIN SELECT RAISE(ABORT,'verification events are immutable'); END;
CREATE TRIGGER notification_address_verification_events_state_guard
BEFORE INSERT ON notification_address_verification_events
WHEN NOT EXISTS(
    SELECT 1 FROM notification_address_verifications v
    WHERE v.id=NEW.verification_id AND v.owner_user_id=NEW.owner_user_id
      AND v.revision=NEW.revision AND (
        (NEW.event_kind='queued' AND v.state='queued') OR
        (NEW.event_kind='already_verified' AND v.state='already_verified') OR
        (NEW.event_kind='submission_started' AND v.state='submitting') OR
        (NEW.event_kind='accepted' AND v.state='accepted') OR
        (NEW.event_kind='failed' AND v.state='failed') OR
        (NEW.event_kind='uncertain' AND v.state='uncertain') OR
        (NEW.event_kind='attempt_failed' AND v.state IN ('accepted','uncertain')) OR
        (NEW.event_kind='verified' AND v.state='verified') OR
        (NEW.event_kind='expired' AND v.state='expired') OR
        (NEW.event_kind='invalidated' AND v.invalidated_at IS NOT NULL)
      )
)
BEGIN SELECT RAISE(ABORT,'verification event does not match persisted state'); END;
