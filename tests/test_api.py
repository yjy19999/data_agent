"""
Tests for AgentAPI (agent/api.py).

All tests mock LLMClient.chat and SessionRecordingService so no real API calls
or file I/O happen.
"""
from __future__ import annotations

import asyncio
from collections.abc import Iterator
from typing import Any
from unittest.mock import MagicMock, patch, call

import pytest

from agent import AgentAPI, Config, TurnEvent
from agent.client import ChatResponse, ToolCall
from agent.telemetry import TokenUsageStats
from agent.tools.base import Tool, ToolRegistry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_response(text: str = "Hello!", tool_calls: list[ToolCall] | None = None) -> ChatResponse:
    """Build a fake ChatResponse (non-streaming path)."""
    resp = ChatResponse()
    resp.content = text
    resp.tool_calls = tool_calls or []
    resp.usage = TokenUsageStats(input_tokens=10, output_tokens=5, total_tokens=15)
    return resp


class EchoTool(Tool):
    """A simple test tool that echoes its input."""
    name = "echo"
    description = "Echo the input back."

    def run(self, message: str) -> str:
        """
        Args:
            message: Text to echo.
        """
        return f"echo: {message}"


def make_api(responses: list[ChatResponse], extra_tools: list[Tool] | None = None) -> AgentAPI:
    """
    Create an AgentAPI whose LLMClient.chat is replaced by a mock that returns
    responses in order. SessionRecordingService is also mocked to avoid disk I/O.
    """
    config = Config(
        base_url="http://localhost:11434/v1",
        api_key="test",
        model="test-model",
        stream=False,
    )
    registry = ToolRegistry()
    if extra_tools:
        for tool in extra_tools:
            registry.register(tool)

    with (
        patch("agent.agent.SessionRecordingService") as mock_recorder_cls,
        patch("agent.agent.LLMClient") as mock_client_cls,
    ):
        mock_recorder = MagicMock()
        mock_recorder_cls.return_value = mock_recorder

        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.chat.side_effect = responses

        api = AgentAPI(config=config, registry=registry)
        # Attach mocks so tests can inspect them
        api._mock_client = mock_client
        api._mock_recorder = mock_recorder
        return api


# ---------------------------------------------------------------------------
# chat() — basic
# ---------------------------------------------------------------------------

class TestChat:
    def test_returns_text(self):
        api = make_api([make_response("The answer is 42.")])
        result = api.chat("What is the answer?")
        assert result == "The answer is 42."

    def test_empty_response(self):
        api = make_api([make_response("")])
        result = api.chat("ping")
        assert result == ""

    def test_raises_on_error_with_no_text(self):
        """chat() raises RuntimeError when only an error event is produced."""
        api = make_api([make_response("")])
        # Inject an error by monkeypatching the internal agent's run
        original_run = api._agent.run

        def run_with_error(msg):
            yield TurnEvent(type="error", data="something went wrong")
            yield TurnEvent(type="done")

        api._agent.run = run_with_error
        with pytest.raises(RuntimeError, match="something went wrong"):
            api.chat("bad request")

    def test_returns_text_even_with_error(self):
        """If there is text AND an error, return the text without raising."""
        api = make_api([make_response("partial answer")])

        def run_with_text_and_error(msg):
            yield TurnEvent(type="text", data="partial answer")
            yield TurnEvent(type="error", data="non-fatal")
            yield TurnEvent(type="done")

        api._agent.run = run_with_text_and_error
        result = api.chat("whatever")
        assert result == "partial answer"

    def test_history_grows_after_chat(self):
        api = make_api([make_response("Hi!")])
        api.chat("Hello")
        # system + user + assistant = 3 messages minimum
        assert len(api.history) >= 3

    def test_multiple_turns(self):
        api = make_api([
            make_response("First"),
            make_response("Second"),
        ])
        r1 = api.chat("Turn 1")
        r2 = api.chat("Turn 2")
        assert r1 == "First"
        assert r2 == "Second"


# ---------------------------------------------------------------------------
# stream() — event types
# ---------------------------------------------------------------------------

