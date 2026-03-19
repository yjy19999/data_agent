"""
Tests for AgentAPI (agent/api.py).

All tests mock LLMClient.chat and SessionRecordingService so no real API calls
or file I/O happen.
"""
from __future__ import annotations

import asyncio
from collections.abc import Iterator
from typing import Any
from unittest.mock import MagicMock, patch

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
