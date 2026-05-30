"""
Transformation Agent
────────────────────
Maps incoming data records to the canonical CSV schema using the field
mappings defined in schema_config.py.

Supports aliasing: if the input uses "name" but the target expects
"Product Name", the mapping finds the match and renames the key.
"""

import csv
from pathlib import Path
from io import StringIO

from prefect import task

from backend.agents.schema_config import TARGETS


def _match_field(input_field: str, candidates: list[str]) -> bool:
    """Case-insensitive match; also strips whitespace / underscores."""
    cleaned = input_field.strip().lower().replace("_", "").replace("-", "")
    return any(
        cleaned == c.strip().lower().replace("_", "").replace("-", "")
        for c in candidates
    )


@task(retries=1, retry_delay_seconds=5)
def transform(rows: list[dict], target_key: str) -> list[dict]:
    """
    Transform a list of input records into the target schema.

    Parameters
    ----------
    rows : list[dict]
        Records from the ingestion agent (may contain _source_file, _ingested_at).
    target_key : str
        One of 'inventory', 'inventory_category', 'purchase_order',
        'invoice', 'shipping_order'.

    Returns
    -------
    list[dict]
        Records conforming to the target schema.
    """
    if target_key not in TARGETS:
        valid = list(TARGETS.keys())
        raise ValueError(f"Unknown target '{target_key}'. Valid: {valid}")

    schema = TARGETS[target_key]
    field_map = schema["field_map"]
    defaults = schema["defaults"]
    transformers = schema.get("transformers", {})

    output_rows = []

    for row in rows:
        out = {}

        for target_field, aliases in field_map.items():
            value = None

            # Check for _generated marker
            if aliases == ["_generated"]:
                gen = defaults.get(target_field)
                value = gen() if callable(gen) else (gen or "")
                out[target_field] = value
                continue

            # Try each alias against every input key
            for alias in aliases:
                for input_key in row:
                    if _match_field(input_key, [alias]):
                        candidate = row[input_key]
                        if candidate is not None and str(candidate).strip():
                            value = candidate
                            break
                if value is not None:
                    break

            # Fall back to default if still missing
            if value is None and target_field in defaults:
                d = defaults[target_field]
                value = d() if callable(d) else d

            # Apply value transformer
            if value is not None and target_field in transformers:
                try:
                    value = transformers[target_field](value)
                except Exception as exc:
                    print(f"  [warn] Transformer failed for {target_field}={value!r}: {exc}")
                    value = 0.0

            out[target_field] = value if value is not None else ""

        output_rows.append(out)

    return output_rows


def preview(rows: list[dict], target_key: str, n: int = 5) -> str:
    """Return a pretty-printed preview of the transformed data."""
    schema = TARGETS[target_key]
    transformed = transform(rows[:n], target_key)
    buf = StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(schema["field_map"]))
    writer.writeheader()
    writer.writerows(transformed)
    return buf.getvalue()
