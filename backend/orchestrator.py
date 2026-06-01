"""
MLOps Pipeline Orchestrator
───────────────────────────
Coordinates the data conversion agents:
  1. Discover new files in data/ingest/
  2. Parse + tag (ingestion agent)
  3. Map to target schema (transformation agent)
  4. Validate (quality agent)
  5. Append to CSV + rebuild RAG (integration agent)

Prefect @task decorators handle retries, state persistence, and
automatic error propagation — no manual try/except bookkeeping needed.
"""

from pathlib import Path

from prefect import flow
from prefect.task_runners import ConcurrentTaskRunner

from backend.agents import ingestion_agent, transformation_agent, quality_agent, integration_agent
from backend.telemetry import get_logger

log = get_logger("orchestrator")


@flow(log_prints=True)
def run_pipeline(
    file_path: Path | None = None,
    target: str = "inventory",
    rebuild_rag: bool = True,
    dry_run: bool = False,
) -> dict:
    """
    Execute the full MLOps pipeline on a single file (or the next
    discovered file if *file_path* is ``None``).
    """
    if file_path is None:
        files = ingestion_agent.discover_new_files()
        if not files:
            return {"passed": False, "message": "No new files found in data/ingest/"}
        file_path = files[0]

    if not file_path.exists():
        return {"passed": False, "message": f"File not found: {file_path}"}

    log.info("pipeline_started", file=file_path.name, target=target)

    rows = ingestion_agent.ingest(file_path)
    log.info("step_ingest", records=len(rows))

    transformed = transformation_agent.transform(rows, target)
    log.info("step_transform", records=len(transformed))

    qr = quality_agent.quality_report(transformed, target)
    if not qr["passed"]:
        log.warning("validation_failed", errors=qr['error_count'])
        for err in qr["errors"]:
            log.warning("validation_error", row=err['row'], field=err['field'], message=err['message'])
        return {"passed": False, "target": target, "errors": qr["errors"]}

    log.info("validation_passed", records=len(transformed))

    if dry_run:
        log.info("dry_run_mode", records=len(transformed))
        return {"passed": True, "target": target, "rows_processed": len(transformed), "dry_run": True}

    result = integration_agent.integrate(transformed, target, rebuild_rag=rebuild_rag)
    log.info("pipeline_complete", rows=result['rows_processed'])

    return {
        "passed": True,
        "target": target,
        **result,
    }


@flow(log_prints=True, task_runner=ConcurrentTaskRunner)
def run_all(rebuild_rag: bool = True, dry_run: bool = False) -> list[dict]:
    """Run the pipeline on every file in the ingest directory."""
    files = ingestion_agent.discover_new_files()
    if not files:
        log.info("no_new_files_to_process")
        return []

    reports = []
    for f in files:
        report = run_pipeline(file_path=f, target="inventory", rebuild_rag=rebuild_rag, dry_run=dry_run)
        reports.append(report)
    return reports
