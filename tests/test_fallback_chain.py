"""Tests for v0.4.0 fallback_chain in resolve_creds_for_spec."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

import archetype_delegate
import router


def _spec_with_fallback(primary_provider, primary_model, fallback_chain):
    return SimpleNamespace(
        name="consultant",
        provider=primary_provider,
        model=primary_model,
        fallback_chain=fallback_chain,
    )


def test_fallback_when_primary_fails(monkeypatch):
    """Primary fails -> first fallback_chain entry wins."""
    calls = []
    def fake_resolve(requested=None, target_model=None, **_):
        calls.append((requested, target_model))
        if requested == "9router":
            raise ConnectionError("9router down")
        return {"provider": requested, "model": target_model,
                "base_url": "http://x", "api_key": "k", "api_mode": "chat"}
    monkeypatch.setattr("hermes_cli.runtime_provider.resolve_runtime_provider", fake_resolve)

    spec = _spec_with_fallback(
        primary_provider="custom:9router",
        primary_model="arc-consultant1",
        fallback_chain=[{"provider": "anthropic", "model": "claude-sonnet-4-6"}],
    )
    bundle = archetype_delegate.resolve_creds_for_spec(spec, _strict_runtime=True)
    assert bundle["provider"] == "anthropic"
    assert bundle["model"] == "claude-sonnet-4-6"
    assert calls == [("9router", "arc-consultant1"), ("anthropic", "claude-sonnet-4-6")]


def test_fallback_walks_multiple_entries(monkeypatch):
    """Primary fails -> first entry fails -> second entry wins."""
    def fake_resolve(requested=None, target_model=None, **_):
        if requested in ("9router", "anthropic"):
            raise ConnectionError(f"{requested} down")
        return {"provider": requested, "model": target_model,
                "base_url": "http://x", "api_key": "k", "api_mode": "chat"}
    monkeypatch.setattr("hermes_cli.runtime_provider.resolve_runtime_provider", fake_resolve)

    spec = _spec_with_fallback(
        primary_provider="custom:9router",
        primary_model="arc-consultant1",
        fallback_chain=[
            {"provider": "anthropic", "model": "claude-sonnet-4-6"},
            {"provider": "minimax", "model": "MiniMax-M3"},
        ],
    )
    bundle = archetype_delegate.resolve_creds_for_spec(spec, _strict_runtime=True)
    assert bundle["provider"] == "minimax"
    assert bundle["model"] == "MiniMax-M3"


def test_fallback_all_fail_returns_empty_bundle(monkeypatch):
    def fake_resolve(requested=None, **_):
        raise ConnectionError(f"{requested} down")
    monkeypatch.setattr("hermes_cli.runtime_provider.resolve_runtime_provider", fake_resolve)

    spec = _spec_with_fallback(
        primary_provider="custom:9router",
        primary_model="arc-consultant1",
        fallback_chain=[{"provider": "anthropic", "model": "x"}],
    )
    bundle = archetype_delegate.resolve_creds_for_spec(spec, _strict_runtime=True)
    assert bundle["base_url"] is None
    assert bundle["api_key"] is None


def test_no_fallback_returns_primary(monkeypatch):
    """Primary works -> no fallback entries tried."""
    calls = []
    def fake_resolve(requested=None, target_model=None, **_):
        calls.append((requested, target_model))
        return {"provider": "9router", "model": target_model,
                "base_url": "http://x", "api_key": "k", "api_mode": "chat"}
    monkeypatch.setattr("hermes_cli.runtime_provider.resolve_runtime_provider", fake_resolve)

    spec = _spec_with_fallback(
        primary_provider="custom:9router",
        primary_model="arc-consultant1",
        fallback_chain=[{"provider": "anthropic", "model": "x"}],
    )
    bundle = archetype_delegate.resolve_creds_for_spec(spec, _strict_runtime=True)
    assert bundle["provider"] == "custom:9router"
    assert calls == [("9router", "arc-consultant1")]


def test_spec_loads_fallback_chain_from_json():
    """Smoke: load real config and verify fallback_chain lands in spec."""
    specs = router.load_archetypes(force_reload=True)
    consultant = specs["consultant"]
    assert hasattr(consultant, "fallback_chain")
    assert len(consultant.fallback_chain) >= 1
    for entry in consultant.fallback_chain:
        assert "provider" in entry
        assert "model" in entry


def test_model_override_preserves_fallback_chain():
    """apply_model_override must keep spec.fallback_chain intact."""
    specs = router.load_archetypes(force_reload=True)
    consultant = specs["consultant"]
    original_chain = consultant.fallback_chain
    overridden = router.apply_model_override(
        consultant,
        {"provider": "anthropic", "model": "claude-sonnet-4-6"},
    )
    assert overridden.fallback_chain == original_chain