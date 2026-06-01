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

# LangGraph agent metrics
AGENT_CALLS = Counter(
    "agent_calls_total",
    "Total agent invocations",
    ["agent", "action"],
)

AGENT_LATENCY = Histogram(
    "agent_latency_seconds",
    "Agent execution latency in seconds",
    ["agent"],
    buckets=(0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0),
)

TOOL_CALLS = Counter(
    "tool_calls_total",
    "Total tool invocations by agents",
    ["agent", "tool", "status"],
)

SESSIONS_ACTIVE = Gauge(
    "sessions_active_total",
    "Currently active chat sessions",
)

# Image CDN metrics
IMAGES_UPLOADED = Counter(
    "images_uploaded_total",
    "Total product images uploaded to CDN",
    ["variant"],
)

IMAGES_SERVED = Counter(
    "images_served_total",
    "Total product images served from CDN",
    ["variant"],
)

CDN_BANDWIDTH_BYTES = Counter(
    "cdn_bandwidth_bytes_total",
    "Total bandwidth served by image CDN in bytes",
)

# Consumer health metrics
CONSUMER_LAG = Gauge(
    "consumer_lag_total",
    "Kafka consumer lag (messages behind latest offset)",
    ["partition"],
)

CONSUMER_LAST_SUCCESS = Gauge(
    "consumer_last_success_timestamp",
    "Unix timestamp of last successfully processed message",
)


# Prefect orchestration metrics
PREFECT_FLOW_STATE = Gauge(
    "prefect_flow_state",
    "Current Prefect flow run state (0=pending, 1=running, 2=completed, 3=failed, 4=crashed)",
    ["flow_name", "state"],
)


def metrics_endpoint(request):
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