class TestStream:
    def test_yields_text_events(self):
        api = make_api([make_response("streaming text")])
        events = list(api.stream("tell me something"))
        text_events = [e for e in events if e.type == "text"]
        assert text_events, "expected at least one text event"
        full_text = "".join(e.data for e in text_events)
        assert full_text == "streaming text"

    def test_yields_done_event(self):
        api = make_api([make_response("ok")])
        events = list(api.stream("go"))
        types = [e.type for e in events]
        assert "done" in types

    def test_yields_usage_event(self):
        api = make_api([make_response("ok")])
        events = list(api.stream("go"))
        usage_events = [e for e in events if e.type == "usage"]
        assert usage_events, "expected a usage event"
        stats = usage_events[-1].data
        assert isinstance(stats, TokenUsageStats)

    def test_tool_events_emitted(self):
        """When LLM requests a tool call, tool_start and tool_end events are emitted."""
        tool_call = ToolCall(id="tc1", name="echo", arguments={"message": "hi"})
        responses = [
            make_response("", tool_calls=[tool_call]),  # first: request tool
            make_response("Done."),                      # second: final answer
        ]
        api = make_api(responses, extra_tools=[EchoTool()])
        events = list(api.stream("echo hi"))

        event_types = [e.type for e in events]
        assert "tool_start" in event_types
        assert "tool_end" in event_types

        tool_start = next(e for e in events if e.type == "tool_start")
        assert tool_start.data["name"] == "echo"

        tool_end = next(e for e in events if e.type == "tool_end")
        assert tool_end.data["result"] == "echo: hi"

    def test_text_after_tool_call(self):
        """Final text comes after tool execution."""
        tool_call = ToolCall(id="tc1", name="echo", arguments={"message": "world"})
        responses = [
            make_response("", tool_calls=[tool_call]),
            make_response("Tool done."),
        ]
        api = make_api(responses, extra_tools=[EchoTool()])
        events = list(api.stream("use tool"))
        text = "".join(e.data for e in events if e.type == "text")
        assert text == "Tool done."


# ---------------------------------------------------------------------------
# reset()
# ---------------------------------------------------------------------------

class TestReset:
    def test_clears_conversation_history(self):
        api = make_api([make_response("reply"), make_response("reply2")])
        api.chat("message 1")
        history_after_turn = len(api.history)
        assert history_after_turn > 1

        api.reset()
        # Only system prompt should remain
        assert len(api.history) == 1
        assert api.history[0]["role"] == "system"

    def test_can_chat_after_reset(self):
        api = make_api([make_response("before"), make_response("after")])
        api.chat("before reset")
        api.reset()
        result = api.chat("after reset")
        assert result == "after"


# ---------------------------------------------------------------------------
# plan() / execute() / plan_and_execute()
# ---------------------------------------------------------------------------

class TestPlanAndExecute:
    def _plan_responses(self):
        """
        Returns a sequence of responses that simulate plan generation:
        1. LLM calls write_plan → triggers PLAN_READY_SENTINEL
        2. LLM executes the plan and responds with text
        """
        from agent.tools.plan import WritePlanTool, PLAN_READY_SENTINEL

        plan_tool_call = ToolCall(
            id="tc_plan",
            name="write_plan",
            arguments={"summary": "Test goal", "steps": ["step 1", "step 2"]},
        )
        return [
            make_response("", tool_calls=[plan_tool_call]),  # planning phase
            make_response("Execution complete."),             # execution phase
        ]

    def test_plan_yields_plan_ready(self):
        responses = self._plan_responses()
        api = make_api(responses)
        # Register the real WritePlanTool so the sentinel fires
        from agent.tools.plan import WritePlanTool
        api._agent._plan_tool = WritePlanTool()

        events = []
        for event in api.plan("do the thing"):
            events.append(event)

        plan_ready_events = [e for e in events if e.type == "plan_ready"]
        assert plan_ready_events, "expected a plan_ready event"
        plan_data = plan_ready_events[0].data
        assert plan_data["summary"] == "Test goal"
        assert plan_data["steps"] == ["step 1", "step 2"]

    def test_plan_and_execute_runs_both_phases(self):
        responses = self._plan_responses()
        api = make_api(responses)
        from agent.tools.plan import WritePlanTool
        api._agent._plan_tool = WritePlanTool()

        events = list(api.plan_and_execute("do the thing"))
        types = [e.type for e in events]

        assert "plan_ready" in types
        assert "text" in types
        text = "".join(e.data for e in events if e.type == "text")
        assert text == "Execution complete."


