-- Draft only: linked owner accounts, append-only transaction batches and frozen simulations.
CREATE TABLE portfolio_accounts (
    id TEXT PRIMARY KEY CHECK(length(id) = 36),
    owner_user_id INTEGER NOT NULL REFERENCES users(id),
    idempotency_key TEXT NOT NULL CHECK(length(idempotency_key) = 36),
    request_sha256 TEXT NOT NULL CHECK(length(request_sha256) = 64),
    label TEXT NOT NULL CHECK(length(trim(label)) BETWEEN 1 AND 80),
    account_type TEXT NOT NULL CHECK(account_type IN ('tfsa', 'rrsp', 'taxable', 'other')),
    revision INTEGER NOT NULL DEFAULT 1 CHECK(revision > 0),
    archived INTEGER NOT NULL DEFAULT 0 CHECK(archived IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(id, owner_user_id),
    UNIQUE(owner_user_id, idempotency_key)
);
CREATE TRIGGER portfolio_accounts_no_delete BEFORE DELETE ON portfolio_accounts
BEGIN SELECT RAISE(ABORT, 'account history must be retained'); END;
CREATE TRIGGER portfolio_accounts_no_replace BEFORE INSERT ON portfolio_accounts
WHEN EXISTS(SELECT 1 FROM portfolio_accounts WHERE id = NEW.id OR
    (owner_user_id = NEW.owner_user_id AND idempotency_key = NEW.idempotency_key))
BEGIN SELECT RAISE(ABORT, 'account identity is immutable'); END;
CREATE TRIGGER portfolio_accounts_identity_immutable BEFORE UPDATE ON portfolio_accounts
WHEN NEW.id != OLD.id OR NEW.owner_user_id != OLD.owner_user_id OR
     NEW.idempotency_key != OLD.idempotency_key OR NEW.request_sha256 != OLD.request_sha256 OR
     NEW.created_at != OLD.created_at
BEGIN SELECT RAISE(ABORT, 'account identity is immutable'); END;
CREATE INDEX portfolio_accounts_owner ON portfolio_accounts(owner_user_id, created_at, id);
CREATE TABLE portfolio_batches (
    id TEXT PRIMARY KEY CHECK(length(id) = 36),
    owner_user_id INTEGER NOT NULL REFERENCES users(id),
    idempotency_key TEXT NOT NULL CHECK(length(idempotency_key) = 36),
    preview_id TEXT NOT NULL CHECK(length(preview_id) = 36),
    request_sha256 TEXT NOT NULL CHECK(length(request_sha256) = 64),
    receipt_json TEXT NOT NULL CHECK(length(CAST(receipt_json AS BLOB)) <= 262144),
    created_at TEXT NOT NULL,
    UNIQUE(id, owner_user_id),
    UNIQUE(owner_user_id, idempotency_key)
);
CREATE TABLE portfolio_transactions (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    id TEXT NOT NULL UNIQUE CHECK(length(id) = 36),
    owner_user_id INTEGER NOT NULL,
    account_id TEXT NOT NULL,
    batch_id TEXT NOT NULL,
    effective_date TEXT NOT NULL CHECK(length(effective_date) = 10),
    payload_json TEXT NOT NULL CHECK(length(CAST(payload_json AS BLOB)) <= 4096),
    duplicate_sha256 TEXT NOT NULL CHECK(length(duplicate_sha256) = 64),
    replaces_id TEXT,
    manual_holding_key TEXT CHECK(manual_holding_key IS NULL OR length(manual_holding_key) = 64),
    created_at TEXT NOT NULL,
    UNIQUE(id, account_id, owner_user_id),
    UNIQUE(owner_user_id, manual_holding_key),
    FOREIGN KEY(account_id, owner_user_id) REFERENCES portfolio_accounts(id, owner_user_id),
    FOREIGN KEY(batch_id, owner_user_id) REFERENCES portfolio_batches(id, owner_user_id),
    FOREIGN KEY(replaces_id, account_id, owner_user_id)
        REFERENCES portfolio_transactions(id, account_id, owner_user_id)
);
CREATE INDEX portfolio_transactions_owner ON portfolio_transactions(owner_user_id, sequence);
CREATE INDEX portfolio_transactions_duplicates ON portfolio_transactions(owner_user_id, duplicate_sha256);
CREATE UNIQUE INDEX portfolio_transactions_one_replacement ON portfolio_transactions(replaces_id)
    WHERE replaces_id IS NOT NULL;
CREATE TRIGGER portfolio_transactions_no_update BEFORE UPDATE ON portfolio_transactions
BEGIN SELECT RAISE(ABORT, 'transactions are append-only'); END;
CREATE TRIGGER portfolio_transactions_no_delete BEFORE DELETE ON portfolio_transactions
BEGIN SELECT RAISE(ABORT, 'transactions are append-only'); END;
CREATE TRIGGER portfolio_transactions_no_replace BEFORE INSERT ON portfolio_transactions
WHEN EXISTS(SELECT 1 FROM portfolio_transactions WHERE id = NEW.id OR sequence = NEW.sequence OR replaces_id = NEW.replaces_id OR
    (owner_user_id = NEW.owner_user_id AND manual_holding_key = NEW.manual_holding_key))
BEGIN SELECT RAISE(ABORT, 'transactions are append-only'); END;
CREATE TRIGGER portfolio_batches_no_update BEFORE UPDATE ON portfolio_batches
BEGIN SELECT RAISE(ABORT, 'transaction batches are immutable'); END;
CREATE TRIGGER portfolio_batches_no_delete BEFORE DELETE ON portfolio_batches
BEGIN SELECT RAISE(ABORT, 'transaction batches are immutable'); END;
CREATE TRIGGER portfolio_batches_no_replace BEFORE INSERT ON portfolio_batches
WHEN EXISTS(SELECT 1 FROM portfolio_batches WHERE id = NEW.id OR
    (owner_user_id = NEW.owner_user_id AND idempotency_key = NEW.idempotency_key))
BEGIN SELECT RAISE(ABORT, 'transaction batches are immutable'); END;
CREATE TABLE portfolio_snapshots (
    id TEXT PRIMARY KEY CHECK(length(id) = 36),
    owner_user_id INTEGER NOT NULL REFERENCES users(id),
    idempotency_key TEXT NOT NULL CHECK(length(idempotency_key) = 36),
    request_sha256 TEXT NOT NULL CHECK(length(request_sha256) = 64),
    payload_json TEXT NOT NULL CHECK(length(CAST(payload_json AS BLOB)) <= 262144),
    created_at TEXT NOT NULL,
    UNIQUE(id, owner_user_id),
    UNIQUE(owner_user_id, idempotency_key)
);
CREATE TABLE portfolio_scenarios (
    id TEXT PRIMARY KEY CHECK(length(id) = 36),
    owner_user_id INTEGER NOT NULL,
    baseline_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL CHECK(length(idempotency_key) = 36),
    request_sha256 TEXT NOT NULL CHECK(length(request_sha256) = 64),
    title TEXT NOT NULL CHECK(length(trim(title)) BETWEEN 1 AND 120),
    assumptions_json TEXT NOT NULL CHECK(length(CAST(assumptions_json AS BLOB)) <= 32768),
    result_json TEXT NOT NULL CHECK(length(CAST(result_json AS BLOB)) <= 262144),
    created_at TEXT NOT NULL,
    UNIQUE(owner_user_id, idempotency_key),
    FOREIGN KEY(baseline_id, owner_user_id) REFERENCES portfolio_snapshots(id, owner_user_id)
);
CREATE INDEX portfolio_snapshots_owner ON portfolio_snapshots(owner_user_id, created_at DESC, id);
CREATE INDEX portfolio_scenarios_owner ON portfolio_scenarios(owner_user_id, created_at DESC, id);
CREATE TRIGGER portfolio_snapshots_no_update BEFORE UPDATE ON portfolio_snapshots
BEGIN SELECT RAISE(ABORT, 'portfolio baselines are immutable'); END;
CREATE TRIGGER portfolio_snapshots_no_delete BEFORE DELETE ON portfolio_snapshots
BEGIN SELECT RAISE(ABORT, 'portfolio baselines are immutable'); END;
CREATE TRIGGER portfolio_snapshots_no_replace BEFORE INSERT ON portfolio_snapshots
WHEN EXISTS(SELECT 1 FROM portfolio_snapshots WHERE id = NEW.id OR
    (owner_user_id = NEW.owner_user_id AND idempotency_key = NEW.idempotency_key))
BEGIN SELECT RAISE(ABORT, 'portfolio baselines are immutable'); END;
CREATE TRIGGER portfolio_scenarios_no_update BEFORE UPDATE ON portfolio_scenarios
BEGIN SELECT RAISE(ABORT, 'saved scenarios are immutable'); END;
CREATE TRIGGER portfolio_scenarios_no_delete BEFORE DELETE ON portfolio_scenarios
BEGIN SELECT RAISE(ABORT, 'saved scenarios are immutable'); END;
CREATE TRIGGER portfolio_scenarios_no_replace BEFORE INSERT ON portfolio_scenarios
WHEN EXISTS(SELECT 1 FROM portfolio_scenarios WHERE id = NEW.id OR
    (owner_user_id = NEW.owner_user_id AND idempotency_key = NEW.idempotency_key))
BEGIN SELECT RAISE(ABORT, 'saved scenarios are immutable'); END;
CREATE TABLE portfolio_fx_cache (
    publication_date TEXT PRIMARY KEY CHECK(length(publication_date) = 10),
    provider TEXT NOT NULL CHECK(provider = 'Bank of Canada'),
    fetched_at TEXT NOT NULL,
    rates_json TEXT NOT NULL CHECK(length(CAST(rates_json AS BLOB)) <= 8192)
);
CREATE TABLE portfolio_fx_fetch_state (
    provider TEXT PRIMARY KEY CHECK(provider = 'Bank of Canada'),
    last_attempt_at TEXT NOT NULL,
    last_attempt_date TEXT NOT NULL CHECK(length(last_attempt_date) = 10),
    last_result TEXT NOT NULL CHECK(last_result IN ('successful', 'failed'))
);
