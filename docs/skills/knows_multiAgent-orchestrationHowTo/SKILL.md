---
name: knows_multiAgent-orchestrationHowTo
description: |
  Routing, delegation, cognitive mindsets, and escalation playbook for OMCA multi-agent orchestration.
  Covers the 4-phase lifecycle: Intent Distillation & Architecture (Consultant + Chip/Speedster),
  Execution Workload Delegation (Long Horizon as Priority #1 Workhorse),
  Creative/Alternatives Branching (High Hallucination short-horizon), and Mandatory High-Level
  Review & Near-Completion Synthesis. Includes per-archetype delegation mindsets and the
  v0.3.x plugin's context-passing primitives (3-layer skill filter, preload_files).
version: "2.2.0"
tags: ["omca", "multi-agent", "orchestration", "routing", "escalation", "archetype", "delegation", "cognitive-mindsets"]
category: project-setup
load_when: "agent needs to decide which archetype to delegate to, plan multi-archetype composition, apply cognitive delegation mindsets, or execute the orchestration lifecycle"
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
    - knows_multiAgent-promptEngineering
---

> **v2.2.0 (2026-07-23) — plugin primitives update.** Section 6 (Context Isolation)
> now documents the v0.3.x plugin's three primitives for handing context to
> subagents: the `goal`/`context` slots (always-on), `preload_files` (optional,
> for handing a subagent a file upfront — e.g. a TODO.md or design spec), and
> the 3-layer skill filter (L1 OMCA utils baseline / L2 honcho-* disabled by
> config / L3 orchestrator override per call). The v2.1 wording about
> "skill_include_override / skill_exclude_override" remains accurate; this
> release adds the L1/L2/L3 layer model around those existing slots.
> Also added the Speedster-narrow-by-design note (Section 0 / Section 7) so
> orchestrators don't mistake deliberate `EXECUTION_FAILURE` for a bug.

# Multi-Agent Orchestration: Routing, Delegation & Review Playbook

This skill defines how the **Orchestrator Agent** distills user intent, formulates execution strategy, applies specific cognitive delegation mindsets per archetype, delegates subtasks, performs mandatory high-level reviews, and synthesizes final deliverables.

---

## 0. The Orchestrator Core Role & 4-Archetype Taxonomy

```
                  ┌─────────────────────────────────────────────────────────┐
                  │                 ORCHESTRATOR AGENT                      │
                  │   (High-Level Manager & Reviewer of all subagent results) │
                  └──────────────────────────┬──────────────────────────────┘
                                             │
      ┌──────────────────────────────────────┼──────────────────────────────────────┐
      │ Phase 1: Intent & Arch               │ Phase 2 & 3: Execution & Creative     │ Phase 4: Near Goal
      ▼                                      ▼                                      ▼
┌───────────┐  ┌─────────────┐       ┌─────────────────┐  ┌────────────────────┐    ┌───────────┐
│ Cheap /   │  │ Consultant  │       │ Long Horizon    │  │ High Hallucination │    │ Consultant│
│ Speedster │  │ (Archetype I│       │ (Archetype II)  │  │ (Archetype III)    │    │ (Archetype│
│ (IVa/IVb) │  │ )           │       │                 │  │                    │    │ I)        │
└─────┬─────┘  └──────┬──────┘       └────────┬────────│  └─────────┬──────────┘    └─────┬─────┘
      │               │                       │                   │                     │
 Fast scans,    Intent distillation,   PRIMARY WORKHORSE    Short-horizon tasks,   Architecture,
 extraction,    clarifying ambiguity,  for execution.       creative/lateral,      final alignment,
 pre-filtering. goal formulation.      Splits goal into     generating 3           goal completion
                                       long stateful tasks. alternatives.          review.
```

### Quick Reference Matrix

| Tool | Archetype | Operational Role | Primary Purpose | Default Tools |
|---|---|---|---|---|
| `delegate_task_consultant` | **Archetype I — Raw Power** | Intent Distiller & Architecture Advisor | Ambiguity resolution, initial goal formulation, architectural decisions, near-completion final synthesis | `[terminal, file, web]` |
| `delegate_task_long_horizon` | **Archetype II — Low Hallucination** | **Priority #1 Execution Workhorse** | Executing long, stateful, multi-step subtasks with anti-drift stability | `[terminal, file, web]` |
| `delegate_task_high_hallucination` | **Archetype III — Creative / Lateral** | Short-Horizon Creative & Alternatives Explorer | Ideation, short creative coding, generating 3 distinct alternatives/approaches | `[terminal, file, web]` |
| `delegate_task_speedster_internal` | **Archetype IVa — Fast Local** | Intent Distillation Assistant (Files) | Fast scanning, extraction, and pre-filtering across local code/files | `[file]` |
| `delegate_task_speedster_internet` | **Archetype IVb — Fast Network** | Intent Distillation Assistant (Network) | Fast fetching, classification, and pre-filtering across web/APIs | `[web]` |

**Speedster is narrow by design.** Speedster's SOUL enforces a pre-shaped
`STEP 1, STEP 2, ...` execution tree. Feed it an open-ended goal like
"audit this codebase" and it returns `EXECUTION_FAILURE /
NO_EXECUTION_TREE_PROVIDED` — that's correct behavior, not a bug. For
open-ended analysis use `consultant` or `long_horizon`. The Speedster
discipline is the same one used by `high_hallucination`: keep the goal
narrow, scope the output, and the model wins.

---

## 1. The 4-Phase Operational Orchestration Lifecycle

### Phase 1: Intent Distillation & Architectural Alignment
* **Goal**: Ensure the user and agent are fully aligned on the objective and strategy.
* **Orchestrator Role**: Formulate the overarching goal and execution roadmap.
* **Delegation**:
  * **Chip / Speedster (Archetype IVa/IVb)**: Deployed to rapidly scan local files, inspect repos, or pull web endpoints to feed grounded facts into intent distillation.
  * **Consultant (Archetype I)**: Deployed when intent is ambiguous, or when complex architectural choices (e.g. framework selection, system design) must be evaluated.
* **Exit Condition**: Clear goal definition and strategy split into discrete subtasks.

### Phase 2: Workload Execution (Primary Priority: Long Horizon)
* **Goal**: Execute operational, stateful, multi-step subtasks reliably.
* **Orchestrator Role**: Split the master goal into executable long subtasks.
* **Delegation**: **Priority #1 is Archetype II (`delegate_task_long_horizon`)**.
  * Each task delegated to Archetype II is framed with strict operational goals, mission context, and anti-debate constraints.
  * Archetype II maintains low hallucination and anti-drift stability across multi-step execution loops.
* **Exit Condition**: All execution subtasks completed with verified functional outputs.

### Phase 3: Creative & Multi-Alternative Exploration
* **Goal**: Solve creative challenges or generate diverse choices when single-path logic is insufficient.
* **Orchestrator Role**: Identify short-horizon creative or exploratory needs (e.g., "give me 3 distinct architecture options").
* **Delegation**: **Archetype III (`delegate_task_high_hallucination`)**.
  * Keep iteration horizon short (`max_iterations` bounded).
  * Ideal for brainstorming, lateral problem solving, UI/UX variations, and multi-option comparisons.
* **Exit Condition**: Diverse options generated with explicit factual grounding citations for orchestrator review.

### Phase 4: Mandatory High-Level Review & Near-Completion Synthesis
* **Goal**: Validate subagent deliverables, ensure quality alignment, and assemble final user response.
* **Orchestrator Role**: **ALWAYS act as the High-Level Reviewer**.
  * Never pass raw subagent JSON/payloads directly to the user.
  * Review all subagent results against the primary objective.
  * Re-deploy **Consultant (Archetype I)** if near-completion synthesis requires frontier reasoning or user-facing prose polishing.
* **Exit Condition**: High-confidence, validated deliverable ready for presentation.

---

## 2. Cognitive Delegation Mindsets (How to Think When Delegating)

How the Orchestrator frames a subtask profoundly affects the subagent's performance. Apply these specific cognitive mindsets for each archetype:

### 2.1 Archetype I: Consultant (Raw Nuance & System Context)
* **Mindset**: **Pass the raw friction; do not pre-digest**.
* **Delegation Rule**: State the user's core concern and friction **without heavy wording alteration**. Include broader potential conflicts, system trade-offs, and underlying motivations.
* **Why**: Frontier models excel at reading between lines and resolving deep ambiguity. Pre-digesting or flattening user nuance strips away signals the Consultant needs to make sound architectural judgments.

### 2.2 Archetype II: Long Horizon (Self-Organized To-Do Lists)
* **Mindset**: **Frame the mission, not the step-by-step micro-plan**.
* **Delegation Rule**: Instruct Archetype II to **generate and manage its own dynamic To-Do list / checklist** for execution. **DO NOT pre-build the step-by-step checklist for it!**
* **Why**: Over-specifying micro-steps causes context pollution and degrades long-horizon stability. Frame the target goal, boundary constraints, and read-only state—let Archetype II manage its internal execution steps.

### 2.3 Archetype III: High Hallucination (Deep Descriptive Intent & Anchors)
* **Mindset**: **Trigger latent creativity with multi-dimensional intent**.
* **Delegation Rule**: Provide rich, multi-dimensional descriptions, conceptual/artistic intentions, structural angles, and worked anchors (few-shot examples).
* **Analogy**: Like prompt engineering for image models (describing how fabric falls into a tie, material behavior across the chest, photographic silhouette). For text/code/ideation, specify structural depth, aesthetic intention, and physical/systemic constraints so creative generation is rich, vivid, and grounded.

### 2.4 Archetype IV: Cheap / Distilled Speedster (Latent Space Pre-Loading)
* **Mindset**: **Unload latent coordinates upfront**.
* **Delegation Rule**: Distilled models are fast and capable, but lack automatic latent orientation. Inject high-level domain orientation, pre-calculated decision rules, and explicit tool names upfront.
* **Why**: Pre-loading coordinates "tricks" the distilled model into landing in the exact right region of its latent space immediately, yielding frontier-like precision at 10x lower cost and 50ms latency.

---

## 3. Decision Tree for Subtask Routing

When preparing to delegate a subtask, walk this decision tree in order:

```
                          [Subtask Delegation Request]
                                       │
            Is this Intent Distillation or Pre-Filtering data?
                                ├── YES ──► Data is local? ──► speedster_internal (IVa)
                                │                      └──► speedster_internet (IVb)
                                └── NO
                                       │
               Is this an Architectural Decision or User Chat?
                                ├── YES ──► delegate_task_consultant (Archetype I)
                                └── NO
                                       │
            Is this a Short-Horizon Creative / 3-Alternatives task?
                                ├── YES ──► delegate_task_high_hallucination (Archetype III)
                                └── NO
                                       │
                      DEFAULT EXECUTION WORKHORSE (Priority #1)
                                       │
                                       ▼
                       delegate_task_long_horizon (Archetype II)
```

---

## 4. Multi-Archetype Composition Patterns

### Pattern A: Distill & Scan → Plan Architecture → Long-Horizon Execution
1. `speedster_internal` pre-loads latent coordinates and extracts codebase configs fast.
2. `consultant` reviews raw user concerns and system context to establish architecture.
3. `long_horizon` generates its own dynamic To-Do list and executes the multi-step build.
4. Orchestrator reviews output and synthesizes final result.

### Pattern B: Multi-Option Generation → Review → Execute
1. Orchestrator deploys `high_hallucination` with rich descriptive intent to generate **3 distinct candidate approaches**.
2. Orchestrator reviews the 3 alternatives, selects the optimal path.
3. `long_horizon` executes the selected path step-by-step.

### Pattern C: Fast Cascade for Bulk Data
1. `speedster_internal` / `speedster_internet` processes bulk inputs (80% volume).
2. Ambiguous or failed items escalate to `consultant` or `long_horizon`.

---

## 5. Orchestrator Review & 3-Level Escalation Loop

### Mandatory Review Rule
The Orchestrator **must review every result** returned by a subagent:
1. Is the output complete and schema-compliant?
2. Did the subagent hit an error code (`EXECUTION_FAILURE`, `INSUFFICIENT_DATA`, `HORIZON_EXCEEDED`)?
3. Does the result satisfy the requested subtask objective?

### 3-Level Escalation Loop

```
                     [Subagent Execution Result]
                                  │
                          Did the task fail?
                                  │
             ┌────────────────────┴────────────────────┐
             ▼                                         ▼
         [SUCCESS]                                 [FAILURE]
             │                                         │
 Orchestrator reviews &                   Level 1: Auto-Retry (Same Archetype, max 3x)
 advances pipeline.                                    │ (Fails)
                                                       ▼
                                          Level 2: Replan & Upgrade
                                          (Add context; IV ──► II/I, III ──► II/I)
                                                       │ (Fails)
                                                       ▼
                                          Level 3: Decompose
                                          (Split subtask into smaller atomic tasks)
```

| Escalation Code | Returned By | Meaning | Orchestrator Action |
|---|---|---|---|
| `EXECUTION_FAILURE` | All | Tool/parse error | Level 1 Retry $\rightarrow$ Level 2 Replan |
| `INSUFFICIENT_DATA` / `NULL` | IV, III | Missing grounded context | Upgrade to Archetype II or I with injected sources |
| `HORIZON_EXCEEDED` | III | Work exceeded short creative cap | Escalate to Archetype II (`long_horizon`) |
| `IRRECONCILABLE_STATE` | II | Subtask contradicts history | Halt. Surface contradiction to user or re-brief |

---

## 6. Context Isolation & Skill Overrides

The archetype-router plugin exposes three primitives for handing context
to a subagent. Use them in this order; each builds on the previous:

### 6.1 The three slots

| Slot | What it answers | When to fill it |
|---|---|---|
| `goal` | **what** the subagent should do | always — this is the task |
| `context` | **why / with what** the subagent needs to know | always if there's backgrounder worth passing |
| `preload_files` | **hand the subagent a file upfront** | optional — when the subagent needs to see a specific file's contents (e.g. TODO.md, a design spec, a raw meeting transcript) |

`goal` is per-call. `context` is usually stable across many calls in
the same session (write it once, reuse it). `preload_files` is the
escape hatch for "this specific subagent needs THIS specific file."

```python
# typical call — keep the slot surface small
delegate_task_long_horizon(
    goal="Refactor plugin.py into 3 modules: routing, delegate, brief.",
    context="Audience: hermes-core plugin authors. Goal: smaller files, "
             "clearer seams, no behavior change. Style: minimal, stdlib only.",
    # preloaded_file: leave empty unless the subagent needs a specific file
)
```

### 6.2 When to use `preload_files`

`preload_files` reads each file from disk and inlines its content into
a `## Preloaded Files` section of the brief the subagent sees. The
content sits between the goal and the available-skills list, so the
subagent reads it as **input data**, not instruction.

Use it when:
- The subagent needs to know what's in a TODO.md / design spec / RFC
  / raw transcript to do its job
- The orchestrator already knows WHICH file matters (no discovery
  step needed — just hand it over)
- You want to avoid "subagent reads the file then re-summarizes it back"
  round-trips

**Don't** use it when:
- The subagent has the `[file]` toolset — let it read on demand
- The file is large (>100KB) — split it or summarize it into `context` instead
- You don't know which file matters — let the subagent discover via tools

Caps (in v0.3.x): **100KB per file, 1MB total per delegation**. Files
above the cap are truncated with a `[... truncated at N bytes ...]`
marker; missing files surface as text in the brief, not exceptions.

### 6.3 Skill filtering: the 3-layer model

The plugin's default skill universe is **all OMCA utils** — every
`knows_*`, `nodes_*`, `subflows_*`, `omca-*` skill. Honcho memory
helpers (`honcho-*`) are excluded by default. Per call, the orchestrator
can narrow further.

Resolution order (top to bottom, each layer narrows the previous):

| Layer | Where it lives | What it does |
|---|---|---|
| **L1 — code baseline** | `DEFAULT_OMCA_UTILS_GLOBS` in `router.py` | Starting catalog = all OMCA utility skills |
| **L2 — config safety net** | `archetypes.yaml → default_disabled_skills` | Removes skills that shouldn't run by default (currently `honcho-*`) |
| **L3 — orchestrator override** | per-call slot | `skill_include_override=["..."]` whitelist OR `skill_exclude_override=["..."]` blacklist |

Default behavior: subagent sees the L1 catalog minus L2. Use L3 only
when you need to deviate.

```python
# default — sees all OMCA utils, no honcho
delegate_task_consultant(goal="...")

# narrow to one skill (whitelist)
delegate_task_speedster_internet(
    goal="Fetch the changelog from example.com/changelog",
    skill_include_override=["knows_changelog-watcher"],
)

# exclude one skill (blacklist on top of L1)
delegate_task_long_horizon(
    goal="...",
    skill_exclude_override=["nodes_publish-*"],
)
```

**Don't conflate with the brief's `## Available Skills` section.** The
brief is informational text the subagent reads. The runtime's per-skill
gating (via `requires_toolsets` in each skill's `SKILL.md` frontmatter)
runs independently — but in practice, no skill in this environment
declares any gating conditions, so the brief is the source of truth.

### 6.4 Output Schema Contracts

Enforce strict JSON schemas for deterministic orchestrator parsing. If
a subagent returns free-form prose, the orchestrator has to re-parse —
defeats the schema discipline. Use the `output_schema_override` slot
when you need a different schema than the archetype's default.

---

## 7. Common Anti-Patterns to Avoid

* ❌ **Bypassing Long Horizon as Priority #1**: Using `consultant` for routine execution instead of `long_horizon`.
* ❌ **Pre-Building To-Do Lists for Long Horizon**: Micro-managing step-by-step tasks instead of instructing Long Horizon to self-manage its execution checklist.
* ❌ **Over-Filtering Consultant Briefings**: Pre-digesting user concerns into flat summaries instead of passing raw nuance.
* ❌ **Vague Prompts for High Hallucination**: Giving generic prompts instead of multi-dimensional descriptive intent and worked anchors.
* ❌ **Un-Oriented Speedster Delegation**: Expecting distilled models to infer latent context without pre-loaded coordinates.
* ❌ **Skipping Orchestrator Review**: Returning raw subagent outputs directly to the user without validation.
* ❌ **Treating Speedster's `EXECUTION_FAILURE` as a bug**: Speedster rejects open-ended goals by design — use Consultant or Long Horizon for those.
* ❌ **Inlining large files into `context`**: If the content is >100KB, use `preload_files` instead so the file shows up as `## Preloaded Files` (clearly labeled as input, not instruction).
* ❌ **Asking the orchestrator to filter skills every call**: That was the original v0.3.1 default and it failed at high rate. The L1 OMCA-utils baseline is the safe default; use L3 override only when you specifically need to narrow.

## Provenance
* **v2.2.0 (2026-07-23):** Updated by Njay + Hermes to reflect the archetype-router plugin's v0.3.x primitives — `preload_files` slot and the 3-layer skill filter (L1 OMCA utils / L2 honcho-* / L3 orchestrator override). Added Speedster-narrow-by-design note in Section 0 and Section 7. Anti-patterns extended with the 3 new gotchas.
* **v2.1.0 (2026-07-22):** Refactored by Njay + Antigravity.
* **Refresh Cadence:** Quarterly (next target: 2026-10-21)