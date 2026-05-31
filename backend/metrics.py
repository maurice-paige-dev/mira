from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
from fastapi.responses import Response

HTTP_REQUEST_COUNT = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "path", "status"],
)

HTTP_REQUEST_DURATION = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["method", "path"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

KAFKA_MESSAGES_PRODUCED = Counter(
    "kafka_messages_produced_total",
    "Total Kafka messages produced",
    ["topic"],
)

KAFKA_MESSAGES_CONSUMED = Counter(
    "kafka_messages_consumed_total",
    "Total Kafka messages consumed",
    ["topic"],
)

KAFKA_DLQ_MESSAGES = Counter(
    "kafka_dlq_messages_total",
    "Total messages sent to DLQ",
    ["topic", "reason"],
)

DB_QUERY_DURATION = Histogram(
    "db_query_duration_seconds",
    "Database query duration in seconds",
    ["operation"],
    buckets=(0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0),
)

PRODUCTS_INGESTED = Counter(
    "products_ingested_total",
    "Total products ingested",
)

CHROMA_DOCUMENTS = Gauge(
    "chroma_documents_total",
    "Total documents in ChromaDB collection",
    ["collection"],
)


def metrics_endpoint(request):
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
