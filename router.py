"""
OMCA Archetype Router — Mimic subagent execution architecture.

Pre-fills per-archetype configuration and instantiates AIAgent directly in-memory:
  - Pre-fills `model` from archetype_model_config.json (the canonical
    model/provider map — edit THIS file to retarget models)
  - Pre-fills `toolsets`, skill whitelist, output_schema from archetypes.yaml
    (stable schema — edit only when evolving mechanical config)
  - Injects the archetype's SOUL_<name>.md as persistent identity
    (the SINGLE source of identity/briefing prose)
  - Resolves skill glob patterns (knows_*, knows_leverage-*, folder-based)
    into the subagent's available skill set
  - Instantiates child AIAgent in-memory with zero file-system writes

CONFIGURATION SPLIT (since 2026-07-22):
  - archetype_model_config.json — model + provider ONLY (rotates often)
  - archetypes.yaml             — schema (stable: skills, SOUL, briefing)

Author: Njay + Hermes (OMCA framework)
"""

from __future__ import annotations

import fnmatch
import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

PLUGIN_DIR = Path(__file__).resolve().parent
SCHEMA_FILE = PLUGIN_DIR / "archetypes.yaml"              # stable schema
MODEL_CONFIG_FILE = PLUGIN_DIR / "archetype_model_config.json"  # rotatable model map

# Hermes skill resolution — matches the same paths the native loader uses.
# See ~/.hermes/profiles/<name>/config.yaml -> skills.external_dirs
# and ~/Desktop/AGENT-*/.opencode/skills for the workspace mirror.
_HERMES_SKILL_ROOTS_ENV = "HERMES_SKILL_ROOTS"


# ---------------------------------------------------------------------------
# YAML loader (PyYAML if available; minimal fallback for our flat shape).
# JSON loader is stdlib (json) — always available.
# ---------------------------------------------------------------------------

def _yaml_safe_load(path: Path) -> dict:
    """Load archetypes.yaml; PyYAML if available, minimal parser otherwise."""
    try:
        import yaml  # type: ignore

        with path.open("r", encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}
    except ImportError:
        logger.warning("PyYAML unavailable — falling back to minimal loader for %s", path)
        return _minimal_yaml_load(path.read_text(encoding="utf-8"))


def _minimal_yaml_load(text: str) -> dict:
    """Minimal fallback for our flat archetypes.yaml shape.

    Handles:
      - top-level `key:` scalars
      - nested 2-space-indent `key: value` (str/int/list)
      - list items starting with `- ` (strings only)

    Does NOT handle: anchors, multi-line scalars, complex nested mappings.
    Adequate for our archetypes.yaml which uses flat key: value with simple
    string lists for skill_include / skill_exclude.
    """
    out: Dict[str, Any] = {}
    current_section: Optional[str] = None
    current_list_key: Optional[str] = None
    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if not raw.startswith(" ") and stripped.endswith(":"):
            current_section = stripped[:-1]
            out[current_section] = {}
            current_list_key = None
            continue
        if raw.startswith("      - "):
            item = stripped[2:].strip().strip("'\"")
            if current_list_key and current_section:
                out[current_section].setdefault(current_list_key, []).append(item)
            continue
        if raw.startswith("  ") and current_section:
            line = stripped.rstrip(":")
            if ":" in line:
                k, _, v = line.partition(":")
                k = k.strip()
                v = v.strip()
                if v == "" or v.lower() in ("null", "~"):
                    current_list_key = k
                    out[current_section].setdefault(k, [])
                elif v.startswith("[") and v.endswith("]"):
                    inner = v[1:-1]
                    items = [s.strip().strip("'\"") for s in inner.split(",") if s.strip()]
                    out[current_section][k] = items
                    current_list_key = None
                else:
                    if v.lower() in ("true", "false"):
                        out[current_section][k] = v.lower() == "true"
                    else:
                        try:
                            out[current_section][k] = int(v)
                        except ValueError:
                            out[current_section][k] = v.strip("'\"")
                    current_list_key = None
    return out


