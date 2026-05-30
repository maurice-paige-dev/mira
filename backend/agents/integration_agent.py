"""
Integration Agent
─────────────────
Appends validated, transformed records to the correct CSV file(s) and
triggers a RAG vector store rebuild so the new data is immediately
queryable.
"""

import csv
import subprocess
import sys
from pathlib import Path

from prefect import task

from backend.agents.schema_config import TARGETS

BASE = Path(__file__).resolve().parent.parent.parent
CSV_DIR = BASE / "data" / "csv"


def append_to_csv(rows: list[dict], target_key: str) -> Path:
    """Append records to the target CSV, creating it if absent."""
    schema = TARGETS[target_key]
    csv_name = schema["target"]
    csv_path = CSV_DIR / csv_name
    fieldnames = list(schema["field_map"].keys())

    file_exists = csv_path.exists()

    with open(csv_path, "a", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        writer.writerows(rows)

    print(f"  [integrate] Appended {len(rows)} rows to {csv_name}")
    return csv_path


@task
def rebuild_vector_store() -> bool:
    """Run the vector store builder to incorporate new data into ChromaDB."""
    print("  [integrate] Rebuilding ChromaDB vector store \u2026")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "backend.vector_store", "--no-interactive"],
            cwd=BASE,
            capture_output=True,
            text=True,
            timeout=300,
        )
        if result.returncode == 0:
            print("  [integrate] Vector store rebuild complete.")
            return True
        else:
            print(f"  [integrate] Vector store rebuild FAILED:\n{result.stderr}")
            return False
    except subprocess.TimeoutExpired:
        print("  [integrate] Vector store rebuild timed out.")
        return False
    except FileNotFoundError:
        print("  [integrate] Could not launch vector store builder.")
        return False


@task(retries=1, retry_delay_seconds=30)
def integrate(rows: list[dict], target_key: str, rebuild_rag: bool = True) -> dict:
    """Append to CSV and optionally rebuild the RAG vector store."""
    csv_path = append_to_csv(rows, target_key)

    rag_status = "skipped"
    if rebuild_rag:
        rag_status = "ok" if rebuild_vector_store() else "failed"

    return {
        "target": target_key,
        "csv": str(csv_path),
        "rows_written": len(rows),
        "rag_rebuild": rag_status,
    }
