"""
Prefect Deployments
───────────────────
Defines scheduled deployments that replace the legacy file watcher
(backend/watcher.py). Registered with `prefect deployment run` or
by executing this file directly.
"""

import time
from pathlib import Path

from prefect import flow

from backend.orchestrator import run_pipeline
from backend.telemetry import get_logger

log = get_logger("deployments")

BASE = Path(__file__).resolve().parent.parent
INGEST_DIR = BASE / "data" / "ingest"
PROCESSED_DIR = INGEST_DIR / "processed"
FAILED_DIR = INGEST_DIR / "failed"

TEMP_SUFFIXES = {".tmp", ".part", ".crdownload", ".download", ".swp"}
SUPPORTED_SUFFIXES = {".csv", ".json", ".jsonl"}
STABILITY_WAIT = 3
TARGET = "inventory"


def _ensure_dirs():
    for d in (INGEST_DIR, PROCESSED_DIR, FAILED_DIR):
        d.mkdir(parents=True, exist_ok=True)


def _is_temp(name: str) -> bool:
    return any(name.lower().endswith(s) for s in TEMP_SUFFIXES)


def _is_supported(name: str) -> bool:
    return any(name.lower().endswith(s) for s in SUPPORTED_SUFFIXES)


def _is_stable(path: Path) -> bool:
    try:
        age = time.time() - path.stat().st_mtime
        return age >= STABILITY_WAIT
    except OSError:
        return False


def _move_to_failed(path: Path) -> Path:
    FAILED_DIR.mkdir(parents=True, exist_ok=True)
    dest = FAILED_DIR / path.name
    counter = 1
    while dest.exists():
        stem = path.stem
        suffix = path.suffix
        dest = FAILED_DIR / f"{stem}_{counter}{suffix}"
        counter += 1
    path.rename(dest)
    log.info("moved_to_failed", file=path.name)
    return dest


def discover_ready_files() -> list[Path]:
    if not INGEST_DIR.exists():
        return []
    ready = []
    for entry in sorted(INGEST_DIR.iterdir()):
        if not entry.is_file():
            continue
        name = entry.name
        if _is_temp(name):
            log.debug("skipping_temp", file=name)
            continue
        if not _is_supported(name):
            log.debug("skipping_unsupported", file=name)
            continue
        if not _is_stable(entry):
            log.debug("waiting_for_stability", file=name)
            continue
        ready.append(entry)
    return ready


def process_one(file_path: Path, rebuild_rag: bool = True) -> bool:
    log.info("processing_file", file=file_path.name)
    try:
        report = run_pipeline(
            file_path=file_path,
            target=TARGET,
            rebuild_rag=rebuild_rag,
            dry_run=False,
        )
        if report.get("passed"):
            log.info("pipeline_ok", file=file_path.name, message=report.get("message", ""))
        else:
            log.warning("pipeline_fail", file=file_path.name, message=report.get("message", ""))
            _move_to_failed(file_path)
            return False
        return True
    except Exception as exc:
        log.error("unhandled_error", file=file_path.name, error=str(exc))
        try:
            _move_to_failed(file_path)
        except Exception:
            pass
        return False


@flow(log_prints=True)
def watch_once():
    """Process all ready files and stop. Called by Prefect cron schedule."""
    _ensure_dirs()
    files = discover_ready_files()
    if not files:
        log.info("no_files_ready")
        return
    log.info("files_found", count=len(files))
    for f in files:
        if not _is_stable(f):
            log.info("file_no_longer_stable", file=f.name)
            continue
        process_one(f, rebuild_rag=True)


@flow(log_prints=True)
def bulk_reprocess():
    """Run pipeline on all files in processed/ (ad-hoc trigger)."""
    from backend.orchestrator import run_all
    return run_all()


if __name__ == "__main__":
    watch_once.serve(
        name="file-watcher",
        cron="* * * * *",
        tags=["pipeline", "ingestion"],
        description="Poll data/ingest/ and process new files",
    )
