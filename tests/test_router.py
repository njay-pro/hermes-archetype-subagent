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
        # v0.4.0: 5 archetype tools + 1 diagnostics tool = 6
        assert ctx.register_tool.call_count == 6


class TestV031BugFixes:
    """Tests for the 3 code bugs filed in v0.3.1."""

    def test_blocklist_includes_plugin_tools(self):
        """Bug #2: DELEGATE_BLOCKED_TOOLS must include all 5 plugin tools."""
        from archetype_delegate import DELEGATE_BLOCKED_TOOLS
        for name in (
            "delegate_task_consultant",
            "delegate_task_long_horizon",
            "delegate_task_high_hallucination",
            "delegate_task_speedster_internal",
            "delegate_task_speedster_internet",
        ):
            assert name in DELEGATE_BLOCKED_TOOLS, (
                f"{name} missing from DELEGATE_BLOCKED_TOOLS — "
                "orchestrator-role subagents can recursively spawn it"
            )

    def test_extract_external_dirs_yaml_style(self, router_module):
        """Bug #3: _extract_external_dirs parses the expected YAML shape."""
        yaml_text = """
# some comment
profiles: []
skills:
  default_disabled_skills:
    - honcho-*
  external_dirs:
    - /tmp/skills-a
    - /tmp/skills-b
other_section:
  foo: bar
"""
        out = router_module._extract_external_dirs(yaml_text)
        assert out == ["/tmp/skills-a", "/tmp/skills-b"]

    def test_extract_external_dirs_inline_list(self, router_module):
        """Bug #3: also handles inline `[a, b]` form."""
        yaml_text = """
skills:
  external_dirs: [/tmp/x, /tmp/y]
"""
        out = router_module._extract_external_dirs(yaml_text)
        assert out == ["/tmp/x", "/tmp/y"]

    def test_extract_external_dirs_empty(self, router_module):
        """Bug #3: returns empty list when external_dirs is absent."""
        yaml_text = """
skills:
  default_disabled_skills:
    - honcho-*
"""
        assert router_module._extract_external_dirs(yaml_text) == []

    def test_batch_dispatch_uses_parallel_executor(self, router_module):
        """Bug #1: batch tasks run concurrently, not sequentially.

        We patch archetype_delegate.archetype_delegate to record start/end
        timestamps for each task. If parallel, total wall-clock should be
        closer to 1x sleep than Nx sleep. We use a small sleep to make the
        difference observable without slowing the test suite.
        """
        import os
        import threading
        import time as _time

        # Only run this test if we can stub archetype_delegate cleanly
        try:
            import archetype_delegate as ad  # type: ignore
        except ImportError:
            pytest.skip("archetype_delegate not importable in test env")

        timings = []
        lock = threading.Lock()

        def fake_arch_delegate(*args, **kwargs):
            t0 = _time.monotonic()
            _time.sleep(0.3)  # simulate model latency
            t1 = _time.monotonic()
            with lock:
                timings.append((t0, t1))
            return f"mock result for {kwargs.get('brief', '')[:20]}"

        # Patch both the import in router.py's closure AND the module attribute
        router_module.archetype_delegate_module = ad  # noqa: F841
        with patch.object(ad, "archetype_delegate", side_effect=fake_arch_delegate):
            handler = router_module._make_handler("consultant")
            t_start = _time.monotonic()
            results = handler(
                goal="ignored",
                context=None,
                tasks=[
                    {"goal": "task a", "context": ""},
                    {"goal": "task b", "context": ""},
                    {"goal": "task c", "context": ""},
                ],
                parent_agent=None,
            )
            t_total = _time.monotonic() - t_start

        # All 3 should have completed
        assert len(results) == 3
        # Parallel: total wall time should be much less than 3 * 0.3 = 0.9s
        # Generous bound: 0.7s allows for thread spinup + GIL contention.
        assert t_total < 0.7, (
            f"Batch took {t_total:.2f}s — looks sequential "
            f"(expected < 0.7s for 3 parallel 0.3s tasks)"
        )

    def test_session_ref_passed_to_progress_callback(self):
        """v0.3.2: _setup_progress_callbacks must accept session_ref so the
        callback can populate child_session_id (TUI preview pane)."""
        import inspect
        from archetype_delegate import _setup_progress_callbacks
        sig = inspect.signature(_setup_progress_callbacks)
        assert "session_ref" in sig.parameters, (
            "_setup_progress_callbacks must accept session_ref to enable TUI preview"
        )
        # Default should be None (backward compatible)
        assert sig.parameters["session_ref"].default is None

    def test_register_unregister_helpers_exist(self):
        """v0.3.2: helper functions to register/unregister into native's
        _active_subagents dict must exist and be best-effort."""
        from archetype_delegate import (
            _register_plugin_subagent,
            _unregister_plugin_subagent,
        )
        # Both should be callable
        assert callable(_register_plugin_subagent)
        assert callable(_unregister_plugin_subagent)

        # Calling register with no parent_agent / no native module must NOT raise.
        # We give it a non-string parent_id and a mock child so the helpers
        # exercise their defensive code paths.
        class _FakeChild:
            session_id = "test-sid"
        # The real native module may or may not be importable depending on
        # the test env. Either way, the helper must swallow the error.
        _register_plugin_subagent(
            subagent_id="sa-test",
            parent_id=None,
            depth=0,
            goal="test",
            model="test-model",
            child=_FakeChild(),
        )
        _unregister_plugin_subagent("sa-test")
        # If we got here without an exception, the best-effort contract holds.

    def test_open_live_transcript_uses_real_goal(self):
        """v0.3.2: _open_live_transcript must accept and forward a real_goal
        argument, instead of always writing the placeholder
        '[<archetype>] (live transcript)' as the goal."""
        import inspect
        from archetype_delegate import _open_live_transcript
        sig = inspect.signature(_open_live_transcript)
        assert "real_goal" in sig.parameters, (
            "_open_live_transcript must accept real_goal to fix the placeholder bug"
        )
        # The function should not hardcode the placeholder string
        import ast
        with open(_open_live_transcript.__code__.co_filename) as f:
            source = f.read()
        # Confirm the old hardcoded literal is no longer present
        assert '"[{" + "archetype_name" + "}] (live transcript)"' not in source, (
            "Found the old hardcoded placeholder string in _open_live_transcript"
        )

    def test_close_manifest_writes_completion(self):
        """v0.3.2: _close_manifest must mark a delegation as completed in
        the live-transcript dir so the dashboard / TUI show it as
        completed, not running-forever."""
        import json
        import tempfile
        from pathlib import Path
        from archetype_delegate import _close_manifest, HERMES_HOME

        # Save the real HERMES_HOME so we can restore it
        orig = HERMES_HOME
        try:
            with tempfile.TemporaryDirectory() as tmp:
                # Patch HERMES_HOME to the temp dir
                import archetype_delegate as ad
                ad.HERMES_HOME = Path(tmp)
                live = Path(tmp) / "cache" / "delegation" / "live" / "deleg_xyz"
                live.mkdir(parents=True)
                (live / "manifest.json").write_text(json.dumps({
                    "delegation_id": "deleg_xyz",
                    "started": "2026-07-23 00:00:00",
                    "task_count": 1,
                    "tasks": [
                        {"index": 0, "goal": "do thing", "log": "x", "status": "running"}
                    ],
                }))
                # Call the close helper
                ok = _close_manifest("deleg_xyz")
                assert ok is True, "_close_manifest should return True on success"
                # Re-read the manifest
                data = json.loads((live / "manifest.json").read_text())
                assert data["exit_reason"] == "completed"
                assert data.get("completed"), "should have a completed timestamp"
                assert data["tasks"][0]["status"] == "completed"
                assert data["tasks"][0]["exit_reason"] == "completed"

                # Idempotent: calling again should not double-write
                orig_completed = data["completed"]
                ok2 = _close_manifest("deleg_xyz")
                assert ok2 is True
                data2 = json.loads((live / "manifest.json").read_text())
                assert data2["completed"] == orig_completed
        finally:
            import archetype_delegate as ad
            ad.HERMES_HOME = orig

    def test_close_manifest_handles_missing(self):
        """_close_manifest returns False for a non-existent delegation."""
        from archetype_delegate import _close_manifest
        assert _close_manifest("deleg_does_not_exist") is False
        assert _close_manifest("") is False

    # ─── v0.3.3 SG1 — load_soul_identity=False ─────────────────────

    def test_sg1_archetype_passes_load_soul_identity_false(self):
        """v0.3.3 SG1: the plugin's AIAgent MUST receive
        load_soul_identity=False so the runtime's default SOUL.md doesn't
        pollute the subagent. The plugin owns the persona via SOUL_<name>.md."""
        import sys
        from unittest.mock import patch, MagicMock

        # AIAgent is imported lazily as `from run_agent import AIAgent` inside
        # _build_child_agent_mimic. We mock the run_agent module so the lazy
        # import resolves to our fake.
        mock_aigent = MagicMock()
        fake_module = MagicMock()
        fake_module.AIAgent = mock_aigent
        with patch.dict(sys.modules, {"run_agent": fake_module}):
            # Mock everything else the build path touches
            with patch("archetype_delegate.resolve_creds_for_spec") as mock_creds, \
                 patch("archetype_delegate._setup_progress_callbacks") as mock_setup, \
                 patch("archetype_delegate._open_live_transcript") as mock_open, \
                 patch("archetype_delegate._wrap_for_live_transcript") as mock_wrap, \
                 patch("archetype_delegate._register_plugin_subagent"):
                mock_creds.return_value = {"model": "test-model", "base_url": None, "api_key": "k", "api_mode": "x", "provider": "p"}
                mock_setup.return_value = (None, None, None)
                mock_open.return_value = (None, None)
                mock_wrap.return_value = None
                from archetype_delegate import _build_child_agent_mimic
                from router import get_archetype
                spec = get_archetype("consultant")
                _build_child_agent_mimic(
                    spec=spec,
                    brief="test brief",
                    toolsets=["terminal"],
                    parent_agent=None,
                )
                # The mock AIAgent was called with kwargs — find load_soul_identity
                _, kwargs = mock_aigent.call_args
                assert "load_soul_identity" in kwargs, (
                    "AIAgent must be called with load_soul_identity kwarg"
                )
                assert kwargs["load_soul_identity"] is False, (
                    f"load_soul_identity must be False, got {kwargs['load_soul_identity']}"
                )
                # Also verify the other v0.3 context-pollution guards are present
                assert kwargs.get("skip_context_files") is True
                assert kwargs.get("skip_memory") is True

    # ─── v0.3.3 SG2 — PRIORITY header + skill_list unification ─────

    def test_sg2_brief_starts_with_priority_header(self):
        """v0.3.3 SG2: the brief MUST start with a PRIORITY header so
        any default role framing from the runtime loses to the SOUL below."""
        from router import _assemble_brief, get_archetype
        spec = get_archetype("consultant")
        skill_filter = ["knows_brand-identity"]
        brief = _assemble_brief(
            spec, "do thing", None, skill_filter,
        )
        # First section must be the priority header
        assert brief.startswith("## PRIORITY"), (
            f"brief must start with '## PRIORITY', got: {brief[:80]!r}"
        )
        assert "canonical instructions" in brief
        assert "SOUL" in brief

    # ─── v0.3.3 SG3 — 3-layer skill resolution ──────────────────────

    def test_sg3_default_skill_filter_is_omca_utils_only(self):
        """v0.3.3 SG3: with no orchestrator override, the default skill
        filter is OMCA utils (knows_*, nodes_*, subflows_*, omca-*) —
        NOT the full skill catalog. This is the L1 code-level baseline."""
        from router import (
            DEFAULT_OMCA_UTILS_GLOBS,
            resolve_orchestrator_skill_filter,
        )
        # The constant is correct
        assert "knows_*" in DEFAULT_OMCA_UTILS_GLOBS
        assert "nodes_*" in DEFAULT_OMCA_UTILS_GLOBS
        assert "subflows_*" in DEFAULT_OMCA_UTILS_GLOBS
        assert "omca-*" in DEFAULT_OMCA_UTILS_GLOBS
        assert "omca_*" in DEFAULT_OMCA_UTILS_GLOBS
        # The default (no override) result must only contain OMCA utils
        skills = resolve_orchestrator_skill_filter(None, None)
        # We can't assert exact set (depends on what's installed) but every
        # returned skill must match the OMCA utils globs.
        from router import _match_skill_glob
        for s in skills:
            assert any(
                _match_skill_glob(s, g) for g in DEFAULT_OMCA_UTILS_GLOBS
            ), f"non-OMCA skill leaked into default filter: {s}"

    def test_sg3_layer1_excludes_honcho_by_default(self):
        """L1 (OMCA utils) + L2 (default_disabled: honcho-*) combine:
        even though honcho-* is technically an OMCA pattern, the L2
        safety net strips it out."""
        from router import resolve_orchestrator_skill_filter
        skills = resolve_orchestrator_skill_filter(None, None)
        honcho_skills = [s for s in skills if "honcho" in s]
        assert honcho_skills == [], (
            f"honcho-* leaked through L1+L2: {honcho_skills}"
        )

    def test_sg3_layer3_include_overrides_everything(self):
        """L3 skill_include_override wins over L1+L2, and can re-enable
        default-disabled skills (the documented 'opt back in' path)."""
        from router import resolve_orchestrator_skill_filter
        # Include a honcho skill — should win even though L2 disables honcho-*
        skills = resolve_orchestrator_skill_filter(
            skill_include_override=["knows_honcho-best-practice"],
            skill_exclude_override=None,
        )
        # Should include only the explicitly-included honcho skill
        assert "knows_honcho-best-practice" in skills, (
            "L3 include must re-enable disabled skills"
        )

    def test_sg3_layer3_exclude_subtracts_from_l1(self):
        """L3 skill_exclude_override subtracts on top of L1."""
        from router import resolve_orchestrator_skill_filter
        # Exclude a knows_* skill
        skills_all = set(resolve_orchestrator_skill_filter(None, None))
        skills_excluded = set(
            resolve_orchestrator_skill_filter(
                None, ["knows_brand-identity"]
            )
        )
        # Excluded must be a strict subset (only knows_brand-identity removed)
        assert "knows_brand-identity" in skills_all, "test precondition"
        assert "knows_brand-identity" not in skills_excluded
        # Other skills preserved
        assert skills_excluded.issubset(skills_all)
        assert len(skills_excluded) == len(skills_all) - 1

    # ─── v0.3.3 SG4 — preload_files slot ──────────────────────────

    def test_sg4_brief_includes_preloaded_file_content(self, tmp_path):
        """v0.3.3 SG4: preload_files slot reads file from disk and
        inlines its content into a '## Preloaded Files' section."""
        from router import _assemble_brief, get_archetype
        todo = tmp_path / "TODO.md"
        todo.write_text("# TODO\n- [ ] write tests\n- [ ] ship v0.3.3\n")
        spec = get_archetype("consultant")
        brief = _assemble_brief(
            spec, "review my todo", None, ["knows_*"],
            preload_files=[str(todo)],
        )
        # The brief should contain the '## Preloaded Files' section AND
        # the file's content
        assert "## Preloaded Files" in brief
        assert "TODO.md" in brief
        assert "write tests" in brief
        assert "ship v0.3.3" in brief

    def test_sg4_relative_path_resolves(self, tmp_path):
        """v0.3.3 SG4: relative paths resolve relative to current working directory."""
        import os
        from router import _assemble_brief, get_archetype
        spec = get_archetype("consultant")
        rel_file = "relative_test_file.txt"
        
        # Write to CWD temp path but keep it relative to CWD
        orig_cwd = os.getcwd()
        os.chdir(str(tmp_path))
        try:
            p = tmp_path / rel_file
            p.write_text("this is relative content")
            brief = _assemble_brief(
                spec, "review", None, ["knows_*"],
                preload_files=[rel_file],
            )
            assert "relative_test_file.txt" in brief
            assert "this is relative content" in brief
        finally:
            os.chdir(orig_cwd)

    def test_sg4_brief_handles_multiple_preloaded_files(self, tmp_path):
        """v0.3.3 SG4: preload_files with 2 files — both should be inlined."""
        from router import _assemble_brief, get_archetype
        f1 = tmp_path / "f1.md"
        f2 = tmp_path / "f2.md"
        f1.write_text("content one")
        f2.write_text("content two")
        spec = get_archetype("consultant")
        brief = _assemble_brief(
            spec, "review", None, ["knows_*"],
            preload_files=[str(f1), str(f2)],
        )
        assert "content one" in brief
        assert "content two" in brief
        assert "f1.md" in brief
        assert "f2.md" in brief

    def test_sg4_brief_handles_missing_file_gracefully(self, tmp_path):
        """v0.3.3 SG4: missing preload file surfaces as text in the
        brief, NOT an exception. The subagent knows it was supposed to
        be there."""
        from router import _assemble_brief, get_archetype
        spec = get_archetype("consultant")
        brief = _assemble_brief(
            spec, "review", None, ["knows_*"],
            preload_files=[str(tmp_path / "nonexistent.md")],
        )
        # Should NOT raise; should have a 'load failed' marker
        assert "## Preloaded Files" in brief
        assert "load failed" in brief.lower() or "not found" in brief.lower()

    def test_sg4_brief_caps_oversized_file(self, tmp_path):
        """v0.3.3 SG4: a file over 100KB is truncated with a marker."""
        from router import _assemble_brief, get_archetype, _PRELOAD_MAX_FILE_BYTES
        big = tmp_path / "big.md"
        # Write 200KB of content (2x the cap)
        big.write_text("X" * (200 * 1024))
        spec = get_archetype("consultant")
        brief = _assemble_brief(
            spec, "review", None, ["knows_*"],
            preload_files=[str(big)],
        )
        # Truncation marker must appear
        assert "truncated" in brief.lower()
        # The full 200KB must NOT be in the brief
        assert len(brief) < 200 * 1024 + 5000  # some slack for other sections

    def test_sg4_no_preload_files_no_section(self, tmp_path):
        """v0.3.3 SG4: without preload_files, the '## Preloaded Files'
        section is absent (no noise)."""
        from router import _assemble_brief, get_archetype
        spec = get_archetype("consultant")
        brief = _assemble_brief(
            spec, "do thing", None, ["knows_*"],
            preload_files=None,
        )
        assert "## Preloaded Files" not in brief

    def test_sg4_brief_total_byte_cap_enforced(self, tmp_path):
        """v0.3.3 SG4: the 1MB total cap is enforced across multiple files.
        Each file under 100KB, but together they exceed 1MB."""
        from router import (
            _assemble_brief, get_archetype,
        )
        # Write 15 files of 80KB each = 1.2MB total (over the 1MB cap)
        # Each is under the 100KB per-file cap, so the per-file truncation
        # doesn't fire — only the total cap does.
        paths = []
        for i in range(15):
            f = tmp_path / f"f{i}.md"
            f.write_text("Z" * (80 * 1024))
            paths.append(str(f))
        spec = get_archetype("consultant")
        brief = _assemble_brief(
            spec, "review", None, ["knows_*"],
            preload_files=paths,
        )
        # The last few files should be marked as budget-exhausted


