"""
ReadFormatTool — reads structured data files and returns a bounded preview.
ReadDataTool   — reads structured data files with no truncation, using block navigation.

Supported modes (both tools):
    json        single JSON value (object, array, or scalar)
    jsonl       newline-delimited JSON; each line is one of:
                  - plain JSON:    {"key": "value", ...}
                  - uuid+json:     <uuid>\t{"key": "value", ...}
    json_gz     gzip-compressed JSON
    jsonl_gz    gzip-compressed JSONL (same line formats as jsonl)
"""
from __future__ import annotations

import gzip
import json
import re
from pathlib import Path
from typing import Any

from .base import Tool


_UUID_RE = re.compile(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
    re.IGNORECASE,
)
_VALID_MODES = frozenset({"json", "jsonl", "json_gz", "jsonl_gz"})
_MAX_VALUE_CHARS = 200   # string values longer than this are replaced with a marker
_MAX_LIST_ITEMS  = 20    # list elements beyond this are summarised


# ── Helpers ────────────────────────────────────────────────────────────────────

def _is_uuid(s: str) -> bool:
    return bool(_UUID_RE.match(s))


def _parse_jsonl_line(line: str) -> tuple[str | None, Any]:
    """
    Parse one JSONL line.

    Returns (uuid, parsed_object) where uuid is None for plain-JSON lines.
    Raises json.JSONDecodeError if the JSON part is invalid.

    Handles:
        plain:     {"key": "val"}
        uuid+json: 550e8400-e29b-41d4-a716-446655440000\t{"key": "val"}
    """
    if "\t" in line:
        prefix, _, rest = line.partition("\t")
        if _is_uuid(prefix.strip()):
            return prefix.strip(), json.loads(rest)
    return None, json.loads(line)


def _truncate_values(obj: Any, max_chars: int = _MAX_VALUE_CHARS) -> Any:
    """
    Recursively truncate string values within a parsed JSON object.

    Rules:
        str   → replaced with "[truncated: N chars]" when len > max_chars
        dict  → each value truncated recursively
        list  → each element truncated; tail summarised if > _MAX_LIST_ITEMS items
        other → returned unchanged (int, float, bool, None)

    This ensures the agent always receives structurally valid JSON with
    all keys visible, never a mid-string cut-off.
    """
    if isinstance(obj, str):
        if len(obj) > max_chars:
            return f"[truncated: {len(obj):,} chars]"
        return obj
    if isinstance(obj, dict):
        return {k: _truncate_values(v, max_chars) for k, v in obj.items()}
    if isinstance(obj, list):
        head = [_truncate_values(v, max_chars) for v in obj[:_MAX_LIST_ITEMS]]
        if len(obj) > _MAX_LIST_ITEMS:
            head.append(f"[... {len(obj) - _MAX_LIST_ITEMS:,} more items]")
        return head
    return obj  # int, float, bool, None — always safe


def _format_record(obj: Any, idx: int, uuid: str | None = None) -> str:
    uuid_tag = f" [uuid: {uuid}]" if uuid else ""
    header = f"--- record {idx}{uuid_tag} ---"
    body = json.dumps(_truncate_values(obj), ensure_ascii=False)
    return f"{header}\n{body}"


def _infer_keys(records: list[Any]) -> list[str]:
    """Collect unique top-level keys from the first few records."""
    seen: dict[str, None] = {}
    for r in records:
        if isinstance(r, dict):
            for k in r:
                seen[str(k)] = None
    return list(seen.keys())[:20]


def _human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n //= 1024
    return f"{n:.1f} TB"


def _read_file_text(p: Path, compressed: bool) -> str:
    if compressed:
        with gzip.open(p, "rt", encoding="utf-8", errors="replace") as f:
            return f.read()
    return p.read_text(encoding="utf-8", errors="replace")


# ── Core parsing ───────────────────────────────────────────────────────────────

