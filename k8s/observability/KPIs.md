# Observability Stack — KPIs

> Covers Prometheus, Grafana, Loki, Fluentd, and Alertmanager in `k8s/observability/`. When any manifest, dashboard, or alerting rule changes, these KPIs govern the release. Also consulted when new specs add instrumentable operations.

## 1. Prometheus

| KPI | Definition | Method | Target |
|---|---|---|---|
| Scrape Target Coverage | All expected jobs (catalog, chatbot, kubernetes-nodes) are up | `up` metric | 3 / 3 |
| Scrape Success Rate | Successful scrapes / total scrapes | `prometheus_target_scrapes_sample_out_of_order_total` | ≥ 99% |
| Rule Evaluation Time | Time to evaluate all alerting rules | `prometheus_evaluator_duration_seconds` | < 5s |
| TSDB Retention | Historical data retention configured | `--storage.tsdb.retention.time` | 15d |
| Storage Usage | TSDB disk usage vs 50Gi PVC | `prometheus_tsdb_storage_blocks_bytes` | < 80% |
| Rule Files Loaded | Alerting rules ConfigMap mounted and parsed | Prometheus `/rules` endpoint | All rules active |

## 2. Grafana

| KPI | Definition | Method | Target |
|---|---|---|---|
| Dashboard Count | Provisioned dashboards loaded | Grafana API / `k8s/observability/grafana-dashboards.yaml` | 3 (Service RED Metrics, Pipeline Metrics, Operational Overview) |
| Data Source Connectivity | Prometheus and Loki datasources configured | Grafana config / provisioning | Connected |
| Panel Error Rate | Panels rendering without errors | Grafana UI / API | 0% |

## 3. Loki

| KPI | Definition | Method | Target |
|---|---|---|---|
| Log Ingestion Rate | Log entries received per second | Loki metrics | — |
| Log Retention | Days of logs retained | Loki config | ≥ 7d |
| Query Latency p99 | Log query response time | Loki metrics | < 5s |
| Storage Usage | Log storage disk utilization | PVC metrics | < 80% |

## 4. Fluentd

| KPI | Definition | Method | Target |
|---|---|---|---|
| Log Forwarding Rate | Log entries forwarded to Loki per second | Fluentd monitoring | — |
| Buffer Queue Size | Unprocessed log entries in buffer | Fluentd `buffer_queue_length` | < 1000 |
| Flush Failure Rate | Failed buffer flushes | Fluentd `flush_error_count` | < 0.1% |

## 5. Alertmanager

| KPI | Definition | Method | Target |
|---|---|---|---|
| Alert Rule Coverage | Number of defined alert rules | `k8s/observability/prometheus-rules.yaml` | ≥ 10 |
| Alert Firing Rate | Active alerts per severity | Alertmanager UI | warning ≤ 2, critical ≤ 0 |
| Notification Delivery | Webhook receiver configured and reachable | Alertmanager config | Yes |
| Inhibition Rules | Critical alerts silence warnings | Alertmanager config | Enabled |

## 6. Metrics Instrumentation Coverage

Every new code module that is a critical path should have Prometheus metrics:

| Metric Type | When to Add | Example |
|---|---|---|
| Counter | Countable events (requests, messages, errors) | `http_requests_total` |
| Histogram | Latency-sensitive operations | `http_request_duration_seconds` |
| Gauge | Current state (counts, sizes, temperatures) | `sessions_active_total` |

Expanding the metrics in `backend/metrics.py` should be a standard step in any spec.

## Spec Assessment Checklist

When a spec proposes changes in `k8s/observability/`:

- [ ] Do new code paths need new Prometheus metrics?
- [ ] Do new metrics need new Grafana dashboard panels?
- [ ] Do new failure modes need alerting rules in `prometheus-rules.yaml`?
- [ ] Do new services need scrape config entries in `prometheus.yaml`?
- [ ] Do new log sources need Fluentd config changes?
- [ ] Are alert thresholds documented in the root `docs/KPIs.md`?
- [ ] Is the `kustomization.yaml` updated with new resources?
- [ ] Have the alert rules been tested with Prometheus `promtool check rules`?
