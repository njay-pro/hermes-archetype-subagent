# Contributing to hermes-archetype-subagent

Thanks for your interest in improving the **OMCA Archetype Router** — a Hermes
Agent plugin that adds five specialist `delegate_task` tools, each with its own
model, persona, toolset, and skill isolation.

## Dev setup

This project uses [uv](https://github.com/astral-sh/uv).

```bash
uv sync                 # install dev dependencies
uv run pytest           # run the full suite (100+ tests)
```

## Project layout

- [`AGENTS.md`](AGENTS.md) — file map for agents and humans.
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — how the mimic layer works.
- [`docs/EXTENDING.md`](docs/EXTENDING.md) — recipe for adding an archetype.
- `router.py` / `archetype_delegate.py` — the public API and the delegate layer.
- `tests/` — the pytest suite (kept green).

Treat the `docs/` files as the source of truth for behavior.

## Making a change

1. Branch from `main`.
2. Keep the change focused — one logical fix or feature per PR.
3. Add or update tests under `tests/`. The suite must stay green:
   `uv run pytest`.
4. If you change behavior, update `CHANGELOG.md` **before** the commit lands.
5. Bump the version in **both** `plugin.yaml` and `pyproject.toml` together
   when preparing a release — they must stay in sync (a past drift caused a
   broken release).
6. Run `uv run ruff check .` and `uv run ruff format .` before pushing.

## Adding an archetype

Follow [`docs/EXTENDING.md`](docs/EXTENDING.md) — a 5-file recipe
(model config, schema, SOUL, registration, tests). Do not hardcode model
names outside `archetype_model_config.json`.

## Commit style

Short imperative subject line, blank line, then body if needed. Explain the
*why*, not the *what*.

## Releasing

The maintainer tags `vX.Y.Z` on the release commit and cuts a GitHub release
from `CHANGELOG.md`. Do not force-push tags.

## Code of conduct

Be respectful. Assume good faith. Keep discussions about the code.
