"""
Ingestion Agent
───────────────
Discovers new data files in the ingest directory, parses them into a
uniform list-of-dicts representation, and tags each record with provenance
metadata.
"""

import csv
import json
from pathlib import Path
from datetime import datetime

BASE = Path(__file__).resolve().parent.parent.parent
INGEST_DIR = BASE / "data" / "ingest"
PROCESSED_DIR = INGEST_DIR / "processed"


def discover_new_files() -> list[Path]:
    """Return sorted list of new files in the ingest directory."""
    if not INGEST_DIR.exists():
        return []
    return sorted(
        p for p in INGEST_DIR.iterdir()
        if p.is_file() and p.suffix.lower() in (".csv", ".json", ".jsonl")
    )


def parse_file(file_path: Path) -> list[dict]:
    """Parse a CSV or JSON file into a list of row dicts."""
    suffix = file_path.suffix.lower()

    if suffix == ".csv":
        return _parse_csv(file_path)
    elif suffix == ".json":
        return _parse_json(file_path)
    elif suffix == ".jsonl":
        return _parse_jsonl(file_path)
    else:
        raise ValueError(f"Unsupported file type: {suffix}")


def _parse_csv(path: Path) -> list[dict]:
    with open(path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = [dict(row) for row in reader]
    if not rows:
        raise ValueError(f"CSV file is empty: {path}")
    return rows


def _parse_json(path: Path) -> list[dict]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        return [data]
    if isinstance(data, list):
        return data
    raise ValueError(f"Unexpected JSON structure in {path}")


def _parse_jsonl(path: Path) -> list[dict]:
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    if not rows:
        raise ValueError(f"JSONL file is empty: {path}")
    return rows


def tag_records(rows: list[dict], source_file: str) -> list[dict]:
    """Add provenance metadata to each record."""
    now = datetime.now().isoformat(timespec="seconds")
    for row in rows:
        row["_source_file"] = source_file
        row["_ingested_at"] = now
    return rows


def move_to_processed(file_path: Path) -> Path:
    """Move the ingested file into the processed archive."""
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    dest = PROCESSED_DIR / file_path.name
    counter = 1
    while dest.exists():
        stem = file_path.stem
        suffix = file_path.suffix
        dest = PROCESSED_DIR / f"{stem}_{counter}{suffix}"
        counter += 1
    file_path.rename(dest)
    return dest


def ingest(file_path: Path) -> list[dict]:
    """Full ingestion: parse + tag, then archive the file."""
    rows = parse_file(file_path)
    rows = tag_records(rows, file_path.name)
    archived = move_to_processed(file_path)
    print(f"  [ingest] Parsed {len(rows)} record(s) from {file_path.name}")
    print(f"  [ingest] Archived to {archived}")
    return rows
