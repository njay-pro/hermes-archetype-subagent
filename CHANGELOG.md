# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.3.0] - 2026-07-22

### Added
- **5 archetype-specific delegation tools** (consultant, long_horizon, high_hallucination, speedster_internal, speedster_internet) replacing the original 4
- **`speedster` split** into `speedster_internal` (local files) and `speedster_internet` (network fetches) with explicit escalation codes
- **9router combo routing** — `archetype_model_config.json` now references Honcho combos (e.g. `arc-consultant1`) instead of direct model names
- **Live transcript logging** via `tools.delegation_live_log` — every archetype call produces `cache/delegation/live/<id>/task-N.log`
- **`DELEGATE_BLOCKED_TOOLS` enforcement** — subagents can't recurse into `delegate_task`, `clarify`, `memory`, etc.
- **Orchestrator-decided skill isolation** via `skill_include_override` and `skill_exclude_override` per call
- **`model_override` escape hatch** for per-call model swaps
- **pytest suite** with 26 tests across 3 files
- **`pyproject.toml`** for dev tooling (ruff, mypy, pytest, coverage)
- **Comprehensive docs/** — ARCHITECTURE.md, CONFIGURATION.md, EXTENDING.md, API.md, TESTING.md, DEBUGGING.md, CAPABILITIES.md, ROADMAP.md, SKILLS.md
- **`docs/skills/`** — bundled 2 skills (knows_multiAgent-promptEngineering,
  knows_multiAgent-orchestrationHowTo) + `install.sh` single-command installer

### Changed
- **Mimic architecture** — plugin constructs `AIAgent` directly instead of
  calling native `delegate_task`. No file-system mutations to
  `~/.hermes/config.yaml`, no mtime cache dance.
- **`high_hallucination`** now has full tool surface `[terminal, file, web]`
  with `max_iterations=40` as the short-horizon guardrail (was tool-stripped)
- **Configuration split:** `archetype_model_config.json` (model) +
  `archetypes.yaml` (schema) + `SOUL_<name>.md` × 5 (identity). Three
  concerns, three files, strict no-duplication rule.
- **Briefing duplication removed** — the `briefing_intro` field is
  gone from YAML; SOUL files own identity prose end-to-end.

### Deprecated
- None.

### Removed
- `delegate_task_speedster` (replaced by `delegate_task_speedster_internal` +
  `delegate_task_speedster_internet`).

### Fixed
- Plugin's `model=` and `toolsets=` kwargs to native `delegate_task` were
  silently no-op (native has neither kwarg). v0.3 routes around native entirely.

## [0.2.0] - 2026-07-22

### Added
- Initial config split (`archetype_model_config.json` + `archetypes.yaml`)
- Bypass architecture: write `delegation.model` to `~/.hermes/config.yaml`
  for the duration of the call, restore on exit.

## [0.1.0] - 2026-07-21

### Added
- Initial plugin (4 archetype tools)
- Wrapper around native `delegate_task`

[Unreleased]: https://github.com/njay-pro/hermes-archetype-subagent/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/njay-pro/hermes-archetype-subagent/releases/tag/v0.3.0
[0.2.0]: https://github.com/njay-pro/hermes-archetype-subagent/releases/tag/v0.2.0
[0.1.0]: https://github.com/njay-pro/hermes-archetype-subagent/releases/tag/v0.1.0
