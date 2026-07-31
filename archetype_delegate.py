"""Archetype delegation — mimic AIAgent subagent execution in-memory with live transcript streaming.

Architecture (v0.3.0 - Mimic):
  - Directly instantiates AIAgent with archetype-specific model & provider credentials
  - Preserves live progress callbacks, streaming transcripts, and subagent progress relays
  - Bypasses native delegate_task wrapper and file-system mutations completely
  - Operates 100% in-memory with zero writes to ~/.hermes/config.yaml

Author: Njay + Hermes (OMCA framework)
"""
from __future__ import annotations

import importlib
import json
import logging
import os
import sys
import uuid as _uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Profile-aware Hermes home resolution (v0.3.4)
# ---------------------------------------------------------------------------
#
# Before v0.3.4, the plugin read `HERMES_HOME` at module import and cached
# the value. It ignored `HERMES_PROFILE` entirely. Subagents spawned in
# non-root profiles (e.g. `ana-board`) wrote their live-transcript cache to
# the root `~/.hermes/cache/delegation/live/...` instead of the
# profile-scoped `~/.hermes/profiles/ana-board/cache/delegation/live/...`,
# causing transcript collisions when two profiles delegated concurrently.
#
# The fix introduces `_hermes_home()`, called by every cache-path write
# site. Resolution priority (highest first):
#   1. HERMES_HOME env var (profile-isolated launches set this).
#   2. HERMES_PROFILE env var (the v0.3.4 fix — subprocesses forgot
#      HERMES_HOME but did forward HERMES_PROFILE).
#   3. Module-level HERMES_HOME if mutated since import (v0.3.2 test contract).
#   4. Native default.
# ---------------------------------------------------------------------------


# Capture the initial env-resolved default at import time. This is the
# "what was the home when the plugin loaded" anchor used by the patch
# detector below.
def _initial_default() -> Path:
    try:
        from hermes_constants import get_hermes_home as _native_home
        return _native_home()
    except ImportError:
        return Path.home() / ".hermes"


_INITIAL_HERMES_HOME: Path = _initial_default()
# Module-level backwards-compat shim for the existing test suite.
HERMES_HOME = _INITIAL_HERMES_HOME


def _hermes_home() -> Path:
    """Return the current profile-aware Hermes home (see module docstring).

    The discriminator between "test monkey-patched HERMES_HOME" and
    "subprocess set HERMES_HOME" is comparing the module-level symbol
    against the value it had at import time (``_INITIAL_HERMES_HOME``).
    If they diverge, someone has patched the symbol. Otherwise env wins.
    """
    # Priority 1: module-level patch wins (v0.3.2 test contract — tests do
    # `ad.HERMES_HOME = Path(tmp)`). Compare against the initial value,
    # not the current env-resolved default, so env mutations between
    # import and call don't get mistaken for patches.
    if HERMES_HOME != _INITIAL_HERMES_HOME:
        return HERMES_HOME

    # Priority 2: env-set HERMES_HOME (profile-isolated launches — wins
    # over HERMES_PROFILE because the subprocess explicitly set it).
    env_home = os.environ.get("HERMES_HOME", "").strip()
    if env_home:
        return Path(env_home)

    # Priority 3: HERMES_PROFILE alone (the v0.3.4 fix — subprocesses that
    # forgot HERMES_HOME but did forward HERMES_PROFILE).
    profile = os.environ.get("HERMES_PROFILE", "").strip()
    if profile:
        return _INITIAL_HERMES_HOME / "profiles" / profile

    # Priority 4: import-time default.
    return _INITIAL_HERMES_HOME


logger = logging.getLogger("archetype-router.delegate")


# Tools that subagent children must not have access to (matches native delegate_task)
DELEGATE_BLOCKED_TOOLS = frozenset(
    [
        "delegate_task",
        "clarify",
        "memory",
        "send_message",
        "execute_code",
        "cronjob",
        # v0.3.1: also block all 5 plugin tools so a role="orchestrator"
        # subagent cannot recursively spawn the same archetype (unbounded
        # recursion / cost-explosion vector). See TODO.md v0.3.1 bug #2.
        "delegate_task_consultant",
        "delegate_task_long_horizon",
        "delegate_task_high_hallucination",
        "delegate_task_speedster_internal",
        "delegate_task_speedster_internet",
    ]
)


