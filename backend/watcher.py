"""
File Watcher
────────────
Polls `data/ingest/` for new files and automatically processes them
through the MLOps pipeline.

Handles:
  - Partial writes (waits for files to stabilise)
  - Temp-file filtering (.tmp, .part, .crdownload)
  - Error recovery (failed files go to data/ingest/failed/)
  - Graceful shutdown on SIGINT/SIGTERM
"""

import os
import sys
import time
import signal
from pathlib import Path
from datetime import datetime, timezone

from backend.orchestrator import run_pipeline
from backend.telemetry import get_logger

log = get_logger("watcher")

BASE = Path(__file__).resolve().parent.parent
INGEST_DIR = BASE / "data" / "ingest"
PROCESSED_DIR = INGEST_DIR / "processed"
FAILED_DIR = INGEST_DIR / "failed"

TEMP_SUFFIXES = {".tmp", ".part", ".crdownload", ".download", ".swp"}
SUPPORTED_SUFFIXES = {".csv", ".json", ".jsonl"}
STABILITY_WAIT = 3          # seconds a file's mtime must be in the past
POLL_INTERVAL = 5           # seconds between polls
TARGET = "inventory"

_shutdown = False


def _handle_signal(signum, frame):
    global _shutdown
    log.info("shutdown_signal", signal=signum)
    _shutdown = True


def _ensure_dirs():
    for d in (INGEST_DIR, PROCESSED_DIR, FAILED_DIR):
        d.mkdir(parents=True, exist_ok=True)


def _is_temp(name: str) -> bool:
    return any(name.lower().endswith(s) for s in TEMP_SUFFIXES)


def _is_supported(name: str) -> bool:
    return any(name.lower().endswith(s) for s in SUPPORTED_SUFFIXES)


def _is_stable(path: Path) -> bool:
    """A file is stable if its mtime is at least STABILITY_WAIT seconds old."""
    try:
        age = time.time() - path.stat().st_mtime
        return age >= STABILITY_WAIT
    except OSError:
        return False


def _log_report(report: dict, filename: str):
    if report.get("passed"):
        log.info("pipeline_ok", file=filename, message=report.get("message", ""))
    else:
        log.warning("pipeline_fail", file=filename, message=report.get("message", ""))


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
    """Return files in INGEST_DIR that are ready for processing."""
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
            log.debug("waiting_for_stability", file=name, age=time.time() - entry.stat().st_mtime)
            continue
        ready.append(entry)
    return ready


def process_one(file_path: Path, rebuild_rag: bool = True) -> bool:
    """Run the pipeline on a single file. Returns True on success."""
    log.info("processing_file", file=file_path.name)
    try:
        report = run_pipeline(
            file_path=file_path,
            target=TARGET,
            rebuild_rag=rebuild_rag,
            dry_run=False,
        )
        _log_report(report, file_path.name)
        if not report.get("passed"):
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


def watch(rebuild_rag: bool = True, once: bool = False):
    """Main watch loop: poll for new files and process them."""
    _ensure_dirs()
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    log.info("watching_directory", path=str(INGEST_DIR), poll_interval=POLL_INTERVAL)
    log.info("config", target=TARGET, stability_wait=STABILITY_WAIT)

    while not _shutdown:
        files = discover_ready_files()

        if files:
            log.info("files_found", count=len(files))
            for f in files:
                if _shutdown:
                    break
                # Re-check stability before processing (in case it was
                # modified between discovery and now)
                if not _is_stable(f):
                    log.info("file_no_longer_stable", file=f.name)
                    continue
                process_one(f, rebuild_rag=rebuild_rag)
        else:
            log.debug("no_new_files")

        if once:
            break

        # Sleep in short increments so we can catch shutdown signals
        for _ in range(POLL_INTERVAL):
            if _shutdown:
                break
            time.sleep(1)

    log.info("watcher_stopped")


def run_once(rebuild_rag: bool = True) -> list[dict]:
    """Process all currently-ready files and return reports (no loop)."""
    _ensure_dirs()
    files = discover_ready_files()
    if not files:
        log.info("no_files_ready")
        return []

    reports = []
    for f in files:
        ok = process_one(f, rebuild_rag=rebuild_rag)
        reports.append({"file": f.name, "passed": ok})
    return reports
