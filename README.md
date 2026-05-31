# Ecommerce Platform — Kafka Streaming Pipeline + RAG Shipping Advisor + Agentic Chat

Full-stack ecommerce platform with an event-driven data pipeline, RAG chatbot,
multi-agent conversational AI, product catalog/quoting API, and React frontend —
deployed on Kubernetes with full observability.

## Architecture

```
Upload API   ──▶  Kafka (product-ingest)  ──▶  Consumer  ──▶  PostgreSQL (product DB)
MinIO/S3     ──▶  Kafka (product-ingest)  ──▶  Consumer  ──▶  ChromaDB (vector store)

React Chatbot  ──▶  Agent API (LangGraph)  ──▶  Products / Shipping / Quote / Pricing /
SSE streaming  │                              Customer Service / Images agents
               │                              ├── PostgreSQL
               │                              ├── ChromaDB
               │                              └── Image CDN (S3 + CloudFront)

Catalog SPA    ──▶  Catalog API  ──▶  PostgreSQL (product queries)
               └──  Upload API   ──▶  Kafka (file→record streaming)

PDF files      ──▶  pipeline.py   ──▶  CSV (legacy import)
```

## Repo structure

```
.
├── backend/
│   ├── agents/              LangGraph agents (Products, Shipping, Quote, Pricing,
│   │                        Customer Service, Images) + ETL agents
│   ├── db/                  SQLAlchemy models, migrations, repository
│   ├── kafka_consumer.py    Streaming consumer (poll → transform → validate → persist)
│   ├── kafka_producer.py    Shared producer helpers
│   ├── chroma_upsert.py     Single-record embedding + ChromaDB upsert
│   ├── api_rag.py           RAG chatbot + LangGraph agent API
│   ├── api_catalog.py       Product catalog, quoting, image upload
│   ├── api_upload.py        File upload → Kafka producer
│   ├── aggregator.py        Periodic composite document build
│   ├── vector_store.py      Full ChromaDB rebuild (legacy)
│   ├── telemetry.py         Structured logging (structlog)
│   ├── metrics.py           Prometheus metric definitions
│   ├── orchestrator.py      Prefect flow (legacy)
│   └── watcher.py           File watcher (legacy)
├── frontend/
│   ├── chatbot/             React chatbot with SSE streaming + agent trace UI
│   └── catalog/             Static catalog SPA
├── k8s/                     Kubernetes manifests (kustomize)
│   ├── observability/       Optional: Loki, Prometheus, Grafana, Fluentd, Alertmanager
│   └── vault/               Vault + External Secrets Operator
├── specs/                   Design specifications
├── scripts/                 Local dev helpers
├── tests/                   pytest suite (14 test files)
├── .github/workflows/       CI/CD pipeline
├── Dockerfile.backend
├── Dockerfile.frontend
└── pyproject.toml
```

## Quick start (local dev)

```bash
# Backend
python -m venv .venv && source .venv/bin/activate
pip install -e ".[test]"

# Run tests
pytest

# Kafka pipeline (requires PostgreSQL + Kafka running)
python -m backend.kafka_consumer

# RAG chatbot (port 8000)
python -m uvicorn backend.api_rag:app --host 0.0.0.0 --port 8000

# Catalog API (port 8001)
python -m uvicorn backend.api_catalog:app --host 0.0.0.0 --port 8001

# Legacy batch pipeline
python run_pipeline.py --all --target inventory

# Frontend
cd frontend/chatbot && npm install && npm run dev
```

## Docs & Specs

| Document | What it covers |
|---|---|
| **Specifications** | |
| [Kafka ingestion spec](specs/kafka-ingestion.md) | Event-driven pipeline replacing batch CronJob with Kafka streaming |
| [Observability spec](specs/observability.md) | Structured logging, Prometheus metrics, Grafana dashboards, alerting |
| [Testing strategy](specs/testing-strategy.md) | pytest suite, CI integration, mock strategy, coverage targets |
| [Agentic chat spec](specs/agentic-chat.md) | LangGraph multi-agent workflow with 6 specialist agents + image CDN |
| [CI/CD pipeline](k8s/ci-cd-spec.md) | GitHub Actions: build, push, kustomize render, artifact upload |
| [K8s deployment](k8s/README.md) | Full Kubernetes spec: components, networking, storage, rollout |
| [Terraform infra](k8s/terraform-infrastructure.md) | AWS infrastructure-as-code: EKS, RDS, MSK, S3, ECR, Route53, ACM |
| **Operational guides** | |
| [DevOps guide](docs/devops.md) | Deployment commands, local dev, troubleshooting |
| [Secrets management](docs/secrets.md) | Vault + External Secrets Operator, bootstrap flow |

## Key decisions

- **Event-driven** — Kafka streaming pipeline replaces batch CronJob for real-time ingestion
- **Incremental ChromaDB upsert** — single-record embedding instead of full O(N) rebuild
- **LangGraph agent system** — 6 specialist agents with local LLM (Ollama/llama3), SSE streaming
- **PostgreSQL + ChromaDB** — structured queries via PG, semantic search via vector store
- **Kustomize** for Kubernetes manifest management
- **Vault + External Secrets Operator** for application secrets
- **Single image, two commands** — backend image runs chatbot (`:8000`) and catalog API (`:8001`)
- **kustomize build + artifact** deployment model (no direct kubectl in CI)
- **Local-first philosophy** — sentence-transformers for embeddings, Ollama for LLM, all self-hosted
- **Optional observability overlay** — Loki, Prometheus, Grafana, Fluentd, Alertmanager
