"""Create .env from .env.example with a freshly generated SECRET_KEY.

Used by run.bat / run.sh. Idempotent: does nothing when .env already exists.
Also repairs an .env that still carries the placeholder secret.
"""

import pathlib
import secrets

PLACEHOLDER = "change-me-to-a-long-random-string"

FALLBACK = (
    "SECRET_KEY=" + PLACEHOLDER + "\n"
    "ADMIN_PASSWORD=changeme-admin\n"
    "STORE_NAME=NodeMarket Store\n"
    "CURRENCY=USD\n"
    "DB_PATH=data/nodemarket.db\n"
    "HOST=127.0.0.1\n"
    "PORT=8000\n"
)

env = pathlib.Path(".env")
example = pathlib.Path(".env.example")

if env.exists():
    text = env.read_text(encoding="utf-8")
    if PLACEHOLDER not in text:
        raise SystemExit(0)
    print("Replacing the placeholder SECRET_KEY in .env")
else:
    print("Creating .env with a random SECRET_KEY")
    text = example.read_text(encoding="utf-8") if example.exists() else FALLBACK

env.write_text(text.replace(PLACEHOLDER, secrets.token_hex(32)), encoding="utf-8")