def _json_safe_load(path: Path) -> dict:
    """Load archetype_model_config.json; stdlib json is always available."""
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh) or {}


# ---------------------------------------------------------------------------
# Archetype registry
# ---------------------------------------------------------------------------

class ArchetypeSpec:
    """One archetype's merged configuration (model from JSON + schema from YAML).

    Skill include/exclude are NOT stored here — they are decided per-call by
    the orchestrator. Briefing/identity prose lives in SOUL_<name>.md; this
    spec only holds the mechanical routing config.
    """

    __slots__ = (
        "name",
        # From archetype_model_config.json
        "provider",
        "model",
        "fallback_chain",
        # From archetypes.yaml
        "default_toolsets",
        "soul_path",
        "output_schema",
        "max_iterations",
    )

    def __init__(
        self,
        name: str,
        model_cfg: dict,      # from archetype_model_config.json
        schema_cfg: dict,     # from archetypes.yaml
        defaults: dict,       # from archetypes.yaml -> defaults
    ):
        self.name = name
        # Model/provider from JSON — this is the rotatable layer
        self.provider: str = model_cfg.get("provider", "")
        self.model: str = model_cfg.get("model", "")
        self.fallback_chain: List[Dict[str, str]] = model_cfg.get("fallback_chain", []) or []
        # Schema from YAML — mechanical config only (identity prose is in SOUL_*.md)
        self.default_toolsets: List[str] = schema_cfg.get(
            "default_toolsets", defaults.get("default_toolsets", ["terminal", "file", "web"])
        )
        soul_rel = schema_cfg.get("soul", f"SOUL_{name}.md")
        self.soul_path: Path = PLUGIN_DIR / soul_rel
        self.output_schema: Optional[dict] = schema_cfg.get(
            "output_schema", defaults.get("output_schema")
        )
        self.max_iterations: int = int(
            schema_cfg.get("max_iterations", defaults.get("max_iterations", 50))
        )

    def __repr__(self) -> str:
        return (
            f"ArchetypeSpec(name={self.name!r}, provider={self.provider!r}, "
            f"model={self.model!r}, toolsets={self.default_toolsets}, "
            f"max_iter={self.max_iterations})"
        )


# Cached registry — keyed by (model_config_mtime, schema_mtime) so changes
# to either file invalidate the cache automatically on next call. This is
# what makes "edit JSON, takes effect immediately" actually work.
_ARCHETYPES: Dict[str, ArchetypeSpec] = {}
_DEFAULTS: dict = {}
_DEFAULT_DISABLED_SKILLS: List[str] = []
_CACHE_KEY: Optional[tuple] = None


def _cache_key() -> tuple:
    """Return a cache key based on the mtime of the two config files.

    Reload is cheap (tiny files, ~200 lines each), so we just always
    check mtimes and rebuild if either file changed since last load.
    """
    try:
        model_mtime = MODEL_CONFIG_FILE.stat().st_mtime if MODEL_CONFIG_FILE.exists() else 0
        schema_mtime = SCHEMA_FILE.stat().st_mtime if SCHEMA_FILE.exists() else 0
        return (model_mtime, schema_mtime)
    except Exception:
        return (0, 0)


