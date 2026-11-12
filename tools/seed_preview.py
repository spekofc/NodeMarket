"""One-shot local seed for previewing: PGP key, products, payment settings."""
from pathlib import Path
import sqlite3

pub = Path("test_pgp_key.pub").read_text()
conn = sqlite3.connect("data/nodemarket.db")
conn.execute(
    "UPDATE store_settings SET store_name=?, pgp_public_key=?, btc_enabled=1, "
    "btc_mode='xpub', btc_rate='0.000015', "
    "xpub='xpub661MyMwAqRbcFtXgS5sYJABqqG9YLmC4Q1Rdap9gSE8NqtwybGhePY2gZ29ESFjqJoCu1Rupje8YtGqsefD265TMg7usUDFdp6W1EGMcet8', "
    "xmr_enabled=1, "
    "xmr_subaddresses='48jewbtxe4jU3MnzJFjZ6sP3tJ6dLq9dZqESiNQpYh9W5rfWCG5pL1tfJguVCEqx3A6bLLBppHBvf8nCJbCWMBG4935q1om', "
    "xmr_rate='0.15', demo_enabled=1, settlement_mode='direct' WHERE id=1",
    ("NodeMarket Store", pub))
conn.execute("INSERT INTO products (name, description, price_cents) "
             "VALUES ('Demo Widget', 'A fine demo widget, privacy included.', 1990)")
conn.execute("INSERT INTO products (name, description, price_cents) "
             "VALUES ('Privacy Handbook', 'Field notes on staying off the radar.', 750)")
conn.commit()
conn.close()
print("seeded")
