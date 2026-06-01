# Backend Core — KPIs

> Covers APIs (`api_catalog.py`, `api_rag.py`, `api_upload.py`), streaming (`kafka_consumer.py`, `kafka_producer.py`), observability code (`metrics.py`, `telemetry.py`), pipeline (`pipeline.py`, `orchestrator.py`, `deployments.py`), vector store (`vector_store.py`, `chroma_upsert.py`), and aggregator (`aggregator.py`). When any file in `backend/` (excluding subdirectories) changes, these KPIs must be assessed.

## 1. Catalog API (`api_catalog.py` — port 8001)

| KPI | Definition | Prometheus Query | Target |
|---|---|---|---|
| Request Rate | Requests per second | `sum(rate(http_requests_total{job="catalog"}[1m]))` | — |
| Error Rate (5xx) | Server errors | `sum(rate(http_requests_total{job="catalog",status=~"5.."}[1m]))` | < 1% |
| 4xx Rate | Client errors (bad requests) | `sum(rate(http_requests_total{job="catalog",status=~"4.."}[1m]))` | < 5% |
| Latency p50 | Median response | `histogram_quantile(0.50, rate(http_request_duration_seconds_bucket{job="catalog"}[1m]))` | < 200ms |
| Latency p99 | Slowest 1% | `histogram_quantile(0.99, rate(http_request_duration_seconds_bucket{job="catalog"}[1m]))` | < 1s |
| Uptime | Service scrapable | `up{job="catalog"}` | 1 |
| DB Dependency | DATABASE_URL configured | `http_requests_total{job="catalog",path="/api/health"}` returns 200 | Yes |

**Degradation signals:** Spikes in 4xx on `/api/quote` suggest schema drift between pipeline output and API expectations.

## 2. RAG Chatbot API (`api_rag.py` — port 8000)

| KPI | Definition | Prometheus Query | Target |
|---|---|---|---|
| Request Rate | Chat queries per second | `sum(rate(http_requests_total{job="chatbot"}[1m]))` | — |
| Error Rate | Server errors on /chat | `sum(rate(http_requests_total{job="chatbot",path="/chat",status=~"5.."}[1m]))` | < 1% |
| Latency p50 | Median chat response | `histogram_quantile(0.50, rate(http_request_duration_seconds_bucket{job="chatbot"}[1m]))` | < 500ms |
| Latency p99 | Slowest chat | `histogram_quantile(0.99, rate(http_request_duration_seconds_bucket{job="chatbot"}[1m]))` | < 3s |
| ChromaDB Doc Count | Documents searchable | `chroma_documents_total{collection="shipping_advisor"}` | > 0 |
| Model Loaded | SentenceTransformer ready | Log-derived (`embedding_model_loaded`) | Yes at startup |
| Uptime | Service scrapable | `up{job="chatbot"}` | 1 |

**Degradation signals:** Zero similarity results, empty answers, or high latency indicate ChromaDB issues or embedding model load failures. See also `k8s/observability/KPIs.md` for alertmanager rules.

## 3. Upload API (`api_upload.py`)

| KPI | Definition | Prometheus Query | Target |
|---|---|---|---|
| Upload Rate | Files uploaded per minute | `rate(kafka_messages_produced_total{topic="product-ingest",job="catalog"}[1m])` | — |
| Parse Failure Rate | Uploaded files that fail parsing | Log-derived (`upload_complete` vs 400 response) | < 1% |
| Kafka Produce Success | Messages produced without error | `rate(kafka_messages_produced_total[1m])` | matches upload count |

**Degradation signals:** Upload succeeds but Kafka produce fails silently — check `api_upload.py:83` flush.

## 4. Kafka Streaming (`kafka_consumer.py`, `kafka_producer.py`)

| KPI | Definition | Prometheus Query | Target |
|---|---|---|---|
| Produce Rate | Messages published per second | `rate(kafka_messages_produced_total[1m])` | — |
| Consume Rate | Messages consumed per second | `rate(kafka_messages_consumed_total[1m])` | matches produce rate |
| Consumer Lag | Unprocessed messages | `consumer_lag_total` | < 100 |
| DLQ Rate | Messages sent to dead-letter queue | `rate(kafka_dlq_messages_total[5m])` | < 1% of consumed |
| Consumer Staleness | Seconds since last success | `time() - consumer_last_success_timestamp` | < 60s |
| Group Rebalance Count | Consumer group rebalances | — | < 1/hour |

