"""
AgentFactory — builds a configured Agent for a specific task type.

Usage::

    from agent import AgentFactory, Config
    from agent.data_quality_runner import _QUALITY_SYSTEM_PROMPT

    factory = AgentFactory(
        config=Config(model="claude-opus-4-6", api_key="..."),
        profile="claude",
        system_prompt=_QUALITY_SYSTEM_PROMPT,
    )

    runner = DataQualityRunner(workspace="/tmp/ws", agent_factory=factory)

The factory separates *what tools to use* and *what role the agent plays*
from the runner's workspace/session plumbing. Pass the same factory to
multiple runners, or swap factories without touching runner code.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .agent import Agent
from .config import Config
from .sandbox import SandboxedRegistry
from .tools.profiles import get_profile, infer_profile


@dataclass
class AgentFactory:
    """
    Holds the tool profile and system prompt for a task type.

    Call ``build()`` to get a fully wired Agent bound to a specific
    workspace and session. The runner supplies workspace/session context
    at build time; the factory supplies the role (tools + system prompt).

    Args:
        config: LLM configuration (model, API key, etc.).
        profile: Tool profile name (``"claude"``, ``"opencode"``, ``"default"``,
            etc.) or ``"auto"`` to infer from the model name.
        system_prompt: The system prompt that defines the agent's role.
    """

    config: Config
    profile: str
    system_prompt: str

    def build(
        self,
        workspace: Path,
        session_id: str | None = None,
        logs_dir: Path | None = None,
        memory_log_dir: Path | None = None,
    ) -> Agent:
        """
        Build and return an Agent sandboxed to *workspace*.

        Args:
            workspace: All file operations are restricted to this folder.
            session_id: Optional session ID for trace files.
            logs_dir: Directory for trajectory/trace files.
            memory_log_dir: Directory for compression memory logs.
        """
        profile_name = self.profile
        if profile_name == "auto":
            profile_name = infer_profile(self.config.model)

        base_registry = get_profile(profile_name).build_registry()
        sandbox = SandboxedRegistry(workspace)
        for schema in base_registry.schemas():
            tool = base_registry.get(schema["function"]["name"])
            if tool:
                sandbox.register(tool)

        system_prompt = self.system_prompt.rstrip() + f"\n\nYour workspace directory: {workspace}"

        return Agent(
            config=Config(
                base_url=self.config.base_url,
                api_key=self.config.api_key,
                model=self.config.model,
                stream=self.config.stream,
                max_tool_iterations=self.config.max_tool_iterations,
                tool_profile=profile_name,
                context_limit=self.config.context_limit,
                compression_threshold=self.config.compression_threshold,
                system_prompt=system_prompt,
            ),
            registry=sandbox,
            session_id=session_id,
            logs_dir=str(logs_dir) if logs_dir else None,
            memory_log_dir=str(memory_log_dir) if memory_log_dir else None,
        )
