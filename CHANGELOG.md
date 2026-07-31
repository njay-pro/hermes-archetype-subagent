# Changelog

## 0.4.5 (2026-07-31) — "Collapsed-Argument Recovery"

**Fixed:**
- **Defeated skill overrides via tool-call bridge.** Some invocation paths
  (notably the JSON `tool_call` bridge) serialize the *entire* arguments object
  into the first positional parameter (`goal`). The handler then received
  `goal={"goal": "...", "skill_include_override": [...]}` while the named
  `skill_include_override` / `skill_exclude_override` params arrived as `None`.
  The resolver silently fell back to the full OMCA catalog (47 skills), so
  per-call skill isolation was silently defeated — the subagent saw everything
  regardless of the requested whitelist.
- The handler now detects a dict-shaped `goal`, recovers every structured field
  from it (`skill_include_override`, `skill_exclude_override`, `context`,
  `max_iterations`, `role`, `background`, `output_schema_override`,
  `model_override`, `preload_files`, `tasks`), and logs the recovery. Named
  params still take precedence when both are present. Resolver + brief builder
  were already correct; only the arg-recovery path was missing.

## 0.4.4 (2026-07-31) — "Construction-Time Prompt Isolation"

**Fixed:**
- **Construction-Time Prompt Bloat.** `AIAgent` construction (which builds
  the system prompt including `<available_skills>`) now runs inside the
  `skill_isolation_context`. Previously, only the `run_conversation` call
  was wrapped, meaning the agent's initial prompt loaded all 147 skill
  frontmatters (massive KV cache bloat). Now, the complement of the
  allowlist is treated as disabled *during construction*, ensuring only the
  whitelisted subset (e.g. 47 allowed skills) is parsed and rendered in the
  system prompt context.

## 0.4.3 (2026-07-31) — "True Runtime Skill Isolation"

**Added:**
- **Context-local skill isolation patches.** The computed L1/L2/L3 skill allowlist
  is now strictly enforced at runtime. We monkeypatch `get_disabled_skill_names`
  and `_is_skill_disabled` globally on plugin load, routing to a thread-safe
  `ContextVar`. During subagent conversation runs, the complement of the
  allowlist is treated as disabled — restricting both the system prompt's
  `<available_skills>` block and the subagent's `skills_list` / `skill_view`
  tools dynamically without database races.
- Added 4 unit tests verifying correct proxy wrapping, context isolation, and
  restoration.

**Fixed:**
- **Diagnostics JSON string contract (v0.4.1).** `delegate_task_diagnostics`
  now JSON-serializes the returned dict to conform to the Hermes tool-result
  string contract.
- **First-dispatch dashboard race (v0.4.2).** `auto_open_dashboard()` now blocks
  the dispatching thread (bounded by 3s max wait) until the dashboard binds the
  port, resolving timing issues where subagents curled the port too early.

## 0.4.0 (2026-07-31) — "No More Duplicates, No More Drift"

**Breaking:** none. Wire-compatible with 0.3.x.

**Added:**
- **Dashboard auto-open on first archetype dispatch.** The Subagent Dashboard
  at `http://127.0.0.1:8765/` now opens automatically the first time a
  plugin-built subagent runs in a Hermes session. Idempotent per process.
  Disable via `archetype_model_config.json → dashboard.auto_open_on_first_dispatch: false`
  or set `open_browser: false` for headless sessions.
- **9router fallback via Hermes built-in resolver.** `resolve_creds_for_spec()`
  now calls `resolve_runtime_provider()` and re-tries with the spec's
  `fallback_chain` on failure. No custom chain — Hermes's own
  `fallback_models` handles model-level drift inside the fallback provider.
  Configurable per archetype in `archetype_model_config.json`.
- **`delegate_task_diagnostics(archetype=None, since="1h")` tool.** Returns
  structured dict from the live transcript log: total calls, success rate,
  fallback usage, p50/p95 latency, SOUL codes emitted. No dashboard frontend
  — pure structured return for the orchestrator to consume.
- **CI via GitHub Actions.** `.github/workflows/test.yml` runs `uv run pytest`
  on push + PR. e2e tests marked `@pytest.mark.integration` and skipped in
  default CI runs.
- **CHANGELOG.md** (this file). First entry — stops the v0.3.0/v0.3.4 drift
  signal that's been confusing public adopters.
- **README install prompt.** New "Installation — don't do this by hand"
  section with a copy-pasteable prompt the user pastes into their Hermes
  agent. The agent walks the install (clone, sync, symlink profiles,
  register combos, restart, verify). No installer script — the agent has
  the context to discover profiles + combo registrations.

**Fixed:**
- **SOUL_consultant.md contradiction** at lines 18-20 vs 70-71. Removed the
  conflicting "you are the only archetype that should speak to the user"
  assertion. Kept the "subagent doesn't handle user-facing conversation"
  guidance. Subagents were reading both lines and behaving unpredictably.
- **Canonical repo drift.** `~/Desktop/OMCA-GODMODE/TOOLS/archetype-router/`
  is now a tombstone README. `~/Code/hermes-archetype-subagent` is the
  single source of truth. `~/.hermes/plugins/archetype-router` and all
  profile plugin dirs are symlinks to the standalone repo.

**Restored:**
- `LICENSE` (MIT)
- `CONTRIBUTING.md` (stub)
- GitHub Release v0.4.0 with this changelog linked

**Deferred to v0.5:**
- `visual_curator`, `voice_imitator`, `storyboarder`, `systems_mapper`,
  `cultural_decoder` archetypes (creative design-language roles)
- Visual-reference seam in SOUL files
- Memory tiering (`memory_tier: none | session | persistent`) — needs
  diagnostics baseline first
- Speedster merge (rejected: both speedsters stay — different tools reduce
  hallucination)

---

## 0.3.x line — pre-v0.4 history

- 0.3.4 — profile-aware Hermes home resolution
- 0.3.3 — context-pollution fixes + file preload + dashboard + orchestrationHowTo v2.2
- 0.3.0 — mimic via direct AIAgent construction; 9router combo routing;
  speedster split (internal/internet); live transcripts via
  tools.delegation_live_log; high_hallucination short-horizon guardrail.

Pre-0.3 history lives in the OMCA monorepo tombstone at
`~/Desktop/OMCA-GODMODE/TOOLS/archetype-router/README.md`.