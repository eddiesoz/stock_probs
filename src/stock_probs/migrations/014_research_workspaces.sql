-- Research revisions and dated comparison evidence remain immutable within owner boundaries.
CREATE TABLE research_theses (
    id TEXT PRIMARY KEY CHECK(length(id) = 36),
    owner_user_id INTEGER NOT NULL REFERENCES users(id),
    idempotency_key TEXT NOT NULL CHECK(length(idempotency_key) = 36),
    request_sha256 TEXT NOT NULL CHECK(length(request_sha256) = 64),
    revision INTEGER NOT NULL CHECK(revision > 0),
    payload_json TEXT NOT NULL CHECK(length(CAST(payload_json AS BLOB)) <= 32768),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(id, owner_user_id),
    UNIQUE(owner_user_id, idempotency_key)
);
CREATE INDEX research_theses_owner ON research_theses(owner_user_id, updated_at DESC, id);
CREATE TABLE research_thesis_revisions (
    thesis_id TEXT NOT NULL,
    owner_user_id INTEGER NOT NULL,
    revision INTEGER NOT NULL CHECK(revision > 0),
    payload_json TEXT NOT NULL CHECK(length(CAST(payload_json AS BLOB)) <= 32768),
    recorded_at TEXT NOT NULL,
    PRIMARY KEY(thesis_id, revision),
    FOREIGN KEY(thesis_id, owner_user_id) REFERENCES research_theses(id, owner_user_id)
);
CREATE TRIGGER research_revisions_no_update BEFORE UPDATE ON research_thesis_revisions
BEGIN SELECT RAISE(ABORT, 'thesis revisions are append-only'); END;
CREATE TRIGGER research_revisions_no_delete BEFORE DELETE ON research_thesis_revisions
BEGIN SELECT RAISE(ABORT, 'thesis revisions are append-only'); END;
CREATE TRIGGER research_revisions_no_replace BEFORE INSERT ON research_thesis_revisions
WHEN EXISTS(SELECT 1 FROM research_thesis_revisions WHERE thesis_id = NEW.thesis_id AND revision = NEW.revision)
BEGIN SELECT RAISE(ABORT, 'thesis revisions are append-only'); END;
CREATE TRIGGER research_theses_no_delete BEFORE DELETE ON research_theses
BEGIN SELECT RAISE(ABORT, 'thesis history must be retained'); END;
CREATE TRIGGER research_theses_no_replace BEFORE INSERT ON research_theses
WHEN EXISTS(SELECT 1 FROM research_theses WHERE id = NEW.id OR (owner_user_id = NEW.owner_user_id AND idempotency_key = NEW.idempotency_key))
BEGIN SELECT RAISE(ABORT, 'thesis history must be retained'); END;
CREATE TRIGGER research_theses_owner_immutable BEFORE UPDATE ON research_theses
WHEN NEW.owner_user_id != OLD.owner_user_id OR NEW.id != OLD.id OR NEW.created_at != OLD.created_at OR NEW.idempotency_key != OLD.idempotency_key OR NEW.request_sha256 != OLD.request_sha256
BEGIN SELECT RAISE(ABORT, 'thesis identity is immutable'); END;
CREATE TABLE research_comparisons (
    id TEXT PRIMARY KEY CHECK(length(id) = 36),
    owner_user_id INTEGER NOT NULL REFERENCES users(id),
    idempotency_key TEXT NOT NULL CHECK(length(idempotency_key) = 36),
    payload_json TEXT NOT NULL CHECK(length(CAST(payload_json AS BLOB)) <= 262144),
    created_at TEXT NOT NULL,
    UNIQUE(owner_user_id, idempotency_key)
);
CREATE INDEX research_comparisons_owner ON research_comparisons(owner_user_id, created_at DESC, id);
CREATE TRIGGER research_comparisons_no_update BEFORE UPDATE ON research_comparisons
BEGIN SELECT RAISE(ABORT, 'comparison snapshots are immutable'); END;
CREATE TRIGGER research_comparisons_no_delete BEFORE DELETE ON research_comparisons
BEGIN SELECT RAISE(ABORT, 'comparison snapshots are immutable'); END;
CREATE TRIGGER research_comparisons_no_replace BEFORE INSERT ON research_comparisons
WHEN EXISTS(SELECT 1 FROM research_comparisons WHERE id = NEW.id OR (owner_user_id = NEW.owner_user_id AND idempotency_key = NEW.idempotency_key))
BEGIN SELECT RAISE(ABORT, 'comparison snapshots are immutable'); END;
