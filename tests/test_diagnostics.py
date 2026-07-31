"""Tests for delegate_task_diagnostics."""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

import router


def _make_deleg(live_root, deleg_id, archetype, status="completed",
                 fallback_used=False, started_at=None, ended_at=None,
                 soul_code=None):
    deleg_dir = live_root / deleg_id
    deleg_dir.mkdir(parents=True, exist_ok=True)
    sa = started_at if started_at is not None else time.time() - 5
    ea = ended_at if ended_at is not None else time.time()
    manifest = {
        "archetype": archetype,
        "status": status,
        "fallback_used": fallback_used,
        "started_at": sa,
        "ended_at": ea,
    }
    (deleg_dir / "manifest.json").write_text(json.dumps(manifest))
    log_lines = []
    if soul_code:
        log_lines.append(json.dumps({"text": f"emitting {soul_code} now"}))
    (deleg_dir / "task-0.log").write_text("\n".join(log_lines))


def _set_mtime(path: Path, ts: float) -> None:
    """Backdate mtime so the diagnostics window filter excludes it."""
    import os
    os.utime(path, (ts, ts))


def test_collect_diagnostics_empty(monkeypatch, tmp_path):
    monkeypatch.setattr("router.Path.home", lambda: tmp_path)
    out = router._collect_diagnostics()
    assert out["total_calls"] == 0
    assert out["per_archetype"] == {}


def test_collect_diagnostics_aggregates_per_archetype(monkeypatch, tmp_path):
    live_root = tmp_path / ".hermes" / "cache" / "delegation" / "live"
    live_root.mkdir(parents=True)
    monkeypatch.setattr("router.Path.home", lambda: tmp_path)

    _make_deleg(live_root, "deleg_aaa", "consultant", status="completed")
    _make_deleg(live_root, "deleg_bbb", "consultant", status="failed")
    _make_deleg(live_root, "deleg_ccc", "long_horizon", status="failed",
                fallback_used=True, soul_code="EXECUTION_FAILURE")

    out = router._collect_diagnostics()
    assert out["totals"]["total_calls"] == 3
    assert out["totals"]["successful"] == 1   # only deleg_aaa completed
    assert out["totals"]["fallback_used"] == 1
    assert out["totals"]["soul_codes_emitted"]["EXECUTION_FAILURE"] == 1
    assert "consultant" in out["per_archetype"]
    assert "long_horizon" in out["per_archetype"]
    assert out["per_archetype"]["consultant"]["calls"] == 2
    assert out["per_archetype"]["consultant"]["successful"] == 1
    assert out["per_archetype"]["long_horizon"]["fallback_used"] == 1


def test_collect_diagnostics_archetype_filter(monkeypatch, tmp_path):
    live_root = tmp_path / ".hermes" / "cache" / "delegation" / "live"
    live_root.mkdir(parents=True)
    monkeypatch.setattr("router.Path.home", lambda: tmp_path)

    _make_deleg(live_root, "deleg_aaa", "consultant")
    _make_deleg(live_root, "deleg_bbb", "long_horizon")

    out = router._collect_diagnostics(archetype="consultant")
    assert "consultant" in out["per_archetype"]
    assert "long_horizon" not in out["per_archetype"]


def test_collect_diagnostics_window_skips_old(monkeypatch, tmp_path):
    live_root = tmp_path / ".hermes" / "cache" / "delegation" / "live"
    live_root.mkdir(parents=True)
    monkeypatch.setattr("router.Path.home", lambda: tmp_path)

    # Old deleg (2 hours ago) — backdate mtime so the window filter skips it
    old_id = "deleg_old"
    _make_deleg(live_root, old_id, "consultant",
                started_at=time.time() - 7200,
                ended_at=time.time() - 7100)
    _set_mtime(live_root / old_id / "manifest.json", time.time() - 7200)
    # Recent deleg
    _make_deleg(live_root, "deleg_new", "consultant")

    out = router._collect_diagnostics(since="1h")
    assert out["totals"]["total_calls"] == 1


def test_collect_diagnostics_handler_invoked_via_build_all():
    tools = router._build_all()
    assert "delegate_task_diagnostics" in tools
    schema, handler = tools["delegate_task_diagnostics"]
    assert schema["properties"]["archetype"]["type"] == "string"
    assert schema["properties"]["since"]["default"] == "1h"
    assert callable(handler)


def test_collect_diagnostics_parses_window():
    from router import _collect_diagnostics as _cd  # noqa: F401
    # Smoke: window parsing handles 1h, 30m, 90s, bare
    for w in ("1h", "30m", "90s", "120"):
        out = _cd(since=w)
        assert "window_sec" in out