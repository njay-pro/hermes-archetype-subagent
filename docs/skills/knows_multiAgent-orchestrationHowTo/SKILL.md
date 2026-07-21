---
name: knows_multiAgent-orchestrationHowTo
description: |
  Routing and escalation playbook for OMCA multi-agent orchestration. Pairs
  with knows_multiAgent-promptEngineering (which holds per-archetype briefing
  templates). This skill covers: which archetype to pick for a given task,
  how to compose multi-archetype pipelines, the 3-level escalation loop
  (Retry / Replan / Decompose), when to override models per-call, and the
  common anti-patterns that break orchestration in production.

  Load when: agent is about to invoke delegate_task_<archetype>, planning a
  multi-step workflow, deciding how to recover from a subagent failure, or
  composing heterogeneous archetype calls.

  Pairs with: the archetype-router Hermes plugin (TOOLS/archetype-router/)
  which exposes the 5 archetype-specific delegate_task tools.
version: "1.0.0"
tags: ["omca", "multi-agent", "orchestration", "routing", "escalation", "archetype", "delegation"]
category: project-setup
load_when: "agent needs to decide which archetype to delegate to, plan multi-archetype composition, or recover from subagent failure"
related_skills:
  - knows_multiAgent-promptEngineering
  - omca-framework
audience: [all-profiles, all-workspaces]
metadata:
  hermes:
    tags: [omca, multi-agent, orchestration, routing, escalation, archetype, delegation]
    related_skills:
      - knows_multiAgent-promptEngineering
  omca:
    layer: orchestration
    distribution: global
    refresh_cadence: "quarterly (next: 2026-10-21)"
prerequisites:
  skills:
    - knows_multiAgent-promptEngineering   # briefing templates live there
    - the archetype-router Hermes plugin (TOOLS/archetype-router/) must be enabled
---

# Multi-Agent Orchestration: Routing & Escalation How-To

The other half of the OMCA multi-agent skill stack. `knows_multiAgent-promptEngineering`
teaches you how to BRIEF each archetype — what XML template to inject, what output schema
to enforce, what role posture the model expects.

This skill teaches you how to ROUTE between archetypes — which one to pick for a given
task, how to compose them into pipelines, when to escalate, and how to recover from
subagent failure.

**Mental model:** You are the orchestrator. The 5 archetypes (`delegate_task_consultant`,
`delegate_task_long_horizon`, `delegate_task_high_hallucination`,
`delegate_task_speedster_internal`, `delegate_task_speedster_internet`) are your
specialist team. Your job is to:

1. **Decompose** a complex goal into sub-tasks.
2. **Route** each sub-task to the right archetype.
3. **Synthesize** the results into a single coherent answer.
4. **Escalate** when a specialist returns NULL, fails, or signals it was the wrong choice.

---

## 0. The 5 Archetypes (Quick Reference)

| Tool | Archetype | Strengths | When to use | Default tools |
|---|---|---|---|---|
| `delegate_task_consultant`             | I — Raw Power | Deep multi-step reasoning, ambiguity resolution, function calling | Complex escalation, novel tasks, user-facing chat (only archetype allowed to speak to user) | `[terminal, file, web]` |
| `delegate_task_long_horizon`           | II — Low Hallucination | Sustained stability, anti-drift, low hallucination over long horizons | Multi-step operational workflows, stateful tasks, mission-framing briefings | `[terminal, file, web]` |
| `delegate_task_high_hallucination`     | III — Creative, Lateral | Non-obvious solutions, lateral thinking, diverse perspectives. Powerful model with full tool surface but short iteration horizon. | Ideation, brainstorming, creative writing, short-horizon creative coding — requires post-validation | `[terminal, file, web]` |
| `delegate_task_speedster_internal`     | IVa — Cheap / Fast / LOCAL | 50-200ms latency, low cost, deterministic file reads | Classify/extract/summarize local files, pattern-match inside local data | `[file]` |
| `delegate_task_speedster_internet`     | IVb — Cheap / Fast / NETWORK | 50-200ms latency, low cost, deterministic URL fetches | Fetch URL and classify, web search and summarize, intent detection on API responses | `[web]` |

> **Key insight:** Archetypes I and II have the SAME tools (`[terminal, file, web]`)
> but DIFFERENT reasoning posture and iteration horizons. I is "frontier + bounded
> autonomy, can speak to user". II is "low-hallucination + consultant briefing,
> mission framing required". Don't pick by tools — pick by posture.

