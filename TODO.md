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
- [x] 9router combo routing
- [x] Live transcript logging via `tools.delegation_live_log`
- [x] 26 pytest tests across 3 files
- [x] docs/ restructure (10 files, ~50KB)
- [x] docs/skills/ with `install.sh` for the bundled 2 skills
- [x] GitHub repo created at njay-pro/hermes-archetype-subagent
- [x] v0.3.0 tagged and released on GitHub
- [x] `sync-to-github.sh` for pushing the monorepo → GitHub

---

*Edit this file when the work changes. Check items off as you finish
them. Don't let stale items linger — if it's no longer relevant, delete
the row.*