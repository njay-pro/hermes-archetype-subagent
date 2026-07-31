"""Hermes Subagent Dashboard — stdlib-only web preview pane for live delegations.

v1.0.0 — Archetype-aware visual language. Editorial typography meets
control-room density. Each delegation gets a card with archetype color
rail, eyebrow + serif goal headline, model/duration/skills meta strip,
and a live event stream when expanded. Per-archetype swatches:
  consultant #5B3422  long_horizon #4A6B7C  high_hallucination #B85C38
  speedster_internal #6B8E5A  speedster_internet #5E7FA8

Reads `~/.hermes/cache/delegation/live/*/manifest.json` + `meta.json`
+ `task-*.log` files. Plugin-supplied delegations include a sibling
meta.json with archetype/model/provider; native delegations fall back
to graceful defaults (no archetype = neutral, no model = hidden).

Run:
    python dashboard.py             # serves on http://127.0.0.1:8765
    python dashboard.py --port 9000 # custom port

Dependencies: zero. Python 3.9+ stdlib only.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional

# ─── Config ─────────────────────────────────────────────────────────────

def _resolve_dashboard_home() -> Path:
    env_home = os.environ.get("HERMES_HOME", "").strip()
    if env_home:
        return Path(env_home)
    profile = os.environ.get("HERMES_PROFILE", "").strip()
    if profile:
        default = Path.home() / ".hermes"
        if sys.platform == "win32":
            local_appdata = os.environ.get("LOCALAPPDATA", "").strip()
            if local_appdata:
                default = Path(local_appdata) / "hermes"
        return default / "profiles" / profile
    return Path.home() / ".hermes"


HERMES_HOME = _resolve_dashboard_home()
LIVE_DIR = HERMES_HOME / "cache" / "delegation" / "live"
DEFAULT_PORT = 8765
SSE_POLL_INTERVAL_SECS = 1.0

# ─── Data model ─────────────────────────────────────────────────────────

@dataclass
class LogEvent:
    timestamp: str
    kind: str
    text: str

    def to_dict(self) -> Dict[str, str]:
        return {"timestamp": self.timestamp, "kind": self.kind, "text": self.text}


@dataclass
class Task:
    index: int
    goal: str
    log_path: Path
    status: str
    log_offset: int = 0
    events: List[LogEvent] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "index": self.index,
            "goal": self.goal,
            "log_path": str(self.log_path),
            "status": self.status,
            "events": [e.to_dict() for e in self.events],
        }


@dataclass
class Delegation:
    id: str
    started_at: str
    task_count: int
    completed_at: Optional[str]
    status: str
    exit_reason: Optional[str]
    archetype: Optional[str] = None
    model: Optional[str] = None
    provider: Optional[str] = None
    dir_path: Path = field(default_factory=lambda: Path("."))
    tasks: List[Task] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "task_count": self.task_count,
            "status": self.status,
            "exit_reason": self.exit_reason,
            "archetype": self.archetype,
            "model": self.model,
            "provider": self.provider,
            "tasks": [t.to_dict() for t in self.tasks],
        }


# ─── Log parser ─────────────────────────────────────────────────────────

LOG_LINE_RE = re.compile(
    r"^(?P<ts>\d{2}:\d{2}:\d{2})\s+(?P<kind>[a-zA-Z_]+)\s*\|\s*(?P<text>.*)$"
)


def parse_log_line(line: str) -> Optional[LogEvent]:
    m = LOG_LINE_RE.match(line)
    if not m:
        return None
    return LogEvent(
        timestamp=m.group("ts"),
        kind=m.group("kind").strip().lower(),
        text=m.group("text"),
    )


def read_new_events(task: Task) -> int:
    if not task.log_path.is_file():
        return 0
    try:
        with task.log_path.open("r", encoding="utf-8", errors="replace") as fh:
            fh.seek(task.log_offset)
            new_data = fh.read()
            task.log_offset = fh.tell()
    except OSError:
        return 0
    if not new_data:
        return 0
    added = 0
    for raw in new_data.splitlines():
        if not raw.strip():
            continue
        ev = parse_log_line(raw)
        if ev is not None:
            task.events.append(ev)
            added += 1
        elif task.events:
            task.events[-1].text += "\n" + raw
    return added


def _overall_status(tasks: List[Task]) -> str:
    if not tasks:
        return "unknown"
    statuses = {t.status for t in tasks}
    if "running" in statuses:
        return "running"
    if "failed" in statuses:
        return "failed"
    if statuses == {"completed"}:
        return "completed"
    return "mixed"


def load_manifest(d: Path) -> Optional[Delegation]:
    manifest_path = d / "manifest.json"
    if not manifest_path.is_file():
        return None
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    tasks: List[Task] = []
    for t in data.get("tasks", []) or []:
        tasks.append(
            Task(
                index=int(t.get("index", 0)),
                goal=str(t.get("goal", "")),
                log_path=Path(t.get("log", str(d / f"task-{t.get('index', 0)}.log"))),
                status=str(t.get("status", "unknown")),
            )
        )
    # Plugin-supplied meta.json (v1.0.0+)
    archetype = model = provider = None
    meta_path = d / "meta.json"
    if meta_path.is_file():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            archetype = meta.get("archetype")
            model = meta.get("model")
            provider = meta.get("provider")
        except (OSError, json.JSONDecodeError):
            pass
    return Delegation(
        id=data.get("delegation_id", d.name),
        started_at=data.get("started", ""),
        task_count=int(data.get("task_count", len(tasks))),
        completed_at=data.get("completed"),
        status=_overall_status(tasks),
        exit_reason=data.get("exit_reason"),
        archetype=archetype,
        model=model,
        provider=provider,
        dir_path=d,
        tasks=tasks,
    )


def refresh_delegation(deleg: Delegation) -> Delegation:
    fresh = load_manifest(deleg.dir_path)
    if fresh is not None:
        old_by_idx = {t.index: t for t in deleg.tasks}
        for t in fresh.tasks:
            old = old_by_idx.get(t.index)
            if old is not None:
                t.log_offset = old.log_offset
                t.events = old.events
                read_new_events(t)
        deleg.tasks = fresh.tasks
        deleg.status = fresh.status
        deleg.completed_at = fresh.completed_at
        deleg.exit_reason = fresh.exit_reason
        deleg.archetype = fresh.archetype
        deleg.model = fresh.model
        deleg.provider = fresh.provider
    else:
        for t in deleg.tasks:
            read_new_events(t)
    return deleg


def scan_live_dir() -> List[Delegation]:
    if not LIVE_DIR.is_dir():
        return []
    delegs: List[Delegation] = []
    for child in LIVE_DIR.iterdir():
        if not child.is_dir():
            continue
        d = load_manifest(child)
        if d is not None:
            delegs.append(d)
    delegs.sort(key=lambda d: d.started_at or "", reverse=True)
    return delegs


# ─── HTML page (v1.0.0 — archetype-aware) ───────────────────────────────

HTML_PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Hermes Subagent Dashboard</title>
<style>
  :root {
    --bg: #0E0D0C;
    --bg-elev: #161412;
    --bg-card: #1B1815;
    --bg-card-active: #221E1B;
    --fg: #E8E3DC;
    --fg-mid: #B5AFA5;
    --fg-dim: #8A847B;
    --fg-mute: #5C5750;
    --accent: #5B3422;
    --accent-2: #6D4530;
    --accent-glow: rgba(91, 52, 34, 0.18);
    --border: #2A2624;
    --border-soft: #1F1C1A;
    --border-strong: #3D352E;

    /* archetype swatches */
    --c-consultant: #5B3422;
    --c-longhorizon: #4A6B7C;
    --c-creative: #B85C38;
    --c-speed-internal: #6B8E5A;
    --c-speed-internet: #5E7FA8;

    /* status (kept distinct from archetype colors) */
    --ok: #6B8E5A;
    --warn: #C9A047;
    --err: #C05050;

    --font-display: ui-serif, "New York", "Charter", "Iowan Old Style", Georgia, serif;
    --font-ui: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Inter", system-ui, sans-serif;
    --font-mono: ui-monospace, "SF Mono", "JetBrains Mono", Menlo, Consolas, monospace;
  }

  * { box-sizing: border-box; }
  html, body { margin: 0; padding: 0; height: 100%; background: var(--bg); color: var(--fg); }
  body {
    font-family: var(--font-ui);
    font-size: 13px;
    line-height: 1.5;
    -webkit-font-smoothing: antialiased;
    -moz-osx-font-smoothing: grayscale;
  }

  /* ── Header ─────────────────────────────────────── */
  header {
    position: sticky; top: 0; z-index: 10;
    background: var(--bg-elev);
    border-bottom: 1px solid var(--border);
    padding: 12px 24px;
    display: flex; align-items: center; gap: 16px;
  }
  header .wordmark {
    font-family: var(--font-display);
    font-size: 16px;
    font-weight: 600;
    letter-spacing: -0.01em;
    color: var(--fg);
  }
  header .wordmark .accent { color: var(--accent); }
  header .stats {
    display: flex; gap: 18px;
    color: var(--fg-dim); font-size: 11px;
    font-family: var(--font-mono);
    letter-spacing: 0.04em;
  }
  header .stats b {
    color: var(--fg); font-weight: 600; margin-left: 4px;
    font-variant-numeric: tabular-nums;
  }
  header .stats .dot {
    display: inline-block; width: 6px; height: 6px; border-radius: 50%;
    margin-right: 5px; vertical-align: middle;
  }
  header .stats .dot.live {
    background: var(--ok); animation: pulse 2.4s ease-in-out infinite;
  }
  header .stats .dot.warn {
    background: var(--warn); animation: pulse 1.4s ease-in-out infinite;
  }
  header .stats .dot.err { background: var(--err); }
  header .stats .dot.dim { background: var(--fg-mute); }

  header .legend {
    margin-left: auto;
    display: flex; gap: 8px;
  }
  header .legend .chip {
    display: inline-flex; align-items: center; gap: 6px;
    padding: 4px 9px;
    border-radius: 999px;
    background: transparent;
    border: 1px solid var(--border);
    color: var(--fg-dim);
    font-size: 11px;
    cursor: pointer;
    user-select: none;
    transition: all 150ms ease;
  }
  header .legend .chip:hover { color: var(--fg); border-color: var(--border-strong); }
  header .legend .chip.on { color: var(--fg); border-color: var(--border-strong); }
  header .legend .chip .glyph { font-family: var(--font-mono); font-size: 12px; }
  header .legend .chip[data-arch="consultant"] .glyph { color: var(--c-consultant); }
  header .legend .chip[data-arch="long_horizon"] .glyph { color: var(--c-longhorizon); }
  header .legend .chip[data-arch="high_hallucination"] .glyph { color: var(--c-creative); }
  header .legend .chip[data-arch="speedster_internal"] .glyph { color: var(--c-speed-internal); }
  header .legend .chip[data-arch="speedster_internet"] .glyph { color: var(--c-speed-internet); }
  header .legend .chip[data-arch="__native__"] .glyph { color: var(--fg-dim); }

  /* ── Column ─────────────────────────────────────── */
  main {
    max-width: 880px;
    margin: 0 auto;
    padding: 32px 24px 80px;
  }
  .section-head {
    display: flex; align-items: baseline; gap: 12px;
    margin: 40px 0 14px;
  }
  .section-head:first-child { margin-top: 8px; }
  .section-head h2 {
    margin: 0;
    font-family: var(--font-display);
    font-size: 17px; font-weight: 600;
    letter-spacing: -0.005em;
    color: var(--fg-mid);
  }
  .section-head .rule {
    flex: 1; height: 1px;
    background: var(--border-soft);
  }
  .section-head .count {
    font-family: var(--font-mono);
    font-size: 11px;
    color: var(--fg-dim);
    letter-spacing: 0.06em;
  }

  /* ── Delegation card ───────────────────────────── */
  .card {
    position: relative;
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 18px 20px 16px 22px;
    margin-bottom: 12px;
    cursor: pointer;
    transition: background 150ms ease, border-color 150ms ease, transform 150ms ease;
    overflow: hidden;
  }
  .card:hover {
    background: var(--bg-card-active);
    border-color: var(--border-strong);
  }
  .card.active {
    border-color: var(--accent-2);
    background: var(--bg-card-active);
  }
  /* archetype rail — left edge */
  .card::before {
    content: "";
    position: absolute;
    left: 0; top: 0; bottom: 0;
    width: 4px;
    background: var(--rail-color, var(--fg-mute));
    border-top-left-radius: 12px;
    border-bottom-left-radius: 12px;
  }
  .card.active::before { width: 6px; }
  .card[data-arch="consultant"] { --rail-color: var(--c-consultant); }
  .card[data-arch="long_horizon"] { --rail-color: var(--c-longhorizon); }
  .card[data-arch="high_hallucination"] { --rail-color: var(--c-creative); }
  .card[data-arch="speedster_internal"] { --rail-color: var(--c-speed-internal); }
  .card[data-arch="speedster_internet"] { --rail-color: var(--c-speed-internet); }
  .card[data-arch="__native__"] { --rail-color: var(--fg-mute); }

  .eyebrow {
    display: flex; align-items: center; gap: 10px;
    font-family: var(--font-mono);
    font-size: 10.5px;
    font-weight: 600;
    letter-spacing: 0.10em;
    text-transform: uppercase;
    color: var(--fg-dim);
    margin-bottom: 6px;
  }
  .eyebrow .glyph { font-size: 13px; }
  .card[data-arch="consultant"] .eyebrow .glyph { color: var(--c-consultant); }
  .card[data-arch="long_horizon"] .eyebrow .glyph { color: var(--c-longhorizon); }
  .card[data-arch="high_hallucination"] .eyebrow .glyph { color: var(--c-creative); }
  .card[data-arch="speedster_internal"] .eyebrow .glyph { color: var(--c-speed-internal); }
  .card[data-arch="speedster_internet"] .eyebrow .glyph { color: var(--c-speed-internet); }

  .eyebrow .archetype {
    color: var(--rail-color, var(--fg-mid));
    text-transform: uppercase;
  }
  .eyebrow .id { color: var(--fg-mute); font-weight: 500; }
  .eyebrow .status { margin-left: auto; }

  .badge {
    display: inline-flex; align-items: center; gap: 5px;
    padding: 2px 7px;
    border-radius: 3px;
    font-family: var(--font-mono);
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 0.06em;
    text-transform: uppercase;
  }
  .badge.running { background: rgba(201, 160, 71, 0.18); color: var(--warn); }
  .badge.completed { background: rgba(107, 142, 90, 0.18); color: var(--ok); }
  .badge.failed { background: rgba(192, 80, 80, 0.18); color: var(--err); }
  .badge.unknown, .badge.mixed { background: rgba(138, 132, 123, 0.18); color: var(--fg-dim); }
  .badge .dot {
    display: inline-block; width: 5px; height: 5px; border-radius: 50%;
    background: currentColor;
  }
  .badge.running .dot { animation: pulse 1.4s ease-in-out infinite; }

  .goal {
    font-family: var(--font-display);
    font-size: 17px;
    line-height: 1.35;
    color: var(--fg);
    letter-spacing: -0.005em;
    margin: 4px 0 10px;
    overflow: hidden;
    text-overflow: ellipsis;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
  }
  .card.active .goal {
    -webkit-line-clamp: unset;
    display: block;
  }

  .meta {
    display: flex; flex-wrap: wrap; gap: 14px;
    font-family: var(--font-mono);
    font-size: 11px;
    color: var(--fg-dim);
    letter-spacing: 0.02em;
  }
  .meta .k { color: var(--fg-mute); margin-right: 4px; }
  .meta .v { color: var(--fg-mid); font-variant-numeric: tabular-nums; }

  /* ── Inline transcript (expanded card) ─────────── */
  .transcript {
    display: none;
    margin-top: 16px;
    padding-top: 14px;
    border-top: 1px solid var(--border-soft);
  }
  .card.active .transcript { display: block; }
  .transcript .row {
    display: grid;
    grid-template-columns: 68px 80px 1fr;
    gap: 10px;
    padding: 3px 0;
    font-family: var(--font-mono);
    font-size: 12px;
    line-height: 1.55;
    border-bottom: 1px solid var(--border-soft);
  }
  .transcript .row:last-child { border-bottom: none; }
  .transcript .ts { color: var(--fg-mute); font-variant-numeric: tabular-nums; }
  .transcript .kind {
    color: var(--fg-mid);
    font-weight: 600;
    text-transform: lowercase;
  }
  .transcript .kind.start, .transcript .kind.user { color: var(--accent-2); }
  .transcript .kind.think, .transcript .kind.assistant, .transcript .kind.final { color: var(--fg-mid); }
  .transcript .kind.tool, .transcript .kind.tool_call { color: var(--c-speed-internal); }
  .transcript .kind.result { color: var(--c-longhorizon); }
  .transcript .kind.error { color: var(--err); }
  .transcript .kind.meta { color: var(--c-speed-internet); }
  .transcript .text {
    color: var(--fg);
    white-space: pre-wrap;
    word-break: break-word;
    overflow-x: auto;
  }
  .transcript .empty {
    color: var(--fg-dim);
    font-style: italic;
    padding: 16px 0;
    font-family: var(--font-ui);
    font-size: 12px;
  }

  /* ── Empty state ───────────────────────────────── */
  .empty-state {
    text-align: center;
    padding: 80px 24px;
    color: var(--fg-dim);
  }
  .empty-state .head {
    font-family: var(--font-display);
    font-size: 18px;
    font-style: italic;
    color: var(--fg-mid);
    margin-bottom: 6px;
  }
  .empty-state .sub {
    font-family: var(--font-mono);
    font-size: 11px;
    letter-spacing: 0.06em;
    color: var(--fg-mute);
  }

  /* ── Error toast (bottom-right, dismissible) ───── */
  #err-toast {
    position: fixed; bottom: 16px; right: 16px; z-index: 50;
    background: var(--bg-card);
    border: 1px solid var(--err);
    border-radius: 6px;
    padding: 10px 14px;
    color: var(--err);
    font-family: var(--font-mono);
    font-size: 11px;
    max-width: 380px;
    box-shadow: 0 4px 16px rgba(0, 0, 0, 0.4);
    display: none;
  }
  #err-toast.show { display: block; }
  #err-toast .x {
    float: right; cursor: pointer; color: var(--fg-dim);
    margin-left: 12px;
  }

  /* ── Animations ────────────────────────────────── */
  @keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.4; }
  }
</style>
</head>
<body>
<header>
  <div class="wordmark"><span class="accent">◆</span>&nbsp;Hermes Subagents</div>
  <div class="stats">
    <span><span class="dot dim"></span><span>Total</span> <b id="stat-total">0</b></span>
    <span><span class="dot warn"></span><span>Running</span> <b id="stat-running">0</b></span>
    <span><span class="dot live"></span><span>Done</span> <b id="stat-completed">0</b></span>
    <span><span class="dot err"></span><span>Failed</span> <b id="stat-failed">0</b></span>
  </div>
  <div class="legend" id="legend">
    <span class="chip on" data-arch="consultant"><span class="glyph">◆</span><span>consultant</span></span>
    <span class="chip on" data-arch="long_horizon"><span class="glyph">☰</span><span>long_horizon</span></span>
    <span class="chip on" data-arch="high_hallucination"><span class="glyph">✦</span><span>creative</span></span>
    <span class="chip on" data-arch="speedster_internal"><span class="glyph">▣</span><span>speedster/int</span></span>
    <span class="chip on" data-arch="speedster_internet"><span class="glyph">◌</span><span>speedster/net</span></span>
    <span class="chip on" data-arch="__native__"><span class="glyph">◇</span><span>native</span></span>
  </div>
</header>
<main id="main">
  <div class="empty-state">
    <div class="head">No delegations yet</div>
    <div class="sub">Waiting for the next dispatch from the orchestrator</div>
  </div>
</main>
<div id="err-toast"><span class="x" onclick="document.getElementById('err-toast').classList.remove('show')">✕</span><span id="err-toast-text"></span></div>

<script>
(function() {
  // ── Error visibility (toast, not sticky) ─────────
  function showError(msg) {
    var t = document.getElementById('err-toast');
    document.getElementById('err-toast-text').textContent = msg;
    t.classList.add('show');
    setTimeout(function() { t.classList.remove('show'); }, 5000);
    console.error(msg);
  }
  window.addEventListener('error', function(e) {
    showError(e.message + ' @ ' + e.filename + ':' + e.lineno);
  });
  window.addEventListener('unhandledrejection', function(e) {
    showError('Promise: ' + (e.reason && e.reason.message || e.reason));
  });

  // ── Constants ───────────────────────────────────
  var ARCH_GLYPH = {
    consultant: '◆',
    long_horizon: '☰',
    high_hallucination: '✦',
    speedster_internal: '▣',
    speedster_internet: '◌',
    __native__: '◇'
  };
  var ARCH_LABEL = {
    consultant: 'Frontier · Consultant',
    long_horizon: 'Workhorse · Long Horizon',
    high_hallucination: 'Lateral · Creative',
    speedster_internal: 'Quick · Speedster/Internal',
    speedster_internet: 'Quick · Speedster/Internet',
    __native__: 'Native · Delegate'
  };

  // ── State ───────────────────────────────────────
  var state = {
    delegs: [],
    selectedId: null,
    filter: { consultant: true, long_horizon: true, high_hallucination: true, speedster_internal: true, speedster_internet: true, __native__: true },
    eventSource: null,
  };

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function(c) {
      return ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'})[c];
    });
  }

  function fmtDuration(d) {
    if (!d || d < 0) return '—';
    if (d < 60) return d.toFixed(1) + 's';
    var m = Math.floor(d / 60), s = Math.floor(d % 60);
    if (m < 60) return m + 'm ' + s + 's';
    var h = Math.floor(m / 60), mm = m % 60;
    return h + 'h ' + mm + 'm';
  }
  function durationFor(d) {
    if (!d.started_at) return null;
    var start = new Date(d.started_at.replace(' ', 'T')).getTime();
    if (isNaN(start)) return null;
    var end = d.completed_at ? new Date(d.completed_at.replace(' ', 'T')).getTime() : Date.now();
    return (end - start) / 1000;
  }
  function eventCount(d) {
    var n = 0;
    (d.tasks || []).forEach(function(t) { n += (t.events || []).length; });
    return n;
  }
  function taskCount(d) {
    return (d.tasks && d.tasks.length) || d.task_count || 1;
  }
  function weightOf(d) {
    var n = eventCount(d);
    var dur = durationFor(d) || 0;
    if (n > 80 || dur > 600) return 'heavy';
    if (n > 20) return 'medium';
    return 'light';
  }
  function archKey(d) {
    var a = d.archetype;
    if (a && ARCH_GLYPH[a]) return a;
    return '__native__';
  }
  function shortId(id) {
    if (!id) return '—';
    var m = /deleg_([0-9a-f]+)/.exec(id);
    return m ? m[1].slice(0, 6) : id.slice(0, 8);
  }
  function shortGoal(g) {
    if (!g) return '(no goal)';
    return g.length > 220 ? g.slice(0, 217) + '…' : g;
  }
  function sectionLabel(started) {
    if (!started) return 'Earlier';
    var t = new Date(started.replace(' ', 'T'));
    if (isNaN(t.getTime())) return 'Earlier';
    var now = new Date();
    var diffMs = now - t;
    var sameDay = t.toDateString() === now.toDateString();
    var yesterday = new Date(now); yesterday.setDate(now.getDate() - 1);
    var sameYest = t.toDateString() === yesterday.toDateString();
    if (sameDay) return 'Today';
    if (sameYest) return 'Yesterday';
    if (diffMs < 7 * 86400e3) return 'Earlier this week';
    return 'Older';
  }

  // ── Render ──────────────────────────────────────
  function statusBadge(s) {
    var known = ['running','completed','failed','mixed','unknown'];
    var cls = known.indexOf(s) >= 0 ? s : 'unknown';
    return '<span class="badge ' + cls + '"><span class="dot"></span>' + esc(s) + '</span>';
  }

  function renderMain() {
    var main = document.getElementById('main');
    var filtered = state.delegs.filter(function(d) { return state.filter[archKey(d)]; });
    if (filtered.length === 0) {
      main.innerHTML = '<div class="empty-state"><div class="head">No delegations match</div><div class="sub">Toggle a chip in the header to widen the filter</div></div>';
      return;
    }
    // group by section label
    var groups = {};
    var order = [];
    filtered.forEach(function(d) {
      var k = sectionLabel(d.started_at);
      if (!groups[k]) { groups[k] = []; order.push(k); }
      groups[k].push(d);
    });
    var html = '';
    order.forEach(function(k) {
      html += '<div class="section-head"><h2>' + esc(k) + '</h2><span class="rule"></span><span class="count">' + groups[k].length + '</span></div>';
      groups[k].forEach(function(d) { html += renderCard(d); });
    });
    main.innerHTML = html;
    // wire click handlers
    Array.prototype.forEach.call(main.querySelectorAll('.card'), function(el) {
      el.addEventListener('click', function(e) {
        if (e.target.closest('a')) return;
        selectDeleg(el.getAttribute('data-id'));
      });
    });
    updateStats();
  }

  function renderCard(d) {
    var ak = archKey(d);
    var glyph = ARCH_GLYPH[ak] || '◇';
    var label = ARCH_LABEL[ak] || 'Native';
    var isActive = d.id === state.selectedId;
    var dur = fmtDuration(durationFor(d));
    var evc = eventCount(d);
    var tc = taskCount(d);
    var w = weightOf(d);
    var model = d.model || '—';
    var id = shortId(d.id);
    var html = '';
    html += '<div class="card ' + (isActive ? 'active' : '') + '" data-id="' + esc(d.id) + '" data-arch="' + esc(ak) + '">';
    html +=   '<div class="eyebrow">';
    html +=     '<span class="glyph">' + glyph + '</span>';
    html +=     '<span class="archetype">' + esc(label) + '</span>';
    html +=     '<span class="id">· ' + esc(id) + '</span>';
    html +=     '<span class="status">' + statusBadge(d.status) + '</span>';
    html +=   '</div>';
    html +=   '<div class="goal">' + esc(shortGoal((d.tasks && d.tasks[0]) ? d.tasks[0].goal : '')) + '</div>';
    html +=   '<div class="meta">';
    html +=     '<span><span class="k">model</span><span class="v">' + esc(model) + '</span></span>';
    html +=     '<span><span class="k">dur</span><span class="v">' + esc(dur) + '</span></span>';
    html +=     '<span><span class="k">events</span><span class="v">' + evc + '</span></span>';
    if (tc > 1) html += '<span><span class="k">tasks</span><span class="v">' + tc + '</span></span>';
    html +=     '<span><span class="k">weight</span><span class="v">' + w + '</span></span>';
    html +=   '</div>';
    html +=   '<div class="transcript">';
    html +=     renderTranscript(d);
    html +=   '</div>';
    html += '</div>';
    return html;
  }

  function renderTranscript(d) {
    if (!d.tasks || d.tasks.length === 0) return '<div class="empty">No transcript yet…</div>';
    var html = '';
    d.tasks.forEach(function(t) {
      if (d.tasks.length > 1) {
        html += '<div class="row" style="grid-template-columns: 1fr;"><div class="ts" style="color:var(--accent-2); font-weight:600;">── task ' + t.index + ' ──</div></div>';
      }
      var evs = t.events || [];
      if (evs.length === 0) {
        html += '<div class="empty">No events yet…</div>';
      } else {
        evs.forEach(function(e) {
          html += '<div class="row">';
          html +=   '<span class="ts">' + esc(e.timestamp || '??:??:??') + '</span>';
          html +=   '<span class="kind">' + esc(e.kind) + '</span>';
          html +=   '<span class="text">' + esc(e.text) + '</span>';
          html += '</div>';
        });
      }
    });
    return html;
  }

  function updateStats() {
    var all = state.delegs;
    document.getElementById('stat-total').textContent = all.length;
    document.getElementById('stat-running').textContent = all.filter(function(d){return d.status==='running';}).length;
    document.getElementById('stat-completed').textContent = all.filter(function(d){return d.status==='completed';}).length;
    document.getElementById('stat-failed').textContent = all.filter(function(d){return d.status==='failed';}).length;
  }

  // ── Selection / streaming ───────────────────────
  function selectDeleg(id) {
    if (id === state.selectedId) {
      // toggle off
      state.selectedId = null;
      if (state.eventSource) { state.eventSource.close(); state.eventSource = null; }
      renderMain();
      return;
    }
    state.selectedId = id;
    if (state.eventSource) { state.eventSource.close(); state.eventSource = null; }
    renderMain();
    // scroll the selected card into view
    var el = document.querySelector('.card[data-id="' + cssEscape(id) + '"]');
    if (el) el.scrollIntoView({block:'start', behavior:'smooth'});
    state.eventSource = new EventSource('/d/' + encodeURIComponent(id) + '/stream');
    state.eventSource.onmessage = function(ev) {
      try {
        var deleg = JSON.parse(ev.data);
        var i = state.delegs.findIndex(function(x){return x.id === deleg.id;});
        if (i >= 0) state.delegs[i] = deleg; else state.delegs.unshift(deleg);
        renderMain();
      } catch (e) { showError('SSE parse: ' + e.message); }
    };
    state.eventSource.onerror = function() { /* browser auto-reconnects */ };
  }

  function cssEscape(s) {
    if (window.CSS && CSS.escape) return CSS.escape(s);
    return String(s).replace(/[^a-zA-Z0-9_-]/g, function(c){return '\\' + c;});
  }

  // ── Filter chips ────────────────────────────────
  Array.prototype.forEach.call(document.querySelectorAll('#legend .chip'), function(chip) {
    chip.addEventListener('click', function() {
      var k = chip.getAttribute('data-arch');
      state.filter[k] = !state.filter[k];
      chip.classList.toggle('on', state.filter[k]);
      renderMain();
    });
  });

  // ── Polling ─────────────────────────────────────
  function refresh() {
    fetch('/api/delegations')
      .then(function(r) { return r.json(); })
      .then(function(delegs) {
        // Preserve selected task event offsets by deep-merging events from the selected SSE
        state.delegs = delegs;
        renderMain();
      })
      .catch(function(e) { showError('list fetch: ' + e.message); });
  }
  refresh();
  setInterval(refresh, 3000);
})();
</script>
</body>
</html>
"""

