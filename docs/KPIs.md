# KPIs & Operational Metrics

## 1. Pipeline Health

| KPI | Definition | Prometheus Query | Target | Grafana Dashboard |
|---|---|---|---|---|
| **Ingestion Throughput** | Products ingested per minute | `rate(products_ingested_total[1m])` | ≥ 10/min | Pipeline Metrics |
| **Kafka Produce Rate** | Messages published to topic per second | `rate(kafka_messages_produced_total[1m])` | — | Pipeline Metrics |
| **Kafka Consume Rate** | Messages consumed per second | `rate(kafka_messages_consumed_total[1m])` | matches produce rate | Pipeline Metrics |
| **Consumer Lag** | Unprocessed messages per partition | `consumer_lag_total` | < 100 | Pipeline Metrics |
| **DLQ Rate** | Messages sent to dead-letter queue | `rate(kafka_dlq_messages_total[5m])` | < 1% of consumed | Pipeline Metrics |
| **Consumer Staleness** | Seconds since last successful message | `time() - consumer_last_success_timestamp` | < 60s | Pipeline Metrics |
| **DB Query Latency (p99)** | Slowest 1% of database queries | `histogram_quantile(0.99, rate(db_query_duration_seconds_bucket[1m]))` | < 500ms | Pipeline Metrics |
| **DB Query Latency (p50)** | Median database query time | `histogram_quantile(0.50, rate(db_query_duration_seconds_bucket[1m]))` | < 50ms | Pipeline Metrics |
| **ChromaDB Doc Count** | Total documents in vector store | `chroma_documents_total` | monotonic growth | Pipeline Metrics |

## 2. API Service Level (RED)

| KPI | Definition | Prometheus Query | Target | Grafana Dashboard |
|---|---|---|---|---|
| **Request Rate** | Total HTTP requests per second | `sum(rate(http_requests_total[1m]))` | — | Service RED Metrics |
| **Error Rate (5xx)** | Server error rate | `sum(rate(http_requests_total{status=~"5.."}[1m]))` | < 1% of total | Service RED Metrics |
| **4xx Rate** | Client error rate | `sum(rate(http_requests_total{status=~"4.."}[1m]))` | < 5% of total | Service RED Metrics |
| **Latency p50** | Median response time | `histogram_quantile(0.50, sum(rate(http_request_duration_seconds_bucket[1m])) by (le))` | < 200ms | Service RED Metrics |
| **Latency p95** | 95th percentile response time | `histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket[1m])) by (le))` | < 500ms | Service RED Metrics |
| **Latency p99** | 99th percentile response time | `histogram_quantile(0.99, sum(rate(http_request_duration_seconds_bucket[1m])) by (le))` | < 1s | Service RED Metrics |
| **Availability (30d)** | Uptime as fraction of requests | `1 - (sum(rate(http_requests_total{status=~"5.."}[30d])) / sum(rate(http_requests_total[30d])))` | ≥ 99.9% | Operational Overview |
| **Service Uptime** | Catalog + chatbot scraped by Prometheus | `up{job=~"catalog|chatbot"}` | 1 | Service RED Metrics |

## 3. Agent System

| KPI | Definition | Prometheus Query | Target | Grafana Dashboard |
|---|---|---|---|---|
| **Agent Call Rate** | Total agent invocations per minute | `sum(rate(agent_calls_total[1m]))` | — | Operational Overview |
| **Agent Call Rate by Agent** | Per-agent invocation rate | `rate(agent_calls_total[1m])` | — | Operational Overview |
| **Agent Latency p50** | Median agent execution time | `histogram_quantile(0.50, rate(agent_latency_seconds_bucket[1m]))` | < 5s | Operational Overview |
| **Agent Latency p95** | Slowest agent execution time | `histogram_quantile(0.95, rate(agent_latency_seconds_bucket[1m]))` | < 15s | Operational Overview |
| **Tool Call Success Rate** | Percentage of tool calls that succeed | `rate(tool_calls_total{status="success"}[1m]) / rate(tool_calls_total[1m]) * 100` | > 95% | Operational Overview |
| **Tool Failure Rate** | Tool calls that error per agent | `rate(tool_calls_total{status="error"}[1m])` | < 5/min | Operational Overview |
| **Active Sessions** | Concurrent chat sessions | `sessions_active_total` | — | Operational Overview |

## 4. Image CDN

