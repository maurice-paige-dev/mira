# Ecommerce Platform — MLOps + RAG Shipping Advisor

Full-stack ecommerce platform with an MLOps data pipeline, RAG chatbot, catalog/quoting API, and React frontend — deployed on Kubernetes.

## Architecture

```
Frontend (React / Vite)  ──▶  Chatbot API (FastAPI)  ──▶  ChromaDB (vector store)
                             Catalog API (FastAPI)  ──▶  PostgreSQL (product DB)
                             MLOps Pipeline (CronJob) ──▶  MinIO (S3), PostgreSQL, ChromaDB
```

## Repo structure

```
.
├── backend/              Chatbot + catalog APIs, pipeline logic
├── frontend/
│   ├── chatbot/          React chatbot (Vite)
│   └── catalog/          Static catalog HTML
├── k8s/                  Kubernetes manifests (kustomize)
├── scripts/              Local dev helpers (macOS watcher)
├── tests/                Test suite
├── .github/workflows/    CI/CD pipeline
├── Dockerfile.backend
├── Dockerfile.frontend
└── pyproject.toml
```

## Quick start (local dev)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e .
python run_pipeline.py --all --target inventory
```

## Docs

| Document | What it covers |
|---|---|
| [K8s architecture](k8s/README.md) | Full Kubernetes deployment spec: components, networking, storage, rollout plan |
| [CI/CD pipeline](k8s/ci-cd-spec.md) | GitHub Actions workflow: build, push, kustomize render, artifact upload |
| [DevOps guide](docs/devops.md) | Deployment commands, local dev, troubleshooting |
| [Secrets management](docs/secrets.md) | Vault + External Secrets Operator, bootstrap flow, local dev secrets |

## Key decisions

- **Kustomize** for Kubernetes manifest management
- **Vault + External Secrets Operator** for application secrets (no secrets in CI artifacts)
- **CronJob** for pipeline scheduling (Prefect deferred to Phase 2)
- **Single image, two commands** — backend image runs chatbot (`:8000`) and catalog API (`:8001`)
- **kustomize build + artifact** deployment model (no direct kubectl in CI)
