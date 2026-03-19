from __future__ import annotations

from agent.tools.profiles import get_profile, infer_profile


def test_opencode_profile_is_registered():
    profile = get_profile("opencode")
    tool_names = profile.tool_names()

    assert profile.name == "opencode"
    assert "read" in tool_names
    assert "bash" in tool_names
    assert "apply_patch" in tool_names
    assert "batch" in tool_names


def test_infer_profile_detects_opencode():
    assert infer_profile("opencode-dev") == "opencode"