def resolve_creds_for_spec(spec, model_override: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Resolve spec.provider + spec.model into a credential bundle.

    Returns a dict with model, provider, base_url, api_key, api_mode. Uses
    native's resolve_runtime_provider() to look up base_url/api_key/api_mode.

    If model_override is given, it wins over spec.model + spec.provider.

    v0.4.0: On failure, walks spec.fallback_chain — a list of
    {provider, model} dicts from archetype_model_config.json. Each entry
    is re-resolved via Hermes's resolve_runtime_provider(); Hermes itself
    walks its own fallback_models list internally per provider. We do NOT
    reimplement the fallback chain — Hermes already has one. We just
    give it a list of provider hops to try.
    """
    try:
        from hermes_cli.runtime_provider import resolve_runtime_provider
    except ImportError as exc:
        logger.error("Cannot import hermes_cli.runtime_provider: %s", exc)
        return {}

    if model_override:
        model = model_override.get("model") or spec.model
        provider = model_override.get("provider") or spec.provider
    else:
        model = spec.model
        provider = spec.provider

    # Build the ordered list of (provider, model) attempts: primary first,
    # then fallback_chain entries. Each is one Hermes resolution attempt.
    attempts: List[Dict[str, str]] = []
    if provider and model:
        attempts.append({"provider": provider, "model": model})
    for entry in (spec.fallback_chain or []):
        if isinstance(entry, dict) and entry.get("provider") and entry.get("model"):
            attempts.append({"provider": entry["provider"], "model": entry["model"]})

    last_exc: Optional[Exception] = None
    for attempt in attempts:
        ap = attempt["provider"]
        am = attempt["model"]
        requested = ap[len("custom:"):] if ap.startswith("custom:") else ap
        try:
            runtime = resolve_runtime_provider(
                requested=requested,
                target_model=am,
            )
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            logger.warning(
                "Provider %r failed for archetype %s: %s. "
                "Trying next in fallback_chain.",
                ap, spec.name, exc,
            )
            continue
        # Success — log which attempt won if it's not the primary
        if attempt is not attempts[0]:
            logger.info(
                "Archetype %s using fallback provider %r (model=%s) — "
                "primary %r unavailable: %s",
                spec.name, ap, am, attempts[0]["provider"], last_exc,
            )
        return {
            "model": am,
            "provider": ap,
            "base_url": runtime.get("base_url"),
            "api_key": runtime.get("api_key"),
            "api_mode": runtime.get("api_mode"),
        }

    # All attempts failed.
    logger.error(
        "All %d fallback providers exhausted for archetype %s. Last error: %s",
        len(attempts), spec.name, last_exc,
    )
    return {
        "model": model,
        "provider": provider,
        "base_url": None,
        "api_key": None,
        "api_mode": None,
    }


def _strip_blocked_tools(toolsets: List[str]) -> List[str]:
    """Filter out blocked tools/toolsets from subagent toolsets."""
    return [t for t in toolsets if t not in DELEGATE_BLOCKED_TOOLS]


def _open_live_transcript(
    archetype_name: str, task_index: int, real_goal: str = ""
) -> Tuple[Optional[Any], Optional[str]]:
    """Create a live-transcript writer for an archetype delegation.

    Returns (writer, log_path). The writer tee's every tool-progress event
    to a JSONL file at ``cache/delegation/live/<delegation_id>/task-<N>.log``
    so post-hoc debugging / replay is possible.

    Native does this via ``tools.delegation_live_log.create_live_transcripts``
    + ``wrap_progress_callback``. We do the same so callers / TUI / log
    scrapers see identical artifacts regardless of which delegation path
    produced the transcript.

    real_goal (v0.3.2): the actual goal text from the orchestrator. We pass
    it through to the live-transcript manifest so the TUI / dashboard show
    the REAL goal, not a placeholder like "[consultant] (live transcript)".
    Falls back to a brief description if real_goal is empty (shouldn't happen
    in practice but we keep the function total).

    Returns ``(None, None)`` if the live-log module isn't importable (e.g.
    during tests outside the Hermes venv) — the agent still runs, we just
    skip the file tee.
    """
    try:
        from tools.delegation_live_log import (
            create_live_transcripts,
            wrap_progress_callback,
        )
    except ImportError:
        try:
            from hermes_agent.tools.delegation_live_log import (
                create_live_transcripts,
                wrap_progress_callback,
            )
        except ImportError:
            logger.debug("Live transcript module not available — skipping file tee")
            return None, None

    # v0.3.2: pass the real goal through. The transcript manifest will then
    # show the actual user goal instead of a placeholder.
    task_goal = real_goal if real_goal else f"[{archetype_name}] (live transcript)"

    # create_live_transcripts expects a list of task dicts.
    # We always have exactly one task per archetype call.
    _, writers, paths = create_live_transcripts(
        [{"goal": task_goal, "context": None}],
        context=None,
    )
    writer = writers[0] if writers else None
    log_path = paths[0] if paths else None
    if log_path:
        logger.info(
            "Live transcript armed for %s task-%d → %s",
            archetype_name, task_index, log_path,
        )
    return writer, log_path


def _wrap_for_live_transcript(
    inner_cb: Optional[Any],
    archetype_name: str,
    task_index: int,
    real_goal: str = "",
) -> Optional[Any]:
    """Open a live-transcript writer and wrap inner_cb so events are tee'd to disk.

    Returns the wrapped callback (or inner_cb unchanged if live-transcript
    isn't available). Always preserves the inner callback contract — if
    the live-transcript setup fails, inner_cb is returned untouched so the
    agent loop is never affected.

    real_goal (v0.3.2): forwarded to _open_live_transcript so the manifest
    shows the actual user goal, not a placeholder.
    """
    try:
        from tools.delegation_live_log import wrap_progress_callback
    except ImportError:
        try:
            from hermes_agent.tools.delegation_live_log import wrap_progress_callback
        except ImportError:
            return inner_cb

    writer, _log_path = _open_live_transcript(archetype_name, task_index, real_goal)
    if writer is None:
        return inner_cb
    try:
        return wrap_progress_callback(inner_cb, writer)
    except Exception as exc:  # noqa: BLE001
        logger.debug("wrap_progress_callback failed, returning inner_cb: %s", exc)
        return inner_cb


def _setup_progress_callbacks(
    task_index: int,
    goal: str,
    parent_agent: Any,
    subagent_id: str,
    model: str,
    toolsets: List[str],
    session_ref: Optional[Dict[str, Any]] = None,
):
    """Set up live progress callback, thinking callback, and text stream relay.

    session_ref (v0.3.2): mutable dict the callback closure reads on every
    event to populate the `child_session_id` field. Native delegates do this
    so the TUI can open a preview pane for the child session. Mimic-constructed
    children were missing this — preview pane stayed empty. Pass a dict that
    gets populated AFTER AIAgent construction with `{"session_id": ...}`; the
    callback picks it up on the next emitted event. See TODO.md v0.3.2.
    """
    try:
        try:
            from tools.delegate_tool import _build_child_progress_callback
        except ImportError:
            from hermes_agent.tools.delegate_tool import _build_child_progress_callback  # type: ignore

        parent_subagent_id = getattr(parent_agent, "_subagent_id", None) if parent_agent else None
        child_depth = getattr(parent_agent, "_delegate_depth", 0) + 1 if parent_agent else 1
        tui_depth = max(0, child_depth - 1)

        child_progress_cb = _build_child_progress_callback(
            task_index,
            goal,
            parent_agent,
            task_count=1,
            subagent_id=subagent_id,
            parent_id=parent_subagent_id,
            depth=tui_depth,
            model=model,
            toolsets=toolsets,
            session_ref=session_ref,  # v0.3.2: threaded into child_session_id
        )

        child_thinking_cb = None
        if child_progress_cb:
            def _child_thinking(text: str) -> None:
                if text:
                    try:
                        child_progress_cb("_thinking", text)
                    except Exception:
                        pass
            child_thinking_cb = _child_thinking

        def _relay_child_text(delta: str) -> None:
            if delta and child_progress_cb:
                try:
                    child_progress_cb("subagent.text", preview=delta)
                except Exception:
                    pass

        return child_progress_cb, child_thinking_cb, _relay_child_text
    except Exception as exc:  # noqa: BLE001
        logger.debug("Progress callback setup skipped: %s", exc)
        return None, None, None


def _build_child_agent_mimic(
    spec,
    brief: str,
    toolsets: List[str],
    parent_agent: Any,
    model_override: Optional[Dict[str, str]] = None,
    task_index: int = 0,
    real_goal: str = "",
) -> Any:
    """Instantiate a child AIAgent directly with explicit archetype credentials and prompt.

    Preserves live progress callbacks and transcript streaming without file mutations.
    """
    try:
        from run_agent import AIAgent  # type: ignore
    except ImportError:
        try:
            from agent.ai_agent import AIAgent  # type: ignore
        except ImportError:
            class AIAgent:  # type: ignore
                def __init__(self, **kwargs):
                    for k, v in kwargs.items():
                        setattr(self, k, v)

                def run_conversation(self, user_message: Any, **kwargs):
                    return {"final_response": f"Mock response for {user_message}"}

    creds = resolve_creds_for_spec(spec, model_override=model_override)
    if not creds or not creds.get("model"):
        raise RuntimeError(
            f"Could not resolve credentials for archetype {spec.name!r} "
            f"(provider={spec.provider!r}, model={spec.model!r}). "
            f"Check that provider is configured in ~/.hermes/config.yaml."
        )

    clean_toolsets = _strip_blocked_tools(toolsets)
    child_depth = getattr(parent_agent, "_delegate_depth", 0) + 1 if parent_agent else 1
    # v0.3.2: mirror native — TUI uses max(0, depth - 1) so a depth-1 child
    # shows at root level, not nested under an invisible parent.
    tui_depth = max(0, child_depth - 1)

    parent_api_key = getattr(parent_agent, "api_key", None) if parent_agent else None
    if (not parent_api_key) and parent_agent and hasattr(parent_agent, "_client_kwargs"):
        parent_api_key = parent_agent._client_kwargs.get("api_key")

    base_url = creds.get("base_url") or (getattr(parent_agent, "base_url", None) if parent_agent else None)
    api_key = creds.get("api_key") or parent_api_key

    subagent_id = f"sa-{task_index}-{_uuid.uuid4().hex[:8]}"
    # v0.3.2: pre-assign a session_id so the TUI preview pane can key off
    # `child_session_id` from the very first emitted event. If we let
    # AIAgent auto-generate one in `__init__`, the value is not visible to
    # `getattr(child, "session_id", None)` until later (race with callback
    # closure). Pre-assigning means we know the value synchronously, populate
    # session_ref before construction, and the very first tool-progress event
    # already carries the right `child_session_id`.
    child_session_id = f"plugin-{subagent_id}"

    # v0.3.2: mutable dict the progress callback closure reads on every event
    # to populate `child_session_id` for the TUI preview pane. Populated
    # IMMEDIATELY (not after AIAgent construction) so the first event has it.
    session_ref: Dict[str, Any] = {"session_id": child_session_id}

    child_progress_cb, child_thinking_cb, stream_relay = _setup_progress_callbacks(
        task_index=task_index,
        goal=real_goal or brief,
        parent_agent=parent_agent,
        subagent_id=subagent_id,
        model=creds["model"],
        toolsets=clean_toolsets,
        session_ref=session_ref,
    )

    # v0.3.2: Open the live transcript FIRST so we get the log_path → derive
    # the delegation_id for the manifest-close path. Then wrap the inner
    # callback with the writer. Doing them separately (instead of using
    # _wrap_for_live_transcript) gives us a stable handle on the writer
    # AND the delegation_id without relying on closure introspection.
    live_writer, live_log_path = _open_live_transcript(
        spec.name, task_index, real_goal=real_goal or brief
    )
    _delegation_id: Optional[str] = None
    if live_log_path is not None:
        try:
            _delegation_id = Path(live_log_path).parent.name
            if _delegation_id in ("", "."):
                _delegation_id = None
        except Exception:
            _delegation_id = None

    # v0.4.0: Auto-open the Subagent Dashboard on the first plugin dispatch
    # in this process. Idempotent — module-level flag makes subsequent
    # dispatches no-ops. The dashboard polls
    # ~/.hermes/cache/delegation/live/*/ so it picks up this delegation
    # once the live_writer writes its first event.
    try:
        from auto_dashboard import auto_open_dashboard
        auto_open_dashboard()
    except Exception as _exc:  # never block dispatch on dashboard failure
        logger.debug("auto_open_dashboard skipped: %s", _exc)

    # Wrap the inner callback with the live-transcript writer
    if live_writer is not None:
        try:
            from tools.delegation_live_log import wrap_progress_callback
        except ImportError:
            from hermes_agent.tools.delegation_live_log import wrap_progress_callback
        wrapped_tpc = wrap_progress_callback(child_progress_cb, live_writer)
    else:
        wrapped_tpc = child_progress_cb

    child = AIAgent(
        base_url=base_url,
        api_key=api_key,
        model=creds["model"],
        provider=creds["provider"],
        api_mode=creds.get("api_mode"),
        max_iterations=spec.max_iterations,
        enabled_toolsets=clean_toolsets,
        quiet_mode=True,
        ephemeral_system_prompt=brief,
        platform="subagent",
        skip_context_files=True,
        # v0.3.3 SG1: don't let the runtime inject its own default SOUL.md
        # — the archetype plugin owns the persona via SOUL_<name>.md in
        # the brief. AIAgent's load_soul_identity=True would compete and
        # pollute the subagent's identity.
        load_soul_identity=False,
        skip_memory=True,
        thinking_callback=child_thinking_cb,
        # v0.3.2: real_goal is already passed to _open_live_transcript above,
        # so the live-transcript manifest shows the actual user goal.
        tool_progress_callback=wrapped_tpc,
        session_db=getattr(parent_agent, "_session_db", None) if parent_agent else None,
        parent_session_id=getattr(parent_agent, "session_id", None) if parent_agent else None,
        # v0.3.2: pass our pre-assigned session_id so the AIAgent uses the
        # same value the callback advertises in child_session_id. Otherwise
        # AIAgent would auto-generate a different one and the TUI preview
        # pane (keyed on the callback's value) would fail to open the
        # matching session.
        session_id=child_session_id,
    )
    setattr(child, "_delegate_depth", child_depth)
    setattr(child, "_subagent_id", subagent_id)
    setattr(child, "_stream_relay", stream_relay)
    setattr(child, "_parent_subagent_id", getattr(parent_agent, "_subagent_id", None) if parent_agent else None)
    if _delegation_id:
        setattr(child, "_delegation_id", _delegation_id)

    # v0.3.2: Defensive — confirm session_id matches what we passed. If AIAgent
    # overrode it for any reason, update session_ref to match (the callback
    # closure reads this dict on every event, so it always sees the latest
    # value). session_ref is already populated with child_session_id; this
    # block only fires if AIAgent changed it.
    child_sid = getattr(child, "session_id", None)
    if isinstance(child_sid, str) and child_sid and child_sid != session_ref.get("session_id"):
        session_ref["session_id"] = child_sid

    # v0.3.2: Register child into the module-level _active_subagents dict
    # so the TUI can target it by subagent_id (interrupt, status queries,
    # live tree view). Mirrors native delegate_tool._register_subagent.
    _register_plugin_subagent(
        subagent_id=subagent_id,
        parent_id=getattr(child, "_parent_subagent_id", None),
        depth=tui_depth if isinstance(tui_depth, int) else 0,
        goal=brief,
        model=creds.get("model"),
        child=child,
    )

    return child


def _register_plugin_subagent(
    subagent_id: str,
    parent_id: Optional[str],
    depth: int,
    goal: str,
    model: Optional[str],
    child: Any,
) -> None:
    """Register a plugin-constructed child into native's _active_subagents dict.

    v0.3.2: this is what lets the TUI's live subagent tree see mimic-built
    children. Native does the same in delegate_tool._register_subagent.

    Module-path problem: `delegate_tool` may be importable as
    `tools.delegate_tool` OR `hermes_agent.tools.delegate_tool` depending on
    how the gateway is wired. Each path loads its own copy of the module
    → each has its OWN `_active_subagents` dict → registering in the wrong
    one means the TUI (which polls the path it loaded) never sees the child.

    Fix: try every plausible import path, and ALSO scan `sys.modules` for
    any module that already has an `_active_subagents` attribute and looks
    like delegate_tool. Register into every match (idempotent — the dict
    is keyed by subagent_id so duplicates are harmless).
    """
    import time as _time
    import types

    record = {
        "subagent_id": subagent_id,
        "parent_id": parent_id if isinstance(parent_id, str) else None,
        "depth": depth,
        "goal": goal,
        "model": model if isinstance(model, str) else None,
        "started_at": _time.time(),
        "status": "running",
        "tool_count": 0,
        "agent": child,
    }

    # Strategy 1: import-time discovery of plausible delegate_tool modules
    candidate_paths = (
        "tools.delegate_tool",
        "hermes_agent.tools.delegate_tool",
        "delegate_tool",
    )
    found_modules: List[Any] = []
    for path in candidate_paths:
        try:
            mod = importlib.import_module(path)
            if hasattr(mod, "_active_subagents") and isinstance(
                getattr(mod, "_active_subagents"), dict
            ):
                found_modules.append(mod)
        except Exception as exc:
            logger.debug("Could not import %s: %s", path, exc)

    # Strategy 2: scan sys.modules for any module that already exposes an
    # _active_subagents dict (catches any future import path we didn't list).
    for mod_name, mod in list(sys.modules.items()):
        if mod is None or not isinstance(mod, types.ModuleType):
            continue
        if "delegate" not in mod_name:
            continue
        if not hasattr(mod, "_active_subagents"):
            continue
        if not isinstance(getattr(mod, "_active_subagents"), dict):
            continue
        if mod not in found_modules:
            found_modules.append(mod)

    if not found_modules:
        logger.debug(
            "Plugin subagent %s not registered — no delegate_tool module "
            "with _active_subagents found in this runtime.",
            subagent_id,
        )
        return

    for mod in found_modules:
        try:
            mod._active_subagents[subagent_id] = record
            logger.debug(
                "Plugin subagent %s registered into %s._active_subagents",
                subagent_id,
                mod.__name__,
            )
        except Exception as exc:
            logger.debug(
                "Failed to register into %s: %s", mod.__name__, exc
            )


def _unregister_plugin_subagent(subagent_id: str) -> None:
    """Mirror of _register_plugin_subagent — drop from every dict we wrote to.

    v0.3.2: keeps the TUI's subagent tree from leaking entries for completed
    plugin children. Removes from every plausible delegate_tool module so
    the TUI's view stays clean regardless of which path it uses.
    """
    import types

    candidate_paths = (
        "tools.delegate_tool",
        "hermes_agent.tools.delegate_tool",
        "delegate_tool",
    )
    seen_modules: set = set()
    targets: List[Any] = []
    for path in candidate_paths:
        try:
            mod = importlib.import_module(path)
            if hasattr(mod, "_active_subagents") and id(mod) not in seen_modules:
                targets.append(mod)
                seen_modules.add(id(mod))
        except Exception:
            pass
    for mod_name, mod in list(sys.modules.items()):
        if mod is None or not isinstance(mod, types.ModuleType):
            continue
        if "delegate" not in mod_name:
            continue
        if not hasattr(mod, "_active_subagents"):
            continue
        if id(mod) not in seen_modules:
            targets.append(mod)
            seen_modules.add(id(mod))

    for mod in targets:
        try:
            mod._active_subagents.pop(subagent_id, None)
        except Exception as exc:
            logger.debug(
                "Failed to unregister from %s: %s", mod.__name__, exc
            )


def _close_manifest(delegation_id: str, exit_reason: str = "completed") -> bool:
    """Mark a delegation manifest as completed in the live-transcript dir.

    v0.3.2: the plugin's previous version never closed the manifest, so
    the dashboard / TUI showed every past plugin delegation as "running"
    forever. This function reads `LIVE_DIR/<delegation_id>/manifest.json`,
    sets per-task status to "completed" (only if the task was running),
    and writes the top-level `completed` timestamp + `exit_reason`.

    Best-effort: any failure (missing manifest, malformed JSON, read-only
    fs) is logged at debug level and returns False. The agent has already
    finished by the time this is called, so a failure here cannot affect
    the run — only the post-hoc view.
    """
    if not delegation_id:
        return False
    import time as _time
    try:
        manifest_path = _hermes_home() / "cache" / "delegation" / "live" / delegation_id / "manifest.json"
        if not manifest_path.is_file():
            return False
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        # Only close if not already closed
        if data.get("completed") and data.get("exit_reason"):
            return True
        # Per-task close
        for task in data.get("tasks", []) or []:
            if task.get("status") == "running":
                task["status"] = "completed"
            if not task.get("exit_reason"):
                task["exit_reason"] = exit_reason
        data["completed"] = _time.strftime("%Y-%m-%d %H:%M:%S")
        data["exit_reason"] = exit_reason
        # Atomic write: write to .tmp then rename
        tmp = manifest_path.with_suffix(".json.tmp")
        try:
            tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            tmp.replace(manifest_path)
        except OSError:
            # Fall back to direct write if rename fails
            manifest_path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        return True
    except Exception as exc:
        logger.debug("Could not close manifest %s: %s", delegation_id, exc)
        return False


def archetype_delegate(
    spec,
    brief: str,
    context: Optional[str],
    toolsets: List[str],
    parent_agent: Any,
    *,
    role: str = "leaf",
    background: bool = False,
    model_override: Optional[Dict[str, str]] = None,
    real_goal: str = "",
    task_index: int = 0,
) -> Any:
    """Spawn a child AIAgent in-memory with archetype model & provider credentials.

    Bypasses native delegate_task and file-system mutations completely while
    preserving live transcript streaming and progress callbacks.
    """
    builder = globals().get("_build_child_agent_mimic", _build_child_agent_mimic)
    child = builder(
        spec=spec,
        brief=brief,
        toolsets=toolsets,
        parent_agent=parent_agent,
        model_override=model_override,
        real_goal=real_goal,
        task_index=task_index,
    )

    logger.info(
        "Archetype %s delegating (MIMIC) → model=%s provider=%s base_url=%s toolsets=%s role=%s background=%s",
        spec.name,
        getattr(child, "model", None),
        getattr(child, "provider", None),
        getattr(child, "base_url", None),
        toolsets,
        role,
        background,
    )

    stream_relay = getattr(child, "_stream_relay", None)
    subagent_id = getattr(child, "_subagent_id", None)

    if background:
        from concurrent.futures import ThreadPoolExecutor

        executor = ThreadPoolExecutor(max_workers=1)

        def _run_and_unregister() -> Any:
            try:
                return child.run_conversation(
                    user_message=brief, stream_callback=stream_relay
                )
            finally:
                if subagent_id:
                    _unregister_plugin_subagent(subagent_id)
                # v0.3.2: close the live-transcript manifest so the
                # dashboard / TUI show this delegation as completed, not
                # running-forever.
                did = getattr(child, "_delegation_id", None)
                if did:
                    _close_manifest(did)

        future = executor.submit(_run_and_unregister)
        return future

    try:
        res = child.run_conversation(user_message=brief, stream_callback=stream_relay)
    finally:
        # v0.3.2: keep the TUI's subagent tree clean after the child ends.
        if subagent_id:
            _unregister_plugin_subagent(subagent_id)
        # v0.3.2: close the manifest so past delegations stop showing as
        # "running" in the dashboard.
        did = getattr(child, "_delegation_id", None)
        if did:
            _close_manifest(did)

    if isinstance(res, dict):
        return res.get("final_response") or res.get("response") or str(res)
    return str(res)