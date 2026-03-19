"""
Multi-agent management for cc_refine_1.3.

Inspired by codex-rs's AgentControl / ThreadManager architecture.
Provides a global AgentManager that tracks spawned sub-agents, their
status, roles, and results.  Agents run in background threads so the
parent can dispatch work and later collect results via wait().
"""
from __future__ import annotations

import queue
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .agent import Agent
    from .config import Config
    from .tools.base import ToolRegistry


# ── Enums ──────────────────────────────────────────────────────────────────────

class AgentStatus(str, Enum):
    PENDING   = "pending"
    RUNNING   = "running"
    COMPLETED = "completed"
    ERRORED   = "errored"
    SHUTDOWN  = "shutdown"


class AgentRole(str, Enum):
    """
    Roles modelled after codex-rs:
      default  – general purpose
      explorer – read-heavy, fast codebase investigation
      worker   – full tools, production implementation
      awaiter  – long-running monitor / poller
    """
    DEFAULT  = "default"
    EXPLORER = "explorer"
    WORKER   = "worker"
    AWAITER  = "awaiter"


@dataclass(frozen=True)
class AgentExecutionContext:
    """Thread-local context for tool calls made by a running agent."""
    config: Config
    registry: ToolRegistry | None
    agent_id: str | None = None
    depth: int = 0


_EXECUTION_CONTEXT = threading.local()


@contextmanager
def agent_execution_context(
    *,
    config: Config,
    registry: ToolRegistry | None,
    agent_id: str | None = None,
    depth: int = 0,
):
    """Expose the currently executing agent context to tools on this thread."""
    previous = getattr(_EXECUTION_CONTEXT, "current", None)
    _EXECUTION_CONTEXT.current = AgentExecutionContext(
        config=config,
        registry=registry,
        agent_id=agent_id,
        depth=depth,
    )
    try:
        yield
    finally:
        if previous is None:
            try:
                delattr(_EXECUTION_CONTEXT, "current")
            except AttributeError:
                pass
        else:
            _EXECUTION_CONTEXT.current = previous


def get_current_execution_context() -> AgentExecutionContext | None:
    """Return the active agent execution context for this thread, if any."""
    return getattr(_EXECUTION_CONTEXT, "current", None)


def clone_registry_for_child(config: Config, registry: ToolRegistry | None) -> ToolRegistry | None:
    """
    Build a child-safe registry from the parent's current registry.

    Sandboxed registries get rebuilt against the same workspace so sub-agents
    cannot silently fall back to an unrestricted default registry.
    """
    if registry is None:
        return None

    from .sandbox import SandboxedRegistry
    from .tools.base import ToolRegistry as BaseToolRegistry
    from .tools.profiles import get_profile, infer_profile

    if isinstance(registry, SandboxedRegistry):
        profile_name = config.tool_profile
        if profile_name == "auto":
            profile_name = infer_profile(config.model)
        base_registry = get_profile(profile_name).build_registry()
        child_registry = SandboxedRegistry(registry.workspace)
        for schema in base_registry.schemas():
            tool = base_registry.get(schema["function"]["name"])
            if tool:
                child_registry.register(tool)
        return child_registry

    child_registry = BaseToolRegistry()
    for schema in registry.schemas():
        tool = registry.get(schema["function"]["name"])
        if tool:
            child_registry.register(tool)
    return child_registry


# ── Role → config overrides ────────────────────────────────────────────────────

_ROLE_SYSTEM_ADDENDUM: dict[str, str] = {
    AgentRole.EXPLORER: (
        "\n\nYou are an EXPLORER agent. Focus on reading and understanding the "
        "codebase quickly. Prefer read-only operations. Be concise and fast."
    ),
    AgentRole.WORKER: (
        "\n\nYou are a WORKER agent. Your job is to implement, write, and modify "
        "code. Be thorough and precise. Complete the task fully."
    ),
    AgentRole.AWAITER: (
        "\n\nYou are an AWAITER agent. You monitor long-running processes or poll "
        "for completion. Report status clearly and wait patiently."
    ),
}

_ROLE_MAX_ITERATIONS: dict[str, int | None] = {
    AgentRole.DEFAULT:  None,   # inherit from config
    AgentRole.EXPLORER: 15,
    AgentRole.WORKER:   None,   # inherit from config
    AgentRole.AWAITER:  50,
}


