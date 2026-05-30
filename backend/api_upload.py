"""
Upload API Router
─────────────────
Accepts product files via POST /api/upload and publishes each record
to Kafka.
"""

import json
import os
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from kafka import KafkaProducer as KProducer

from backend.agents.ingestion_agent import parse_file

router = APIRouter()

KAFKA_BOOTSTRAP = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
KAFKA_TOPIC = os.environ.get("KAFKA_TOPIC_PRODUCT_INGEST", "product-ingest")
SASL_USERNAME = os.environ.get("KAFKA_SASL_USERNAME") or None
SASL_PASSWORD = os.environ.get("KAFKA_SASL_PASSWORD") or None


def _get_producer() -> KProducer:
    config = {
        "bootstrap_servers": KAFKA_BOOTSTRAP,
        "value_serializer": lambda v: json.dumps(v).encode("utf-8"),
        "key_serializer": lambda k: str(k).encode("utf-8"),
        "acks": "all",
    }
    if SASL_USERNAME and SASL_PASSWORD:
        config["security_protocol"] = "SASL_SSL"
        config["sasl_mechanism"] = "PLAIN"
        config["sasl_plain_username"] = SASL_USERNAME
        config["sasl_plain_password"] = SASL_PASSWORD
    return KProducer(**config)


@router.post("/api/upload")
async def upload_file(
    file: UploadFile = File(...),
    target: str = Form("inventory"),
):
    if target not in ("inventory", "inventory_category", "purchase_order", "invoice", "shipping_order"):
        raise HTTPException(status_code=400, detail=f"Invalid target: {target}")

    suffix = Path(file.filename).suffix.lower()
    if suffix not in (".csv", ".json", ".jsonl"):
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {suffix}")

    content = await file.read()
    temp_path = Path(f"/tmp/{file.filename}")
    temp_path.write_bytes(content)

    try:
        rows = parse_file(temp_path)
    except Exception as e:
        temp_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=f"Parse failed: {e}")

    temp_path.unlink(missing_ok=True)

    if not rows:
        raise HTTPException(status_code=400, detail="File contains no records")

    producer = _get_producer()
    sent = 0
    try:
        for row in rows:
            msg = {
                "source": "upload_api",
                "source_file": file.filename,
                "target": target,
                "record": row,
            }
            key = str(row.get("id", row.get("product_name", row.get("Product Name", sent))))
            producer.send(topic=KAFKA_TOPIC, key=key, value=msg)
            sent += 1
        producer.flush()
    finally:
        producer.close()

    return {
        "accepted": True,
        "record_count": sent,
        "file": file.filename,
        "target": target,
    }
