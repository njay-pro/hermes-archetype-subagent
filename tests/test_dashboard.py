"""Tests for dashboard.py — stdlib subagent preview pane.

Covers the log line parser, manifest loader, and the HTTP routes.
Uses Python's stdlib `unittest` so we don't need pytest as a runtime dep
(the plugin's pyproject already requires pytest, so this is belt-and-suspenders).
"""
from __future__ import annotations

import json
import sys
import tempfile
import threading
import time
import unittest
from http.client import HTTPConnection
from pathlib import Path

# Ensure the plugin dir is on sys.path so `import dashboard` works.
PLUGIN_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN_DIR))

import dashboard  # noqa: E402


# ─── log line parser ─────────────────────────────────────────────────────

class TestParseLogLine(unittest.TestCase):
    def test_standard_line(self):
        ev = dashboard.parse_log_line("16:35:16 think    | Native delegate is alive.")
        assert ev is not None
        self.assertEqual(ev.timestamp, "16:35:16")
        self.assertEqual(ev.kind, "think")
        self.assertEqual(ev.text, "Native delegate is alive.")

    def test_final_line(self):
        ev = dashboard.parse_log_line(
            "16:35:16 final    | status=completed duration=11.85s summary: Done."
        )
        assert ev is not None
        self.assertEqual(ev.kind, "final")
        self.assertIn("status=completed", ev.text)
        self.assertIn("duration=11.85s", ev.text)

    def test_header_line_returns_none(self):
        # Lines like "=== Hermes subagent live transcript ===" don't match.
        self.assertIsNone(dashboard.parse_log_line("=== Hermes subagent live transcript ==="))

    def test_blank_line_returns_none(self):
        self.assertIsNone(dashboard.parse_log_line(""))
        self.assertIsNone(dashboard.parse_log_line("   "))

    def test_kickoff_line(self):
        ev = dashboard.parse_log_line("19:29:30 user     | kickoff: hello world")
        assert ev is not None
        self.assertEqual(ev.kind, "user")
        self.assertEqual(ev.text, "kickoff: hello world")


# ─── manifest loader ─────────────────────────────────────────────────────

class TestLoadManifest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.tmp_path = Path(self.tmp.name)

    def _write_manifest(self, d: Path, manifest: dict, log_content: str = ""):
        d.mkdir(parents=True, exist_ok=True)
        (d / "manifest.json").write_text(json.dumps(manifest))
        if log_content:
            (d / "task-0.log").write_text(log_content)

    def test_basic_manifest(self):
        d = self.tmp_path / "deleg_abc"
        self._write_manifest(d, {
            "delegation_id": "deleg_abc",
            "started": "2026-07-23 12:00:00",
            "task_count": 1,
            "tasks": [
                {"index": 0, "goal": "do thing", "log": str(d / "task-0.log"), "status": "running"}
            ],
        })
        result = dashboard.load_manifest(d)
        assert result is not None
        self.assertEqual(result.id, "deleg_abc")
        self.assertEqual(result.started_at, "2026-07-23 12:00:00")
        self.assertEqual(result.status, "running")
        self.assertEqual(len(result.tasks), 1)
        self.assertEqual(result.tasks[0].goal, "do thing")

    def test_completed_status_overall(self):
        d = self.tmp_path / "deleg_done"
        self._write_manifest(d, {
            "delegation_id": "deleg_done",
            "started": "2026-07-23 12:00:00",
            "task_count": 1,
            "completed": "2026-07-23 12:00:11",
            "exit_reason": "completed",
            "tasks": [
                {"index": 0, "goal": "x", "log": str(d / "task-0.log"), "status": "completed"}
            ],
        })
        result = dashboard.load_manifest(d)
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.completed_at, "2026-07-23 12:00:11")
        self.assertEqual(result.exit_reason, "completed")

    def test_missing_manifest(self):
        d = self.tmp_path / "deleg_orphan"
        d.mkdir()
        self.assertIsNone(dashboard.load_manifest(d))

    def test_malformed_manifest(self):
        d = self.tmp_path / "deleg_broken"
        d.mkdir()
        (d / "manifest.json").write_text("{not json")
        self.assertIsNone(dashboard.load_manifest(d))


# ─── incremental log reading ─────────────────────────────────────────────

