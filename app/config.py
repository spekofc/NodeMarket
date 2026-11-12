"""NodeMarket configuration. Reads .env (stdlib-only parser) with safe defaults."""

import secrets
from pathlib import Path

_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


def load_env() -> dict:
    """Minimal .env parser: KEY=VALUE lines, '#' comments, quoted values stripped."""
    env = {}
    if _ENV_FILE.is_file():
        for raw in _ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            value = value.strip().strip('"').strip("'")
            env[key.strip()] = value
    return env


class Settings:
    def __init__(self) -> None:
        env = load_env()
        self.store_name: str = env.get("STORE_NAME", "NodeMarket Store")
        self.currency: str = env.get("CURRENCY", "USD")
        self.db_path: str = env.get("DB_PATH", "data/nodemarket.db")
        self.admin_password: str = env.get("ADMIN_PASSWORD", "changeme-admin")
        self.host: str = env.get("HOST", "127.0.0.1")
        self.port: int = int(env.get("PORT", "8000"))
        self.trust_proxy: bool = env.get("TRUST_PROXY", "false").lower() == "true"

        secret = env.get("SECRET_KEY")
        if not secret or secret == "change-me-to-a-long-random-string":
            # Random per-boot fallback: sessions survive within one run only.
            secret = secrets.token_hex(32)
            print("[NodeMarket] SECRET_KEY not set in .env - using an ephemeral "
                  "random key. Sessions will reset on restart.")
        self.secret_key: str = secret


settings = Settings()
