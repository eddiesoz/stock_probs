-- Assistant history belongs to the authenticated workspace owner. Runtime session state and
-- provider credentials stay outside this canonical store.
CREATE TABLE assistant_conversations (
    id TEXT PRIMARY KEY CHECK (length(id) = 36),
    user_id INTEGER NOT NULL REFERENCES users(id),
    title TEXT NOT NULL CHECK (length(trim(title)) BETWEEN 1 AND 160),
    context_json TEXT NOT NULL CHECK (length(CAST(context_json AS BLOB)) <= 8192),
    context_version TEXT NOT NULL CHECK (length(context_version) = 64),
    revision INTEGER NOT NULL DEFAULT 1 CHECK (revision > 0),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK (updated_at >= created_at),
    UNIQUE (id, user_id)
);
CREATE INDEX idx_assistant_conversations_owner
    ON assistant_conversations(user_id, updated_at DESC, id DESC);

CREATE TABLE assistant_turns (
    id TEXT PRIMARY KEY CHECK (length(id) = 36),
    conversation_id TEXT NOT NULL,
    user_id INTEGER NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN ('queued', 'running', 'completed', 'cancelled', 'failed', 'timed_out')
    ),
    model_id TEXT NOT NULL CHECK (length(trim(model_id)) BETWEEN 1 AND 160),
    policy_version TEXT NOT NULL CHECK (length(trim(policy_version)) BETWEEN 1 AND 80),
    context_json TEXT NOT NULL CHECK (length(CAST(context_json AS BLOB)) <= 8192),
    context_version TEXT NOT NULL CHECK (length(context_version) = 64),
    created_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    error_code TEXT CHECK (error_code IS NULL OR length(trim(error_code)) BETWEEN 1 AND 80),
    CHECK (started_at IS NULL OR started_at >= created_at),
    CHECK (completed_at IS NULL OR completed_at >= created_at),
    UNIQUE (id, conversation_id, user_id),
    FOREIGN KEY (conversation_id, user_id)
        REFERENCES assistant_conversations(id, user_id)
);
CREATE INDEX idx_assistant_turns_conversation
    ON assistant_turns(conversation_id, user_id, created_at, id);

CREATE TABLE assistant_messages (
    id TEXT PRIMARY KEY CHECK (length(id) = 36),
    conversation_id TEXT NOT NULL,
    turn_id TEXT NOT NULL,
    user_id INTEGER NOT NULL,
    sequence INTEGER NOT NULL CHECK (sequence > 0),
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content TEXT NOT NULL CHECK (length(CAST(content AS BLOB)) <= 65536),
    created_at TEXT NOT NULL,
    UNIQUE (conversation_id, sequence),
    UNIQUE (id, conversation_id, user_id),
    FOREIGN KEY (conversation_id, user_id)
        REFERENCES assistant_conversations(id, user_id),
    FOREIGN KEY (turn_id, conversation_id, user_id)
        REFERENCES assistant_turns(id, conversation_id, user_id)
);
CREATE INDEX idx_assistant_messages_conversation
    ON assistant_messages(conversation_id, user_id, sequence);

CREATE TABLE assistant_events (
    conversation_id TEXT NOT NULL,
    turn_id TEXT NOT NULL,
    user_id INTEGER NOT NULL,
    sequence INTEGER NOT NULL CHECK (sequence > 0),
    event_type TEXT NOT NULL CHECK (
        event_type IN (
            'meta', 'token', 'tool', 'source', 'proposed_action',
            'private_context_preview', 'webfetch_preview', 'complete', 'error'
        )
    ),
    payload_json TEXT NOT NULL CHECK (length(CAST(payload_json AS BLOB)) <= 16384),
    created_at TEXT NOT NULL,
    PRIMARY KEY (turn_id, sequence),
    FOREIGN KEY (conversation_id, user_id)
        REFERENCES assistant_conversations(id, user_id),
    FOREIGN KEY (turn_id, conversation_id, user_id)
        REFERENCES assistant_turns(id, conversation_id, user_id)
);
CREATE INDEX idx_assistant_events_owner
    ON assistant_events(user_id, conversation_id, turn_id, sequence);

