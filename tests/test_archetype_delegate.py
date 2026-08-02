"""Unit tests for archetype_delegate.py — Mimic subagent execution and credential resolution."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


# ── resolve_creds_for_spec ─────────────────────────────────────────────


class TestResolveCredsForSpec:
    """Resolves spec.provider + spec.model to a credential bundle."""

    def test_resolves_9router_combo(self, delegate_module, router_module):
        spec = router_module.get_archetype("consultant")
        creds = delegate_module.resolve_creds_for_spec(spec, _strict_runtime=False)
        assert creds["model"] == "arc-consultant1"
        assert creds["provider"] == "custom:9router"

    def test_all_5_archetypes_resolve(self, delegate_module, router_module):
        expected = {
            "consultant": "arc-consultant1",
            "long_horizon": "arc-longHorizon1",
            "high_hallucination": "arc-highHallucination1",
            "speedster_internal": "arc-speedster1",
            "speedster_internet": "arc-speedster1",
        }
        for name, expected_model in expected.items():
            spec = router_module.get_archetype(name)
            creds = delegate_module.resolve_creds_for_spec(spec, _strict_runtime=False)
            assert creds["model"] == expected_model, f"{name}: got {creds['model']}"

    def test_model_override_wins(self, delegate_module, router_module):
        spec = router_module.get_archetype("consultant")
        override = {"provider": "openrouter", "model": "openai/gpt-5.6"}
        creds = delegate_module.resolve_creds_for_spec(spec, model_override=override, _strict_runtime=False)
        assert creds["model"] == "openai/gpt-5.6"
        assert creds["provider"] == "openrouter"

    def test_model_override_partial(self, delegate_module, router_module):
        """Override only the model; provider stays from spec."""
        spec = router_module.get_archetype("consultant")
        override = {"model": "different-model"}  # no provider
        creds = delegate_module.resolve_creds_for_spec(spec, model_override=override, _strict_runtime=False)
        assert creds["model"] == "different-model"
        assert creds["provider"] == "custom:9router", "should fall back to spec.provider"

    def test_unknown_provider_falls_back_to_bare(self, delegate_module, router_module):
        spec = router_module.get_archetype("consultant")
        override = {"provider": "non-existent-provider", "model": "x"}
        creds = delegate_module.resolve_creds_for_spec(spec, model_override=override, _strict_runtime=False)
        assert creds["model"] == "x"
        assert creds["provider"] == "non-existent-provider"


# ── _build_child_agent_mimic & archetype_delegate ──────────────────────


class TestMimicDelegation:
    """Verifies that archetype_delegate constructs and executes AIAgent in-memory."""

    def test_archetype_delegate_calls_run_conversation(
        self, delegate_module, router_module, fake_parent_agent
    ):
        mock_child = MagicMock()
        mock_child.run_conversation.return_value = {"final_response": "consultant response payload"}

        with patch.object(delegate_module, "_build_child_agent_mimic", return_value=mock_child) as mock_build:
            spec = router_module.get_archetype("consultant")
            res = delegate_module.archetype_delegate(
                spec=spec,
                brief="Analyze Q3 Dip",
                context="Sales Dip data",
                toolsets=["terminal", "file", "web"],
                parent_agent=fake_parent_agent,
            )

            assert res == "consultant response payload"
            mock_build.assert_called_once()
            mock_child.run_conversation.assert_called_once()
            assert mock_child.run_conversation.call_args.kwargs["user_message"] == "Analyze Q3 Dip"

    def test_strip_blocked_tools(self, delegate_module):
        clean = delegate_module._strip_blocked_tools(["terminal", "file", "delegate_task", "clarify"])
        assert clean == ["terminal", "file"]
        assert "delegate_task" not in clean
        assert "clarify" not in clean