"""
Multi-agent tools for cc_refine_1.3.

Mirrors codex-rs's five core multi-agent tools:
  spawn_agent   – launch a named background agent
  send_input    – send a message to a running/completed agent
  wait_for_agents – block until agents finish and collect results
  close_agent   – signal an agent to stop
  resume_agent  – spawn an agent that resumes a saved session

All tools share the global AgentManager (get_manager()).
"""
from __future__ import annotations

import json

from .base import Tool


def _mgr():
    """Return the global AgentManager (lazy init)."""
    from ..multi_agent import get_manager
    return get_manager()


def _inherit_parent_context() -> dict:
    """Carry the current agent's config/registry into spawned children."""
    from ..multi_agent import clone_registry_for_child, get_current_execution_context

    context = get_current_execution_context()
    if context is None:
        return {}

    kwargs = {
        "config": context.config.model_copy(),
        "registry": clone_registry_for_child(context.config, context.registry),
        "depth": context.depth + 1,
    }
    if context.agent_id is not None:
        kwargs["parent_id"] = context.agent_id
    return kwargs


# ── spawn_agent ────────────────────────────────────────────────────────────────

class SpawnAgentTool(Tool):
    name = "spawn_agent"
    description = (
        "Spawn a new background agent to handle an isolated task. "
        "The agent runs concurrently in a separate thread. "
        "Returns an agent_id — use wait_for_agents() to collect the result. "
        "Roles: default (general), explorer (read-only/fast), "
        "worker (full tools/implementation), awaiter (long-running monitor)."
    )

    @property
    def parameters_schema(self):
        return {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "Full instructions for the sub-agent.",
                },
                "role": {
                    "type": "string",
                    "enum": ["default", "explorer", "worker", "awaiter"],
                    "description": "Agent role — influences tools and iteration limits.",
                },
                "nickname": {
                    "type": "string",
                    "description": "Human-readable name for this agent (auto-assigned if omitted).",
                },
            },
            "required": ["prompt"],
        }

    def run(
        self,
        prompt: str,
        role: str = "default",
        nickname: str | None = None,
    ) -> str:
        """
        Args:
            prompt: Full instructions for the sub-agent.
            role: Agent role (default, explorer, worker, awaiter).
            nickname: Optional human-readable label.
        """
        # Determine current depth from any parent agent context
        # (future: could be injected; for now always depth=0 for user-spawned agents)
        try:
            agent_id = _mgr().spawn(
                prompt=prompt,
                role=role,
                nickname=nickname,
                **_inherit_parent_context(),
            )
            entry = _mgr().get_entry(agent_id)
            nick = entry.nickname if entry else nickname or role
            return (
                f"[spawned] agent_id={agent_id} nickname={nick} role={role}\n"
                f"Use wait_for_agents(agent_ids=[\"{agent_id}\"]) to block until it finishes."
            )
        except RuntimeError as exc:
            return f"[error] {exc}"


# ── send_input ────────────────────────────────────────────────────────────────

class SendInputTool(Tool):
    name = "send_input"
    description = (
        "Send a message to a running or completed agent. "
        "If the agent is running, the message is queued for processing after the current task. "
        "If the agent already completed, it is restarted with the new input in context. "
        "Use agent_id or nickname to identify the agent."
    )

    @property
    def parameters_schema(self):
        return {
            "type": "object",
            "properties": {
                "agent_id": {
                    "type": "string",
                    "description": "The agent_id or nickname of the target agent.",
                },
                "message": {
                    "type": "string",
                    "description": "The message or follow-up instruction to send.",
                },
            },
            "required": ["agent_id", "message"],
        }

    def run(self, agent_id: str, message: str) -> str:
        """
        Args:
            agent_id: The agent_id or nickname of the target agent.
            message: The message or follow-up instruction to send.
        """
        return _mgr().send_input(agent_id, message)


# ── wait ──────────────────────────────────────────────────────────────────────