# ── AgentEntry ─────────────────────────────────────────────────────────────────

@dataclass
class AgentEntry:
    agent_id:  str
    nickname:  str
    role:      str
    status:    AgentStatus
    depth:     int
    parent_id: str | None
    created_at: float = field(default_factory=time.time)

    # Results
    result:  str | None = None
    error:   str | None = None
    config:  Config | None = field(default=None, repr=False)
    registry: Any = field(default=None, repr=False)

    # Threading primitives
    _thread:      threading.Thread | None = field(default=None, repr=False)
    _done_event:  threading.Event         = field(default_factory=threading.Event, repr=False)
    _stop_flag:   threading.Event         = field(default_factory=threading.Event, repr=False)
    _input_queue: queue.Queue             = field(default_factory=queue.Queue, repr=False)

    def is_done(self) -> bool:
        return self.status in (AgentStatus.COMPLETED, AgentStatus.ERRORED, AgentStatus.SHUTDOWN)

    def elapsed_seconds(self) -> float:
        return time.time() - self.created_at


# ── AgentManager ──────────────────────────────────────────────────────────────

class AgentManager:
    """
    Central registry for all spawned sub-agents.

    Usage:
        manager = get_manager()
        agent_id = manager.spawn("analyse this codebase", role="explorer")
        results  = manager.wait([agent_id], timeout=120)
    """

    def __init__(self, max_threads: int = 4, max_depth: int = 3):
        self._agents:  dict[str, AgentEntry] = {}
        self._lock:    threading.Lock = threading.Lock()
        self.max_threads = max_threads
        self.max_depth   = max_depth
        self._nickname_counters: dict[str, int] = {}

    # ── Public API ─────────────────────────────────────────────────────────────

    def spawn(
        self,
        prompt:    str,
        role:      str = AgentRole.DEFAULT,
        nickname:  str | None = None,
        parent_id: str | None = None,
        depth:     int = 0,
        config:    Config | None = None,
        registry=None,
    ) -> str:
        """
        Spawn a new agent in a background thread.

        Returns the agent_id immediately; the agent runs asynchronously.
        Call wait([agent_id]) to block until it finishes.
        """
        from .config import Config as _Config

        with self._lock:
            # Depth limit
            if depth >= self.max_depth:
                raise RuntimeError(
                    f"Cannot spawn agent at depth {depth}: max_depth={self.max_depth}"
                )
            # Thread limit
            running = sum(
                1 for e in self._agents.values()
                if e.status == AgentStatus.RUNNING
            )
            if running >= self.max_threads:
                raise RuntimeError(
                    f"Cannot spawn agent: {running}/{self.max_threads} threads already running"
                )

            role = role if isinstance(role, str) else role.value
            agent_id = uuid.uuid4().hex[:12]
            if nickname is None:
                count = self._nickname_counters.get(role, 0) + 1
                self._nickname_counters[role] = count
                nickname = f"{role}-{count}"

            entry = AgentEntry(
                agent_id=agent_id,
                nickname=nickname,
                role=role,
                status=AgentStatus.PENDING,
                depth=depth,
                parent_id=parent_id,
            )
            self._agents[agent_id] = entry

        cfg = config or _Config()
        entry.config = cfg.model_copy()
        entry.registry = registry
        t = threading.Thread(
            target=self._run,
            args=(entry, prompt, cfg, registry),
            daemon=True,
            name=f"agent-{nickname}",
        )
        entry._thread = t
        t.start()
        return agent_id

    def send_input(self, agent_id: str, message: str) -> str:
        """
        Queue additional input for an agent.

        If the agent is still running, the message is queued and processed
        after the current task completes.  If the agent already finished,
        it is restarted in a new thread with the message added to context.
        """
        entry = self._get(agent_id)
        if entry is None:
            return f"[error] agent '{agent_id}' not found"

        if entry.status == AgentStatus.RUNNING:
            entry._input_queue.put(message)
            return f"[ok] queued input for {entry.nickname} ({agent_id})"

        if entry.status == AgentStatus.COMPLETED:
            # Re-run with continuation prompt
            continuation = (
                f"Previous result:\n{entry.result or '(none)'}\n\n"
                f"Now do the following:\n{message}"
            )
            entry._done_event.clear()
            entry._stop_flag.clear()
            entry.status = AgentStatus.PENDING
            entry.result = None
            entry.error  = None
            from .config import Config as _Config
            cfg = entry.config.model_copy() if entry.config is not None else _Config()
            t = threading.Thread(
                target=self._run,
                args=(entry, continuation, cfg, entry.registry),
                daemon=True,
                name=f"agent-{entry.nickname}-cont",
            )
            entry._thread = t
            t.start()
            return f"[ok] restarted {entry.nickname} ({agent_id}) with new input"

        return f"[error] agent '{agent_id}' is {entry.status.value} — cannot send input"

    def wait(
        self,
        agent_ids: list[str],
        timeout: int = 60,
    ) -> dict[str, str]:
        """
        Block until all specified agents finish (or timeout expires).

        Returns a dict of {agent_id: result_or_error}.
        """
        deadline = time.time() + timeout
        results: dict[str, str] = {}

        for agent_id in agent_ids:
            entry = self._get(agent_id)
            if entry is None:
                results[agent_id] = f"[error] agent '{agent_id}' not found"
                continue
            remaining = max(0.0, deadline - time.time())
            finished = entry._done_event.wait(timeout=remaining)
            if not finished:
                results[agent_id] = (
                    f"[timeout] agent '{entry.nickname}' did not finish within {timeout}s"
                )
            elif entry.status == AgentStatus.ERRORED:
                results[agent_id] = f"[error] {entry.error}"
            else:
                results[agent_id] = entry.result or "(no output)"

        return results

    def close(self, agent_id: str) -> str:
        """
        Signal an agent to stop.  The agent will finish its current tool call
        then exit (best-effort; Python threads cannot be forcibly killed).
        """
        entry = self._get(agent_id)
        if entry is None:
            return f"[error] agent '{agent_id}' not found"
        if entry.is_done():
            return f"[ok] agent '{entry.nickname}' is already {entry.status.value}"
        entry._stop_flag.set()
        entry.status = AgentStatus.SHUTDOWN
        return f"[ok] stop signal sent to '{entry.nickname}' ({agent_id})"

    def resume(
        self,
        session_id: str,
        prompt: str | None = None,
        role:   str = AgentRole.DEFAULT,
        nickname: str | None = None,
        depth:  int = 0,
        config: Config | None = None,
        registry=None,
        parent_id: str | None = None,
    ) -> str:
        """
        Spawn an agent that resumes a previously saved session.

        Returns the new agent_id.
        """
        from .config import Config as _Config
        cfg = config or _Config()

        def _resume_run(entry: AgentEntry) -> None:
            from .agent import Agent
            entry.status = AgentStatus.RUNNING
            try:
                if entry.registry is not None:
                    agent = Agent(
                        config=cfg,
                        registry=entry.registry,
                        agent_id=entry.agent_id,
                        agent_depth=entry.depth,
                    )
                else:
                    agent = Agent(
                        config=cfg,
                        agent_id=entry.agent_id,
                        agent_depth=entry.depth,
                    )
                record = agent.resume_session(session_id)
                if record is None:
                    entry.error = f"session '{session_id}' not found"
                    entry.status = AgentStatus.ERRORED
                    return

                parts: list[str] = []
                msg = prompt or "Continue from where you left off."
                for event in agent.run(msg):
                    if entry._stop_flag.is_set():
                        break
                    if event.type == "text":
                        parts.append(event.data)

                entry.result = "".join(parts).strip()
                entry.status = AgentStatus.COMPLETED
            except Exception as exc:
                entry.error = str(exc)
                entry.status = AgentStatus.ERRORED
            finally:
                entry._done_event.set()

        with self._lock:
            agent_id = uuid.uuid4().hex[:12]
            role_str = role if isinstance(role, str) else role.value
            if nickname is None:
                count = self._nickname_counters.get(role_str, 0) + 1
                self._nickname_counters[role_str] = count
                nickname = f"{role_str}-resume-{count}"
            entry = AgentEntry(
                agent_id=agent_id,
                nickname=nickname,
                role=role_str,
                status=AgentStatus.PENDING,
                depth=depth,
                parent_id=parent_id,
            )
            entry.config = cfg.model_copy()
            entry.registry = registry
            self._agents[agent_id] = entry

        t = threading.Thread(
            target=_resume_run,
            args=(entry,),
            daemon=True,
            name=f"agent-{nickname}",
        )
        entry._thread = t
        t.start()
        return agent_id

    def get_entry(self, agent_id: str) -> AgentEntry | None:
        return self._get(agent_id)

    def list_agents(self) -> list[AgentEntry]:
        with self._lock:
            return list(self._agents.values())

    def summary(self) -> str:
        entries = self.list_agents()
        if not entries:
            return "No agents spawned yet."
        lines = ["Agents:"]
        for e in entries:
            status_marker = {
                AgentStatus.PENDING:   "⏳",
                AgentStatus.RUNNING:   "🔄",
                AgentStatus.COMPLETED: "✅",
                AgentStatus.ERRORED:   "❌",
                AgentStatus.SHUTDOWN:  "🛑",
            }.get(e.status, "?")
            lines.append(
                f"  {status_marker} {e.nickname} ({e.agent_id[:8]}) "
                f"[{e.role}] depth={e.depth} elapsed={e.elapsed_seconds():.1f}s"
            )
        return "\n".join(lines)

    # ── Internal ───────────────────────────────────────────────────────────────

    def _get(self, agent_id: str) -> AgentEntry | None:
        with self._lock:
            # Support lookup by partial ID or nickname
            if agent_id in self._agents:
                return self._agents[agent_id]
            for entry in self._agents.values():
                if entry.nickname == agent_id or entry.agent_id.startswith(agent_id):
                    return entry
        return None

    def _run(
        self,
        entry:    AgentEntry,
        prompt:   str,
        config:   Config,
        registry,
    ) -> None:
        from .agent import Agent

        entry.status = AgentStatus.RUNNING
        try:
            # Apply role-specific overrides
            role_addendum = _ROLE_SYSTEM_ADDENDUM.get(entry.role, "")
            role_max_iter = _ROLE_MAX_ITERATIONS.get(entry.role)

            cfg = config.model_copy()
            if role_addendum:
                cfg.system_prompt = (cfg.system_prompt or "") + role_addendum
            if role_max_iter is not None:
                cfg.max_tool_iterations = min(cfg.max_tool_iterations, role_max_iter)

            # Depth-based iteration cap: children get progressively fewer iterations
            depth_cap = max(5, cfg.max_tool_iterations - entry.depth * 3)
            cfg.max_tool_iterations = min(cfg.max_tool_iterations, depth_cap)

            agent = Agent(
                config=cfg,
                registry=registry,
                agent_id=entry.agent_id,
                agent_depth=entry.depth,
            )

            parts: list[str] = []

            for event in agent.run(prompt):
                if entry._stop_flag.is_set():
                    break
                if event.type == "text":
                    parts.append(event.data)

            # Drain any queued inputs
            while not entry._input_queue.empty() and not entry._stop_flag.is_set():
                msg = entry._input_queue.get_nowait()
                for event in agent.run(msg):
                    if entry._stop_flag.is_set():
                        break
                    if event.type == "text":
                        parts.append(event.data)

            entry.result = "".join(parts).strip()
            if entry.status != AgentStatus.SHUTDOWN:
                entry.status = AgentStatus.COMPLETED

        except Exception as exc:
            entry.error = str(exc)
            entry.status = AgentStatus.ERRORED
        finally:
            entry._done_event.set()


# ── Global singleton ───────────────────────────────────────────────────────────

_GLOBAL_MANAGER: AgentManager | None = None
_MANAGER_LOCK = threading.Lock()


def get_manager(max_threads: int = 4, max_depth: int = 3) -> AgentManager:
    """
    Return the global AgentManager, creating it on first call.

    Pass max_threads / max_depth only on first call (or they are ignored).
    """
    global _GLOBAL_MANAGER
    if _GLOBAL_MANAGER is None:
        with _MANAGER_LOCK:
            if _GLOBAL_MANAGER is None:
                _GLOBAL_MANAGER = AgentManager(
                    max_threads=max_threads,
                    max_depth=max_depth,
                )
    return _GLOBAL_MANAGER