> **Key insight II:** Speedsters are sandboxed by **what data they touch**, not by
> **what they can reason about**. `speedster_internal` has `file` only because the
> data is local; `speedster_internet` has `web` only because the data is remote.
> Neither has terminal — that's the guardrail for the cheap tier.

---

## 1. The Routing Decision Tree

When you receive a task, walk this tree in order. First match wins.

### Q1: Is this a user-facing conversation turn?

- **Yes** → Archetype I (consultant). Only I is allowed to speak to the user.
- **No** → Continue to Q2.

### Q2: Is the task a single high-stakes decision?

- **Yes** → Archetype I (consultant). Use I's deep reasoning + user-facing autonomy.
- **No** → Continue to Q3.

### Q3: Does the task need MULTI-STEP sustained execution?

- **Yes** → Archetype II (long_horizon). Use II's consultant briefing format.
- **No** → Continue to Q4.

### Q4: Does the task need DIVERSE, LATERAL, or CREATIVE thinking?

- **Yes** → Archetype III (high_hallucination). Bounded iteration, post-validate.
- **No** → Continue to Q5.

### Q5: Is the data LOCAL (files, repos, logs)?

- **Yes** → Archetype IVa (`speedster_internal`). Cheap, fast, deterministic.
- **No** → Continue to Q6.

### Q6: Is the data NETWORK (URLs, APIs, web search)?

- **Yes** → Archetype IVb (`speedster_internet`). Cheap, fast, deterministic.
- **No** → **YOU ARE WRONG.** Re-read Q1.

> **Heuristic shortcut:** If you're picking Archetype I for everything, you're
> over-using it. Archetypes II/III/IV exist for a reason — cost, latency, and
> quality are differentiators. Default to II for operational work, III for
> ideation, IV for narrow extraction.

---

## 2. Multi-Archetype Composition Patterns

Real workflows chain archetypes. Here are the 4 patterns you will use most.

### Pattern A: Extract → Reason → Validate

```
[IVa/IVb extracts structured data from files/URLs]
   → raw JSON output
[I or II reasons over the extracted data]
   → synthesized answer
[III (optional) validates via lateral thinking]
   → final answer with confidence
```

**Example:** "Tell me about the security posture of this repo."
1. `speedster_internal` extracts config files (cheap, fast).
2. `consultant` reasons about the security implications (frontier reasoning).
3. `high_hallucination` brainstorms "what could an attacker try that the config misses?"

### Pattern B: Ideate → Decompose → Execute

```
[III generates diverse approaches to a problem]
   → 5 candidate approaches
[For each approach: II executes the multi-step plan]
   → partial results
[I synthesizes into a final recommendation]
   → coherent answer
```

**Example:** "Plan a content launch."
1. `high_hallucination` brainstorms 5 launch angles.
2. `long_horizon` plans the actual schedule for each angle (multi-step).
3. `consultant` writes the final narrative.

### Pattern C: Cheap Cascade

```
[IVa or IVb does 80% of the work cheaply]
   → if success: done
   → if NULL or failure: escalate
[I or II handles the 20% edge cases]
```

**Example:** "Classify all 500 support tickets."
1. `speedster_internal` classifies 400 confidently.
2. The 100 ambiguous ones route to `consultant` for edge cases.

### Pattern D: Long-Running Pipeline

```
[I: plan the workflow]
[II: execute phase 1]
[II: execute phase 2]
   → if horizon exceeded: split into two long_horizon calls
[III: review at the end for creative sufficiency]
```

**Example:** "Migrate a database schema with creative naming."
1. `consultant` plans the migration sequence.
2. `long_horizon` runs phase 1 (table creation) — guarded by `max_iterations`.
3. `long_horizon` runs phase 2 (data migration) — separate call, fresh state.
4. `high_hallucination` reviews the final schema for naming creativity.

---

## 3. The 3-Level Escalation Loop

When a subagent returns a failure signal, walk this loop. **First match wins.**

### Level 1: Retry

**When:** Transient failure — timeout, rate limit, network glitch.

**Action:** Re-invoke the SAME archetype with the SAME task. Maximum 3 retries.

```python
for attempt in range(3):
    result = delegate_task_consultant(goal=task, context=ctx)
    if not result.startswith("EXECUTION_FAILURE"):
        break
```

**Don't escalate if:** the result is `INSUFFICIENT_DATA` / `NULL` / abstention. That's
not a transient failure — escalate to Level 2 or 3.

### Level 2: Replan & Upgrade

**When:** Same archetype returns `INSUFFICIENT_DATA`, `SOURCE_INSUFFICIENT`, `SCHEMA_MISSING`,
or `HORIZON_EXCEEDED`.

