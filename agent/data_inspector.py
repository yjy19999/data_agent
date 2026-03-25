from __future__ import annotations

import gzip
import json
from collections import Counter
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any


_JSON_EXTENSIONS = {".json", ".jsonl", ".ndjson"}
_HTML_EXTENSIONS = {".html", ".htm", ".xhtml"}
_CODE_EXTENSIONS = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".go", ".rs",
    ".cpp", ".cc", ".cxx", ".c", ".h", ".hpp", ".cs", ".rb",
    ".php", ".scala", ".kt", ".swift", ".sh", ".sql",
}
_TEXT_EXTENSIONS = {
    ".txt", ".md", ".rst", ".log", ".csv", ".tsv", ".yaml", ".yml",
    ".xml", ".toml",
}


@dataclass
class PreviewChunk:
    index: int
    char_start: int
    char_end: int
    line_start: int
    line_end: int
    preview: str


@dataclass
class FileInspection:
    path: str
    kind: str
    size_bytes: int
    sampled_chars: int
    sampled_lines: int
    scan_truncated: bool
    schema_family: dict[str, Any]
    preview_chunks: list[PreviewChunk]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["preview_chunks"] = [asdict(chunk) for chunk in self.preview_chunks]
        return data


def detect_data_kind(path: str | Path, sample_text: str) -> str:
    p = Path(path)
    ext = p.suffix.lower()
    stripped = sample_text.lstrip()

    # .gz files: inspect inner suffix (e.g. data.jsonl.gz → inner ".jsonl")
    # If no inner suffix is present, default to jsonl_gz.
    if ext == ".gz":
        inner_ext = Path(p.stem).suffix.lower()
        if inner_ext == ".json":
            return "json_gz"
        if inner_ext in {".jsonl", ".ndjson"}:
            return "jsonl_gz"
        # No recognisable inner suffix — guess jsonl_gz (most common for .gz dumps)
        return "jsonl_gz"

    if ext in {".jsonl", ".ndjson"}:
        return "jsonl"
    if ext == ".json":
        return "json"
    if ext in _HTML_EXTENSIONS or stripped[:200].lower().startswith(("<!doctype html", "<html")):
        return "webpage"
    if ext in _CODE_EXTENSIONS:
        return "code"
    if ext in _TEXT_EXTENSIONS:
        return "text"
    if _looks_like_jsonl(sample_text):
        return "jsonl"
    if stripped.startswith(("{", "[")):
        try:
            json.loads(sample_text)
            return "json"
        except json.JSONDecodeError:
            pass
    return "text"


def inspect_file(
    path: str | Path,
    *,
    scan_bytes: int = 200_000,
    chunk_chars: int = 4_000,
    preview_chars: int = 800,
    max_preview_chunks: int = 8,
    max_json_records: int = 50,
) -> FileInspection:
    p = Path(path)
    size_bytes = p.stat().st_size
    if p.suffix.lower() == ".gz":
        with gzip.open(p, "rb") as handle:
            sample = handle.read(scan_bytes)
    else:
        with p.open("rb") as handle:
            sample = handle.read(scan_bytes)
    text = sample.decode("utf-8", errors="replace")
    kind = detect_data_kind(p, text)
    schema_family = infer_schema_family(
        p,
        kind=kind,
        sample_text=text,
        max_json_records=max_json_records,
        scan_truncated=size_bytes > scan_bytes,
    )
    preview_chunks = chunk_text(
        text,
        chunk_chars=chunk_chars,
        preview_chars=preview_chars,
        max_chunks=max_preview_chunks,
    )
    return FileInspection(
        path=str(p),
        kind=kind,
        size_bytes=size_bytes,
        sampled_chars=len(text),
        sampled_lines=text.count("\n") + (1 if text else 0),
        scan_truncated=size_bytes > scan_bytes,
        schema_family=schema_family,
        preview_chunks=preview_chunks,
    )


