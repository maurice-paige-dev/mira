import json
from pathlib import Path

import pytest

from backend.agents.ingestion_agent import (
    parse_file,
    _parse_csv,
    _parse_json,
    _parse_jsonl,
    tag_records,
)


class TestParseCSV:
    def test_basic_csv(self, tmp_path):
        f = tmp_path / "test.csv"
        f.write_text("Product Name,Unit Price,Quantity\nChai,18.0,10\nTofu,12.0,5\n")
        rows = _parse_csv(f)
        assert len(rows) == 2
        assert rows[0]["Product Name"] == "Chai"

    def test_csv_with_bom(self, tmp_path):
        f = tmp_path / "bom.csv"
        f.write_bytes(b"\xef\xbb\xbfName,Price\nChai,18.0\n")
        rows = _parse_csv(f)
        assert len(rows) == 1
        assert rows[0]["Name"] == "Chai"

    def test_empty_csv(self, tmp_path):
        f = tmp_path / "empty.csv"
        f.write_text("Header\n")
        with pytest.raises(ValueError, match="empty"):
            _parse_csv(f)


class TestParseJSON:
    def test_json_list(self, tmp_path):
        f = tmp_path / "data.json"
        f.write_text('[{"name": "Chai"}, {"name": "Tofu"}]')
        rows = _parse_json(f)
        assert len(rows) == 2

    def test_json_single_object(self, tmp_path):
        f = tmp_path / "data.json"
        f.write_text('{"name": "Chai"}')
        rows = _parse_json(f)
        assert len(rows) == 1

    def test_invalid_json(self, tmp_path):
        f = tmp_path / "bad.json"
        f.write_text("not json")
        with pytest.raises(json.JSONDecodeError):
            _parse_json(f)


class TestParseJSONL:
    def test_jsonl(self, tmp_path):
        f = tmp_path / "data.jsonl"
        f.write_text('{"name": "Chai"}\n{"name": "Tofu"}\n')
        rows = _parse_jsonl(f)
        assert len(rows) == 2

    def test_jsonl_empty(self, tmp_path):
        f = tmp_path / "empty.jsonl"
        f.write_text("")
        with pytest.raises(ValueError, match="empty"):
            _parse_jsonl(f)

    def test_jsonl_with_blank_lines(self, tmp_path):
        f = tmp_path / "data.jsonl"
        f.write_text('{"name": "Chai"}\n\n{"name": "Tofu"}\n')
        rows = _parse_jsonl(f)
        assert len(rows) == 2


class TestParseFile:
    def test_csv(self, tmp_path):
        f = tmp_path / "test.csv"
        f.write_text("Product Name\nChai\n")
        rows = parse_file(f)
        assert len(rows) == 1

    def test_json(self, tmp_path):
        f = tmp_path / "test.json"
        f.write_text('[{"name": "Chai"}]')
        rows = parse_file(f)
        assert len(rows) == 1

    def test_jsonl(self, tmp_path):
        f = tmp_path / "test.jsonl"
        f.write_text('{"name": "Chai"}\n')
        rows = parse_file(f)
        assert len(rows) == 1

    def test_unsupported(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("data")
        with pytest.raises(ValueError, match="Unsupported"):
            parse_file(f)


class TestTagRecords:
    def test_tags_added(self):
        rows = [{"name": "Chai"}]
        tagged = tag_records(rows, "test.csv")
        assert tagged[0]["_source_file"] == "test.csv"
        assert "_ingested_at" in tagged[0]
