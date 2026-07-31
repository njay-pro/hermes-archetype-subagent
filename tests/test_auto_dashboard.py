"""Tests for auto_dashboard — first-dispatch hook."""
from __future__ import annotations

import time

import auto_dashboard


def test_auto_open_dashboard_idempotent(monkeypatch):
    """Second call in same process must NOT re-open the browser."""
    calls = []
    monkeypatch.setattr(auto_dashboard, "webbrowser", type("wb", (), {
        "open": staticmethod(lambda *a, **k: calls.append(a))
    }))
    monkeypatch.setattr(auto_dashboard, "_port_open", lambda *a, **k: True)
    auto_dashboard.reset_for_testing()

    auto_dashboard.auto_open_dashboard()
    auto_dashboard.auto_open_dashboard()  # second call

    time.sleep(0.5)
    assert len(calls) == 1, f"expected 1 browser open, got {len(calls)}"


def test_dashboard_already_running_skips_spawn(monkeypatch):
    monkeypatch.setattr(auto_dashboard, "_port_open", lambda *a, **k: True)
    spawn_calls = []
    monkeypatch.setattr(auto_dashboard, "_start_dashboard",
                        lambda *a, **k: spawn_calls.append(a))
    auto_dashboard.reset_for_testing()
    auto_dashboard.auto_open_dashboard()
    time.sleep(0.3)
    assert spawn_calls == [], "should not spawn a second server when one is already up"


def test_spawns_when_port_closed(monkeypatch):
    monkeypatch.setattr(auto_dashboard, "_port_open", lambda *a, **k: False)
    monkeypatch.setattr(auto_dashboard, "_wait_for_port", lambda *a, **k: True)
    spawn_calls = []
    monkeypatch.setattr(auto_dashboard, "_start_dashboard",
                        lambda *a, **k: spawn_calls.append(a))
    monkeypatch.setattr(auto_dashboard, "webbrowser", type("wb", (), {
        "open": staticmethod(lambda *a, **k: None)
    }))
    auto_dashboard.reset_for_testing()
    auto_dashboard.auto_open_dashboard()
    time.sleep(0.3)
    assert len(spawn_calls) == 1


def test_open_browser_false_skips_browser(monkeypatch):
    monkeypatch.setattr(auto_dashboard, "_port_open", lambda *a, **k: True)
    calls = []
    monkeypatch.setattr(auto_dashboard, "webbrowser", type("wb", (), {
        "open": staticmethod(lambda *a, **k: calls.append(a))
    }))
    auto_dashboard.reset_for_testing()
    auto_dashboard.auto_open_dashboard(open_browser=False)
    time.sleep(0.3)
    assert calls == []