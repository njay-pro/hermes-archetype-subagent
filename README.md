# hermes-archetype-subagent

> **`delegate_task` on steroids.** Five archetype-specific delegation
> tools for Hermes, built by mimicking the native `delegate_task` machinery
> and adding the per-archetype configuration layer (model, persona,
> toolset, skill isolation) that `delegate_task` deliberately refuses to
> bake in.

---

## The 5 Tools

| Tool | Archetype | Combo | Tools | Max Iter |
|------|-----------|-------|-------|----------|
| `delegate_task_consultant`             | I  — Raw Power / Frontier        | `arc-consultant1`         | `[terminal, file, web]` | 50  |
| `delegate_task_long_horizon`           | II — Low-Hallucination / Stable  | `arc-longHorizon1`       | `[terminal, file, web]` | 100 |
| `delegate_task_high_hallucination`     | III — Creative / Lateral          | `arc-highHallucination1` | `[terminal, file, web]` | 40  |
| `delegate_task_speedster_internal`     | IVa — Cheap / LOCAL Files        | `arc-speedster1`          | `[file]` | 15 |
| `delegate_task_speedster_internet`     | IVb — Cheap / NETWORK Fetches    | `arc-speedster1`          | `[web]` | 20 |

---

## 60-Second Usage

```python
# From any AIAgent in any Hermes profile:

delegate_task_consultant(
    goal="Analyze the auth bottleneck in this codebase",
    context="Tech stack: Python, FastAPI, Redis. 10K req/s baseline.",
)

delegate_task_speedster_internal(
    goal="Classify each .md file by topic. Return {file, topic} pairs.",
    skill_include_override=["nodes_caption_image"],
)

delegate_task_high_hallucination(
    goal="Generate 5 brand names for a luxury lighting line",
    context="Audience: architects, interior designers, high-end retail.",
    output_schema_override={"type": "array", "items": {"type": "string"}},
)
```

All 5 tools accept the same params as native `delegate_task` plus 4
plugin extras: `output_schema_override`, `skill_include_override`,
`skill_exclude_override`, `model_override`.

---

## The Manifesto (1-paragraph version)

`delegate_task` is a general-purpose subagent launcher. It takes a
goal, spawns a child AIAgent, runs it. That's exactly what it should
do — and it should NOT grow into a router, a model selector, a
persona injector, or a skill filter. Those are orchestrator
decisions. The archetype plugin gives the orchestrator 5 well-typed
tools, one per archetype. Each tool is `delegate_task` with the
archetype's config baked in.

**The plugin is not fighting `delegate_task`; it is `delegate_task`
made configurable.** Read the [full manifesto](docs/ARCHITECTURE.md#manifesto-why-delegate_task-on-steroids).

---

## Quick Configuration Reference

| File | Holds | When to edit |
|------|-------|--------------|
| `archetype_model_config.json` | provider + model combo per archetype | Model ships/retires; swap combo |
| `archetypes.yaml` | toolsets, max_iterations, output_schema, `default_disabled_skills` | Persona evolves, skill set changes |
| `SOUL_<name>.md` × 5 | Identity prose | Persona identity changes |

All three auto-reload on mtime change — no plugin restart, no gateway
restart. Full reference: [docs/CONFIGURATION.md](docs/CONFIGURATION.md).

---

## Install the Skills (Optional)

This plugin bundles 2 skills it uses heavily. To install them to all
your Hermes profiles + AGENT-* workspaces:

```bash
cd docs/skills
./install.sh
```

Restart Hermes. See [docs/SKILLS.md](docs/SKILLS.md) for details.

---

## Documentation Map

| You want to... | Read |
|---|---|
| What is this plugin? | [README.md](README.md) (you are here) |
| How does it work internally? | [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) |
| Edit config / swap model | [docs/CONFIGURATION.md](docs/CONFIGURATION.md) |
| Add a new archetype / skill | [docs/EXTENDING.md](docs/EXTENDING.md) |
| Look up a public function | [docs/API.md](docs/API.md) |
| Run / write tests | [docs/TESTING.md](docs/TESTING.md) |
| Debug a live delegation | [docs/DEBUGGING.md](docs/DEBUGGING.md) |
| Decide native vs plugin | [docs/CAPABILITIES.md](docs/CAPABILITIES.md) |
| Plan a feature | [docs/ROADMAP.md](docs/ROADMAP.md) |
| Install the shipped skills | [docs/SKILLS.md](docs/SKILLS.md) |
| File map for AI agents | [AGENTS.md](AGENTS.md) |

---

## Anti-patterns (operator quick-reference)

❌ **Using one archetype for everything** — collapses the cost/latency
spectrum. Mix archetypes per call: speedster for classify, consultant
for synthesize.

❌ **Inlining the SOUL into the goal** — the SOUL is auto-injected.
Just write the task.

❌ **Calling native `delegate_task` when you need a different model /
toolset** — use the archetype tool.

❌ **Editing `~/.hermes/config.yaml` directly to swap models** — use
`archetype_model_config.json` and `hermes config set` for combo
registration.

❌ **Forgetting to register a combo in `custom_providers.0.models`** —
every combo MUST be registered. See
[docs/CONFIGURATION.md](docs/CONFIGURATION.md#combo-registration).

---

## Versioning

- **0.3** — mimic via direct `AIAgent` construction. No file-system
  mutations. 9router combo routing. Live transcripts. Speedster split
  into internal/internet. `high_hallucination` full surface, short
  horizon.

---

## License

MIT. See `LICENSE` (or, until we add it, the standard MIT terms).

---

**Next step:** open [AGENTS.md](AGENTS.md) for the file map, or jump
straight to [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the
v0.3 Mimic design.