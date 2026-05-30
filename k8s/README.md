# Kubernetes Deployment Spec — MLOps + Ecommerce Platform

## 1. Overview

Deploy the full ecommerce platform (MLOps data pipeline + RAG shipping advisor + catalog/quoting API + frontend) onto Kubernetes. The pipeline ingests product files from object storage, transforms/validates them, commits to a database, and rebuilds the ChromaDB vector store so new data is immediately queryable by the RAG chatbot.

**Status**: Spec (pre-implementation)  
**Target cluster**: Any standard Kubernetes 1.28+ (tested on k3s / EKS / GKE)

---

## 2. Architecture

```
┌─────────────────────────────────────────────────────────┐
│                        Ingress                          │
│                    (nginx-ingress)                       │
└──┬────────────────────┬──────────────────┬──────────────┘
   │                    │                  │
   ▼                    ▼                  ▼
┌──────────┐     ┌──────────┐     ┌──────────────┐
│ Frontend │     │  Chatbot │     │ Catalog API  │
│ (React)  │────▶│  API     │     │ (FastAPI)    │
│          │     │(FastAPI) │     │              │
└──────────┘     └────┬─────┘     └──────────────┘
                      │
                      ▼
              ┌──────────────┐
              │  ChromaDB    │
              │  (Stateful)  │
              └──────────────┘

┌─────────────────────────────────────────────────────────┐
│              Prefect Server / Cloud                      │
│  (schedules & orchestrates pipeline runs)               │
└──────────────────────────┬──────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────┐
│            Prefect Agent (Deployment)                    │
│  polls Prefect Server → creates Jobs per flow run       │
│                                                         │
│  Pipeline flow:                                         │
│  1. Ingest  → read from S3                              │
│  2. Transform → map fields                              │
│  3. Validate → quality checks                           │
│  4. Integrate → write to DB + trigger RAG rebuild       │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│                   Data Layer                             │
│  ┌──────────┐  ┌──────────────┐  ┌──────────────────┐  │
│  │  MinIO   │  │ PostgreSQL   │  │  ChromaDB PVC    │  │
│  │ (S3 API) │  │ (product DB) │  │ (vector store)   │  │
│  └──────────┘  └──────────────┘  └──────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

---

## 3. Components

### 3.1 Frontend (React)

| Field | Value |
|---|---|
| Container | `frontend:latest` (nginx-alpine serving static build) |
| Replicas | 2 (HPA min=2, max=10 @ CPU > 70%) |
| Port | 80 |
| Ingress | `/ → frontend` |
| Resources | requests: 64m CPU, 128Mi RAM; limits: 256m CPU, 512Mi RAM |
| Readiness | HTTP GET /index.html |
| Liveness | HTTP GET /index.html |

### 3.2 Chatbot API (FastAPI — RAG shipping advisor)

| Field | Value |
|---|---|
| Container | `backend:latest` (uvicorn) |
| Replicas | 2 (HPA min=2, max=5 @ CPU > 70%) |
| Port | 8000 |
| Ingress | `/api/chat → chatbot` |
| Resources | requests: 256m CPU, 512Mi RAM; limits: 1 CPU, 2Gi RAM |
| Readiness | HTTP GET /health |
| Liveness | HTTP GET /health |
| Depends on | ChromaDB (read-only for queries) |
| Env | `CHROMA_DB_PATH=/data/chroma`, `SENTENCE_TRANSFORMERS_HOME=/cache` |

### 3.3 Catalog / Quoting API (FastAPI)

| Field | Value |
|---|---|
| Container | `backend:latest` (uvicorn — second process) |
| Replicas | 2 (HPA min=2, max=5 @ CPU > 70%) |
| Port | 8001 |
| Ingress | `/api/catalog → catalog`, `/api/quoting → catalog` |
| Resources | requests: 256m CPU, 512Mi RAM; limits: 1 CPU, 2Gi RAM |
| Readiness | HTTP GET /health |
| Liveness | HTTP GET /health |
| Depends on | PostgreSQL (product data) |

### 3.4 MLOps Pipeline (Prefect)

| Component | K8s Resource | Details |
|---|---|---|
| Prefect Server | **Deployment** + **Service** (port 4200) | Single replica; SQLite (dev) or PostgreSQL (prod) backend |
| Prefect Agent | **Deployment** | Picks up flow runs; creates Kubernetes Jobs per execution |
| Pipeline flow run | **Job** (created by Prefect Agent) | One Job per `run_pipeline` invocation; tasks run as containers |
| Cron trigger | **CronJob** (alternative) | `*/1 * * * *` calls `run_pipeline --deploy`; simpler than Prefect Agent |

**Recommended**: Start with the **CronJob** approach (no Prefect Server dependency), migrate to Prefect Agent + Server when run history / UI / retry observability becomes critical.

#### CronJob variant

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: mlops-pipeline
spec:
  schedule: "*/1 * * * *"
  jobTemplate:
    spec:
      template:
        spec:
          serviceAccountName: mlops-pipeline
          restartPolicy: OnFailure
          containers:
          - name: pipeline
            image: backend:latest
            command: ["python", "run_pipeline.py", "--deploy"]
            env:
            - name: S3_ENDPOINT
              value: "http://minio:9000"
            - name: S3_BUCKET
              value: "ingest"
            - name: CSV_DIR
              value: /data/csv
            - name: CHROMA_DB_PATH
              value: /data/chroma
            volumeMounts:
            - name: csv-storage
              mountPath: /data/csv
            - name: chroma-storage
              mountPath: /data/chroma
          volumes:
          - name: csv-storage
            persistentVolumeClaim:
              claimName: mlops-csv-pvc
          - name: chroma-storage
            persistentVolumeClaim:
              claimName: chroma-pvc
```

