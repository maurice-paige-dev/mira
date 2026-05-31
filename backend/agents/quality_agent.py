"""
Quality Agent
─────────────
Validates transformed records against schema rules before they are
committed to the CSV store.
"""

from prefect import task

from backend.agents.schema_config import TARGETS
from backend.telemetry import get_logger

log = get_logger("quality_agent")


def validate(rows: list[dict], target_key: str) -> list[dict]:
    """
    Validate transformed records. Returns a list of error dicts;
    an empty list means all records passed.

    Each error::
        {"row": int, "field": str, "message": str}
    """
    if target_key not in TARGETS:
        raise ValueError(f"Unknown target '{target_key}'")

    schema = TARGETS[target_key]
    required = schema["required"]
    errors = []

    for idx, row in enumerate(rows):
        for field in required:
            val = row.get(field)

            if val is None or str(val).strip() == "":
                errors.append({
                    "row": idx + 1,
                    "field": field,
                    "message": f"Required field '{field}' is missing or empty.",
                })
                continue

            if field in ("Unit Price", "Total Price", "Product Total"):
                try:
                    float(val)
                except (ValueError, TypeError):
                    errors.append({
                        "row": idx + 1,
                        "field": field,
                        "message": f"'{field}' must be numeric, got {val!r}.",
                    })

            if field in ("Quantity", "Units Sold", "Units in Stock"):
                try:
                    ival = int(float(val))
                    if ival < 0:
                        errors.append({
                            "row": idx + 1,
                            "field": field,
                            "message": f"'{field}' must be >= 0, got {ival}.",
                        })
                except (ValueError, TypeError):
                    errors.append({
                        "row": idx + 1,
                        "field": field,
                        "message": f"'{field}' must be numeric, got {val!r}.",
                    })

            if field == "Product Name":
                s = str(val).strip()
                if len(s) < 2:
                    errors.append({
                        "row": idx + 1,
                        "field": field,
                        "message": f"'{field}' is too short ({len(s)} chars).",
                    })

    return errors


@task
def quality_report(rows: list[dict], target_key: str) -> dict:
    """Run validation and return a structured pass/fail report."""
    errors = validate(rows, target_key)
    passed = len(errors) == 0
    return {
        "target": target_key,
        "records_in": len(rows),
        "passed": passed,
        "error_count": len(errors),
        "errors": errors,
    }