def build_input_manifest(
    files: list[str | Path],
    *,
    scan_bytes: int = 200_000,
    chunk_chars: int = 4_000,
    preview_chars: int = 800,
    max_preview_chunks: int = 8,
    max_json_records: int = 50,
) -> dict[str, Any]:
    inspected = [
        inspect_file(
            file_path,
            scan_bytes=scan_bytes,
            chunk_chars=chunk_chars,
            preview_chars=preview_chars,
            max_preview_chunks=max_preview_chunks,
            max_json_records=max_json_records,
        )
        for file_path in sorted(Path(f) for f in files)
        if Path(file_path).is_file()
    ]

    kind_counts = Counter(item.kind for item in inspected)
    family_counts = Counter(item.schema_family.get("family", "unknown") for item in inspected)
    total_bytes = sum(item.size_bytes for item in inspected)
    return {
        "summary": {
            "file_count": len(inspected),
            "total_bytes": total_bytes,
            "by_kind": dict(kind_counts),
            "by_schema_family": dict(family_counts),
        },
        "files": [item.to_dict() for item in inspected],
    }


def chunk_text(
    text: str,
    *,
    chunk_chars: int = 4_000,
    preview_chars: int = 800,
    max_chunks: int = 8,
) -> list[PreviewChunk]:
    if not text:
        return []

    chunks: list[PreviewChunk] = []
    start = 0
    for index in range(1, max_chunks + 1):
        if start >= len(text):
            break
        end = min(len(text), start + chunk_chars)
        snippet = text[start:end]
        line_start = text.count("\n", 0, start) + 1
        line_end = line_start + snippet.count("\n")
        preview = snippet[:preview_chars]
        chunks.append(
            PreviewChunk(
                index=index,
                char_start=start,
                char_end=end,
                line_start=line_start,
                line_end=line_end,
                preview=preview,
            )
        )
        start = end
    return chunks


def infer_schema_family(
    path: str | Path,
    *,
    kind: str,
    sample_text: str,
    max_json_records: int = 50,
    scan_truncated: bool = False,
) -> dict[str, Any]:
    p = Path(path)
    if kind == "webpage":
        return {
            "family": "webpage",
            "confidence": 0.95,
            "top_level_type": "document",
            "field_paths": [],
            "sampled_records": 1,
        }

    if kind not in {"json", "jsonl", "json_gz", "jsonl_gz"}:
        return {
            "family": "code_sample" if kind == "code" else "document",
            "confidence": 0.9 if kind == "code" else 0.6,
            "top_level_type": "text",
            "field_paths": [],
            "sampled_records": 1,
        }

    try:
        records, top_level_type = _load_json_records(sample_text, kind, max_json_records=max_json_records)
    except json.JSONDecodeError as exc:
        if scan_truncated and kind in {"json", "json_gz"}:
            full_text = _read_full_text(p, kind)
            try:
                records, top_level_type = _load_json_records(full_text, kind, max_json_records=max_json_records)
            except json.JSONDecodeError as full_exc:
                return {
                    "family": "malformed_json",
                    "confidence": 1.0,
                    "top_level_type": "unknown",
                    "field_paths": [],
                    "sampled_records": 0,
                    "error": str(full_exc),
                }
        else:
            return {
                "family": "malformed_json",
                "confidence": 1.0,
                "top_level_type": "unknown",
                "field_paths": [],
                "sampled_records": 0,
                "error": str(exc),
            }

    flattened = Counter()
    for record in records:
        _flatten_paths(record, flattened)

    family, confidence = _guess_family(records, flattened, path=p)
    return {
        "family": family,
        "confidence": round(confidence, 2),
        "top_level_type": top_level_type,
        "field_paths": [
            {"path": path_name, "observed_types": sorted(list(types))}
            for path_name, types in _collect_path_types(records).items()
        ][:40],
        "sampled_records": len(records),
    }


