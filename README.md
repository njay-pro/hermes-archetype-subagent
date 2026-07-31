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

## Installation — don't do this by hand

**This plugin is tightly coupled to Hermes internals.** It mimics
`delegate_task`'s call path (`AIAgent`, live-transcript writer,
`_active_subagents` registration, profile env propagation). A Hermes
upgrade can silently break it.

**Don't try to install it yourself.** Paste the prompt below into your
Hermes agent and let it walk the install. The agent has the context to
discover your profiles, your `custom_providers.0.models` registrations,
and your gateway state — you don't.

````markdown
Install the hermes-archetype-subagent plugin from
https://github.com/njay-pro/hermes-archetype-subagent (tag v0.4.0).

Steps:
1. Clone to ~/.hermes/plugins/archetype-router (NOT ~/Code/... —
   plugin loader expects this path).
2. Run `uv sync --extra dev --extra test` inside that clone.
3. Replace ~/.hermes/plugins/archetype-router if it was a real dir
   (some users have one) with a symlink to the clone.
4. For each Hermes profile you have (discover them via
   ~/.hermes/profiles/), symlink ~/.hermes/profiles/<prof>/plugins/archetype-router
   to ~/.hermes/plugins/archetype-router.
5. Read archetype_model_config.json. For each `arc-*` combo in
   the archetypes block, register it in Hermes:
     hermes config set custom_providers.0.models.<combo>.context_length 1000000 --force
   Do this for ALL your profiles.
6. Restart the gateway so it picks up the plugin.
7. Verify: dispatch delegate_task_consultant with goal="echo your SOUL
   first 50 chars" — subagent should return. If it returns
   ModuleNotFoundError, you forgot step 2.
8. The first dispatch in any new Hermes session auto-opens the
   dashboard at http://127.0.0.1:8765/. No action needed.

If any step fails, stop and tell me which step + the error. Do NOT
work around silently.
````

**After install:** the agent should report what it did and the result of
step 7. If anything looks wrong, paste the output back and we'll debug.

**Compatibility:** tested against Hermes as of 2026-07. If your Hermes
is more than a few months old or pre-release, ask before installing.

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

## Speedster is narrow on purpose

`delegate_task_speedster_internal` and `delegate_task_speedster_internet`
are intentionally narrow. They are **deterministic, single-pass
extraction** agents — feed them a pre-shaped `STEP 1, STEP 2, ...` tree
and they execute it. Feed them an open-ended goal like "audit this
codebase" and they return `EXECUTION_FAILURE / NO_EXECUTION_TREE_PROVIDED`
because their SOUL explicitly rejects that shape.

This is **correct behavior, not a bug.** If you need open-ended analysis,
use `delegate_task_consultant` or `delegate_task_long_horizon` instead.
See [SOUL_speedster_internet.md](SOUL_speedster_internet.md) for the
full briefing discipline.

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
- **0.3.2** — `child_session_id` wiring + native `_active_subagents`
  registration for TUI preview pane. Optional web preview pane
  (`dashboard.py`, see below).

---

## Optional: Web Preview Pane

`dashboard.py` is a single-file, stdlib-only web server that reads
`~/.hermes/cache/delegation/live/*/manifest.json` + `task-*.log` and
renders every delegation (native AND plugin) in a single page.

```bash
python dashboard.py             # serves on http://127.0.0.1:8765
python dashboard.py --port 9000 # custom port
python dashboard.py --no-clear  # skip the startup prune of old delegations
```

What you get:
- **Timeline** of all delegations (newest first), with status badge +
  goal preview
- **Detail view** of the selected delegation, with live transcript
  streaming (SSE; auto-tail mode for running ones)
- **Zero dependencies** — Python 3.9+ stdlib only. No `pip install`
  needed. `Ctrl+C` to stop.

It works for both `delegate_task` (native) and the 5 archetype tools
(consultant, long_horizon, high_hallucination, speedster_internal,
speedster_internet) because both write to the same on-disk format.

**Note:** the plugin currently writes the goal as
`[consultant] (live transcript)` (a placeholder) instead of the real goal.
The dashboard shows whatever is in the log — the real goal for native,
the placeholder for plugin delegations. Fix tracked in v0.3.2 TODO.

---

## License

MIT. See `LICENSE` (or, until we add it, the standard MIT terms).

---

**Next step:** open [AGENTS.md](AGENTS.md) for the file map, or jump
straight to [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the
v0.3 Mimic design.