class TestReadNewEvents(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.tmp_path = Path(self.tmp.name)
        self.log_path = self.tmp_path / "task-0.log"
        self.log_path.write_text(
            "=== header line 1 ===\n"
            "=== header line 2 ===\n"
            "16:35:04 user     | kickoff: test\n"
            "16:35:16 final    | status=completed\n"
        )
        self.task = dashboard.Task(
            index=0, goal="x", log_path=self.log_path, status="running"
        )

    def test_first_read_picks_up_all_events(self):
        n = dashboard.read_new_events(self.task)
        self.assertEqual(n, 2)  # 2 valid events (user, final)
        self.assertEqual(len(self.task.events), 2)
        self.assertEqual(self.task.events[0].kind, "user")
        self.assertEqual(self.task.events[1].kind, "final")

    def test_second_read_is_noop(self):
        dashboard.read_new_events(self.task)
        n = dashboard.read_new_events(self.task)
        self.assertEqual(n, 0)

    def test_third_read_picks_up_new_lines(self):
        dashboard.read_new_events(self.task)
        with self.log_path.open("a") as fh:
            fh.write("16:36:00 think    | A new thought.\n")
        n = dashboard.read_new_events(self.task)
        self.assertEqual(n, 1)
        self.assertEqual(self.task.events[-1].text, "A new thought.")

    def test_multiline_continuation(self):
        log_path = self.tmp_path / "task-multi.log"
        log_path.write_text(
            "=== header ===\n"
            "10:00:00 think    | First line of thinking\n"
            "Second line of thinking\n"
            "Third line of thinking\n"
        )
        task = dashboard.Task(index=0, goal="x", log_path=log_path, status="running")
        n = dashboard.read_new_events(task)
        self.assertEqual(n, 1)
        self.assertIn("First line of thinking", task.events[0].text)
        self.assertIn("Second line of thinking", task.events[0].text)
        self.assertIn("Third line of thinking", task.events[0].text)



# ─── HTTP smoke test ─────────────────────────────────────────────────────

class TestHTTPServer(unittest.TestCase):
    """Spin up the dashboard on a random port, hit endpoints, tear down."""

    @classmethod
    def setUpClass(cls):
        # Isolated LIVE_DIR so we don't read the user's real delegations
        cls.tmp = tempfile.TemporaryDirectory()
        cls.live_dir = Path(cls.tmp.name) / "live"
        cls.live_dir.mkdir(parents=True)

        # Seed one sample delegation
        sample = cls.live_dir / "deleg_smoke"
        sample.mkdir()
        (sample / "manifest.json").write_text(json.dumps({
            "delegation_id": "deleg_smoke",
            "started": "2026-07-23 10:00:00",
            "task_count": 1,
            "tasks": [
                {"index": 0, "goal": "smoke test goal",
                 "log": str(sample / "task-0.log"),
                 "status": "completed"}
            ],
            "completed": "2026-07-23 10:00:05",
            "exit_reason": "completed",
        }))
        (sample / "task-0.log").write_text(
            "=== header ===\n"
            "10:00:00 user     | kickoff: smoke test goal\n"
            "10:00:05 final    | status=completed\n"
        )

        # Patch the module-level LIVE_DIR
        cls._orig_live_dir = dashboard.LIVE_DIR
        dashboard.LIVE_DIR = cls.live_dir

        # Pick a free port
        import socket
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        cls.port = sock.getsockname()[1]
        sock.close()

        # Start server in a background thread
        from http.server import ThreadingHTTPServer
        cls.server = ThreadingHTTPServer(("127.0.0.1", cls.port), dashboard.DashboardHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        dashboard.LIVE_DIR = cls._orig_live_dir
        cls.tmp.cleanup()

    def _get(self, path: str) -> tuple:
        conn = HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            conn.request("GET", path)
            resp = conn.getresponse()
            return resp.status, resp.read()
        finally:
            conn.close()

    def test_index_returns_html(self):
        status, body = self._get("/")
        self.assertEqual(status, 200)
        self.assertIn(b"Hermes Subagent Dashboard", body)
        self.assertIn(b"<html", body.lower())

    def test_api_delegations_lists_seeded_one(self):
        status, body = self._get("/api/delegations")
        self.assertEqual(status, 200)
        data = json.loads(body)
        ids = [d["id"] for d in data]
        self.assertIn("deleg_smoke", ids)

    def test_api_delegation_detail(self):
        status, body = self._get("/api/delegations/deleg_smoke")
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertEqual(data["status"], "completed")
        self.assertEqual(data["tasks"][0]["goal"], "smoke test goal")
        self.assertEqual(len(data["tasks"][0]["events"]), 2)

    def test_api_delegation_404(self):
        status, body = self._get("/api/delegations/deleg_does_not_exist")
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertIn("error", data)

    def test_unknown_path_404(self):
        status, _ = self._get("/no/such/route")
        self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main()
