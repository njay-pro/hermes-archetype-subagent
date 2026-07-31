"""Auto-launch the Hermes Subagent Dashboard on first archetype dispatch.

Hooked from archetype_delegate._build_child_agent_mimic() so the dashboard
opens the first time a plugin dispatch happens in a given Hermes session.

Design choices:
  - One-shot per PROCESS. _started_this_process is module-level so the
    browser does not re-open on every delegation.
  - Idempotent: if the dashboard is already running on the target port,
    we just open the browser. We do not start a second server.
  - Blocks the calling dispatch (sync) until the dashboard binds the
    port, bounded by `_BLOCK_MAX_WAIT_SEC` (default 3s). After binding,
    the browser-open happens in a daemon thread so the dispatch is not
    held on webbrowser.open() latency.
  - Failure-tolerant: if the dashboard fails to bind within the timeout,
    _started_this_process is NOT set, so the next dispatch retries.
    This avoids a one-shot dead-state where the flag is True but the
    dashboard never came up.
"""

from __future__ import annotations

import logging
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

logger = logging.getLogger(__name__)

_started_this_process = False
_lock = threading.Lock()

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765

# v0.4.2: bound the blocking wait so a hung spawn can't stall the dispatch.
_BLOCK_MAX_WAIT_SEC = 3.0
_BLOCK_POLL_INTERVAL_SEC = 0.1


def _port_open(host: str, port: int, timeout: float = 0.25) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _wait_for_port(host: str, port: int, max_wait: float) -> bool:
    """Poll until the dashboard binds the port or timeout elapses.

    Returns True if the port became reachable within max_wait, False
    otherwise. Caller uses the return value to decide whether to set
    the one-shot flag.
    """
    deadline = time.monotonic() + max_wait
    while time.monotonic() < deadline:
        if _port_open(host, port, timeout=0.05):
            return True
        time.sleep(_BLOCK_POLL_INTERVAL_SEC)
    return False


def _start_dashboard(host: str, port: int) -> None:
    """Spawn dashboard.py in a detached subprocess.

    Uses Popen with start_new_session so the dashboard outlives the
    calling process. We do NOT call .wait() — the dashboard is a
    long-running server, not a job. We just give it a moment to start
    then return; _wait_for_port() polls independently.
    """
    import subprocess
    here = Path(__file__).resolve().parent
    dashboard = here / "dashboard.py"
    if not dashboard.is_file():
        logger.warning(
            "dashboard.py not found at %s — skipping auto-launch", dashboard
        )
        return
    subprocess.Popen(
        [sys.executable, str(dashboard), "--host", host, "--port", str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def auto_open_dashboard(
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    open_browser: bool = True,
    block_until_bound: bool = True,
    max_block_sec: float = _BLOCK_MAX_WAIT_SEC,
) -> bool:
    """First-dispatch hook. Idempotent within this process.

    v0.4.2 race-fix: by default, blocks the calling thread until the
    dashboard is reachable on `host:port`, bounded by `max_block_sec`.
    This closes the race where a subagent dispatched in the same
    process checks the port BEFORE the daemon thread has finished
    spawning + binding dashboard.py.

    Returns True if the dashboard is reachable on return, False if the
    spawn was skipped or the port never bound within the timeout.

    If block_until_bound=False, behavior is unchanged from v0.4.0/v0.4.1
    (fire-and-forget daemon thread, no caller-side wait).
    """
    global _started_this_process
    with _lock:
        if _started_this_process:
            return True  # already up — fast path, no extra wait
        _started_this_process = True  # claim the slot optimistically

    url = f"http://{host}:{port}/"
    needs_spawn = not _port_open(host, port)

    if needs_spawn:
        _start_dashboard(host, port)

    # If the caller wants the race closed, block until bound (or timeout).
    if block_until_bound:
        bound = _wait_for_port(host, port, max_block_sec)
        if not bound:
            # Roll back the optimistic flag so the next dispatch retries.
            with _lock:
                _started_this_process = False
            logger.warning(
                "Dashboard did not bind %s within %.1fs — "
                "next dispatch will retry.",
                url, max_block_sec,
            )
            return False
    else:
        # Legacy path — async, daemon-thread polls in the background.
        def _runner():
            if needs_spawn:
                if not _wait_for_port(host, port, 5.0):
                    logger.warning(
                        "Dashboard did not bind %s within 5s — "
                        "next dispatch will retry.",
                        url,
                    )
                    with _lock:
                        _started_this_process = False
                    return
            if open_browser:
                try:
                    webbrowser.open(url, new=2)
                except Exception as exc:
                    logger.warning("webbrowser.open failed: %s", exc)

        threading.Thread(target=_runner, daemon=True, name="auto-dashboard").start()

    # Browser-open runs in a daemon thread so webbrowser.open() latency
    # doesn't hold the dispatch. Browser-open failures are non-fatal.
    if open_browser:
        def _open_browser():
            try:
                webbrowser.open(url, new=2)
            except Exception as exc:
                logger.warning("webbrowser.open failed: %s", exc)

        threading.Thread(target=_open_browser, daemon=True,
                         name="auto-dashboard-browser").start()

    return True


def reset_for_testing() -> None:
    """Test helper — reset the one-shot flag so the hook fires again."""
    global _started_this_process
    with _lock:
        _started_this_process = False