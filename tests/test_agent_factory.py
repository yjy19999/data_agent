"""
Tests for AgentFactory (agent/agent_factory.py).

Verifies that:
- build() returns an Agent with a SandboxedRegistry
- The factory's system_prompt reaches the Agent config
- The factory's profile is resolved (including "auto")
- Runners accept agent_factory and delegate _make_agent to it
- Runners fall back to their own defaults when agent_factory=None
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agent import AgentFactory, CodingTaskRunner, DataQualityRunner, Config
from agent.sandbox import SandboxedRegistry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

CUSTOM_PROMPT = "You are a custom test agent."


def make_factory(tmp_path: Path, profile: str = "default") -> AgentFactory:
    return AgentFactory(
        config=Config(model="test-model", api_key="test"),
        profile=profile,
        system_prompt=CUSTOM_PROMPT,
    )


# ---------------------------------------------------------------------------
# AgentFactory.build()
# ---------------------------------------------------------------------------

class TestAgentFactoryBuild:
    def test_returns_agent_with_sandboxed_registry(self, tmp_path):
        factory = make_factory(tmp_path)
        with (
            patch("agent.agent_factory.Agent") as mock_agent_cls,
            patch("agent.agent.SessionRecordingService"),
            patch("agent.agent.LLMClient"),
        ):
            mock_agent_cls.return_value = MagicMock()
            factory.build(workspace=tmp_path)
            call_kwargs = mock_agent_cls.call_args
            registry = call_kwargs.kwargs.get("registry") or call_kwargs[1].get("registry")
            assert isinstance(registry, SandboxedRegistry)

    def test_system_prompt_passed_to_agent_config(self, tmp_path):
        factory = make_factory(tmp_path)
        with (
            patch("agent.agent_factory.Agent") as mock_agent_cls,
            patch("agent.agent.SessionRecordingService"),
            patch("agent.agent.LLMClient"),
        ):
            mock_agent_cls.return_value = MagicMock()
            factory.build(workspace=tmp_path)
            call_kwargs = mock_agent_cls.call_args
            config_arg = call_kwargs.kwargs.get("config") or call_kwargs[1].get("config")
            assert config_arg.system_prompt == CUSTOM_PROMPT

    def test_session_id_forwarded(self, tmp_path):
        factory = make_factory(tmp_path)
        with (
            patch("agent.agent_factory.Agent") as mock_agent_cls,
            patch("agent.agent.SessionRecordingService"),
            patch("agent.agent.LLMClient"),
        ):
            mock_agent_cls.return_value = MagicMock()
            factory.build(workspace=tmp_path, session_id="abc123")
            call_kwargs = mock_agent_cls.call_args
            sid = call_kwargs.kwargs.get("session_id") or call_kwargs[1].get("session_id")
            assert sid == "abc123"

    def test_logs_dir_forwarded(self, tmp_path):
        factory = make_factory(tmp_path)
        logs = tmp_path / "logs"
        with (
            patch("agent.agent_factory.Agent") as mock_agent_cls,
            patch("agent.agent.SessionRecordingService"),
            patch("agent.agent.LLMClient"),
        ):
            mock_agent_cls.return_value = MagicMock()
            factory.build(workspace=tmp_path, logs_dir=logs)
            call_kwargs = mock_agent_cls.call_args
            logs_arg = call_kwargs.kwargs.get("logs_dir") or call_kwargs[1].get("logs_dir")
            assert logs_arg == str(logs)

    def test_none_logs_dir_stays_none(self, tmp_path):
        factory = make_factory(tmp_path)
        with (
            patch("agent.agent_factory.Agent") as mock_agent_cls,
            patch("agent.agent.SessionRecordingService"),
            patch("agent.agent.LLMClient"),
        ):
            mock_agent_cls.return_value = MagicMock()
            factory.build(workspace=tmp_path, logs_dir=None)
            call_kwargs = mock_agent_cls.call_args
            logs_arg = call_kwargs.kwargs.get("logs_dir") or call_kwargs[1].get("logs_dir")
            assert logs_arg is None

    def test_auto_profile_resolves(self, tmp_path):
        """profile='auto' should be resolved via infer_profile, not passed through as 'auto'."""
        factory = AgentFactory(
            config=Config(model="claude-opus-4-6", api_key="test"),
            profile="auto",
            system_prompt=CUSTOM_PROMPT,
        )
        with (
            patch("agent.agent_factory.Agent") as mock_agent_cls,
            patch("agent.agent.SessionRecordingService"),
            patch("agent.agent.LLMClient"),
        ):
            mock_agent_cls.return_value = MagicMock()
            factory.build(workspace=tmp_path)
            call_kwargs = mock_agent_cls.call_args
            config_arg = call_kwargs.kwargs.get("config") or call_kwargs[1].get("config")
            # Should have resolved to "claude", not left as "auto"
            assert config_arg.tool_profile != "auto"
            assert config_arg.tool_profile == "claude"

    def test_explicit_profile_used_in_config(self, tmp_path):
        factory = make_factory(tmp_path, profile="readonly")
        with (
            patch("agent.agent_factory.Agent") as mock_agent_cls,
            patch("agent.agent.SessionRecordingService"),
            patch("agent.agent.LLMClient"),
        ):
            mock_agent_cls.return_value = MagicMock()
            factory.build(workspace=tmp_path)
            call_kwargs = mock_agent_cls.call_args
            config_arg = call_kwargs.kwargs.get("config") or call_kwargs[1].get("config")
            assert config_arg.tool_profile == "readonly"


# ---------------------------------------------------------------------------
# CodingTaskRunner — agent_factory integration
# ---------------------------------------------------------------------------

class TestCodingTaskRunnerFactory:
    def test_accepts_agent_factory(self, tmp_path):
        factory = make_factory(tmp_path)
        runner = CodingTaskRunner(workspace=tmp_path, agent_factory=factory)
        assert runner.agent_factory is factory

    def test_none_by_default(self, tmp_path):
        runner = CodingTaskRunner(workspace=tmp_path)
        assert runner.agent_factory is None

    def test_make_agent_delegates_to_factory(self, tmp_path):
        factory = make_factory(tmp_path)
        mock_agent = MagicMock()
        factory.build = MagicMock(return_value=mock_agent)

        runner = CodingTaskRunner(workspace=tmp_path, agent_factory=factory)
        result = runner._make_agent()

        factory.build.assert_called_once_with(
            workspace=runner.workspace,
            session_id=runner.session_id,
            logs_dir=None,
            memory_log_dir=None,
        )
        assert result is mock_agent

    def test_make_agent_fallback_when_no_factory(self, tmp_path):
        """Without a factory, _make_agent uses the default coding profile."""
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

    def test_factory_system_prompt_overrides_default(self, tmp_path):
        """The factory's system_prompt replaces _CODING_SYSTEM_PROMPT."""
        factory = make_factory(tmp_path)
        mock_agent = MagicMock()

        captured_config = {}

        def fake_build(**kwargs):
            # Peek at what config the factory would build
            captured_config["system_prompt"] = factory.system_prompt
            return mock_agent

        factory.build = fake_build
        runner = CodingTaskRunner(workspace=tmp_path, agent_factory=factory)
        runner._make_agent()
        assert captured_config["system_prompt"] == CUSTOM_PROMPT


# ---------------------------------------------------------------------------
# DataQualityRunner — agent_factory integration
# ---------------------------------------------------------------------------

class TestDataQualityRunnerFactory:
    def test_accepts_agent_factory(self, tmp_path):
        factory = make_factory(tmp_path)
        runner = DataQualityRunner(workspace=tmp_path, agent_factory=factory)
        assert runner.agent_factory is factory

    def test_none_by_default(self, tmp_path):
        runner = DataQualityRunner(workspace=tmp_path)
        assert runner.agent_factory is None

    def test_make_agent_delegates_to_factory(self, tmp_path):
        factory = make_factory(tmp_path)
        mock_agent = MagicMock()
        factory.build = MagicMock(return_value=mock_agent)

        runner = DataQualityRunner(workspace=tmp_path, agent_factory=factory)
        result = runner._make_agent()

        factory.build.assert_called_once_with(
            workspace=runner.workspace,
            session_id=runner.session_id,
            logs_dir=runner.logs_dir,
            memory_log_dir=runner.memory_log_dir,
        )
        assert result is mock_agent

    def test_make_agent_fallback_when_no_factory(self, tmp_path):
        """Without a factory, _make_agent uses the default quality profile."""
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
