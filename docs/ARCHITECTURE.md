# Architecture (v0.3.0 — Mimic)

> Deep dive into the plugin's call path, the mimic design, and why we
> don't call native `delegate_task`. For "what is this", see
> [README.md](../README.md). For "how do I contribute", see [AGENTS.md](../AGENTS.md).

---

## The 3-Layer Call Path

The plugin does NOT call native `delegate_task`. Instead it constructs
the `AIAgent` directly with the resolved credentials.

```
                          ┌─────────────────────────────────────────────┐
                          │  Plugin handler (router.py _make_handler)  │
                          │  ├── assembles brief (SOUL + goal + schema) │
                          │  ├── resolves skills (include/exclude)      │
                          │  └── calls archetype_delegate()              │
                          └─────────────────────┬───────────────────────┘
                                                │
                          ┌─────────────────────▼───────────────────────┐
                          │  archetype_delegate.py                       │
                          │  ├── resolve_creds_for_spec()                  │
                          │  │     → archetype_model_config.json           │
                          │  │     → resolve_runtime_provider()            │
                          │  ├── _strip_blocked_tools(toolsets)            │
                          │  ├── _setup_progress_callbacks()               │
                          │  ├── _open_live_transcript() → log file        │
                          │  ├── _wrap_for_live_transcript() → tee events │
                          │  └── AIAgent(... ephemeral_system_prompt=brief,
                          │                 thinking_callback=...,
                          │                 tool_progress_callback=...)
                          └─────────────────────┬───────────────────────┘
                                                │
                          ┌─────────────────────▼───────────────────────┐
                          │  run_agent.AIAgent.run_conversation()        │
                          │  (native Hermes agent loop, unmodified)      │
                          │  ├── Streamed events → live transcript log   │
                          │  └── Returns {final_response, ...}            │
                          └─────────────────────────────────────────────┘
```

## Why mimic, not wrap

Earlier versions (v0.1, v0.2) called native `delegate_task` with
`model=` and `toolsets=` kwargs. That **didn't work** — native has neither
kwarg. v0.3 directly constructs the AIAgent. Pros:

- **No file-system mutations** to `~/.hermes/config.yaml` (no `delegation.model` snapshot/restore)
- **No mtime cache dependency** — credentials passed directly to `AIAgent.__init__`
- **Direct control over the 14 AIAgent constructor kwargs** — `ephemeral_system_prompt`, `enabled_toolsets`, `thinking_callback`, `tool_progress_callback`, etc.
- **`DELEGATE_BLOCKED_TOOLS` enforced** — subagents can't recurse into `delegate_task` / `clarify` / `memory` / `execute_code` / `send_message` / `cronjob`
- **Live transcripts preserved** via `tools.delegation_live_log.create_live_transcripts` + `wrap_progress_callback` (matches native's on-disk artifact path)

## How Plugin Load Works

```
Hermes loads plugin.yaml
  → _parse_manifest validates schema + provides_tools
  → _load_plugin(spec_from_file_location(__init__.py))
  → exec_module(__init__.py)
  → __getattr__("register") called by Hermes
  → register(ctx) builds 5 tools via _make_handler()
  → registry.register(name, schema, handler)
```

The `__init__.py` uses **PEP 562 lazy re-exports** so it can be imported
standalone (e.g. by tests) without triggering `router.py`'s module-level
work. The `__getattr__` is the only entry that actually loads `router.py`.

## How a Delegation Call Works

```
agent calls delegate_task_consultant(goal=..., context=...)
  → handler() (closure built by _make_handler)
  → apply_model_override(spec, override) if user passed override
  → resolve_orchestrator_skill_filter(include=..., exclude=...)
  → budget = max_iterations or spec.max_iterations
  → _assemble_brief(spec, goal, context, skill_filter, schema_override)
  → archetype_delegate(spec=spec, brief=brief, ...)
    → resolve_creds_for_spec(spec, model_override)
    → _strip_blocked_tools(toolsets)
    → _setup_progress_callbacks(...)  # TUI live updates
    → _open_live_transcript(name, task_index)
    → _wrap_for_live_transcript(callback)  # tee to log file
    → AIAgent(ephemeral_system_prompt=brief, tool_progress_callback=wrapped, ...)
    → if background: ThreadPoolExecutor.submit(child.run_conversation, ...)
       else:        child.run_conversation(user_message=brief)
    → return child.run_conversation result
  → handler returns final_response
```

## The ArchetypeSpec

```python
@dataclass(slots=True)
class ArchetypeSpec:
    name: str                      # e.g. "consultant"
    provider: str                  # e.g. "custom:9router"
    model: str                     # e.g. "arc-consultant1"  (combo name, NOT direct model)
    fallback_chain: List[Dict]     # Honcho/9router internal fallback (informational)
    default_toolsets: List[str]    # ["terminal", "file", "web"] etc.
    soul_path: Path                # absolute path to SOUL_<name>.md
    output_schema: Optional[dict]  # JSON contract (None = freeform)
    max_iterations: int            # 15 / 20 / 40 / 50 / 100
```

`ArchetypeSpec` is **immutable** in spirit (frozen via `__slots__`). All
mutations (e.g. `apply_model_override`) return new instances.

## What we reuse from native (and what we don't)

| Native piece | We use? | How |
|---|---|---|
| `run_agent.AIAgent` | ✅ yes | direct construction with archetype credentials |
| `agent.conversation_loop.run_conversation` | ✅ yes | called via AIAgent (we don't import directly) |
| `tools.delegation_live_log.create_live_transcripts` | ✅ yes | wraps the child's `tool_progress_callback` |
| `tools.delegation_live_log.wrap_progress_callback` | ✅ yes | tee events to per-task JSONL log |
| `tools.delegate_tool._build_child_progress_callback` | ✅ yes | sets up TUI live updates via `_setup_progress_callbacks` |
| `hermes_cli.runtime_provider.resolve_runtime_provider` | ✅ yes | resolves `arc-*` combo to base_url/api_key |
| `tools.delegate_task` (the public tool) | ❌ no | mimicked via direct AIAgent construction |
| `model_tools._last_resolved_tool_names` save/restore | ❌ no | AIAgent construction handles toolsets directly |
| `dispatch_async_delegation_batch` (multi-task concurrent) | ❌ no | one task per archetype call; no fan-out |
| `_normalize_role` strict enforcement | ❌ no | we accept `role=` but don't enforce leaf/orchestrator |
| Native's spawn pause (`is_spawn_paused()`) | ❌ no | delegated to AIAgent's own loop |

The plugin gives up native's **concurrent batching** + **role enforcement** in
exchange for **per-archetype configuration**. If you need multi-task batching,
add it to `_make_handler` (it would loop over tasks internally — see
[ROADMAP.md](ROADMAP.md) § Multi-task batching).

## Provenance

- **v0.1** — wrapper around native `delegate_task` (no-op for model override;
  native has no `model=` kwarg).
- **v0.2** — bypass via writing `delegation.model` to `~/.hermes/config.yaml`
  for the duration of the call, restore on exit. Mtime-based cache
  invalidation.
- **v0.3** — mimic via direct `AIAgent` construction. No file-system
  mutations. Adds live transcripts via `tools.delegation_live_log`. Adds
  9router combo routing. Splits `speedster` into internal/internet. Gives
  `high_hallucination` full tool surface with short-horizon guardrail.