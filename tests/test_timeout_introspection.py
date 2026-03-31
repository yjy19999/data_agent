"""
Tests for sub-agent timeout introspection:
  - progress_snapshot() returns correct state
  - _run() captures tool_start/tool_end events into progress fields
  - wait() timeout return includes progress snapshot
  - send_input() restart clears progress state
  - CheckAgentTool returns JSON snapshot
"""
from __future__ import annotations

import json
import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from agent.config import Config
from agent.multi_agent import AgentEntry, AgentManager, AgentStatus, get_manager
from agent.tools.multi_agents import CheckAgentTool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_entry(**kwargs) -> AgentEntry:
    defaults = dict(
        agent_id="abc123",
        nickname="worker-1",
        role="worker",
        status=AgentStatus.RUNNING,
        depth=0,
        parent_id=None,
    )
    defaults.update(kwargs)
    return AgentEntry(**defaults)


def fake_turn_events(*events):
    """Return an iterator that yields TurnEvent-like objects."""
    from agent.agent import TurnEvent
    return iter([TurnEvent(type=t, data=d) for t, d in events])


# ---------------------------------------------------------------------------
# progress_snapshot — initial state
# ---------------------------------------------------------------------------

class TestProgressSnapshotInitial:
    def test_fields_present(self):
        entry = make_entry()
        snap = entry.progress_snapshot()
        assert snap["agent_id"] == "abc123"
        assert snap["nickname"] == "worker-1"
        assert snap["status"] == "running"
        assert isinstance(snap["elapsed_seconds"], float)
        assert snap["tool_iterations_completed"] == 0
        assert snap["current_tool"] is None
        assert snap["last_completed_tool"] is None
        assert snap["partial_output_tail"] == ""

    def test_elapsed_increases(self):
        entry = make_entry()
        snap1 = entry.progress_snapshot()
        time.sleep(0.05)
        snap2 = entry.progress_snapshot()
        assert snap2["elapsed_seconds"] >= snap1["elapsed_seconds"]


# ---------------------------------------------------------------------------
# progress_snapshot — after simulated writes
# ---------------------------------------------------------------------------

class TestProgressSnapshotAfterWrite:
    def test_partial_text_captured(self):
        entry = make_entry()
        with entry._progress_lock:
            entry._partial_parts.extend(["Hello", " ", "world"])
        snap = entry.progress_snapshot()
        assert snap["partial_output_tail"] == "Hello world"

    def test_partial_text_truncated_at_2000(self):
        entry = make_entry()
        long_text = "x" * 3000
        with entry._progress_lock:
            entry._partial_parts.append(long_text)
        snap = entry.progress_snapshot()
        assert len(snap["partial_output_tail"]) <= 2003  # "..." + 2000
        assert snap["partial_output_tail"].startswith("...")

    def test_current_tool_captured(self):
        entry = make_entry()
        with entry._progress_lock:
            entry._current_tool = {"name": "Read", "arguments": {"path": "foo.py"}, "started_at": time.time()}
        snap = entry.progress_snapshot()
        assert snap["current_tool"]["name"] == "Read"

    def test_current_tool_args_truncated_at_500(self):
        entry = make_entry()
        with entry._progress_lock:
            entry._current_tool = {"name": "Bash", "arguments": "a" * 600, "started_at": time.time()}
        snap = entry.progress_snapshot()
        assert len(snap["current_tool"]["arguments"]) <= 503  # 500 + "..."
        assert snap["current_tool"]["arguments"].endswith("...")

    def test_tool_log_count(self):
        entry = make_entry()
        with entry._progress_lock:
            entry._tool_log.append({"name": "Read", "arguments": {}, "started_at": 0.0, "duration_ms": 10.0})
            entry._tool_log.append({"name": "Bash", "arguments": {}, "started_at": 0.0, "duration_ms": 20.0})
        snap = entry.progress_snapshot()
        assert snap["tool_iterations_completed"] == 2
        assert snap["last_completed_tool"]["name"] == "Bash"


# ---------------------------------------------------------------------------
# _run() event capture — tool_start / tool_end / text
# ---------------------------------------------------------------------------

