# Roadmap

> What we're working toward next, in priority order.

---

## Near-term (next 1-2 sessions)

### Multi-task batching in `_make_handler`

Currently one task per call. Add native-style batch by looping and
collecting results:

```python
if tasks:
    results = []
    for t in tasks:
        r = archetype_delegate(spec, brief, ...)
        results.append(r)
    return results
```

The infrastructure is already there — `tasks` is a native param. The
plugin just needs to iterate instead of treating it as a single call.

**Effort:** ~20 LOC + tests.

### Role enforcement

Currently we accept `role=` and pass it through. We don't check
`_get_max_spawn_depth()` or enforce `leaf` vs `orchestrator`. This is a
copy of native's `_normalize_role` logic.

**Effort:** ~10 LOC. Copy from native.

### CI integration

`.github/workflows/test.yml` running:
- pytest with coverage gate (≥ 80%)
- ruff lint
- mypy type check (lenient: `ignore_missing_imports=True`)

**Effort:** ~30 LOC YAML. Add a CI badge to README.

### LICENSE + CONTRIBUTING + CHANGELOG

For "imagine you'll open-source it tomorrow" tier:
- `LICENSE` (MIT)
- `CONTRIBUTING.md` (dev setup, test commands, PR review checklist)
- `CHANGELOG.md` (Keep-a-Changelog format, v0.3.0 entry)

**Effort:** ~80 LOC of boilerplate.

---

## Mid-term (next 2-4 sessions)

### Fallback exhaustion detection

If `arc-consultant1` exhausts its 9router fallback chain (3 models
tried, all failed), the plugin should escalate to `arc-longHorizon1`
automatically. The signal: 3 consecutive `EXECUTION_FAILURE` returns
from the subagent, or a specific error code in the result.

**Effort:** ~50 LOC + tests. Pairs well with the 3-level escalation loop
documented in `knows_multiAgent-orchestrationHowTo`.

### Pattern detection: composite calls

Single tool that does "speedster → consultant" as a pipeline:

```python
delegate_task_classify_then_reason(
    goal="Classify this by topic, then analyze each category",
    # internally: speedster_internal first, then consultant on the classified result
)
```

**Effort:** ~100 LOC. New spec type: `archetype_pair` instead of `archetype`.

### Real-time cost tracking

Parse token usage from the live transcript log, expose as a
`cost(archetype_name)` helper. Add to a `/cost` dashboard that shows
cumulative cost per archetype per session.

**Effort:** ~80 LOC + dashboard frontend.

### Memory tiering

Add an `memory_tier` field to `archetypes.yaml`:
- `"none"` — no memory between calls (default for speedsters)
- `"session"` — share within a single Hermes session
- `"persistent"` — share across sessions (uses Honcho)

The plugin injects memory fetch/build calls around `archetype_delegate()`.

**Effort:** ~150 LOC. Requires Honcho integration tests.

---

## Long-term (next 1-2 months)

### Archetype inheritance

Allow an archetype to extend another:
```yaml
archetypes:
  consultant_creative:
    extends: consultant
    output_schema: {...}  # override just the schema
    max_iterations: 80     # override just the cap
```

Reduces duplication when 3 archetypes share 80% of config.

### Cross-archetype composition DSL

A small declarative language for pipelines:
```yaml
pipelines:
  analyze_repo:
    - speedster_internal: classify README files
    - consultant: analyze top categories
    - high_hallucination: generate marketing angles
```

Compile down to a `pipeline_delegate` tool that calls the archetypes in
sequence with shared context.

### Open-source release prep

- Move repo to `njay-pro/omca-archetype-router` on GitHub
- Tag `v1.0.0` (breaking-change boundary for stable public API)
- Add GitHub issue templates
- Add "good first issue" labels
- Write blog post: "Why we forked `delegate_task` into 5 specialists"

---

## Out of scope (we won't do this)

- **Re-implementing `delegate_task` from scratch** — we mimic, not replace.
- **Bypassing Hermes entirely** — the plugin is a plugin, not a fork.
- **Custom model routing inside the plugin** — that's 9router's job.
- **Per-user personalization** — the plugin is shared across all profiles;
  customization happens at the SOUL level, not the plugin level.

---

## Contributing

Have an idea that fits the roadmap above? Want to add a new archetype?
See [EXTENDING.md](EXTENDING.md) for the recipes, and the AGENTS.md
file map for which file to touch.

For anything not on the roadmap, open an issue with the `proposal`
label first. Big changes get discussed before they get built.