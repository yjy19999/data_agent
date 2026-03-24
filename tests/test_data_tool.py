"""
Tests for ReadDataTool (agent/tools/data.py).
"""
from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest

from agent.tools.data import ReadDataTool, _truncate_values


@pytest.fixture
def tool():
    return ReadDataTool()


def write_json(path: Path, data) -> Path:
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def write_jsonl(path: Path, records: list) -> Path:
    path.write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")
    return path


def write_jsonl_uuid(path: Path, records: list[tuple[str, dict]]) -> Path:
    lines = [f"{uid}\t{json.dumps(obj)}" for uid, obj in records]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def write_gz(path: Path, content: str) -> Path:
    with gzip.open(path, "wt", encoding="utf-8") as f:
        f.write(content)
    return path


# ── Validation ─────────────────────────────────────────────────────────────────

class TestValidation:
    def test_invalid_mode(self, tool, tmp_path):
        f = tmp_path / "x.txt"
        f.write_text("{}")
        out = tool.run(str(f), mode="csv")
        assert "[error]" in out
        assert "csv" in out

    def test_file_not_found(self, tool, tmp_path):
        out = tool.run(str(tmp_path / "missing.json"), mode="json")
        assert "[error]" in out
        assert "not found" in out

    def test_path_is_directory(self, tool, tmp_path):
        out = tool.run(str(tmp_path), mode="json")
        assert "[error]" in out


# ── JSON mode ──────────────────────────────────────────────────────────────────

class TestJsonMode:
    def test_array_shows_metadata(self, tool, tmp_path):
        f = write_json(tmp_path / "data.json", [{"a": 1}, {"a": 2}])
        out = tool.run(str(f), mode="json")
        assert "array" in out
        assert "2" in out  # item count

    def test_array_respects_max_records(self, tool, tmp_path):
        records = [{"i": i} for i in range(20)]
        f = write_json(tmp_path / "data.json", records)
        out = tool.run(str(f), mode="json", max_records=3)
        assert "record 1" in out
        assert "record 3" in out
        assert "record 4" not in out
        assert "17" in out  # 20 - 3 = 17 not shown

    def test_array_shows_keys(self, tool, tmp_path):
        f = write_json(tmp_path / "data.json", [{"name": "alice", "score": 10}])
        out = tool.run(str(f), mode="json")
        assert "name" in out
        assert "score" in out

    def test_dict_shows_key_count(self, tool, tmp_path):
        f = write_json(tmp_path / "cfg.json", {"host": "localhost", "port": 8080})
        out = tool.run(str(f), mode="json")
        assert "object" in out
        assert "2" in out  # 2 keys

    def test_dict_shows_keys(self, tool, tmp_path):
        f = write_json(tmp_path / "cfg.json", {"host": "localhost", "port": 8080})
        out = tool.run(str(f), mode="json")
        assert "host" in out
        assert "port" in out

    def test_scalar_string(self, tool, tmp_path):
        f = write_json(tmp_path / "s.json", "hello")
        out = tool.run(str(f), mode="json")
        assert "hello" in out

    def test_invalid_json(self, tool, tmp_path):
        f = tmp_path / "bad.json"
        f.write_text("{ not valid json }", encoding="utf-8")
        out = tool.run(str(f), mode="json")
        assert "[error]" in out
        assert "invalid JSON" in out

    def test_shows_file_path_and_mode(self, tool, tmp_path):
        f = write_json(tmp_path / "data.json", [])
        out = tool.run(str(f), mode="json")
        assert "json" in out


# ── JSONL mode ─────────────────────────────────────────────────────────────────

