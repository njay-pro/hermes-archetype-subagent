# TODO

Open work for the `archetype-router` plugin. Check off as items ship.

## In flight

- [ ] **no more local mirror. fix the monorepo issue**

  The plugin currently lives at `~/Desktop/OMCA-GODMODE/TOOLS/archetype-router/`
  and is mirrored to `~/Code/hermes-archetype-subagent/` (which we then push
  to https://github.com/njay-pro/hermes-archetype-subagent).

  The problem: two copies of the same code. Drift risk. The mirror's
  `sync-to-github.sh` works, but it's a hack.

  Options to fix:
  1. **Make the monorepo plugin its own git submodule** of the GitHub
     repo — subdir tracks a remote, monorepo keeps the directory
  2. **Set up a CI job** in the OMCA monorepo that auto-pushes the
     plugin subtree to GitHub on every commit
  3. **Move the plugin to a proper `packages/archetype-router/` subfolder**
     and use `git subtree push` from the monorepo directly — no local
     mirror
  4. **Drop the GitHub repo for now** — keep the plugin in the
     monorepo, push to GitHub later when actually ready to opensource

  **Decision needed.** My recommendation: option 3 (subtree push) —
  keeps the monorepo intact, eliminates the mirror, lets us push
  with one command from the monorepo root.

- [ ] **v0.3.2 — TUI preview pane wiring (2026-07-22)**

  Surfaced by njaypro live-testing the plugin in the main TUI. Three
  wiring gaps that prevent the TUI's subagent preview pane from showing
  plugin-constructed children, even though the "subagent running" status
  fires correctly.

  - [x] **`_build_child_progress_callback` was called without `session_ref`**
        → no `child_session_id` threaded into events → TUI preview stays empty.
        FIXED: added `session_ref` param to `_setup_progress_callbacks`,
        pass a mutable dict, populate with `child.session_id` after AIAgent
        construction. Test `test_session_ref_passed_to_progress_callback`.

  - [x] **Plugin children were not registered into native's `_active_subagents`**
        → TUI's subagent tree doesn't see them → no interrupt/status from
        the TUI. FIXED: added `_register_plugin_subagent` /
        `_unregister_plugin_subagent` helpers that call native's
        `_register_subagent` / `_unregister_subagent` (lazy import, best-effort).
        `_build_child_agent_mimic` registers eagerly after AIAgent construction;
        `archetype_delegate` unregisters in a `finally` (both sync and background
        paths). Test `test_register_unregister_helpers_exist`.

  **Shipped 2026-07-22.** 33/33 tests pass (was 31).

  **Re-test gate:** restart the gateway, run a 4-archetype parallel
  delegation from the TUI, and verify the preview pane shows the child
  session. If the pane is still empty after the restart, the remaining
  surface is the TUI itself — escalate to Hermes-core (file: tui_gateway/server.py
  keying off `child_session_id`).

- [ ] **v0.3.1 — bug-fix milestone from archetype audit (2026-07-22)**

  Surfaced by 3 parallel archetype audits (`consultant`, `long_horizon`,
  `speedster_internet`) on 2026-07-22. Two bugs already fixed in this
  session; six more filed for the v0.3.1 milestone.

  **Already shipped (this session, 2026-07-22):**
  - [x] Plugin module resolution — `__init__.py` now `sys.path.insert(0, PLUGIN_DIR)`
        before lazy-loading router.py, so handler's `from archetype_delegate import ...`
        resolves at dispatch time. (Was raising `ModuleNotFoundError`.)
  - [x] String coercion in `_assemble_brief` — handles dict-typed `goal`/`context`
        that some MCP wrappers serialize as `{"context": "..."}`. Added
        `_coerce_str()` helper. (Was raising `AttributeError: 'dict' object has no attribute 'strip'`.)

  **Filed for v0.3.1 (priority order):**

  - [x] **CRITICAL — Batch mode is sequential, not parallel** (`router.py:_make_handler`
        batch path). FIXED 2026-07-22: replaced `for t in tasks` loop with
        `concurrent.futures.ThreadPoolExecutor`, capped by
        `HERMES_MAX_CONCURRENT_CHILDREN` env var. Test
        `test_batch_dispatch_uses_parallel_executor` proves 3× 0.3s tasks
        complete in <0.7s (parallel), not 0.9s+ (sequential).
        *Source: consultant audit.*

  - [x] **CRITICAL — Role enforcement unimplemented** (`archetype_delegate.py:DELEGATE_BLOCKED_TOOLS`).
        FIXED 2026-07-22: added all 5 plugin tool names to the frozenset
        (`delegate_task_consultant`, `_long_horizon`, `_high_hallucination`,
        `_speedster_internal`, `_speedster_internet`). Test
        `test_blocklist_includes_plugin_tools` asserts all 5 are present.
        *Source: consultant audit.*

  - [x] **HIGH — Skill root discovery incomplete** (`router.py:_resolve_skill_roots`).
        FIXED 2026-07-22: now reads `skills.external_dirs` from every
        `~/.hermes/profiles/*/config.yaml` via a minimal YAML extractor
        (`_extract_external_dirs`). 3 tests cover the YAML list form,
        inline `[a, b]` form, and absent-key case.
        *Source: long_horizon audit.*

  - [x] **MED — CAPABILITIES.md lies about toolset mutation**. Audit found
        the doc claims "by mutating `parent.enabled_toolsets`" but the mimic
        actually passes `enabled_toolsets=clean_toolsets` to the child
        AIAgent only — parent is never mutated. Either fix the doc or
        delete the row. *Source: long_horizon audit.* → doc fixed 2026-07-23.

  - [x] **LOW — speedster SOUL strictness is a feature, not a bug**
        (no code change needed, but document it). Confirmed 2026-07-22:
        speedster_internet returns `EXECUTION_FAILURE / NO_EXECUTION_TREE_PROVIDED`
        when the goal isn't a deterministic STEP 1, STEP 2, ... tree. This
        is correct behavior per SOUL — speedster is narrow-extraction-only.
        Add a note to README.md that speedster rejects open-ended tasks
        by design, so future operators don't think it's broken.
        → README note added 2026-07-23.

  **Re-fire gate for v0.3.1: DONE.** Re-ran archetype delegations live;
  3 code bugs confirmed fixed (batch parallel, role blocklist, skill roots
  external_dirs). All 3 critical/high items shipped. 9router health check
  was removed per njaypro directive, not a regression. v0.3.1 milestone
  CLOSED 2026-07-23.

- [x] **v0.3.2 — TUI preview pane + manifest/goal fixes (2026-07-23)**

  Surfaced when njaypro tested plugin subagents in the main TUI and saw the
  "subagent running" indicator but no preview pane. Three wiring gaps fixed:

  - SG-preview: pre-assign `child_session_id = f"plugin-{subagent_id}"`
    BEFORE callback construction; populate `session_ref` dict so the
    callback closure sees it from the first emitted event. Otherwise the
    TUI's preview pane (which keys on `child_session_id`) opens to nothing.
  - SG-register: register/unregister the plugin child into native's
    `_active_subagents` dict so the TUI's subagent tree can find it.
    Lazy-imports native's `_register_subagent` / `_unregister_subagent`
    via `sys.modules` scan because the gateway may load `delegate_tool`
    as `tools.delegate_tool` OR `hermes_agent.tools.delegate_tool`.
  - SG-manifest: live-transcript manifest used to never get closed.
    Plugin's `_unregister_plugin_subagent` didn't update `manifest.json`
    with `status: "completed"` + `exit_reason`. Fix: derive the
    `delegation_id` from the live-transcript log path's parent dir
    (`<HERMES_HOME>/cache/delegation/live/<id>/manifest.json`) and write
    `completed` + `exit_reason` to the manifest in a `finally` block on
    both sync and background delegation paths.
  - SG-goal: live-transcript manifest used to write the placeholder
    `[<archetype>] (live transcript)` instead of the orchestrator's
    actual goal. Fix: `_open_live_transcript` accepts `real_goal` and
    `_wrap_for_live_transcript` forwards it; `_build_child_agent_mimic`
    opens the live transcript FIRST (so the delegation_id is known)
    and derives the log_path → delegation_id mapping deterministically.

  33 tests passing (was 26, +7 new). Gateway restart required.

- [x] **v0.3.3 — context-pollution hardening + file preload (2026-07-23)**

  Four subgoals shipped:

  - SG1: pass `load_soul_identity=False` to AIAgent. Stops the runtime
    from injecting a default SOUL.md that competes with the plugin's
    archetype-specific SOUL. ~3 LOC.
  - SG2: add a `## PRIORITY` header at the top of the brief. Tells the
    subagent that the SOUL below supersedes any default role framing
    the runtime may have added. ~10 LOC + 1 test.
  - SG3: 3-layer skill resolution. L1 (code) baseline = OMCA utils
    (`knows_*`, `nodes_*`, `subflows_*`, `omca-*`, `omca_*`). L2 (config)
    safety net = `honcho-*` disabled in `default_disabled_skills`.
    L3 (orchestrator) = `skill_include_override` (whitelist) /
    `skill_exclude_override` (blacklist). Replaces "load all 70+ skills"
    with "load all OMCA utils" as the default. ~20 LOC + 4 tests.
  - SG4: `preload_files` slot. Orchestrator passes
    `preload_files=["/abs/path.md", ...]` to any archetype tool; each
    file's content is inlined into a `## Preloaded Files` section of
    the brief. Caps: 100KB per file, 1MB total per delegation. Missing
    or oversized files surface as text in the brief, not exceptions.
    ~60 LOC + 6 tests.

  v0.3.3 also includes the standalone dashboard:
  - `dashboard.py` (~24KB, single-file stdlib, port 8765). Reads
    `~/.hermes/cache/delegation/live/*/manifest.json` + `task-*.log`.
    Renders timeline (left) + live-tail detail (right) + SSE stream
    for the active delegation. Works uniformly for native and plugin.
    Zero deps. 18 tests for log parser + HTTP routes.

  **SG2 part 2 (skill_filter unification via "skills" toolset) was REVERTED**
  after investigation: hermes-core's `_skill_should_show` reads
  `requires_toolsets` frontmatter, but **0 of 25 installed skills** in
  this environment declare any gating conditions. The brief's
  `## Available Skills` section is sufficient as the single source
  of truth — no second filter needed.

  66 tests passing (was 54, +12 new). No gateway restart needed for
  SG1/SG2/SG3 (purely prompt-side); SG4 needs a restart to take effect
  in live delegations.

  **Test note (2026-07-23):** verified live in the dashboard. 18 historical
  manifests retroactively closed by running `_close_manifest` on each
  delegation dir. Fresh delegations now close themselves automatically.

## Backlog

- [ ] Run `ruff check .` and `mypy . --ignore-missing-imports` in CI
      and add the resulting lint-clean state as a baseline
- [ ] Add `docs/QUICKSTART.md` for the 5-minute "set up on a new machine"
      path (clone → install.sh → symlink → restart → call tool)
- [ ] Bump coverage to 80% line coverage in `pyproject.toml` (currently
      ~70%); the gap is mostly in `router.py:_make_handler` error paths
- [ ] Replace `python3` in the project with a small wrapper script so
      contributors can `bin/test` / `bin/lint` / `bin/sync` instead of
      remembering the exact pytest/ruff/mypy invocations
- [ ] Add a `version` field to `pyproject.toml` that's the single source
      of truth (currently duplicated in `plugin.yaml`)

## Done (recent)

- [x] v0.3.0 — Mimic via direct AIAgent construction
- [x] v0.3.1 — 3 code bugs (batch parallel, role blocklist, skill roots external_dirs) + doc fixes
- [x] v0.3.2 — TUI preview wiring + manifest close + real goal
- [x] v0.3.3 — context-pollution hardening (L1/L2/L3) + file preload + dashboard
- [x] 9router combo routing
- [x] Live transcript logging via `tools.delegation_live_log`
- [x] 66 pytest tests across 4 files
- [x] docs/ restructure (10 files, ~50KB)
- [x] docs/skills/ with `install.sh` for the bundled 2 skills
- [x] GitHub repo created at njay-pro/hermes-archetype-subagent
- [x] v0.3.0 tagged and released on GitHub
- [x] `sync-to-github.sh` for pushing the monorepo → GitHub

---

*Edit this file when the work changes. Check items off as you finish
them. Don't let stale items linger — if it's no longer relevant, delete
the row.*