"""v0.3.4 — Tests for profile-aware Hermes home resolution.

Before v0.3.4, the plugin read `HERMES_HOME` at module import and cached
the value. It ignored `HERMES_PROFILE` entirely. Subagents spawned in
non-root profiles (e.g. `ana-board`) wrote their live-transcript cache to
the root `~/.hermes/cache/delegation/live/...` instead of the
profile-scoped `~/.hermes/profiles/ana-board/cache/delegation/live/...`,
causing transcript collisions when two profiles delegated concurrently.

These tests cover the four resolution paths of `_hermes_home()`:

  1. `HERMES_HOME` env wins when set (explicit override wins).
  2. `HERMES_PROFILE` env → `~/.hermes/profiles/<name>` (the fix).
  3. Neither set → platform default (legacy behaviour).
  4. The module-level `HERMES_HOME` symbol is set on import and is a Path.
"""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from typing import Any

import pytest

PLUGIN_DIR = Path(__file__).resolve().parent.parent


def _load_delegate() -> Any:
    """Load archetype_delegate on demand so env vars settled in the test
    are honoured by the module-load path."""
    spec = importlib.util.spec_from_file_location(
        "archetype_delegate_profile_test",
        PLUGIN_DIR / "archetype_delegate.py",
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def delegate():
    """Reload the plugin module with current env (does not mutate env)."""
    return _load_delegate()


@pytest.fixture
def clean_env(monkeypatch):
    """Strip both HERMES_HOME and HERMES_PROFILE before each test."""
    monkeypatch.delenv("HERMES_HOME", raising=False)
    monkeypatch.delenv("HERMES_PROFILE", raising=False)


class TestResolveHermesHome:
    """The four resolution paths of `_hermes_home()`."""

    def test_hermes_home_env_wins_when_set(self, delegate, monkeypatch):
        """Explicit HERMES_HOME always wins (subprocess set it for us)."""
        monkeypatch.setenv("HERMES_HOME", "/tmp/custom-home")
        assert delegate._hermes_home() == Path("/tmp/custom-home")

    def test_hermes_profile_falls_back_to_profile_dir(self, delegate, monkeypatch, clean_env):
        """HERMES_PROFILE alone → ~/.hermes/profiles/<name>."""
        monkeypatch.setenv("HERMES_PROFILE", "ana-board")
        home = delegate._hermes_home()
        assert home == Path.home() / ".hermes" / "profiles" / "ana-board"

    def test_no_env_returns_platform_default(self, delegate, clean_env):
        """No env at all → ~/.hermes."""
        home = delegate._hermes_home()
        # On macOS the platform default is ~/.hermes; on Windows it's %LOCALAPPDATA%/hermes
        if sys.platform == "win32":
            local = os.environ.get("LOCALAPPDATA", "").strip()
            expected = Path(local) / "hermes" if local else Path.home() / "AppData" / "Local" / "hermes"
            assert home == expected
        else:
            assert home == Path.home() / ".hermes"

    def test_hermes_home_takes_priority_over_profile(self, delegate, monkeypatch):
        """When both are set, HERMES_HOME wins (it might already be profile-scoped)."""
        monkeypatch.setenv("HERMES_HOME", "/some/already-scoped/path")
        monkeypatch.setenv("HERMES_PROFILE", "ana-board")
        assert delegate._hermes_home() == Path("/some/already-scoped/path")


class TestModuleLevelHermesHome:
    """The `HERMES_HOME` module symbol must be a Path on import."""

    def test_hermes_home_is_path_on_import(self, delegate):
        assert isinstance(delegate.HERMES_HOME, Path)

    def test_hermes_home_is_existing_directory(self, delegate):
        """The resolved home should land on a real dir (or ~/.hermes)."""
        assert delegate.HERMES_HOME.is_dir() or str(delegate.HERMES_HOME) == str(Path.home() / ".hermes")


class TestManifestPathUsesProfileHome:
    """The cache-path used by `_close_manifest` must follow the resolved home."""

    def test_manifest_path_uses_hermes_home(self, delegate, monkeypatch):
        """When HERMES_HOME points to a temp dir, the manifest path follows it."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            monkeypatch.setenv("HERMES_HOME", tmp)
            monkeypatch.setenv("HERMES_PROFILE", "")
            resolved = delegate._hermes_home()
            manifest_path = (
                resolved / "cache" / "delegation" / "live" / "deleg_xyz" / "manifest.json"
            )
            # Manifest lives under the configured HERMES_HOME
            assert manifest_path.parent.parent.parent.parent.parent == Path(tmp)
            assert manifest_path.parent.parent.parent.parent == Path(tmp) / "cache"

    def test_workspace_artifact_path_is_profile_aware(self, delegate, monkeypatch):
        """If HERMES_PROFILE is set, the cache path lands under profiles/<name>."""
        monkeypatch.setenv("HERMES_PROFILE", "ana-board")
        monkeypatch.delenv("HERMES_HOME", raising=False)
        resolved = delegate._hermes_home()
        cache_dir = resolved / "cache" / "delegation" / "live"
        assert cache_dir != Path.home() / ".hermes" / "cache" / "delegation" / "live"
        assert cache_dir == Path.home() / ".hermes" / "profiles" / "ana-board" / "cache" / "delegation" / "live"


class TestBackwardsCompatibility:
    """The module-level HERMES_HOME symbol must remain monkey-patchable for
    the existing v0.3.2 test suite (test_router.py patches it directly)."""

    def test_module_hermes_home_is_mutable(self, delegate):
        """Existing tests do `ad.HERMES_HOME = Path(tmp)` — must still work."""
        delegate.HERMES_HOME = Path("/tmp/replaced")
        assert delegate.HERMES_HOME == Path("/tmp/replaced")
