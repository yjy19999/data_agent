from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Iterator
from typing import Any

from .agent import Agent, TurnEvent
from .config import Config
from .tools import ToolRegistry


class AgentAPI:
    """
    Simple Python API for the agent framework.

    Wraps the core Agent with convenient sync, streaming, and async interfaces.

    Basic usage::

        from agent import AgentAPI

        api = AgentAPI()

        # Simple blocking call — returns final text
        reply = api.chat("list all Python files in src/")
        print(reply)

        # Streaming — yields TurnEvent objects
        for event in api.stream("explain this codebase"):
            if event.type == "text":
                print(event.data, end="", flush=True)

        # Async
        reply = await api.async_chat("what is 2 + 2?")

        # Async streaming
        async for event in api.async_stream("list files"):
            if event.type == "text":
                print(event.data, end="", flush=True)

    Custom config::

        from agent import AgentAPI, Config

        api = AgentAPI(Config(
            base_url="https://api.openai.com/v1",
            api_key="sk-...",
            model="gpt-4o",
        ))
    """

    def __init__(
        self,
        config: Config | None = None,
        registry: ToolRegistry | None = None,
    ) -> None:
        self._agent = Agent(config=config, registry=registry)

    # ------------------------------------------------------------------
    # Synchronous interface
    # ------------------------------------------------------------------

    def chat(self, message: str) -> str:
        """
        Send a message and return the final text response.

        Tool calls are executed automatically. Blocks until the agent
        finishes all tool iterations and produces a final response.

        Args:
            message: User message to send.

        Returns:
            The assistant's final text response.

        Raises:
            RuntimeError: If the agent returns an error event.
        """
        parts: list[str] = []
        error: str | None = None
        for event in self._agent.run(message):
            if event.type == "text":
                parts.append(event.data)
            elif event.type == "error":
                error = event.data
        if error and not parts:
            raise RuntimeError(error)
        return "".join(parts)

    def stream(self, message: str) -> Iterator[TurnEvent]:
        """
        Send a message and stream TurnEvent objects as the agent works.

        Event types:
            - ``text``       — incremental assistant text chunk
            - ``tool_start`` — agent is about to call a tool; data has ``name`` and ``arguments``
            - ``tool_end``   — tool finished; data has ``name`` and ``result``
            - ``error``      — error message string in ``data``
            - ``usage``      — TokenUsageStats in ``data``
            - ``compressed`` — history was compressed; data has token counts
            - ``done``       — turn finished (last event)

        Args:
            message: User message to send.

        Yields:
            TurnEvent objects.
        """
        yield from self._agent.run(message)

    # ------------------------------------------------------------------
    # Async interface
    # ------------------------------------------------------------------

    async def async_chat(self, message: str) -> str:
        """
        Async version of chat(). Runs the agent in a thread pool executor
        so it doesn't block the event loop.

        Args:
            message: User message to send.

        Returns:
            The assistant's final text response.
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.chat, message)

    async def async_stream(self, message: str) -> AsyncGenerator[TurnEvent, None]:
        """
        Async streaming version. Runs the agent in a background thread and
        yields TurnEvent objects without blocking the event loop.

        Args:
            message: User message to send.

        Yields:
            TurnEvent objects.
        """
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[TurnEvent | None] = asyncio.Queue()

        def _run() -> None:
            try:
                for event in self._agent.run(message):
                    loop.call_soon_threadsafe(queue.put_nowait, event)
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, None)

        future = loop.run_in_executor(None, _run)
        while True:
            event = await queue.get()
            if event is None:
                break
            yield event
        await future  # propagate any thread exceptions

    # ------------------------------------------------------------------
    # Plan-then-execute interface
    # ------------------------------------------------------------------

    def plan(self, message: str) -> Iterator[TurnEvent]:
        """
        Phase 1 of plan-then-execute: explore and generate a plan.

        Yields events including a ``plan_ready`` event whose ``data`` is::

            {"goal": str, "steps": list[str]}

        After this, call execute() to run the plan.

        Args:
            message: Task description.

        Yields:
            TurnEvent objects. ``plan_ready`` event signals plan is ready.
        """
        yield from self._agent.generate_plan(message)

    def execute(self) -> Iterator[TurnEvent]:
        """
        Phase 2 of plan-then-execute: execute the approved plan.

        Must be called after plan() yields a ``plan_ready`` event.

        Yields:
            TurnEvent objects.
        """
        yield from self._agent.execute()

    def plan_and_execute(self, message: str) -> Iterator[TurnEvent]:
        """
        Convenience method: generate a plan and execute it automatically.

        Yields all events from both phases.

        Args:
            message: Task description.

        Yields:
            TurnEvent objects from planning and execution phases.
        """
        plan_ready = False
        for event in self._agent.generate_plan(message):
            yield event
            if event.type == "plan_ready":
                plan_ready = True
        if plan_ready:
            yield from self._agent.execute()

    # ------------------------------------------------------------------
    # Session management
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Clear conversation history (keeps the system prompt)."""
        self._agent.reset()

    def resume_session(self, session_id: str) -> Any:
        """
        Resume a previous session by restoring its message history.

        Args:
            session_id: Session ID returned by list_sessions().

        Returns:
            ConversationRecord if found, None otherwise.
        """
        return self._agent.resume_session(session_id)

    def list_sessions(self) -> list[dict[str, Any]]:
        """Return metadata for all saved sessions."""
        return self._agent.list_sessions()

    def delete_session(self, session_id: str) -> bool:
        """
        Delete a saved session.

        Args:
            session_id: ID of the session to delete.

        Returns:
            True if deleted, False if not found.
        """
        return self._agent.delete_session(session_id)

    def save_session(self) -> None:
        """Flush current session metrics to disk."""
        self._agent.save_session()

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def history(self) -> list[dict[str, Any]]:
        """Conversation history as a list of OpenAI-format message dicts."""
        return list(self._agent.history)

    @property
    def metrics(self) -> Any:
        """Session metrics (token counts, latency, tool success rates)."""
        return self._agent.metrics

    @property
    def session_id(self) -> str:
        """Current session ID."""
        return self._agent.session_id

    @property
    def config(self) -> Config:
        """Active Config object."""
        return self._agent.config

    def __repr__(self) -> str:
        return (
            f"AgentAPI(model={self.config.model!r}, "
            f"profile={getattr(self._agent, 'profile_name', 'custom')!r}, "
            f"session_id={self.session_id!r})"
        )
