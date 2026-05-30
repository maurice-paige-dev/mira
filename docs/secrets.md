# Secrets Management

## Overview

Application secrets (PostgreSQL credentials, MinIO access keys) are managed by **HashiCorp Vault + External Secrets Operator (ESO)**. Infrastructure secrets (Docker Hub) stay in GitHub Actions secrets.

```
Vault (KV v2)
  └─ secret/data/ecommerce/postgres  ├─ username
                                      └─ password
  └─ secret/data/ecommerce/minio     ├─ access-key
                                      └─ secret-key
       │
       ▼  (ESO syncs via K8s auth)
       │
K8s Secret  postgres-credentials  ──▶  PostgreSQL / catalog pods
K8s Secret  minio-credentials     ──▶  MinIO / pipeline pods
```

## Vault deployment

Vault runs inside the cluster as a single-replica StatefulSet with file storage.

### Bootstrap flow

| Step | What happens |
|---|---|
| 1 | `kustomize build k8s/ \| kubectl apply -f -` creates all resources |
| 2 | Vault StatefulSet starts — Vault is **sealed + uninitialized** |
| 3 | `vault-bootstrap` Job runs: |
|    | a. Waits for Vault to respond (via `vault-0.vault:8200`) |
|    | b. `vault operator init` — generates 5 unseal keys, root token |
|    | c. Stores keys + token in `vault-unseal-keys` K8s Secret (via K8s API) |
|    | d. `vault operator unseal` × 3 (threshold = 3) |
|    | e. Enables KV v2 at `secret/` |
|    | f. Writes initial secrets: `ecommerce/postgres`, `ecommerce/minio` |
|    | g. Enables K8s auth, creates `ecommerce` role and policy |
| 4 | Vault readiness probe succeeds → pod becomes ready |
| 5 | ESO authenticates via K8s auth → syncs secrets → K8s `Secret` objects |
| 6 | All pods resolve secret references and start |

### Auto-unseal (pod restart)

The Vault container's entrypoint is a wrapper script that:
1. Starts `vault server` in background
2. Waits for it to respond
3. If `/etc/vault/unseal/key-0` exists (from the `vault-unseal-keys` Secret mount): reads each key file and calls `vault operator unseal`
4. Foregrounds the Vault process

The Service is **headless** (`clusterIP: None`):
- `vault:8200` resolves only to **ready** pods (Vault must be unsealed)
- `vault-0.vault:8200` (StatefulSet ordinal DNS) resolves regardless of readiness — used by the bootstrap Job

### Token flow

No static Vault tokens are stored anywhere. ESO authenticates via K8s auth:

```
ESO pod (SA: external-secrets)
  │  presents SA JWT
  ▼
Vault K8s auth (role: ecommerce)
  │  calls K8s TokenReview API
  │  returns short-lived Vault token
  ▼
Vault KV v2 — reads secret/data/ecommerce/*
```

### Readiness probe

Vault's readiness probe hits `/v1/sys/health`:
- **200**: initialized + unsealed → ready
- **503**: initialized + sealed → not ready
- **501**: not initialized → not ready

## One-time Vault setup (if running bootstrap manually)

```bash
# Initialize
vault operator init -key-shares=5 -key-threshold=3

# Unseal (repeat with 3 of 5 keys)
vault operator unseal <key-1>
vault operator unseal <key-2>
vault operator unseal <key-3>

# Login
vault login <root-token>

# Enable KV
vault secrets enable -path=secret kv-v2

# Write secrets
vault kv put secret/ecommerce/postgres username=products password=<your-password>
vault kv put secret/ecommerce/minio access-key=<your-key> secret-key=<your-secret>

# Enable K8s auth
vault auth enable kubernetes
vault write auth/kubernetes/config \
  kubernetes_host=https://kubernetes.default.svc

# Create policy
vault policy write ecommerce - << 'POL'
path "secret/data/ecommerce/*" {
  capabilities = ["read"]
}
POL

# Create role for ESO
vault write auth/kubernetes/role/ecommerce \
  bound_service_account_names=external-secrets \
  bound_service_account_namespaces=external-secrets \
  policies=ecommerce \
  ttl=1h
```

## Local development (without Vault)

For local dev without a K8s cluster, copy the secret template and edit values:

```bash
cp k8s/secrets.yaml.template k8s/secrets.yaml
# Edit k8s/secrets.yaml with your credentials
kubectl apply -f k8s/secrets.yaml
```

The template contains placeholder values:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: postgres-credentials
  namespace: ecommerce
type: Opaque
stringData:
  username: products
  password: changeme
---
apiVersion: v1
kind: Secret
metadata:
  name: minio-credentials
  namespace: ecommerce
type: Opaque
stringData:
  access-key: minioadmin
  secret-key: minioadmin
```

> **Note**: When deploying via kustomize, `k8s/secrets.yaml` is gitignored. The kustomization.yaml references the Vault resources (`vault/secretstore.yaml`, `vault/external-secrets.yaml`) instead. For local dev without Vault, comment out those resources in `kustomization.yaml` and add `secrets.yaml` back.

## Changing secrets

1. Update the value in Vault:
   ```bash
   vault kv put secret/ecommerce/postgres password=<new-password>
   ```
2. ESO will pick up the change within the `refreshInterval` (default: 1h).
3. Pods referencing the K8s Secret will need to be restarted to pick up the new value (unless using a controller that watches Secret changes).

## Revoking access

- Remove the `ecommerce` policy from Vault
- Delete the K8s auth role: `vault delete auth/kubernetes/role/ecommerce`
- Delete the ExternalSecrets: `kubectl -n ecommerce delete externalsecret postgres-credentials minio-credentials`
- Delete the resulting K8s Secrets: `kubectl -n ecommerce delete secret postgres-credentials minio-credentials`

## Files

| File | Purpose |
|---|---|
| `k8s/vault/config.yaml` | Vault server config (file storage, no TLS) |
| `k8s/vault/vault.yaml` | StatefulSet + headless Service + PVC + RBAC |
| `k8s/vault/bootstrap-job.yaml` | One-time init/unseal/configure Job |
| `k8s/vault/secretstore.yaml` | ESO SecretStore (K8s auth → Vault) |
| `k8s/vault/external-secrets.yaml` | ExternalSecret resources for postgres + minio |
| `k8s/secrets.yaml.template` | Local dev template (gitignored actual) |