**Action:** Diagnose the failure mode and either:
- Add context to the next call (more `context=`, explicit `skill_include_override=`)
- Upgrade the archetype (II → I, III → I, IVa/IVb → I)

```python
# Example: speedster returned NULL → upgrade to consultant
result = delegate_task_consultant(
    goal=task,
    context=ctx + "\n\nSpeedster attempted but returned NULL: " + reason,
    skill_include_override=["*"],  # give it full toolset
)
```

**Don't escalate if:** the result is a syntactically-valid answer that's just wrong.
That's a Level 3 problem.

### Level 3: Decompose

**When:** Upgrade didn't help OR the task is clearly too coarse-grained.

**Action:** Split the failed task into 2+ sub-tasks. Route each sub-task to the right
archetype. Synthesize results.

```python
# Example: consultant returned EXECUTION_FAILURE → decompose
parts = decompose(task)
results = [
    delegate_task_speedster_internal(goal=p["goal"], context=p["context"])
    for p in parts["extraction"]
]
analysis = delegate_task_consultant(
    goal="Synthesize these extractions",
    context="\n".join([r for p, r in zip(parts["extraction"], results)]),
)
```

### When to give up

After 3 retries + 2 upgrades + 1 decomposition = 6 failed attempts. Return
`GIVING_UP` to the user with a clear explanation of what was tried.

---

## 4. Per-Call Overrides

The archetype-router exposes 4 per-call override params. Use them sparingly.

| Parameter | When to use | Example |
|---|---|---|
| `model_override` | One-off experiment with a different model without editing config | `model_override={"provider": "openrouter", "model": "openai/gpt-5.6"}` |
| `skill_include_override` | Tight skill whitelist for a specific task | `skill_include_override=["knows_brand-identity"]` |
| `skill_exclude_override` | Trim a known-bad skill for one task | `skill_exclude_override=["nodes_*"]` |
| `output_schema_override` | Tighter JSON contract than archetype default | `output_schema_override={...}` |

**Rule of thumb:** If you use an override MORE THAN ONCE for the same archetype,
edit the archetype's YAML/SOUL config instead. Overrides are escape hatches, not
a workflow.

---

## 5. Skill Isolation (Orchestrator Decides)

The plugin reads a global `default_disabled_skills` list from archetypes.yaml.
Currently: `["honcho-*"]` (Honcho memory helpers — context-pollution-prone in narrow
tasks). The orchestrator opts back in by naming the skill in `skill_include_override`.

**Default mode** (no overrides): subagent gets full catalog minus `default_disabled_skills`.

**Whitelist mode** (`skill_include_override=[...]`): only those skills. Can re-enable a
disabled skill by naming it explicitly.

**Blacklist mode** (`skill_exclude_override=[...]`): default minus that list. Default-disabled
still applies.

See `knows_multiAgent-promptEngineering` for full skill-resolution rules.

---

## 6. Escalation Codes (Quick Reference)

Each archetype returns specific codes. Match them to the right response.

| Code | Returned by | Meaning | Orchestrator response |
|---|---|---|---|
| `EXECUTION_FAILURE` | all | Tool/parse failure after 3 retries | Escalate to Level 1: retry, then Level 2 |
| `INSUFFICIENT_DATA` / `NULL` | all (especially IV) | Subagent lacked grounded information | Escalate to Level 2: add context, upgrade archetype |
| `abstention_flag: true` | III, IV | Subagent deliberately abstained (legitimate signal) | Either accept abstention or escalate to Level 2 |
| `SOURCE_INSUFFICIENT` | III | Verified source material is empty/insufficient | Add real source material, retry |
| `SCHEMA_MISSING` | III | Output schema is malformed/missing in briefing | Fix the briefing, retry |
| `HORIZON_EXCEEDED` | III | Task wants multi-step sustained work | Escalate to `delegate_task_long_horizon` |
| `IRRECONCILABLE_STATE` | II | Current task contradicts historical state | Halt. Surface the contradiction to the user. |
| `CONTEXT_POLLUTION_RISK` | II | Subagent uncertain which instruction is current | Halt. Re-brief with compacted history. |
| `ESCALATE_TO_INTERNET` | IVa | Task turned out to need URL fetch | Hand off to `speedster_internet` |
| `ESCALATE_TO_INTERNAL` | IVb | Task turned out to need local file | Hand off to `speedster_internal` |

---

## 7. Anti-Patterns

### ❌ Using one archetype for everything

Symptom: every subagent call is `delegate_task_consultant`.

