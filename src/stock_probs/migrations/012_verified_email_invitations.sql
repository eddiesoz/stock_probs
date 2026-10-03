-- Email invites are bound by a keyed digest until GitHub proves the verified mailbox.
-- Existing invitations retain their numeric GitHub identity and every original field.
ALTER TABLE invitations RENAME TO invitations_before_email_binding;

CREATE TABLE invitations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    github_user_id INTEGER CHECK (github_user_id IS NULL OR github_user_id > 0),
    github_login TEXT,
    email_hash TEXT CHECK (
        email_hash IS NULL OR
        (length(email_hash) = 64 AND email_hash NOT GLOB '*[^0-9a-f]*')
    ),
    token_hash TEXT NOT NULL UNIQUE
        CHECK (length(token_hash) = 64 AND token_hash NOT GLOB '*[^0-9a-f]*'),
    invited_by_user_id INTEGER NOT NULL REFERENCES users(id),
    expires_at TEXT NOT NULL,
    used_at TEXT,
    created_at TEXT NOT NULL,
    CHECK (
        (github_user_id IS NOT NULL AND
         (email_hash IS NULL OR used_at IS NOT NULL)) OR
        (github_user_id IS NULL AND email_hash IS NOT NULL)
    ),
    CHECK (github_user_id IS NOT NULL OR github_login IS NULL),
    CHECK (used_at IS NULL OR used_at >= created_at)
);

INSERT INTO invitations
    (id, github_user_id, github_login, email_hash, token_hash, invited_by_user_id,
     expires_at, used_at, created_at)
SELECT id, github_user_id, github_login, NULL, token_hash, invited_by_user_id,
       expires_at, used_at, created_at
FROM invitations_before_email_binding;

DROP TABLE invitations_before_email_binding;

CREATE INDEX idx_invitations_github ON invitations(github_user_id, id DESC);
CREATE INDEX idx_invitations_expiry ON invitations(expires_at, used_at);
