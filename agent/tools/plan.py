from __future__ import annotations

from .base import Tool

# Sentinel returned to the agent loop to signal the plan is ready
PLAN_READY_SENTINEL = "__PLAN_READY__"


class ExitPlanModeTool(Tool):
    """
    Signal that planning is complete and execution should begin.
    Claude Code style: the model calls this when it has finished exploring
    and is ready to act. Works like write_plan but without requiring steps.
    """
    name = "exit_plan_mode"
    description = (
        "Signal that you have finished planning and are ready to execute. "
        "Call this after analysing the task. Provide a brief summary of what you will do."
    )

    def __init__(self):
        self.pending: dict | None = None

    def run(self, summary: str) -> str:
        """
        Args:
            summary: Brief description of what you plan to do next.
        """
        self.pending = {"summary": summary, "steps": [summary]}
        return PLAN_READY_SENTINEL


class WritePlanTool(Tool):
    name = "write_plan"
    description = (
        "Submit a step-by-step plan BEFORE taking any action. "
        "Describe what you intend to do so the user can approve it. "
        "You MUST call this tool before using any other tool."
    )

    def __init__(self):
        self.pending: dict | None = None

    def run(self, steps: list, summary: str = "") -> str:
        """
        Args:
            steps: Ordered list of steps you plan to take.
            summary: One-line description of the overall goal.
        """
        self.pending = {"summary": summary, "steps": steps}
        return PLAN_READY_SENTINEL
