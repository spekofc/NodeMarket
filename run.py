"""NodeMarket launcher: python run.py"""

import uvicorn

from app.config import settings

if __name__ == "__main__":
    if settings.host not in ("127.0.0.1", "localhost"):
        print("[NodeMarket] WARNING: binding to %s. Without HTTPS (reverse "
              "proxy) or a Tor hidden service, buyer data travels in "
              "cleartext to this server. See README 'Transport security'."
              % settings.host)
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        access_log=False,  # no request logs, no IP addresses, anywhere
    )
