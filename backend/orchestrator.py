"""
MLOps Pipeline Orchestrator
───────────────────────────
Coordinates the data conversion agents:
  1. Discover new files in data/ingest/
  2. Parse + tag (ingestion agent)
  3. Map to target schema (transformation agent)
  4. Validate (quality agent)
  5. Append to CSV + rebuild RAG (integration agent)
"""

from pathlib import Path

from prefect import flow

from backend.agents import ingestion_agent, transformation_agent, quality_agent, integration_agent
from backend.telemetry import get_logger

log = get_logger("orchestrator")


PIPELINE_STEPS = ["ingest", "transform", "validate", "integrate"]


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
    report = {
        "target": target,
        "dry_run": dry_run,
        "steps": {},
        "passed": False,
    }

    # ── 1. Discover ────────────────────────────────────────
    if file_path is None:
        files = ingestion_agent.discover_new_files()
        if not files:
            report["message"] = "No new files found in data/ingest/"
            return report
        file_path = files[0]

    if not file_path.exists():
        report["message"] = f"File not found: {file_path}"
        return report

    log.info("pipeline_started", file=file_path.name, target=target)

    # ── 2. Ingest ──────────────────────────────────────────
    log.info("step_ingest", file=file_path.name)
    try:
        rows = ingestion_agent.ingest(file_path)
        report["steps"]["ingest"] = {"status": "ok", "records": len(rows)}
    except Exception as exc:
        report["steps"]["ingest"] = {"status": "failed", "error": str(exc)}
        report["message"] = f"Ingestion failed: {exc}"
        return report

    # ── 3. Transform ───────────────────────────────────────
    log.info("step_transform", target=target)
    try:
        preview = transformation_agent.preview(rows, target)
        transformed = transformation_agent.transform(rows, target)
        report["steps"]["transform"] = {
            "status": "ok",
            "records_out": len(transformed),
        }
        log.info("transform_complete", records=len(transformed))
        for line in preview.splitlines()[:4]:
            log.debug("preview", line=line)
    except Exception as exc:
        report["steps"]["transform"] = {"status": "failed", "error": str(exc)}
        report["message"] = f"Transformation failed: {exc}"
        return report

    # ── 4. Validate ────────────────────────────────────────
    log.info("step_validate", records=len(transformed))
    qr = quality_agent.quality_report(transformed, target)
    report["steps"]["validate"] = qr

    if not qr["passed"]:
        log.warning("validation_failed", errors=qr['error_count'])
        for err in qr["errors"]:
            log.warning("validation_error", row=err['row'], field=err['field'], message=err['message'])
        report["message"] = f"Quality checks failed: {qr['error_count']} error(s)"
        return report

    log.info("validation_passed", records=len(transformed))

    if dry_run:
        log.info("dry_run", detail="validation passed, no data committed")
        report["passed"] = True
        report["message"] = "Dry run: validation passed, no data committed."
        return report

    # ── 5. Integrate ───────────────────────────────────────
    log.info("step_integrate")
    try:
        result = integration_agent.integrate(transformed, target, rebuild_rag=rebuild_rag)
        report["steps"]["integrate"] = result
        report["passed"] = True
        report["message"] = (
            f"Pipeline complete. {result['rows_written']} rows "
            f"written to {Path(result['csv']).name}. "
            f"RAG rebuild: {result['rag_rebuild']}."
        )
        log.info("integrate_complete")
    except Exception as exc:
        report["steps"]["integrate"] = {"status": "failed", "error": str(exc)}
        report["message"] = f"Integration failed: {exc}"
        return report

    log.info("pipeline_complete", message=report['message'])

    return report


@flow(log_prints=True)
def run_all(rebuild_rag: bool = True, dry_run: bool = False) -> list[dict]:
    """Run the pipeline on every file in the ingest directory."""
    files = ingestion_agent.discover_new_files()
    if not files:
        log.info("no_new_files_to_process")
        return []

    reports = []
    for f in files:
        r = run_pipeline(f, target="inventory", rebuild_rag=rebuild_rag, dry_run=dry_run)
        reports.append(r)
    return reports
