"""
Kafka Producer
──────────────
Publishes product records to the configured Kafka topic.
"""

import json
from kafka import KafkaProducer


def create_producer(
    bootstrap_servers: str = "localhost:9092",
    sasl_username: str | None = None,
    sasl_password: str | None = None,
) -> KafkaProducer:
    config = {
        "bootstrap_servers": bootstrap_servers,
        "value_serializer": lambda v: json.dumps(v).encode("utf-8"),
        "key_serializer": lambda k: str(k).encode("utf-8"),
        "acks": "all",
        "retries": 3,
    }
    if sasl_username and sasl_password:
        config["security_protocol"] = "SASL_SSL"
        config["sasl_mechanism"] = "PLAIN"
        config["sasl_plain_username"] = sasl_username
        config["sasl_plain_password"] = sasl_password
    return KafkaProducer(**config)


def publish_record(
    producer: KafkaProducer,
    topic: str,
    record: dict,
    key: str | None = None,
) -> None:
    msg_key = key or str(record.get("id", record.get("product_name", "unknown")))
    producer.send(topic=topic, key=msg_key, value=record)


def publish_batch(
    producer: KafkaProducer,
    topic: str,
    records: list[dict],
    key_field: str = "id",
) -> int:
    for record in records:
        key = str(record.get(key_field, "unknown"))
        producer.send(topic=topic, key=key, value=record)
    producer.flush()
    return len(records)


def close_producer(producer: KafkaProducer) -> None:
    producer.flush()
    producer.close()
