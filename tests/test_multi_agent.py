from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from agent.config import Config
from agent.multi_agent import AgentEntry, AgentManager, AgentStatus, agent_execution_context
from agent.sandbox import SandboxedRegistry
from agent.tools.multi_agents import SpawnAgentTool


def test_spawn_agent_inherits_parent_sandbox_context(tmp_path):
    cfg = Config(model="claude-test", api_key="test", tool_profile="claude")
    sandbox = SandboxedRegistry(tmp_path)

    fake_manager = MagicMock()
    fake_manager.spawn.return_value = "child123"
    fake_manager.get_entry.return_value = AgentEntry(
        agent_id="child123",
        nickname="explorer-1",
        role="explorer",
        status=AgentStatus.PENDING,
        depth=1,
        parent_id="parent123",
    )

    with patch("agent.tools.multi_agents._mgr", return_value=fake_manager):
        with agent_execution_context(
            config=cfg,
            registry=sandbox,
            agent_id="parent123",
            depth=0,
        ):
            result = SpawnAgentTool().run(prompt="inspect", role="explorer")

    kwargs = fake_manager.spawn.call_args.kwargs
    assert kwargs["parent_id"] == "parent123"
    assert kwargs["depth"] == 1
    assert kwargs["config"].model == cfg.model
    assert isinstance(kwargs["registry"], SandboxedRegistry)
    assert kwargs["registry"] is not sandbox
    assert kwargs["registry"].workspace == Path(tmp_path).resolve()
    assert "agent_id=child123" in result
    assert "wait_for_agents(agent_ids=[\"child123\"])" in result


def test_send_input_restart_reuses_stored_registry_and_config(tmp_path):
    cfg = Config(model="claude-test", api_key="test", tool_profile="claude")
    sandbox = SandboxedRegistry(tmp_path)
    manager = AgentManager()
    entry = AgentEntry(
        agent_id="child123",
        nickname="worker-1",
        role="worker",
        status=AgentStatus.COMPLETED,
        depth=1,
        parent_id="parent123",
        result="done",
        config=cfg,
        registry=sandbox,
    )
    manager._agents[entry.agent_id] = entry

    thread_args = {}

    class FakeThread:
        def __init__(self, *, target, args, daemon, name):
            thread_args["target"] = target
            thread_args["args"] = args
            thread_args["daemon"] = daemon
            thread_args["name"] = name

        def start(self):
            thread_args["started"] = True

    with patch("agent.multi_agent.threading.Thread", FakeThread):
        result = manager.send_input(entry.agent_id, "follow up")

    assert "[ok] restarted" in result
    assert thread_args["started"] is True
    assert thread_args["args"][2].model == cfg.model
    assert thread_args["args"][3] is sandbox