def load_archetypes(force_reload: bool = False) -> Dict[str, ArchetypeSpec]:
    """Load both config files and merge into ArchetypeSpec dict.

    Auto-reloads when either file's mtime changes — no plugin restart
    needed. Pass `force_reload=True` to skip the cache check.
    """
    global _ARCHETYPES, _DEFAULTS, _DEFAULT_DISABLED_SKILLS, _CACHE_KEY

    current_key = _cache_key()
    if not force_reload and _CACHE_KEY == current_key and _ARCHETYPES:
        return _ARCHETYPES

    # Validate both files exist
    missing = []
    if not MODEL_CONFIG_FILE.exists():
        missing.append(str(MODEL_CONFIG_FILE))
    if not SCHEMA_FILE.exists():
        missing.append(str(SCHEMA_FILE))
    if missing:
        raise FileNotFoundError(
            f"Archetype config files missing: {missing}. "
            f"Both archetype_model_config.json AND archetypes.yaml are required."
        )

    # Load JSON (model/provider)
    model_raw = _json_safe_load(MODEL_CONFIG_FILE)
    model_archetypes = model_raw.get("archetypes", {}) or {}

    # Load YAML (schema)
    schema_raw = _yaml_safe_load(SCHEMA_FILE)
    _DEFAULTS = schema_raw.get("defaults", {}) or {}
    _DEFAULT_DISABLED_SKILLS = schema_raw.get("default_disabled_skills", []) or []
    schema_archetypes = schema_raw.get("archetypes", {}) or {}

    # Merge — the union of archetype names from both files
    all_names = sorted(set(model_archetypes) | set(schema_archetypes))
    merged: Dict[str, ArchetypeSpec] = {}
    warnings: List[str] = []

    for name in all_names:
        model_cfg = model_archetypes.get(name, {})
        schema_cfg = schema_archetypes.get(name, {})
        if not model_cfg:
            warnings.append(f"archetype '{name}' has schema but no model config (using empty provider/model)")
        if not schema_cfg:
            warnings.append(f"archetype '{name}' has model config but no schema (will fall back to defaults)")
        merged[name] = ArchetypeSpec(name, model_cfg, schema_cfg, _DEFAULTS)

    _ARCHETYPES = merged
    _CACHE_KEY = current_key

    if warnings:
        for w in warnings:
            logger.warning(w)
    logger.debug(
        "Loaded %d archetypes (model file mtime=%s, schema file mtime=%s), "
        "%d default-disabled skills: %s",
        len(_ARCHETYPES), current_key[0], current_key[1],
        len(_DEFAULT_DISABLED_SKILLS), _DEFAULT_DISABLED_SKILLS,
    )
    return _ARCHETYPES


def reload_archetypes() -> Dict[str, ArchetypeSpec]:
    """Force a fresh load of both config files. Useful for tests."""
    return load_archetypes(force_reload=True)


def get_archetype(name: str) -> ArchetypeSpec:
    """Return one archetype by name; raises KeyError with a helpful message."""
    specs = load_archetypes()
    if name not in specs:
        raise KeyError(
            f"Unknown archetype '{name}'. Available: {list(specs)}. "
            f"To add a new archetype: edit BOTH archetype_model_config.json "
            f"(add model/provider) and archetypes.yaml (add schema), then "
            f"restart the gateway so the plugin re-discovers it."
        )
    return specs[name]


def list_archetypes() -> List[str]:
    return list(load_archetypes().keys())


def get_default_disabled_skills() -> List[str]:
    """Return the global list of skill globs disabled by default.

    These are skills excluded from EVERY archetype unless the orchestrator
    explicitly opts back in via `skill_include_override` at call time.

    Lives at the top of archetypes.yaml (`default_disabled_skills`). Edit
    the YAML to add/remove entries — takes effect on next delegation call.
    """
    load_archetypes()  # ensure cache is fresh
    return list(_DEFAULT_DISABLED_SKILLS)


def describe_config_split() -> Dict[str, str]:
    """Diagnostic helper: report which file holds what."""
    return {
        "model_config": str(MODEL_CONFIG_FILE),
        "schema_config": str(SCHEMA_FILE),
        "split": (
            "archetype_model_config.json holds model/provider ONLY "
            "(edit this to retarget). archetypes.yaml holds schema ONLY "
            "(edit this to evolve persona/skills/contract)."
        ),
    }


# ---------------------------------------------------------------------------
# Skill isolation
# ---------------------------------------------------------------------------