def _load_json_records(sample_text: str, kind: str, *, max_json_records: int) -> tuple[list[Any], str]:
    if kind in {"jsonl", "jsonl_gz"}:
        records = []
        for line in sample_text.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            try:
                records.append(json.loads(stripped))
            except json.JSONDecodeError:
                # Skip lines that fail to parse — typically the last line
                # when the scan window cut the file mid-record.
                continue
            if len(records) >= max_json_records:
                break
        return records, kind

    payload = json.loads(sample_text)
    if isinstance(payload, list):
        return payload[:max_json_records], "list"
    if isinstance(payload, dict):
        if "messages" in payload and isinstance(payload["messages"], list):
            return payload["messages"][:max_json_records], "object(messages)"
        if "turns" in payload and isinstance(payload["turns"], list):
            return payload["turns"][:max_json_records], "object(turns)"
        return [payload], "object"
    return [payload], type(payload).__name__


def _read_full_text(path: Path, kind: str) -> str:
    if kind == "json_gz":
        with gzip.open(path, "rb") as fh:
            return fh.read().decode("utf-8", errors="replace")
    with path.open("rb") as fh:
        return fh.read().decode("utf-8", errors="replace")


def _looks_like_jsonl(sample_text: str) -> bool:
    lines = [line.strip() for line in sample_text.splitlines() if line.strip()]
    if len(lines) < 2:
        return False
    checked = 0
    for line in lines[:10]:
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            return False
        if not isinstance(parsed, (dict, list)):
            return False
        checked += 1
    return checked >= 2


def _flatten_paths(value: Any, acc: Counter[str], prefix: str = "") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            acc[path] += 1
            _flatten_paths(child, acc, path)
        return
    if isinstance(value, list):
        list_path = f"{prefix}[]" if prefix else "[]"
        acc[list_path] += 1
        for child in value[:5]:
            _flatten_paths(child, acc, list_path)


def _collect_path_types(records: list[Any]) -> dict[str, set[str]]:
    observed: dict[str, set[str]] = {}
    for record in records:
        _collect_types(record, observed)
    return observed


def _collect_types(value: Any, observed: dict[str, set[str]], prefix: str = "") -> None:
    type_name = _json_type_name(value)
    observed.setdefault(prefix or "$", set()).add(type_name)
    if isinstance(value, dict):
        for key, child in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            _collect_types(child, observed, path)
        return
    if isinstance(value, list):
        for child in value[:5]:
            path = f"{prefix}[]" if prefix else "[]"
            _collect_types(child, observed, path)


def _guess_family(
    records: list[Any],
    flattened: Counter[str],
    *,
    path: Path,
) -> tuple[str, float]:
    key_space = {name.lower() for name in flattened}

    candidates = {
        "agent_trajectory": {
            "messages", "turns", "tool", "tool_calls", "observation",
            "assistant", "user", "system", "action", "result", "content",
        },
        "code_sample": {
            "code", "language", "file_path", "path", "dependencies",
            "stdout", "stderr", "exit_code", "execution_result",
        },
        "webpage": {
            "title", "body", "content", "published_at", "published_time",
            "url", "source", "source_url",
        },
        "qa_pair": {
            "question", "answer", "query", "response", "prompt", "completion",
        },
        "triple": {
            "subject", "predicate", "object", "head", "relation", "tail",
        },
    }

    scored: list[tuple[str, float]] = []
    for family, tokens in candidates.items():
        hits = sum(1 for token in tokens if any(token == key.split(".")[-1].replace("[]", "") for key in key_space))
        scored.append((family, hits / max(len(tokens), 1)))

    family, score = max(scored, key=lambda item: item[1], default=("generic_json", 0.0))
    if score == 0:
        if path.suffix.lower() in _HTML_EXTENSIONS:
            return "webpage", 0.9
        return "generic_json", 0.35
    return family, min(0.99, 0.45 + score)


def _json_type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int) and not isinstance(value, bool):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__
