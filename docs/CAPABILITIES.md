# Capabilities Matrix

> Native `delegate_task` vs the archetype plugin, side by side.

---

## Side-by-side

| Capability | Native `delegate_task` | This Plugin (v0.3) |
|---|---|---|
| Spawn child AIAgent | ✅ | ✅ (direct construction) |
| Per-archetype model override | ❌ no `model=` kwarg | ✅ via `archetype_model_config.json` |
| Per-archetype SOUL identity | ❌ manual injection | ✅ auto-injected from SOUL_*.md |
| Per-archetype skill whitelist | ❌ no model-facing arg | ✅ via plugin tool params |
| Per-archetype toolset restriction | ❌ no `toolsets=` kwarg | ✅ passes `enabled_toolsets=clean_toolsets` to child AIAgent |
| Live transcript log | ✅ `cache/delegation/live/` | ✅ Same path via `create_live_transcripts` |
| Child AIAgent toolset wiring | ✅ passed via AIAgent constructor | ✅ passed via `enabled_toolsets=` (parent is NOT mutated) |
| Concurrent batching | ✅ multi-task in one call | ✅ multi-task in one call (v0.3.1 ThreadPoolExecutor parallel) |
| Spawn pause/kill switch | ✅ `is_spawn_paused()` | ❌ delegated to AIAgent's own loop |
| Role normalization | ✅ `_normalize_role` | ⚠️ accepts `role=` but doesn't enforce |
| Result aggregation | ✅ batch joins | ❌ one result per call |
| Token budget tracking | ✅ `max_iterations` enforced | ✅ passed to AIAgent |
| Recursive delegation blocklist | ❌ no blocklist | ✅ `DELEGATE_BLOCKED_TOOLS` (6 tools blocked) |
| Output schema enforcement | ⚠️ partial (description hint) | ✅ strict JSON Schema (per-archetype or per-call) |
| Skill include/exclude per call | ❌ no model-facing arg | ✅ `skill_include_override` + `skill_exclude_override` |
| Per-call model escape hatch | ❌ no | ✅ `model_override` |
| 9router combo routing | ❌ no | ✅ yes |

---

## What we trade away (intentionally)

The plugin gives up these native features in exchange for per-archetype
configuration:

- **Concurrent batching** — one task per call. Add a loop in `_make_handler` if you need fan-out.
- **Spawn pause** — `is_spawn_paused()` is not checked. AIAgent has its own
  interrupt protection (`agent.auxiliary_client.aux_interrupt_protection`)
  but the plugin's `_build_child_agent_mimic` doesn't wire it.
- **Role enforcement** — we accept `role=` and pass it to AIAgent, but
  don't check `depth < max_spawn`. Architecturally fine for archetypes
  that are always `leaf`.

If you need those, run native `delegate_task` instead. The plugin
is for the "I have a team of specialists" case; native is for the
"I have one general subagent" case.

---

## What we add (the value)

| Capability | Why |
|---|---|
| Per-archetype model | Cost vs reasoning vs speed tradeoffs become declarative, not string-concat hacks |
| Per-archetype persona (SOUL) | 8,000-token briefing becomes a one-line tool call, not a manual paste |
| Per-archetype toolset | Speedster doesn't need terminal; consultant needs everything — the toolset encodes this |
| Recursive delegation blocklist | Subagents can't accidentally loop into `delegate_task_consultant` again |
| Output schema per archetype | III returns JSON; II returns prose; I returns either — contract is per-archetype |
| Skill isolation per call | Orchestrator decides which skills each subagent sees (per-call whitelist) |
| 9router combo routing | Combos are versioned in 9router; swapping a combo in JSON swaps the model, not the wire-up |
| Live transcript at the same path | Debug artifacts identical to native's — no separate scraping tools |

---

## When to use which

| If your task is... | Use |
|---|---|
| Delegate with my profile's model and toolset | native `delegate_task` |
| Different model / toolset / persona per call | **the plugin** |
| Block recursive delegation or user-asks | **the plugin** (`DELEGATE_BLOCKED_TOOLS`) |
| 8 specialists on 8 model combos, each with their own briefing | **the plugin** |
| Multi-task fan-out in one call | native `delegate_task` (until plugin adds batching) |
| Hot path that runs hundreds of times | native `delegate_task` (lower per-call cost) |
| Need spawn pause / kill switch from TUI | native `delegate_task` |
| Tight 3-line hot path | native `delegate_task` |

Most projects start with `delegate_task` and graduate to the plugin when
they have 3+ distinct delegation patterns. If you're at that point, this
plugin is for you.

---

## Reference: the 4 capabilities the plugin adds

1. **Per-archetype model** — `archetype_model_config.json` maps archetype
   → 9router combo → resolved model/provider/base_url/api_key. Native
   has no such map.

2. **Per-archetype persona** — `SOUL_<name>.md` is read on every delegation
   and prepended to the goal. Native has no persona concept.

3. **Per-archetype toolset + blocklist** — `default_toolsets` from YAML +
   `DELEGATE_BLOCKED_TOOLS` (delegate_task, clarify, memory, etc.) —
   both enforced at AIAgent construction. Native uses parent's toolsets
   verbatim.

4. **Orchestrator-decided skill isolation** — `skill_include_override`
   and `skill_exclude_override` per call, on top of a global
   `default_disabled_skills` safety net. Native's
   `model_tools._last_resolved_tool_names` saves/restores parent toolset
   but has no per-call whitelist API.