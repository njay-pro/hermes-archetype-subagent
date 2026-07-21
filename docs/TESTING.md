# Testing

> How to run the test suite, what's covered, and the rules for adding tests.

---

## Running the suite

```bash
cd /Users/njaypro/Desktop/OMCA-GODMODE/TOOLS/archetype-router

# Fast (no coverage, ~0.4s)
/Users/njaypro/.hermes/hermes-agent/venv/bin/python3 -m pytest tests/ --no-cov

# With coverage
/Users/njaypro/.hermes/hermes-agent/venv/bin/python3 -m pytest tests/ --cov=. --cov-report=term-missing

# Single file
/Users/njaypro/.hermes/hermes-agent/venv/bin/python3 -m pytest tests/test_router.py -v

# Single test
/Users/njaypro/.hermes/hermes-agent/venv/bin/python3 -m pytest tests/test_router.py::TestArchetypeLoading::test_loads_all_5_archetypes -v
```

---

## What's covered

26 tests across 3 files:

### `test_router.py` (15 tests)

- **Archetype loading** — `load_archetypes()`, `get_archetype()`, all 5 specs have correct fields
- **Skill resolution** — whitelist, blacklist, fnmatch with prefix-extraction, default mode
- **Brief assembly** — SOUL prepended, goal/context/skills/model_block all present, output_schema embedded
- **Model override** — `apply_model_override()` returns new spec, doesn't mutate original
- **Plugin manifest** — `plugin.yaml` declares 5 tools

### `test_archetype_delegate.py` (7 tests)

- **Config I/O** — `snapshot_delegation_config()` returns all 5 keys, `write_delegation_config()` preserves comments, missing keys → None/empty
- **Context manager** — `delegation_config_context()` sets inside, restores on exit + on exception, yields saved snapshot, thread-safe
- **Credential resolution** — 5 archetypes resolve to `custom:9router` + `arc-*` combo, `model_override` wins, partial override falls back, unknown provider returns bare values

### `test_archetype_delegate_e2e.py` (4 tests)

- **End-to-end orchestration** — native receives only the kwargs it accepts (no `model=`, no `toolsets=`), delegation.config set before native runs, restored after success + after native failure, parent.enabled_toolsets mutated + restored, missing creds → clear error, max_iterations passed from spec, background flag pass-through

---

## Rules for adding tests

1. **Test against the actual config files, not mocks.** The `hermes_config_path` fixture snapshots `~/.hermes/config.yaml`; use it instead of mocking `write_yaml`.

2. **Don't import `archetype_delegate.py` as a package.** It's a flat module, loaded via `importlib.util.spec_from_file_location`. The `conftest.py` already does this correctly — copy that pattern.

3. **Test contracts, not implementations.** Assert "brief contains the goal" not "brief calls `_assemble_brief()` with these args". Behavior, not internal calls.

4. **The `fake_parent_agent` fixture is the canonical stub.** Use it for any test that needs to call `archetype_delegate()`. Don't make your own.

5. **For pytest, `cd` into the plugin dir first.** The test config (`pyproject.toml`) sets `rootdir = tests` and only works when CWD is the plugin root.

6. **The `--import-mode=importlib` flag is in the test config.** Don't override it. The plugin's `__init__.py` uses PEP 562 lazy re-exports that require importlib mode.

7. **Tests should run in < 1s each.** If a test takes longer, mark it `@pytest.mark.slow` and document why.

---

## CI

(Coming soon) GitHub Actions will run:

```yaml
- name: Test
  run: |
    /Users/njaypro/.hermes/hermes-agent/venv/bin/python3 -m pip install -e ".[dev]"
    /Users/njaypro/.hermes/hermes-agent/venv/bin/python3 -m pytest tests/ --cov=. --cov-fail-under=80
- name: Lint
  run: /Users/njaypro/.hermes/hermes-agent/venv/bin/python3 -m ruff check .
- name: Type-check
  run: /Users/njaypro/.hermes/hermes-agent/venv/bin/python3 -m mypy . --ignore-missing-imports
```

The CI config is in `.github/workflows/test.yml` (TBD — see
[ROADMAP.md](ROADMAP.md) § CI integration).

---

## Coverage

Current state: ~70% line coverage. The bypass layer (archetype_delegate.py)
gets the most coverage; the config I/O helpers get less because they
require live config files.

```bash
# Show uncovered lines
/Users/njaypro/.hermes/hermes-agent/venv/bin/python3 -m pytest tests/ --cov=. --cov-report=term-missing
```

Goal: 80% line coverage. Focus on the handler closures in `router.py`
(most error paths) and the live-transcript helpers in
`archetype_delegate.py` (the wire-up to native).