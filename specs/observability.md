# Observability: Structured Logging, Metrics, and Monitoring Stack

## 1. Motivation

The platform has zero observability instrumentation. All backend services log via `print()` with ad-hoc prefixes (`[consumer]`, `[integrate]`, `[FATAL]`). No structured format, no log levels, no request/response tracking, no runtime metrics. When a pipeline fails or an API returns 500, debugging requires SSH access and manual log spelunking.

Without metrics, horizontal pod autoscaling uses CPU-only signals (configured in `k8s/hpa.yaml`), which is insufficient for request-rate or latency-based scaling. There are no SLOs, no dashboards, no alerting.

The `k8s/README.md` Section 8 defines a target stack (stdout JSON → Fluentd → Loki, Prometheus + kube-state-metrics, Grafana, Alertmanager) but none of it is implemented. This spec delivers the full observability stack — code-level instrumentation plus K8s manifests.

## 2. Proposed Approach

### Architecture

```
┌────────────────────────────────────────────────────────────┐
│                    Each Python process                      │
│                                                             │
│  structlog → stdout JSON lines  (all components)            │
│  prometheus_client → /metrics HTTP endpoint (FastAPI apps)  │
└────────────────────┬───────────────────────────────────────┘
                     │
            stdout JSON (one line = one event)
                     │
                     ▼
┌────────────────────────────────────────────────────────────┐
│  fluentd DaemonSet (per node)                               │
│  tail /var/log/containers/*.log → parse JSON → tag →       │
│    → Loki (logs)                                            │
│    → Prometheus (extracted metrics if any)                  │
└────────────────────┬───────────────────────────────────────┘
                     │
          ┌──────────┴──────────┐
          ▼                     ▼
┌──────────────────┐  ┌──────────────────────┐
│  Loki             │  │  Prometheus           │
│  (log storage)    │  │  (metric storage)     │
│  Service: loki    │  │  Service: prometheus  │
│  Port: 3100       │  │  Port: 9090           │
└────────┬─────────┘  └──────────┬───────────┘
         │                       │
         └───────────┬───────────┘
                     ▼
          ┌──────────────────────┐
          │  Grafana              │
          │  (dashboards + alert) │
          │  Service: grafana     │
          │  Port: 3000           │
          └──────────────────────┘
```

### Detailed design

#### 2.1 Structured JSON logging (structlog)

**Every Python component** uses a shared logging configuration:

| Component | Current | Target |
|---|---|---|
| `api_catalog.py` | `print()` | `structlog.get_logger("catalog")` |
| `api_rag.py` | `print()` | `structlog.get_logger("rag")` |
| `api_upload.py` | silent | `structlog.get_logger("upload")` |
| `kafka_consumer.py` | `print("[consumer] ...")` | `structlog.get_logger("consumer")` |
| `kafka_producer.py` | silent | `structlog.get_logger("producer")` |
| `aggregator.py` | `print("[aggregator] ...")` | `structlog.get_logger("aggregator")` |
| `chroma_upsert.py` | silent | `structlog.get_logger("chroma_upsert")` |
| `vector_store.py` | `print()` | `structlog.get_logger("vector_store")` |
| `pipeline.py` | `print()` | `structlog.get_logger("pipeline")` |
| `orchestrator.py` | `print()` (captured by Prefect) | `structlog.get_logger("orchestrator")` |
| `ingestion_agent.py` | `print("[ingest] ...")` | `structlog.get_logger("ingestion_agent")` |
| `transformation_agent.py` | `print("[warn] ...")` | `structlog.get_logger("transformation_agent")` |
| `integration_agent.py` | `print("[integrate] ...")` | `structlog.get_logger("integration_agent")` |
| `quality_agent.py` | silent | `structlog.get_logger("quality_agent")` |
| `watcher.py` | `logging` module | Migrate to structlog |

**Shared configuration** (`backend/telemetry.py`):

