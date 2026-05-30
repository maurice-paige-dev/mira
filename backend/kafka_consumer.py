"""
Kafka Consumer
──────────────
Subscribes to the product-ingest topic, processes each message through
the pipeline agents, writes to PostgreSQL and ChromaDB, and handles
failures via a dead-letter queue.
"""

import json
import os
import signal
import sys
from pathlib import Path

from kafka import KafkaConsumer, KafkaProducer as DlqProducer

from backend.agents import transformation_agent, quality_agent
from backend.agents.integration_agent import integrate
from backend.agents.schema_config import TARGETS
from backend.db.migrations import create_tables

TOPIC = os.environ.get("KAFKA_TOPIC_PRODUCT_INGEST", "product-ingest")
DLQ_TOPIC = os.environ.get("KAFKA_TOPIC_DLQ", "product-ingest-dlq")
GROUP_ID = os.environ.get("KAFKA_GROUP_ID", "product-ingestion")
BOOTSTRAP = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
DATABASE_URL = os.environ.get("DATABASE_URL", "")
CHROMA_PATH = os.environ.get("CHROMA_DB_PATH", "")

SASL_USERNAME = os.environ.get("KAFKA_SASL_USERNAME") or None
SASL_PASSWORD = os.environ.get("KAFKA_SASL_PASSWORD") or None

running = True


def _consumer_config() -> dict:
    config = {
        "bootstrap_servers": BOOTSTRAP,
        "value_deserializer": lambda v: json.loads(v.decode("utf-8")),
        "key_deserializer": lambda k: k.decode("utf-8") if k else None,
        "group_id": GROUP_ID,
        "auto_offset_reset": "earliest",
        "enable_auto_commit": False,
        "max_poll_records": 100,
    }
    if SASL_USERNAME and SASL_PASSWORD:
        config["security_protocol"] = "SASL_SSL"
        config["sasl_mechanism"] = "PLAIN"
        config["sasl_plain_username"] = SASL_USERNAME
        config["sasl_plain_password"] = SASL_PASSWORD
    return config


def _dlq_producer() -> DlqProducer:
    config = {
        "bootstrap_servers": BOOTSTRAP,
        "value_serializer": lambda v: json.dumps(v).encode("utf-8"),
        "acks": "all",
    }
    if SASL_USERNAME and SASL_PASSWORD:
        config["security_protocol"] = "SASL_SSL"
        config["sasl_mechanism"] = "PLAIN"
        config["sasl_plain_username"] = SASL_USERNAME
        config["sasl_plain_password"] = SASL_PASSWORD
    return DlqProducer(**config)


def _send_to_dlq(producer: DlqProducer, message: dict, error: str) -> None:
    message["error"] = error
    producer.send(DLQ_TOPIC, value=message)
    producer.flush()
    print(f"  [consumer] Sent to DLQ: {error}")


def _process_message(
    msg_value: dict,
    dlq: DlqProducer,
) -> bool:
    source = msg_value.get("source", "unknown")
    source_file = msg_value.get("source_file", "unknown")
    target = msg_value.get("target", "inventory")
    record = msg_value.get("record", msg_value)

    if target not in TARGETS:
        _send_to_dlq(dlq, msg_value, f"Unknown target: {target}")
        return True

    print(f"  [consumer] Processing record from {source_file} (target={target})")

    try:
        transformed = transformation_agent.transform([record], target)
    except Exception as e:
        _send_to_dlq(dlq, msg_value, f"Transform failed: {e}")
        return True

    if not transformed:
        _send_to_dlq(dlq, msg_value, "Transform produced empty result")
        return True

    qr = quality_agent.quality_report(transformed, target)
    if not qr.get("passed"):
        errors = "; ".join(
            f"{e.get('field')}: {e.get('message')}" for e in qr.get("errors", [])
        )
        _send_to_dlq(dlq, msg_value, f"Validation failed: {errors}")
        return True

    try:
        result = integrate(
            rows=transformed,
            target_key=target,
            database_url=DATABASE_URL,
            chroma_path=CHROMA_PATH,
        )
        print(f"  [consumer] Integrated {result['rows_processed']} record(s)")
        return True
    except Exception as e:
        print(f"  [consumer] Integration failed (will retry): {e}")
        return False


def run() -> None:
    global running

    def shutdown(signum, frame):
        global running
        print("\n[consumer] Shutdown signal received…")
        running = False

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    if DATABASE_URL:
        create_tables(DATABASE_URL)
        print("[consumer] Database tables ready")

    consumer = KafkaConsumer(TOPIC, **_consumer_config())
    dlq = _dlq_producer()
    print(f"[consumer] Subscribed to {TOPIC} (group={GROUP_ID})")

    try:
        while running:
            messages = consumer.poll(timeout_ms=1000, max_records=100)
            if not messages:
                continue

            for tp, batch in messages.items():
                for msg in batch:
                    if not running:
                        break
                    try:
                        ok = _process_message(msg.value, dlq)
                    except Exception as e:
                        print(f"  [consumer] Unexpected error: {e}")
                        ok = False

                    if ok:
                        consumer.commit()
                    else:
                        print("  [consumer] Will retry on next poll")
    except KeyboardInterrupt:
        pass
    finally:
        consumer.close()
        dlq.close()
        print("[consumer] Stopped")


if __name__ == "__main__":
    run()