class TestJsonlMode:
    def test_plain_format(self, tool, tmp_path):
        f = write_jsonl(tmp_path / "data.jsonl", [{"x": i} for i in range(10)])
        out = tool.run(str(f), mode="jsonl")
        assert "plain" in out
        assert "record 1" in out
        assert "record 5" in out
        assert "record 6" not in out  # max_records=5 default

    def test_uuid_format_detected(self, tool, tmp_path):
        records = [
            ("550e8400-e29b-41d4-a716-446655440000", {"msg": "hello"}),
            ("6ba7b810-9dad-11d1-80b4-00c04fd430c8", {"msg": "world"}),
        ]
        f = write_jsonl_uuid(tmp_path / "data.jsonl", records)
        out = tool.run(str(f), mode="jsonl")
        assert "uuid+json" in out
        assert "550e8400-e29b-41d4-a716-446655440000" in out

    def test_uuid_json_part_parsed(self, tool, tmp_path):
        records = [("550e8400-e29b-41d4-a716-446655440000", {"answer": 42})]
        f = write_jsonl_uuid(tmp_path / "data.jsonl", records)
        out = tool.run(str(f), mode="jsonl")
        assert "42" in out

    def test_total_record_count(self, tool, tmp_path):
        f = write_jsonl(tmp_path / "data.jsonl", [{"i": i} for i in range(100)])
        out = tool.run(str(f), mode="jsonl", max_records=5)
        assert "100" in out
        assert "95" in out  # 100 - 5 not shown

    def test_blank_lines_skipped(self, tool, tmp_path):
        f = tmp_path / "data.jsonl"
        f.write_text('\n{"a": 1}\n\n{"b": 2}\n\n', encoding="utf-8")
        out = tool.run(str(f), mode="jsonl")
        assert "2" in out  # total 2 records

    def test_bad_lines_counted_as_errors(self, tool, tmp_path):
        f = tmp_path / "data.jsonl"
        f.write_text('{"ok": 1}\nnot json\n{"ok": 2}\n', encoding="utf-8")
        out = tool.run(str(f), mode="jsonl")
        assert "1" in out   # 1 error
        assert "Errors" in out or "error" in out.lower()

    def test_bad_lines_do_not_stop_parsing(self, tool, tmp_path):
        f = tmp_path / "data.jsonl"
        f.write_text('{"a": 1}\nbad\n{"a": 3}\n', encoding="utf-8")
        out = tool.run(str(f), mode="jsonl")
        # Both valid records should be shown
        assert '"a": 1' in out
        assert '"a": 3' in out

    def test_tab_in_value_not_confused_with_uuid_format(self, tool, tmp_path):
        # A line where the tab is inside a value, not a UUID prefix
        f = tmp_path / "data.jsonl"
        f.write_text('{"key": "val\\twith\\ttabs"}\n', encoding="utf-8")
        out = tool.run(str(f), mode="jsonl")
        # Should not crash; parsed as plain JSON
        assert "plain" in out or "record 1" in out


# ── GZ modes ───────────────────────────────────────────────────────────────────

class TestGzModes:
    def test_json_gz(self, tool, tmp_path):
        data = [{"n": i} for i in range(10)]
        f = tmp_path / "data.json.gz"
        write_gz(f, json.dumps(data))
        out = tool.run(str(f), mode="json_gz")
        assert "array" in out
        assert "10" in out
        assert "record 1" in out

    def test_jsonl_gz_plain(self, tool, tmp_path):
        lines = "\n".join(json.dumps({"n": i}) for i in range(20))
        f = tmp_path / "data.jsonl.gz"
        write_gz(f, lines)
        out = tool.run(str(f), mode="jsonl_gz")
        assert "20" in out
        assert "plain" in out

    def test_jsonl_gz_uuid_format(self, tool, tmp_path):
        lines = "\n".join(
            f"550e8400-e29b-41d4-a716-{i:012d}\t" + json.dumps({"i": i})
            for i in range(5)
        )
        f = tmp_path / "data.jsonl.gz"
        write_gz(f, lines)
        out = tool.run(str(f), mode="jsonl_gz")
        assert "uuid+json" in out

    def test_bad_gz_file(self, tool, tmp_path):
        f = tmp_path / "bad.json.gz"
        f.write_bytes(b"this is not gzip data")
        out = tool.run(str(f), mode="json_gz")
        assert "[error]" in out


# ── Output caps ────────────────────────────────────────────────────────────────

class TestOutputCaps:
    def test_max_chars_truncates(self, tool, tmp_path):
        big = [{"text": "x" * 500} for _ in range(20)]
        f = write_json(tmp_path / "big.json", big)
        out = tool.run(str(f), mode="json", max_chars=200)
        assert len(out) <= 250  # some slack for truncation message
        assert "truncated" in out

    def test_max_records_zero_shows_nothing(self, tool, tmp_path):
        f = write_jsonl(tmp_path / "data.jsonl", [{"a": 1}, {"a": 2}])
        out = tool.run(str(f), mode="jsonl", max_records=0)
        assert "record 1" not in out


# ── Field-value truncation ─────────────────────────────────────────────────────