```python
import structlog
import os

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
SERVICE_NAME = os.getenv("SERVICE_NAME", "unknown")

structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.dev.JSONRenderer(),
    ],
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
    cache_logger_on_first_use=True,
)


def get_logger(component: str) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger().bind(service=SERVICE_NAME, component=component)
```

Each output line is a JSON object:

```json
{"event": "Processing record from file.csv", "level": "info", "timestamp": "2026-05-30T12:00:00.000Z", "service": "catalog", "component": "consumer", "target": "inventory", "record_count": 42}
```

Log levels used: `debug`, `info`, `warning`, `error`, `critical`.

**Migrate `watcher.py`** from `logging` to `structlog` with the same JSON output format.

#### 2.2 Request logging middleware

Add a FastAPI middleware to both `api_catalog.py` and `api_rag.py`:

```python
import time
from structlog import get_logger

logger = get_logger("http")

@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.monotonic()
    response = await call_next(request)
    elapsed = time.monotonic() - start
    logger.info(
        "request",
        method=request.method,
        path=request.url.path,
        status=response.status_code,
        elapsed_ms=round(elapsed * 1000),
    )
    return response
```

This logs every request in structured JSON format. Sensitive headers (auth tokens) are not logged.

#### 2.3 Prometheus metrics (prometheus_client)

Add a shared module `backend/metrics.py` that defines and exposes metrics:

```python
from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
from starlette.responses import Response

HTTP_REQUEST_COUNT = Counter(
    "http_requests_total", "Total HTTP requests",
    ["method", "path", "status"],
)
HTTP_REQUEST_DURATION = Histogram(
    "http_request_duration_seconds", "HTTP request duration",
    ["method", "path"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)
KAFKA_MESSAGES_PRODUCED = Counter(
    "kafka_messages_produced_total", "Total Kafka messages produced",
    ["topic"],
)
KAFKA_MESSAGES_CONSUMED = Counter(
    "kafka_messages_consumed_total", "Total Kafka messages consumed",
    ["topic"],
)
KAFKA_DLQ_MESSAGES = Counter(
    "kafka_dlq_messages_total", "Total messages sent to DLQ",
    ["topic", "reason"],
)
DB_QUERY_DURATION = Histogram(
    "db_query_duration_seconds", "Database query duration",
    ["operation"],
    buckets=(0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0),
)
PRODUCTS_INGESTED = Counter(
    "products_ingested_total", "Total products ingested",
)
CHROMA_DOCUMENTS = Gauge(
    "chroma_documents_total", "Total documents in ChromaDB collection",
    ["collection"],
)


def metrics_endpoint(request):
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
```

**In each FastAPI app**, add `GET /metrics` route:

```python
from backend.metrics import metrics_endpoint

app.add_route("/metrics", metrics_endpoint)
```

**Middleware integration** — update the request logging middleware to also increment counters:

```python
@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    method = request.method
    path = request.url.path
    start = time.monotonic()
    response = await call_next(request)
    elapsed = time.monotonic() - start
    HTTP_REQUEST_COUNT.labels(method=method, path=path, status=response.status_code).inc()
    HTTP_REQUEST_DURATION.labels(method=method, path=path).observe(elapsed)
    return response
```

**In non-HTTP components** (consumer, aggregator), import and update metrics directly:

```python
from backend.metrics import KAFKA_MESSAGES_CONSUMED, KAFKA_DLQ_MESSAGES

KAFKA_MESSAGES_CONSUMED.labels(topic=TOPIC).inc()
KAFKA_DLQ_MESSAGES.labels(topic=TOPIC, reason="unknown_target").inc()
```

#### 2.4 K8s observability manifests

New files in `k8s/observability/`:

