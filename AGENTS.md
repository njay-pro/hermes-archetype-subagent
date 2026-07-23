# AGENTS.md — File map for AI agents and human contributors

> **This file is a file map, not documentation.** If you want to understand
> what the plugin does, start with [README.md](README.md). If you want to
> understand how it works, start with [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
>
> This file exists so an AI agent (or new human contributor) can orient
> themselves in 30 seconds and know exactly which file to open next.

---

## Start here

| You want to... | Read this | Touch this file |
|---|---|---|
| Understand what this plugin does | [README.md](README.md) | — |
| Understand how it works | [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | `archetype_delegate.py`, `router.py` |
| Edit config | [docs/CONFIGURATION.md](docs/CONFIGURATION.md) | `archetype_model_config.json`, `archetypes.yaml`, `SOUL_*.md` |
| Add a new archetype | [docs/EXTENDING.md](docs/EXTENDING.md) | 5 files (see recipe) |
| Add a new skill to the plugin's bundle | [docs/SKILLS.md](docs/SKILLS.md) | `docs/skills/your_skill/SKILL.md` |
| Look up a public function | [docs/API.md](docs/API.md) | `router.py`, `archetype_delegate.py` |
| Run / write tests | [docs/TESTING.md](docs/TESTING.md) | `tests/` |
| Debug a live delegation | [docs/DEBUGGING.md](docs/DEBUGGING.md) | — |
| Decide native vs plugin | [docs/CAPABILITIES.md](docs/CAPABILITIES.md) | — |
| Plan a feature | [docs/ROADMAP.md](docs/ROADMAP.md) | — |
| Run the web preview pane | [DASHBOARD_PLAN.md](DASHBOARD_PLAN.md) | `dashboard.py` |

---

## File layout (annotated)

```
archetype-router/
├── README.md                ← landing page (≤ 100 lines): pitch, tools, quick start
├── AGENTS.md                ← you are here — file map for agents
├── plugin.yaml              ← Hermes manifest (name, version, provides_tools)
│
├── router.py                ← public API + 5 tool schemas + handler closures
├── archetype_delegate.py    ← mimic layer: resolve creds → construct AIAgent → run
│
├── archetype_model_config.json   ← model/provider per archetype (rotates often)
├── archetypes.yaml               ← toolsets, max_iterations, output_schema (rotates rarely)
├── SOUL_<name>.md × 5            ← per-archetype identity prose (single source)
│
├── pyproject.toml           ← dev tooling config (ruff/mypy/pytest/coverage)
├── tests/                   ← 26 pytest tests
│   ├── conftest.py
│   ├── test_router.py
│   ├── test_archetype_delegate.py
│   └── test_archetype_delegate_e2e.py
│
└── docs/                    ← long-form content (read these)
    ├── ARCHITECTURE.md     ← mimic design, 3-layer call path
    ├── CONFIGURATION.md    ← JSON / YAML / SOUL field reference
    ├── EXTENDING.md        ← adding archetypes / skills / params
    ├── API.md              ← public function signatures
    ├── TESTING.md          ← pytest commands + suite summary
    ├── DEBUGGING.md        ← live transcript log + 8 common failures
    ├── CAPABILITIES.md     ← native vs plugin matrix
    ├── ROADMAP.md          ← near/mid/long-term plans
    ├── SKILLS.md           ← docs/skills/ index + install.sh usage
    └── skills/              ← shipped skills + installer
        ├── install.sh                     ← single-command installer
        ├── knows_multiAgent-promptEngineering/
        └── knows_multiAgent-orchestrationHowTo/
```

---

## Architecture lineage (why this folder structure exists)

- **v0.1** — wrapper around native `delegate_task` (no-op for model override)
- **v0.2** — bypass via writing `delegation.model` to `~/.hermes/config.yaml`
- **v0.3** — mimic via direct `AIAgent` construction. No file-system
  mutations. Adds live transcripts via `tools.delegation_live_log`. Adds
  9router combo routing. Splits `speedster` into internal/internet.
  Gives `high_hallucination` full tool surface with short-horizon
  guardrail.

See [docs/ARCHITECTURE.md § Provenance](docs/ARCHITECTURE.md#provenance)
for the full history.

---

## Maintainer notes

- **Don't add doc content here.** Use the appropriate `docs/*.md` file.
  This file is a map, not a destination.
- **Update the file map when you add a new docs/ file.** That's the
  single point this file exists for.
- **Update [docs/ROADMAP.md](docs/ROADMAP.md) when you change direction.**
  Keep it as a single source of "what we're working on next."

---

*Edit this file when the structure of the plugin changes. Keep the
file map accurate — the next agent who reads this will use it to
navigate.*