# Hermes Subagent Dashboard — PLAN

**Status:** plan only, not yet built. Awaiting njaypro's "go" to start.
**Date:** 2026-07-23
**Owner:** njaypro (operator), hermes (build)

---

## Why

The TUI's subagent preview pane doesn't surface plugin-constructed children
(see archetype-router v0.3.2 partial work — register/unregister into native's
`_active_subagents` works, but the TUI's serialization, session DB lookup,
and module-path coupling make a clean fix fragile).

A standalone web dashboard sidesteps all of that. It reads the **live
transcript log files** that hermes-core ALREADY writes for both native and
plugin delegations — the log file format is the contract, and that contract
is stable. The dashboard is a pure reader, not a participant.

## What it does

- **Timeline view** of every delegation (native + plugin + everything else
  that writes to `~/.hermes/cache/delegation/live/`)
- **Detail pane** showing the live transcript of the selected delegation
  (auto-tail mode for running ones)
- **Status indicators** from the manifest: `running` / `completed` / `failed`
- **Goal** (the real goal, not the placeholder the plugin used to write)
- **Started time, duration, model, toolsets, session_id**
- **Auto-prunes** completed delegations older than N days (configurable, default 7)

## What it does NOT do (v0.1 scope)

- ❌ Don't re-implement the TUI's session tree / kill / pause
- ❌ Don't send messages to subagents
- ❌ Don't aggregate across profiles (single user, single Hermes home)
- ❌ Don't write back to hermes-core (read-only)

## Where it lives

`~/Desktop/OMCA-GODMODE/TOOLS/archetype-router/dashboard.py`

Why: archetype-router is the plugin this dashboard was built to support,
and it's about to be open-sourced. Keeping the dashboard inside the plugin
repo means one clone = one install, and the README documents it as
"optional web preview pane." It also keeps the dashboard **outside
omca-godmode** so when we open-source the plugin, the dashboard ships with
it cleanly — no `~/Desktop/OMCA-GODMODE/dashboards/` path to exclude.

The dashboard is log-file-based and plugin-agnostic. It works for native
delegate_task and any future subagent that writes to
`~/.hermes/cache/delegation/live/`. Putting it in the plugin repo is a
distribution choice, not a coupling one.

## Tech stack

- **stdlib only** — `http.server` (or `socketserver` for SSE) + no deps
- **Embedded HTML** — single string in the python file, no templates
- **SSE for live updates** — `text/event-stream` content type, one
  stream per open detail view, server polls `task-*.log` mtime every 1s
  and pushes diffs
- **Theme:** Dark with `#5B3422` warm accent (matches honcho)
- **Port:** `8765`
- **No DB** — read everything from the filesystem on demand

The "anti-overengineering" rule (from your identity card: "minimal
complexity, less dependencies, less headache") applies. fastapi + jinja2 +
htmx is 3 new dependencies for "show me what's running" — overkill.
stdlib only ships.

## File layout

```
archetype-router/
├── README.md                ← add "Optional: web preview pane" section
├── AGENTS.md
├── plugin.yaml
├── router.py
├── archetype_delegate.py
├── archetype_model_config.json
├── archetypes.yaml
├── SOUL_*.md
├── dashboard.py             ← v0.3.2: NEW — stdlib web preview pane
├── tests/
│   └── test_dashboard.py    ← v0.3.2: NEW — sample log dir + HTTP smoke
├── pyproject.toml
├── ... (existing files)
```

**Single file, stdlib only, ~200 LOC.** Embedded HTML in a triple-quoted
string. No templates/, no static/, no separate JS file. CSS is inline.
One `python dashboard.py` to run; one `Ctrl+C` to stop.

## Routes

| Route | Method | Purpose |
|---|---|---|
| `/` | GET | Timeline (all delegations) + auto-refresh via htmx |
| `/d/<delegation_id>` | GET | Detail page (selected delegation) |
| `/d/<delegation_id>/stream` | GET (SSE) | Live transcript updates |
| `/api/delegations` | GET (JSON) | All current delegations as JSON |
| `/api/delegations/<id>` | GET (JSON) | One delegation (status + meta) |

## Data model (in-memory, built on every request)

```python
@dataclass
class Delegation:
    id: str                # "deleg_48d7091b"
    task_count: int
    started_at: str        # ISO timestamp
    completed_at: Optional[str]
    status: str            # "running" | "completed" | "failed"
    exit_reason: Optional[str]
    tasks: List[Task]

@dataclass
class Task:
    index: int
    goal: str              # the REAL goal, not the placeholder
    log_path: str
    status: str
    # Parsed from log lines:
    events: List[LogEvent] # "user", "think", "assistant", "final", etc.

@dataclass
class LogEvent:
    timestamp: str
    kind: str              # "user" | "start" | "think" | "assistant" | "final" | "tool"
    text: str
```

## Reading the log file format

Sample existing log line:
```
16:35:16 final    | status=completed duration=11.85s summary: Native delegate is alive and reachable.
```

Format: `HH:MM:SS <kind>    | <payload>`

The dashboard's `delegate_watcher.py` parses lines into `LogEvent` records.
Streaming = watch file mtime, re-read new bytes, push parsed events to SSE
client.

## v0.1 acceptance criteria

- [ ] `bash scripts/run.sh` starts the server on `http://127.0.0.1:5174`
- [ ] Timeline shows every delegation in `~/.hermes/cache/delegation/live/`
- [ ] Each delegation row shows: id, status, goal (real), started time, duration
- [ ] Click a delegation → detail page shows the full transcript
- [ ] For a running delegation, detail page auto-updates within 2s
- [ ] Theme matches honcho dashboard (dark, `#5B3422` accent)
- [ ] Tests pass (`uv run pytest`)
- [ ] No new hermes-core coupling — only file reads from the cache dir

## Known caveats (from v0.3.2 plugin work)

- **Plugin goals are placeholders.** The plugin writes
  `[consultant] (live transcript)` instead of the real goal. v0.1 of the
  dashboard shows whatever's in the log. The plugin fix is in
  `archetype_delegate.py:_open_live_transcript` — change the placeholder
  to the real `brief` argument. Ship that as a separate v0.3.2 patch
  BEFORE this dashboard, otherwise the dashboard will show
  `[consultant] (live transcript)` for every plugin delegation.
- **Plugin manifests don't get `status=completed` written.** Same
  v0.3.2 patch list — the dashboard's timeline will show plugin
  delegations as "running" forever. Fix is `_unregister_plugin_subagent`
  needs to also update the manifest.

So: **ship the v0.3.2 plugin-side manifest fixes first**, THEN the
dashboard. The dashboard will look broken if the plugin-side is left as is.

## Open questions (before I build)

1. **Port:** `5174` (matches honcho's 5173 pattern) — OK?
2. **Auto-prune threshold:** default 7 days, configurable via env var?
3. **Show all 4 hermes profiles** or **default profile only** with
   profile-switcher dropdown?
4. **Goals placeholder fix in plugin first** (per "Known caveats") or
   ship dashboard with placeholder visible for plugin delegations?