def _parse_jsonl(
    raw_text: str,
    max_records: int,
) -> tuple[list[str], int, int, str | None]:
    """
    Parse JSONL text.

    Returns:
        formatted_records   list of rendered record strings (up to max_records)
        total_lines         total non-empty lines seen
        error_count         lines that failed JSON parsing (skipped)
        detected_format     "uuid+json" | "plain" | None
    """
    formatted: list[str] = []
    total = 0
    errors = 0
    detected_format: str | None = None
    record_num = 0

    for raw in raw_text.splitlines():
        line = raw.strip()
        if not line:
            continue
        total += 1
        try:
            uuid, obj = _parse_jsonl_line(line)
            if detected_format is None:
                detected_format = "uuid+json" if uuid else "plain"
            record_num += 1
            if record_num <= max_records:
                formatted.append(_format_record(obj, record_num, uuid))
        except json.JSONDecodeError:
            errors += 1

    return formatted, total, errors, detected_format


def _parse_json(
    raw_text: str,
    max_records: int,
) -> tuple[str, list[str], list[str], int]:
    """
    Parse a single JSON value.

    Returns:
        top_type_label      human-readable type description
        key_list            top-level keys (for objects/arrays of objects)
        formatted_records   rendered record strings
        remaining           number of items not shown
    """
    data = json.loads(raw_text)  # raises json.JSONDecodeError on bad input

    if isinstance(data, list):
        top_type = f"array  ({len(data):,} items)"
        keys = _infer_keys(data[:max_records])
        records = [_format_record(r, i + 1) for i, r in enumerate(data[:max_records])]
        remaining = max(0, len(data) - max_records)

    elif isinstance(data, dict):
        top_type = f"object  ({len(data):,} keys)"
        keys = list(str(k) for k in data.keys())[:20]
        records = [_format_record(data, 1)]
        remaining = 0

    else:
        top_type = type(data).__name__
        keys = []
        records = [f"--- value ---\n{json.dumps(data)}"]
        remaining = 0

    return top_type, keys, records, remaining


# ── Tool ───────────────────────────────────────────────────────────────────────

class ReadFormatTool(Tool):
    name = "ReadFormat"
    description = (
        "Read structured data files and return a bounded preview for inspection. "
        "Supports four modes: json, jsonl, json_gz, jsonl_gz. "
        "JSONL lines may be plain JSON objects or 'uuid\\t{json}' — both are detected automatically. "
        "Returns file metadata, schema shape, total record count, and sampled rows."
    )

    def run(
        self,
        path: str,
        mode: str,
        max_records: int = 5,
        max_chars: int = 8000,
    ) -> str:
        """
        Args:
            path: Path to the data file (absolute or relative to cwd).
            mode: File format — one of "json", "jsonl", "json_gz", "jsonl_gz".
            max_records: Maximum number of records/items to show. Defaults to 5.
            max_chars: Maximum total output characters. Defaults to 8000.
        """
        if mode not in _VALID_MODES:
            return (
                f"[error] unknown mode {mode!r}. "
                f"Valid modes: {', '.join(sorted(_VALID_MODES))}"
            )

        p = Path(path).expanduser()
        if not p.exists():
            return f"[error] file not found: {path}"
        if not p.is_file():
            return f"[error] not a file: {path}"

        size_bytes = p.stat().st_size
        compressed = mode.endswith("_gz")

        try:
            raw_text = _read_file_text(p, compressed)
        except Exception as exc:
            return f"[error] could not read file: {exc}"

        base_mode = mode.removesuffix("_gz")  # "json" or "jsonl"

        if base_mode == "json":
            return self._render_json(path, mode, raw_text, size_bytes, max_records, max_chars)
        else:
            return self._render_jsonl(path, mode, raw_text, size_bytes, max_records, max_chars)

    # ── Renderers ──────────────────────────────────────────────────────────────

    def _render_json(
        self,
        path: str,
        mode: str,
        raw_text: str,
        size_bytes: int,
        max_records: int,
        max_chars: int,
    ) -> str:
        try:
            top_type, keys, records, remaining = _parse_json(raw_text, max_records)
        except json.JSONDecodeError as exc:
            return f"[error] invalid JSON in {path}: {exc}"

        lines = [
            f"File:    {path}",
            f"Mode:    {mode}",
            f"Size:    {_human_size(size_bytes)}",
            f"Type:    {top_type}",
        ]
        if keys:
            lines.append(f"Keys:    {', '.join(keys)}")
        lines.append("")
        lines.extend(records)
        if remaining:
            lines.append(f"\n[{remaining:,} more items not shown]")

        return _cap(lines, max_chars)

    def _render_jsonl(
        self,
        path: str,
        mode: str,
        raw_text: str,
        size_bytes: int,
        max_records: int,
        max_chars: int,
    ) -> str:
        formatted, total, errors, detected_format = _parse_jsonl(raw_text, max_records)

        shown = len(formatted)
        lines = [
            f"File:    {path}",
            f"Mode:    {mode}",
            f"Size:    {_human_size(size_bytes)}",
            f"Records: {total:,}  (showing first {shown})",
        ]
        if detected_format:
            lines.append(f"Format:  {detected_format}")
        if errors:
            lines.append(f"Errors:  {errors:,} lines failed to parse (skipped)")
        lines.append("")
        lines.extend(formatted)
        if total > max_records:
            lines.append(f"\n[{total - max_records:,} more records not shown]")

        return _cap(lines, max_chars)