def _resolve_skill_roots() -> List[Path]:
    """Return skill search roots in priority order.

    Honours $HERMES_SKILL_ROOTS (colon-separated) when set — useful for tests
    and for forcing isolation. Otherwise falls back to the standard locations
    the native delegate_task would also search.
    """
    env = os.getenv(_HERMES_SKILL_ROOTS_ENV, "").strip()
    if env:
        return [Path(p).expanduser() for p in env.split(":") if p.strip()]

    roots: List[Path] = []
    home = Path(os.path.expanduser("~"))
    candidates = [
        home / "Desktop" / "OMCA-GODMODE" / "skills",
        home / ".hermes" / "skills",
    ]
    desktop = home / "Desktop"
    if desktop.is_dir():
        for ws in desktop.glob("AGENT-*"):
            sp = ws / ".opencode" / "skills"
            if sp.is_dir():
                candidates.append(sp)
    for c in candidates:
        if c.is_dir():
            roots.append(c)
    return roots


def _list_all_skills(roots: List[Path]) -> List[str]:
    """Enumerate every skill name across the given roots.

    A 'skill' is a directory containing SKILL.md. The name is the directory
    name. Duplicates across roots are de-duplicated (first root wins).
    """
    seen: Dict[str, None] = {}
    for root in roots:
        if not root.is_dir():
            continue
        for entry in root.iterdir():
            if entry.is_dir() and (entry / "SKILL.md").is_file():
                seen.setdefault(entry.name, None)
    return list(seen)


def _match_skill_glob(skill_name: str, pattern: str) -> bool:
    """Match a skill name against a fnmatch glob pattern.

    Supports two pattern styles:
      1. Prefix-match: 'honcho-*' matches anything containing 'honcho-' (after
         stripping known prefixes like 'knows_'). Useful for catching
         'knows_honcho-*', 'subflows_honcho-*', etc.
      2. fnmatch: 'knows_*' matches anything starting with 'knows_' exactly.
         'knows_leverage-*' matches anything starting with 'knows_leverage-'.

    The skill name is stripped of common prefixes before pattern 1 is tried.
    """
    # Try exact fnmatch first (catches 'knows_*', 'knows_leverage-*')
    if fnmatch.fnmatchcase(skill_name, pattern):
        return True
    # Then try prefix-stripped match (catches 'honcho-*' against 'knows_honcho-*')
    for prefix in ("knows_", "nodes_", "subflows_", "omca-", "omca_"):
        if skill_name.startswith(prefix):
            stripped = skill_name[len(prefix):]
            if fnmatch.fnmatchcase(stripped, pattern):
                return True
            break
    return False


def resolve_skill_filter(
    include: List[str], exclude: List[str], roots: Optional[List[Path]] = None
) -> List[str]:
    """Resolve include/exclude glob patterns against the actual skill catalog."""
    if roots is None:
        roots = _resolve_skill_roots()
    all_skills = _list_all_skills(roots)
    if not all_skills:
        return []

    if include and all(p == "*" for p in include):
        candidates = set(all_skills)
    else:
        candidates = set()
        for skill in all_skills:
            if any(_match_skill_glob(skill, pat) for pat in include):
                candidates.add(skill)

    for skill in all_skills:
        if any(_match_skill_glob(skill, pat) for pat in exclude):
            candidates.discard(skill)

    return sorted(candidates)


def resolve_orchestrator_skill_filter(
    skill_include_override: Optional[List[str]],
    skill_exclude_override: Optional[List[str]],
    roots: Optional[List[Path]] = None,
) -> List[str]:
    """Apply the orchestrator's per-call skill decisions.

    Resolution order (orchestrator decides; config file only adds a default-disable safety net):
      1. Start with the FULL skill catalog.
      2. ALWAYS subtract `default_disabled_skills` from archetypes.yaml.
         This is the safety net — context-pollution-prone skills are off by default.
      3. If orchestrator passed `skill_include_override`:
         - WHITELIST MODE: only those skills remain. Orchestrator can opt back in
           to a default-disabled skill by including its name (e.g. include
           "knows_honcho-best-practice" re-enables it).
      4. Else if orchestrator passed `skill_exclude_override`:
         - BLACKLIST MODE: subtract those too on top of the default-disabled list.
      5. Else: full catalog minus default_disabled_skills.

    Returns the sorted list of skill names the subagent should see.
    """
    if roots is None:
        roots = _resolve_skill_roots()
    all_skills = set(_list_all_skills(roots))
    if not all_skills:
        return []

    # Step 2: always subtract default-disabled
    disabled = set(get_default_disabled_skills())
    candidates = all_skills - {s for s in all_skills if any(_match_skill_glob(s, p) for p in disabled)}

    # Step 3: orchestrator passed an explicit include list -> whitelist mode
    if skill_include_override:
        include_set = {s for s in all_skills if any(_match_skill_glob(s, p) for p in skill_include_override)}
        # The orchestrator's explicit include RE-ENABLES disabled skills for this call.
        # This is the documented "opt back in" path: passing a skill name explicitly
        # in skill_include_override overrides the default_disabled safety net for that name.
        candidates = include_set
    # Step 4: orchestrator passed an explicit exclude list -> blacklist mode
    elif skill_exclude_override:
        candidates -= {s for s in candidates if any(_match_skill_glob(s, p) for p in skill_exclude_override)}

    # Step 5: neither — full catalog minus default-disabled (already handled above)

    return sorted(candidates)


