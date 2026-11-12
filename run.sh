#!/usr/bin/env bash
# NodeMarket — one-click run script for Linux/macOS
# Usage: ./run.sh

set -euo pipefail

echo
echo "========================================"
echo "  NodeMarket — Privacy-First Marketplace"
echo "========================================"
echo

# Check if .venv exists
if [[ ! -d ".venv" ]]; then
    echo "[1/4] Creating virtual environment..."
    python3 -m venv .venv
    echo "[2/4] Installing dependencies..."
    .venv/bin/pip install --upgrade pip
    .venv/bin/pip install -r requirements.txt
else
    echo "[1/4] Virtual environment found."
    echo "[2/4] Checking dependencies..."
    .venv/bin/pip install -r requirements.txt >/dev/null 2>&1
fi

# Check if .env exists
if [[ ! -f ".env" ]]; then
    echo "[3/4] Creating .env from .env.example..."
    if [[ -f ".env.example" ]]; then
        cp .env.example .env
        echo "Generated .env — please edit it and set SECRET_KEY and ADMIN_PASSWORD."
    else
        echo "WARNING: .env.example not found. Creating minimal .env..."
        cat > .env <<'EOF'
SECRET_KEY=change-me-to-a-long-random-string
ADMIN_PASSWORD=changeme-admin
STORE_NAME=NodeMarket Store
CURRENCY=USD
EOF
    fi
else
    echo "[3/4] .env found."
fi

echo "[4/4] Starting server..."
echo
echo "Server will be available at: http://127.0.0.1:8000"
echo "Admin panel: http://127.0.0.1:8000/admin (password from .env)"
echo
echo "Press Ctrl+C to stop."
echo

.venv/bin/python run.py