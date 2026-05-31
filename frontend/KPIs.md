# Frontend — KPIs

> Covers the React chatbot app (`frontend/chatbot/`) and catalog static site (`frontend/catalog/`). When frontend code changes, these KPIs must be assessed. When new specs propose UI changes, frontend KPIs must be reviewed and updated.

## 1. Build & Deploy

| KPI | Definition | Source | Target |
|---|---|---|---|
| Build Success | Vite builds without errors | `npm run build` | Pass |
| Bundle Size | Production JS bundle | Vite output | < 256KB |
| Build Time | Total build duration | CI | < 60s |

## 2. Chatbot UI (`frontend/chatbot/`)

| KPI | Definition | Method | Target |
|---|---|---|---|
| API Connectivity | `/chat` endpoint reachable from browser | UI renders without network error | Always |
| Response Rendering | Chat responses display within 500ms of API response | User-perceived latency | < 500ms |
| Error Handling | API errors show user-friendly message, not raw JSON | UI inspection | Yes |

## 3. Catalog UI (`frontend/catalog/`)

| KPI | Definition | Method | Target |
|---|---|---|---|
| Static Content Load | `index.html` serves without errors | HTTP status | 200 |
| API Data Display | Product listings render from `/api/products` | UI inspection | Yes |

## 4. Frontend Infrastructure

| KPI | Definition | Source | Target |
|---|---|---|---|
| Docker Build | `Dockerfile.frontend` builds with nginx | CI (`build-deploy.yml`) | Pass |
| Nginx Config | Routes `/api/*` to backend, `/` to static files | `nginx.conf` | Correct |
| HPA Scaling | Frontend scales under load | `k8s/hpa.yaml` (2–10 replicas, CPU 70%) | Responsive |
| Memory Usage | Frontend pod memory | Prometheus `container_memory_working_set_bytes` | < 128Mi per pod |

## Spec Assessment Checklist

When a spec proposes frontend changes:

- [ ] Do new UI features have corresponding API endpoints?
- [ ] Are API calls wrapped with error handling (catch + user message)?
- [ ] Does the nginx reverse proxy route need updates?
- [ ] Are HPA thresholds still appropriate for the new workload?
- [ ] Is the Vite bundle size increase within acceptable limits?
- [ ] Are environment variables (VITE_API_URL) properly configured for dev vs prod?