# ─── HTTP server ───────────────────────────────────────────────────────

class DashboardHandler(BaseHTTPRequestHandler):
    server_version = "HermesSubagentDashboard/1.0.0"

    def log_message(self, format, *args):
        return  # quiet

    def do_GET(self):
        path = self.path
        if path == "/" or path == "/index.html":
            self._send_html(HTML_PAGE)
        elif path == "/api/delegations":
            self._send_json(self._scan_state())
        elif path.startswith("/api/delegations/"):
            did = path[len("/api/delegations/"):]
            self._send_json(self._delegation_state(did))
        elif path.startswith("/d/") and path.endswith("/stream"):
            did = path[len("/d/"):-len("/stream")].rstrip("/")
            self._send_sse_stream(did)
        else:
            self.send_error(404, "Not Found")

    def _scan_state(self) -> List[Dict[str, Any]]:
        return [d.to_dict() for d in scan_live_dir()]

    def _delegation_state(self, did: str) -> Dict[str, Any]:
        d_path = LIVE_DIR / did
        if not d_path.is_dir():
            return {"error": "delegation not found: " + did}
        deleg = load_manifest(d_path)
        if deleg is None:
            return {"error": "manifest missing or malformed: " + did}
        refresh_delegation(deleg)
        return deleg.to_dict()

    def _send_html(self, body: str):
        data = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_json(self, obj: Any):
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)

    def _send_sse_stream(self, did: str):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

        d_path = LIVE_DIR / did
        if not d_path.is_dir():
            self._sse_write({"error": "delegation not found: " + did})
            return
        deleg = load_manifest(d_path)
        if deleg is None:
            self._sse_write({"error": "manifest missing or malformed: " + did})
            return

        last_payload = None
        try:
            while True:
                refresh_delegation(deleg)
                payload = deleg.to_dict()
                if payload != last_payload:
                    self._sse_write(payload)
                    last_payload = payload
                if deleg.status in ("completed", "failed"):
                    fully_read = True
                    for t in deleg.tasks:
                        if t.log_path.exists():
                            try:
                                if t.log_offset < t.log_path.stat().st_size:
                                    fully_read = False
                                    break
                            except OSError:
                                pass
                    if fully_read:
                        self.wfile.write(b"event: done\ndata: {}\\n\\n")
                        self.wfile.flush()
                        break
                time.sleep(SSE_POLL_INTERVAL_SECS)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:
            try:
                self._sse_write({"error": "stream crashed: " + str(e)})
            except Exception:
                pass

    def _sse_write(self, obj: Any):
        data = json.dumps(obj, ensure_ascii=False)
        self.wfile.write(("data: " + data + "\n\n").encode("utf-8"))
        self.wfile.flush()


# ─── Entry point ────────────────────────────────────────────────────────

def main(argv: Optional[List[str]] = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(
        description="Hermes Subagent Dashboard — read-only web preview of live delegations",
    )
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args(argv)

    if not LIVE_DIR.is_dir():
        print("[dashboard] " + str(LIVE_DIR) + " does not exist yet", file=sys.stderr)

    server = ThreadingHTTPServer((args.host, args.port), DashboardHandler)
    print("[dashboard] serving http://" + args.host + ":" + str(args.port) + "/", file=sys.stderr)
    print("[dashboard] watching " + str(LIVE_DIR), file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[dashboard] shutting down", file=sys.stderr)
        server.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