def _cap(lines: list[str], max_chars: int) -> str:
    output = "\n".join(lines)
    if len(output) > max_chars:
        output = output[:max_chars] + f"\n\n[output truncated at {max_chars:,} chars]"
    return output


# ── ReadDataTool helpers ────────────────────────────────────────────────────────

def _split_blocks(text: str, block_size: int) -> list[str]:
    """Split text into sequential chunks of block_size chars."""
    if not text:
        return [""]
    return [text[i:i + block_size] for i in range(0, len(text), block_size)]


def _sample_lines(lines: list[str], n: int = 5) -> list[tuple[int, str]]:
    """Return up to n evenly-spaced (1-based line number, line text) pairs."""
    if not lines:
        return []
    if len(lines) <= n:
        return [(i + 1, line) for i, line in enumerate(lines)]
    indices = [int(round(i * (len(lines) - 1) / (n - 1))) for i in range(n)]
    seen: set[int] = set()
    result = []
    for idx in indices:
        if idx not in seen:
            seen.add(idx)
            result.append((idx + 1, lines[idx]))
    return result


# ── Tool ───────────────────────────────────────────────────────────────────────

class ReadDataTool(Tool):
    name = "ReadData"
    description = (
        "Read structured data files with full content — no value truncation. "
        "Large files and large JSONL lines are split into navigable blocks. "
        "JSONL: call without args to see a sampled line index; then line=N to inspect "
        "a line (shows block index if the line is large, or full content if it fits); "
        "then line=N block=M to read a specific block of that line. "
        "JSON: call without args to see a block index; then block=N to read a block."
    )

    def run(
        self,
        path: str,
        mode: str,
        line: int | None = None,
        block: int | None = None,
        block_size: int = 4000,
        preview_chars: int = 500,
    ) -> str:
        """
        Args:
            path: Path to the data file (absolute or relative to cwd).
            mode: File format — one of "json", "jsonl", "json_gz", "jsonl_gz".
            line: JSONL only — 1-based line number to inspect.
            block: Block number to read in full (1-based).
            block_size: Characters per block. Defaults to 4000.
            preview_chars: Characters shown per entry in the index. Defaults to 500.
        """
        if mode not in _VALID_MODES:
            return (
                f"[error] unknown mode {mode!r}. "
                f"Valid modes: {', '.join(sorted(_VALID_MODES))}"
            )

        # Coerce numeric args to int — LLMs sometimes pass them as strings
        try:
            if line is not None:
                line = int(line)
            if block is not None:
                block = int(block)
            block_size = int(block_size)
            preview_chars = int(preview_chars)
        except (ValueError, TypeError) as exc:
            return f"[error] numeric arguments must be integers: {exc}"

        p = Path(path).expanduser()
        if not p.exists():
            return f"[error] file not found: {path}"
        if not p.is_file():
            return f"[error] not a file: {path}"

        size_bytes = p.stat().st_size
        compressed = mode.endswith("_gz")

        try:
            raw_text = _read_file_text(p, compressed)
        except Exception as exc:
            return f"[error] could not read file: {exc}"

        base_mode = mode.removesuffix("_gz")

        if base_mode == "jsonl":
            return self._handle_jsonl(path, mode, raw_text, size_bytes, line, block, block_size, preview_chars)
        else:
            return self._handle_json(path, mode, raw_text, size_bytes, block, block_size, preview_chars)

    # ── JSONL ──────────────────────────────────────────────────────────────────

    def _handle_jsonl(
        self,
        path: str,
        mode: str,
        raw_text: str,
        size_bytes: int,
        line: int | None,
        block: int | None,
        block_size: int,
        preview_chars: int,
    ) -> str:
        lines = [ln for ln in raw_text.splitlines() if ln.strip()]
        total = len(lines)

        if line is None:
            # Level 1: sampled line index
            sampled = _sample_lines(lines, n=5)
            out = [
                f"File:    {path}",
                f"Mode:    {mode}",
                f"Size:    {_human_size(size_bytes)}",
                f"Lines:   {total:,}",
                "",
            ]
            for lnum, ltext in sampled:
                preview = ltext[:preview_chars].replace("\n", " ")
                out.append(f"Line {lnum:<8} {preview}")
            out += ["", "Use ReadData with line=N to inspect a specific line."]
            return "\n".join(out)

        if line < 1 or line > total:
            return f"[error] line {line} out of range (file has {total:,} lines)"

        line_text = lines[line - 1]
        blocks = _split_blocks(line_text, block_size)

        if block is None:
            if len(blocks) == 1:
                # Line fits in one block — return full content directly
                return "\n".join([
                    f"File:    {path}",
                    f"Line:    {line} of {total:,}  ({len(line_text):,} chars)",
                    "",
                    line_text,
                ])
            # Level 2: block index for this line
            header = f"Line:    {line} of {total:,}  ({len(line_text):,} chars)"
            hint = f"line={line} block=N"
            return self._render_block_index(path, header, blocks, preview_chars, hint)

        # Level 3: read specific block of a line
        header = f"Line:    {line} of {total:,}"
        return self._render_block(path, header, blocks, block)

    # ── JSON ───────────────────────────────────────────────────────────────────

    def _handle_json(
        self,
        path: str,
        mode: str,
        raw_text: str,
        size_bytes: int,
        block: int | None,
        block_size: int,
        preview_chars: int,
    ) -> str:
        blocks = _split_blocks(raw_text, block_size)

        if block is None:
            header = f"Size:    {_human_size(size_bytes)}"
            hint = "block=N"
            return self._render_block_index(path, header, blocks, preview_chars, hint)

        header = f"Size:    {_human_size(size_bytes)}"
        return self._render_block(path, header, blocks, block)

    # ── Shared renderers ───────────────────────────────────────────────────────

    def _render_block_index(
        self,
        path: str,
        header: str,
        blocks: list[str],
        preview_chars: int,
        hint: str,
    ) -> str:
        out = [
            f"File:    {path}",
            header,
            f"Blocks:  {len(blocks)}",
            "",
        ]
        for i, b in enumerate(blocks, 1):
            preview = b[:preview_chars].replace("\n", " ")
            out.append(f"Block {i:<5} {preview}")
        out += ["", f"Use ReadData with {hint} to read a block in full."]
        return "\n".join(out)

    def _render_block(
        self,
        path: str,
        header: str,
        blocks: list[str],
        block: int,
    ) -> str:
        total = len(blocks)
        if block < 1 or block > total:
            return f"[error] block {block} out of range (has {total} block(s))"
        return "\n".join([
            f"File:    {path}",
            header,
            f"Block:   {block} of {total}",
            "",
            blocks[block - 1],
        ])
