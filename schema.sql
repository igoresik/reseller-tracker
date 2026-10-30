-- money is stored as whole cents and fee rates as basis points (12.8% = 1280),
-- so no amount ever goes through floating point

CREATE TABLE IF NOT EXISTS platforms (
    name            TEXT PRIMARY KEY,
    fee_bps         INTEGER NOT NULL DEFAULT 0 CHECK (fee_bps >= 0),
    fee_fixed_cents INTEGER NOT NULL DEFAULT 0 CHECK (fee_fixed_cents >= 0)
);

-- starting values only, edit them in the app
INSERT OR IGNORE INTO platforms (name, fee_bps, fee_fixed_cents) VALUES
    ('Vinted', 0, 0),
    ('Depop', 1000, 0),
    ('eBay', 1280, 30);

CREATE TABLE IF NOT EXISTS listings (
    id         INTEGER PRIMARY KEY,
    title      TEXT NOT NULL,
    brand      TEXT,
    size       TEXT,
    platform   TEXT NOT NULL REFERENCES platforms(name),
    cost_cents INTEGER NOT NULL CHECK (cost_cents >= 0),
    list_cents INTEGER NOT NULL CHECK (list_cents > 0),
    sale_cents INTEGER CHECK (sale_cents > 0),
    sale_fee_cents INTEGER,  -- the fee when it sold, so editing a platform's rates leaves past profit alone
    status     TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'sold')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS shipments (
    id              INTEGER PRIMARY KEY,
    listing_id      INTEGER NOT NULL UNIQUE REFERENCES listings(id),
    carrier         TEXT,
    tracking_number TEXT,
    shipping_cents  INTEGER NOT NULL DEFAULT 0 CHECK (shipping_cents >= 0),
    status          TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'label_created', 'shipped', 'delivered', 'returned')),
    updated_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_event      TEXT
);

-- every tracking event Ship24 has reported; checking again only adds new ones
CREATE TABLE IF NOT EXISTS shipment_events (
    id          INTEGER PRIMARY KEY,
    shipment_id INTEGER NOT NULL REFERENCES shipments(id),
    event_id    TEXT NOT NULL,
    occurred_at TEXT,
    status      TEXT NOT NULL,
    location    TEXT,
    milestone   TEXT,
    UNIQUE (shipment_id, event_id)
);

-- API keys and tokens; vault.py encrypts the secret ones on Windows
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

PRAGMA user_version = 3;