CREATE TABLE assistant_sources (
    id TEXT PRIMARY KEY CHECK (length(id) = 36),
    conversation_id TEXT NOT NULL,
    turn_id TEXT NOT NULL,
    user_id INTEGER NOT NULL,
    source_type TEXT NOT NULL CHECK (length(trim(source_type)) BETWEEN 1 AND 40),
    title TEXT NOT NULL CHECK (length(trim(title)) BETWEEN 1 AND 500),
    url TEXT CHECK (url IS NULL OR length(url) <= 2048),
    source_ref TEXT CHECK (source_ref IS NULL OR length(source_ref) <= 256),
    retrieved_at TEXT NOT NULL,
    as_of TEXT,
    metadata_json TEXT NOT NULL CHECK (length(CAST(metadata_json AS BLOB)) <= 4096),
    FOREIGN KEY (conversation_id, user_id)
        REFERENCES assistant_conversations(id, user_id),
    FOREIGN KEY (turn_id, conversation_id, user_id)
        REFERENCES assistant_turns(id, conversation_id, user_id)
);
CREATE INDEX idx_assistant_sources_turn
    ON assistant_sources(turn_id, user_id, id);

CREATE TABLE assistant_proposed_actions (
    id TEXT PRIMARY KEY CHECK (length(id) = 36),
    conversation_id TEXT NOT NULL,
    turn_id TEXT NOT NULL,
    user_id INTEGER NOT NULL,
    session_id TEXT NOT NULL CHECK (length(session_id) BETWEEN 16 AND 128),
    context_version TEXT NOT NULL
        CHECK (length(context_version) = 64 AND context_version NOT GLOB '*[^0-9a-f]*'),
    action_type TEXT NOT NULL CHECK (length(trim(action_type)) BETWEEN 1 AND 80),
    payload_json TEXT NOT NULL CHECK (length(CAST(payload_json AS BLOB)) <= 8192),
    action_version INTEGER NOT NULL CHECK (action_version > 0),
    confirmation_phrase_hash TEXT NOT NULL
        CHECK (length(confirmation_phrase_hash) = 64 AND confirmation_phrase_hash NOT GLOB '*[^0-9a-f]*'),
    status TEXT NOT NULL CHECK (
        status IN ('pending', 'executing', 'applied', 'handed_off', 'denied', 'expired', 'failed', 'unknown')
    ),
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    completed_at TEXT,
    FOREIGN KEY (conversation_id, user_id)
        REFERENCES assistant_conversations(id, user_id),
    FOREIGN KEY (turn_id, conversation_id, user_id)
        REFERENCES assistant_turns(id, conversation_id, user_id)
);
CREATE INDEX idx_assistant_actions_owner
    ON assistant_proposed_actions(user_id, conversation_id, status, expires_at);

CREATE TABLE assistant_action_receipts (
    id TEXT PRIMARY KEY CHECK (length(id) = 36),
    action_id TEXT NOT NULL UNIQUE REFERENCES assistant_proposed_actions(id),
    conversation_id TEXT NOT NULL,
    user_id INTEGER NOT NULL,
    outcome TEXT NOT NULL CHECK (
        outcome IN ('executing', 'applied', 'handed_off', 'denied', 'failed', 'unknown')
    ),
    result_json TEXT NOT NULL CHECK (length(CAST(result_json AS BLOB)) <= 4096),
    created_at TEXT NOT NULL,
    FOREIGN KEY (conversation_id, user_id)
        REFERENCES assistant_conversations(id, user_id)
);

CREATE TABLE assistant_execution_leases (
    execution_id TEXT PRIMARY KEY CHECK (length(execution_id) = 32),
    conversation_id TEXT NOT NULL,
    turn_id TEXT NOT NULL,
    user_id INTEGER NOT NULL,
    session_id TEXT NOT NULL CHECK (length(session_id) BETWEEN 16 AND 128),
    session_token_hash TEXT NOT NULL
        CHECK (length(session_token_hash) = 64 AND session_token_hash NOT GLOB '*[^0-9a-f]*'),
    capability_hash TEXT NOT NULL
        CHECK (length(capability_hash) = 64 AND capability_hash NOT GLOB '*[^0-9a-f]*'),
    app_id TEXT NOT NULL CHECK (app_id = 'signal-ledger'),
    context_version TEXT NOT NULL CHECK (length(context_version) = 64),
    private_read_seen INTEGER NOT NULL DEFAULT 0 CHECK (private_read_seen IN (0, 1)),
    tool_calls INTEGER NOT NULL DEFAULT 0 CHECK (tool_calls BETWEEN 0 AND 8),
    status TEXT NOT NULL CHECK (status IN ('active', 'closed', 'revoked')),
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    closed_at TEXT,
    UNIQUE (execution_id, user_id),
    FOREIGN KEY (conversation_id, user_id)
        REFERENCES assistant_conversations(id, user_id),
    FOREIGN KEY (turn_id, conversation_id, user_id)
        REFERENCES assistant_turns(id, conversation_id, user_id)
);
CREATE INDEX idx_assistant_execution_leases_owner
    ON assistant_execution_leases(user_id, status, expires_at);

