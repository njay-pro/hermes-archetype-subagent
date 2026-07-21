# Contributing

Thanks for your interest in contributing to `hermes-archetype-subagent`!

## What this project is

A Hermes plugin that exposes 5 archetype-specific delegation tools
(`delegate_task_consultant`, `delegate_task_long_horizon`, etc.), built
by mimicking Hermes's native `delegate_task` machinery and adding
per-archetype configuration (model, persona, toolset, skill isolation).

For "what" and "why", read [README.md](README.md).
For "how", start with [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
For "where to add a new archetype", see [docs/EXTENDING.md](docs/EXTENDING.md#adding-a-new-archetype).

## Development setup

```bash
git clone https://github.com/njay-pro/hermes-archetype-subagent.git
cd hermes-archetype-subagent
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

You'll also need the Hermes agent to be installed at `~/.hermes/hermes-agent/`
(this plugin extends it). If you don't have it, see
[github.com/nousresearch/hermes-agent](https://github.com/nousresearch/hermes-agent).

## Running tests

```bash
# Fast
python -m pytest tests/ --no-cov

# With coverage
python -m pytest tests/ --cov=. --cov-report=term-missing
```

See [docs/TESTING.md](docs/TESTING.md) for details.

## Code style

This project uses:
- **ruff** for linting (`ruff check .`)
- **mypy** for type checking (`mypy . --ignore-missing-imports`)
- pytest for tests

Both are configured in `pyproject.toml`. Run them before opening a PR.

## Pull request process

1. **Open an issue first** for non-trivial changes. Big changes get
   discussed before they get built. See [docs/ROADMAP.md](docs/ROADMAP.md)
   for what's already planned.
2. **Keep PRs small.** One logical change per PR.
3. **Write tests** for any new behavior. Run the full suite before
   pushing.
4. **Update docs** in the same PR. If you change the routing, update
   `docs/EXTENDING.md`. If you add a tool param, update `docs/API.md`.
5. **Follow the file map.** The repo's `AGENTS.md` is the file map for
   AI agents and new contributors. If you add a new docs/ file, add
   it to the file map.
6. **Commit messages:** use [Conventional Commits](https://www.conventionalcommits.org/)
   format. `feat:`, `fix:`, `chore:`, `docs:`, etc.
7. **No merge commits.** Rebase before opening the PR.

## Reporting bugs

Open an issue with:
- Plugin version (`grep version plugin.yaml`)
- Hermes version (`hermes --version`)
- Steps to reproduce
- Expected vs actual behavior
- Relevant log output (`tail ~/.hermes/logs/*.log | grep archetype-router`)

## Security issues

Email `njay@njaypro.com` directly. Don't open a public issue.

## Code of conduct

Be kind. This is a small, focused project. Disagreements happen; we
resolve them with words, not escalation.