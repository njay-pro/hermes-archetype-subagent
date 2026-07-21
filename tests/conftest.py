"""Shared fixtures for the test suite.

Tests live next to the plugin source. The conftest sets up the import path
so `import router` works without pip-installing the plugin (Hermes loads
the plugin via spec_from_file_location, not via pip).
"""
from __future__ import annotations

import importlib.util
import shutil
import sys
from pathlib import Path
from typing import Any, Iterator

import pytest

PLUGIN_DIR = Path(__file__).resolve().parent.parent

# Make plugin importable as a flat module — matches how Hermes loads it.
sys.path.insert(0, str(PLUGIN_DIR.parent))  # so `import archetype_delegate` works
sys.path.insert(0, str(PLUGIN_DIR))

# Add Hermes agent path if present so hermes_cli, run_agent, agent modules resolve
hermes_agent_dir = Path.home() / ".hermes" / "hermes-agent"
if hermes_agent_dir.is_dir() and str(hermes_agent_dir) not in sys.path:
    sys.path.insert(0, str(hermes_agent_dir))



@pytest.fixture(scope="session")
def plugin_dir() -> Path:
    """Absolute path to the plugin's flat directory."""
    return PLUGIN_DIR


@pytest.fixture(scope="session")
def router_module() -> Any:
    """Loaded `router` module from the plugin directory."""
    spec = importlib.util.spec_from_file_location(
        "router_under_test",
        PLUGIN_DIR / "router.py",
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def delegate_module() -> Any:
    """Loaded `archetype_delegate` module."""
    spec = importlib.util.spec_from_file_location(
        "archetype_delegate_under_test",
        PLUGIN_DIR / "archetype_delegate.py",
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def hermes_config_path() -> Iterator[Path]:
    """Snapshot and restore ~/.hermes/config.yaml around tests that mutate it.

    Snapshot is taken BEFORE the test, restore happens AFTER. This means tests
    that modify the config during their run do not affect later tests.
    """
    config = Path.home() / ".hermes" / "config.yaml"
    backup = Path("/tmp/hermes_config_test_backup.yaml")
    # Pre-test snapshot
    if config.exists():
        shutil.copy(config, backup)

    yield config

    # Post-test restore — always
    if backup.exists():
        shutil.copy(backup, config)
        backup.unlink(missing_ok=True)
    # Also remove any unique marker comments that test fixtures may have added
    # (defensive — the snapshot/restore above should handle it)


@pytest.fixture
def fake_parent_agent() -> Any:
    """A minimal stand-in for AIAgent that has every attribute native reads.

    Native `delegate_task` reads these from `parent_agent`:
      enabled_toolsets, model, provider, api_mode, base_url, api_key,
      _delegate_depth, _subagent_id, valid_tool_names, reasoning_config,
      acp_command, acp_args, tool_progress_callback
    """
    from types import SimpleNamespace

    return SimpleNamespace(
        enabled_toolsets=["terminal", "file", "web"],
        _enabled_toolsets=None,
        model="Strong1",
        provider="custom:9router",
        api_mode="chat_completions",
        base_url="http://localhost:20128/v1",
        api_key="sk-test-fake",
        _delegate_depth=0,
        _subagent_id=None,
        valid_tool_names=[],
        reasoning_config=None,
        acp_command=None,
        acp_args=[],
        tool_progress_callback=None,
    )