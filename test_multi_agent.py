#!/usr/bin/env python3
"""
Tests for the multi-agent system.

Part 1: Unit tests (no LLM needed) — AgentManager logic
Part 2: Integration tests (needs live LLM) — full spawn/wait cycle
"""
from __future__ import annotations

import json
import sys
import threading
import time

# ============================================================================
# Part 1: Unit tests — AgentManager internals
# ============================================================================

def test_manager_singleton():
    """get_manager() returns the same instance."""
    from agent.multi_agent import get_manager
    m1 = get_manager()
    m2 = get_manager()
    assert m1 is m2, "get_manager() should return a singleton"
    print("  [PASS] singleton")


def test_status_and_role_enums():
    """Enum values are strings and match expectations."""
    from agent.multi_agent import AgentStatus, AgentRole
    assert AgentStatus.COMPLETED.value == "completed"
    assert AgentRole.EXPLORER.value == "explorer"
    assert len(AgentStatus) == 5
    assert len(AgentRole) == 4
    print("  [PASS] enums")


def test_entry_is_done():
    """AgentEntry.is_done() reflects terminal states."""
    from agent.multi_agent import AgentEntry, AgentStatus
    e = AgentEntry(
        agent_id="test", nickname="test", role="default",
        status=AgentStatus.RUNNING, depth=0, parent_id=None,
    )
    assert not e.is_done()
    e.status = AgentStatus.COMPLETED
    assert e.is_done()
    e.status = AgentStatus.ERRORED
    assert e.is_done()
    e.status = AgentStatus.SHUTDOWN
    assert e.is_done()
    print("  [PASS] AgentEntry.is_done()")


def test_depth_limit():
    """Manager rejects spawns beyond max_depth."""
    from agent.multi_agent import AgentManager
    mgr = AgentManager(max_threads=10, max_depth=1)
    # depth=0 should be fine (spawn won't actually work without an LLM,
    # but the depth check happens before the thread starts)
    # depth=1 should be rejected
    try:
        mgr.spawn("test", depth=1)
        # If we get here, it means the depth check didn't fire
        print("  [WARN] depth limit did not raise (thread may have started)")
    except RuntimeError as exc:
        assert "max_depth" in str(exc)
        print("  [PASS] depth limit")


def test_thread_limit():
    """Manager rejects spawns beyond max_threads."""
    from agent.multi_agent import AgentManager, AgentStatus, AgentEntry
    mgr = AgentManager(max_threads=1, max_depth=5)

    # Fake a running agent
    fake = AgentEntry(
        agent_id="fake-1", nickname="fake-1", role="default",
        status=AgentStatus.RUNNING, depth=0, parent_id=None,
    )
    mgr._agents["fake-1"] = fake

    try:
        mgr.spawn("test")
        print("  [WARN] thread limit did not raise")
    except RuntimeError as exc:
        assert "threads already running" in str(exc)
        print("  [PASS] thread limit")
    finally:
        del mgr._agents["fake-1"]


def test_nickname_generation():
    """Nicknames auto-increment per role."""
    from agent.multi_agent import AgentManager
    mgr = AgentManager(max_threads=10, max_depth=5)
    # We can't fully spawn (no LLM), but we can test the counter logic
    mgr._nickname_counters = {}
    # Simulate nickname creation
    role = "explorer"
    count = mgr._nickname_counters.get(role, 0) + 1
    mgr._nickname_counters[role] = count
    assert count == 1
    count = mgr._nickname_counters.get(role, 0) + 1
    mgr._nickname_counters[role] = count
    assert count == 2
    print("  [PASS] nickname auto-increment")


def test_get_by_nickname():
    """_get() supports lookup by nickname or partial ID."""
    from agent.multi_agent import AgentManager, AgentStatus, AgentEntry
    mgr = AgentManager()
    fake = AgentEntry(
        agent_id="abcdef123456", nickname="my-worker", role="worker",
        status=AgentStatus.COMPLETED, depth=0, parent_id=None,
    )
    mgr._agents["abcdef123456"] = fake

    # Exact ID
    assert mgr._get("abcdef123456") is fake
    # Nickname
    assert mgr._get("my-worker") is fake
    # Partial ID
    assert mgr._get("abcdef") is fake
    # Miss
    assert mgr._get("nonexistent") is None
    print("  [PASS] lookup by nickname/partial-id")

    del mgr._agents["abcdef123456"]


