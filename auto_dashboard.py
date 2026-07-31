"""Auto-launch the Hermes Subagent Dashboard on first archetype dispatch.

Hooked from archetype_delegate._build_child_agent_mimic() so the dashboard
opens the first time a plugin dispatch happens in a given Hermes session.

Design choices:
  - One-shot per process. _started_this_process is module-level so the
    browser does not re-open on every delegation.
  - Idempotent: if the dashboard is already running on the target port,
    we just open the browser. We do not start a second server.
  - Background=True safe: the auto-launch itself runs in a daemon thread
    so the delegation is not blocked on browser startup.
"""

from __future__ import annotations

import logging
import socket
import threading
import time
import webbrowser
from pathlib import Path

logger = logging.getLogger(__name__)

_started_this_process = False
_lock = threading.Lock()

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765


def _port_open(host: str, port: int, timeout: float = 0.25) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _start_dashboard(host: str, port: int) -> None:
    import subprocess
    import sys
    here = Path(__file__).resolve().parent
    dashboard = here / "dashboard.py"
    if not dashboard.is_file():
        logger.warning("dashboard.py not found at %s — skipping auto-launch", dashboard)
        return
    subprocess.Popen(
        [sys.executable, str(dashboard), "--host", host, "--port", str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def _wait_for_port(host: str, port: int, max_wait: float = 5.0) -> bool:
    deadline = time.monotonic() + max_wait
    while time.monotonic() < deadline:
        if _port_open(host, port):
            return True
        time.sleep(0.1)
    return False


def auto_open_dashboard(
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    open_browser: bool = True,
) -> None:
    """First-dispatch hook. Idempotent within this process."""
    global _started_this_process
    with _lock:
        if _started_this_process:
            return
        _started_this_process = True

    def _runner():
        url = f"http://{host}:{port}/"
        if not _port_open(host, port):
            _start_dashboard(host, port)
            if not _wait_for_port(host, port):
                logger.warning(
                    "Dashboard did not bind %s within timeout — skipping browser open",
                    url,
                )
                return
        if open_browser:
            try:
                webbrowser.open(url, new=2)
            except Exception as exc:
                logger.warning("webbrowser.open failed: %s", exc)

    threading.Thread(target=_runner, daemon=True, name="auto-dashboard").start()


def reset_for_testing() -> None:
    """Test helper — reset the one-shot flag so the hook fires again."""
    global _started_this_process
    with _lock:
        _started_this_process = False