| KPI | Definition | Prometheus Query | Target | Grafana Dashboard |
|---|---|---|---|---|
| **Upload Rate** | Images uploaded per minute | `rate(images_uploaded_total[1m])` | — | Operational Overview |
| **Serve Rate** | Images served per second | `rate(images_served_total[1m])` | — | Operational Overview |
| **CDN Bandwidth** | Bytes served per second | `rate(cdn_bandwidth_bytes_total[1m])` | — | Operational Overview |

## 5. Code Quality

| KPI | Definition | Source | Target |
|---|---|---|---|
| **Test Coverage** | Line coverage of `backend/` package | `pytest --cov=backend` in CI | ≥ 70% |
| **Coverage by Module** | Per-package breakdown | CI job summary (XML report) | each ≥ 60% |
| **CI Pass Rate** | Percentage of CI runs passing | GitHub Actions | 100% on main |
| **Test Count** | Total passing test cases | `pytest --collect-only` | monotonic growth |

## 6. Aggregated Health (30-Day Rolling)

| KPI | Definition | Prometheus Query | Target |
|---|---|---|---|
| **Total Requests** | HTTP requests served in last 30 days | `sum(increase(http_requests_total[30d]))` | — |
| **Total Products Ingested** | Products added in last 30 days | `sum(increase(products_ingested_total[30d]))` | — |
| **Total Images Uploaded** | CDN uploads in last 30 days | `sum(increase(images_uploaded_total[30d]))` | — |
| **Total Kafka Messages** | Messages consumed in last 30 days | `sum(increase(kafka_messages_consumed_total[30d]))` | — |
| **Error Budget Remaining** | Allowed 5xx budget for 99.9% SLA | `(1 - (sum(rate(http_requests_total{status=~"5.."}[30d])) / sum(rate(http_requests_total[30d])))) * 100` | > 99.9% |

## Data Sources

All time-series KPIs are instrumented via Prometheus metrics defined in `backend/metrics.py` and scraped by the Prometheus StatefulSet in `k8s/observability/prometheus.yaml`. Dashboards are provisioned via `k8s/observability/grafana-dashboards.yaml`. Coverage KPIs come from `pytest --cov` in CI (`.github/workflows/build-deploy.yml`).

## Alert Thresholds (via Alertmanager)

| Condition | Severity | Action |
|---|---|---|
| `consumer_lag_total > 1000` for > 5m | warning | Scale consumer or investigate broker |
| `time() - consumer_last_success_timestamp > 120` | critical | Consumer may be down |
| `rate(http_requests_total{status=~"5.."}[5m]) > 0.05` for > 5m | warning | Elevated error rate |
| `sessions_active_total > 100` | info | High concurrency — consider capacity |
| `tool_calls_total{status="error"} / tool_calls_total > 0.1` | warning | Agent tool failures |
| Coverage drops below 70% on main CI | fail | CI pipeline fails the build |

## Per-Area KPI References

Each critical area of the repository has area-specific KPIs that are assessed when code or specs change in that directory:

| Area | File | Scope |
|---|---|---|
| Pipeline Agents | `backend/agents/KPIs.md` | Ingestion, transformation, quality, integration agents |
| Database Layer | `backend/db/KPIs.md` | Models, migrations, repository |
| Backend Core | `backend/KPIs.md` | APIs, Kafka, vector store, pipeline, orchestrator, aggregator |
| K8s Infrastructure | `k8s/KPIs.md` | Deployments, statefulsets, HPA, ingress, storage |
| Observability Stack | `k8s/observability/KPIs.md` | Prometheus, Grafana, Loki, Fluentd, Alertmanager |
| Vault & Secrets | `k8s/vault/KPIs.md` | Vault, ESO, SecretStore, bootstrap |
| Test Suite | `tests/KPIs.md` | Coverage, test health, module coverage targets |
| Frontend | `frontend/KPIs.md` | Build, chatbot UI, catalog UI, nginx, HPA |
| Design Specs | `specs/KPIs.md` | Spec completeness, KPI awareness, lifecycle |
| CI/CD Pipeline | `.github/workflows/KPIs.md` | Test job, build job, kustomize, pipeline health |
| Deployment Scripts | `scripts/KPIs.md` | Local setup, LaunchAgent, script robustness |
| Documentation | `docs/KPIs.md` (this file) | Completeness, freshness, self-assessment |