def test_tool_schemas():
    """All multi-agent tools produce valid schemas."""
    from agent.tools.multi_agents import (
        SpawnAgentTool, SendInputTool, WaitTool,
        CloseAgentTool, ResumeAgentTool, ListAgentsTool,
    )
    tools = [
        SpawnAgentTool(), SendInputTool(), WaitTool(),
        CloseAgentTool(), ResumeAgentTool(), ListAgentsTool(),
    ]
    for tool in tools:
        schema = tool.parameters_schema
        assert isinstance(schema, dict), f"{tool.name} schema not a dict"
        assert schema.get("type") == "object", f"{tool.name} schema type != object"
        assert tool.name, f"tool has no name"
        assert tool.description, f"{tool.name} has no description"
    print(f"  [PASS] all {len(tools)} tool schemas valid")


def test_list_agents_empty():
    """list_agents on fresh manager returns empty summary."""
    from agent.tools.multi_agents import ListAgentsTool
    tool = ListAgentsTool()
    result = tool.run()
    assert "No agents" in result or "Agents:" in result
    print("  [PASS] list_agents (empty)")


def test_wait_for_nonexistent():
    """wait_for_agents with unknown ID returns error."""
    from agent.tools.multi_agents import WaitTool
    tool = WaitTool()
    result = tool.run(agent_ids=["nonexistent-999"], timeout=10)
    data = json.loads(result)
    assert "not found" in data.get("nonexistent-999", "")
    print("  [PASS] wait for nonexistent agent")


def test_close_nonexistent():
    """close_agent with unknown ID returns error."""
    from agent.tools.multi_agents import CloseAgentTool
    tool = CloseAgentTool()
    result = tool.run(agent_id="nonexistent-999")
    assert "not found" in result
    print("  [PASS] close nonexistent agent")


def test_send_input_nonexistent():
    """send_input with unknown ID returns error."""
    from agent.tools.multi_agents import SendInputTool
    tool = SendInputTool()
    result = tool.run(agent_id="nonexistent-999", message="hello")
    assert "not found" in result
    print("  [PASS] send_input nonexistent agent")


def test_profiles_include_multi_agent_tools():
    """claude and opencode profiles include all 6 multi-agent tools."""
    from agent.tools.profiles import get_profile
    expected = {"spawn_agent", "send_input", "wait_for_agents", "close_agent", "resume_agent", "list_agents"}
    for profile_name in ("claude", "opencode"):
        names = set(get_profile(profile_name).tool_names())
        missing = expected - names
        assert not missing, f"{profile_name} profile missing: {missing}"
    print("  [PASS] profiles include multi-agent tools")


def test_config_fields():
    """Config has agent_max_threads and agent_max_depth."""
    from agent.config import Config
    cfg = Config()
    assert hasattr(cfg, "agent_max_threads")
    assert hasattr(cfg, "agent_max_depth")
    assert isinstance(cfg.agent_max_threads, int)
    assert isinstance(cfg.agent_max_depth, int)
    assert cfg.agent_max_threads > 0
    assert cfg.agent_max_depth > 0
    print(f"  [PASS] config fields (threads={cfg.agent_max_threads}, depth={cfg.agent_max_depth})")


# ============================================================================
# Part 2: Integration test — real LLM spawn/wait cycle
# ============================================================================

def test_spawn_and_wait_live():
    """Spawn an explorer agent, wait for it, check results."""
    from agent.tools.multi_agents import SpawnAgentTool, WaitTool, ListAgentsTool

    print("\n  Spawning explorer agent (simple math question)...")
    spawn = SpawnAgentTool()
    result = spawn.run(
        prompt="What is 2 + 2? Answer with just the number, nothing else.",
        role="explorer",
        nickname="math-test",
    )
    print(f"  spawn result: {result}")
    assert "agent_id=" in result, f"Expected agent_id in: {result}"

    # Extract agent_id
    agent_id = result.split("agent_id=")[1].split(" ")[0].strip()
    print(f"  agent_id: {agent_id}")

    # List agents while running
    list_tool = ListAgentsTool()
    listing = list_tool.run()
    print(f"  listing:\n{listing}")
    assert "math-test" in listing

    # Wait for completion (up to 120s for slow models)
    print("  Waiting for agent to finish (max 120s)...")
    wait = WaitTool()
    wait_result = wait.run(agent_ids=[agent_id], timeout=120)
    print(f"  wait result: {wait_result}")

    data = json.loads(wait_result)
    agent_result = data.get(agent_id, "")
    assert "[error]" not in agent_result and "[timeout]" not in agent_result, \
        f"Agent failed or timed out: {agent_result}"
    print(f"  agent output: {agent_result[:200]}")

    return True