class TestRunProgressCapture:
    def _make_manager_and_run(self, events):
        """Spawn a real AgentManager, fake agent.run() to emit given events."""
        from agent.agent import TurnEvent

        manager = AgentManager(max_threads=4, max_depth=3)
        cfg = Config(base_url="http://localhost", api_key="test", model="test-model", stream=False)

        event_objects = [TurnEvent(type=t, data=d) for t, d in events]

        fake_agent = MagicMock()
        fake_agent.run.return_value = iter(event_objects)

        with patch("agent.agent.Agent", return_value=fake_agent):
            agent_id = manager.spawn("do work", config=cfg)
            results = manager.wait([agent_id], timeout=5)

        entry = manager.get_entry(agent_id)
        return entry, results

    def test_text_events_populate_partial_parts(self):
        entry, _ = self._make_manager_and_run([
            ("text", "Hello "),
            ("text", "world"),
        ])
        snap = entry.progress_snapshot()
        assert snap["partial_output_tail"] == "Hello world"

    def test_tool_start_sets_current_tool_during_run(self):
        """After completion, current_tool should be cleared by tool_end."""
        entry, _ = self._make_manager_and_run([
            ("tool_start", {"name": "Read", "arguments": {"path": "x.py"}}),
            ("tool_end",   {"name": "Read", "result": "content"}),
        ])
        snap = entry.progress_snapshot()
        assert snap["current_tool"] is None  # cleared by tool_end
        assert snap["tool_iterations_completed"] == 1
        assert snap["last_completed_tool"]["name"] == "Read"

    def test_tool_log_has_duration(self):
        entry, _ = self._make_manager_and_run([
            ("tool_start", {"name": "Bash", "arguments": {"cmd": "ls"}}),
            ("tool_end",   {"name": "Bash", "result": "file.py"}),
        ])
        snap = entry.progress_snapshot()
        assert snap["last_completed_tool"]["duration_ms"] >= 0

    def test_multiple_tool_calls_counted(self):
        entry, _ = self._make_manager_and_run([
            ("tool_start", {"name": "Read",  "arguments": {}}),
            ("tool_end",   {"name": "Read",  "result": ""}),
            ("tool_start", {"name": "Bash",  "arguments": {}}),
            ("tool_end",   {"name": "Bash",  "result": ""}),
            ("tool_start", {"name": "Write", "arguments": {}}),
            ("tool_end",   {"name": "Write", "result": ""}),
        ])
        snap = entry.progress_snapshot()
        assert snap["tool_iterations_completed"] == 3

    def test_final_result_still_returned(self):
        _, results = self._make_manager_and_run([
            ("text", "done!"),
        ])
        agent_id = list(results.keys())[0]
        assert results[agent_id] == "done!"


# ---------------------------------------------------------------------------
# wait() timeout includes progress snapshot
# ---------------------------------------------------------------------------

class TestWaitTimeoutProgress:
    def test_timeout_returns_json_with_status_and_progress(self):
        from agent.agent import TurnEvent

        manager = AgentManager(max_threads=4, max_depth=3)
        cfg = Config(base_url="http://localhost", api_key="test", model="test-model", stream=False)

        # Agent that blocks for longer than the timeout
        barrier = threading.Event()

        def slow_run(prompt):
            barrier.wait(timeout=5)  # holds until test releases it
            yield TurnEvent(type="text", data="done")

        fake_agent = MagicMock()
        fake_agent.run.side_effect = slow_run

        with patch("agent.agent.Agent", return_value=fake_agent):
            agent_id = manager.spawn("slow task", config=cfg)
            results = manager.wait([agent_id], timeout=1)

        barrier.set()  # release the blocked thread

        value = results[agent_id]
        data = json.loads(value)
        assert data["status"] == "timeout"
        assert "did not finish" in data["message"]
        assert "progress" in data
        assert "tool_iterations_completed" in data["progress"]
        assert "partial_output_tail" in data["progress"]

    def test_timeout_progress_shows_running_status(self):
        from agent.agent import TurnEvent

        manager = AgentManager(max_threads=4, max_depth=3)
        cfg = Config(base_url="http://localhost", api_key="test", model="test-model", stream=False)

        barrier = threading.Event()

        def slow_run(prompt):
            barrier.wait(timeout=5)
            yield TurnEvent(type="text", data="done")

        fake_agent = MagicMock()
        fake_agent.run.side_effect = slow_run

        with patch("agent.agent.Agent", return_value=fake_agent):
            agent_id = manager.spawn("slow task", config=cfg)
            results = manager.wait([agent_id], timeout=1)

        barrier.set()

        data = json.loads(results[agent_id])
        assert data["progress"]["status"] == "running"