CREATE TABLE assistant_search_previews (
    id TEXT PRIMARY KEY CHECK (length(id) = 36),
    conversation_id TEXT NOT NULL,
    turn_id TEXT NOT NULL,
    user_id INTEGER NOT NULL,
    execution_id TEXT NOT NULL,
    query_text TEXT NOT NULL CHECK (length(CAST(query_text AS BLOB)) BETWEEN 1 AND 1000),
    context_version TEXT NOT NULL CHECK (length(context_version) = 64),
    confirmation_phrase_hash TEXT NOT NULL
        CHECK (length(confirmation_phrase_hash) = 64 AND confirmation_phrase_hash NOT GLOB '*[^0-9a-f]*'),
    status TEXT NOT NULL CHECK (status IN ('pending', 'approved', 'denied', 'expired')),
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    completed_at TEXT,
    FOREIGN KEY (conversation_id, user_id)
        REFERENCES assistant_conversations(id, user_id),
    FOREIGN KEY (turn_id, conversation_id, user_id)
        REFERENCES assistant_turns(id, conversation_id, user_id),
    FOREIGN KEY (execution_id, user_id)
        REFERENCES assistant_execution_leases(execution_id, user_id)
);

CREATE TABLE assistant_model_consents (
    id TEXT PRIMARY KEY CHECK (length(id) = 36),
    user_id INTEGER NOT NULL REFERENCES users(id),
    model_id TEXT NOT NULL CHECK (length(trim(model_id)) BETWEEN 1 AND 160),
    policy_version TEXT NOT NULL CHECK (length(trim(policy_version)) BETWEEN 1 AND 80),
    accepted_terms INTEGER NOT NULL CHECK (accepted_terms IN (0, 1)),
    data_collection_opt_in INTEGER NOT NULL CHECK (data_collection_opt_in IN (0, 1)),
    recorded_at TEXT NOT NULL,
    CHECK (accepted_terms = 1 OR data_collection_opt_in = 0)
);
CREATE INDEX idx_assistant_consents_owner
    ON assistant_model_consents(user_id, model_id, policy_version, id DESC);

CREATE TABLE assistant_conversation_deletions (
    conversation_id TEXT PRIMARY KEY CHECK (length(conversation_id) = 36),
    user_id INTEGER NOT NULL REFERENCES users(id),
    content_digest TEXT NOT NULL
        CHECK (length(content_digest) = 64 AND content_digest NOT GLOB '*[^0-9a-f]*'),
    deleted_bytes INTEGER NOT NULL CHECK (deleted_bytes >= 0),
    deleted_at TEXT NOT NULL
);

-- A chat's durable content may be purged only after the owner deletion receipt is recorded.
CREATE TRIGGER assistant_conversations_delete_guard BEFORE DELETE ON assistant_conversations
WHEN NOT EXISTS (
    SELECT 1 FROM assistant_conversation_deletions AS deletion
    WHERE deletion.conversation_id = OLD.id AND deletion.user_id = OLD.user_id
)
BEGIN SELECT RAISE(ABORT, 'assistant conversation deletion requires an owner tombstone'); END;

