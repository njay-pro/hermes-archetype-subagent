# Configuration

> Field-level reference for `archetype_model_config.json`, `archetypes.yaml`,
> and `SOUL_<name>.md`. For the operator's view (when to edit which), see
> [README.md → Configuration Split](../README.md#configuration-split-operator-view).

Three files, three concerns. Edit the one that matches your change.

| File | Holds | When to edit | Reload |
|------|-------|--------------|--------|
| `archetype_model_config.json` | provider + model combo per archetype | Model ships/retires; swap combo | **mtime** — instant, no restart |
| `archetypes.yaml` | toolsets, max_iterations, output_schema, `default_disabled_skills` | Persona evolves, skill set changes | **mtime** — instant |
| `SOUL_<name>.md` × 5 | Identity prose (who the archetype is, anti-patterns, escalation codes) | Persona identity changes | **mtime** — re-read on every call |

The 3-way split is **strict**: identity prose NEVER duplicates into YAML.
`SOUL_<name>.md` is the single source of "who is this archetype" prose.

---

## `archetype_model_config.json`

```json
{
  "version": "1.2.0",
  "provider": "custom:9router",      // global default
  "base_url": "http://localhost:20128/v1",
  "archetypes": {
    "consultant": {
      "provider": "custom:9router",
      "model": "arc-consultant1",
      "_comment": "Honcho combo — 9router picks the actual underlying model"
    }
  }
}
```

### Field reference

| Field | Required | Default | Notes |
|---|---|---|---|
| `version` | yes | — | Schema version, bumped on breaking changes |
| `provider` (top-level) | no | `"custom:9router"` | Fallback when an archetype omits its own |
| `base_url` (top-level) | no | `"http://localhost:20128/v1"` | Fallback base_url for the 9router |
| `archetypes.<name>.provider` | no | inherits top-level | Overrides the top-level |
| `archetypes.<name>.model` | yes | — | **Combo name** registered in Honcho (NOT a direct model name) |
| `archetypes.<name>.fallback_chain` | no | `[]` | Informational; 9router handles fallback internally |
| `archetypes.<name>._comment` | no | — | For human readers; stripped at load |

### Combo registration

Combo names must be registered in Hermes's `custom_providers.0.models`
block before they appear here. Use:

```bash
hermes config set custom_providers.0.models.<combo>.context_length 1000000 --force
```

If a combo is referenced from `archetype_model_config.json` but not
registered, `resolve_runtime_provider()` raises `ValueError` and the
delegation fails fast.

### How it gets used

```python
# In archetype_delegate.py:
def resolve_creds_for_spec(spec, model_override=None):
    requested = spec.provider.removeprefix("custom:")  # "9router"
    runtime = resolve_runtime_provider(
        requested=requested,
        target_model=spec.model,  # "arc-consultant1"
    )
    return {
        "model": spec.model,
        "provider": spec.provider,        # "custom:9router"
        "base_url": runtime.get("base_url"),
        "api_key": runtime.get("api_key"),
        "api_mode": runtime.get("api_mode"),
    }
```

The 9router side then resolves the combo to the actual underlying model
+ handles the fallback chain (informational; we don't see it).

---

## `archetypes.yaml`

```yaml
default_disabled_skills:
  - "honcho-*"     # safety net: context-pollution-prone skills off by default

defaults:
  max_iterations: 50
  default_toolsets: [terminal, file, web]

archetypes:
  consultant:
    default_toolsets: [terminal, file, web]
    soul: SOUL_consultant.md
    output_schema: null
    max_iterations: 50
```

### Field reference (top-level)

| Field | Required | Default | Notes |
|---|---|---|---|
| `default_disabled_skills` | no | `[]` | fnmatch globs. Subtracted from EVERY archetype's skill catalog. Orchestrator can opt back in by naming the skill in `skill_include_override`. |
| `defaults` | no | `{}` | Fall-through for missing fields per archetype |

### Field reference (per archetype)

| Field | Required | Default | Notes |
|---|---|---|---|
| `default_toolsets` | yes | inherits `defaults.default_toolsets` | List, must be Hermes toolset names |
| `soul` | yes | `SOUL_<name>.md` | Filename relative to plugin root |
| `output_schema` | no | `null` | JSON Schema (or null for freeform) |
| `max_iterations` | yes | inherits `defaults.max_iterations` | Int, passed to AIAgent |

### Skill resolution

The plugin walks 6 skill roots to discover the catalog:

```python
# (from router.py)
def _resolve_skill_roots() -> List[Path]:
    roots = []
    # ~/.hermes/skills/ always
    roots.append(Path.home() / ".hermes" / "skills")
    # ~/.hermes/profiles/*/skills/ for each profile
    for prof in Path.home().glob(".hermes/profiles/*/skills"):
        roots.append(prof)
    # ~/.hermes/profiles/*/config.yaml -> skills.external_dirs (4 profiles)
    for cfg in Path.home().glob(".hermes/profiles/*/config.yaml"):
        config = yaml.safe_load(cfg.read_text())
        for ext in config.get("skills", {}).get("external_dirs", []):
            roots.append(Path(ext).expanduser())
    return roots
```

The skill catalog is the union of all skill names found in those roots,
minus the global `default_disabled_skills` list.

### When you should NOT edit this file

- To change a model — edit `archetype_model_config.json`
- To change persona prose — edit `SOUL_<name>.md`
- To add a new archetype — also edit `archetype_model_config.json` AND `plugin.yaml`

---

## `SOUL_<name>.md`

Plain markdown. The plugin reads it as a string and prepends it to the
composed brief.

### Conventions (per skill `knows_prompts-material` style)

- `# SOUL — <Name> Archetype` as the first heading
- `## Who You Are` — persona identity
- `## How You Are Briefed` — input contract
- `## Anti-Patterns` — what NOT to do
- `## When To Escalate` — return codes

### SOULs in this plugin

| File | Lines | Archetype |
|------|-------|------------|
| `SOUL_consultant.md` | ~85 | I — Raw Power / Frontier |
| `SOUL_long_horizon.md` | ~95 | II — Low-Hallucination / Stable |
| `SOUL_high_hallucination.md` | ~120 | III — Creative / Lateral |
| `SOUL_speedster_internal.md` | ~125 | IVa — Cheap / LOCAL Files |
| `SOUL_speedster_internet.md` | ~125 | IVb — Cheap / NETWORK Fetches |

### What NEVER goes in SOUL

- The model's name or 9router combo — that's `archetype_model_config.json`
- Toolset list or iteration cap — that's `archetypes.yaml`
- Skill lists — those come from Hermes's external_dirs

If you find yourself adding these to a SOUL file, you have the wrong
file. Refactor.

### How SOULs are read

```python
# In router.py:
def _read_soul(spec: ArchetypeSpec) -> str:
    try:
        return spec.soul_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        logger.warning(f"SOUL not found at {spec.soul_path}")
        return ""
```

The string is prepended to the composed brief. The plugin does NOT parse
the SOUL — it's pure prose. Any structure you put in the SOUL is for
the subagent's benefit, not the orchestrator's.

---

## mtime-based cache invalidation

All three config files are auto-reloaded by `load_archetypes()`:

```python
# In router.py:
def _cache_key() -> tuple:
    """Returns (model_mtime, schema_mtime) — invalidates when either changes."""
    model_mtime = (PLUGIN_DIR / "archetype_model_config.json").stat().st_mtime
    schema_mtime = (PLUGIN_DIR / "archetypes.yaml").stat().st_mtime
    return (model_mtime, schema_mtime)

def load_archetypes(force_reload: bool = False) -> Dict[str, ArchetypeSpec]:
    if not force_reload and _ARCHETYPES_CACHE and _CACHE_KEY == _cache_key():
        return _ARCHETYPES_CACHE
    # ... reload ...
    _CACHE_KEY = _cache_key()
    _ARCHETYPES_CACHE = specs
    return specs
```

**Implication:** editing any of the three files takes effect on the
**next delegation call** — no plugin restart, no gateway restart, no
skill reload.

The `SOUL_<name>.md` files are NOT cached — they're re-read on every
call. So you can iterate on persona prose live.

---

## Verifying your config

```bash
cd /Users/njaypro/Desktop/OMCA-GODMODE/TOOLS/archetype-router
/Users/njaypro/.hermes/hermes-agent/venv/bin/python3 -c "
import importlib.util
spec = importlib.util.spec_from_file_location('r', 'router.py')
r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)
for name in r.list_archetypes():
    s = r.get_archetype(name)
    print(f'{name:25} provider={s.provider!r:20} model={s.model!r:25} tools={s.default_toolsets}')
"
```

Expected output:

```
consultant                provider='custom:9router'    model='arc-consultant1'         tools=['terminal', 'file', 'web']
long_horizon              provider='custom:9router'    model='arc-longHorizon1'       tools=['terminal', 'file', 'web']
high_hallucination        provider='custom:9router'    model='arc-highHallucination1' tools=['terminal', 'file', 'web']
speedster_internal        provider='custom:9router'    model='arc-speedster1'          tools=['file']
speedster_internet        provider='custom:9router'    model='arc-speedster1'          tools=['web']
```