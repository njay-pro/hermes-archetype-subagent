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
from typing import Any, Dict, List, Optional, Tuple

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

    v0.3.1: also reads `skills.external_dirs` from every
    `~/.hermes/profiles/*/config.yaml` so the plugin honours Hermes's
    official skill-discovery extension point. Previously the plugin only
    walked 3 hard-coded paths; skills placed in a non-standard
    external_dirs were silently invisible. See TODO.md v0.3.1 bug #3.
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

    # Read external_dirs from every profile's config.yaml.
    # Use minimal YAML parsing here (no PyYAML needed for a single
    # top-level key whose value is a list of strings).
    prof_root = home / ".hermes" / "profiles"
    if prof_root.is_dir():
        for cfg_path in prof_root.glob("*/config.yaml"):
            try:
                cfg_text = cfg_path.read_text(encoding="utf-8")
                ext_dirs = _extract_external_dirs(cfg_text)
            except Exception as exc:
                logger.debug("Could not read %s for external_dirs: %s", cfg_path, exc)
                continue
            for ext in ext_dirs:
                p = Path(ext).expanduser()
                if p.is_dir():
                    candidates.append(p)

    for c in candidates:
        if c.is_dir():
            roots.append(c)
    return roots


def _extract_external_dirs(yaml_text: str) -> List[str]:
    """Minimal extractor for `skills.external_dirs: [a, b, c]` blocks.

    Only handles the exact shape we expect:
      skills:
        external_dirs:
          - /path/one
          - /path/two
    Returns an empty list on any parse failure — never raises.
    """
    out: List[str] = []
    lines = yaml_text.splitlines()
    in_skills = False
    in_external = False
    for raw in lines:
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        # Detect entering the skills: block
        if not in_skills:
            if stripped == "skills:" or stripped.startswith("skills:"):
                in_skills = True
            continue
        # Inside skills: — look for external_dirs:
        if not in_external:
            if "external_dirs" in stripped:
                # Two shapes: `external_dirs:` (list follows on next lines)
                # or `external_dirs: [a, b]` (inline list).
                if stripped.endswith(":"):
                    in_external = True
                    # Same-line list possible: external_dirs: [a, b]
                    if "[" in stripped and "]" in stripped:
                        inner = stripped.split("[", 1)[1].rsplit("]", 1)[0]
                        for item in inner.split(","):
                            item = item.strip().strip("'\"")
                            if item:
                                out.append(item)
                        in_external = False
                elif "[" in stripped and "]" in stripped and ":" in stripped.split("[", 1)[0]:
                    # `external_dirs: [a, b]` without trailing colon after the bracket
                    inner = stripped.split("[", 1)[1].rsplit("]", 1)[0]
                    for item in inner.split(","):
                        item = item.strip().strip("'\"")
                        if item:
                            out.append(item)
            continue
        # Inside external_dirs: — read list items
        if stripped.startswith("- "):
            item = stripped[2:].strip().strip("'\"")
            if item:
                out.append(item)
        elif stripped.endswith(":"):
            # A different key under skills: — stop reading external_dirs
            in_external = False
    return out


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


# v0.3.3 SG3: the L1 (code-level) baseline for the skill universe.
# Default = all OMCA utility skills (knows_*, nodes_*, subflows_*, omca-*).
# Matches the convention used by the omca-ebook profile — see the
# memory entry "njaypro is using the omca-ebook profile to read all
# skills matching omca-*, omca_*, knows_*, nodes_*, subflows_*".
# Per-archetype config and per-call orchestrator override still narrow
# further on top of this baseline.
DEFAULT_OMCA_UTILS_GLOBS: List[str] = [
    "knows_*",
    "nodes_*",
    "subflows_*",
    "omca-*",
    "omca_*",
]