CREATE TRIGGER assistant_turns_delete_guard BEFORE DELETE ON assistant_turns
WHEN NOT EXISTS (
    SELECT 1 FROM assistant_conversation_deletions AS deletion
    WHERE deletion.conversation_id = OLD.conversation_id AND deletion.user_id = OLD.user_id
)
BEGIN SELECT RAISE(ABORT, 'assistant turn deletion requires an owner tombstone'); END;
CREATE TRIGGER assistant_messages_delete_guard BEFORE DELETE ON assistant_messages
WHEN NOT EXISTS (
    SELECT 1 FROM assistant_conversation_deletions AS deletion
    WHERE deletion.conversation_id = OLD.conversation_id AND deletion.user_id = OLD.user_id
)
BEGIN SELECT RAISE(ABORT, 'assistant message deletion requires an owner tombstone'); END;
CREATE TRIGGER assistant_events_delete_guard BEFORE DELETE ON assistant_events
WHEN NOT EXISTS (
    SELECT 1 FROM assistant_conversation_deletions AS deletion
    WHERE deletion.conversation_id = OLD.conversation_id AND deletion.user_id = OLD.user_id
)
BEGIN SELECT RAISE(ABORT, 'assistant event deletion requires an owner tombstone'); END;
CREATE TRIGGER assistant_sources_delete_guard BEFORE DELETE ON assistant_sources
WHEN NOT EXISTS (
    SELECT 1 FROM assistant_conversation_deletions AS deletion
    WHERE deletion.conversation_id = OLD.conversation_id AND deletion.user_id = OLD.user_id
)
BEGIN SELECT RAISE(ABORT, 'assistant source deletion requires an owner tombstone'); END;
CREATE TRIGGER assistant_actions_delete_guard BEFORE DELETE ON assistant_proposed_actions
WHEN NOT EXISTS (
    SELECT 1 FROM assistant_conversation_deletions AS deletion
    WHERE deletion.conversation_id = OLD.conversation_id AND deletion.user_id = OLD.user_id
)
BEGIN SELECT RAISE(ABORT, 'assistant action deletion requires an owner tombstone'); END;
CREATE TRIGGER assistant_action_receipts_delete_guard BEFORE DELETE ON assistant_action_receipts
WHEN NOT EXISTS (
    SELECT 1 FROM assistant_conversation_deletions AS deletion
    WHERE deletion.conversation_id = OLD.conversation_id AND deletion.user_id = OLD.user_id
)
BEGIN SELECT RAISE(ABORT, 'assistant receipt deletion requires an owner tombstone'); END;
CREATE TRIGGER assistant_leases_delete_guard BEFORE DELETE ON assistant_execution_leases
WHEN NOT EXISTS (
    SELECT 1 FROM assistant_conversation_deletions AS deletion
    WHERE deletion.conversation_id = OLD.conversation_id AND deletion.user_id = OLD.user_id
)
BEGIN SELECT RAISE(ABORT, 'assistant lease deletion requires an owner tombstone'); END;
CREATE TRIGGER assistant_previews_delete_guard BEFORE DELETE ON assistant_search_previews
WHEN NOT EXISTS (
    SELECT 1 FROM assistant_conversation_deletions AS deletion
    WHERE deletion.conversation_id = OLD.conversation_id AND deletion.user_id = OLD.user_id
)
BEGIN SELECT RAISE(ABORT, 'assistant preview deletion requires an owner tombstone'); END;

-- Transcript records remain append-only. A claimed action has one reserved executing receipt;
-- it may transition once to a terminal receipt, after which it is immutable.
CREATE TRIGGER assistant_messages_update_guard BEFORE UPDATE ON assistant_messages
BEGIN SELECT RAISE(ABORT, 'assistant messages are immutable'); END;
CREATE TRIGGER assistant_events_update_guard BEFORE UPDATE ON assistant_events
BEGIN SELECT RAISE(ABORT, 'assistant events are immutable'); END;
CREATE TRIGGER assistant_sources_update_guard BEFORE UPDATE ON assistant_sources
BEGIN SELECT RAISE(ABORT, 'assistant sources are immutable'); END;
CREATE TRIGGER assistant_action_receipts_update_guard BEFORE UPDATE ON assistant_action_receipts
WHEN NOT (
    OLD.outcome = 'executing'
    AND NEW.outcome IN ('applied', 'handed_off', 'denied', 'failed', 'unknown')
    AND NEW.id = OLD.id
    AND NEW.action_id = OLD.action_id
    AND NEW.conversation_id = OLD.conversation_id
    AND NEW.user_id = OLD.user_id
)
BEGIN SELECT RAISE(ABORT, 'assistant action receipt can only finalize its reservation'); END;
CREATE TRIGGER assistant_consents_update_guard BEFORE UPDATE ON assistant_model_consents
BEGIN SELECT RAISE(ABORT, 'assistant model consents are append-only'); END;
CREATE TRIGGER assistant_consents_delete_guard BEFORE DELETE ON assistant_model_consents
BEGIN SELECT RAISE(ABORT, 'assistant model consents are append-only'); END;
CREATE TRIGGER assistant_deletions_update_guard BEFORE UPDATE ON assistant_conversation_deletions
BEGIN SELECT RAISE(ABORT, 'assistant deletion receipts are immutable'); END;
CREATE TRIGGER assistant_deletions_delete_guard BEFORE DELETE ON assistant_conversation_deletions
BEGIN SELECT RAISE(ABORT, 'assistant deletion receipts are immutable'); END;

CREATE TRIGGER assistant_messages_insert_conflict BEFORE INSERT ON assistant_messages
WHEN EXISTS (SELECT 1 FROM assistant_messages WHERE id = NEW.id)
 OR EXISTS (
     SELECT 1 FROM assistant_messages
     WHERE conversation_id = NEW.conversation_id AND sequence = NEW.sequence
 )
