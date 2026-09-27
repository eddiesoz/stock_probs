-- One fixed portfolio and one fixed watchlist keep mutable user context separate from audit data.
CREATE TABLE instrument_list_items (
    kind TEXT NOT NULL CHECK (kind IN ('portfolio', 'watchlist')),
    provider TEXT NOT NULL CHECK (length(trim(provider)) BETWEEN 1 AND 80),
    canonical_symbol TEXT NOT NULL CHECK (length(trim(canonical_symbol)) BETWEEN 1 AND 15),
    asset_type TEXT NOT NULL CHECK (asset_type IN ('stock', 'etf')),
    exchange TEXT NOT NULL CHECK (length(trim(exchange)) BETWEEN 1 AND 40),
    display_name TEXT NOT NULL CHECK (length(trim(display_name)) BETWEEN 1 AND 200),
    quantity REAL CHECK (quantity IS NULL OR quantity >= 0),
    added_at TEXT NOT NULL,
    CHECK (kind = 'portfolio' OR quantity IS NULL),
    PRIMARY KEY (kind, provider, canonical_symbol, asset_type)
);

CREATE INDEX idx_instrument_list_items_scan
    ON instrument_list_items(kind, added_at, canonical_symbol);