# ---------------------------------------------------------------------------
# Briefing assembly
# ---------------------------------------------------------------------------

def _read_soul(spec: ArchetypeSpec) -> str:
    """Read the archetype's SOUL.md file. Empty string if missing."""
    if not spec.soul_path.is_file():
        logger.warning("SOUL file missing for archetype %s: %s", spec.name, spec.soul_path)
        return ""
    return spec.soul_path.read_text(encoding="utf-8").strip()


def _assemble_brief(
    spec: ArchetypeSpec,
    goal: str,
    context: Optional[str],
    skill_filter: List[str],
    output_schema_override: Optional[dict] = None,
    include_model_block: bool = True,
) -> str:
    """Compose the full prompt the subagent will see as its goal+context.

    Structure (each section is separated by '---'):
      <SOUL — persistent identity from SOUL_<name>.md>
      <model — provider/model from JSON (optional, helps subagent self-identify)>
      <goal — from orchestrator>
      <context — from orchestrator (optional)>
      <skill_filter — list of skills visible to this subagent>
      <output_schema — if specified, embedded as a JSON contract>

    Note: briefing_intro has been merged into SOUL_<name>.md to eliminate
    duplication. The SOUL file is the single source of identity prose.
    """
    soul = _read_soul(spec)
    parts: List[str] = []

    if soul:
        parts.append(soul)

    if include_model_block and spec.model:
        parts.append("---")
        parts.append("## Active Model")
        parts.append(
            f"You are running on **{spec.provider} / {spec.model}**. "
            f"This is the configured model for the {spec.name} archetype."
        )

    parts.append("---")
    parts.append("## Goal (from orchestrator)")
    parts.append(goal.strip() if goal else "(no goal provided)")

    if context:
        parts.append("---")
        parts.append("## Context (from orchestrator)")
        parts.append(context.strip())

    parts.append("---")
    parts.append("## Available Skills")
    if skill_filter:
        parts.append(
            "You may invoke skills from this whitelist only:\n"
            + "\n".join(f"- `{s}`" for s in skill_filter)
        )
    else:
        parts.append(
            "No skill whitelist applied — all skills from the standard "
            "catalog (minus default_disabled_skills) are available to you."
        )

    schema = output_schema_override if output_schema_override is not None else spec.output_schema
    if schema is not None:
        parts.append("---")
        parts.append("## Required Output Schema")
        parts.append(
            "Your final response MUST be a single valid JSON object matching "
            "this schema. No prose, no markdown fences, no preamble outside the JSON.\n"
            f"```json\n{json.dumps(schema, indent=2, ensure_ascii=False)}\n```"
        )

    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Native delegate_task import (lazy — only when a tool is actually called)
# ---------------------------------------------------------------------------

_NATIVE_DELEGATE_TASK: Optional[Any] = None
_NATIVE_IMPORT_ERROR: Optional[Exception] = None


