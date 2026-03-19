from __future__ import annotations

import json
from pathlib import Path

from .base import Tool


class NotebookReadTool(Tool):
    name = "NotebookRead"
    description = (
        "Read a Jupyter notebook (.ipynb) file. "
        "Returns all cells with their type, source, and outputs."
    )

    def run(self, notebook_path: str) -> str:
        """
        Args:
            notebook_path: Path to the .ipynb file.
        """
        p = Path(notebook_path).expanduser()
        if not p.exists():
            return f"[error] notebook not found: {notebook_path}"
        if p.suffix != ".ipynb":
            return f"[error] not a notebook file (.ipynb): {notebook_path}"

        try:
            nb = json.loads(p.read_text(encoding="utf-8"))
        except Exception as exc:
            return f"[error] could not parse notebook: {exc}"

        cells = nb.get("cells", [])
        if not cells:
            return "[empty notebook]"

        lines = [f"Notebook: {p.name}  ({len(cells)} cells)\n{'═' * 50}"]

        for i, cell in enumerate(cells):
            cell_type = cell.get("cell_type", "unknown")
            source    = "".join(cell.get("source", []))
            outputs   = cell.get("outputs", [])

            lines.append(f"\n[Cell {i} · {cell_type}]")
            if source.strip():
                lines.append(source.rstrip())
            else:
                lines.append("(empty)")

            if outputs:
                lines.append("── output ──")
                for out in outputs:
                    out_type = out.get("output_type", "")
                    if out_type == "stream":
                        text = "".join(out.get("text", []))
                        lines.append(text.rstrip())
                    elif out_type in ("display_data", "execute_result"):
                        data = out.get("data", {})
                        if "text/plain" in data:
                            lines.append("".join(data["text/plain"]).rstrip())
                        if "image/png" in data:
                            lines.append("[image/png — not shown]")
                    elif out_type == "error":
                        lines.append(f"[error] {out.get('ename')}: {out.get('evalue')}")

        return "\n".join(lines)


class NotebookEditTool(Tool):
    name = "NotebookEdit"
    description = (
        "Edit a cell in a Jupyter notebook (.ipynb) file. "
        "Can replace a cell's source, insert a new cell, or delete a cell."
    )

    @property
    def parameters_schema(self):
        return {
            "type": "object",
            "properties": {
                "notebook_path": {
                    "type": "string",
                    "description": "Path to the .ipynb file.",
                },
                "cell_index": {
                    "type": "integer",
                    "description": "0-based index of the cell to edit/delete, or insertion position.",
                },
                "new_source": {
                    "type": "string",
                    "description": "New source code/text for the cell (required for replace/insert).",
                },
                "edit_mode": {
                    "type": "string",
                    "enum": ["replace", "insert", "delete"],
                    "description": (
                        "'replace' — overwrite the cell at cell_index. "
                        "'insert' — add a new cell before cell_index. "
                        "'delete' — remove the cell at cell_index."
                    ),
                },
                "cell_type": {
                    "type": "string",
                    "enum": ["code", "markdown"],
                    "description": "Cell type for insert/replace. Defaults to 'code'.",
                },
            },
            "required": ["notebook_path", "cell_index", "edit_mode"],
        }

    def run(
        self,
        notebook_path: str,
        cell_index: int,
        edit_mode: str = "replace",
        new_source: str = "",
        cell_type: str = "code",
    ) -> str:
        """
        Args:
            notebook_path: Path to the .ipynb file.
            cell_index: 0-based cell index.
            edit_mode: 'replace', 'insert', or 'delete'.
            new_source: New cell source (for replace/insert).
            cell_type: 'code' or 'markdown' (for replace/insert).
        """
        p = Path(notebook_path).expanduser()
        if not p.exists():
            return f"[error] notebook not found: {notebook_path}"

        try:
            nb = json.loads(p.read_text(encoding="utf-8"))
        except Exception as exc:
            return f"[error] could not parse notebook: {exc}"

        cells = nb.get("cells", [])

        if edit_mode == "delete":
            if cell_index < 0 or cell_index >= len(cells):
                return f"[error] cell_index {cell_index} out of range (0–{len(cells)-1})"
            cells.pop(cell_index)
            nb["cells"] = cells
            p.write_text(json.dumps(nb, indent=1, ensure_ascii=False), encoding="utf-8")
            return f"[ok] deleted cell {cell_index} from {notebook_path}"

        if edit_mode in ("replace", "insert") and not new_source and new_source != "":
            return "[error] new_source is required for replace/insert"

        new_cell = {
            "cell_type": cell_type,
            "source": new_source,
            "metadata": {},
            "outputs": [] if cell_type == "code" else None,
            "execution_count": None if cell_type == "code" else None,
        }
        # Remove None values (markdown cells don't have outputs)
        new_cell = {k: v for k, v in new_cell.items() if v is not None}

        if edit_mode == "replace":
            if cell_index < 0 or cell_index >= len(cells):
                return f"[error] cell_index {cell_index} out of range (0–{len(cells)-1})"
            cells[cell_index] = new_cell
            action = f"replaced cell {cell_index}"
        elif edit_mode == "insert":
            cells.insert(cell_index, new_cell)
            action = f"inserted cell at position {cell_index}"
        else:
            return f"[error] unknown edit_mode: {edit_mode!r} (use replace/insert/delete)"

        nb["cells"] = cells
        try:
            p.write_text(json.dumps(nb, indent=1, ensure_ascii=False), encoding="utf-8")
        except Exception as exc:
            return f"[error] could not write notebook: {exc}"

        return f"[ok] {action} in {notebook_path}"
