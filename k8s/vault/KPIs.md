# Vault & Secrets Management — KPIs

> Covers Vault server, bootstrap job, External Secrets Operator, and SecretStore configuration in `k8s/vault/`. Secrets health is critical for all services that connect to databases, Kafka, and MinIO.

## 1. Vault Server

| KPI | Definition | Method | Target |
|---|---|---|---|
| Vault Seal Status | Vault is unsealed and operational | `vault status` | Unsealed |
| Vault Uptime | Pod running and healthy | `kubectl get pods -n ecommerce -l app=vault` | Running |
| Token Validity | Service tokens not expired | `vault token lookup` | TTL > 30d |

## 2. Bootstrap Job

| KPI | Definition | Method | Target |
|---|---|---|---|
| Job Completion | Bootstrap completes successfully | `kubectl get jobs -n ecommerce` | Succeeded |
| Secret Count | Secrets written by bootstrap | Vault KV listing | All expected secrets exist |
| Idempotency | Re-running is safe | Static (code review) | Yes (upsert, not create) |

## 3. External Secrets Operator

| KPI | Definition | Method | Target |
|---|---|---|---|
| SecretSync Success | All ExternalSecrets synced to K8s | `kubectl get externalsecret -n ecommerce` | Synced |
| Sync Freshness | Secrets refreshed within polling interval | ESO metrics | < 1h |
| Auth Health | ESO can authenticate to Vault | SecretStore status | Ready |

## 4. Secrets Referenced by Services

| Service | Secret Name | Required Keys | Status |
|---|---|---|---|
| Catalog API | `database-url` | `url` | Required |
| | `kafka-credentials` | `bootstrap-servers`, `sasl-username`, `sasl-password` | Required |
| Chatbot | — | No secrets (uses local ChromaDB) | N/A |
| Kafka Consumer | `database-url` | `url` | Required |
| | `kafka-credentials` | `bootstrap-servers`, `sasl-username`, `sasl-password` | Required |
| PostgreSQL | `postgres-credentials` | `username`, `password` | Required |
| MinIO | `minio-credentials` | `access-key`, `secret-key` | Required |

## Spec Assessment Checklist

When a spec proposes changes in `k8s/vault/`:

- [ ] Are new secrets added to both Vault path and ExternalSecret resources?
- [ ] Is the bootstrap job updated to write new secrets?
- [ ] Are new services wired with `secretKeyRef` env vars (not hardcoded)?
- [ ] Is the `secrets.yaml.template` updated for local development?
- [ ] Are secret rotation procedures documented?
- [ ] Does the new secret require Vault policy updates?