class WaitTool(Tool):
    name = "wait_for_agents"
    description = (
        "Block until the specified agents finish and return their results. "
        "Pass a list of agent_ids. Optionally set a timeout (default 60s, max 3600s). "
        "Returns a JSON object mapping agent_id → result."
    )

    @property
    def parameters_schema(self):
        return {
            "type": "object",
            "properties": {
                "agent_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of agent_ids (or nicknames) to wait for.",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Max seconds to wait per agent (10–3600, default 60).",
                    "minimum": 10,
                    "maximum": 3600,
                },
            },
            "required": ["agent_ids"],
        }

    def run(self, agent_ids: list[str], timeout: int = 60) -> str:
        """
        Args:
            agent_ids: List of agent_ids or nicknames to wait for.
            timeout: Max seconds to wait (10–3600).
        """
        timeout = max(10, min(3600, int(timeout)))
        results = _mgr().wait(agent_ids, timeout=timeout)
        return json.dumps(results, indent=2, ensure_ascii=False)


# ── close_agent ───────────────────────────────────────────────────────────────

class CloseAgentTool(Tool):
    name = "close_agent"
    description = (
        "Send a stop signal to an agent. "
        "The agent will finish its current tool call then exit (best-effort). "
        "Use agent_id or nickname to identify the agent."
    )

    @property
    def parameters_schema(self):
        return {
            "type": "object",
            "properties": {
                "agent_id": {
                    "type": "string",
                    "description": "The agent_id or nickname of the agent to stop.",
                },
            },
            "required": ["agent_id"],
        }

    def run(self, agent_id: str) -> str:
        """
        Args:
            agent_id: The agent_id or nickname of the agent to stop.
        """
        return _mgr().close(agent_id)


# ── resume_agent ──────────────────────────────────────────────────────────────

class ResumeAgentTool(Tool):
    name = "resume_agent"
    description = (
        "Spawn a new agent that resumes a previously saved session. "
        "The agent loads the full conversation history from the session file "
        "and continues from where it left off. "
        "Returns an agent_id — use wait_for_agents() to collect the result."
    )

    @property
    def parameters_schema(self):
        return {
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "The session ID to resume (from a prior agent session).",
                },
                "prompt": {
                    "type": "string",
                    "description": "Optional follow-up instruction (defaults to 'Continue from where you left off.').",
                },
                "role": {
                    "type": "string",
                    "enum": ["default", "explorer", "worker", "awaiter"],
                    "description": "Role for the resumed agent.",
                },
                "nickname": {
                    "type": "string",
                    "description": "Optional label for the resumed agent.",
                },
            },
            "required": ["session_id"],
        }

    def run(
        self,
        session_id: str,
        prompt: str | None = None,
        role: str = "default",
        nickname: str | None = None,
    ) -> str:
        """
        Args:
            session_id: The session ID to resume.
            prompt: Optional follow-up instruction.
            role: Role for the resumed agent.
            nickname: Optional label.
        """
        try:
            agent_id = _mgr().resume(
                session_id=session_id,
                prompt=prompt,
                role=role,
                nickname=nickname,
                **_inherit_parent_context(),
            )
            entry = _mgr().get_entry(agent_id)
            nick = entry.nickname if entry else nickname or role
            return (
                f"[resumed] agent_id={agent_id} nickname={nick} "
                f"from session={session_id}\n"
                f"Use wait_for_agents(agent_ids=[\"{agent_id}\"]) to block until it finishes."
            )
        except Exception as exc:
            return f"[error] {exc}"


# ── list_agents ───────────────────────────────────────────────────────────────

class ListAgentsTool(Tool):
    name = "list_agents"
    description = (
        "List all spawned agents and their current status. "
        "Shows agent_id, nickname, role, status, depth, and elapsed time."
    )

    @property
    def parameters_schema(self):
        return {"type": "object", "properties": {}}

    def run(self) -> str:
        return _mgr().summary()
