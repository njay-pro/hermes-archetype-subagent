"""OMCA Archetype Router — Hermes plugin.

Exposes 5 archetype-specific delegation tools:

  - delegate_task_consultant             (Archetype I — Raw Power)
  - delegate_task_long_horizon           (Archetype II — Low-Hallucination)
  - delegate_task_high_hallucination     (Archetype III — Creative, Lateral)
  - delegate_task_speedster_internal     (Archetype IVa — Cheap / Fast / LOCAL)
  - delegate_task_speedster_internet     (Archetype IVb — Cheap / Fast / NETWORK)

Each tool is a thin wrapper around Hermes's native `delegate_task` that
pre-fills:

  - the archetype's model + provider (from archetype_model_config.json)
  - the archetype's default toolsets, skill whitelist, output_schema
    (from archetypes.yaml — mechanical config only)
  - the archetype's SOUL_<name>.md as persistent identity
    (the SINGLE source of identity prose — not duplicated in YAML)

CONFIGURATION SPLIT (since 2026-07-22):
  - archetype_model_config.json — model + provider ONLY (rotates often)
    Edit this file to retarget an archetype to a different model.
    Takes effect on the next delegation call — no plugin reload needed.
  - archetypes.yaml             — mechanical config ONLY (stable)
    Edit this to change toolsets, output_schema, max_iterations, or
    the global default_disabled_skills list.
    Takes effect on the next delegation call — no plugin reload needed.
  - SOUL_<name>.md              — identity prose ONLY (the single source)
    Edit this to evolve the persona: who the archetype is, its
    anti-patterns, escalation codes, briefing format expectations.
    Read on every delegation call.

OVERRIDE ESCAPE HATCH:
  The `model_override` parameter on each tool allows per-call model
  retargeting without editing the JSON. Use sparingly — it bypasses
  the canonical config. Format:
      delegate_task_consultant(
          goal="...",
          model_override={"provider": "openrouter", "model": "openai/gpt-5.6"}
      )

Architecture: this plugin bypasses native `delegate_task`'s model+provider
resolution layer by setting `delegation.model` + `delegation.provider` in
~/.hermes/config.yaml for each call, then calling native. Native reads the
new values via its mtime-based config cache. The bypass lives in
`archetype_delegate.py` (~330 LOC). Native still does the heavy lifting:
child construction, live transcripts, async dispatch, spawn pause, role
gating, result aggregation.

SOUL_<name>.md is the single source of identity prose — archetypes.yaml
holds only mechanical routing config.

Author: Njay + Hermes (OMCA framework, July 2026)
"""
__version__ = "0.3.0"

# Lazy re-exports — defer importing router.py until register() is called
# by Hermes. This avoids import-time failures when test tooling tries to
# import this __init__.py as a standalone module.
__all__ = [
    "register",
    "load_archetypes",
    "reload_archetypes",
    "list_archetypes",
    "get_archetype",
    "describe_config_split",
    "apply_model_override",
    "get_default_disabled_skills",
    "resolve_orchestrator_skill_filter",
]


def __getattr__(name: str):  # PEP 562 — module-level __getattr__
    """Lazy attribute access. Imports router on first access of any export."""
    if name in __all__:
        # Load router.py as a sibling module via importlib (works whether or
        # not this plugin is being imported as a package or as a flat module).
        import importlib.util
        import sys
        from pathlib import Path

        # Resolve the path to this plugin directory and load router.py as
        # an absolute module name so relative imports inside router.py work.
        _plugin_dir = Path(__file__).resolve().parent
        _router_path = _plugin_dir / "router.py"

        # Use a stable module name so subsequent calls hit the import cache
        _router_module_name = "_archetype_router_internal"
        if _router_module_name not in sys.modules:
            spec = importlib.util.spec_from_file_location(
                _router_module_name, _router_path
            )
            if spec is None or spec.loader is None:
                raise ImportError(
                    f"Cannot load router.py at {_router_path}"
                )
            module = importlib.util.module_from_spec(spec)
            sys.modules[_router_module_name] = module
            spec.loader.exec_module(module)

        value = getattr(sys.modules[_router_module_name], name)
        globals()[name] = value  # cache for next access
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")