```
k8s/observability/
├── kustomization.yaml     # resources + namespace
├── loki.yaml              # StatefulSet + Service (single-node, no auth)
├── fluentd.yaml           # DaemonSet + ConfigMap (tail container logs → Loki)
├── prometheus.yaml        # StatefulSet + Service + ConfigMap + RBAC
├── grafana.yaml           # Deployment + Service + ConfigMap (datasources + dashboards)
└── alertmanager.yaml      # StatefulSet + Service + ConfigMap
```

Add `k8s/observability/kustomization.yaml` as a separate overlay, NOT included in the main `k8s/kustomization.yaml` by default (optional enable).

**Loki** (`loki.yaml`):
- Single-instance StatefulSet, `grafana/loki:3.0` image
- Port 3100, simple config with filesystem storage
- PVC for data persistence (10Gi)

**Fluentd** (`fluentd.yaml`):
- DaemonSet, `fluent/fluentd-kubernetes-daemonset:v1.16` with Loki plugin
- ConfigMap: tail container logs from `/var/log/containers/*.log`, match JSON fields, forward to Loki service
- RBAC: ServiceAccount + ClusterRole for reading pod logs

**Prometheus** (`prometheus.yaml`):
- StatefulSet, `prom/prometheus:v2.53` image
- ConfigMap: scrape config for:
  - `chatbot:8000/metrics`
  - `catalog:8001/metrics`
  - `kube-state-metrics` (if deployed)
  - `kubelet` (cAdvisor for container metrics)
- PVC for TSDB storage (50Gi), retention 15d

**Grafana** (`grafana.yaml`):
- Deployment, `grafana/grafana:11.0` image
- ConfigMap with:
  - `datasources.yaml`: Loki + Prometheus datasources pre-configured
  - `dashboards.yaml`: provisioning for 2 dashboards:
    1. **Service Dashboard** — request rate, error rate, latency (RED metrics) per service
    2. **Pipeline Dashboard** — Kafka messages, DLQ depth, products ingested, ChromaDB size
- Service on port 3000, PVC for plugin storage (1Gi)
- Admin password from Secret (default: auto-generated)

**Alertmanager** (`alertmanager.yaml`):
- StatefulSet, `prom/alertmanager:v0.27` image
- ConfigMap with routes and receivers (email or webhook placeholder)
- PVC for silences data (1Gi)

#### 2.5 Environment variables

| Variable | Default | Used In |
|---|---|---|
| `LOG_LEVEL` | `"INFO"` | `backend/telemetry.py` |
| `SERVICE_NAME` | auto-detected from component | `backend/telemetry.py` |

No new secrets. No new required env vars for the K8s components.

### 2.6 Dockerfile changes

`Dockerfile.backend` — no changes needed. `structlog` and `prometheus_client` are pure Python with no native deps.

`pyproject.toml` — add dependencies:

```toml
dependencies = [
    ... existing ...
    "prometheus-client>=0.20",
    "structlog>=24.0",
]
```

## 3. Key Decisions

1. **structlog over stdlib logging**: structlog's processor pipeline produces clean JSON without custom formatter code. It supports bound loggers (service, component fields auto-attached) and has a first-class JSON renderer. The only cost is one dependency.

2. **prometheus_client over prometheus_fastapi_instrumentator**: prometheus_client keeps full control over metric definitions. The instrumentator is convenient but opaque — it would add auto-generated metrics for every route including `/metrics` itself. Direct instrumentation means the `/metrics` endpoint is excluded and custom business metrics (Kafka depth, DLQ count, products ingested) are explicit.

3. **Separate observability Kustomize overlay vs inline manifests**: Keeping observability out of the main `kustomization.yaml` means the core app can be deployed without the full monitoring stack. The overlay is applied separately: `kubectl apply -k k8s/observability/`. This matches the Phase 2 ("Staging") rollout plan in the K8s README.

4. **Single-instance Loki/Prometheus**: This spec targets dev/staging. Production would need Loki microservices mode and Prometheus with Thanos or Mimir for HA. Called out as an open question.