class TestTruncateValues:
    """Unit tests for _truncate_values — the core context-protection function."""

    def test_short_string_unchanged(self):
        assert _truncate_values("hello", max_chars=200) == "hello"

    def test_long_string_replaced_with_marker(self):
        long = "x" * 500
        result = _truncate_values(long, max_chars=200)
        assert result == "[truncated: 500 chars]"
        assert long not in result

    def test_marker_reports_original_length(self):
        result = _truncate_values("a" * 1234, max_chars=100)
        assert "1,234" in result

    def test_numbers_unchanged(self):
        assert _truncate_values(42, max_chars=1) == 42
        assert _truncate_values(3.14, max_chars=1) == 3.14

    def test_bool_unchanged(self):
        assert _truncate_values(True, max_chars=1) is True

    def test_none_unchanged(self):
        assert _truncate_values(None, max_chars=1) is None

    def test_dict_values_truncated(self):
        obj = {"short": "hi", "long": "y" * 500}
        result = _truncate_values(obj, max_chars=10)
        assert result["short"] == "hi"
        assert "truncated" in result["long"]

    def test_dict_keys_preserved(self):
        obj = {"a": "x" * 500, "b": "x" * 500, "c": 1}
        result = _truncate_values(obj, max_chars=10)
        assert set(result.keys()) == {"a", "b", "c"}

    def test_nested_dict_truncated(self):
        obj = {"outer": {"inner": "z" * 500}}
        result = _truncate_values(obj, max_chars=10)
        assert "truncated" in result["outer"]["inner"]

    def test_list_items_truncated(self):
        lst = ["x" * 500, "short", "y" * 300]
        result = _truncate_values(lst, max_chars=10)
        assert "truncated" in result[0]
        assert result[1] == "short"
        assert "truncated" in result[2]

    def test_long_list_summarised(self):
        lst = [str(i) for i in range(30)]   # 30 items, _MAX_LIST_ITEMS=20
        result = _truncate_values(lst, max_chars=1000)
        assert len(result) == 21            # 20 items + 1 summary marker
        assert "10" in result[-1]           # "10 more items"

    def test_result_is_json_serialisable(self):
        obj = {
            "text": "t" * 5000,
            "tags": ["label"] * 30,
            "meta": {"source": "s" * 1000, "score": 0.9},
            "count": 42,
        }
        result = _truncate_values(obj, max_chars=200)
        serialised = json.dumps(result)     # must not raise
        assert "truncated" in serialised


class TestFieldTruncationIntegration:
    """Integration tests — long field values must not break tool output."""

    def test_long_field_value_replaced_in_jsonl(self, tool, tmp_path):
        records = [{"id": i, "text": "word " * 1000} for i in range(3)]
        f = write_jsonl(tmp_path / "data.jsonl", records)
        out = tool.run(str(f), mode="jsonl")
        # Must contain the marker, not the raw text
        assert "truncated" in out
        assert "word " * 10 not in out      # raw repeated content must be absent

    def test_all_keys_visible_despite_long_values(self, tool, tmp_path):
        record = {"id": 1, "title": "short", "body": "x" * 5000, "label": "pos"}
        f = write_jsonl(tmp_path / "data.jsonl", [record])
        out = tool.run(str(f), mode="jsonl")
        # All keys must still appear in the output
        for key in ("id", "title", "body", "label"):
            assert f'"{key}"' in out

    def test_numeric_values_preserved(self, tool, tmp_path):
        record = {"score": 0.987, "count": 42, "text": "x" * 5000}
        f = write_jsonl(tmp_path / "data.jsonl", [record])
        out = tool.run(str(f), mode="jsonl")
        assert "0.987" in out
        assert "42" in out

    def test_output_is_bounded_regardless_of_record_size(self, tool, tmp_path):
        # Each record is 100 KB of text; 5 records = 500 KB raw
        records = [{"text": "z" * 100_000} for _ in range(5)]
        f = write_json(tmp_path / "data.json", records)
        out = tool.run(str(f), mode="json")
        assert len(out) < 10_000           # well under max_chars=8000 + some slack

    def test_long_value_in_gz_file(self, tool, tmp_path):
        lines = "\n".join(json.dumps({"body": "w " * 2000, "id": i}) for i in range(3))
        f = tmp_path / "data.jsonl.gz"
        write_gz(f, lines)
        out = tool.run(str(f), mode="jsonl_gz")
        assert "truncated" in out
        assert '"id"' in out


# ── Profile integration ────────────────────────────────────────────────────────

class TestProfileIntegration:
    def test_datacheck_profile_includes_read_data(self):
        from agent.tools.profiles import get_profile
        profile = get_profile("datacheck")
        assert "ReadData" in profile.tool_names()
