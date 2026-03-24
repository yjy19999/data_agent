"""
Tests for RunnerRegistry (agent/runner_registry.py).

Verifies that:
- Entries can be registered and retrieved
- make_factory returns an AgentFactory with the correct profile/prompt
- Profile priority: config.tool_profile > registry entry > "auto" inference
- Both runners self-register at import time
- Changing a registry entry affects subsequent runner._make_agent() calls
- KeyError is raised for unknown task types
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from agent import (
    AgentFactory,
    CodingTaskRunner,
    Config,
    DataQualityRunner,
    RunnerEntry,
    RunnerRegistry,
    runner_registry,
)
from agent.sandbox import SandboxedRegistry
from agent.task_runner import _CODING_SYSTEM_PROMPT
from agent.data_quality_runner import _QUALITY_SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# RunnerRegistry — basic operations
# ---------------------------------------------------------------------------

class TestRunnerRegistryBasics:
    def setup_method(self):
        self.reg = RunnerRegistry()

    def test_register_and_get(self):
        self.reg.register("mytype", profile="claude", system_prompt="You are X.")
        entry = self.reg.get("mytype")
        assert isinstance(entry, RunnerEntry)
        assert entry.name == "mytype"
        assert entry.profile == "claude"
        assert entry.system_prompt == "You are X."

    def test_get_unknown_returns_none(self):
        assert self.reg.get("nonexistent") is None

    def test_names_returns_registered_keys(self):
        self.reg.register("a", "auto", "prompt A")
        self.reg.register("b", "readonly", "prompt B")
        assert set(self.reg.names()) == {"a", "b"}

    def test_register_overwrites_existing(self):
        self.reg.register("x", "auto", "old prompt")
        self.reg.register("x", "opencode", "new prompt")
        entry = self.reg.get("x")
        assert entry.profile == "opencode"
        assert entry.system_prompt == "new prompt"

    def test_description_stored(self):
        self.reg.register("x", "auto", "prompt", description="My task type")
        assert self.reg.get("x").description == "My task type"

    def test_repr_shows_names_and_profiles(self):
        self.reg.register("coding", "auto", "prompt")
        r = repr(self.reg)
        assert "coding" in r
        assert "auto" in r


# ---------------------------------------------------------------------------
# RunnerRegistry.make_factory — profile priority
# ---------------------------------------------------------------------------

class TestMakeFactory:
    def setup_method(self):
        self.reg = RunnerRegistry()
        self.reg.register("mytask", profile="readonly", system_prompt="You are Y.")

    def test_returns_agent_factory(self):
        factory = self.reg.make_factory("mytask", Config(api_key="test"))
        assert isinstance(factory, AgentFactory)

    def test_factory_carries_system_prompt(self):
        factory = self.reg.make_factory("mytask", Config(api_key="test"))
        assert factory.system_prompt == "You are Y."

    def test_registry_profile_used_when_config_is_auto(self):
        """Registry profile wins when config.tool_profile == 'auto'."""
        config = Config(api_key="test", tool_profile="auto")
        factory = self.reg.make_factory("mytask", config)
        assert factory.profile == "readonly"

    def test_config_profile_overrides_registry(self):
        """Explicit config.tool_profile (not 'auto') overrides the registry."""
        config = Config(api_key="test", tool_profile="opencode")
        factory = self.reg.make_factory("mytask", config)
        assert factory.profile == "opencode"

    def test_unknown_task_raises_key_error(self):
        with pytest.raises(KeyError, match="nonexistent"):
            self.reg.make_factory("nonexistent", Config(api_key="test"))

    def test_error_message_lists_registered_types(self):
        with pytest.raises(KeyError) as exc_info:
            self.reg.make_factory("nope", Config(api_key="test"))
        assert "mytask" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Global runner_registry — built-in registrations
# ---------------------------------------------------------------------------

class TestGlobalRegistry:
    def test_coding_is_registered(self):
        entry = runner_registry.get("coding")
        assert entry is not None
        assert entry.profile == "auto"
        assert entry.system_prompt == _CODING_SYSTEM_PROMPT

    def test_quality_is_registered(self):
        entry = runner_registry.get("quality")
        assert entry is not None
        assert entry.profile == "auto"
        assert entry.system_prompt == _QUALITY_SYSTEM_PROMPT

    def test_both_types_in_names(self):
        assert "coding" in runner_registry.names()
        assert "quality" in runner_registry.names()


# ---------------------------------------------------------------------------
# CodingTaskRunner — uses registry in _make_agent fallback
# ---------------------------------------------------------------------------

class TestCodingTaskRunnerUsesRegistry:
    def test_make_agent_uses_registry_system_prompt(self, tmp_path):
        runner = CodingTaskRunner(
            workspace=tmp_path,
            config=Config(model="test", api_key="test"),
        )
        with (
            patch("agent.agent_factory.Agent") as mock_agent_cls,
            patch("agent.agent.SessionRecordingService"),
            patch("agent.agent.LLMClient"),
        ):
            mock_agent_cls.return_value = MagicMock()
            runner._make_agent()
            call_kwargs = mock_agent_cls.call_args
            config_arg = call_kwargs.kwargs.get("config") or call_kwargs[1].get("config")
            assert config_arg.system_prompt == _CODING_SYSTEM_PROMPT

    def test_make_agent_uses_sandboxed_registry(self, tmp_path):
        runner = CodingTaskRunner(
            workspace=tmp_path,
            config=Config(model="test", api_key="test"),
        )
        with (
            patch("agent.agent_factory.Agent") as mock_agent_cls,
            patch("agent.agent.SessionRecordingService"),
            patch("agent.agent.LLMClient"),
        ):
            mock_agent_cls.return_value = MagicMock()
            runner._make_agent()
            call_kwargs = mock_agent_cls.call_args
            registry = call_kwargs.kwargs.get("registry") or call_kwargs[1].get("registry")
            assert isinstance(registry, SandboxedRegistry)

    def test_registry_profile_change_affects_runner(self, tmp_path):
        """Changing the registry entry changes the profile used by the runner."""
        original_entry = runner_registry.get("coding")
        try:
            runner_registry.register("coding", profile="readonly", system_prompt=_CODING_SYSTEM_PROMPT)
            config = Config(model="test", api_key="test", tool_profile="auto")
            factory = runner_registry.make_factory("coding", config)
            assert factory.profile == "readonly"
        finally:
            # Restore original entry
            runner_registry.register(
                "coding",
                profile=original_entry.profile,
                system_prompt=original_entry.system_prompt,
                description=original_entry.description,
            )

    def test_config_tool_profile_overrides_registry(self, tmp_path):
        """LLM_TOOL_PROFILE env var (config.tool_profile) wins over registry."""
        config = Config(model="test", api_key="test", tool_profile="minimal")
        factory = runner_registry.make_factory("coding", config)
        assert factory.profile == "minimal"


# ---------------------------------------------------------------------------
# DataQualityRunner — uses registry in _make_agent fallback
# ---------------------------------------------------------------------------

class TestDataQualityRunnerUsesRegistry:
    def test_make_agent_uses_registry_system_prompt(self, tmp_path):
        runner = DataQualityRunner(
            workspace=tmp_path,
            config=Config(model="test", api_key="test"),
        )
        with (
            patch("agent.agent_factory.Agent") as mock_agent_cls,
            patch("agent.agent.SessionRecordingService"),
            patch("agent.agent.LLMClient"),
        ):
            mock_agent_cls.return_value = MagicMock()
            runner._make_agent()
            call_kwargs = mock_agent_cls.call_args
            config_arg = call_kwargs.kwargs.get("config") or call_kwargs[1].get("config")
            assert config_arg.system_prompt == _QUALITY_SYSTEM_PROMPT

    def test_make_agent_uses_sandboxed_registry(self, tmp_path):
        runner = DataQualityRunner(
            workspace=tmp_path,
            config=Config(model="test", api_key="test"),
        )
        with (
            patch("agent.agent_factory.Agent") as mock_agent_cls,
            patch("agent.agent.SessionRecordingService"),
            patch("agent.agent.LLMClient"),
        ):
            mock_agent_cls.return_value = MagicMock()
            runner._make_agent()
            call_kwargs = mock_agent_cls.call_args
            registry = call_kwargs.kwargs.get("registry") or call_kwargs[1].get("registry")
            assert isinstance(registry, SandboxedRegistry)

    def test_registry_profile_change_affects_runner(self, tmp_path):
        original_entry = runner_registry.get("quality")
        try:
            runner_registry.register("quality", profile="readonly", system_prompt=_QUALITY_SYSTEM_PROMPT)
            config = Config(model="test", api_key="test", tool_profile="auto")
            factory = runner_registry.make_factory("quality", config)
            assert factory.profile == "readonly"
        finally:
            runner_registry.register(
                "quality",
                profile=original_entry.profile,
                system_prompt=original_entry.system_prompt,
                description=original_entry.description,
            )
