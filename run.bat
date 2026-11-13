@echo off
REM NodeMarket v0.7 — one-click run script for Windows
REM Usage: double-click run.bat or run from cmd/powershell

chcp 65001 >nul
title NodeMarket Server

echo.
echo ========================================
echo  NodeMarket v0.7 — Privacy-First Marketplace
echo  Visual Store Customizer & Full Configuration
echo ========================================
echo.

REM Check if .venv exists
if not exist ".venv" (
    echo [1/4] Creating virtual environment...
    python -m venv .venv
    if errorlevel 1 (
        echo ERROR: Failed to create virtual environment.
        echo Make sure Python is installed and in PATH.
        pause
        exit /b 1
    )
    echo [2/4] Installing dependencies...
    .venv\Scripts\pip install --upgrade pip
    .venv\Scripts\pip install -r requirements.txt
    if errorlevel 1 (
        echo ERROR: Failed to install dependencies.
        pause
        exit /b 1
    )
) else (
    echo [1/4] Virtual environment found.
    echo [2/4] Checking dependencies...
    .venv\Scripts\pip install -r requirements.txt >nul 2>&1
)

REM Check if .env exists
if not exist ".env" (
    echo [3/4] Creating .env from .env.example...
    if exist ".env.example" (
        copy .env.example .env >nul
        echo Generated .env — please edit it and set SECRET_KEY and ADMIN_PASSWORD.
    ) else (
        echo WARNING: .env.example not found. Creating minimal .env...
        echo SECRET_KEY=change-me-to-a-long-random-string > .env
        echo ADMIN_PASSWORD=changeme-admin >> .env
        echo STORE_NAME=NodeMarket Store >> .env
        echo CURRENCY=USD >> .env
    )
) else (
    echo [3/4] .env found.
)

echo [4/4] Starting server...
echo.
echo Server will be available at: http://127.0.0.1:8000
echo Admin panel: http://127.0.0.1:8000/admin (password from .env)
echo Visual Customizer: http://127.0.0.1:8000/admin/customize
echo.
echo Press Ctrl+C to stop.
echo.

.venv\Scripts\python.exe run.py