BEGIN SELECT RAISE(ABORT, 'assistant messages are immutable'); END;
CREATE TRIGGER assistant_events_insert_conflict BEFORE INSERT ON assistant_events
WHEN EXISTS (
    SELECT 1 FROM assistant_events
    WHERE turn_id = NEW.turn_id AND sequence = NEW.sequence
)
BEGIN SELECT RAISE(ABORT, 'assistant events are immutable'); END;
CREATE TRIGGER assistant_sources_insert_conflict BEFORE INSERT ON assistant_sources
WHEN EXISTS (SELECT 1 FROM assistant_sources WHERE id = NEW.id)
BEGIN SELECT RAISE(ABORT, 'assistant sources are immutable'); END;
CREATE TRIGGER assistant_action_receipts_insert_conflict BEFORE INSERT ON assistant_action_receipts
WHEN EXISTS (SELECT 1 FROM assistant_action_receipts WHERE id = NEW.id)
 OR EXISTS (SELECT 1 FROM assistant_action_receipts WHERE action_id = NEW.action_id)
BEGIN SELECT RAISE(ABORT, 'assistant action receipts are immutable'); END;
CREATE TRIGGER assistant_consents_insert_conflict BEFORE INSERT ON assistant_model_consents
WHEN EXISTS (SELECT 1 FROM assistant_model_consents WHERE id = NEW.id)
BEGIN SELECT RAISE(ABORT, 'assistant model consents are append-only'); END;
CREATE TRIGGER assistant_deletions_insert_conflict BEFORE INSERT ON assistant_conversation_deletions
WHEN EXISTS (SELECT 1 FROM assistant_conversation_deletions WHERE conversation_id = NEW.conversation_id)
BEGIN SELECT RAISE(ABORT, 'assistant deletion receipts are immutable'); END;

CREATE TRIGGER assistant_turn_status_guard BEFORE UPDATE OF status ON assistant_turns
WHEN NOT (
    (OLD.status = 'queued' AND NEW.status IN ('running', 'cancelled', 'failed', 'timed_out'))
    OR (OLD.status = 'running' AND NEW.status IN ('completed', 'cancelled', 'failed', 'timed_out'))
    OR (OLD.status = NEW.status)
)
BEGIN SELECT RAISE(ABORT, 'invalid assistant turn status transition'); END;

CREATE TRIGGER assistant_action_identity_guard
BEFORE UPDATE OF id, conversation_id, turn_id, user_id, action_type, payload_json,
                 action_version, confirmation_phrase_hash, expires_at, created_at
ON assistant_proposed_actions
BEGIN SELECT RAISE(ABORT, 'assistant proposed action identity is immutable'); END;
CREATE TRIGGER assistant_action_status_guard BEFORE UPDATE OF status ON assistant_proposed_actions
WHEN NOT (
    (OLD.status = 'pending' AND NEW.status IN ('executing', 'denied', 'expired'))
    OR (OLD.status = 'executing' AND NEW.status IN ('applied', 'handed_off', 'failed', 'unknown'))
    OR (OLD.status = NEW.status)
)
BEGIN SELECT RAISE(ABORT, 'invalid assistant action status transition'); END;

CREATE TRIGGER assistant_lease_identity_guard
BEFORE UPDATE OF execution_id, conversation_id, turn_id, user_id, session_id,
                 session_token_hash, capability_hash, app_id, context_version,
                 created_at, expires_at
ON assistant_execution_leases
BEGIN SELECT RAISE(ABORT, 'assistant execution identity is immutable'); END;
CREATE TRIGGER assistant_lease_counter_guard BEFORE UPDATE OF tool_calls ON assistant_execution_leases
WHEN NEW.tool_calls != OLD.tool_calls + 1 OR NEW.tool_calls > 8
BEGIN SELECT RAISE(ABORT, 'assistant tool call count is bounded'); END;

CREATE TRIGGER assistant_search_preview_identity_guard
BEFORE UPDATE OF id, conversation_id, turn_id, user_id, execution_id, query_text,
                 context_version, confirmation_phrase_hash, expires_at, created_at
ON assistant_search_previews
BEGIN SELECT RAISE(ABORT, 'assistant search preview identity is immutable'); END;
CREATE TRIGGER assistant_search_preview_status_guard
BEFORE UPDATE OF status ON assistant_search_previews
WHEN NOT (
    (OLD.status = 'pending' AND NEW.status IN ('approved', 'denied', 'expired'))
    OR (OLD.status = NEW.status)
)
BEGIN SELECT RAISE(ABORT, 'invalid assistant search preview status transition'); END;
