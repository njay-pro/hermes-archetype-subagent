"""Unit tests for router.py — archetype loading, skill filtering, and briefing assembly."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


class TestRouterConfigLoading:
    def test_list_archetypes(self, router_module):
        names = router_module.list_archetypes()
        assert "consultant" in names
        assert "long_horizon" in names
        assert "high_hallucination" in names
        assert "speedster_internal" in names
        assert "speedster_internet" in names

    def test_get_archetype_valid(self, router_module):
        spec = router_module.get_archetype("consultant")
        assert spec.name == "consultant"
        assert spec.provider == "custom:9router"
        assert spec.model == "arc-consultant1"
        assert spec.default_toolsets == ["terminal", "file", "web"]
        assert spec.max_iterations == 50

    def test_get_archetype_unknown_raises(self, router_module):
        with pytest.raises(KeyError, match="Unknown archetype"):
            router_module.get_archetype("unknown_nonexistent")

    def test_get_default_disabled_skills(self, router_module):
        disabled = router_module.get_default_disabled_skills()
        assert "honcho-*" in disabled

    def test_describe_config_split(self, router_module):
        info = router_module.describe_config_split()
        assert "model_config" in info
        assert "schema_config" in info


class TestSkillMatching:
    def test_exact_fnmatch(self, router_module):
        assert router_module._match_skill_glob("knows_honcho-best-practice", "knows_*") is True
        assert router_module._match_skill_glob("other_skill", "knows_*") is False

    def test_prefix_stripped_matching(self, router_module):
        assert router_module._match_skill_glob("knows_honcho-best-practice", "honcho-*") is True
        assert router_module._match_skill_glob("omca_honcho-best-practice", "honcho-*") is True

    def test_resolve_orchestrator_skill_filter_default(self, router_module):
        roots = [router_module.PLUGIN_DIR]
        # When neither override is set, default_disabled_skills (honcho-*) are removed
        res = router_module.resolve_orchestrator_skill_filter(
            skill_include_override=None,
            skill_exclude_override=None,
            roots=roots,
        )
        assert isinstance(res, list)

    def test_resolve_orchestrator_skill_filter_whitelist(self, router_module):
        roots = [router_module.PLUGIN_DIR]
        res = router_module.resolve_orchestrator_skill_filter(
            skill_include_override=["knows_*"],
            skill_exclude_override=None,
            roots=roots,
        )
        assert isinstance(res, list)


class TestBriefingAssembly:
    def test_assemble_brief_includes_soul_and_goal(self, router_module):
        spec = router_module.get_archetype("consultant")
        brief = router_module._assemble_brief(
            spec=spec,
            goal="Analyze Dip",
            context="Sales data",
            skill_filter=["knows_test"],
        )
        assert "Goal (from orchestrator)" in brief
        assert "Analyze Dip" in brief
        assert "Context (from orchestrator)" in brief
        assert "Sales data" in brief
        assert "`knows_test`" in brief
        assert "Active Model" in brief

    def test_assemble_brief_includes_output_schema(self, router_module):
        spec = router_module.get_archetype("high_hallucination")
        brief = router_module._assemble_brief(
            spec=spec,
            goal="Brainstorm",
            context=None,
            skill_filter=[],
        )
        assert "Required Output Schema" in brief
        assert "creative_perspectives" in brief


class TestModelOverride:
    def test_apply_model_override(self, router_module):
        spec = router_module.get_archetype("consultant")
        override = {"provider": "openrouter", "model": "openai/gpt-5.6"}
        overridden = router_module.apply_model_override(spec, override)
        assert overridden.provider == "openrouter"
        assert overridden.model == "openai/gpt-5.6"
        assert overridden.name == "consultant"

    def test_apply_model_override_none_returns_original(self, router_module):
        spec = router_module.get_archetype("consultant")
        assert router_module.apply_model_override(spec, None) is spec


class TestToolRegistration:
    def test_build_all(self, router_module):
        tools = router_module._build_all()
        assert "delegate_task_consultant" in tools
        assert "delegate_task_long_horizon" in tools
        assert "delegate_task_high_hallucination" in tools
        assert "delegate_task_speedster_internal" in tools
        assert "delegate_task_speedster_internet" in tools

    def test_register(self, router_module):
        ctx = MagicMock()
        router_module.register(ctx)
        assert ctx.register_tool.call_count == 5