"""Entry point of the packaged app: starts the server and shows it in its own window."""

import ctypes
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

# imported here so PyInstaller bundles what app.py needs
import db
import ebay  # noqa: F401
import finance  # noqa: F401
import ship24  # noqa: F401

NAME = "Logistics Tracker"
PORT = 48651
LOG_LIMIT = 1_000_000
ROOT = Path(__file__).parent
BROWSERS = [
    r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe",
    r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe",
    r"%ProgramFiles%\Google\Chrome\Application\chrome.exe",
    r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe",
    r"%LocalAppData%\Google\Chrome\Application\chrome.exe",
]


def open_log(path, limit=LOG_LIMIT):
    """Open the log for appending, so a crash from the last run is still there. Over ``limit`` bytes, the old log
    moves to ``NAME.1`` (replacing an older one) and a fresh file starts."""
    path = Path(path)
    if path.exists() and path.stat().st_size > limit:
        os.replace(path, path.with_name(path.name + ".1"))
    return open(path, "a", encoding="utf-8")


def is_running(port):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/_stcore/health", timeout=1) as reply:
            return reply.status == 200
    except OSError:
        return False


def free_port():
    with socket.socket() as probe:
        try:
            probe.bind(("127.0.0.1", PORT))
        except OSError:
            probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def window_command(browser, port):
    return [
        browser,
        f"--app=http://127.0.0.1:{port}",
        # its own profile: the browser process then lives exactly as long as the window
        f"--user-data-dir={db.DATA_DIR / 'window'}",
        "--no-first-run",
        "--no-default-browser-check",
    ]


def show_window(browser, port):
    while not is_running(port):
        time.sleep(0.2)
    subprocess.run(window_command(browser, port))
    os._exit(0)  # window closed: stop the server too


def main():
    browser = next((p for p in map(os.path.expandvars, BROWSERS) if os.path.exists(p)), None)
    if not browser:
        ctypes.windll.user32.MessageBoxW(None, f"{NAME} needs Microsoft Edge or Google Chrome.", NAME, 0x10)
        return
    if is_running(PORT):  # already open: just show another window
        subprocess.Popen(window_command(browser, PORT))
        return

    if sys.stdout is None:  # no console in the packaged app
        sys.stdout = sys.stderr = open_log(db.DATA_DIR / "app.log")
    os.chdir(ROOT)  # Streamlit reads .streamlit/config.toml from the working directory
    port = free_port()
    threading.Thread(target=show_window, args=(browser, port), daemon=True).start()

    from streamlit.web import cli

    sys.argv = [
        "streamlit", "run", str(ROOT / "app.py"),
        "--server.port", str(port),
        "--server.headless", "true",
        "--server.fileWatcherType", "none",
        "--browser.gatherUsageStats", "false",
        "--global.developmentMode", "false",
    ]
    cli.main()


if __name__ == "__main__":
    main()
