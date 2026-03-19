from __future__ import annotations

from .base import Tool


class TaskTool(Tool):
    name = "Task"
    description = (
        "Launch a sub-agent to handle a self-contained task and return its result. "
        "Use for parallelisable or isolated work: research, file analysis, code generation. "
        "The sub-agent has access to the same tools as the parent."
    )

    @property
    def parameters_schema(self):
        return {
            "type": "object",
            "properties": {
                "description": {
                    "type": "string",
                    "description": "Short label for this task (shown in output).",
                },
                "prompt": {
                    "type": "string",
                    "description": "Full instructions for the sub-agent.",
                },
            },
            "required": ["description", "prompt"],
        }

    def run(self, prompt: str, description: str = "") -> str:
        """
        Args:
            prompt: Full instructions for the sub-agent.
            description: Short label for this task (shown in output).
        """
        # Import here to avoid circular imports at module load time
        from ..agent import Agent
        from ..config import Config

        label = description or "sub-task"

        try:
            config = Config()
            # Sub-agent uses the same config but with a tighter tool iteration cap
            config.max_tool_iterations = min(config.max_tool_iterations, 10)
            sub = Agent(config=config)

            parts: list[str] = []
            for event in sub.run(prompt):
                if event.type == "text":
                    parts.append(event.data)
                elif event.type == "error":
                    parts.append(f"\n[sub-agent error] {event.data}")

            result = "".join(parts).strip()
            return f"[task: {label}]\n{result}" if result else f"[task: {label}] (no output)"

        except Exception as exc:
            return f"[task: {label}] [error] {exc}"