### 3.5 ChromaDB

| Field | Value |
|---|---|
| Container | `ghcr.io/chroma-core/chroma:latest` |
| Workload | **StatefulSet** (1 replica) |
| Port | 8000 |
| Storage | PersistentVolumeClaim (10Gi, ReadWriteOnce) |
| Resources | requests: 1 CPU, 2Gi RAM; limits: 2 CPU, 4Gi RAM |
| Readiness | HTTP GET /api/v1/health |
| Env | `IS_PERSISTENT=TRUE`, `PERSIST_DIRECTORY=/chroma/data` |

### 3.6 MinIO (S3-compatible storage)

| Field | Value |
|---|---|
| Container | `quay.io/minio/minio:latest` |
| Workload | **StatefulSet** (1 replica, 4 for HA) |
| Port | 9000 (API), 9001 (console) |
| Storage | PersistentVolumeClaim (10Gi, ReadWriteOnce) |
| Bucket | `ingest/` — files to process; `processed/` — archived; `failed/` — errors |

### 3.7 PostgreSQL

| Field | Value |
|---|---|
| Container | `postgres:16-alpine` |
| Workload | **StatefulSet** (1 replica) |
| Port | 5432 |
| Storage | PersistentVolumeClaim (10Gi, ReadWriteOnce) |
| Databases | `products` (catalog), `prefect` (Prefect Server backend) |

---

## 4. Data Flow

### 4.1 Ingestion path

```
[User uploads file to MinIO bucket "ingest/"]
     │
     ▼
[CronJob: mlops-pipeline every minute]
     │
     ├─ read files from MinIO ingest/
     ├─ ingest (parse JSON/CSV/JSONL)
     ├─ transform (map to target schema)
     ├─ validate (quality checks)
     ├─ integrate (append to PostgreSQL table)
     ├─ move file to MinIO processed/ (or failed/)
     └─ trigger ChromaDB rebuild
          │
          ▼
[Job: rebuild-chromadb] (optional, can be sidecar)
     │
     ├─ read all rows from PostgreSQL
     ├─ generate embeddings (sentence-transformers)
     └─ upsert into ChromaDB
```

### 4.2 Query path (RAG chatbot)

```
[User message → Chatbot API]
     │
     ├─ embed query via sentence-transformers
     ├─ query ChromaDB for top-k similar docs
     ├─ build prompt with retrieved context
     └─ return LLM-generated answer
```

---

## 5. Networking

| Rule | From | To | Port |
|---|---|---|---|
| Ingress → Frontend | Internet | frontend Service | 80 |
| Ingress → Chatbot | Internet | chatbot Service | 8000 |
| Ingress → Catalog | Internet | catalog Service | 8001 |
| Chatbot → ChromaDB | chatbot Pod | chromadb Service | 8000 |
| Pipeline → MinIO | pipeline Job | minio Service | 9000 |
| Pipeline → PostgreSQL | pipeline Job | postgres Service | 5432 |
| Pipeline → ChromaDB | pipeline Job | chromadb Service | 8000 |
| Prefect → Agent | Prefect Server | prefect-agent Service | gRPC |

