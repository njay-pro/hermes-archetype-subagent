"""Tests for v0.4.3 runtime skill isolation."""
from __future__ import annotations

import contextvars
from pathlib import Path
import sys

import pytest

import skill_isolation


def test_patch_initializes_and_replaces_functions():
    # Make sure patch can run safely
    skill_isolation.patch_skills_isolation_system()
    
    import agent.skill_utils as skill_utils
    import tools.skills_tool as skills_tool

    assert "patched_get_disabled_skill_names" in skill_utils.get_disabled_skill_names.__name__
    assert "patched_is_skill_disabled" in skills_tool._is_skill_disabled.__name__


def test_allowlist_context_manager_scoping():
    """Verify ContextVar preserves values within the scoping block and resets on exit."""
    # Ensure empty default
    assert skill_isolation._SKILL_ALLOWLIST.get() is None

    # Enter allowlist context
    whitelist = ["skill-a", "skill-b"]
    with skill_isolation.skill_isolation_context(whitelist):
        assert skill_isolation._SKILL_ALLOWLIST.get() == whitelist

    # Exited context
    assert skill_isolation._SKILL_ALLOWLIST.get() is None


def test_patched_is_skill_disabled_behavior(monkeypatch):
    """Verify that _is_skill_disabled behaves as an allowlist when ContextVar is set,
    and defaults to original when None.
    """
    skill_isolation.patch_skills_isolation_system()
    import tools.skills_tool as skills_tool

    # Mock the original function stored on skill_isolation module
    def fake_is_disabled(name, platform=None):
        return name == "skill-x"
    monkeypatch.setattr(skill_isolation, "orig_is_disabled", fake_is_disabled)

    # 1. Without allowlist context (default)
    # skill-x is disabled (fake returns True)
    assert skills_tool._is_skill_disabled("skill-x") is True
    # skill-y is enabled (fake returns False)
    assert skills_tool._is_skill_disabled("skill-y") is False

    # 2. Within allowlist context
    whitelist = ["skill-y", "skill-z"]
    with skill_isolation.skill_isolation_context(whitelist):
        # skill-y is allowed (in whitelist) -> not disabled (returns False)
        assert skills_tool._is_skill_disabled("skill-y") is False
        # skill-x is not in whitelist -> disabled (returns True)
        assert skills_tool._is_skill_disabled("skill-x") is True
        # skill-z is allowed (in whitelist) -> not disabled (returns False)
        assert skills_tool._is_skill_disabled("skill-z") is False


def test_patched_get_disabled_skill_names_behavior(monkeypatch):
    """Verify that get_disabled_skill_names returns the complement of the whitelist."""
    skill_isolation.patch_skills_isolation_system()
    import agent.skill_utils as skill_utils

    # Mock get_external_skills_dirs and iter_skill_index_files to return a fake filesystem set of skills
    class FakePath:
        def __init__(self, name):
            self.parent = SimpleNamespace(name=name)
    
    from types import SimpleNamespace
    fake_files = [
        SimpleNamespace(parent=SimpleNamespace(name="skill-a")),
        SimpleNamespace(parent=SimpleNamespace(name="skill-b")),
        SimpleNamespace(parent=SimpleNamespace(name="skill-c")),
    ]
    monkeypatch.setattr(skill_utils, "iter_skill_index_files", lambda *a, **k: fake_files)
    monkeypatch.setattr(skill_utils, "get_external_skills_dirs", lambda *a, **k: [])
    # Mock original get_disabled_skill_names stored on skill_isolation module
    monkeypatch.setattr(skill_isolation, "orig_get_disabled", lambda *a, **k: set())

    # 1. Default (no allowlist)
    assert skill_utils.get_disabled_skill_names() == set()

    # 2. Allowlist set
    whitelist = ["skill-b"]
    with skill_isolation.skill_isolation_context(whitelist):
        disabled = skill_utils.get_disabled_skill_names()
        # All installed skills (skill-a, skill-b, skill-c) minus whitelist (skill-b) -> disabled (skill-a, skill-c)
        assert "skill-a" in disabled
        assert "skill-c" in disabled
        assert "skill-b" not in disabled