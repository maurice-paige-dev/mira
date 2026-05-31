# Prefect Orchestration Upgrade

## 1. Motivation

The pipeline orchestrator (`backend/orchestrator.py`) and file watcher (`backend/watcher.py`) use Prefect shallowly — `@flow(log_prints=True)` and `@task(retries=N)` decorators — but get almost none of Prefect's value. The result:

- **No state persistence**: Every `run_pipeline()` call creates a `report` dict (`orchestrator.py:36-41`) that vanishes when the process exits. History, timing, and failure context are lost unless structlog logs are retained.
- **Manual error bookkeeping**: The try/except pyramid (`orchestrator.py:59-119`) manually propagates failures and short-circuits. Prefect's DAG engine does this automatically.
- **Reimplemented scheduler**: `watcher.py:136-170` is a polling loop (`time.sleep(1)`, file mtime checks, `_is_stable()`) that Prefect's `CronSchedule` and `EventTrigger` provide natively.
- **No caching**: `quality_report()` re-validates identical input on every run. No dedup.
- **No concurrency**: `run_all()` (`orchestrator.py:126-138`) processes files sequentially.
- **No notifications**: Failed files silently move to `data/ingest/failed/` with no alert.

Upgrading to full Prefect (server + deployments + schedules + notifications) eliminates the hand-rolled infrastructure with minimal code changes.

## 2. Proposed Approach

Deploy a Prefect server (one container), replace `watcher.py` with a scheduled Prefect deployment, wire task dependencies declaratively, add caching for quality checks, add concurrency for batch processing, and add Slack/webhook notifications on failure.

### Architecture

```
┌──────────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  Prefect Server      │     │  Prefect Agent    │     │  Pipeline        │
│  (State + History)   │◄────│  (Schedules +     │◄────│  Tasks           │
│  SQLite / PostgreSQL │     │   Deployments)    │     │  (ingest →       │
│  :4200 (UI)          │     │                   │     │   transform →    │
└──────────────────────┘     └──────────────────┘     │   validate →     │
                                                       │   integrate)     │
                                                       └─────────────────┘
```

### Detailed design

#### 2.1 Prefect Server

**Local dev:**
```bash
pip install prefect
prefect server start   # SQLite-backed, port 4200
```

**Production (K8s):**
A new Deployment + Service in `k8s/prefect.yaml`. PostgreSQL-backed for production durability:

```yaml
# k8s/prefect.yaml (new)
apiVersion: apps/v1
kind: Deployment
metadata:
  name: prefect-server
  namespace: ecommerce
spec:
  replicas: 1
  selector:
    matchLabels:
      app: prefect-server
  template:
    metadata:
      labels:
        app: prefect-server
    spec:
      containers:
        - name: server
          image: prefecthq/prefect:3-latest
          command: ["prefect", "server", "start"]
          env:
            - name: PREFECT_UI_URL
              value: "http://localhost:4200"
            - name: PREFECT_API_URL
              value: "http://localhost:4200/api"
            - name: PREFECT_SERVER_API_HOST
              value: "0.0.0.0"
            - name: PREFECT_SERVER_API_PORT
              value: "4200"
            - name: PREFECT_API_DATABASE_CONNECTION_URL
              valueFrom:
                secretKeyRef:
                  name: database-url
                  key: url   # reuse existing PG; PREFECT_API_DATABASE_CONNECTION_URL=postgresql+asyncpg://...
          ports:
            - containerPort: 4200
          resources:
            requests:
              memory: 256Mi
              cpu: 100m
            limits:
              memory: 1Gi
              cpu: 500m
```

A `Service` exposing port 4200 and a PVC for SQLite fallback. The `kustomization.yaml` is updated.

The **chatbot and catalog containers** need `PREFECT_API_URL=http://prefect-server:4200/api` set so their `@flow` and `@task` calls can persist to the server.

#### 2.2 Replace watcher.py with Prefect Schedule

**Delete** `backend/watcher.py` (and `com.ecommerce.ingest-watcher.plist`, `install-watcher.sh`).

**Create** a new deployment file `backend/deployments.py`:

