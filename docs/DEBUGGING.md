# Debugging

> How to read a live delegation, find failures, and tail the transcript.

---

## Live transcript log

Every archetype call produces a log file at:

```
~/.hermes/cache/delegation/live/<delegation_id>/task-<N>.log
```

- `delegation_id` — uuid per Hermes invocation
- `task_index` — 0 for archetype calls (we always have one task per call)

### Watch live progress

```bash
# Find the most recent task log
TASK_LOG=$(find ~/.hermes/cache/delegation/live -name 'task-0.log' | tail -1)

# Tail with pretty-print
tail -f "$TASK_LOG" | jq .
```

### Log entry shape (one event per line, JSONL)

```json
{"ts": "2026-07-22T03:38:14Z", "event": "tool.start", "tool": "read_file", "args": {"path": "/Users/njaypro/..."}}
{"ts": "2026-07-22T03:38:14Z", "event": "tool.end",   "tool": "read_file", "result": "..."}
{"ts": "2026-07-22T03:38:15Z", "event": "model.text.delta", "preview": "Looking at the file..."}
{"ts": "2026-07-22T03:38:16Z", "event": "model.tool_call", "name": "read_file", "args": {...}}
{"ts": "2026-07-22T03:38:17Z", "event": "model.text.delta", "preview": "Now I'll..."}
{"ts": "2026-07-22T03:38:20Z", "event": "subagent.text", "preview": "..."}
{"ts": "2026-07-22T03:38:25Z", "event": "task.complete", "result": "..."}
```

---

## Common failures and fixes

### 1. `ValueError: Cannot resolve delegation provider 'custom:9router'`

The combo isn't registered in Hermes's `custom_providers.0.models`:

```bash
hermes config set custom_providers.0.models.<combo>.context_length 1000000 --force
```

Or use a different combo that IS registered.

### 2. `FileNotFoundError: SOUL_consultant.md`

You added a new archetype but didn't create the SOUL file. The plugin
silently returns an empty SOUL if the file is missing — but it does log a
warning. Check `~/.hermes/logs/`.

### 3. `AIAgent.__init__() got an unexpected keyword argument 'X'`

You're on an older Hermes version that doesn't support the kwarg. The
plugin passes 14 kwargs to AIAgent (see [ARCHITECTURE.md](ARCHITECTURE.md));
if your Hermes predates the latest AIAgent signature, the construction
fails. Update Hermes or pin the plugin to a compatible version.

### 4. `RuntimeError: Could not resolve credentials for archetype 'X'`

`resolve_creds_for_spec()` returned empty. Check:
- `archetype_model_config.json` has an entry for the archetype
- The model field is non-empty
- The combo is registered in Hermes (see #1)

### 5. `KeyError: 'X'` in `delegate_task_consultant`

The orchestrator called a tool name that doesn't exist. The 5 valid
names are: `delegate_task_consultant`, `delegate_task_long_horizon`,
`delegate_task_high_hallucination`, `delegate_task_speedster_internal`,
`delegate_task_speedster_internet`. Check the tool name.

### 6. Subagent returns `None` instead of a string

`child.run_conversation()` returned a dict but none of the keys the
plugin checks (`final_response`, `response`) had a string value. The
agent loop itself returned a malformed result. Check the live transcript
log for what the subagent actually output.

### 7. Subagent loops forever and exhausts `max_iterations`

The SOUL or the goal is too open-ended. The subagent keeps generating
tool calls. Options:
- Lower `max_iterations` in `archetypes.yaml` for this archetype
- Tighten the goal to be more specific
- Add a `## When To Stop` section to the SOUL

### 8. Subagent returns `EXECUTION_FAILURE` immediately

The agent loop failed before producing any output. Check `~/.hermes/logs/`
for the actual exception. Common causes: API key not in env, model not
available, rate limit hit.

---

## Inspecting plugin state at runtime

```bash
# What archetypes are loaded?
/Users/njaypro/.hermes/hermes-agent/venv/bin/python3 -c "
import importlib.util
spec = importlib.util.spec_from_file_location('r', '/Users/njaypro/Desktop/OMCA-GODMODE/TOOLS/archetype-router/router.py')
r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)
for n in r.list_archetypes():
    s = r.get_archetype(n)
    print(f'{n:25} provider={s.provider!r:20} model={s.model!r:25} tools={s.default_toolsets}')
"

# What config did the plugin see?
/Users/njaypro/.hermes/hermes-agent/venv/bin/python3 -c "
import importlib.util
spec = importlib.util.spec_from_file_location('r', '/Users/njaypro/Desktop/OMCA-GODMODE/TOOLS/archetype-router/router.py')
r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)
print(r.describe_config_split())
"
```

---

## Reading the in-flight delegation

To watch a delegation AS it runs:

```bash
# Pick the most recent live transcript dir
LATEST=$(ls -t ~/.hermes/cache/delegation/live/ | head -1)
tail -f ~/.hermes/cache/delegation/live/$LATEST/task-0.log | jq .
```

The TUI also shows live progress for the parent's display (a different
channel from the transcript log file). Both are wired by the plugin.

---

## Debug logs

The plugin logs to `archetype-router.delegate` (and `archetype-router`
for the router). To see them:

```bash
# Recent plugin log lines
tail -f ~/.hermes/logs/*.log | grep archetype-router
```

Log levels:
- `DEBUG` — config I/O, progress callback setup
- `INFO` — every delegation start, with model + provider + toolsets
- `WARNING` — missing SOUL file, partial config
- `ERROR` — credential resolution failure, AIAgent construction failure

Set log level via:

```bash
hermes config set log_level DEBUG
```

---

## Common pitfalls (developer reference)

1. **Editing `~/.hermes/config.yaml` directly** — use `hermes config set/unset`
   instead. The plugin writes to this file on every delegation; direct edits
   race with the plugin's writes.
2. **Forgetting to register a combo in `custom_providers.0.models`** — every
   combo referenced from `archetype_model_config.json` MUST be registered.
   Otherwise `resolve_runtime_provider()` raises ValueError.
3. **Adding a new archetype without a SOUL_<name>.md file** — the plugin
   silently fails with empty SOUL content. Always create the SOUL file.
4. **Modifying `archetypes.yaml` while delegations are in flight** —
   in-flight delegations cache the spec at start. New specs take effect on
   the next delegation. mtime-based cache invalidation handles this.
5. **Calling `archetype_delegate()` from outside a Hermes handler** — the
   function expects a `parent_agent` with `_delegate_depth`, `session_db`,
   `session_id`, `_client_kwargs`, etc. If you call it from a non-AIAgent
   context, those attributes will be missing and you'll get AttributeErrors.