def resolve_orchestrator_skill_filter(
    skill_include_override: Optional[List[str]],
    skill_exclude_override: Optional[List[str]],
    roots: Optional[List[Path]] = None,
) -> List[str]:
    """Apply the orchestrator's per-call skill decisions.

    3-LAYER SKILL RESOLUTION (v0.3.3 SG3):
      L1 (code-level baseline): start with the OMCA utils catalog
          (knows_*, nodes_*, subflows_*, omca-*). Defined in
          DEFAULT_OMCA_UTILS_GLOBS. This is the default for ALL archetype
          delegations and replaces the previous "load everything" baseline.
      L2 (config safety net): ALWAYS subtract `default_disabled_skills`
          from archetypes.yaml. Currently `honcho-*` is disabled by default
          because Honcho memory helpers are context-pollution-prone in
          narrow subagent tasks. (Config file lives in archetypes.yaml.)
      L3 (orchestrator override):
        - skill_include_override: WHITELIST MODE. Only matching skills
          remain. The explicit include RE-ENABLES disabled skills for
          this call (documented "opt back in" path).
        - skill_exclude_override: BLACKLIST MODE. Subtract matching skills
          on top of L1+L2.

    Resolution order: L1 → L2 → L3. Each layer narrows the previous.

    Returns the sorted list of skill names the subagent should see.
    """
    if roots is None:
        roots = _resolve_skill_roots()
    all_skills = set(_list_all_skills(roots))
    if not all_skills:
        return []

    # Step 1 (L1): start with OMCA utils, not the full catalog.
    # This is the default for archetype-based subagents.
    candidates = {
        s for s in all_skills
        if any(_match_skill_glob(s, glob) for glob in DEFAULT_OMCA_UTILS_GLOBS)
    }

    # Step 2 (L2): always subtract config-level default-disabled.
    disabled = set(get_default_disabled_skills())
    candidates -= {
        s for s in candidates if any(_match_skill_glob(s, p) for p in disabled)
    }

    # Step 3 (L3a): orchestrator passed an explicit include list -> whitelist mode
    if skill_include_override:
        include_set = {
            s for s in all_skills
            if any(_match_skill_glob(s, p) for p in skill_include_override)
        }
        # The orchestrator's explicit include RE-ENABLES disabled skills for this call.
        # This is the documented "opt back in" path: passing a skill name explicitly
        # in skill_include_override overrides the default_disabled safety net for that name.
        candidates = include_set
    # Step 4 (L3b): orchestrator passed an explicit exclude list -> blacklist mode
    elif skill_exclude_override:
        candidates -= {
            s for s in candidates
            if any(_match_skill_glob(s, p) for p in skill_exclude_override)
        }

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
    preload_files: Optional[List[str]] = None,
) -> str:
    """Compose the full prompt the subagent will see as its goal+context.

    Structure (each section is separated by '---'):
      <PRIORITY header — declares this brief overrides any default role framing>
      <SOUL — persistent identity from SOUL_<name>.md>
      <model — provider/model from JSON (optional, helps subagent self-identify)>
      <goal — from orchestrator>
      <context — from orchestrator (optional)>
      <preloaded_files — content of preload_files slot (optional)>
      <skill_filter — list of skills visible to this subagent>
      <output_schema — if specified, embedded as a JSON contract>

    Note: briefing_intro has been merged into SOUL_<name>.md to eliminate
    duplication. The SOUL file is the single source of identity prose.

    v0.3.3 SG2: a PRIORITY header is prepended to the brief. This tells the
    subagent that everything below the header supersedes any default role
    framing the runtime may have added (e.g. AIAgent's built-in
    "you are a helpful AI..." prefix). The SOUL section is the canonical
    role, not the runtime's fallback.
    """
    soul = _read_soul(spec)
    parts: List[str] = []

    # v0.3.3 SG2: PRIORITY header. Prepended to everything else so the
    # model attends to it first. Explains that the SOUL below is the
    # canonical role and any default "helpful AI assistant" framing is
    # a runtime artifact to be ignored.
    parts.append(
        "## PRIORITY\n"
        "The following brief is the canonical instructions for this subagent. "
        "If any default role framing from the runtime contradicts what is "
        "below (for example, a generic 'helpful AI assistant' preamble), "
        "follow the role, audience, and behavior defined in the SOUL section "
        "below — not the runtime default. The SOUL is authoritative."
    )

    if soul:
        parts.append(soul)

    if include_model_block and spec.model:
        parts.append("---")
        parts.append("## Active Model")
        parts.append(
            f"You are running on **{spec.provider} / {spec.model}**. "
            f"This is the configured model for the {spec.name} archetype."
        )

    # Defensive coercion: MCP tool layers sometimes serialize string
    # params as dicts (e.g. {"context": "..."}). Normalize to str before
    # .strip() so the briefing never crashes on a non-string input.
    def _coerce_str(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            # Common case: {"context": "..."} or {"goal": "..."} — extract
            # the first string value we find.
            for v in value.values():
                if isinstance(v, str):
                    return v
            return str(value)
        return str(value)

    goal_str = _coerce_str(goal)
    context_str = _coerce_str(context)

    parts.append("---")
    parts.append("## Goal (from orchestrator)")
    parts.append(goal_str.strip() if goal_str else "(no goal provided)")

    if context_str:
        parts.append("---")
        parts.append("## Context (from orchestrator)")
        parts.append(context_str.strip())

    # v0.3.3 SG4: Preloaded Files section. Reads each file from disk and
    # inlines its content into the brief. Absolute paths only. 100KB cap
    # per file, 1MB cap total. Errors are surfaced as "(load failed: ...)"
    # text so the subagent knows the file was supposed to be there.
    if preload_files:
        # Reset per-delegation preload budget at the START of this
        # section (once per _assemble_brief call). Subsequent file
        # reads accumulate against this budget.
        _read_preload_file._total_bytes = 0  # type: ignore[attr-defined]
        parts.append("---")
        parts.append("## Preloaded Files")
        parts.append(
            "The orchestrator preloaded these files for you. Their content "
            "is inlined below. You can use this as context, reference, or raw "
            "data — depending on the goal above."
        )
        for path_str in preload_files:
            content = _read_preload_file(path_str)
            file_name = path_str.split("/")[-1] if "/" in path_str else path_str
            parts.append(f"### `{file_name}`")
            parts.append(content)

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


# v0.3.3 SG4: Preload file caps. Tuned conservatively — a single 100KB file is
# already 25K-50K tokens of context once it goes through the model.
# The 1MB total cap means you can pre-load ~10 reasonable files before
# the brief itself starts dominating the context window.
_PRELOAD_MAX_FILE_BYTES = 100 * 1024      # 100 KB per file
_PRELOAD_MAX_TOTAL_BYTES = 1024 * 1024   # 1 MB total per delegation


def _read_preload_file(path_str: str) -> str:
    """Read a preload file and return its content as a string.

    v0.3.3 SG4: best-effort. Resolves paths intelligently:
      1. Absolute path: used as-is.
      2. Relative path: tries relative to current working directory (Path.cwd() / path).
      3. Fallback: tries relative to the home directory if ~ is used.

    Caps: 100KB per file, 1MB total per delegation. Excess content is
    truncated with a `[... truncated at N bytes ...]` marker so the
    subagent knows there's more if it asks.

    The per-delegation total byte counter is reset by the caller
    (once per _assemble_brief call) so budgets don't leak across briefs.
    """
    try:
        # Resolve the path intelligently
        p = Path(path_str).expanduser()
        if not p.is_absolute():
            # Try relative to the current working directory first
            cwd_path = Path.cwd() / path_str
            if cwd_path.is_file():
                p = cwd_path

        if not p.is_file():
            return f"(load failed: file not found: {path_str} [attempted: {p}])"
        size = p.stat().st_size
        if size > _PRELOAD_MAX_FILE_BYTES:
            with p.open("r", encoding="utf-8", errors="replace") as fh:
                content = fh.read(_PRELOAD_MAX_FILE_BYTES)
            content += (
                f"\n\n[... truncated at "
                f"{_PRELOAD_MAX_FILE_BYTES // 1024}KB of "
                f"{size // 1024}KB total ...]"
            )
        else:
            content = p.read_text(encoding="utf-8", errors="replace")
        # Per-delegation total cap
        if _read_preload_file._total_bytes + len(content) > _PRELOAD_MAX_TOTAL_BYTES:  # type: ignore[attr-defined]
            return (
                f"(preload skipped: would exceed total budget "
                f"{_PRELOAD_MAX_TOTAL_BYTES // 1024}KB; "
                f"already used {_read_preload_file._total_bytes // 1024}KB)"  # type: ignore[attr-defined]
            )
        _read_preload_file._total_bytes += len(content)  # type: ignore[attr-defined]
        return content
    except (OSError, UnicodeDecodeError) as exc:
        return f"(load failed: {type(exc).__name__}: {exc})"


# Ensure the counter attribute exists at import time
_read_preload_file._total_bytes = 0  # type: ignore[attr-defined]


def reset_preload_budget() -> None:
    """Reset the per-delegation preload byte counter. Called by the handler
    wrapper at the start of each delegation so budgets don't leak across calls."""
    _read_preload_file._total_bytes = 0  # type: ignore[attr-defined]


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
        # v0.3.3 SG4: list of absolute file paths to preload into the brief.
        # Each file is read and its content inlined into a "## Preloaded Files"
        # section. 100KB per file, 1MB total per delegation. Best-effort —
        # missing files surface as text in the brief, not exceptions.
        preload_files: Optional[List[str]] = None,
        **extra: Any,
    ) -> Any:
        """Delegate to the named archetype. Same shape as native delegate_task.

        Returns str for single-task mode, list for batch (tasks=[...]) mode.
        """
        spec = get_archetype(archetype_name)

        # Apply per-call model override (rare escape hatch)
        if model_override:
            spec = apply_model_override(spec, model_override)

        # Reset preload budget at the start of every delegation
        reset_preload_budget()

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
            # v0.3.1: dispatch in PARALLEL via ThreadPoolExecutor (matches
            # native delegate_task's behaviour). Previously this looped
            # sequentially, silently serialising work that callers expected
            # to run concurrently. See TODO.md v0.3.1 bug #1.
            from concurrent.futures import ThreadPoolExecutor

            # Cap concurrency: never spawn more workers than tasks, and
            # never more than delegation.max_concurrent_children (matches
            # native's safety bound). Fall back to len(tasks) if not set.
            try:
                max_workers = min(
                    len(tasks),
                    int(os.getenv("HERMES_MAX_CONCURRENT_CHILDREN", str(len(tasks))))
                    if os.getenv("HERMES_MAX_CONCURRENT_CHILDREN", "").isdigit()
                    else len(tasks),
                )
            except Exception:
                max_workers = len(tasks)

            def _run_one(item: Tuple[int, Dict[str, Any]]) -> Any:
                idx, t = item
                t_goal = t.get("goal", "")
                t_context = t.get("context", "")
                t_role = t.get("role", role) or "leaf"
                t_max = t.get("max_iterations") or budget
                brief = _assemble_brief(
                    spec, t_goal, t_context, skill_filter, output_schema_override,
                    preload_files=preload_files,
                )
                return _arch_delegate(
                    spec=spec,
                    brief=brief,
                    context=t_context,
                    toolsets=spec.default_toolsets,
                    parent_agent=parent_agent,
                    role=t_role,
                    background=bool(background),
                    real_goal=t_goal,
                    task_index=idx,
                )

            with ThreadPoolExecutor(max_workers=max(1, max_workers)) as ex:
                results = list(ex.map(_run_one, enumerate(tasks)))
            return results

        # Single task
        brief = _assemble_brief(
            spec, goal or "", context, skill_filter, output_schema_override,
            preload_files=preload_files,
        )
        return _arch_delegate(
            spec=spec,
            brief=brief,
            context=context,
            toolsets=spec.default_toolsets,
            parent_agent=parent_agent,
            role=role or "leaf",
            background=bool(background),
            real_goal=goal or "",
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
        "preload_files": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "v0.3.3 SG4: list of absolute file paths to preload into the brief. "
                "Each file is read and its content inlined into a '## Preloaded Files' "
                "section the subagent sees. Useful for TODO.md, raw-meeting-transcripts, "
                "design specs, or any reference material the subagent needs upfront. "
                "Caps: 100KB per file, 1MB total per delegation. Best-effort — missing "
                "or oversized files surface as text in the brief, not exceptions."
            ),
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