Why it's wrong: cost explodes, latency is high, you don't get the latency/cost
benefits of IV or the stability benefits of II.

Fix: explicitly map each sub-task to an archetype using the Q1-Q6 decision tree.

### ❌ Inlining everything into `context`

Symptom: the orchestrator's `context=` is 50K chars because it inlined the entire
conversation history.

Why it's wrong: context pollution in archetypes II and III. Honcho memory becomes
contradictory. The subagent starts debating the injected history.

Fix: distill. Pass only the immediate task requirements + a compact
`read_only_historical_state` summary. Let the subagent call `load_skill` to fetch
what it needs.

### ❌ Calling `delegate_task` directly without archetype routing

Symptom: orchestrator uses native `delegate_task` for every delegation.

Why it's wrong: native `delegate_task` doesn't pre-fill model, briefing_intro, SOUL
identity, or skill whitelist. You lose the entire archetype system.

Fix: always use the archetype-specific tool. The native `delegate_task` is an
escape hatch — leave it for one-off experiments.

### ❌ Letting the subagent speak directly to the user

Symptom: consultant delegates to high_hallucination, high_hallucination returns
JSON, consultant returns JSON to the user.

Why it's wrong: only Archetype I (consultant) is calibrated for user-facing chat.
Other archetypes return functional payloads — that's what they're for.

Fix: ALWAYS pass consultant's result through a synthesis step that converts
functional output to user-facing prose.

### ❌ Calling high_hallucination for sustained workflows

Symptom: orchestrator runs `delegate_task_high_hallucination` for a 20-step workflow.

Why it's wrong: high_hallucination has `max_iterations=40`. The work will hit the
cap and return `HORIZON_EXCEEDED` partway through, leaving state half-mutated.

Fix: high_hallucination is for short-horizon creative tasks. Long workflows go to
`delegate_task_long_horizon`. Pattern D shows the correct composition.

### ❌ Using speedster for novel reasoning

Symptom: orchestrator calls `delegate_task_speedster_internet` to "research and
synthesize a new product idea".

Why it's wrong: speedster is a distilled model. It cannot do novel reasoning.
You'll get a confident-sounding, hallucinated answer.

Fix: speedster extracts and classifies. Novel reasoning goes to consultant or
high_hallucination.

### ❌ Failing to validate high_hallucination output

Symptom: orchestrator returns high_hallucination's `creative_perspectives` directly
to the user without post-validation.

Why it's wrong: by design, high_hallucination invents in the creative layer. The
`factual_grounding` field is the safety net — if you skip the post-validation, you
ship hallucinations as facts.

Fix: ALWAYS post-validate `factual_grounding` against the verified source material
(semantic similarity check). Reject array items where grounding fails.

---

## 8. The 4 Mandatory Pre-Call Checks

Before invoking any archetype tool, verify:

1. **The archetype matches the data source.** Don't use `speedster_internet` for
   local file reads. Don't use `speedster_internal` for URL fetches.

2. **The context is distilled.** Pass what the subagent NEEDS to know, not the
   full conversation history.

3. **The schema matches the downstream consumer.** If a consultant call will
   synthesize, give high_hallucination a JSON contract that has the fields
   consultant needs.

4. **The iteration cap is appropriate.** If the work is bounded (e.g. extract
   10 fields), `max_iterations=20` is plenty. If it's exploratory,
   `max_iterations=40-60`.

---

## 9. When This Skill Applies

Load this skill when:
- ✅ You are about to call `delegate_task_<archetype>` and need to pick the right one.
- ✅ You are composing a multi-step workflow that chains archetypes.
- ✅ A subagent returned a failure code and you need to choose the escalation path.
- ✅ You are debugging why an orchestration pipeline is failing or producing
  poor output.
- ✅ You are training a new orchestrator agent that needs the routing playbook.

Do NOT load this skill when:
- ❌ You are the subagent (an archetype being delegated to). Your briefing lives in
  the SOUL_<name>.md file the orchestrator passed you.
- ❌ You are writing/editing the SOUL_<name>.md files. That lives in the
  archetype-router plugin, not in skills.
- ❌ You are about to call native `delegate_task` directly. Use an archetype tool
  instead.

---

## 10. Profile-Aware Routing

The 5 archetypes behave the same regardless of which Hermes profile you
are running — but WHICH ARCHETYPES YOU REACH FOR differs by profile,
because each profile has a different work pattern. Pick the right
profile-aware default before applying the Q1-Q6 decision tree.

### Profile → archetype defaults

