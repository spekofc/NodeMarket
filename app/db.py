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
    created_at    TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS store_settings (
    id                 INTEGER PRIMARY KEY CHECK (id = 1),
    store_name         TEXT NOT NULL DEFAULT 'NodeMarket Store',
    pgp_public_key     TEXT,
    payment_provider   TEXT NOT NULL DEFAULT 'demo',
    xpub               TEXT
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
    created_at       TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS order_items (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id         INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    product_id       INTEGER,
    name_snapshot    TEXT    NOT NULL,
    qty              INTEGER NOT NULL,
    unit_price_cents INTEGER NOT NULL
);
"""


def connect() -> sqlite3.Connection:
    Path("data").mkdir(exist_ok=True)
    conn = sqlite3.connect("data/nodemarket.db", timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    conn = connect()
    try:
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