```python
from prefect import flow
from prefect.deployments import Deployment
from backend.orchestrator import run_pipeline

# ── Continuous watcher deployment ──────────────────────
# Polls data/ingest/ every 60 seconds via the ingestion agent's
# discover_new_files(), then runs the pipeline on each file.
# This replaces watcher.py:136-170 and the LaunchAgent.

@flow(log_prints=True)
def watch_once():
    """Process all ready files and stop (called by schedule)."""
    from backend.agents.ingestion_agent import discover_new_files
    from backend.watcher import discover_ready_files, process_one

    files = discover_ready_files()
    for f in files:
        process_one(f, rebuild_rag=True)

if __name__ == "__main__":
    # Register as a scheduled deployment
    watch_once.serve(
        name="file-watcher",
        cron="* * * * *",               # every minute
        tags=["pipeline", "ingestion"],
        description="Poll data/ingest/ and process new files",
    )
```

The `watch_once()` flow wraps the existing `discover_ready_files()` and `process_one()` from `watcher.py` — no need to rewrite the stability-checking logic.

**Also register** the bulk-reprocess deployment:

```python
@flow(log_prints=True)
def bulk_reprocess():
    """Run pipeline on all files in processed/."""
    from backend.orchestrator import run_all
    return run_all()

if __name__ == "__main__":
    bulk_reprocess.serve(
        name="bulk-reprocess",
        tags=["pipeline", "maintenance"],
        description="Re-process all files in processed/",
    )
```

This can be triggered ad-hoc from the Prefect UI instead of running `python -m backend.orchestrator`.

#### 2.3 Declarative Task Dependencies

Replace the try/except pyramid in `orchestrator.py` with proper task dependencies. The flow body becomes:

```python
@flow(log_prints=True)
def run_pipeline(file_path: Path, target: str = "inventory", rebuild_rag: bool = True) -> dict:
    rows = ingestion_agent.ingest(file_path)          # @task(retries=2)
    transformed = transformation_agent.transform(rows, target)  # @task(retries=1)
    qr = quality_agent.quality_report(transformed, target)      # @task
    if not qr["passed"]:
        return {"passed": False, "target": target, "errors": qr["errors"]}
    result = integration_agent.integrate(transformed, target, rebuild_rag=rebuild_rag)  # @task(retries=1)
    return {"passed": True, "target": target, **result}
```

Prefect automatically:
- Skips downstream tasks if an upstream task raises
- Records each task's duration, state, and return value
- Retries only the failed task (not the whole flow)
- Propagates the `report` dict via return value

The manual `try/except/report["steps"]/return report` pattern is deleted.

#### 2.4 Caching for Quality Checks

Add a cache policy to `quality_agent.quality_report`:

```python
from prefect.cache_policies import INPUTS
from datetime import timedelta

@task(cache_policy=INPUTS, cache_expiration=timedelta(hours=1))
def quality_report(rows: list[dict], target_key: str) -> dict:
    # ... existing body ...
```

If the identical `(rows, target_key)` pair is submitted within 1 hour, Prefect returns the cached result without re-validating. This matters when the same CSV file is accidentally re-dropped into `data/ingest/`.

#### 2.5 Concurrency for Bulk Processing

`run_all()` currently loops sequentially:

```python
@flow(log_prints=True)
def run_all(rebuild_rag: bool = True, dry_run: bool = False) -> list[dict]:
    files = ingestion_agent.discover_new_files()
    reports = []
    for f in files:
        r = run_pipeline(f, target="inventory", ...)  # sequential
        reports.append(r)
    return reports
```

Change to concurrent execution:

```python
from prefect.task_runners import ConcurrentTaskRunner

@flow(log_prints=True, task_runner=ConcurrentTaskRunner)
def run_all(rebuild_rag: bool = True, dry_run: bool = False) -> list[dict]:
    files = ingestion_agent.discover_new_files()
    # .map() submits each file as a separate concurrent run
    reports = run_pipeline.map(
        file_path=files,
        target=["inventory"] * len(files),
        rebuild_rag=[rebuild_rag] * len(files),
        dry_run=[dry_run] * len(files),
    )
    return reports
```

