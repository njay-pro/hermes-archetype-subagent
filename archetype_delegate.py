"""Archetype delegation — mimic AIAgent subagent execution in-memory with live transcript streaming.

Architecture (v0.3.0 - Mimic):
  - Directly instantiates AIAgent with archetype-specific model & provider credentials
  - Preserves live progress callbacks, streaming transcripts, and subagent progress relays
  - Bypasses native delegate_task wrapper and file-system mutations completely
  - Operates 100% in-memory with zero writes to ~/.hermes/config.yaml

Author: Njay + Hermes (OMCA framework)
"""
from __future__ import annotations

import logging
import uuid as _uuid
from typing import Any, Dict, List, Optional, Tuple

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
    ]
)


def resolve_creds_for_spec(spec, model_override: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Resolve spec.provider + spec.model into a credential bundle.

    Returns a dict with model, provider, base_url, api_key, api_mode. Uses
    native's resolve_runtime_provider() to look up base_url/api_key/api_mode.

    If model_override is given, it wins over spec.model + spec.provider.
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

    if provider and provider.startswith("custom:"):
        requested = provider[len("custom:"):]
        try:
            runtime = resolve_runtime_provider(
                requested=requested,
                target_model=model,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to resolve provider %r: %s", provider, exc)
            return {
                "model": model,
                "provider": provider,
                "base_url": None,
                "api_key": None,
                "api_mode": None,
            }
        return {
            "model": model,
            "provider": provider,
            "base_url": runtime.get("base_url"),
            "api_key": runtime.get("api_key"),
            "api_mode": runtime.get("api_mode"),
        }

    try:
        runtime = resolve_runtime_provider(
            requested=provider,
            target_model=model,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Provider %r did not resolve (%s); using bare values", provider, exc)
        return {
            "model": model,
            "provider": provider,
            "base_url": None,
            "api_key": None,
            "api_mode": None,
        }
    return {
        "model": model,
        "provider": provider,
        "base_url": runtime.get("base_url"),
        "api_key": runtime.get("api_key"),
        "api_mode": runtime.get("api_mode"),
    }


def _strip_blocked_tools(toolsets: List[str]) -> List[str]:
    """Filter out blocked tools/toolsets from subagent toolsets."""
    return [t for t in toolsets if t not in DELEGATE_BLOCKED_TOOLS]


def _open_live_transcript(archetype_name: str, task_index: int) -> Tuple[Optional[Any], Optional[str]]:
    """Create a live-transcript writer for an archetype delegation.

    Returns (writer, log_path). The writer tee's every tool-progress event
    to a JSONL file at ``cache/delegation/live/<delegation_id>/task-<N>.log``
    so post-hoc debugging / replay is possible.

    Native does this via ``tools.delegation_live_log.create_live_transcripts``
    + ``wrap_progress_callback``. We do the same so callers / TUI / log
    scrapers see identical artifacts regardless of which delegation path
    produced the transcript.

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

    # create_live_transcripts expects a list of task dicts.
    # We always have exactly one task per archetype call.
    _, writers, paths = create_live_transcripts(
        [{"goal": f"[{archetype_name}] (live transcript)", "context": None}],
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
) -> Optional[Any]:
    """Open a live-transcript writer and wrap inner_cb so events are tee'd to disk.

    Returns the wrapped callback (or inner_cb unchanged if live-transcript
    isn't available). Always preserves the inner callback contract — if
    the live-transcript setup fails, inner_cb is returned untouched so the
    agent loop is never affected.
    """
    try:
        from tools.delegation_live_log import wrap_progress_callback
    except ImportError:
        try:
            from hermes_agent.tools.delegation_live_log import wrap_progress_callback
        except ImportError:
            return inner_cb

    writer, _log_path = _open_live_transcript(archetype_name, task_index)
    if writer is None:
        return inner_cb
    try:
        return wrap_progress_callback(inner_cb, writer)
    except Exception as exc:  # noqa: BLE001
        logger.debug("wrap_progress_callback failed, returning inner_cb: %s", exc)
        return inner_cb


def _setup_progress_callbacks(task_index: int, goal: str, parent_agent: Any, subagent_id: str, model: str, toolsets: List[str]):
    """Set up live progress callback, thinking callback, and text stream relay."""
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

    parent_api_key = getattr(parent_agent, "api_key", None) if parent_agent else None
    if (not parent_api_key) and parent_agent and hasattr(parent_agent, "_client_kwargs"):
        parent_api_key = parent_agent._client_kwargs.get("api_key")

    base_url = creds.get("base_url") or (getattr(parent_agent, "base_url", None) if parent_agent else None)
    api_key = creds.get("api_key") or parent_api_key

    subagent_id = f"sa-{task_index}-{_uuid.uuid4().hex[:8]}"

    child_progress_cb, child_thinking_cb, stream_relay = _setup_progress_callbacks(
        task_index=task_index,
        goal=brief,
        parent_agent=parent_agent,
        subagent_id=subagent_id,
        model=creds["model"],
        toolsets=clean_toolsets,
    )

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
        skip_memory=True,
        thinking_callback=child_thinking_cb,
        # Wrap the progress callback so events are ALSO tee'd to a live
        # transcript log file at cache/delegation/live/<id>/task-<N>.log.
        # See tools.delegation_live_log — the wrapper is best-effort;
        # failures in the writer never reach the agent loop.
        tool_progress_callback=_wrap_for_live_transcript(
            child_progress_cb, archetype_name=spec.name, task_index=task_index,
        ),
        session_db=getattr(parent_agent, "_session_db", None) if parent_agent else None,
        parent_session_id=getattr(parent_agent, "session_id", None) if parent_agent else None,
    )
    setattr(child, "_delegate_depth", child_depth)
    setattr(child, "_subagent_id", subagent_id)
    setattr(child, "_stream_relay", stream_relay)
    return child


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

    if background:
        from concurrent.futures import ThreadPoolExecutor

        executor = ThreadPoolExecutor(max_workers=1)
        future = executor.submit(
            child.run_conversation, user_message=brief, stream_callback=stream_relay
        )
        return future

    res = child.run_conversation(user_message=brief, stream_callback=stream_relay)
    if isinstance(res, dict):
        return res.get("final_response") or res.get("response") or str(res)
    return str(res)