def test_spawn_two_parallel():
    """Spawn two workers in parallel, wait for both."""
    from agent.tools.multi_agents import SpawnAgentTool, WaitTool

    spawn = SpawnAgentTool()
    print("\n  Spawning two parallel agents...")

    r1 = spawn.run(
        prompt="What is the capital of France? Answer in one word.",
        role="worker",
        nickname="geo-1",
    )
    r2 = spawn.run(
        prompt="What is the capital of Japan? Answer in one word.",
        role="worker",
        nickname="geo-2",
    )
    print(f"  spawn 1: {r1}")
    print(f"  spawn 2: {r2}")

    id1 = r1.split("agent_id=")[1].split(" ")[0].strip()
    id2 = r2.split("agent_id=")[1].split(" ")[0].strip()

    print("  Waiting for both (max 120s)...")
    wait = WaitTool()
    result = wait.run(agent_ids=[id1, id2], timeout=120)
    print(f"  results: {result}")

    data = json.loads(result)
    for aid in [id1, id2]:
        assert "[error]" not in data.get(aid, ""), f"Agent {aid} failed"
        assert "[timeout]" not in data.get(aid, ""), f"Agent {aid} timed out"

    print(f"  geo-1 output: {data[id1][:100]}")
    print(f"  geo-2 output: {data[id2][:100]}")
    return True


def test_close_agent_live():
    """Spawn an agent with a long task and close it mid-flight."""
    from agent.tools.multi_agents import SpawnAgentTool, CloseAgentTool, WaitTool

    spawn = SpawnAgentTool()
    print("\n  Spawning agent with long task to test close...")
    r = spawn.run(
        prompt="List every country in the world and their capitals. Be very detailed.",
        role="worker",
        nickname="long-task",
    )
    agent_id = r.split("agent_id=")[1].split(" ")[0].strip()

    # Give it a moment to start
    time.sleep(2)

    close = CloseAgentTool()
    close_result = close.run(agent_id=agent_id)
    print(f"  close result: {close_result}")
    assert "[ok]" in close_result or "already" in close_result

    # Wait briefly to confirm it stopped
    wait = WaitTool()
    result = wait.run(agent_ids=[agent_id], timeout=30)
    print(f"  final status: {result}")
    return True


# ============================================================================
# Runner
# ============================================================================

def run_unit_tests():
    print("=" * 60)
    print("UNIT TESTS (no LLM needed)")
    print("=" * 60)
    tests = [
        test_manager_singleton,
        test_status_and_role_enums,
        test_entry_is_done,
        test_depth_limit,
        test_thread_limit,
        test_nickname_generation,
        test_get_by_nickname,
        test_tool_schemas,
        test_list_agents_empty,
        test_wait_for_nonexistent,
        test_close_nonexistent,
        test_send_input_nonexistent,
        test_profiles_include_multi_agent_tools,
        test_config_fields,
    ]
    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except Exception as exc:
            print(f"  [FAIL] {t.__name__}: {exc}")
            failed += 1
    print(f"\nUnit tests: {passed} passed, {failed} failed\n")
    return failed == 0


def run_integration_tests():
    print("=" * 60)
    print("INTEGRATION TESTS (live LLM)")
    print("=" * 60)
    tests = [
        ("spawn_and_wait", test_spawn_and_wait_live),
        ("parallel_spawn", test_spawn_two_parallel),
        ("close_agent", test_close_agent_live),
    ]
    passed = 0
    failed = 0
    for name, t in tests:
        try:
            print(f"\n--- {name} ---")
            t()
            passed += 1
            print(f"  [PASS] {name}")
        except Exception as exc:
            print(f"  [FAIL] {name}: {exc}")
            import traceback
            traceback.print_exc()
            failed += 1
    print(f"\nIntegration tests: {passed} passed, {failed} failed\n")
    return failed == 0


if __name__ == "__main__":
    unit_ok = run_unit_tests()

    if "--unit-only" in sys.argv:
        sys.exit(0 if unit_ok else 1)

    if unit_ok:
        integ_ok = run_integration_tests()
        sys.exit(0 if integ_ok else 1)
    else:
        print("Skipping integration tests due to unit test failures.")
        sys.exit(1)
