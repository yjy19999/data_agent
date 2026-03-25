"""
RunnerRegistry — maps task-type names to default AgentFactory configurations.

This is the central place to control which tool profile and system prompt
each task type uses by default, without touching any runner code.

Profile priority (highest → lowest):
1. Explicit ``agent_factory`` kwarg passed to a runner constructor
2. Per-runner env var: ``LLM_{NAME}_PROFILE`` (e.g. ``LLM_CODING_PROFILE=claude``)
3. Global ``LLM_TOOL_PROFILE`` when it is not ``"auto"``
4. The profile registered here for this task type
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from .agent_factory import AgentFactory
from .config import Config


@dataclass
class RunnerEntry:
    """A registered task type with its default profile and system prompt."""

    name: str
    profile: str        # tool profile name or "auto"
    system_prompt: str
    description: str = ""


class RunnerRegistry:
    """Maps task-type names to default ``AgentFactory`` configurations."""

    def __init__(self) -> None:
        self._entries: dict[str, RunnerEntry] = {}

    def register(
        self,
        name: str,
        profile: str,
        system_prompt: str,
        description: str = "",
    ) -> None:
        """Register (or replace) a task type.

        Args:
            name: Unique task-type key, e.g. ``"coding"`` or ``"quality"``.
            profile: Default tool profile for this task type. Use ``"auto"``
                to fall back to ``config.tool_profile`` / model-name inference.
            system_prompt: System prompt that defines the agent's role.
            description: Human-readable description (for introspection only).
        """
        self._entries[name] = RunnerEntry(
            name=name,
            profile=profile,
            system_prompt=system_prompt,
            description=description,
        )

    def get(self, name: str) -> RunnerEntry | None:
        """Return the entry for *name*, or ``None`` if not registered."""
        return self._entries.get(name)

    def names(self) -> list[str]:
        """Return all registered task-type names."""
        return list(self._entries.keys())

    def make_factory(self, name: str, config: Config) -> AgentFactory:
        """Build an ``AgentFactory`` for the named task type.

        Profile resolution order:
        - If ``config.tool_profile`` is not ``"auto"``: use that (env-var override).
        - Else: use the profile registered for *name* (may itself be ``"auto"``,
          which ``AgentFactory.build()`` resolves via model-name inference).

        Raises:
            KeyError: if *name* is not registered.
        """
        entry = self._entries.get(name)
        if entry is None:
            raise KeyError(
                f"No runner registered for task type '{name}'. "
                f"Registered types: {self.names()}"
            )
        # Per-runner env var takes priority (e.g. LLM_CODING_PROFILE, LLM_QUALITY_PROFILE)
        per_runner_env = f"LLM_{name.upper()}_PROFILE"
        if runner_profile := os.getenv(per_runner_env, ""):
            profile = runner_profile
        elif config.tool_profile != "auto":
            profile = config.tool_profile
        else:
            profile = entry.profile
        return AgentFactory(
            config=config,
            profile=profile,
            system_prompt=entry.system_prompt,
        )

    def __repr__(self) -> str:
        entries = ", ".join(
            f"{n!r}(profile={e.profile!r})" for n, e in self._entries.items()
        )
        return f"RunnerRegistry({entries})"


# Global default registry — runners register themselves at import time.
runner_registry = RunnerRegistry()