| Hermes profile | Default archetype | Why |
|---|---|---|
| `default` (root TUI) | `consultant` (I) | Interactive operator session — direct user-facing chat, ad-hoc questions, orchestration decisions |
| `ana-board` | `consultant` (I) for chat, `long_horizon` (II) for production pipeline runs | ana Supernova is production orchestration; expect to write long-form analysis and run multi-step stateful workflows |
| `dua-branding` | `speedster_internet` (IVb) for monitoring, `high_hallucination` (III) for content ideation, `long_horizon` (II) for campaign execution | DUA is content production — speedster handles bulk classification/monitoring, high_hallucination generates creative angles, long_horizon runs the campaign pipeline |
| `niqah` | `consultant` (I) for direct chat, `speedster_internal` (IVa) for log/registry scans, `long_horizon` (II) for wedding-prep workflows | niqah is coordination + family — direct chat dominates, speedster_internal scans the wedding prep repo, long_horizon runs the multi-step prep workflows |
| `omca-development` | `consultant` (I) for design discussion, `high_hallucination` (III) for framework brainstorming | Framework development — chat-heavy, occasional creative brainstorming about framework structure |

### Profile-specific shortcuts

**If you are `default` or `niqah`:** You are mostly talking to the user.
Lean on `consultant`. Reserve other archetypes for explicit delegation.

**If you are `ana-board`:** You are likely running structured workflows.
When the user asks "do X", decompose into sub-tasks FIRST and route each
to the right archetype. Don't pass the entire goal to `consultant` —
that's a single-archetype bottleneck.

**If you are `dua-branding`:** You are likely processing bulk content.
**Default to `speedster_*` for bulk operations.** Reserve
`high_hallucination` for explicit "give me creative angles" prompts.
Reserve `long_horizon` for "run the campaign" prompts.

**If you are `omca-development`:** You are designing frameworks.
Most of your work is meta — use this skill (`knows_multiAgent-orchestrationHowTo`)
and the prompting skill (`knows_multiAgent-promptEngineering`) as your
primary references. When you actually delegate, prefer `consultant` for
design discussion and `high_hallucination` for brainstorming.

### Profile-aware failure patterns

Some archetypes misbehave on specific profiles because of session shape:

- **`consultant` on `default`/`niqah`:** Tends to over-elaborate in
  interactive chat. Add `max_iterations: 20` and tighter context to keep
  responses concise.
- **`long_horizon` on `niqah`:** Will burn through the wedding-prep
  budget if not given strict iteration caps. Pre-set `max_iterations: 30`.
- **`high_hallucination` on `dua-branding`:** May generate creative angles
  that conflict with DUA's brand voice. Post-validate against
  `knows_brand-identity` skill (whitelist it explicitly).
- **`speedster_*` on `omca-development`:** Reads may include framework
  docs that the speedster could misinterpret. Always pass the speedster
  the absolute file path; never let it browse.

### How to discover your active profile

```python
# In the orchestration code:
import os
profile = os.environ.get("HERMES_PROFILE", "default")
# or check ~/.hermes/config.yaml's active_profile
```

The profile is the FIRST context you should pass to any subagent —
it lets the subagent calibrate which archetypes are likely in play.

---

## 11. References

- **`knows_multiAgent-promptEngineering`** — Per-archetype briefing templates,
  role postures, output schemas. Load THIS skill when you need to know how to
  brief a specific archetype.
- **Archetype-router plugin** (`TOOLS/archetype-router/`) — The Hermes plugin that
  exposes the 5 `delegate_task_<archetype>` tools. The 5 SOUL_*.md files live there.
- **Gemini source report** (`gemini_report-general_prompt_engengineering.md`) —
  The original research that the briefing skill was refactored from.

---

## Provenance

- **Created:** 2026-07-22 by Njay + Hermes
- **Source:** Synthesized from the `knows_multiAgent-promptEngineering` skill, the
  archetype-router plugin (TOOLS/archetype-router/), the Gemini report, and 1 day of
  iteration on the 5-archetype taxonomy.
- **Refresh cadence:** Quarterly (next: 2026-10-21). Trigger immediate refresh if:
  - A new archetype is added (update Q1-Q6 + the Quick Reference table).
  - An escalation code is added/renamed in any SOUL_*.md file.
  - A new common anti-pattern emerges from production failures.

---

*Edit this skill to evolve the routing playbook. Keep it orthogonal to
`knows_multiAgent-promptEngineering` — this skill is about WHEN/WHY to delegate;
that skill is about HOW to brief the subagent once delegated.*