`run_pipeline.map()` fans out N concurrent pipeline runs (limited by Prefect's concurrency defaults or explicit `with concurrency:` blocks).

#### 2.6 K8s Prefect Agent

A Prefect Agent pod in the cluster picks up scheduled deployments and executes them:

```yaml
# Also in k8s/prefect.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: prefect-agent
  namespace: ecommerce
spec:
  replicas: 1
  selector:
    matchLabels:
      app: prefect-agent
  template:
    metadata:
      labels:
        app: prefect-agent
    spec:
      containers:
        - name: agent
          image: backend:latest   # same image, has all code
          command:
            - prefect
            - agent
            - start
            - --work-queue
            - default
          env:
            - name: PREFECT_API_URL
              value: "http://prefect-server:4200/api"
```

The agent runs inside the cluster with access to the same PVCs (chroma-storage, model-cache) and secrets (database-url, kafka-credentials).

#### 2.7 Notifications

Add a notification block in `deployments.py`:

```python
from prefect_webhooks import WebhookNotification

notification = WebhookNotification(
    name="pipeline-failure",
    webhook_url=os.environ.get("SLACK_WEBHOOK_URL", ""),
    description="Slack alert on pipeline failure",
)

watch_once.serve(
    name="file-watcher",
    cron="* * * * *",
    tags=["pipeline"],
    notifications=[notification],
)
```

#### 2.8 Flow State Metrics

Add a Prometheus metric for Prefect flow run states:

```python
# backend/metrics.py (add)
PREFECT_FLOW_STATE = Gauge(
    "prefect_flow_state",
    "Prefect flow run state (1=success, 0=failure)",
    ["flow_name"],
)
```

A post-run hook updates this:

```python
@flow(on_completion=[update_flow_metric], on_failure=[update_flow_metric])
def run_pipeline(...):
    ...
```

### Configuration changes

| Env var | Used by | Value |
|---|---|---|
| `PREFECT_API_URL` | All containers running flows | Local: `http://localhost:4200/api`, K8s: `http://prefect-server:4200/api` |
| `PREFECT_API_DATABASE_CONNECTION_URL` | Prefect server | Local: `sqlite+aiosqlite:///...`, K8s: reuse PostgreSQL (`postgresql+asyncpg://...`) |
| `SLACK_WEBHOOK_URL` | Notification (optional) | Slack incoming webhook URL |
| `PREFECT_LOGGING_LEVEL` | All | `INFO` |

## 3. Key Decisions

| Decision | Choice | Rationale |
|---|---|---|
| **Server mode vs. ephemeral** | Server mode | Ephemeral (`@flow` without server) gives no history, no UI, no scheduling — the current state. The whole point is persistence + scheduling. |
| **SQLite vs. PostgreSQL backend** | SQLite locally, PostgreSQL in K8s | SQLite requires zero setup for dev. K8s PG is already running; Prefect's async driver works with the same `DATABASE_URL`. |
| **Replace watcher.py vs. wrap it** | Wrap watcher logic in a new `watch_once` flow | `discover_ready_files()` and `process_one()` work correctly and handle edge cases (stability checks, temp files, failed/ dir). No need to rewrite. |
| **Delete watcher.py** | Yes | Replaced entirely by Prefect's cron schedule. The LaunchAgent plist (`com.ecommerce.ingest-watcher.plist`) and `install-watcher.sh` are also deleted. |
| **Caching for quality checks** | `cache_policy=INPUTS` with 1-hour TTL | Avoids re-validation when the same CSV is re-submitted. 1 hour is short enough that schema changes don't silently pass. |
| **ConcurrentTaskRunner for run_all** | Yes | Safe because each pipeline run writes to different tables/is idempotent (upsert). No shared mutable state between runs. |
| **Prefect agent vs. K8s CronJob** | Prefect agent (always-on) | Agent is simpler than maintaining CronJob scheduling + state. Agent polls the server for work; no `kubectl create job` needed. |
| **Slack vs. email notifications** | Webhook (Slack or generic) | Prefect notifications integrate via webhook blocks. Slack is the most common; email requires SMTP setup. Configurable via env var. |

## 4. Open Questions

- **Prefect version compatibility**: Prefect 3.x changed the API significantly from 2.x. Is `prefect>=3.0` in `pyproject.toml` sufficient for server mode, or do we need to pin a specific minor version?
- **PostgreSQL async driver**: Prefect server requires `asyncpg` for the PG backend. Verify the existing `DATABASE_URL` format works with `postgresql+asyncpg://` or if a separate connection URL is needed.
- **Existing `prefect` import in orchestrator.py**: The current `from prefect import flow` will continue to work. But namespace collisions with the new `prefect.deployments`, `prefect.task_runners`, etc. need to be checked.
- **PVC access**: The Prefect agent pod needs read/write access to the same chroma-storage and model-cache PVCs as the consumer and aggregator. Confirm `ReadWriteMany` access mode on the chroma-pvc.
- **Prefect UI ingress**: Should the Prefect UI (`:4200`) be exposed via the nginx ingress (`k8s/ingress.yaml`) or remain cluster-internal with `kubectl port-forward`?

## 5. Implementation Plan

| Step | What | Files Changed / Created | Verification |
|---|---|---|---|
| 1 | Install prefect server dependencies | `pyproject.toml` (add `asyncpg`, `prefect[server]`) | `pip install -e ".[test]"` succeeds |
| 2 | Create `backend/deployments.py` with `watch_once` + `bulk_reprocess` flows | Create `backend/deployments.py` | `python -m backend.deployments` registers deployments |
| 3 | Refactor `orchestrator.py`: remove try/except pyramid, use declarative task dependencies | `backend/orchestrator.py` | `pytest` passes; flow runs without manual bookkeeping |
| 4 | Add caching to `quality_agent.quality_report` | `backend/agents/quality_agent.py` | Second call with same input returns cached result |
| 5 | Add `ConcurrentTaskRunner` to `run_all()` | `backend/orchestrator.py` | `run_all()` processes N files concurrently |
| 6 | Add `PREFECT_FLOW_STATE` metric to `backend/metrics.py` | `backend/metrics.py` | Metric appears at `/metrics` endpoint |
| 7 | Create `k8s/prefect.yaml` (server + agent deployments + service + PVC) | Create `k8s/prefect.yaml` | `kustomize build k8s/` succeeds |
| 8 | Add Prefect server to `k8s/kustomization.yaml` | `k8s/kustomization.yaml` | Server + agent pods start |
| 9 | Add `PREFECT_API_URL` to chatbot, catalog, and consumer env vars | `k8s/backend.yaml`, `k8s/kafka-consumer.yaml` | Flows appear in Prefect UI |
| 10 | Update `k8s/ingress.yaml` for Prefect UI (if needed) | `k8s/ingress.yaml` | UI reachable at `/prefect/` |
| 11 | Delete `watcher.py`, `com.ecommerce.ingest-watcher.plist`, `install-watcher.sh` | Remove 3 files | No references remain |
| 12 | Update `README.md` and `AGENTS.md` | `README.md`, `AGENTS.md` | References to watcher replaced with Prefect |

## 6. KPIs Affected

See `backend/KPIs.md` — Pipeline Orchestration section:

| KPI | Current (shallow) | After Upgrade |
|---|---|---|
| Pipeline Success Rate | Log-derived (`pipeline_complete` vs logs) | Prefect UI + `PREFECT_FLOW_STATE` gauge |
| Step Failure Rate | Manual try/except tracking | Prefect auto-tracks per-task state |
| Watcher Cycle Time | `watcher.py` polling loop | `prefect agent` picks up cron-triggered deployments |
| File Failure Rate | Log-derived (`moved_to_failed`) | Prefect run states + notification blocks |
| Cache Hit Rate | 0% (never caches) | `cache_policy=INPUTS` eliminates redundant `quality_report` runs |
| Concurrency | 1 file at a time | N files concurrently via `ConcurrentTaskRunner` |
| Recovery Time | Manual — grep logs for `moved_to_failed` | Instant — Prefect UI + Slack notification |

See `backend/agents/KPIs.md` — Quality Agent: validate cache hit rate will need a new KPI row.

## 7. Spec Assessment Checklist

- [x] KPIs Affected section added referencing `backend/KPIs.md`
- [x] Prometheus metrics identified (`PREFECT_FLOW_STATE`)
- [ ] Grafana dashboard panel for Prefect flow state needed
- [ ] Alerting rules for Prefect flow failures (new `k8s/observability/prometheus-rules.yaml` entry)
- [x] Test coverage: existing `pytest` tests must pass after `orchestrator.py` refactor
- [x] AGENTS.md updated with prefect server usage notes
- [x] README.md docs table updated
