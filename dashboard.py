"""Hermes Subagent Dashboard — stdlib-only web preview pane for live delegations.

Reads `~/.hermes/cache/delegation/live/*/manifest.json` + `task-*.log` files
and renders them in a single-page web app. Works for native `delegate_task`
and any plugin-constructed child (e.g. archetype-router) — both write to
the same on-disk format.

Run:
    python dashboard.py             # serves on http://127.0.0.1:8765
    python dashboard.py --port 9000 # custom port

Dependencies: zero. Python 3.9+ stdlib only.

v0.3.2 — bundled with the archetype-router plugin, but works for any
subagent that writes to `~/.hermes/cache/delegation/live/`. See
DASHBOARD_PLAN.md for the design rationale.
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

# ─── Config ──────────────────────────────────────────────────────────────

HERMES_HOME = Path(os.environ.get("HERMES_HOME") or Path.home() / ".hermes")
LIVE_DIR = HERMES_HOME / "cache" / "delegation" / "live"
DEFAULT_PORT = 8765
SSE_POLL_INTERVAL_SECS = 1.0
ACCENT_HEX = "#5B3422"

# ─── Data model ──────────────────────────────────────────────────────────

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
    dir_path: Path
    tasks: List[Task] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "task_count": self.task_count,
            "status": self.status,
            "exit_reason": self.exit_reason,
            "tasks": [t.to_dict() for t in self.tasks],
        }


# ─── Log parser ──────────────────────────────────────────────────────────

# Log line format: "HH:MM:SS <kind>    | <payload>"
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
    """Append any new log lines to task.events. Returns count added.

    Tracks read position in task.log_offset so re-reading is cheap.
    Handles multi-line continuation: if a line doesn't start with a
    timestamp header, append it to the preceding event's text instead of
    discarding it.
    """
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
            # Multi-line continuation of preceding event
            task.events[-1].text += "\n" + raw
            # Counted as 0 new events (just an extension of the last one)
    return added


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
    return Delegation(
        id=data.get("delegation_id", d.name),
        started_at=data.get("started", ""),
        task_count=int(data.get("task_count", len(tasks))),
        completed_at=data.get("completed"),
        status=_overall_status(tasks),
        exit_reason=data.get("exit_reason"),
        dir_path=d,
        tasks=tasks,
    )


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


# ─── HTTP server ─────────────────────────────────────────────────────────

# Single HTML page. Inline CSS + JS. Designed to fail loudly: if any JS
# errors out, the error is shown on the page itself instead of silently
# leaving "Loading..." on screen.
HTML_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Hermes Subagent Dashboard</title>
<style>
  :root {
    --bg: #0e0d0c;
    --bg-elev: #1a1816;
    --bg-elev2: #242120;
    --fg: #e8e3dc;
    --fg-dim: #8a847b;
    --accent: """ + ACCENT_HEX + """;
    --ok: #6b8e5a;
    --warn: #c9a047;
    --err: #c05050;
    --border: #2e2a27;
  }
  * { box-sizing: border-box; }
  html, body { margin: 0; padding: 0; height: 100%; }
  body {
    background: var(--bg);
    color: var(--fg);
    font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI", sans-serif;
    font-size: 13px;
    line-height: 1.5;
  }
  header {
    background: var(--bg-elev);
    border-bottom: 1px solid var(--border);
    padding: 10px 16px;
    display: flex;
    align-items: center;
    gap: 12px;
  }
  header h1 {
    margin: 0;
    font-size: 14px;
    font-weight: 600;
  }
  header .dot {
    width: 8px; height: 8px; border-radius: 50%;
    background: var(--accent);
  }
  header .stats {
    margin-left: auto;
    display: flex;
    gap: 12px;
    color: var(--fg-dim);
    font-size: 11px;
  }
  header .stats b { color: var(--fg); margin-left: 4px; }
  .layout {
    display: grid;
    grid-template-columns: 340px 1fr;
    height: calc(100vh - 42px);
  }
  .timeline {
    background: var(--bg-elev);
    border-right: 1px solid var(--border);
    overflow-y: auto;
  }
  .timeline .item {
    padding: 10px 14px;
    border-bottom: 1px solid var(--border);
    cursor: pointer;
  }
  .timeline .item:hover { background: var(--bg-elev2); }
  .timeline .item.active {
    background: var(--bg-elev2);
    border-left: 3px solid var(--accent);
    padding-left: 11px;
  }
  .timeline .id {
    font-family: ui-monospace, "SF Mono", Menlo, monospace;
    font-size: 11px;
    color: var(--fg-dim);
  }
  .timeline .goal {
    color: var(--fg);
    margin: 4px 0;
    overflow: hidden;
    text-overflow: ellipsis;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
  }
  .timeline .meta {
    display: flex;
    gap: 8px;
    align-items: center;
    font-size: 11px;
    color: var(--fg-dim);
  }
  .badge {
    display: inline-block;
    padding: 1px 6px;
    border-radius: 3px;
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    font-weight: 600;
  }
  .badge.running { background: var(--warn); color: #1a1816; }
  .badge.completed { background: var(--ok); color: #1a1816; }
  .badge.failed { background: var(--err); color: #1a1816; }
  .badge.unknown { background: var(--fg-dim); color: #1a1816; }
  .detail {
    overflow-y: auto;
    padding: 16px 20px;
  }
  .detail .empty {
    color: var(--fg-dim);
    text-align: center;
    padding: 60px 20px;
    font-style: italic;
  }
  .detail .error {
    color: var(--err);
    background: rgba(192, 80, 80, 0.1);
    border: 1px solid var(--err);
    border-radius: 4px;
    padding: 12px 14px;
    margin: 12px 0;
    font-family: ui-monospace, "SF Mono", Menlo, monospace;
    font-size: 12px;
    white-space: pre-wrap;
  }
  .detail .header {
    border-bottom: 1px solid var(--border);
    padding-bottom: 12px;
    margin-bottom: 16px;
  }
  .detail .goal {
    font-size: 15px;
    margin: 0 0 8px 0;
    line-height: 1.4;
  }
  .detail .meta-row {
    display: flex;
    gap: 16px;
    font-size: 11px;
    color: var(--fg-dim);
    font-family: ui-monospace, "SF Mono", Menlo, monospace;
    flex-wrap: wrap;
  }
  .events {
    font-family: ui-monospace, "SF Mono", Menlo, monospace;
    font-size: 12px;
  }
  .event {
    padding: 4px 0;
    border-bottom: 1px solid var(--border);
    white-space: pre-wrap;
    word-break: break-word;
  }
  .event:last-child { border-bottom: none; }
  .event .ts { color: var(--fg-dim); margin-right: 8px; }
  .event .kind {
    display: inline-block;
    width: 80px;
    font-weight: 600;
    color: var(--accent);
  }
</style>
</head>
<body>
<header>
  <span class="dot"></span>
  <h1>Hermes Subagent Dashboard</h1>
  <div class="stats">
    <span>Total: <b id="stat-total">0</b></span>
    <span>Running: <b id="stat-running">0</b></span>
    <span>Completed: <b id="stat-completed">0</b></span>
    <span>Failed: <b id="stat-failed">0</b></span>
  </div>
  <span style="color: var(--fg-dim); margin-left: 16px;" id="clock"></span>
</header>
<div class="layout">
  <div class="timeline" id="timeline">
    <div class="item" style="color: var(--fg-dim); font-style: italic;">Loading...</div>
  </div>
  <div class="detail" id="detail">
    <div class="empty">Select a delegation from the timeline to view live logs</div>
  </div>
</div>
<script>
(function() {
  // === ERROR VISIBILITY ===
  // Show any JS error on the page itself, so the user is never stuck on
  // "Loading..." with no clue what broke.
  function showError(msg) {
    var d = document.getElementById('detail');
    if (!d) return;
    var box = document.createElement('div');
    box.className = 'error';
    box.textContent = '[JS ERROR] ' + msg;
    d.appendChild(box);
    console.error(msg);
  }
  window.addEventListener('error', function(e) {
    showError(e.message + '\\n  at ' + e.filename + ':' + e.lineno + ':' + e.colno);
  });
  window.addEventListener('unhandledrejection', function(e) {
    showError('Unhandled promise rejection: ' + (e.reason && e.reason.message || e.reason));
  });

  // === STATE ===
  var state = {
    delegs: [],
    selectedId: null,
    eventSource: null,
  };

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function(c) {
      return ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'})[c];
    });
  }

  function statusBadge(s) {
    var known = ['running','completed','failed'];
    var cls = known.indexOf(s) >= 0 ? s : 'unknown';
    return '<span class="badge ' + cls + '">' + esc(s) + '</span>';
  }

  function updateStats(delegs) {
    document.getElementById('stat-total').textContent = delegs.length;
    document.getElementById('stat-running').textContent =
      delegs.filter(function(d) { return d.status === 'running'; }).length;
    document.getElementById('stat-completed').textContent =
      delegs.filter(function(d) { return d.status === 'completed'; }).length;
    document.getElementById('stat-failed').textContent =
      delegs.filter(function(d) { return d.status === 'failed'; }).length;
  }

  function renderTimeline() {
    var tl = document.getElementById('timeline');
    if (state.delegs.length === 0) {
      tl.innerHTML = '<div class="item" style="color: var(--fg-dim); font-style: italic;">No delegations yet</div>';
      return;
    }
    var html = '';
    for (var i = 0; i < state.delegs.length; i++) {
      var d = state.delegs[i];
      var goal = (d.tasks && d.tasks[0]) ? d.tasks[0].goal : '(no task)';
      var isActive = d.id === state.selectedId;
      html += '<div class="item' + (isActive ? ' active' : '') + '" data-id="' + esc(d.id) + '">';
      html += '<div class="id">' + esc(d.id) + '</div>';
      html += '<div class="goal">' + esc(goal) + '</div>';
      html += '<div class="meta">' + statusBadge(d.status);
      html += '<span>' + esc(d.started_at || '') + '</span>';
      html += '</div></div>';
    }
    tl.innerHTML = html;
    var items = tl.querySelectorAll('.item');
    for (var j = 0; j < items.length; j++) {
      items[j].addEventListener('click', function(el) {
        return function() { selectDeleg(el.getAttribute('data-id')); };
      }(items[j]));
    }
  }

  function renderDetail(d) {
    var detail = document.getElementById('detail');
    if (!d) {
      detail.innerHTML = '<div class="empty">No delegation selected</div>';
      return;
    }
    if (d.error) {
      detail.innerHTML = '<div class="empty">' + esc(d.error) + '</div>';
      return;
    }
    var task = (d.tasks && d.tasks[0]) ? d.tasks[0] : null;
    var goal = task ? task.goal : '(no task)';
    var evs = task ? task.events : [];
    var evHtml = '';
    for (var i = 0; i < evs.length; i++) {
      var e = evs[i];
      evHtml += '<div class="event">';
      evHtml += '<span class="ts">' + esc(e.timestamp || '??:??:??') + '</span>';
      evHtml += '<span class="kind">' + esc(e.kind) + '</span>';
      evHtml += '<span>' + esc(e.text) + '</span>';
      evHtml += '</div>';
    }
    var meta = '<span>id: ' + esc(d.id) + '</span>';
    meta += statusBadge(d.status);
    meta += '<span>started: ' + esc(d.started_at || '?') + '</span>';
    if (d.completed_at) meta += '<span>completed: ' + esc(d.completed_at) + '</span>';
    if (d.exit_reason) meta += '<span>exit: ' + esc(d.exit_reason) + '</span>';
    detail.innerHTML =
      '<div class="header"><div class="goal">' + esc(goal) + '</div>' +
      '<div class="meta-row">' + meta + '</div></div>' +
      '<div class="events">' + (evHtml || '<div class="empty" style="padding: 30px;">No events yet...</div>') + '</div>';
    detail.scrollTop = detail.scrollHeight;
  }

  function selectDeleg(id) {
    if (id === state.selectedId) return;
    state.selectedId = id;
    renderTimeline();
    if (state.eventSource) { state.eventSource.close(); state.eventSource = null; }
    var detail = document.getElementById('detail');
    detail.innerHTML = '<div class="empty">Loading delegation...</div>';
    state.eventSource = new EventSource('/d/' + encodeURIComponent(id) + '/stream');
    state.eventSource.onmessage = function(ev) {
      try {
        var deleg = JSON.parse(ev.data);
        renderDetail(deleg);
      } catch (e) {
        showError('Failed to parse SSE data: ' + e.message);
      }
    };
    state.eventSource.onerror = function() {
      // Browser will auto-reconnect. Don't spam errors.
    };
  }

  function refreshTimeline() {
    fetch('/api/delegations')
      .then(function(r) { return r.json(); })
      .then(function(delegs) {
        state.delegs = delegs;
        updateStats(delegs);
        renderTimeline();
      })
      .catch(function(e) {
        showError('Failed to load /api/delegations: ' + e.message);
      });
  }

  function updateClock() {
    var el = document.getElementById('clock');
    if (el) el.textContent = new Date().toLocaleTimeString();
  }
  setInterval(updateClock, 1000);
  updateClock();
  setInterval(refreshTimeline, 2000);
  refreshTimeline();
})();
</script>
</body>
</html>
"""


class DashboardHandler(BaseHTTPRequestHandler):
    server_version = "HermesSubagentDashboard/0.3.2"

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
                # Only emit when state actually changed (saves bandwidth)
                if payload != last_payload:
                    self._sse_write(payload)
                    last_payload = payload
                if deleg.status in ("completed", "failed") and not deleg.tasks:
                    break
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


# ─── Entry point ─────────────────────────────────────────────────────────

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
