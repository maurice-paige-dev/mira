# Kubernetes Infrastructure — KPIs

> Covers all K8s manifests in `k8s/` (core deployments, statefulsets, services, HPA, ingress, PVCs, CronJobs, kustomization). When any manifest changes, these KPIs govern the release.

## 1. Application Deployments

| KPI | Definition | Source | Target |
|---|---|---|---|
| Pod Uptime | All pods in `Running` state | `kubectl get pods -n ecommerce` | 100% |
| Deployment Rollout Success | New revision rolls out without errors | `kubectl rollout status` | Yes |
| Replica Count | Actual replicas match desired replicas | HPA / Deployment spec | 2 (min) |
| Container Restart Rate | Restarts per pod per hour | `kubectl get pods` / Prometheus `kube_pod_container_status_restarts_total` | < 1/hour |
| Image Freshness | Deployed image tag is the latest CI build | CI/CD pipeline | Always latest SHA |

## 2. StatefulSet Health (PostgreSQL, ChromaDB, MinIO)

| KPI | Definition | Source | Target |
|---|---|---|---|
| Data Persistence | PVC bound and healthy | `kubectl get pvc -n ecommerce` | Bound |
| Storage Utilization | PVC usage vs capacity | Prometheus `kubelet_volume_stats_used_bytes` | < 80% |
| DB Connectivity | Catalog API health endpoint returns 200 | `/api/health` | Yes |
| Startup Time | Time from pod creation to readiness | — | < 60s |

## 3. Horizontal Pod Autoscaler

| KPI | Definition | Source | Target |
|---|---|---|---|
| CPU Utilization | Current CPU vs HPA target | `kubectl get hpa -n ecommerce` | ≤ 70% |
| Scale-Up Latency | Time from CPU spike to new pod ready | — | < 120s |
| Min Replicas | Never scale below minimum | HPA spec | 2 per service |

## 4. Ingress / Networking

| KPI | Definition | Source | Target |
|---|---|---|---|
| Route Coverage | All expected paths routed to correct services | `k8s/ingress.yaml` | 100% |
| TLS Termination | SSL configured and valid | Ingress annotations | Yes (in production) |
| Body Size Limit | Upload limit allows catalogue uploads | `proxy-body-size` annotation | ≥ 50m |

## 5. Storage

| KPI | Definition | Source | Target |
|---|---|---|---|
| PVC Capacity | Total storage provisioned | PVC specs | 10Gi (chroma, postgres, minio), 1Gi (model-cache) |
| Volume Snapshots | Backup strategy defined | — | Documented in `k8s/README.md` |
| Access Mode Correctness | RWO for postgres, RWX for chroma | PVC specs | Correct per workload |

## 6. CronJob Health

| KPI | Definition | Source | Target |
|---|---|---|---|
| Aggregator Success Rate | Chroma aggregator CronJob succeeds | `kubectl get jobs -n ecommerce` | ≥ 99% |
| Job Completion Time | Aggregator runtime | — | < 10m |
| Job Cleanup | `ttlSecondsAfterFinished` configured | CronJob spec | 86400s |

## Spec Assessment Checklist

When a spec proposes changes in `k8s/`, verify:

- [ ] Are new services exposed via ClusterIP with correct port mappings?
- [ ] Do new Deployments/StatefulSets have readiness + liveness probes?
- [ ] Are resource requests/limits set (not omitted)?
- [ ] Are secrets referenced via `secretKeyRef` (not hardcoded)?
- [ ] Does the `kustomization.yaml` include the new resource?
- [ ] Do HPA metrics cover the new workload?
- [ ] Are persistent volumes needed and properly configured?
- [ ] Do init containers handle data preconditions (ChromaDB collection, DB migrations)?
- [ ] Has the Terraform spec (`k8s/terraform-infrastructure.md`) been updated for production infrastructure?
