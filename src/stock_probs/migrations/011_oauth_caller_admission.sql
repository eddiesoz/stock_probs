-- OAuth states are short-lived browser transactions. Old rows cannot be assigned to an
-- authenticated ingress caller, so expire only these pending transactions before adding the key.
DELETE FROM oauth_states;

ALTER TABLE oauth_states
ADD COLUMN caller_key_hash TEXT NOT NULL DEFAULT
    '0000000000000000000000000000000000000000000000000000000000000000'
    CHECK (length(caller_key_hash) = 64 AND caller_key_hash NOT GLOB '*[^0-9a-f]*');

CREATE INDEX idx_oauth_states_caller_pending
ON oauth_states(caller_key_hash, consumed_at, expires_at);
