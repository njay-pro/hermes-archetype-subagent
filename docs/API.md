# Public API

> Reference for every public function the plugin exports. For the
> operator's view of the 5 tools, see [README.md → The 5 Tools](../README.md#the-5-tools).

---

## From `router.py`

```python
def load_archetypes(force_reload: bool = False) -> Dict[str, ArchetypeSpec]:
    """Load + merge archetype_model_config.json + archetypes.yaml → ArchetypeSpec dict.
    Cached by file mtime; force_reload=True bypasses."""

def reload_archetypes() -> Dict[str, ArchetypeSpec]:
    """Force reload (drops cache)."""

def get_archetype(name: str) -> ArchetypeSpec:
    """Lookup by name. Raises KeyError if unknown."""

def list_archetypes() -> List[str]:
    """All archetype names in load order."""

def get_default_disabled_skills() -> List[str]:
    """Skills excluded from EVERY archetype unless orchestrator opts in."""

def resolve_orchestrator_skill_filter(
    skill_include_override: Optional[List[str]],
    skill_exclude_override: Optional[List[str]],
    roots: Optional[List[Path]] = None,
) -> List[str]:
    """Orchestrator-decided skill filtering. Returns sorted list of skill names."""

def apply_model_override(spec: ArchetypeSpec, override: Dict[str, str]) -> ArchetypeSpec:
    """Per-call model swap (escape hatch). Returns NEW spec — original is not mutated."""

def describe_config_split() -> Dict[str, str]:
    """Diagnostic: which file holds what."""

def register(ctx) -> None:
    """Hermes plugin entry — registers 5 tools with the registry. Called once at load."""
```

---

## From `archetype_delegate.py`

```python
def archetype_delegate(
    spec: ArchetypeSpec,
    brief: str,                      # composed brief (SOUL + goal + skills + schema)
    context: Optional[str],
    toolsets: List[str],             # e.g. ["terminal", "file", "web"]
    parent_agent: Any,               # the AIAgent calling us
    *,
    role: str = "leaf",
    background: bool = False,
    model_override: Optional[Dict[str, str]] = None,
) -> Any:
    """Build child AIAgent and run_conversation. Returns final_response string
    (sync) or concurrent.futures.Future (background=True)."""

def resolve_creds_for_spec(
    spec: ArchetypeSpec,
    model_override: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Resolve {provider, model, base_url, api_key, api_mode} from spec + 9router."""
```

---

## Tool Param Schemas

Each of the 5 `delegate_task_<archetype>` tools exposes the same params:

### Native passthrough (6)

| Param | Type | Notes |
|---|---|---|
| `goal` | string | The task |
| `context` | string | Orchestrator-provided scaffolding (optional) |
| `tasks` | array of {goal, context, role, max_iterations} | Batch mode |
| `max_iterations` | int | Override archetype's default |
| `role` | string | `"leaf"` (default) or `"orchestrator"` |
| `background` | bool | Async dispatch via ThreadPoolExecutor |

### Plugin extras (4)

| Param | Type | Notes |
|---|---|---|
| `output_schema_override` | object | Per-call JSON contract (overrides archetype's YAML schema) |
| `skill_include_override` | array of strings | Whitelist; can re-enable `default_disabled_skills` |
| `skill_exclude_override` | array of strings | Blacklist; applied on top of `default_disabled_skills` |
| `model_override` | object `{provider, model}` | Per-call model swap (escape hatch) |

### Pattern matching for skill params

The plugin uses an extended fnmatch that handles skill-naming-prefixes:

| Pattern | Matches |
|---|---|
| `knows_*` | `knows_brand-identity`, `knows_longHorizonDocs` |
| `honcho-*` | `knows_honcho-best-practice`, `nodes_honcho-something` |
| `nodes_caption` | exactly `nodes_caption` |
| `omca-_*` | `omca-omca-mcp-bridge` |

The prefix-extraction logic: if the pattern has a `tier-` (dash) or `tier_`
(underscore) prefix that the skill also has, the matcher compares the
remaining string with fnmatch. This lets `honcho-*` match
`knows_honcho-best-practice` without writing `knows_honcho-*`.