# CI/CD Pipeline — Build & Deploy

## 1. Motivation

Currently the K8s manifests and Dockerfiles exist but there is no automated
pipeline to build container images, push them to a registry, or generate the
final deployment YAML. Every deploy is manual. This spec defines a CI/CD
pipeline that automates the build → push → manifest generation flow using
GitHub Actions.

## 2. Proposed Approach

A single GitHub Actions workflow (`build-deploy.yml`) that:

1. **Builds** both container images (`backend`, `frontend`)
2. **Pushes** them to Docker Hub with `latest` and commit-sha tags
3. **Updates** the Kustomize image tags in `k8s/kustomization.yaml`
4. **Renders** the final Kubernetes YAML via `kustomize build`
5. **Uploads** the rendered YAML as a workflow artifact (for downstream GitOps
   consumption)

Separation of concerns:
- The **CI pipeline** (this spec) handles build + push + artifact generation.
- **Deployment** is handled out-of-band (ArgoCD / Flux / manual
  `kubectl apply` using the artifact).

### Detailed design

#### Trigger

On every push to `main` and on pull requests targeting `main`.

#### Environment

| Variable | Source | Purpose |
|---|---|---|
| `DOCKER_USERNAME` | GitHub Actions secret | Docker Hub login |
| `DOCKER_PASSWORD` | GitHub Actions secret | Docker Hub login |

#### Steps

```
Trigger: push to main / PR to main
  │
  ├─ 1. Checkout
  ├─ 2. Login to Docker Hub
  ├─ 3. Build & tag backend image
  ├─ 4. Build & tag frontend image
  ├─ 5. Push both images
  ├─ 6. Update kustomization.yaml with new image tags
  ├─ 7. Run kustomize build → output.yaml
  └─ 8. Upload output.yaml as artifact
```

#### Secrets management

Application secrets (PostgreSQL credentials, MinIO credentials) are **not** handled
by the CI pipeline. Instead, they are provisioned at runtime via
**HashiCorp Vault + External Secrets Operator (ESO)**:

1. `SecretStore` (`k8s/vault/secretstore.yaml`) configures the Vault connection
   (Kubernetes auth, path `secret/`, KV v2).
2. `ExternalSecret` resources (`k8s/vault/external-secrets.yaml`) declare which
   Vault paths map to which `kind: Secret` objects.
3. ESO syncs from Vault into native `Secret` objects in the `ecommerce` namespace.
4. Pods reference the resulting `Secret` objects normally (no application changes).

Infrastructure secrets (Docker Hub) remain in GitHub Actions secrets.

#### Image tagging scheme

- `ecommerce-backend:<git-sha>` and `ecommerce-backend:latest`
- `ecommerce-frontend:<git-sha>` and `ecommerce-frontend:latest`

On `main` pushes, both `latest` and the sha tag are pushed. On PRs, only the
sha tag is pushed (no `latest` update).

#### Kustomize update

After pushing, the pipeline patches `k8s/kustomization.yaml` to set
`newTag: <git-sha>` for both images, then runs `kustomize build k8s/` to
render the final YAML. The rendered file is uploaded as a workflow artifact
named `k8s-manifests`.

## 3. Key Decisions

| Decision | Rationale |
|---|---|
| **GitHub Actions** | Native to the repo; no extra infrastructure. |
| **Docker Hub** | Simple public registry; push via username+password secret. |
| **kustomize build + artifact** (not direct `kubectl apply`) | Keeps the pipeline decoupled from any specific cluster. A GitOps tool (or operator) applies the artifact. This matches the "kustomize build + PR" pattern. |
| **latest + sha tags** | `latest` for convenience; `sha` for auditability and rollback. |
| **Single workflow file** | Simpler to maintain than multiple files. |
| **Vault + External Secrets Operator for app secrets** | Secrets never appear in the CI artifact. ESO syncs from Vault at runtime; pods consume standard `Secret` objects. Infra secrets (Docker Hub) stay in GitHub secrets. |

## 4. Open Questions

- Are the Vault paths / role names in `k8s/vault/` correct for the target
  cluster's Vault configuration?
- Should local dev use a direct `secrets.yaml` (from template) or a local Vault
  dev server?

## 5. Implementation Plan

| Step | File | What |
|---|---|---|
| 1 | `.github/workflows/build-deploy.yml` | Create the workflow with build, push, kustomize-build, and artifact upload |
| 2 | `k8s/kustomization.yaml` | Reference `vault/` resources instead of `secrets.yaml` |
| 3 | `k8s/secrets.yaml` → `k8s/secrets.yaml.template` | Rename to template; placeholder values for local dev |
| 4 | `k8s/vault/secretstore.yaml` | Create SecretStore pointing to Vault (Kubernetes auth) |
| 5 | `k8s/vault/external-secrets.yaml` | Create ExternalSecrets for postgres + minio credentials |
| 6 | `.github/workflows/build-deploy.yml` | Remove the secrets generation step (Vault handles it) |
| 7 | `.gitignore` | Remove `k8s/secrets.yaml` entry |

