-- Persistent monitoring is independent of assistant execution and retains immutable observations.
CREATE UNIQUE INDEX monitoring_outcome_owner_identity ON outcome_owners(outcome_id, owner_user_id);

CREATE TABLE monitoring_control (
    id INTEGER PRIMARY KEY CHECK(id = 1),
    enabled INTEGER NOT NULL DEFAULT 0 CHECK(enabled IN (0,1)),
    revision INTEGER NOT NULL DEFAULT 1 CHECK(revision > 0),
    queue_sequence INTEGER NOT NULL DEFAULT 0 CHECK(queue_sequence >= 0),
    updated_at TEXT NOT NULL
);
INSERT INTO monitoring_control(id, enabled, revision, queue_sequence, updated_at)
VALUES (1, 0, 1, 0, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'));

CREATE TABLE notification_addresses (
    id TEXT PRIMARY KEY CHECK(length(id) = 36),
    owner_user_id INTEGER NOT NULL REFERENCES users(id),
    address TEXT NOT NULL CHECK(length(address) BETWEEN 3 AND 320),
    challenge_hash TEXT CHECK(challenge_hash IS NULL OR length(challenge_hash) = 64),
    challenge_expires_at TEXT,
    challenge_attempts INTEGER NOT NULL DEFAULT 0 CHECK(challenge_attempts BETWEEN 0 AND 5),
    verified_at TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(id, owner_user_id)
);
CREATE INDEX notification_addresses_owner ON notification_addresses(owner_user_id, created_at DESC);

CREATE TABLE notification_preferences (
    owner_user_id INTEGER PRIMARY KEY REFERENCES users(id),
    revision INTEGER NOT NULL CHECK(revision > 0),
    address_id TEXT,
    alert_email INTEGER NOT NULL DEFAULT 0 CHECK(alert_email IN (0,1)),
    digest_email INTEGER NOT NULL DEFAULT 0 CHECK(digest_email IN (0,1)),
    digest_time TEXT NOT NULL DEFAULT '09:00' CHECK(length(digest_time) = 5),
    digest_timezone TEXT NOT NULL DEFAULT 'America/Toronto' CHECK(length(digest_timezone) BETWEEN 1 AND 64),
    updated_at TEXT NOT NULL,
    FOREIGN KEY(address_id, owner_user_id) REFERENCES notification_addresses(id, owner_user_id)
);

CREATE TABLE price_alerts (
    id TEXT PRIMARY KEY CHECK(length(id) = 36),
    owner_user_id INTEGER NOT NULL REFERENCES users(id),
    idempotency_key TEXT NOT NULL CHECK(length(idempotency_key) = 36),
    request_sha256 TEXT NOT NULL CHECK(length(request_sha256) = 64),
    revision INTEGER NOT NULL CHECK(revision > 0),
    monitor_revision INTEGER NOT NULL CHECK(monitor_revision > 0),
    payload_json TEXT NOT NULL CHECK(length(CAST(payload_json AS BLOB)) <= 4096),
    enabled INTEGER NOT NULL CHECK(enabled IN (0,1)),
    armed_at TEXT NOT NULL,
    arm_generation INTEGER NOT NULL CHECK(arm_generation > 0),
    arm_snapshot_generation INTEGER,
    arm_snapshot_request_id TEXT,
    arm_snapshot_requested_at TEXT,
    arm_snapshot_received_at TEXT,
    last_side INTEGER CHECK(last_side IN (-1,0,1)),
    ready INTEGER NOT NULL DEFAULT 0 CHECK(ready IN (0,1)),
    last_observed_at TEXT,
    last_observation_json TEXT CHECK(last_observation_json IS NULL OR length(CAST(last_observation_json AS BLOB)) <= 4096),
    last_fetch_request_id TEXT,
    last_fetch_requested_at TEXT,
    last_fetch_received_at TEXT,
    last_check_at TEXT,
    last_success_at TEXT,
    check_state TEXT NOT NULL DEFAULT 'arming' CHECK(check_state IN ('arming','watching','paused','triggered','unavailable')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(id, owner_user_id),
    UNIQUE(owner_user_id, idempotency_key),
    CHECK (
        (arm_snapshot_generation IS NULL AND arm_snapshot_request_id IS NULL
         AND arm_snapshot_requested_at IS NULL AND arm_snapshot_received_at IS NULL)
        OR (arm_snapshot_generation = arm_generation AND arm_snapshot_generation > 0
            AND arm_snapshot_request_id IS NOT NULL AND arm_snapshot_requested_at IS NOT NULL
            AND arm_snapshot_received_at IS NOT NULL)
    ),
    CHECK (
        (last_observed_at IS NULL AND last_observation_json IS NULL)
        OR (last_observed_at IS NOT NULL AND last_observation_json IS NOT NULL)
    ),
    CHECK (
        (last_fetch_request_id IS NULL AND last_fetch_requested_at IS NULL AND last_fetch_received_at IS NULL)
        OR (last_fetch_request_id IS NOT NULL AND last_fetch_requested_at IS NOT NULL
            AND last_fetch_received_at IS NOT NULL)
    ),
    CHECK (ready = 0 OR arm_snapshot_generation = arm_generation)
);
CREATE INDEX price_alerts_owner ON price_alerts(owner_user_id, created_at DESC, id);

CREATE TABLE price_alert_revisions (
    alert_id TEXT NOT NULL,
    owner_user_id INTEGER NOT NULL,
    revision INTEGER NOT NULL CHECK(revision > 0),
    payload_json TEXT NOT NULL CHECK(length(CAST(payload_json AS BLOB)) <= 4096),
    enabled INTEGER NOT NULL CHECK(enabled IN (0,1)),
    recorded_at TEXT NOT NULL,
    PRIMARY KEY(alert_id, revision),
    FOREIGN KEY(alert_id, owner_user_id) REFERENCES price_alerts(id, owner_user_id)
);

CREATE TABLE monitoring_owner_queue (
    owner_user_id INTEGER PRIMARY KEY REFERENCES users(id),
    service_sequence INTEGER NOT NULL DEFAULT 0 CHECK(service_sequence >= 0),
    last_served_at TEXT NOT NULL
);

CREATE TABLE monitoring_jobs (
    id TEXT PRIMARY KEY CHECK(length(id) = 36),
    owner_user_id INTEGER NOT NULL REFERENCES users(id),
    kind TEXT NOT NULL CHECK(kind IN ('price','outcome','mail','digest','brief_price')),
    resource_id TEXT NOT NULL CHECK(length(resource_id) BETWEEN 1 AND 80),
    due_at TEXT NOT NULL,
    alert_generation INTEGER CHECK(alert_generation IS NULL OR alert_generation > 0),
    expected_monitor_revision INTEGER CHECK(expected_monitor_revision IS NULL OR expected_monitor_revision > 0),
    request_kind TEXT CHECK(request_kind IS NULL OR request_kind IN ('arm_snapshot','tick')),
    lease_token TEXT CHECK(lease_token IS NULL OR length(lease_token) = 36),
    lease_until TEXT,
    active_request_id TEXT CHECK(active_request_id IS NULL OR length(active_request_id) = 36),
    active_requested_at TEXT,
    attempts INTEGER NOT NULL DEFAULT 0 CHECK(attempts >= 0),
    revision INTEGER NOT NULL DEFAULT 1 CHECK(revision > 0),
    last_attempt_at TEXT,
    last_success_at TEXT,
    failure_code TEXT CHECK(failure_code IS NULL OR length(failure_code) <= 80),
    checkpoint_json TEXT NOT NULL DEFAULT '{}' CHECK(length(CAST(checkpoint_json AS BLOB)) <= 4096),
    UNIQUE(id, owner_user_id),
    UNIQUE(owner_user_id, kind, resource_id),
    CHECK (
        (lease_token IS NULL AND lease_until IS NULL AND active_request_id IS NULL AND active_requested_at IS NULL)
        OR (lease_token IS NOT NULL AND lease_until IS NOT NULL AND active_request_id IS NOT NULL
            AND active_requested_at IS NOT NULL)
    ),
    CHECK (
        (kind = 'price' AND alert_generation IS NOT NULL AND expected_monitor_revision IS NOT NULL
         AND request_kind IS NOT NULL)
        OR (kind != 'price' AND alert_generation IS NULL AND expected_monitor_revision IS NULL
            AND request_kind IS NULL)
    )
);
CREATE INDEX monitoring_jobs_due ON monitoring_jobs(due_at, owner_user_id, id);

CREATE TABLE price_alert_observations (
    request_id TEXT PRIMARY KEY CHECK(length(request_id) = 36),
    owner_user_id INTEGER NOT NULL,
    alert_id TEXT NOT NULL,
    job_id TEXT NOT NULL,
    generation INTEGER NOT NULL CHECK(generation > 0),
    observation_kind TEXT NOT NULL CHECK(observation_kind IN ('arm_snapshot','tick')),
    request_sha256 TEXT NOT NULL CHECK(length(request_sha256) = 64 AND request_sha256 NOT GLOB '*[^0-9a-f]*'),
    receipt_sha256 TEXT NOT NULL CHECK(length(receipt_sha256) = 64 AND receipt_sha256 NOT GLOB '*[^0-9a-f]*'),
    dedupe_sha256 TEXT NOT NULL CHECK(length(dedupe_sha256) = 64 AND dedupe_sha256 NOT GLOB '*[^0-9a-f]*'),
    lease_token TEXT NOT NULL CHECK(length(lease_token) = 36),
    requested_at TEXT NOT NULL,
    received_at TEXT NOT NULL,
    accepted_at TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    provider TEXT NOT NULL CHECK(length(provider) BETWEEN 1 AND 80),
    symbol TEXT NOT NULL CHECK(length(symbol) BETWEEN 1 AND 80),
    currency TEXT NOT NULL CHECK(length(currency) = 3),
    price TEXT NOT NULL CHECK(length(price) BETWEEN 1 AND 64),
    disposition TEXT NOT NULL CHECK(disposition IN ('initial','ignored','observed','triggered')),
    stale INTEGER NOT NULL CHECK(stale IN (0,1)),
    state_revision_before INTEGER NOT NULL CHECK(state_revision_before > 0),
    state_revision_after INTEGER NOT NULL CHECK(state_revision_after = state_revision_before + 1),
    UNIQUE(request_id, owner_user_id, alert_id, generation),
    UNIQUE(owner_user_id, alert_id, generation, dedupe_sha256),
    FOREIGN KEY(alert_id, owner_user_id) REFERENCES price_alerts(id, owner_user_id),
    FOREIGN KEY(job_id, owner_user_id) REFERENCES monitoring_jobs(id, owner_user_id)
);
CREATE INDEX price_alert_observations_owner ON price_alert_observations(owner_user_id, alert_id, observed_at DESC);

CREATE TABLE notifications (
    id TEXT PRIMARY KEY CHECK(length(id) = 36),
    owner_user_id INTEGER NOT NULL REFERENCES users(id),
    dedupe_sha256 TEXT NOT NULL CHECK(length(dedupe_sha256) = 64 AND dedupe_sha256 NOT GLOB '*[^0-9a-f]*'),
    kind TEXT NOT NULL CHECK(kind IN ('price_alert','forecast_outcome','thesis_review')),
    payload_json TEXT NOT NULL CHECK(length(CAST(payload_json AS BLOB)) <= 8192),
    is_read INTEGER NOT NULL DEFAULT 0 CHECK(is_read IN (0,1)),
    revision INTEGER NOT NULL DEFAULT 1 CHECK(revision > 0),
    created_at TEXT NOT NULL,
    UNIQUE(id, owner_user_id),
    UNIQUE(owner_user_id, dedupe_sha256)
);
CREATE INDEX notifications_owner ON notifications(owner_user_id, created_at DESC, id);

CREATE TABLE notification_read_events (
    id TEXT PRIMARY KEY CHECK(length(id) = 36),
    notification_id TEXT NOT NULL,
    owner_user_id INTEGER NOT NULL,
    revision INTEGER NOT NULL CHECK(revision > 1),
    is_read INTEGER NOT NULL CHECK(is_read IN (0,1)),
    changed_at TEXT NOT NULL,
    UNIQUE(notification_id, revision),
    FOREIGN KEY(notification_id, owner_user_id) REFERENCES notifications(id, owner_user_id)
);

CREATE TABLE notification_outbox (
    id TEXT PRIMARY KEY CHECK(length(id) = 36),
    owner_user_id INTEGER NOT NULL REFERENCES users(id),
    notification_id TEXT NOT NULL,
    delivery_version INTEGER NOT NULL CHECK(typeof(delivery_version) = 'integer' AND delivery_version > 0),
    preference_revision INTEGER NOT NULL CHECK(typeof(preference_revision) = 'integer' AND preference_revision > 0),
    job_id TEXT NOT NULL,
    dedupe_sha256 TEXT NOT NULL CHECK(length(dedupe_sha256) = 64 AND dedupe_sha256 NOT GLOB '*[^0-9a-f]*'),
    address_id TEXT NOT NULL,
    kind TEXT NOT NULL CHECK(kind = 'price_alert'),
    payload_json TEXT NOT NULL CHECK(length(CAST(payload_json AS BLOB)) <= 16384),
    state TEXT NOT NULL DEFAULT 'queued' CHECK(state IN ('queued','claimed','submitting','accepted','failed','uncertain')),
    attempts INTEGER NOT NULL DEFAULT 0 CHECK(typeof(attempts) = 'integer' AND attempts BETWEEN 0 AND 3),
    attempt_revision INTEGER NOT NULL DEFAULT 0 CHECK(typeof(attempt_revision) = 'integer' AND attempt_revision BETWEEN 0 AND 3),
    attempt_id TEXT CHECK(attempt_id IS NULL OR length(attempt_id) = 36),
    revision INTEGER NOT NULL DEFAULT 1 CHECK(typeof(revision) = 'integer' AND revision > 0),
    next_attempt_at TEXT NOT NULL,
    lease_token TEXT CHECK(lease_token IS NULL OR length(lease_token) = 36),
    lease_until TEXT,
    submission_started_at TEXT,
    created_at TEXT NOT NULL,
    submitted_at TEXT,
    completed_at TEXT,
    transitioned_at TEXT NOT NULL,
    failure_code TEXT CHECK(failure_code IS NULL OR (length(failure_code) BETWEEN 1 AND 80 AND failure_code NOT GLOB '*[^a-z0-9_:-]*')),
    UNIQUE(id, owner_user_id),
    UNIQUE(owner_user_id, dedupe_sha256),
    UNIQUE(notification_id, delivery_version),
    UNIQUE(job_id, owner_user_id),
    FOREIGN KEY(notification_id, owner_user_id) REFERENCES notifications(id, owner_user_id),
    FOREIGN KEY(address_id, owner_user_id) REFERENCES notification_addresses(id, owner_user_id),
    FOREIGN KEY(job_id, owner_user_id) REFERENCES monitoring_jobs(id, owner_user_id),
    CHECK ((attempts = 0 AND attempt_revision = 0 AND attempt_id IS NULL)
        OR (attempts = attempt_revision AND attempt_revision > 0 AND attempt_id IS NOT NULL)),
    CHECK ((lease_token IS NULL AND lease_until IS NULL)
        OR (lease_token IS NOT NULL AND lease_until IS NOT NULL)),
    CHECK (
        (state = 'queued' AND lease_token IS NULL AND submission_started_at IS NULL
         AND submitted_at IS NULL AND completed_at IS NULL)
        OR (state = 'claimed' AND lease_token IS NOT NULL AND submission_started_at IS NULL
            AND submitted_at IS NULL AND completed_at IS NULL)
        OR (state = 'submitting' AND lease_token IS NOT NULL AND submission_started_at IS NOT NULL
            AND submitted_at IS NULL AND completed_at IS NULL)
        OR (state = 'accepted' AND lease_token IS NULL AND submission_started_at IS NOT NULL
            AND submitted_at IS NOT NULL AND completed_at IS NOT NULL)
        OR (state = 'failed' AND lease_token IS NULL AND submitted_at IS NULL AND completed_at IS NOT NULL)
        OR (state = 'uncertain' AND lease_token IS NULL AND submission_started_at IS NOT NULL
            AND submitted_at IS NULL AND completed_at IS NOT NULL)
    )
);
CREATE INDEX notification_outbox_due ON notification_outbox(state, next_attempt_at, owner_user_id, id);
CREATE INDEX notification_outbox_owner ON notification_outbox(owner_user_id, created_at DESC, id);

CREATE TABLE notification_outbox_attempts (
    event_id INTEGER PRIMARY KEY,
    outbox_id TEXT NOT NULL,
    owner_user_id INTEGER NOT NULL,
    attempt_id TEXT NOT NULL CHECK(length(attempt_id) = 36),
    attempt_revision INTEGER NOT NULL CHECK(typeof(attempt_revision) = 'integer' AND attempt_revision > 0),
    revision INTEGER NOT NULL CHECK(typeof(revision) = 'integer' AND revision > 1),
    event_kind TEXT NOT NULL CHECK(event_kind IN ('claimed','submission_started','retry_scheduled','pre_submission_failed','accepted','failed','uncertain')),
    occurred_at TEXT NOT NULL,
    failure_code TEXT CHECK(failure_code IS NULL OR (length(failure_code) BETWEEN 1 AND 80 AND failure_code NOT GLOB '*[^a-z0-9_:-]*')),
    UNIQUE(outbox_id, revision),
    FOREIGN KEY(outbox_id, owner_user_id) REFERENCES notification_outbox(id, owner_user_id)
);

CREATE TABLE collected_outcome_evidence (
    outcome_id INTEGER PRIMARY KEY REFERENCES outcomes(id),
    owner_user_id INTEGER NOT NULL,
    result_id INTEGER NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('observed','unavailable','incomparable')),
    payload_json TEXT NOT NULL CHECK(length(CAST(payload_json AS BLOB)) <= 262144),
    collected_at TEXT NOT NULL,
    FOREIGN KEY(outcome_id, owner_user_id) REFERENCES outcome_owners(outcome_id, owner_user_id),
    FOREIGN KEY(result_id, owner_user_id) REFERENCES forecast_result_owners(result_id, owner_user_id)
);
CREATE TRIGGER collected_outcomes_match_result BEFORE INSERT ON collected_outcome_evidence
WHEN NOT EXISTS (
    SELECT 1 FROM outcomes WHERE id = NEW.outcome_id AND result_id = NEW.result_id
)
BEGIN SELECT RAISE(ABORT, 'outcome evidence must match its recorded forecast result'); END;

CREATE TABLE forecast_outcome_reviews (
    owner_user_id INTEGER NOT NULL,
    result_id INTEGER NOT NULL,
    revision INTEGER NOT NULL CHECK(revision > 0),
    state TEXT NOT NULL CHECK(state IN ('confirmed','disputed')),
    note TEXT NOT NULL DEFAULT '' CHECK(length(CAST(note AS BLOB)) <= 2048),
    reviewed_at TEXT NOT NULL,
    PRIMARY KEY(owner_user_id, result_id, revision),
    FOREIGN KEY(result_id, owner_user_id) REFERENCES forecast_result_owners(result_id, owner_user_id)
);

CREATE TRIGGER alert_revisions_insert_guard BEFORE INSERT ON price_alert_revisions
WHEN NOT EXISTS (
    SELECT 1 FROM price_alerts a
    WHERE a.id = NEW.alert_id AND a.owner_user_id = NEW.owner_user_id
      AND (NEW.revision = a.revision OR NEW.revision = a.revision + 1)
      AND (NEW.revision != a.revision OR
           (NEW.payload_json = a.payload_json AND NEW.enabled = a.enabled))
)
BEGIN SELECT RAISE(ABORT, 'alert revision must match the current or next CAS snapshot'); END;
CREATE TRIGGER alert_revisions_no_update BEFORE UPDATE ON price_alert_revisions BEGIN SELECT RAISE(ABORT,'alert revisions are immutable'); END;
CREATE TRIGGER alert_revisions_no_delete BEFORE DELETE ON price_alert_revisions BEGIN SELECT RAISE(ABORT,'alert revisions are immutable'); END;
CREATE TRIGGER alert_revisions_no_replace BEFORE INSERT ON price_alert_revisions
WHEN EXISTS(SELECT 1 FROM price_alert_revisions WHERE alert_id=NEW.alert_id AND revision=NEW.revision)
BEGIN SELECT RAISE(ABORT,'alert revisions are immutable'); END;

CREATE TRIGGER alerts_preserve_identity BEFORE UPDATE ON price_alerts
WHEN NEW.id IS NOT OLD.id OR NEW.owner_user_id IS NOT OLD.owner_user_id
  OR NEW.idempotency_key IS NOT OLD.idempotency_key OR NEW.request_sha256 IS NOT OLD.request_sha256
  OR NEW.created_at IS NOT OLD.created_at
BEGIN SELECT RAISE(ABORT,'alert identity is immutable'); END;
CREATE TRIGGER alerts_no_replace BEFORE INSERT ON price_alerts
WHEN EXISTS(SELECT 1 FROM price_alerts WHERE id=NEW.id OR (owner_user_id=NEW.owner_user_id AND idempotency_key=NEW.idempotency_key))
BEGIN SELECT RAISE(ABORT,'alert identity is immutable'); END;
CREATE TRIGGER alerts_revision_link_guard BEFORE UPDATE ON price_alerts
WHEN NEW.revision != OLD.revision OR NEW.payload_json IS NOT OLD.payload_json OR NEW.enabled != OLD.enabled
BEGIN
    SELECT CASE WHEN NEW.revision != OLD.revision + 1 OR NOT EXISTS (
        SELECT 1 FROM price_alert_revisions r
        WHERE r.alert_id=OLD.id AND r.owner_user_id=OLD.owner_user_id AND r.revision=NEW.revision
          AND r.payload_json=NEW.payload_json AND r.enabled=NEW.enabled
    ) THEN RAISE(ABORT,'alert configuration must link to its append-only revision') END;
END;
CREATE TRIGGER alerts_monitor_revision_guard BEFORE UPDATE ON price_alerts
WHEN NEW.monitor_revision != OLD.monitor_revision + 1
BEGIN SELECT RAISE(ABORT,'monitor checkpoint must use its own CAS revision'); END;
CREATE TRIGGER alerts_snapshot_evidence_guard BEFORE UPDATE OF arm_snapshot_generation, arm_snapshot_request_id,
    arm_snapshot_requested_at, arm_snapshot_received_at ON price_alerts
WHEN NEW.arm_snapshot_generation IS NOT NULL AND NOT EXISTS (
    SELECT 1 FROM price_alert_observations o
    WHERE o.request_id=NEW.arm_snapshot_request_id AND o.owner_user_id=NEW.owner_user_id
      AND o.alert_id=NEW.id AND o.generation=NEW.arm_snapshot_generation
      AND o.observation_kind='arm_snapshot' AND o.disposition='initial'
      AND o.requested_at=NEW.arm_snapshot_requested_at AND o.received_at=NEW.arm_snapshot_received_at
)
BEGIN SELECT RAISE(ABORT,'arm snapshot state must link to immutable observation evidence'); END;

CREATE TRIGGER price_observations_insert_guard BEFORE INSERT ON price_alert_observations
WHEN NOT EXISTS (
    SELECT 1 FROM price_alerts a JOIN users u ON u.id=a.owner_user_id
    JOIN monitoring_jobs j ON j.owner_user_id=a.owner_user_id AND j.resource_id=a.id AND j.kind='price'
    WHERE a.id=NEW.alert_id AND a.owner_user_id=NEW.owner_user_id AND u.status='active'
      AND a.enabled=1 AND a.check_state!='triggered' AND a.arm_generation=NEW.generation
      AND a.monitor_revision=NEW.state_revision_before
      AND NEW.state_revision_after=NEW.state_revision_before+1
      AND j.id=NEW.job_id AND j.lease_token=NEW.lease_token
      AND j.lease_until > NEW.accepted_at AND j.active_request_id=NEW.request_id
      AND j.active_requested_at=NEW.requested_at AND j.alert_generation=NEW.generation
      AND j.expected_monitor_revision=NEW.state_revision_before
      AND j.request_kind=NEW.observation_kind
      AND NEW.requested_at <= NEW.received_at AND NEW.received_at <= NEW.accepted_at
      AND NEW.observed_at <= NEW.received_at
      AND (NEW.observation_kind != 'arm_snapshot' OR NEW.requested_at >= a.armed_at)
      AND (NEW.observation_kind != 'tick' OR a.arm_snapshot_generation=a.arm_generation)
      AND (NEW.observation_kind != 'arm_snapshot' OR NOT EXISTS (
          SELECT 1 FROM price_alert_observations old
          WHERE old.alert_id=NEW.alert_id AND old.owner_user_id=NEW.owner_user_id
            AND old.generation=NEW.generation AND old.observation_kind='arm_snapshot'
      ))
)
BEGIN SELECT RAISE(ABORT,'observation requires the current active owner, generation, request and server lease'); END;
CREATE TRIGGER price_observations_no_update BEFORE UPDATE ON price_alert_observations BEGIN SELECT RAISE(ABORT,'price observations are immutable'); END;
CREATE TRIGGER price_observations_no_delete BEFORE DELETE ON price_alert_observations BEGIN SELECT RAISE(ABORT,'price observations are immutable'); END;
CREATE TRIGGER price_observations_no_replace BEFORE INSERT ON price_alert_observations
WHEN EXISTS(SELECT 1 FROM price_alert_observations WHERE request_id=NEW.request_id OR
    (owner_user_id=NEW.owner_user_id AND alert_id=NEW.alert_id AND generation=NEW.generation AND dedupe_sha256=NEW.dedupe_sha256))
BEGIN SELECT RAISE(ABORT,'price observations are immutable'); END;

CREATE TRIGGER monitoring_jobs_identity_guard BEFORE UPDATE ON monitoring_jobs
WHEN NEW.id IS NOT OLD.id OR NEW.owner_user_id IS NOT OLD.owner_user_id
  OR NEW.kind IS NOT OLD.kind OR NEW.resource_id IS NOT OLD.resource_id
BEGIN SELECT RAISE(ABORT,'monitoring job identity is immutable'); END;
CREATE TRIGGER monitoring_jobs_revision_guard BEFORE UPDATE ON monitoring_jobs
WHEN NEW.revision != OLD.revision + 1
BEGIN SELECT RAISE(ABORT,'monitoring job checkpoint must use its CAS revision'); END;
CREATE TRIGGER monitoring_jobs_no_replace BEFORE INSERT ON monitoring_jobs
WHEN EXISTS(SELECT 1 FROM monitoring_jobs WHERE id=NEW.id OR
    (owner_user_id=NEW.owner_user_id AND kind=NEW.kind AND resource_id=NEW.resource_id))
BEGIN SELECT RAISE(ABORT,'monitoring job identity is retained'); END;

CREATE TRIGGER notifications_preserve_evidence BEFORE UPDATE ON notifications
WHEN NEW.id IS NOT OLD.id OR NEW.owner_user_id IS NOT OLD.owner_user_id
  OR NEW.payload_json IS NOT OLD.payload_json OR NEW.dedupe_sha256 IS NOT OLD.dedupe_sha256
  OR NEW.kind IS NOT OLD.kind OR NEW.created_at IS NOT OLD.created_at
BEGIN SELECT RAISE(ABORT,'notification evidence is immutable'); END;
CREATE TRIGGER notifications_read_cas_guard BEFORE UPDATE ON notifications
WHEN NEW.is_read != OLD.is_read OR NEW.revision != OLD.revision
BEGIN
    SELECT CASE WHEN NEW.revision != OLD.revision + 1 OR NOT EXISTS (
        SELECT 1 FROM notification_read_events e
        WHERE e.notification_id=OLD.id AND e.owner_user_id=OLD.owner_user_id
          AND e.revision=NEW.revision AND e.is_read=NEW.is_read
    ) THEN RAISE(ABORT,'notification read state must link to its CAS event') END;
END;
CREATE TRIGGER notifications_no_delete BEFORE DELETE ON notifications BEGIN SELECT RAISE(ABORT,'notification evidence is immutable'); END;
CREATE TRIGGER notifications_no_replace BEFORE INSERT ON notifications
WHEN EXISTS(SELECT 1 FROM notifications WHERE id=NEW.id OR (owner_user_id=NEW.owner_user_id AND dedupe_sha256=NEW.dedupe_sha256))
BEGIN SELECT RAISE(ABORT,'notification evidence is immutable'); END;
CREATE TRIGGER notification_reads_no_update BEFORE UPDATE ON notification_read_events BEGIN SELECT RAISE(ABORT,'notification read events are immutable'); END;
CREATE TRIGGER notification_reads_no_delete BEFORE DELETE ON notification_read_events BEGIN SELECT RAISE(ABORT,'notification read events are immutable'); END;
CREATE TRIGGER notification_reads_no_replace BEFORE INSERT ON notification_read_events
WHEN EXISTS(SELECT 1 FROM notification_read_events WHERE id=NEW.id OR
    (notification_id=NEW.notification_id AND revision=NEW.revision))
BEGIN SELECT RAISE(ABORT,'notification read events are immutable'); END;

CREATE TRIGGER notification_preferences_insert_guard BEFORE INSERT ON notification_preferences
WHEN (NEW.alert_email=1 OR NEW.digest_email=1) AND NOT EXISTS (
    SELECT 1 FROM notification_addresses a
    WHERE a.id=NEW.address_id AND a.owner_user_id=NEW.owner_user_id AND a.verified_at IS NOT NULL
)
BEGIN SELECT RAISE(ABORT,'email notification preferences require a verified owner address'); END;
CREATE TRIGGER notification_preferences_update_guard BEFORE UPDATE ON notification_preferences
WHEN NEW.owner_user_id IS NOT OLD.owner_user_id OR NEW.revision != OLD.revision + 1
  OR ((NEW.alert_email=1 OR NEW.digest_email=1) AND NOT EXISTS (
    SELECT 1 FROM notification_addresses a
    WHERE a.id=NEW.address_id AND a.owner_user_id=NEW.owner_user_id AND a.verified_at IS NOT NULL
  ))
BEGIN SELECT RAISE(ABORT,'notification preferences require CAS and a verified owner address'); END;

CREATE TRIGGER notification_outbox_insert_guard BEFORE INSERT ON notification_outbox
WHEN NOT EXISTS (
    SELECT 1 FROM notifications n
    JOIN users u ON u.id=n.owner_user_id
    JOIN notification_preferences p ON p.owner_user_id=n.owner_user_id
    JOIN notification_addresses a ON a.id=p.address_id AND a.owner_user_id=p.owner_user_id
    JOIN monitoring_jobs j ON j.id=NEW.job_id AND j.owner_user_id=NEW.owner_user_id
    WHERE n.id=NEW.notification_id AND n.owner_user_id=NEW.owner_user_id
      AND n.kind='price_alert' AND NEW.kind='price_alert'
      AND u.status='active' AND p.revision=NEW.preference_revision
      AND p.address_id=NEW.address_id AND p.alert_email=1
      AND a.verified_at IS NOT NULL
      AND j.kind='mail' AND j.resource_id=NEW.id
)
BEGIN SELECT RAISE(ABORT,'outbox enqueue requires an active owner, verified address and current email opt-in'); END;

CREATE TRIGGER notification_outbox_preserve_payload BEFORE UPDATE ON notification_outbox
WHEN NEW.id IS NOT OLD.id OR NEW.owner_user_id IS NOT OLD.owner_user_id
  OR NEW.notification_id IS NOT OLD.notification_id OR NEW.delivery_version IS NOT OLD.delivery_version
  OR NEW.preference_revision IS NOT OLD.preference_revision OR NEW.job_id IS NOT OLD.job_id
  OR NEW.address_id IS NOT OLD.address_id OR NEW.kind IS NOT OLD.kind
  OR NEW.payload_json IS NOT OLD.payload_json OR NEW.dedupe_sha256 IS NOT OLD.dedupe_sha256
  OR NEW.created_at IS NOT OLD.created_at
BEGIN SELECT RAISE(ABORT,'outbox identity and content are immutable'); END;

CREATE TRIGGER notification_outbox_transition_guard BEFORE UPDATE ON notification_outbox
BEGIN
    SELECT CASE WHEN NEW.revision != OLD.revision + 1 OR NEW.transitioned_at < OLD.transitioned_at
      THEN RAISE(ABORT,'outbox transition requires its next revision and monotonic timestamp') END;
    SELECT CASE WHEN NEW.state IN ('claimed','submitting') AND NOT EXISTS (
        SELECT 1 FROM users u
        JOIN notification_preferences p ON p.owner_user_id=u.id
        JOIN notification_addresses a ON a.id=p.address_id AND a.owner_user_id=p.owner_user_id
        WHERE u.id=NEW.owner_user_id AND u.status='active'
          AND p.revision=NEW.preference_revision AND p.address_id=NEW.address_id
          AND p.alert_email=1 AND a.verified_at IS NOT NULL
    ) THEN RAISE(ABORT,'outbox attempt requires its current active verified opt-in') END;
    SELECT CASE WHEN NOT (
        (OLD.state='queued' AND NEW.state='claimed'
         AND NEW.attempts=OLD.attempts+1 AND NEW.attempt_revision=OLD.attempt_revision+1
         AND NEW.attempt_id IS NOT NULL AND NEW.attempt_id IS NOT OLD.attempt_id
         AND NEW.lease_token IS NOT NULL AND NEW.lease_until IS NOT NULL
         AND NEW.submission_started_at IS NULL AND NEW.submitted_at IS NULL AND NEW.completed_at IS NULL
         AND NEW.next_attempt_at=OLD.next_attempt_at AND NEW.failure_code IS NULL)
        OR (OLD.state='claimed' AND NEW.state='claimed'
         AND OLD.lease_until<=NEW.transitioned_at
         AND NEW.attempts=OLD.attempts+1 AND NEW.attempt_revision=OLD.attempt_revision+1
         AND NEW.attempt_id IS NOT NULL AND NEW.attempt_id IS NOT OLD.attempt_id
         AND NEW.lease_token IS NOT NULL AND NEW.lease_token IS NOT OLD.lease_token
         AND NEW.lease_until IS NOT NULL AND NEW.submission_started_at IS NULL
         AND NEW.submitted_at IS NULL AND NEW.completed_at IS NULL
         AND NEW.next_attempt_at=OLD.next_attempt_at AND NEW.failure_code IS NULL)
        OR (OLD.state='claimed' AND NEW.state='submitting'
         AND NEW.attempts=OLD.attempts AND NEW.attempt_revision=OLD.attempt_revision
         AND NEW.attempt_id IS OLD.attempt_id AND NEW.lease_token IS OLD.lease_token
         AND NEW.lease_until IS OLD.lease_until
         AND NEW.submission_started_at=NEW.transitioned_at
         AND NEW.submission_started_at<NEW.lease_until
         AND NEW.submitted_at IS NULL AND NEW.completed_at IS NULL AND NEW.failure_code IS NULL)
        OR (OLD.state='claimed' AND NEW.state='queued'
         AND NEW.attempts=OLD.attempts AND NEW.attempt_revision=OLD.attempt_revision
         AND NEW.attempt_id IS OLD.attempt_id AND NEW.lease_token IS NULL AND NEW.lease_until IS NULL
         AND NEW.submission_started_at IS NULL AND NEW.submitted_at IS NULL AND NEW.completed_at IS NULL
         AND NEW.next_attempt_at>=NEW.transitioned_at AND NEW.failure_code IS NOT NULL)
        OR (OLD.state='claimed' AND NEW.state='failed'
         AND NEW.attempts=OLD.attempts AND NEW.attempt_revision=OLD.attempt_revision
         AND NEW.attempt_id IS OLD.attempt_id AND NEW.lease_token IS NULL AND NEW.lease_until IS NULL
         AND NEW.submission_started_at IS NULL AND NEW.submitted_at IS NULL
         AND NEW.completed_at=NEW.transitioned_at AND NEW.failure_code IS NOT NULL)
        OR (OLD.state='submitting' AND NEW.state='accepted'
         AND NEW.attempts=OLD.attempts AND NEW.attempt_revision=OLD.attempt_revision
         AND NEW.attempt_id IS OLD.attempt_id AND NEW.lease_token IS NULL AND NEW.lease_until IS NULL
         AND NEW.submission_started_at IS OLD.submission_started_at
         AND NEW.submitted_at=NEW.transitioned_at AND NEW.completed_at=NEW.transitioned_at
         AND NEW.failure_code IS NULL)
        OR (OLD.state='submitting' AND NEW.state IN ('failed','uncertain')
         AND NEW.attempts=OLD.attempts AND NEW.attempt_revision=OLD.attempt_revision
         AND NEW.attempt_id IS OLD.attempt_id AND NEW.lease_token IS NULL AND NEW.lease_until IS NULL
         AND NEW.submission_started_at IS OLD.submission_started_at
         AND NEW.submitted_at IS NULL AND NEW.completed_at=NEW.transitioned_at
         AND NEW.failure_code IS NOT NULL)
    ) THEN RAISE(ABORT,'outbox state transition is not permitted') END;
END;

CREATE TRIGGER notification_outbox_attempt_log AFTER UPDATE ON notification_outbox
WHEN NEW.state != OLD.state OR NEW.attempt_revision != OLD.attempt_revision
BEGIN
    INSERT INTO notification_outbox_attempts(
        outbox_id,owner_user_id,attempt_id,attempt_revision,revision,event_kind,occurred_at,failure_code
    ) VALUES (
        NEW.id,NEW.owner_user_id,NEW.attempt_id,NEW.attempt_revision,NEW.revision,
        CASE
            WHEN NEW.state='claimed' THEN 'claimed'
            WHEN NEW.state='submitting' THEN 'submission_started'
            WHEN NEW.state='queued' THEN 'retry_scheduled'
            WHEN NEW.state='accepted' THEN 'accepted'
            WHEN NEW.state='uncertain' THEN 'uncertain'
            WHEN NEW.state='failed' AND OLD.state='claimed' THEN 'pre_submission_failed'
            ELSE 'failed'
        END,
        NEW.transitioned_at,NEW.failure_code
    );
END;

CREATE TRIGGER notification_outbox_attempts_insert_guard BEFORE INSERT ON notification_outbox_attempts
WHEN NOT EXISTS (
    SELECT 1 FROM notification_outbox o
    WHERE o.id=NEW.outbox_id AND o.owner_user_id=NEW.owner_user_id
      AND o.attempt_id=NEW.attempt_id AND o.attempt_revision=NEW.attempt_revision
      AND o.revision=NEW.revision AND o.transitioned_at=NEW.occurred_at
      AND o.failure_code IS NEW.failure_code
      AND ((NEW.event_kind='claimed' AND o.state='claimed')
        OR (NEW.event_kind='submission_started' AND o.state='submitting')
        OR (NEW.event_kind='retry_scheduled' AND o.state='queued')
        OR (NEW.event_kind='pre_submission_failed' AND o.state='failed' AND o.submission_started_at IS NULL)
        OR (NEW.event_kind='accepted' AND o.state='accepted')
        OR (NEW.event_kind='failed' AND o.state='failed' AND o.submission_started_at IS NOT NULL)
        OR (NEW.event_kind='uncertain' AND o.state='uncertain'))
)
BEGIN SELECT RAISE(ABORT,'outbox attempt event must match the typed state revision'); END;
CREATE TRIGGER notification_outbox_attempts_no_update BEFORE UPDATE ON notification_outbox_attempts BEGIN SELECT RAISE(ABORT,'outbox attempt events are immutable'); END;
CREATE TRIGGER notification_outbox_attempts_no_delete BEFORE DELETE ON notification_outbox_attempts BEGIN SELECT RAISE(ABORT,'outbox attempt events are immutable'); END;
CREATE TRIGGER notification_outbox_attempts_no_replace BEFORE INSERT ON notification_outbox_attempts
WHEN EXISTS(SELECT 1 FROM notification_outbox_attempts WHERE event_id=NEW.event_id OR (outbox_id=NEW.outbox_id AND revision=NEW.revision))
BEGIN SELECT RAISE(ABORT,'outbox attempt events are immutable'); END;

CREATE TRIGGER notification_outbox_no_delete BEFORE DELETE ON notification_outbox BEGIN SELECT RAISE(ABORT,'outbox receipts are retained'); END;
CREATE TRIGGER notification_outbox_no_replace BEFORE INSERT ON notification_outbox
WHEN EXISTS(SELECT 1 FROM notification_outbox WHERE id=NEW.id OR
    (owner_user_id=NEW.owner_user_id AND dedupe_sha256=NEW.dedupe_sha256) OR
    (notification_id=NEW.notification_id AND delivery_version=NEW.delivery_version))
BEGIN SELECT RAISE(ABORT,'outbox receipts are retained'); END;

CREATE TRIGGER collected_outcomes_no_update BEFORE UPDATE ON collected_outcome_evidence BEGIN SELECT RAISE(ABORT,'outcome evidence is immutable'); END;
CREATE TRIGGER collected_outcomes_no_delete BEFORE DELETE ON collected_outcome_evidence BEGIN SELECT RAISE(ABORT,'outcome evidence is immutable'); END;
CREATE TRIGGER collected_outcomes_no_replace BEFORE INSERT ON collected_outcome_evidence
WHEN EXISTS(SELECT 1 FROM collected_outcome_evidence WHERE outcome_id=NEW.outcome_id)
BEGIN SELECT RAISE(ABORT,'outcome evidence is immutable'); END;
CREATE TRIGGER outcome_reviews_no_update BEFORE UPDATE ON forecast_outcome_reviews BEGIN SELECT RAISE(ABORT,'outcome reviews are immutable'); END;
CREATE TRIGGER outcome_reviews_no_delete BEFORE DELETE ON forecast_outcome_reviews BEGIN SELECT RAISE(ABORT,'outcome reviews are immutable'); END;
CREATE TRIGGER outcome_reviews_no_replace BEFORE INSERT ON forecast_outcome_reviews
WHEN EXISTS(SELECT 1 FROM forecast_outcome_reviews WHERE owner_user_id=NEW.owner_user_id AND result_id=NEW.result_id AND revision=NEW.revision)
BEGIN SELECT RAISE(ABORT,'outcome reviews are immutable'); END;
CREATE TRIGGER addresses_preserve_identity BEFORE UPDATE ON notification_addresses
WHEN NEW.id IS NOT OLD.id OR NEW.owner_user_id IS NOT OLD.owner_user_id
  OR NEW.address IS NOT OLD.address OR NEW.created_at IS NOT OLD.created_at
BEGIN SELECT RAISE(ABORT,'verified address identity is immutable'); END;
CREATE TRIGGER addresses_no_replace BEFORE INSERT ON notification_addresses
WHEN EXISTS(SELECT 1 FROM notification_addresses WHERE id=NEW.id)
BEGIN SELECT RAISE(ABORT,'verified address identity is immutable'); END;