**Degradation signals:** Growing lag indicates consumer throughput bottleneck; DLQ spikes indicate upstream data quality or schema drift.

## 5. PDF Pipeline (`pipeline.py`)

| KPI | Definition | Instrumentation | Target |
|---|---|---|---|
| Parse Success Rate | PDFs parsed without error | Log-derived (`parse_error`) | ≥ 98% |
| Row Yield | Avg rows per PDF type | Log-derived (`csv_written`) | Varies by doc type |
| Processing Time | Time to parse directory | — | < 30s per 100 files |

**Degradation signals:** High parse errors suggest PDF format changes (columns shifted, new layouts).

## 6. Vector Store (`vector_store.py`, `chroma_upsert.py`)

| KPI | Definition | Prometheus Query | Target |
|---|---|---|---|
| Doc Count | Total vector documents | `chroma_documents_total{collection="shipping_advisor"}` | — |
| Embedding Latency | Time to encode single doc | — | < 500ms |
| Upsert Success Rate | ChromaDB upserts without error | Log-derived | ≥ 99% |
| Collection Exists | Collection created and usable | `chroma_documents_total` > 0 | Yes |

**Degradation signals:** Zero document count despite successful pipeline runs indicates ChromaDB path mismatch or collection name mismatch.

## 7. Pipeline Orchestration (`orchestrator.py`, `deployments.py`)

| KPI | Definition | Instrumentation | Target |
|---|---|---|---|
| Pipeline Success Rate | `run_pipeline` passes all steps | Prefect UI + `PREFECT_FLOW_STATE` gauge | ≥ 95% |
| Step Failure Rate | Failures per pipeline step | Prefect auto-tracks per-task state | ingest < 2%, transform < 1%, validate < 5%, integrate < 1% |
| Watcher Cycle Time | Time to discover + process one file | Prefect flow run duration | < 60s |
| File Failure Rate | Files moved to `failed/` | Log-derived (`moved_to_failed`) | < 5% |
| Cache Hit Rate | `quality_report` returns cached result | `@task(cache_policy=INPUTS)` | ≥ 10% of validation calls |
| Concurrency | Files processed in parallel by `run_all` | `ConcurrentTaskRunner` | ≥ 4 concurrent runs |
| Flow State | Prefect flow run state | `PREFECT_FLOW_STATE{flow_name,state}` | 2 (completed) |
| Schedule Uptime | Cron deployment fires each minute | Prefect scheduled run history | ≥ 99% of expected runs |

**Degradation signals:** `PREFECT_FLOW_STATE` shows repeated `3 (failed)` or `4 (crashed)` for `watch_once` or `run_pipeline` flows; cron deployment misses scheduled slots.

## 8. Aggregator (`aggregator.py`)

| KPI | Definition | Instrumentation | Target |
|---|---|---|---|
| CronJob Success Rate | Aggregator completes without error | — | ≥ 99% |
| Agg Doc Freshness | Aggregate docs up-to-date | — | < 25h |

## Spec Assessment Checklist

When a spec proposes changes in `backend/` root files, verify:

- [ ] Do new API endpoints need Prometheus metrics and structlog logging?
- [ ] Are new metrics added to `metrics.py` and is `generate_latest()` wired?
- [ ] Do new background tasks need health checks or readiness probes?
- [ ] Are error paths logged (not silently swallowed)?
- [ ] Do new modules need type annotations on all public functions?
- [ ] Are there integration/unit tests in `tests/` for the new code?
- [ ] Do Kafka topic names or consumer groups need updating in K8s configs?
- [ ] Does the aggregator CronJob need a new aggregate document type?
- [ ] Do Prefect deployments need notification blocks or alerting rules?
- [ ] Are cache policies (INPUTS) correctly scoped to avoid stale results?