# ---------------------------------------------------------------------------
# send_input() restart clears progress state
# ---------------------------------------------------------------------------

class TestSendInputProgressReset:
    def test_restart_clears_tool_log_and_partial(self):
        cfg = Config(base_url="http://localhost", api_key="test", model="test-model", stream=False)
        manager = AgentManager()
        entry = make_entry(
            status=AgentStatus.COMPLETED,
            result="old result",
            config=cfg,
        )
        # Populate stale progress
        with entry._progress_lock:
            entry._tool_log.append({"name": "OldTool", "arguments": {}, "started_at": 0, "duration_ms": 5})
            entry._partial_parts.append("old text")
            entry._current_tool = {"name": "Stale", "arguments": {}, "started_at": 0}

        manager._agents[entry.agent_id] = entry

        class FakeThread:
            def __init__(self, **kw): pass
            def start(self): pass

        with patch("agent.multi_agent.threading.Thread", FakeThread):
            manager.send_input(entry.agent_id, "new task")

        snap = entry.progress_snapshot()
        assert snap["tool_iterations_completed"] == 0
        assert snap["partial_output_tail"] == ""
        assert snap["current_tool"] is None

    def test_restart_does_not_clear_for_running_agent(self):
        """Queued input on a RUNNING agent should NOT clear progress."""
        manager = AgentManager()
        entry = make_entry(status=AgentStatus.RUNNING)
        with entry._progress_lock:
            entry._tool_log.append({"name": "Bash", "arguments": {}, "started_at": 0, "duration_ms": 5})
        manager._agents[entry.agent_id] = entry

        manager.send_input(entry.agent_id, "extra instruction")

        snap = entry.progress_snapshot()
        assert snap["tool_iterations_completed"] == 1  # unchanged


# ---------------------------------------------------------------------------
# CheckAgentTool
# ---------------------------------------------------------------------------

class TestCheckAgentTool:
    def test_returns_json_snapshot(self):
        entry = make_entry(agent_id="xyz999", nickname="explorer-1")
        with entry._progress_lock:
            entry._partial_parts.append("some output")

        fake_manager = MagicMock()
        fake_manager.get_entry.return_value = entry

        with patch("agent.tools.multi_agents._mgr", return_value=fake_manager):
            result = CheckAgentTool().run(agent_id="xyz999")

        data = json.loads(result)
        assert data["agent_id"] == "xyz999"
        assert data["nickname"] == "explorer-1"
        assert data["partial_output_tail"] == "some output"

    def test_unknown_agent_returns_error(self):
        fake_manager = MagicMock()
        fake_manager.get_entry.return_value = None

        with patch("agent.tools.multi_agents._mgr", return_value=fake_manager):
            result = CheckAgentTool().run(agent_id="nope")

        assert "[error]" in result
        assert "nope" in result

    def test_snapshot_is_valid_json(self):
        entry = make_entry()
        fake_manager = MagicMock()
        fake_manager.get_entry.return_value = entry

        with patch("agent.tools.multi_agents._mgr", return_value=fake_manager):
            result = CheckAgentTool().run(agent_id="abc123")

        # Must not raise
        data = json.loads(result)
        assert isinstance(data, dict)

    def test_all_expected_keys_present(self):
        entry = make_entry()
        fake_manager = MagicMock()
        fake_manager.get_entry.return_value = entry

        with patch("agent.tools.multi_agents._mgr", return_value=fake_manager):
            result = CheckAgentTool().run(agent_id="abc123")

        data = json.loads(result)
        expected_keys = {
            "agent_id", "nickname", "status", "elapsed_seconds",
            "tool_iterations_completed", "current_tool",
            "last_completed_tool", "partial_output_tail",
        }
        assert expected_keys.issubset(data.keys())