### Vault deployment — sealing, unsealing, and token flow

#### Architecture

```
kustomize build
  │
  ├── vault/config.yaml          Vault server config (file storage, no TLS)
  ├── vault/vault.yaml           StatefulSet + Service + PVC + SA + RBAC
  ├── vault/bootstrap-job.yaml   One-time Job: init → unseal → configure
  ├── vault/secretstore.yaml     SecretStore (ESO → Vault via K8s auth)
  └── vault/external-secrets.yaml ExternalSecrets (Vault path → K8s Secret)
```

Vault is deployed **inside** the `ecommerce` namespace as a single-replica
StatefulSet with file storage backed by a RWO PVC.

#### Sealing and unsealing

Vault starts **sealed** after every restart. The unseal keys are stored in a
K8s Secret (`vault-unseal-keys`) created by the bootstrap Job.

| Phase | What happens |
|---|---|
| **1. Initial deploy** | Vault StatefulSet starts; Vault is sealed. The `vault-unseal-keys` Secret does not yet exist, so the `optional: true` mount is empty. The container's wrapper script skips auto-unseal. |
| **2. Bootstrap Job** | Waits for Vault to respond. Calls `vault operator init` → generates 5 unseal keys + root token. Creates the `vault-unseal-keys` Secret via the K8s API (using the pod's service account + RBAC). Calls `vault operator unseal` with 3 of the 5 keys (threshold=3). Vault is now unsealed. |
| **3. Bootstrap configures Vault** | Enables KV v2 at `secret/`, writes initial app secrets (`postgres`, `minio`), enables K8s auth, writes the `ecommerce` policy, and creates the `ecommerce` role bound to ESO's service account. |
| **4. Pod restart** | Vault starts sealed. The wrapper script finds the `vault-unseal-keys` Secret mounted at `/etc/vault/unseal/`. It iterates over `key-*` files and calls `vault operator unseal` for each. Readiness probe checks `/v1/sys/health` → only succeeds when unsealed. |

Key design points:
- The `vault-unseal-keys` Secret mount is `optional: true` — the pod starts
  even before bootstrap has run.
- The readiness probe checks `/v1/sys/health` (returns 503 when sealed, 200 when
  unsealed), so dependents wait until Vault is actually ready.
- The bootstrap Job is idempotent (`already_initialized` check at start).

#### Token flow (no static tokens)

```
                K8s API (TokenReview)
                ▲
                │
  ┌─────────────┴──────────────┐
  │  Vault K8s auth backend    │
  │  role: ecommerce           │
  │  bound to: external-secrets│
  │  SA                        │
  └──────────┬─────────────────┘
             │ authenticate via SA JWT
  ┌──────────▼─────────────────┐
  │  External Secrets Operator │
  │  serviceAccountRef:        │
  │    external-secrets        │
  └──────────┬─────────────────┘
             │ read secret/data/ecommerce/*  (policy: ecommerce)
  ┌──────────▼─────────────────┐
  │  Vault KV v2               │
  │  secret/data/ecommerce/     │
  │  ├─ postgres (username,     │
  │  │            password)     │
  │  └─ minio   (access-key,    │
  │              secret-key)    │
  └─────────────────────────────┘
```

1. ESO presents the `external-secrets` SA's JWT to Vault's K8s auth endpoint.
2. Vault calls the K8s TokenReview API to verify the JWT is valid.
3. If valid and the SA matches `bound_service_account_names`, Vault returns a
   short-lived Vault token with the `ecommerce` policy attached.
4. ESO uses this token to read secrets from `secret/data/ecommerce/*`.
5. ESO syncs the values into native K8s `Secret` objects.

No long-lived static Vault tokens are stored anywhere. The K8s SA token is
auto-rotated by Kubernetes.

#### Initial deployment order

```
1. kubectl apply -k k8s/        # Creates everything
2. Vault pod starts (sealed)
3. Bootstrap Job runs:
   a. Waits for Vault to respond
   b. Initializes Vault
   c. Stores unseal keys in K8s Secret
   d. Unseals Vault
   e. Configures K8s auth, secrets, policies
4. ESO detects Vault is ready → authenticates via K8s auth
5. ESO syncs secrets → creates postgres-credentials + minio-credentials
6. All pods resolve secret references and start normally
```

### Required GitHub Actions secrets

| Secret | Purpose |
|---|---|
| `DOCKER_USERNAME` | Docker Hub login |
| `DOCKER_PASSWORD` | Docker Hub login |

Verification:
1. Run `kubectl apply -k k8s/`.
2. Watch the bootstrap Job: `kubectl -n ecommerce logs job/vault-bootstrap -f`.
3. Confirm Vault becomes ready: `kubectl -n ecommerce wait --for=condition=ready pod -l app=vault`.
4. Confirm ESO creates the target Secrets: `kubectl -n ecommerce get secret postgres-credentials minio-credentials`.
5. Push to a branch, open a PR, and confirm the workflow runs and the
   `k8s-manifests` artifact contains `ExternalSecret` + `SecretStore` resources
   (not plain `Secret` objects).
