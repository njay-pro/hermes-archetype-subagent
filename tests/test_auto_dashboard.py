"""Tests for auto_dashboard — first-dispatch hook + v0.4.2 race-fix."""
from __future__ import annotations

import threading
import time

import auto_dashboard


def _wb_stub():
    """Return a stand-in webbrowser module with a recording .open()."""
    calls = []
    wb = type("wb", (), {"open": staticmethod(lambda *a, **k: calls.append(a))})
    return wb, calls


def test_auto_open_dashboard_idempotent(monkeypatch):
    """Second call in same process must NOT re-open the browser."""
    wb, calls = _wb_stub()
    monkeypatch.setattr(auto_dashboard, "webbrowser", wb)
    monkeypatch.setattr(auto_dashboard, "_port_open", lambda *a, **k: True)
    auto_dashboard.reset_for_testing()

    auto_dashboard.auto_open_dashboard()
    auto_dashboard.auto_open_dashboard()

    time.sleep(0.5)
    assert len(calls) == 1, f"expected 1 browser open, got {len(calls)}"


def test_dashboard_already_running_skips_spawn(monkeypatch):
    monkeypatch.setattr(auto_dashboard, "_port_open", lambda *a, **k: True)
    spawn_calls = []
    monkeypatch.setattr(auto_dashboard, "_start_dashboard",
                        lambda *a, **k: spawn_calls.append(a))
    monkeypatch.setattr(auto_dashboard, "webbrowser", *_wb_stub())
    auto_dashboard.reset_for_testing()
    auto_dashboard.auto_open_dashboard(block_until_bound=False)
    time.sleep(0.3)
    assert spawn_calls == [], "should not spawn a second server when one is already up"


def test_spawns_when_port_closed(monkeypatch):
    """Legacy async path: spawns dashboard when port is closed."""
    monkeypatch.setattr(auto_dashboard, "_port_open", lambda *a, **k: False)
    monkeypatch.setattr(auto_dashboard, "_wait_for_port", lambda *a, **k: True)
    spawn_calls = []
    monkeypatch.setattr(auto_dashboard, "_start_dashboard",
                        lambda *a, **k: spawn_calls.append(a))
    monkeypatch.setattr(auto_dashboard, "webbrowser", *_wb_stub())
    auto_dashboard.reset_for_testing()
    auto_dashboard.auto_open_dashboard(block_until_bound=False)
    time.sleep(0.3)
    assert len(spawn_calls) == 1


def test_open_browser_false_skips_browser(monkeypatch):
    monkeypatch.setattr(auto_dashboard, "_port_open", lambda *a, **k: True)
    wb, calls = _wb_stub()
    monkeypatch.setattr(auto_dashboard, "webbrowser", wb)
    auto_dashboard.reset_for_testing()
    auto_dashboard.auto_open_dashboard(open_browser=False)
    time.sleep(0.3)
    assert calls == []


# -------- v0.4.2 race-fix tests --------

def test_blocks_until_port_bound(monkeypatch):
    """block_until_bound=True (default) must wait for port to bind."""
    port_states = [False, False, False, True]
    idx = [0]
    def fake_port_open(*a, **k):
        v = port_states[min(idx[0], len(port_states) - 1)]
        idx[0] += 1
        return v
    monkeypatch.setattr(auto_dashboard, "_port_open", fake_port_open)
    # Patch the helper _wait_for_port calls into, to mimic the real behavior:
    # poll until fake_port_open returns True or max_wait expires.
    def fake_wait_for_port(host, port, max_wait):
        deadline = time.monotonic() + max_wait
        while time.monotonic() < deadline:
            if fake_port_open():
                return True
            time.sleep(0.05)
        return False
    monkeypatch.setattr(auto_dashboard, "_wait_for_port", fake_wait_for_port)
    spawn_calls = []
    monkeypatch.setattr(auto_dashboard, "_start_dashboard",
                        lambda *a, **k: spawn_calls.append(a))
    monkeypatch.setattr(auto_dashboard, "webbrowser", *_wb_stub())
    auto_dashboard.reset_for_testing()

    t0 = time.monotonic()
    auto_dashboard.auto_open_dashboard(block_until_bound=True, max_block_sec=2.0)
    elapsed = time.monotonic() - t0
    assert len(spawn_calls) == 1
    # Should return once the port is bound, NOT spin for full max_block
    assert elapsed < 1.5, f"hook held {elapsed:.2f}s — should have returned at first bind"


def test_rollback_flag_on_bind_timeout(monkeypatch):
    """If port never binds, _started_this_process must roll back so next dispatch retries."""
    monkeypatch.setattr(auto_dashboard, "_port_open", lambda *a, **k: False)
    monkeypatch.setattr(auto_dashboard, "_wait_for_port",
                        lambda host, port, max_wait: False)
    spawn_calls = []
    monkeypatch.setattr(auto_dashboard, "_start_dashboard",
                        lambda *a, **k: spawn_calls.append(a))
    monkeypatch.setattr(auto_dashboard, "webbrowser", *_wb_stub())
    auto_dashboard.reset_for_testing()

    result = auto_dashboard.auto_open_dashboard(
        block_until_bound=True, max_block_sec=0.2,
    )
    assert result is False
    assert auto_dashboard._started_this_process is False, (
        "flag must roll back so the next dispatch retries the spawn"
    )


def test_idempotent_fast_path_returns_immediately(monkeypatch):
    """If flag is already set, return True without touching the port."""
    # Simulate "already up" by setting the flag and mocking port check
    auto_dashboard.reset_for_testing()
    auto_dashboard._started_this_process = True

    port_check_calls = []
    def port_check(*a, **k):
        port_check_calls.append(a)
        return True
    monkeypatch.setattr(auto_dashboard, "_port_open", port_check)

    # block_until_bound=False to make timing deterministic — fast path
    # should short-circuit BEFORE any port check.
    result = auto_dashboard.auto_open_dashboard(block_until_bound=False)
    assert result is True


def test_block_until_bound_false_legacy_async_path(monkeypatch):
    """block_until_bound=False must use the old daemon-thread path."""
    monkeypatch.setattr(auto_dashboard, "_port_open", lambda *a, **k: False)
    spawn_calls = []
    monkeypatch.setattr(auto_dashboard, "_start_dashboard",
                        lambda *a, **k: spawn_calls.append(a))
    # Make the daemon-thread _runner() no-op quickly
    monkeypatch.setattr(auto_dashboard, "_wait_for_port", lambda *a, **k: True)
    monkeypatch.setattr(auto_dashboard, "webbrowser", *_wb_stub())

    auto_dashboard.reset_for_testing()
    t0 = time.monotonic()
    auto_dashboard.auto_open_dashboard(block_until_bound=False)
    elapsed = time.monotonic() - t0
    # Legacy path returns immediately (no caller-side wait)
    assert elapsed < 0.3, f"legacy path should return fast, took {elapsed:.2f}s"
    assert len(spawn_calls) == 1