# ---------------------------------------------------------------------------
# Session management
# ---------------------------------------------------------------------------

class TestSessionManagement:
    def test_list_sessions_delegates(self):
        api = make_api([])
        api._agent.list_sessions = MagicMock(return_value=[{"id": "abc"}])
        result = api.list_sessions()
        assert result == [{"id": "abc"}]

    def test_delete_session_delegates(self):
        api = make_api([])
        api._agent.delete_session = MagicMock(return_value=True)
        assert api.delete_session("abc") is True

    def test_save_session_delegates(self):
        api = make_api([])
        api._agent.save_session = MagicMock()
        api.save_session()
        api._agent.save_session.assert_called_once()

    def test_resume_session_delegates(self):
        api = make_api([])
        api._agent.resume_session = MagicMock(return_value=None)
        result = api.resume_session("nonexistent")
        assert result is None


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------

class TestProperties:
    def test_session_id_is_string(self):
        api = make_api([])
        assert isinstance(api.session_id, str)
        assert len(api.session_id) > 0

    def test_config_is_config(self):
        api = make_api([])
        assert isinstance(api.config, Config)
        assert api.config.model == "test-model"

    def test_metrics_available(self):
        api = make_api([make_response("hi")])
        api.chat("hello")
        assert api.metrics is not None

    def test_history_is_copy(self):
        api = make_api([make_response("hi")])
        api.chat("hello")
        h = api.history
        assert isinstance(h, list)
        # Mutating the returned list does not affect internal state
        h.clear()
        assert len(api.history) > 0

    def test_repr(self):
        api = make_api([])
        r = repr(api)
        assert "AgentAPI" in r
        assert "test-model" in r


# ---------------------------------------------------------------------------
# Async interface
# ---------------------------------------------------------------------------

class TestAsync:
    def test_async_chat_returns_text(self):
        api = make_api([make_response("async reply")])
        result = asyncio.run(api.async_chat("hello async"))
        assert result == "async reply"

    def test_async_stream_yields_events(self):
        api = make_api([make_response("async stream")])

        async def collect():
            events = []
            async for event in api.async_stream("go"):
                events.append(event)
            return events

        events = asyncio.run(collect())
        text = "".join(e.data for e in events if e.type == "text")
        assert text == "async stream"

    def test_async_stream_yields_done(self):
        api = make_api([make_response("ok")])

        async def collect():
            return [e async for e in api.async_stream("go")]

        events = asyncio.run(collect())
        assert any(e.type == "done" for e in events)

    def test_async_chat_multiple_turns(self):
        api = make_api([make_response("one"), make_response("two")])

        async def run():
            r1 = await api.async_chat("first")
            r2 = await api.async_chat("second")
            return r1, r2

        r1, r2 = asyncio.run(run())
        assert r1 == "one"
        assert r2 == "two"


# ---------------------------------------------------------------------------
# Tool registry — custom tools
# ---------------------------------------------------------------------------

class TestCustomTools:
    def test_unknown_tool_returns_error_string(self):
        """Registry returns an error string for unknown tool names (no exception)."""
        registry = ToolRegistry()
        result = registry.execute("nonexistent", {})
        assert result.startswith("[error]")

    def test_echo_tool_works(self):
        tool = EchoTool()
        assert tool(message="world") == "echo: world"

    def test_custom_tool_schema_generation(self):
        tool = EchoTool()
        schema = tool.to_openai_schema()
        assert schema["function"]["name"] == "echo"
        assert "message" in schema["function"]["parameters"]["properties"]
        assert "message" in schema["function"]["parameters"]["required"]


