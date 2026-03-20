from __future__ import annotations

import json

from agent.data_inspector import build_input_manifest, detect_data_kind, inspect_file


def test_detect_data_kind_html_from_content(tmp_path):
    sample = "<html><head><title>x</title></head><body>hello</body></html>"
    path = tmp_path / "page.txt"
    path.write_text(sample, encoding="utf-8")

    assert detect_data_kind(path, sample) == "webpage"


def test_inspect_file_infers_agent_trajectory_family(tmp_path):
    path = tmp_path / "trace.jsonl"
    path.write_text(
        "\n".join(
            [
                json.dumps({"role": "system", "content": "rules"}),
                json.dumps({"role": "user", "content": "fix bug"}),
                json.dumps({"role": "assistant", "tool_calls": [{"name": "read_file"}]}),
                json.dumps({"role": "tool", "observation": "file content"}),
            ]
        ),
        encoding="utf-8",
    )

    inspection = inspect_file(path)

    assert inspection.kind == "jsonl"
    assert inspection.schema_family["family"] == "agent_trajectory"
    assert inspection.schema_family["sampled_records"] == 4


def test_inspect_file_infers_code_sample_family(tmp_path):
    path = tmp_path / "snippet.json"
    path.write_text(
        json.dumps(
            {
                "language": "python",
                "file_path": "src/app.py",
                "code": "print('hello')",
                "dependencies": ["requests"],
                "execution_result": {"exit_code": 0, "stdout": "hello"},
            }
        ),
        encoding="utf-8",
    )

    inspection = inspect_file(path)

    assert inspection.kind == "json"
    assert inspection.schema_family["family"] == "code_sample"


def test_build_input_manifest_chunks_long_text(tmp_path):
    long_text = ("line\n" * 2500).strip()
    path = tmp_path / "notes.txt"
    path.write_text(long_text, encoding="utf-8")

    manifest = build_input_manifest([path], chunk_chars=500, preview_chars=120, max_preview_chunks=3)

    assert manifest["summary"]["file_count"] == 1
    file_entry = manifest["files"][0]
    assert file_entry["kind"] == "text"
    assert len(file_entry["preview_chunks"]) == 3
    assert all(len(chunk["preview"]) <= 120 for chunk in file_entry["preview_chunks"])