def _get_native_delegate_task():
    """Lazy-import the native delegate_task from hermes_agent.tools."""
    global _NATIVE_DELEGATE_TASK, _NATIVE_IMPORT_ERROR
    if _NATIVE_DELEGATE_TASK is not None:
        return _NATIVE_DELEGATE_TASK
    if _NATIVE_IMPORT_ERROR is not None:
        raise _NATIVE_IMPORT_ERROR

    try:
        try:
            from tools.delegate_tool import delegate_task  # type: ignore
        except ImportError:
            from hermes_agent.tools.delegate_tool import delegate_task  # type: ignore
        _NATIVE_DELEGATE_TASK = delegate_task
        return _NATIVE_DELEGATE_TASK
    except ImportError as exc:
        _NATIVE_IMPORT_ERROR = exc
        logger.error("Cannot import native delegate_task: %s", exc)
        raise


# ---------------------------------------------------------------------------
# Per-call model override (rare escape hatch)
# ---------------------------------------------------------------------------

def apply_model_override(
    spec: ArchetypeSpec, override: Optional[Dict[str, str]]
) -> ArchetypeSpec:
    """Return a copy of `spec` with model/provider overridden for one call.

    `override` is a dict like {"provider": "openrouter", "model": "gpt-5.6"}
    or None. Returns the original spec when override is None or empty.

    Used by the per-call `model_override` parameter on the tool handlers.
    Rare — the canonical path is editing archetype_model_config.json.
    """
    if not override:
        return spec
    if not (override.get("provider") and override.get("model")):
        logger.warning("model_override missing provider or model: %r", override)
        return spec
    # Cheap copy — just construct a new ArchetypeSpec with merged config
    merged_model_cfg = {
        "provider": override["provider"],
        "model": override["model"],
        "fallback_chain": spec.fallback_chain,
    }
    schema_cfg = {
        "default_toolsets": spec.default_toolsets,
        "soul": spec.soul_path.name,
        "output_schema": spec.output_schema,
        "max_iterations": spec.max_iterations,
    }
    logger.info(
        "Per-call model override for archetype %s: %s/%s -> %s/%s",
        spec.name, spec.provider, spec.model, override["provider"], override["model"],
    )
    return ArchetypeSpec(spec.name, merged_model_cfg, schema_cfg, {})


# ---------------------------------------------------------------------------
# Tool handlers (4 archetypes — one per delegated tool)
# ---------------------------------------------------------------------------