---

## 6. Storage

| PVC | Access Mode | Size | Used By |
|---|---|---|---|
| `chroma-pvc` | ReadWriteOnce | 10Gi | ChromaDB StatefulSet |
| `mlops-csv-pvc` | ReadWriteOnce | 5Gi | Pipeline CronJob (intermediate CSV storage) |
| `minio-pvc` | ReadWriteOnce | 10Gi | MinIO StatefulSet |
| `postgres-pvc` | ReadWriteOnce | 10Gi | PostgreSQL StatefulSet |

---

## 7. Configuration & Secrets

| Secret | Keys |
|---|---|
| `postgres-credentials` | `username`, `password` |
| `minio-credentials` | `access-key`, `secret-key` |
| `prefect-api-key` | `api-key` (only needed for Prefect Cloud) |

ConfigMap `pipeline-config`:
- `S3_ENDPOINT`
- `S3_BUCKET`
- `TARGET_SCHEMA` (default: `inventory`)
- `LOG_LEVEL` (default: `INFO`)
- `PYTHONUNBUFFERED=1`

---

## 8. Observability

| System | Tool | Details |
|---|---|---|
| Logs | stdout (JSON) → Fluentd → Loki | All components log structured JSON |
| Metrics | Prometheus + kube-state-metrics | HPA targets, custom metrics |
| Dashboards | Grafana | CPU/RAM per component, pipeline success rate, ChromaDB query latency |
| Alerts | Alertmanager | Pipeline failures, Pod CrashLoopBackOff, PVC usage > 80% |
| Prefect UI | Prefect Server or Cloud | Flow run history, task retries, duration, failure logs |

---

## 9. Deployment Order

| Step | What | Verification |
|---|---|---|
| 1 | Namespace (`ecommerce`) | `kubectl get ns` |
| 2 | PostgreSQL StatefulSet + Service | Pod Ready; `psql` connects |
| 3 | MinIO StatefulSet + Service | Pod Ready; `mc ls` works |
| 4 | ChromaDB StatefulSet + Service | Pod Ready; `curl /api/v1/health` returns 200 |
| 5 | PVCs for pipeline storage | Bound |
| 6 | ConfigMap + Secrets | Present |
| 7 | MLOps CronJob | `kubectl get cronjob`; first Job completes |
| 8 | Chatbot API Deployment + Service | Readiness probe passes |
| 9 | Catalog API Deployment + Service | Readiness probe passes |
| 10 | Frontend Deployment + Service | HTTP 200 on / |
| 11 | Ingress | End-to-end: upload file → pipeline processes → chatbot returns new data |
| 12 | HPA + Monitoring | HPA targets configured; metrics visible in Grafana |

---

## 10. Rollout Plan

**Phase 1 — Dev** (this spec):
- Implement all manifests: StatefulSets, Deployments, Services, ConfigMaps, Secrets, PVCs, CronJob, Ingress
- Verify end-to-end on k3d / kind

**Phase 2 — Staging**:
- Deploy to staging cluster
- Add HPA + PodDisruptionBudget
- Set up Prometheus + Grafana

**Phase 3 — Production**:
- Multi-replica MinIO (4-node distributed mode)
- Multi-replica ChromaDB (if supported, else single + rebuild strategy)
- Prefect Server (with PostgreSQL backend) + Prefect Agent (Deployment)
- Configure Alertmanager
- Load test

---

## 11. Migration Notes (CSV → PostgreSQL)

The current pipeline appends to CSV files. In K8s, these CSV paths map to a PVC shared across the CronJob Pod and — if needed — a sidecar. For production:
1. Replace CSV writes with PostgreSQL INSERT in `integration_agent.py`
2. Replace CSV reads in `vector_store.py` with PostgreSQL SELECT
3. This eliminates the `mlops-csv-pvc` and makes the pipeline stateless (except for ChromaDB)

---

## 12. Open Questions

- [ ] Do we keep the CSV intermediate layer or skip straight to PostgreSQL?
- [ ] Should `rebuild_vector_store` be an in-process task or a separate Job?
- [ ] Prefect Server vs Prefect Cloud — which for the target deployment?
- [ ] What is the expected ingest volume (files/day, rows/file) for PVC sizing?
- [ ] Is sentence-transformers model cached in a shared PVC or baked into the image?
