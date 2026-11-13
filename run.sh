#!/usr/bin/env bash
# NodeMarket v0.7 - one-click launcher for Linux/macOS
# Usage: ./run.sh   (chmod +x run.sh once, if needed)

set -euo pipefail

echo
echo "========================================"
echo "  NodeMarket v0.7 - Privacy-First Marketplace"
echo "  Visual Store Customizer & Full Configuration"
echo "========================================"
echo

# --- 0/4: Python 3.11+ ------------------------------------------------------
PY=""
for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1 && \
       "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' >/dev/null 2>&1; then
        PY="$candidate"
        break
    fi
done
if [[ -z "$PY" ]]; then
    echo "ERROR: Python 3.11 or newer was not found."
    echo
    echo "  Debian/Ubuntu: sudo apt install python3 python3-venv python3-pip"
    echo "  Fedora:        sudo dnf install python3 python3-pip"
    echo "  macOS:         brew install python@3.12"
    echo
    echo "Then run ./run.sh again."
    exit 1
fi
echo "[0/4] Using $PY ($("$PY" -c 'import sys; print("%d.%d" % sys.version_info[:2])'))"

# --- 1/4 + 2/4: virtual environment and dependencies ------------------------
if [[ ! -x ".venv/bin/python" ]]; then
    echo "[1/4] Creating virtual environment..."
    "$PY" -m venv .venv
    echo "[2/4] Installing dependencies (first run, a few minutes)..."
    .venv/bin/python -m pip install --upgrade pip -q
    .venv/bin/python -m pip install -r requirements.txt
else
    echo "[1/4] Virtual environment found."
    if .venv/bin/python -c "import fastapi, uvicorn, jinja2, itsdangerous, multipart, pgpy" >/dev/null 2>&1; then
        echo "[2/4] Dependencies already installed."
    else
        echo "[2/4] Installing missing dependencies..."
        .venv/bin/python -m pip install -r requirements.txt
    fi
fi

# --- 3/4: .env with a random SECRET_KEY ------------------------------------
.venv/bin/python tools/make_env.py

echo "[4/4] Starting server..."
echo
echo "  Storefront:        http://127.0.0.1:8000"
echo "  Admin panel:       http://127.0.0.1:8000/admin"
echo "  Visual Customizer: http://127.0.0.1:8000/admin/customize"
echo
echo "  Admin password: see ADMIN_PASSWORD in .env"
echo "  Press Ctrl+C to stop the server."
echo

.venv/bin/python tools/open_browser.py 8000 &
.venv/bin/python run.py