def _make_handler(archetype_name: str):
    """Build a closure that handles delegate_task_<archetype> calls.

    Mirrors the native delegate_task signature (goal, context, tasks,
    max_iterations, role, background, parent_agent) so the agent's
    training-time expectations match.

    Skill include/exclude resolution (the orchestrator decides per call):
      - Orchestrator MUST pass either skill_include OR skill_exclude.
        If neither is passed, the subagent gets ALL skills EXCEPT the
        global default_disabled_skills list from archetypes.yaml.
      - skill_include_override: whitelist mode. Orchestrator picks the
        exact skills. default_disabled_skills is STILL applied (orchestrator
        must explicitly opt back in by including a disabled skill).
      - skill_exclude_override: blacklist mode. Orchestrator picks what
        to exclude on top of default_disabled_skills.
      - skill_include=None and skill_exclude=None: full catalog minus
        default_disabled_skills.

    Plugin extras: output_schema_override, model_override.
    """
    def handler(
        goal: Optional[str] = None,
        context: Optional[str] = None,
        tasks: Optional[List[Dict[str, Any]]] = None,
        max_iterations: Optional[int] = None,
        role: Optional[str] = None,
        background: Optional[bool] = None,
        parent_agent: Any = None,
        # Plugin-specific extras (NOT in native schema — passed via context):
        output_schema_override: Optional[dict] = None,
        skill_include_override: Optional[List[str]] = None,
        skill_exclude_override: Optional[List[str]] = None,
        model_override: Optional[Dict[str, str]] = None,
        **extra: Any,
    ) -> str:
        """Delegate to the named archetype. Same shape as native delegate_task."""
        spec = get_archetype(archetype_name)

        # Apply per-call model override (rare escape hatch)
        if model_override:
            spec = apply_model_override(spec, model_override)

        # Skill resolution — orchestrator decides per call
        skill_filter = resolve_orchestrator_skill_filter(
            skill_include_override=skill_include_override,
            skill_exclude_override=skill_exclude_override,
        )

        # Iteration budget — archetype default, override if caller specifies
        budget = max_iterations if max_iterations is not None else spec.max_iterations

        # Bypass model/provider resolution: archetype_delegate() sets
        # delegation.model + delegation.provider in ~/.hermes/config.yaml
        # before calling native. Native sees our values via its mtime-based
        # config cache (auto-invalidates on file change).
        from archetype_delegate import archetype_delegate as _arch_delegate

        if tasks:
            # Batch mode: apply the archetype uniformly to every task.
            # Each task runs as its own child via separate calls (no native
            # batch — we get per-call config snapshot/restore for free).
            results = []
            for t in tasks:
                t_goal = t.get("goal", "")
                t_context = t.get("context", "")
                t_role = t.get("role", role) or "leaf"
                t_max = t.get("max_iterations") or budget
                brief = _assemble_brief(
                    spec, t_goal, t_context, skill_filter, output_schema_override
                )
                r = _arch_delegate(
                    spec=spec,
                    brief=brief,
                    context=t_context,
                    toolsets=spec.default_toolsets,
                    parent_agent=parent_agent,
                    role=t_role,
                    background=bool(background),
                )
                results.append(r)
            return results

        # Single task
        brief = _assemble_brief(
            spec, goal or "", context, skill_filter, output_schema_override
        )
        return _arch_delegate(
            spec=spec,
            brief=brief,
            context=context,
            toolsets=spec.default_toolsets,
            parent_agent=parent_agent,
            role=role or "leaf",
            background=bool(background),
        )

    handler.__name__ = f"_delegate_task_{archetype_name}"
    handler.__qualname__ = handler.__name__
    handler.__doc__ = (
        f"Delegate to the {archetype_name} archetype. Pre-fills model (from "
        f"archetype_model_config.json) + SOUL identity (from SOUL_{archetype_name}.md) "
        f"+ skill whitelist (computed from per-call skill_include_override / "
        f"skill_exclude_override + the global default_disabled_skills from "
        f"archetypes.yaml). Same shape as native delegate_task plus plugin "
        f"extras: output_schema_override, skill_include_override, "
        f"skill_exclude_override, model_override."
    )
    return handler


# ---------------------------------------------------------------------------
# Tool schemas (one per archetype). Mirrors the native delegate_task schema
# with plugin-specific extras appended.
# ---------------------------------------------------------------------------

