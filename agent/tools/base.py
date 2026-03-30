from __future__ import annotations

import inspect
import json
import re
from abc import ABC, abstractmethod
import types
from typing import Any, Union, get_type_hints


class Tool(ABC):
    """
    Base class for all agent tools.

    Subclasses define:
      - name        : str   — tool name the model uses to call it
      - description : str   — what the tool does (shown to the model)
      - run()       — the actual implementation

    Parameter schema is built automatically from run()'s type annotations
    and docstring. Override `parameters_schema` for full manual control.
    """

    name: str
    description: str

    @abstractmethod
    def run(self, **kwargs: Any) -> str:
        """Execute the tool and return a string result."""
        ...

    # ------------------------------------------------------------------
    # Schema generation
    # ------------------------------------------------------------------

    @property
    def parameters_schema(self) -> dict[str, Any]:
        """
        Auto-generate JSON Schema from run()'s signature.
        Override this if you need custom schema control.
        """
        sig = inspect.signature(self.run)
        hints = get_type_hints(self.run)
        doc = inspect.getdoc(self.run) or ""

        properties: dict[str, Any] = {}
        required: list[str] = []

        for param_name, param in sig.parameters.items():
            if param_name in ("self", "kwargs"):
                continue

            prop: dict[str, Any] = {
                "type": _python_type_to_json(hints.get(param_name, str)),
            }

            # Pull per-param description from docstring "Args:" block
            param_doc = _extract_param_doc(doc, param_name)
            if param_doc:
                prop["description"] = param_doc

            properties[param_name] = prop

            if param.default is inspect.Parameter.empty:
                required.append(param_name)

        return {
            "type": "object",
            "properties": properties,
            "required": required,
        }

    def to_openai_schema(self) -> dict[str, Any]:
        """Return the OpenAI tool schema for this tool."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters_schema,
            },
        }

    def __call__(self, **kwargs: Any) -> str:
        sig = inspect.signature(self.run)
        accepted = set(sig.parameters) - {"self"}
        # Drop unknown kwargs the model hallucinated; warn so it's visible in logs
        unknown = set(kwargs) - accepted
        if unknown:
            import sys
            print(
                f"[warning] {self.name}: ignoring unknown argument(s) {sorted(unknown)}",
                file=sys.stderr,
            )
            kwargs = {k: v for k, v in kwargs.items() if k in accepted}
        return self.run(**kwargs)


# ------------------------------------------------------------------
# Registry
# ------------------------------------------------------------------

class ToolRegistry:
    """Holds all registered tools and dispatches model tool calls."""

    def __init__(self):
        self._tools: dict[str, Tool] = {}

    def register(self, *tools: Tool) -> None:
        for tool in tools:
            self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def schemas(self) -> list[dict[str, Any]]:
        """Return OpenAI-format tool list to pass with each request."""
        return [t.to_openai_schema() for t in self._tools.values()]

    def execute(self, name: str, arguments: dict[str, Any]) -> str:
        """
        Run a tool by name. Returns its string output or an error message.
        
        FIX: Validates tool names and suggests corrections if the model
        called an invalid tool (e.g., "list_dirlist_dir" instead of "list_dir").
        """
        tool = self._tools.get(name)
        if tool is None:
            # Try to find what the model might have meant
            available = list(self._tools.keys())
            suggestion = self._find_closest_match(name, available)
            msg = f"[error] unknown tool: {name!r}"
            if suggestion:
                msg += f" (did you mean '{suggestion}'?)"
            return msg
        try:
            return tool(**arguments)
        except Exception as exc:
            return f"[error] {name} raised {type(exc).__name__}: {exc}"

    def _find_closest_match(self, name: str, available: list[str]) -> str | None:
        """
        Find closest tool name using substring matching.
        Handles cases where the model concatenates or mangles tool names.
        """
        name_lower = name.lower()
        
        # Exact match (case-insensitive)
        for tool_name in available:
            if tool_name.lower() == name_lower:
                return tool_name
        
        # Substring match: if the invalid name contains a valid tool name
        for tool_name in available:
            if tool_name in name_lower:
                return tool_name
        
        # Reverse: if a valid tool name contains the invalid name
        for tool_name in available:
            if name_lower in tool_name:
                return tool_name
        
        return None

    def __len__(self) -> int:
        return len(self._tools)

    def __repr__(self) -> str:
        return f"ToolRegistry({list(self._tools.keys())})"


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _python_type_to_json(tp: Any) -> str:
    mapping = {
        str: "string",
        int: "integer",
        float: "number",
        bool: "boolean",
        list: "array",
        dict: "object",
    }
    # Handle Optional[X] / X | None (typing.Union or types.UnionType)
    origin = getattr(tp, "__origin__", None)
    args = getattr(tp, "__args__", None)
    is_union = origin is Union or isinstance(tp, types.UnionType)
    if args and is_union:
        # Filter out NoneType to find the real type
        real = [a for a in args if a is not type(None)]
        if real:
            return mapping.get(real[0], "string")
    return mapping.get(tp, "string")


def _extract_param_doc(docstring: str, param_name: str) -> str:
    """
    Extract a parameter description from a Google-style docstring Args block.

    Example docstring:
        Args:
            path: The file path to read.
            encoding: File encoding.
    """
    lines = docstring.splitlines()
    in_args = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.lower() in ("args:", "arguments:"):
            in_args = True
            continue
        if in_args:
            # Stop at next section heading
            if stripped and not stripped.startswith(" ") and stripped.endswith(":"):
                break
            if stripped.startswith(f"{param_name}:"):
                desc = stripped[len(param_name) + 1:].strip()
                # Collect continuation lines (stop at next param or section)
                for cont in lines[i + 1:]:
                    c = cont.strip()
                    if not c:
                        break
                    # Stop if this looks like a new param "name:" or section heading
                    if re.match(r'^[a-zA-Z_]\w*:', c):
                        break
                    desc += " " + c
                return desc
    return ""
