@echo off
REM NodeMarket v0.7 - one-click launcher for Windows
REM Usage: double-click run.bat (or run it from cmd / PowerShell)

chcp 65001 >nul
title NodeMarket Server
setlocal

echo.
echo ========================================
echo  NodeMarket v0.7 - Privacy-First Marketplace
echo  Visual Store Customizer ^& Full Configuration
echo ========================================
echo.

REM --- 0/4: Python 3.11+ -------------------------------------------------
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python 3.11 or newer was not found on PATH.
    echo.
    echo   1. Download it from https://www.python.org/downloads/
    echo   2. During setup, tick "Add python.exe to PATH"
    echo   3. Close this window and double-click run.bat again
    echo.
    pause
    exit /b 1
)
echo [0/4] Python found.

REM --- 1/4 + 2/4: virtual environment and dependencies --------------------
if not exist ".venv\Scripts\python.exe" (
    echo [1/4] Creating virtual environment...
    python -m venv .venv
    if errorlevel 1 (
        echo ERROR: Failed to create the virtual environment.
        pause
        exit /b 1
    )
    echo [2/4] Installing dependencies ^(first run, a few minutes^)...
    .venv\Scripts\python.exe -m pip install --upgrade pip -q
    .venv\Scripts\python.exe -m pip install -r requirements.txt
    if errorlevel 1 (
        echo ERROR: Failed to install dependencies. Check your connection.
        pause
        exit /b 1
    )
) else (
    echo [1/4] Virtual environment found.
    .venv\Scripts\python.exe -c "import fastapi, uvicorn, jinja2, itsdangerous, multipart, pgpy" >nul 2>&1
    if errorlevel 1 (
        echo [2/4] Installing missing dependencies...
        .venv\Scripts\python.exe -m pip install -r requirements.txt
    ) else (
        echo [2/4] Dependencies already installed.
    )
)

REM --- 3/4: .env with a random SECRET_KEY --------------------------------
.venv\Scripts\python.exe tools\make_env.py

echo [4/4] Starting server...
echo.
echo   Storefront:        http://127.0.0.1:8000
echo   Admin panel:       http://127.0.0.1:8000/admin
echo   Visual Customizer: http://127.0.0.1:8000/admin/customize
echo.
echo   Admin password: see ADMIN_PASSWORD in .env
echo   Press Ctrl+C to stop the server.
echo.

start "" /b .venv\Scripts\python.exe tools\open_browser.py 8000
.venv\Scripts\python.exe run.py

echo.
echo Server stopped.
pause