# ---------------------------------------------------------------------------
# Sub-agent interface
# ---------------------------------------------------------------------------

def make_fake_manager():
    """Return a MagicMock that looks like an AgentManager."""
    from agent.multi_agent import AgentEntry, AgentStatus
    mgr = MagicMock()
    mgr.spawn.return_value = "abc123"
    mgr.send_input.return_value = "[ok] queued input for worker-1 (abc123)"
    mgr.wait.return_value = {"abc123": "done"}
    mgr.close.return_value = "[ok] stop signal sent to 'worker-1' (abc123)"
    mgr.resume.return_value = "def456"
    mgr.get_entry.return_value = AgentEntry(
        agent_id="abc123",
        nickname="default-1",
        role="default",
        status=AgentStatus.COMPLETED,
        depth=0,
        parent_id=None,
        result="result text",
    )
    mgr.list_agents.return_value = [
        AgentEntry(
            agent_id="abc123",
            nickname="default-1",
            role="default",
            status=AgentStatus.COMPLETED,
            depth=0,
            parent_id=None,
        )
    ]
    return mgr


class TestSubAgentAPI:
    """Tests for the 7 new sub-agent methods on AgentAPI."""

    # ------------------------------------------------------------------ spawn

    def test_spawn_agent_returns_agent_id(self):
        api = make_api([])
        mgr = make_fake_manager()
        with patch("agent.api.get_manager", return_value=mgr):
            result = api.spawn_agent("do something")
        assert result == "abc123"
        mgr.spawn.assert_called_once_with(
            prompt="do something",
            role="default",
            nickname=None,
            config=api.config,
        )

    def test_spawn_agent_passes_role_and_nickname(self):
        api = make_api([])
        mgr = make_fake_manager()
        with patch("agent.api.get_manager", return_value=mgr):
            result = api.spawn_agent("explore", role="explorer", nickname="scout")
        assert result == "abc123"
        mgr.spawn.assert_called_once_with(
            prompt="explore",
            role="explorer",
            nickname="scout",
            config=api.config,
        )

    def test_spawn_agent_inherits_parent_config(self):
        api = make_api([])
        mgr = make_fake_manager()
        with patch("agent.api.get_manager", return_value=mgr):
            api.spawn_agent("task")
        _, kwargs = mgr.spawn.call_args
        assert kwargs["config"].model == "test-model"

    # ------------------------------------------------------------------ wait

    def test_wait_for_agents_returns_results(self):
        api = make_api([])
        mgr = make_fake_manager()
        with patch("agent.api.get_manager", return_value=mgr):
            results = api.wait_for_agents(["abc123"])
        assert results == {"abc123": "done"}
        mgr.wait.assert_called_once_with(["abc123"], timeout=60)

    def test_wait_for_agents_custom_timeout(self):
        api = make_api([])
        mgr = make_fake_manager()
        with patch("agent.api.get_manager", return_value=mgr):
            api.wait_for_agents(["abc123"], timeout=120)
        mgr.wait.assert_called_once_with(["abc123"], timeout=120)

    def test_wait_for_multiple_agents(self):
        api = make_api([])
        mgr = make_fake_manager()
        mgr.wait.return_value = {"abc123": "r1", "def456": "r2"}
        with patch("agent.api.get_manager", return_value=mgr):
            results = api.wait_for_agents(["abc123", "def456"])
        assert len(results) == 2
        mgr.wait.assert_called_once_with(["abc123", "def456"], timeout=60)

    # ---------------------------------------------------------------- send_to

    def test_send_to_agent_delegates(self):
        api = make_api([])
        mgr = make_fake_manager()
        with patch("agent.api.get_manager", return_value=mgr):
            result = api.send_to_agent("abc123", "follow up")
        assert "[ok]" in result
        mgr.send_input.assert_called_once_with("abc123", "follow up")

    def test_send_to_agent_by_nickname(self):
        api = make_api([])
        mgr = make_fake_manager()
        with patch("agent.api.get_manager", return_value=mgr):
            api.send_to_agent("worker-1", "do more")
        mgr.send_input.assert_called_once_with("worker-1", "do more")

    # ----------------------------------------------------------------- close

    def test_close_agent_delegates(self):
        api = make_api([])
        mgr = make_fake_manager()
        with patch("agent.api.get_manager", return_value=mgr):
            result = api.close_agent("abc123")
        assert "[ok]" in result
        mgr.close.assert_called_once_with("abc123")

    # --------------------------------------------------------------- resume

    def test_resume_agent_returns_new_agent_id(self):
        api = make_api([])
        mgr = make_fake_manager()
        with patch("agent.api.get_manager", return_value=mgr):
            result = api.resume_agent("sess-xyz")
        assert result == "def456"
        mgr.resume.assert_called_once_with(
            session_id="sess-xyz",
            prompt=None,
            role="default",
            nickname=None,
            config=api.config,
        )

    def test_resume_agent_passes_all_args(self):
        api = make_api([])
        mgr = make_fake_manager()
        with patch("agent.api.get_manager", return_value=mgr):
            api.resume_agent("sess-xyz", prompt="continue", role="worker", nickname="r1")
        mgr.resume.assert_called_once_with(
            session_id="sess-xyz",
            prompt="continue",
            role="worker",
            nickname="r1",
            config=api.config,
        )

    # --------------------------------------------------------------- get_agent

    def test_get_agent_returns_entry(self):
        from agent.multi_agent import AgentEntry
        api = make_api([])
        mgr = make_fake_manager()
        with patch("agent.api.get_manager", return_value=mgr):
            entry = api.get_agent("abc123")
        assert isinstance(entry, AgentEntry)
        assert entry.agent_id == "abc123"
        mgr.get_entry.assert_called_once_with("abc123")

    def test_get_agent_returns_none_for_unknown(self):
        api = make_api([])
        mgr = make_fake_manager()
        mgr.get_entry.return_value = None
        with patch("agent.api.get_manager", return_value=mgr):
            result = api.get_agent("no-such-id")
        assert result is None

    # -------------------------------------------------------------- list_agents

    def test_list_agents_returns_entries(self):
        from agent.multi_agent import AgentEntry
        api = make_api([])
        mgr = make_fake_manager()
        with patch("agent.api.get_manager", return_value=mgr):
            agents = api.list_agents()
        assert isinstance(agents, list)
        assert len(agents) == 1
        assert isinstance(agents[0], AgentEntry)
        mgr.list_agents.assert_called_once()

    def test_list_agents_empty(self):
        api = make_api([])
        mgr = make_fake_manager()
        mgr.list_agents.return_value = []
        with patch("agent.api.get_manager", return_value=mgr):
            agents = api.list_agents()
        assert agents == []

    # ----------------------------------------------- spawn+wait integration

    def test_spawn_then_wait_full_cycle(self):
        """Simulate the common spawn → wait pattern."""
        api = make_api([])
        mgr = make_fake_manager()
        mgr.wait.return_value = {"abc123": "analysis complete"}
        with patch("agent.api.get_manager", return_value=mgr):
            agent_id = api.spawn_agent("analyse the repo", role="explorer")
            results = api.wait_for_agents([agent_id])
        assert results[agent_id] == "analysis complete"

    def test_spawn_multiple_then_wait(self):
        """Spawn two agents, collect both results."""
        api = make_api([])
        mgr = make_fake_manager()
        mgr.spawn.side_effect = ["id-1", "id-2"]
        mgr.wait.return_value = {"id-1": "r1", "id-2": "r2"}
        with patch("agent.api.get_manager", return_value=mgr):
            a1 = api.spawn_agent("task 1", role="worker")
            a2 = api.spawn_agent("task 2", role="worker")
            results = api.wait_for_agents([a1, a2], timeout=90)
        assert results["id-1"] == "r1"
        assert results["id-2"] == "r2"
        assert mgr.spawn.call_count == 2
        mgr.wait.assert_called_once_with(["id-1", "id-2"], timeout=90)