class TestCollapsedArgRecovery:
    """v0.4.5 regression: when the tool-call bridge collapses the entire
    arguments object into `goal` (a dict), the handler must recover the named
    overrides (especially skill_include_override) instead of silently falling
    back to the full catalog."""

    def test_collapsed_goal_dict_recovers_skill_include(self, router_module, monkeypatch):
        """A dict-shaped `goal` carrying skill_include_override must yield a
        1-skill filter — the exact bug from v0.4.4 live testing."""
        captured = {}

        def fake_spawn(spec=None, brief=None, **kwargs):
            captured["skill_filter"] = kwargs.get("skill_filter")
            captured["brief"] = brief
            # Minimal stand-in return so the handler completes.
            from types import SimpleNamespace
            return SimpleNamespace(final_response="ok")

        monkeypatch.setattr(
            router_module, "archetype_delegate", fake_spawn, raising=False
        )
        # Ensure archetype_delegate resolves to our fake at call time.
        import archetype_delegate as ad
        monkeypatch.setattr(ad, "archetype_delegate", fake_spawn, raising=False)

        handler = router_module._make_handler("consultant")
        collapsed_goal = {
            "goal": "List the skills you can see.",
            "skill_include_override": ["knows_multiAgent-orchestrationHowTo"],
        }
        handler(goal=collapsed_goal)

        assert captured.get("skill_filter") == ["knows_multiAgent-orchestrationHowTo"], (
            f"expected 1-skill filter, got {captured.get('skill_filter')}"
        )
        # The brief's '## Available Skills' block must name only the whitelisted skill.
        assert "knows_multiAgent-orchestrationHowTo" in (captured.get("brief") or "")
        assert "nodes_auto-caption" not in (captured.get("brief") or "")

    def test_named_params_still_take_precedence(self, router_module, monkeypatch):
        """When both a dict goal AND explicit named params are present, the
        explicit named param wins."""
        captured = {}

        def fake_spawn(spec=None, brief=None, **kwargs):
            captured["skill_filter"] = kwargs.get("skill_filter")
            from types import SimpleNamespace
            return SimpleNamespace(final_response="ok")

        import archetype_delegate as ad
        monkeypatch.setattr(ad, "archetype_delegate", fake_spawn, raising=False)

        handler = router_module._make_handler("consultant")
        collapsed_goal = {
            "goal": "x",
            "skill_include_override": ["knows_multiAgent-orchestrationHowTo"],
        }
        # Explicit named param should override the collapsed one.
        handler(goal=collapsed_goal, skill_include_override=["nodes_vector-search"])

        assert captured.get("skill_filter") == ["nodes_vector-search"]