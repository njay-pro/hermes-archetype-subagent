# Extending the Plugin

> Recipes for adding new archetypes, skills, and tools.

---

## Adding a New Archetype

1. **Add the combo in Honcho's dashboard.** Pick a model chain. Note the combo name (e.g. `arc-researcher1`).

2. **Register the combo in Hermes:**
   ```bash
   hermes config set custom_providers.0.models.arc-researcher1.context_length 1000000 --force
   ```

3. **Add the entry to `archetype_model_config.json`** under `archetypes`:
   ```json
   "researcher": {
     "provider": "custom:9router",
     "model": "arc-researcher1"
   }
   ```

4. **Add the schema to `archetypes.yaml`** under `archetypes`:
   ```yaml
   researcher:
     default_toolsets: [web, file]
     soul: SOUL_researcher.md
     output_schema:
       type: object
       required: [findings]
       properties:
         findings:
           type: array
           items: {type: string}
     max_iterations: 25
   ```

5. **Write `SOUL_researcher.md`** — the persistent identity prose. See [CONFIGURATION.md](CONFIGURATION.md#soul_namemd) for conventions.

6. **Add the tool name to `plugin.yaml`'s `provides_tools`:**
   ```yaml
   provides_tools:
     - delegate_task_researcher
   ```

7. **Add a unit test** to `tests/test_router.py` covering the new archetype's fields.

8. **Run `pytest`** — all 26 tests must still pass.

The plugin auto-picks up the new archetype on next gateway restart.

---

## Adding a New Skill (per-call)

Skills are NOT defined in this plugin. They come from Hermes's external
skill directories. To make a new skill visible to archetypes:

1. Create the skill at `~/Desktop/OMCA-GODMODE/skills/<skill_name>/SKILL.md`.
2. Symlink it to the 4 `AGENT-*` workspaces and `~/.hermes/skills/`.
3. The plugin auto-discovers it via `resolve_skill_filter` walking
   `~/.hermes/profiles/*/config.yaml` → `skills.external_dirs`.

See `~/Desktop/OMCA-GODMODE/skills/AGENTS.md` for full distribution rules.

For an example of a skill the plugin SHIPS WITH (so you can run archetypes
out of the box), see [`docs/skills/`](skills/) and the `install.sh` script.

---

## Adding a New SOUL_*.md

Just write the file. The plugin reads it on every call (no caching). The
file MUST be named `SOUL_<archetypespec_name>.md` and placed in the plugin
root. The `archetypes.yaml` schema's `soul:` field references the filename.

```
archetype-router/
├── SOUL_consultant.md
├── SOUL_long_horizon.md
├── SOUL_high_hallucination.md
├── SOUL_speedster_internal.md
├── SOUL_speedster_internet.md
└── SOUL_<your_new_archetype>.md   ← add this
```

---

## Adding a New Tool Param (e.g. `toolsets_override`)

If you want to add a per-call override for a parameter that's currently
in `default_disabled_skills` or the YAML only, three places to change:

1. **Handler signature** in `router.py:_make_handler`:
   ```python
   def handler(
       # ... existing params ...
       toolsets_override: Optional[List[str]] = None,
       **extra: Any,
   ) -> str:
   ```

2. **Schema** in `router.py:_BASE_PARAMETERS["properties"]`:
   ```python
   "toolsets_override": {
       "type": "array",
       "items": {"type": "string"},
       "description": (
           "Override default_toolsets for this call. Use sparingly — "
           "the archetype's default toolsets are usually right."
       ),
   },
   ```

3. **Wire it through** in `_assemble_brief()` and `archetype_delegate()`:
   ```python
   effective_toolsets = toolsets_override or spec.default_toolsets
   ```

4. **Add a test** in `tests/test_router.py`:
   ```python
   def test_toolsets_override_replaces_defaults(self, router_module):
       # test that the override actually flows through
   ```

5. **Document** in [docs/API.md](API.md) (the public API reference).

6. **Update the SOUL files** that mention the new param so archetypes
   know it exists.

---

## Adding a New Escalation Code

Each archetype's `SOUL_<name>.md` defines its own return codes. The
plugin's `archetype_delegate()` propagates the raw return; the
orchestrator reads the return and decides what to do.

1. **Add the code to the SOUL's `## When To Escalate` section**, e.g.:
   ```markdown
   ## When To Escalate

   Return `MY_NEW_CODE` when:
   - The input is too noisy
   - The tool was rate-limited
   ```

2. **Update the orchestrator skill** (`knows_multiAgent-orchestrationHowTo`):
   - Add the code to the "10 escalation codes" table in section 6
   - Add a handling rule: "If `MY_NEW_CODE`, retry once with a different model"

3. **Document** in [docs/CAPABILITIES.md](CAPABILITIES.md) if it's a new
   cross-archetype pattern.

The plugin itself doesn't need code changes — escalation codes are
prose-level contracts between SOUL and orchestrator.