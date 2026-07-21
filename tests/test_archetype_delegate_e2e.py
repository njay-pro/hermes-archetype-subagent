"""Unit tests for archetype_delegate.py — Mimic architecture end-to-end delegation."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


class TestArchetypeDelegateMimic:
    """End-to-end tests for the Mimic archetype_delegate function."""

    def test_delegates_to_child_agent(
        self, delegate_module, router_module, fake_parent_agent
    ):
        mock_child = MagicMock()
        mock_child.run_conversation.return_value = {"final_response": "consultant response payload"}

        with patch.object(delegate_module, "_build_child_agent_mimic", return_value=mock_child) as mock_build:
            spec = router_module.get_archetype("long_horizon")
            result = delegate_module.archetype_delegate(
                spec=spec,
                brief="long horizon task",
                context="context info",
                toolsets=["terminal", "file", "web"],
                parent_agent=fake_parent_agent,
                role="leaf",
                background=False,
            )

            assert result == "consultant response payload"
            mock_build.assert_called_once_with(
                spec=spec,
                brief="long horizon task",
                toolsets=["terminal", "file", "web"],
                parent_agent=fake_parent_agent,
                model_override=None,
            )

    def test_delegates_with_model_override(
        self, delegate_module, router_module, fake_parent_agent
    ):
        mock_child = MagicMock()
        mock_child.run_conversation.return_value = {"final_response": "overridden response"}

        with patch.object(delegate_module, "_build_child_agent_mimic", return_value=mock_child) as mock_build:
            spec = router_module.get_archetype("consultant")
            override = {"provider": "openrouter", "model": "openai/gpt-5.6"}
            result = delegate_module.archetype_delegate(
                spec=spec,
                brief="override test",
                context=None,
                toolsets=["terminal", "file", "web"],
                parent_agent=fake_parent_agent,
                model_override=override,
            )

            assert result == "overridden response"
            mock_build.assert_called_once_with(
                spec=spec,
                brief="override test",
                toolsets=["terminal", "file", "web"],
                parent_agent=fake_parent_agent,
                model_override=override,
            )

    def test_raises_when_creds_cannot_be_resolved(
        self, delegate_module, router_module, fake_parent_agent
    ):
        with patch.object(delegate_module, "resolve_creds_for_spec", return_value={}):
            spec = router_module.get_archetype("consultant")

            with pytest.raises(RuntimeError, match="Could not resolve credentials"):
                delegate_module.archetype_delegate(
                    spec=spec,
                    brief="fail test",
                    context=None,
                    toolsets=["terminal", "file", "web"],
                    parent_agent=fake_parent_agent,
                )

    def test_background_mode_returns_future(
        self, delegate_module, router_module, fake_parent_agent
    ):
        mock_child = MagicMock()
        mock_child.run_conversation.return_value = {"final_response": "bg result"}

        with patch.object(delegate_module, "_build_child_agent_mimic", return_value=mock_child) as mock_build:
            spec = router_module.get_archetype("speedster_internal")
            future = delegate_module.archetype_delegate(
                spec=spec,
                brief="bg task",
                context=None,
                toolsets=["file"],
                parent_agent=fake_parent_agent,
                background=True,
            )

            assert hasattr(future, "result")
            res = future.result(timeout=5)
            assert res == {"final_response": "bg result"}