5. **Replaced Prefect `log_prints=True`**: The orchestrator flow currently uses `@flow(log_prints=True)`. After migration to structlog, Prefect still captures log output because structlog writes to stdout. No change needed in Prefect config.

## 4. Open Questions

1. **Tracing**: Should we add distributed tracing (OpenTelemetry) in the same spec? Kafka → consumer → DB → ChromaDB is a natural trace. OTel would add context propagation across async boundaries. Deferred to a follow-up.

2. **Prometheus Operator vs raw manifests**: The spec uses raw Prometheus StatefulSet + ConfigMap. If the target cluster has the Prometheus Operator, a `ServiceMonitor` CRD would be cleaner. Decision: stick with raw manifests for portability.

3. **Alertmanager receiver**: Which notification channel (email, Slack, PagerDuty)? The spec creates the Alertmanager config with a placeholder receiver. Team to configure post-deploy.

4. **Grafana dashboards as JSON or ConfigMap**: JSON dashboard models are large. Should they live in the repo as committed JSON files, or be created ad-hoc via the Grafana UI? Spec proposes provisioning via ConfigMap for reproducibility.

5. **Production HA for Loki/Prometheus**: Single-instance Loki and Prometheus are single points of failure. For production, Loki needs microservices mode and Prometheus needs Thanos sidecar or Mimir. Should the spec include the production HA layout or leave it for a follow-up?

6. **Log retention**: What retention period for Loki logs and Prometheus TSDB? Defaults: Prometheus 15d, Loki 7d. Team to tune.

## 5. Implementation Plan

### Phase 1 — Python instrumentation (1 session)

1. Add `structlog>=24.0` and `prometheus-client>=0.20` to `pyproject.toml`
2. Create `backend/telemetry.py` — shared structlog configuration + `get_logger()` factory + log level from env
3. Create `backend/metrics.py` — Prometheus metric definitions + `/metrics` response helper
4. Replace `print()` with structlog in all 15 backend files (see table in 2.1)
5. Add request logging + metrics middleware to `api_catalog.py` and `api_rag.py`
6. Add `GET /metrics` route to both FastAPI apps
7. Wire Prometheus counters into `kafka_consumer.py`, `kafka_producer.py`, `aggregator.py`, `chroma_upsert.py`, `db/repository.py`

**Verify**: `pytest` passes. Launch each FastAPI app, hit `/metrics` — see prometheus output. Hit any route — see JSON log line on stdout.

### Phase 2 — K8s manifests (1 session)

8. Create `k8s/observability/kustomization.yaml`
9. Create `k8s/observability/loki.yaml` — StatefulSet + Service
10. Create `k8s/observability/fluentd.yaml` — DaemonSet + ConfigMap + RBAC
11. Create `k8s/observability/prometheus.yaml` — StatefulSet + Service + ConfigMap
12. Create `k8s/observability/grafana.yaml` — Deployment + Service + ConfigMap (datasources + dashboards)
13. Create `k8s/observability/alertmanager.yaml` — StatefulSet + Service + ConfigMap

**Verify**: `kubectl apply -k k8s/observability/` succeeds. Loki, Prometheus, Grafana pods start. Grafana datasources show Loki + Prometheus pre-configured.

### Phase 3 — Dashboards + validation (1 session)

14. Create Grafana dashboard JSON models (Service RED metrics + Pipeline metrics)
15. Package dashboards into `k8s/observability/grafana-dashboards.yaml` ConfigMap
16. Deploy full stack to dev cluster, verify:
    - JSON logs appear in Loki (query `{service="catalog"}`)
    - Metrics appear in Prometheus (query `http_requests_total`)
    - Dashboards show data
    - Alertmanager loads config

**Verify**: E2E test: upload a file via catalog API → pipeline processes → ChromaDB updated → RAG chatbot answers correctly. All steps visible in Grafana dashboard.
