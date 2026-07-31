"""Context-local skill isolation hook for archetype-router.

We patch the skill discovery and verification functions globally once,
delegating to a contextvar (`_SKILL_ALLOWLIST`). When the contextvar is
set (during a subagent's run_conversation), the patched functions enforce
the allowlist. Otherwise, they fall back to native Hermes logic.

Thread-safe and async-safe via ContextVar.
"""

from __future__ import annotations

import contextvars
import logging
from pathlib import Path
import sys
import threading
from typing import Optional

logger = logging.getLogger(__name__)

# The active allowlist for the current execution context.
# If None, native Hermes skill discovery/validation runs unchanged.
_SKILL_ALLOWLIST: contextvars.ContextVar[Optional[list[str]]] = contextvars.ContextVar(
    "_SKILL_ALLOWLIST", default=None
)

_patched = False
_lock = threading.Lock() if "threading" in sys.modules else None


# Store original functions on the module so they are mockable and accessible
orig_get_disabled = None
orig_is_disabled = None


def patch_skills_isolation_system() -> None:
    """Globally patch Hermes skill resolution to support context-local whitelists.

    Must be called once at plugin load (e.g. in router.register or plugin root init).
    """
    global _patched, orig_get_disabled, orig_is_disabled
    if _patched:
        return
    
    # Simple double-check lock if threading is loaded
    if _lock:
        with _lock:
            if _patched:
                return
            _patched = True
    else:
        _patched = True

    try:
        import agent.skill_utils as skill_utils
        import tools.skills_tool as skills_tool
    except ImportError as e:
        logger.error("Could not import Hermes skill modules for isolation patching: %s", e)
        return

    # 1. Patch agent.skill_utils.get_disabled_skill_names
    orig_get_disabled = skill_utils.get_disabled_skill_names

    def patched_get_disabled_skill_names(platform: str | None = None) -> set[str]:
        allowlist = _SKILL_ALLOWLIST.get()
        if allowlist is None:
            return orig_get_disabled(platform)
        
        # Whitelist mode: treat everything NOT in the allowlist as "disabled"
        # First gather all installed skills
        from agent.skill_utils import get_external_skills_dirs, iter_skill_index_files
        all_skills = set()
        
        # Resolve active skills dir
        active_skills_dir = Path.home() / ".hermes" / "skills"
        # Try live dir from active profile if possible
        try:
            from tools.skills_tool import _skills_dir
            active_skills_dir = _skills_dir()
        except Exception:
            pass

        dirs = []
        if active_skills_dir.exists():
            dirs.append(active_skills_dir)
        dirs.extend(get_external_skills_dirs())

        for d in dirs:
            for skill_md in iter_skill_index_files(d, "SKILL.md"):
                # skill directory name is the lookup name
                all_skills.add(skill_md.parent.name)

        # Complement of whitelist is the disabled set
        # (We also include the original disabled ones just in case)
        disabled_complement = {s for s in all_skills if s not in allowlist}
        return disabled_complement | orig_get_disabled(platform)

    skill_utils.get_disabled_skill_names = patched_get_disabled_skill_names

    # Also patch any modules that might have already imported it via `from ... import`
    for mod_name, mod in list(sys.modules.items()):
        if mod and hasattr(mod, "get_disabled_skill_names") and getattr(mod, "get_disabled_skill_names") is orig_get_disabled:
            setattr(mod, "get_disabled_skill_names", patched_get_disabled_skill_names)

    # 2. Patch tools.skills_tool._is_skill_disabled
    orig_is_disabled = skills_tool._is_skill_disabled

    def patched_is_skill_disabled(name: str, platform: Optional[str] = None) -> bool:
        allowlist = _SKILL_ALLOWLIST.get()
        if allowlist is None:
            # Cast platform to str | None which is safe because Python accepts None
            return orig_is_disabled(name, platform)  # type: ignore
        # Whitelist check: if it's not in the allowlist, it is disabled
        return name not in allowlist

    skills_tool._is_skill_disabled = patched_is_skill_disabled

    # Also patch any modules that might have already imported it via `from ... import`
    for mod_name, mod in list(sys.modules.items()):
        if mod and hasattr(mod, "_is_skill_disabled") and getattr(mod, "_is_skill_disabled") is orig_is_disabled:
            setattr(mod, "_is_skill_disabled", patched_is_skill_disabled)

    logger.info("Hermes skill isolation system successfully patched (v0.4.3 context-local)")


class skill_isolation_context:
    """Context manager to enforce a skill allowlist in the current thread context."""
    def __init__(self, allowlist: list[str] | None):
        self.allowlist = allowlist
        self.token = None

    def __enter__(self):
        if self.allowlist is not None:
            self.token = _SKILL_ALLOWLIST.set(self.allowlist)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.token is not None:
            _SKILL_ALLOWLIST.reset(self.token)
