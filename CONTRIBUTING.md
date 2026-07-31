# Contributing

Thanks for your interest in hermes-archetype-subagent. This is a single-
maintainer plugin by Njay + Hermes; the contribution bar is high because
the plugin couples tightly to Hermes internals.

## Before opening a PR

1. **Read `AGENTS.md`** — file map for agents and contributors. Most of
   your questions will be answered there.
2. **Read `docs/ARCHITECTURE.md`** — the 3-layer call path and the
   reasons we mimic `delegate_task` instead of wrapping it.
3. **Run the test suite locally** — `uv run pytest tests/ -q`. Must be
   green before PR.

## Conventions

- **Identity prose lives in `SOUL_<name>.md`.** Never duplicate persona
  prose into YAML or JSON. The triad (SOUL + archetype_model_config.json
  + archetypes.yaml) decouples identity / model / mechanics.
- **Models go in `archetype_model_config.json`.** Not in YAML, not in
  plugin.yaml. Combo names only — direct model IDs go inside 9router.
- **Tool configs go in `archetypes.yaml`.** Not in the JSON.
- **Tests live next to the code they test.** `tests/test_*.py` mirrors
  the file structure.

## Adding a new archetype

See `docs/EXTENDING.md`. Short version:

1. Write `SOUL_<name>.md` (identity prose).
2. Add a `name:` block in `archetypes.yaml` (toolsets, max_iterations,
   output_schema).
3. Add an entry in `archetype_model_config.json` (provider, model,
   fallback_chain).
4. Add a handler closure in `router.py` (`_make_handler`).
5. Register the tool in `plugin.yaml → provides_tools`.
6. Tests: at least one integration test exercising the new tool end-to-end.

## Reporting bugs

- Hermes upgrade broke something? Include the Hermes version + commit.
- 9router combo misbehaving? Include the combo config from the Honcho
  dashboard.
- Plugin not loading? Include `~/.hermes/cache/delegation/live/<id>/task-0.log`.

## Code of conduct

Be direct, not diplomatic. No sycophancy, no hedging. The plugin is a
tool, not a personality.