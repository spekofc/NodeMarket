"""NodeMarket SQLite layer. stdlib-only, WAL mode, dict-row helpers.

No client IP, no request logs: the database never records anything about
the requester beyond what a buyer explicitly types at checkout (which is
PGP-encrypted before it ever hits disk).
"""

import sqlite3
from pathlib import Path

_SCHEMA = """
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS products (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT    NOT NULL,
    description   TEXT    NOT NULL DEFAULT '',
    price_cents   INTEGER NOT NULL,
    currency      TEXT    NOT NULL DEFAULT 'USD',
    active        INTEGER NOT NULL DEFAULT 1,
    category_id   INTEGER,
    created_at    TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS categories (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    slug TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS store_settings (
    id                 INTEGER PRIMARY KEY CHECK (id = 1),
    store_name         TEXT NOT NULL DEFAULT 'NodeMarket Store',
    pgp_public_key     TEXT,
    payment_provider   TEXT NOT NULL DEFAULT 'demo',   -- legacy single-provider (v0.2)
    xpub               TEXT,
    -- v0.3 multi-currency switches (independent enable/disable)
    btc_enabled        INTEGER NOT NULL DEFAULT 0,
    btc_mode           TEXT    NOT NULL DEFAULT 'xpub', -- 'xpub' | 'rpc'
    btc_rate           TEXT    NOT NULL DEFAULT '',     -- 1 fiat unit = N BTC (manual)
    xmr_enabled        INTEGER NOT NULL DEFAULT 0,
    xmr_address        TEXT    NOT NULL DEFAULT '',     -- main address (direct mode)
    xmr_subaddresses   TEXT    NOT NULL DEFAULT '',     -- per-order rotation (direct mode)
    xmr_rate           TEXT    NOT NULL DEFAULT '',     -- 1 fiat unit = N XMR (manual)
    demo_enabled       INTEGER NOT NULL DEFAULT 1,
    payout_btc_address TEXT    NOT NULL DEFAULT '',     -- escrow auto-release destination
    payout_xmr_address TEXT    NOT NULL DEFAULT '',
    settlement_mode    TEXT    NOT NULL DEFAULT 'direct' -- 'direct' | 'escrow'
);

INSERT OR IGNORE INTO store_settings (id) VALUES (1);

CREATE TABLE IF NOT EXISTS orders (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    order_ref        TEXT    NOT NULL UNIQUE,
    status           TEXT    NOT NULL DEFAULT 'pending',
    total_cents      INTEGER NOT NULL,
    currency         TEXT    NOT NULL,
    payment_provider TEXT    NOT NULL,
    payment_label    TEXT    NOT NULL DEFAULT '',
    payment_details  TEXT    NOT NULL DEFAULT '',
    buyer_encrypted  TEXT    NOT NULL,          -- PGP ciphertext, never plaintext
    created_at       TEXT    NOT NULL DEFAULT (datetime('now')),
    settlement_mode  TEXT    NOT NULL DEFAULT 'direct' -- frozen at checkout
);

CREATE TABLE IF NOT EXISTS escrow_events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id   INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    event      TEXT    NOT NULL,   -- resulting state or note
    actor      TEXT    NOT NULL,   -- 'buyer' | 'admin' | 'system'
    note       TEXT    NOT NULL DEFAULT '',
    created_at TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS order_items (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id         INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    product_id       INTEGER,
    name_snapshot    TEXT    NOT NULL,
    qty              INTEGER NOT NULL,
    unit_price_cents INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS order_messages (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id   INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    author     TEXT    NOT NULL,          -- 'buyer' | 'seller'
    body       TEXT    NOT NULL,          -- PGP ciphertext (buyer) or plaintext (seller)
    is_encrypted INTEGER NOT NULL DEFAULT 1,
    created_at TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS reports (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id  INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    reason      TEXT    NOT NULL,
    description TEXT    NOT NULL DEFAULT '',
    status      TEXT    NOT NULL DEFAULT 'open',  -- 'open' | 'archived' | 'actioned'
    created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);
"""


def connect() -> sqlite3.Connection:
    Path("data").mkdir(exist_ok=True)
    conn = sqlite3.connect("data/nodemarket.db", timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


_MIGRATIONS = {
    "store_settings": {
        "btc_enabled":        "INTEGER NOT NULL DEFAULT 0",
        "btc_mode":           "TEXT    NOT NULL DEFAULT 'xpub'",
        "btc_rate":           "TEXT    NOT NULL DEFAULT ''",
        "xmr_enabled":        "INTEGER NOT NULL DEFAULT 0",
        "xmr_address":        "TEXT    NOT NULL DEFAULT ''",
        "xmr_subaddresses":   "TEXT    NOT NULL DEFAULT ''",
        "xmr_rate":           "TEXT    NOT NULL DEFAULT ''",
        "demo_enabled":       "INTEGER NOT NULL DEFAULT 1",
        "payout_btc_address": "TEXT    NOT NULL DEFAULT ''",
        "payout_xmr_address": "TEXT    NOT NULL DEFAULT ''",
        "settlement_mode":    "TEXT    NOT NULL DEFAULT 'direct'",
    },
    "orders": {
        "settlement_mode": "TEXT NOT NULL DEFAULT 'direct'",
    },
    "products": {
        "category_id": "INTEGER",
    },
}


def _migrate(conn: sqlite3.Connection) -> None:
    """Add v0.3 columns to databases created before v0.3 (idempotent)."""
    for table, cols in _MIGRATIONS.items():
        existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        if not existing:
            continue  # table will be created by the schema script below
        for name, decl in cols.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")


def init_db() -> None:
    conn = connect()
    try:
        _migrate(conn)
        conn.executescript(_SCHEMA)
        conn.commit()
    finally:
        conn.close()


def query(sql: str, params: tuple = ()) -> list[sqlite3.Row]:
    conn = connect()
    try:
        rows = conn.execute(sql, params).fetchall()
        conn.commit()
        return rows
    finally:
        conn.close()


def execute(sql: str, params: tuple = ()) -> int:
    """Run a write statement, return lastrowid."""
    conn = connect()
    try:
        cur = conn.execute(sql, params)
        conn.commit()
        return cur.lastrowid or 0
    finally:
        conn.close()
