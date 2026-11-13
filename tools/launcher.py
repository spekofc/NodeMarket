"""NodeMarket one-click launcher (source for NodeMarket-Windows.exe).

Build:
    pyinstaller --onefile --console --name NodeMarket-Windows \
        --distpath dist --workpath build --specpath build launcher.py

On first run it checks Python 3.11+, creates ``.venv``, installs
``requirements.txt``, writes ``.env`` with a random SECRET_KEY, starts the
server on 127.0.0.1:8000 and opens the storefront in the default browser.
Nothing is written outside the project folder.
"""

from __future__ import annotations

import os
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

MIN_PYTHON = (3, 11)
HOST = "127.0.0.1"
PORT = 8000

BANNER = r"""
========================================
 NodeMarket v0.7 - Privacy-First Marketplace
 Visual Store Customizer & Full Configuration
========================================
"""


def project_dir() -> Path:
    """Folder holding run.py: next to the exe, its parent, or the cwd."""
    if getattr(sys, "frozen", False):
        start = Path(sys.executable).resolve().parent
    else:
        start = Path(__file__).resolve().parent.parent
    for candidate in (start, start.parent, Path.cwd()):
        if (candidate / "run.py").exists():
            return candidate
    return start


def say(msg: str) -> None:
    print(msg, flush=True)


def die(msg: str) -> None:
    say("")
    say("ERROR: " + msg)
    say("")
    if os.name == "nt":
        try:
            input("Press Enter to close...")
        except EOFError:
            pass
    sys.exit(1)


def find_python() -> list[str]:
    """Return a command prefix for a Python 3.11+ interpreter."""
    candidates: list[list[str]] = []
    for name in ("py", "python3", "python"):
        found = shutil.which(name)
        if found:
            candidates.append([found])
            if name == "py":
                candidates.append([found, "-3"])
    for cmd in candidates:
        try:
            out = subprocess.run(
                cmd + ["-c", "import sys; print('%d.%d' % sys.version_info[:2])"],
                capture_output=True, text=True, timeout=15,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if out.returncode != 0:
            continue
        try:
            major, minor = (int(x) for x in out.stdout.strip().split("."))
        except ValueError:
            continue
        if (major, minor) >= MIN_PYTHON:
            return cmd
    die(
        "Python %d.%d+ not found.\n"
        "  Install it from https://www.python.org/downloads/ and tick\n"
        "  'Add python.exe to PATH' during setup, then run this again."
        % MIN_PYTHON
    )
    return []  # unreachable


def venv_python(root: Path) -> Path:
    if os.name == "nt":
        return root / ".venv" / "Scripts" / "python.exe"
    return root / ".venv" / "bin" / "python"


def has_deps(py: Path) -> bool:
    try:
        out = subprocess.run(
            [str(py), "-c", "import fastapi, uvicorn, jinja2, itsdangerous, multipart, pgpy"],
            capture_output=True, timeout=90,
        )
        return out.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def ensure_venv(root: Path, base_python: list[str]) -> Path:
    py = venv_python(root)
    req = root / "requirements.txt"
    if not req.exists():
        die("requirements.txt is missing - extract the full NodeMarket package "
            "next to this launcher.")
    if not py.exists():
        say("[1/4] Creating virtual environment (.venv)...")
        res = subprocess.run(base_python + ["-m", "venv", str(root / ".venv")])
        if res.returncode != 0 or not py.exists():
            die("Could not create the virtual environment.")
    else:
        say("[1/4] Virtual environment found.")

    if has_deps(py):
        say("[2/4] Dependencies already installed.")
        return py

    say("[2/4] Installing dependencies (first run, a few minutes)...")
    subprocess.run([str(py), "-m", "pip", "install", "--upgrade", "pip", "-q"])
    res = subprocess.run([str(py), "-m", "pip", "install", "-r", str(req)])
    if res.returncode != 0:
        die("Dependency installation failed. Check your internet connection "
            "and run it again.")
    return py


def ensure_env(root: Path) -> None:
    env = root / ".env"
    if env.exists():
        text = env.read_text(encoding="utf-8", errors="replace")
        if "change-me-to-a-long-random-string" in text:
            text = text.replace(
                "change-me-to-a-long-random-string", secrets.token_hex(32)
            )
            env.write_text(text, encoding="utf-8")
            say("[3/4] Replaced the placeholder SECRET_KEY in .env.")
        else:
            say("[3/4] .env found.")
        return

    say("[3/4] Creating .env with a random SECRET_KEY...")
    example = root / ".env.example"
    if example.exists():
        text = example.read_text(encoding="utf-8", errors="replace")
    else:
        text = (
            "SECRET_KEY=change-me-to-a-long-random-string\n"
            "ADMIN_PASSWORD=changeme-admin\n"
            "STORE_NAME=NodeMarket Store\n"
            "CURRENCY=USD\n"
            "DB_PATH=data/nodemarket.db\n"
            "HOST=127.0.0.1\n"
            "PORT=8000\n"
        )
    text = text.replace("change-me-to-a-long-random-string", secrets.token_hex(32))
    env.write_text(text, encoding="utf-8")


def open_when_ready(url: str, host: str, port: int, timeout: float = 60.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            if s.connect_ex((host, port)) == 0:
                webbrowser.open(url)
                return
        time.sleep(0.5)


def main() -> int:
    say(BANNER)
    root = project_dir()
    os.chdir(root)

    if not (root / "run.py").exists():
        die(
            "run.py not found in %s\n"
            "  Download NodeMarket-v0.7.0-portable.zip, extract it, then run\n"
            "  NodeMarket-Windows.exe from inside the extracted folder."
            % root
        )

    py = ensure_venv(root, find_python())
    ensure_env(root)

    say("[4/4] Starting server on http://%s:%d" % (HOST, PORT))
    say("      Admin panel:       http://%s:%d/admin" % (HOST, PORT))
    say("      Visual Customizer: http://%s:%d/admin/customize" % (HOST, PORT))
    say("      Stop with Ctrl+C.")
    say("")

    threading.Thread(
        target=open_when_ready,
        args=("http://%s:%d" % (HOST, PORT), HOST, PORT),
        daemon=True,
    ).start()

    try:
        proc = subprocess.Popen([str(py), str(root / "run.py")], cwd=str(root))
    except OSError as exc:
        die("Could not start the server: %s" % exc)
    try:
        return proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        return 0


if __name__ == "__main__":
    sys.exit(main())