_BASE_PARAMETERS: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "goal": {
            "type": "string",
            "description": (
                "The task to delegate. Concatenated with the archetype's "
                "SOUL (from SOUL_<name>.md) before being passed to the subagent."
            ),
        },
        "context": {
            "type": "string",
            "description": (
                "Orchestrator-provided scaffolding passed through to the "
                "subagent. Injected after the SOUL and before the "
                "skill-filter block in the composed prompt."
            ),
        },
        "tasks": {
            "type": "array",
            "description": (
                "Batch mode (parallel). Same shape as native delegate_task; "
                "every task in the batch is routed to the SAME archetype."
            ),
            "items": {
                "type": "object",
                "properties": {
                    "goal":       {"type": "string"},
                    "context":    {"type": "string"},
                    "role":       {"type": "string", "enum": ["leaf", "orchestrator"]},
                    "max_iterations": {"type": "integer", "minimum": 1, "maximum": 200},
                },
            },
        },
        "max_iterations": {
            "type": "integer",
            "minimum": 1,
            "maximum": 200,
            "description": "Override the archetype's default iteration budget.",
        },
        "role": {
            "type": "string",
            "enum": ["leaf", "orchestrator"],
            "description": "Whether the subagent can further delegate (orchestrator) or not (leaf).",
        },
        "background": {
            "type": "boolean",
            "description": "Run as a background/async delegation (parent does not block).",
        },
        "output_schema_override": {
            "type": "object",
            "description": (
                "Per-call JSON schema override. Useful for Speedster (IV) when "
                "the orchestrator wants a tighter shape than archetypes.yaml "
                "declares. Merged into the briefing as a JSON contract."
            ),
            "additionalProperties": True,
        },
        "skill_include_override": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "WHITELIST MODE: orchestrator picks the exact skills the subagent sees. "
                "Same fnmatch syntax as archetypes.yaml: 'knows_*', 'knows_leverage-*', "
                "'nodes_*', 'subflows_*', 'omca-*', or '*' for everything. "
                "When set, skill_exclude_override is IGNORED. Skills in "
                "default_disabled_skills remain disabled UNLESS the orchestrator "
                "explicitly includes them by name (e.g. include 'knows_honcho-best-practice' "
                "to re-enable it for this call)."
            ),
        },
        "skill_exclude_override": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "BLACKLIST MODE: orchestrator picks what to exclude from the "
                "default catalog ON TOP OF default_disabled_skills. Only applies when "
                "skill_include_override is not set. Use when the orchestrator wants "
                "to trim a known-bad skill for one task without re-enabling "
                "default-disabled ones."
            ),
        },
        "model_override": {
            "type": "object",
            "description": (
                "RARE ESCAPE HATCH: per-call model/provider override. Canonical "
                "path is editing archetype_model_config.json. Use this only when "
                "a one-off experiment needs a different model without editing the "
                "config. Format: {\"provider\": \"openrouter\", \"model\": \"openai/gpt-5.6\"}."
            ),
            "properties": {
                "provider": {"type": "string"},
                "model": {"type": "string"},
            },
            "required": ["provider", "model"],
        },
    },
    "required": [],
}


def _build_schema(archetype_name: str) -> dict:
    spec = get_archetype(archetype_name)
    desc = (
        f"Delegate to the **{spec.name}** archetype "
        f"(provider={spec.provider or 'inherit'}, model={spec.model or 'inherit'}, "
        f"default_toolsets={spec.default_toolsets}, "
        f"max_iterations={spec.max_iterations}).\n\n"
        f"Model + provider come from `archetype_model_config.json`. Toolsets, "
        f"SOUL, briefing, output_schema come from `archetypes.yaml`. "
        f"Skills are decided PER CALL by the orchestrator (skill_include_override "
        f"/ skill_exclude_override), with the global `default_disabled_skills` "
        f"list from archetypes.yaml applied as a safety net.\n\n"
        f"**Native delegate_task signature preserved** — `goal`, `context`, "
        f"`tasks`, `max_iterations`, `role`, `background`, `parent_agent` "
        f"all pass through to the native tool. Plugin extras: "
        f"`output_schema_override`, `skill_include_override`, "
        f"`skill_exclude_override`, `model_override`."
    )
    return {
        "name": f"delegate_task_{archetype_name}",
        "description": desc,
        "parameters": _BASE_PARAMETERS,
    }


# ---------------------------------------------------------------------------
# Plugin registration entry point (called by Hermes's PluginManager)
# ---------------------------------------------------------------------------

def _build_all() -> Dict[str, Any]:
    """Return {tool_name: (schema, handler)} for every archetype."""
    load_archetypes()
    out: Dict[str, Any] = {}
    for name in list_archetypes():
        tool_name = f"delegate_task_{name}"
        out[tool_name] = (_build_schema(name), _make_handler(name))
    return out


def register(ctx) -> None:
    """Hermes plugin entry point. Called once when the plugin loads.

    Registers one tool per archetype under its own tool name. Each tool
    inherits the 'terminal' toolset by default (which is what users
    typically have enabled); the per-archetype default_toolsets in
    archetypes.yaml is *passed through* to the native delegate_task but
    doesn't change this plugin tool's toolset registration — that's
    controlled by the user's enabled_toolsets config.
    """
    for tool_name, (schema, handler) in _build_all().items():
        ctx.register_tool(
            name=tool_name,
            toolset="terminal",
            schema=schema,
            handler=handler,
            description=schema["description"],
            emoji="🎭",
        )
        logger.info("Archetype Router registered tool: %s", tool_name)