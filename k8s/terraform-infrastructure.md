# Terraform Infrastructure Management — AWS

## 1. Motivation

The entire application stack is defined as Kubernetes manifests under `k8s/` and
deployed via `kustomize build`. However, there is no infrastructure-as-code
coverage for anything outside the cluster:

| Gap | Impact |
|---|---|
| **No cluster definition in code** | Cluster is assumed pre-existing; team must manually provision EKS/GKE/k3s via console or ad-hoc scripts. No repro, no audit trail. |
| **In-cluster everything** | PostgreSQL, Kafka (via MinIO→Kafka-proxy pattern), MinIO all run as StatefulSets inside Kubernetes. No managed services — no automated backups, no scaling, no patch management. |
| **No DNS or TLS** | Ingress uses `ecommerce.local` with no TLS. Not deployable to production as-is. |
| **Container registry hardcoded** | Images pushed to Docker Hub. No ECR integration, no IAM-based access control. |
| **Manual Vault bootstrap** | Vault runs in-cluster with file storage. Auto-unseal works post-bootstrap, but the initial bootstrap Job is fragile and state lives on a PVC — loss means re-initialization and secret rot. |
| **No networking foundation** | VPC, subnets, NAT, security groups are not defined in code. Every cluster bootstrap starts from scratch. |

Adding Terraform solves all of these by defining the full AWS foundation —
cluster, managed services, networking, DNS, and registry — in codified,
reviewable, state-tracked modules.

---

## 2. Proposed Approach

### Architecture

Terraform provisions and manages all AWS infrastructure. Kustomize continues to
manage application-level Kubernetes resources (Deployments, Services, ConfigMaps,
HPAs, etc.) that deploy on top of the provisioned cluster.

```
┌──────────────────────────────────────────────────────────┐
│                   Terraform (this spec)                   │
│                                                           │
│  AWS Provider                                              │
│  ├── VPC + subnets + NAT + security groups                │
│  ├── EKS cluster + node groups + OIDC provider            │
│  ├── RDS PostgreSQL (replaces in-cluster Postgres)        │
│  ├── MSK Kafka (replaces in-cluster Kafka setup)          │
│  ├── S3 bucket + IAM (replaces MinIO)                     │
│  ├── ECR repositories (replaces Docker Hub)               │
│  ├── Route53 zone + ACM certificate                       │
│  └── IAM roles for EKS pods (IRSA)                        │
│                                                           │
│  Helm Provider                                             │
│  ├── aws-load-balancer-controller                         │
│  ├── external-dns                                         │
│  ├── cert-manager                                         │
│  └── nginx-ingress (upgraded with TLS)                    │
└────────────────────┬─────────────────────────────────────┘
                     │ terraform output → kubeconfig
                     ▼
┌──────────────────────────────────────────────────────────┐
│                  Kustomize (unchanged)                    │
│                                                           │
│  Deployments, Services, ConfigMaps, HPAs, etc.             │
│  Backend (chatbot + catalog), Frontend, ChromaDB,         │
│  Kafka consumer/aggregator, Observability (optional)      │
│                                                           │
│  Secret management: Vault + ESO (unchanged)               │
└──────────────────────────────────────────────────────────┘
```

### Detailed design

#### 2.1 Directory structure

```
terraform/
├── versions.tf              # Terraform / provider version constraints
├── backend.tf               # State backend config (local initially)
├── provider.tf              # AWS + Helm + Kubernetes providers
├── locals.tf                # Common tags, region, name prefix
├── variables.tf             # Input variables
├── outputs.tf               # Outputs (kubeconfig, DB endpoint, etc.)
│
├── networks/
│   └── main.tf              # VPC, public/private subnets, NAT gateway, route tables, security groups
│
├── eks/
│   ├── main.tf              # EKS cluster, node groups, OIDC provider, KMS key for secrets
│   └── irsa.tf              # IAM roles for service accounts (IRSA)
│
├── rds/
│   └── main.tf              # RDS PostgreSQL instance, subnet group, parameter group, secret in AWS Secrets Manager
│
├── msk/
│   └── main.tf              # MSK cluster, topic configuration, client authentication via IAM
│
├── s3/
│   └── main.tf              # S3 buckets (ingest, model-cache, archives)
│
├── ecr/
│   └── main.tf              # ECR repositories (backend, frontend)
│
├── dns/
│   └── main.tf              # Route53 hosted zone, ACM certificate, validation records
│
├── helm/
│   ├── main.tf              # Helm provider config
│   ├── aws-lb-controller.tf # aws-load-balancer-controller (NLB/ALB for ingress)
│   ├── external-dns.tf      # external-dns for Route53 record management
│   ├── cert-manager.tf      # cert-manager for automatic TLS certificate issuance
│   └── ingress-nginx.tf     # nginx-ingress controller with TLS
│
└── monitoring/
    └── main.tf              # (Optional) Prometheus/Grafana/Loki as Helm charts or skip (use existing k8s/observability)
```

#### 2.2 Terraform configuration

**versions.tf**:
```hcl
terraform {
  required_version = ">= 1.8"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.70"
    }
    helm = {
      source  = "hashicorp/helm"
      version = "~> 2.15"
    }
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 2.33"
    }
    tls = {
      source  = "hashicorp/tls"
      version = "~> 4.0"
    }
  }
}
```

**provider.tf**:
```hcl
provider "aws" {
  region = var.aws_region
}

provider "kubernetes" {
  host                   = module.eks.cluster_endpoint
  cluster_ca_certificate = base64decode(module.eks.cluster_ca_cert)
  exec {
    api_version = "client.authentication.k8s.io/v1beta1"
    command     = "aws"
    args        = ["eks", "get-token", "--cluster-name", module.eks.cluster_name]
  }
}

provider "helm" {
  kubernetes {
    host                   = module.eks.cluster_endpoint
    cluster_ca_certificate = base64decode(module.eks.cluster_ca_cert)
    exec {
      api_version = "client.authentication.k8s.io/v1beta1"
      command     = "aws"
      args        = ["eks", "get-token", "--cluster-name", module.eks.cluster_name]
    }
  }
}
```

#### 2.3 Networks (VPC)

| Resource | Configuration |
|---|---|
| **VPC** | CIDR `10.0.0.0/16`, DNS hostnames enabled |
| **Public subnets** | 3 × `/24` across AZs (for NAT gateway and ALB) |
| **Private subnets** | 3 × `/20` across AZs (for EKS nodes and RDS) |
| **NAT Gateway** | Single NAT in public subnet (1 AZ, dev-appropriate) |
| **Internet Gateway** | Standard IGW attached to VPC |
| **Security groups** | EKS cluster SG, RDS SG (allow 5432 from EKS), MSK SG (allow 9092-9098 from EKS) |

#### 2.4 EKS cluster

| Property | Value |
|---|---|
| **Version** | 1.31 |
| **Node group type** | Managed node groups (not self-managed) |
| **Default node pool** | `m6i.large` (3 × min=2, max=6) — covers backend, frontend, ChromaDB, Vault |
| **GPU node pool** | (Optional) `g5.xlarge` — if sentence-transformers offloading to GPU is desired |
| **Add-ons** | `vpc-cni`, `coredns`, `kube-proxy`, `ebs-csi-driver` |
| **Access** | `aws-auth` ConfigMap managed via `aws_eks_access_entry` |
| **Secrets encryption** | KMS key for `kube-system` secrets encryption |
| **IRSA** | IAM roles for: cert-manager, external-dns, aws-load-balancer-controller, EBS CSI driver, Kafka consumer (S3 access) |

#### 2.5 RDS PostgreSQL

Replaces `k8s/postgresql.yaml`. The in-cluster StatefulSet is removed.

| Property | Value |
|---|---|
| **Engine** | PostgreSQL 16 |
| **Instance class** | `db.t3.medium` (dev), `db.r6g.large` (prod) |
| **Storage** | 100GB gp3, auto-scaling to 500GB |
| **Multi-AZ** | false (dev), true (prod) |
| **Backup retention** | 7 days |
| **Deletion protection** | true |
| **Credentials** | Stored in AWS Secrets Manager, synced to K8s Secret via ESO |

The ESO `SecretStore` is updated to reference AWS Secrets Manager as an
additional (or alternative) backend alongside Vault.

#### 2.6 MSK Kafka

Replaces the "external managed Kafka" assumption in `specs/kafka-ingestion.md`.
The spec assumed Confluent / Redpanda; Terraform provisions MSK instead.

| Property | Value |
|---|---|
| **Version** | 3.7.x |
| **Broker type** | `kafka.t3.small` (dev), `kafka.m5.large` (prod) |
| **Broker count** | 3 (1 per AZ) |
| **Storage** | 500GB EBS gp3 per broker |
| **Authentication** | IAM-based (no client certs or SASL/SCRAM to manage) |
| **Encryption** | In-transit TLS, at-rest KMS |
| **Topic auto-creation** | Disabled (MSK requires manual topic creation or via config) |
| **Topics** | `product-ingest`, `product-ingest-dlq`, `minio-events` — created via Terraform resource or post-deploy script |

The consumer and producer code in `backend/` must be updated to use IAM auth
(the `kafka-python` library does not natively support IAM; use
`aws-msk-iam-auth` library or switch to `confluent-kafka` with IAM OAuth).

#### 2.7 S3

Replaces MinIO (`k8s/minio.yaml`). MinIO StatefulSet is removed.

| Bucket | Purpose | Access |
|---|---|---|
| `ecommerce-ingest-{env}` | File uploads (replaces MinIO `ingest/`) | Kafka consumer IRSA role |
| `ecommerce-model-cache-{env}` | sentence-transformers model cache | Backend IRSA role |
| `ecommerce-archives-{env}` | Historical file archival | Backend IRSA role |

#### 2.8 ECR

Replaces Docker Hub as the container registry. The CI/CD pipeline and
`k8s/kustomization.yaml` are updated to reference ECR URLs.

| Repository | Image |
|---|---|
| `ecommerce-backend` | Backend chatbot + catalog |
| `ecommerce-frontend` | Frontend React app |

Tagging scheme: `:latest` + `:<sha>` (same as current, just different registry).

#### 2.9 DNS and TLS

| Resource | Configuration |
|---|---|
| **Route53 zone** | `ecommerce.example.com` (variable) |
| **ACM certificate** | `*.ecommerce.example.com`, DNS-validated via Route53 |
| **Ingress update** | `k8s/ingress.yaml`: host changed to `api.ecommerce.example.com` / `chat.ecommerce.example.com`, TLS added |

#### 2.10 Helm charts (cluster add-ons)

These run in the cluster and are deployed via `helm_release` Terraform resources:

| Chart | Namespace | Purpose |
|---|---|---|
| `aws-load-balancer-controller` | `kube-system` | Provisions ALB/NLB for Kubernetes Ingress/Service of type LoadBalancer |
| `external-dns` | `kube-system` | Creates Route53 records from Kubernetes Ingress/Service annotations |
| `cert-manager` | `cert-manager` | Issues and renews ACM certificates via `Certificate` CRDs |
| `ingress-nginx` | `ingress-nginx` | Upgraded ingress controller with TLS termination (replaces `ingressClassName: nginx` assumption) |

#### 2.11 Remaining in-cluster services

The following stay in Kustomize manifests and are **not** replaced by Terraform:

| Service | Reason |
|---|---|
| **ChromaDB** | No AWS managed equivalent; remains as StatefulSet with EBS CSI driver PVC |
| **Vault + ESO** | Remains in-cluster for runtime secrets; can also reference AWS Secrets Manager as additional backend |
| **Kafka consumer / aggregator** | Application code; remains as Deployment and CronJob |
| **Backend / Frontend** | Application code; remains as Deployments |
| **Observability stack** | Separate overlay; can be deployed or skipped |

#### 2.12 CI/CD changes

The `.github/workflows/build-deploy.yml` requires the following changes:

1. **Terraform plan job** added (optional, can run in a separate workflow)
2. **Docker registry** changed from Docker Hub to ECR
3. **ECR login** step added (`aws ecr get-login-password`)
4. **Kustomize image names** updated to ECR URLs (e.g., `123456.dkr.ecr.us-east-1.amazonaws.com/ecommerce-backend`)

#### 2.13 Environment variables

| Variable | Used by | Source |
|---|---|---|
| `DATABASE_URL` | Backend | RDS endpoint (from Terraform output → K8s secret via ESO) |
| `KAFKA_BOOTSTRAP_SERVERS` | Consumer, upload API | MSK broker list (from Terraform output → K8s secret) |
| `KAFKA_SASL_USERNAME` | Removed | Replaced by IAM auth |
| `KAFKA_SASL_PASSWORD` | Removed | Replaced by IAM auth |
| `S3_ENDPOINT` | Removed | Replaced by env vars for AWS SDK |
| `S3_BUCKET` | Backend | `ecommerce-ingest-{env}` |
| `AWS_REGION` | Backend, consumer | Injected via IRSA |
| `ECR_REPOSITORY` | CI/CD | ECR URL |

#### 2.14 Migration strategy (zero-downtime)

The Terraform-managed infrastructure is provisioned alongside the existing
in-cluster services:

1. Provision RDS, MSK, S3 buckets via Terraform in a new AWS account / VPC.
2. Seed data from in-cluster PostgreSQL → RDS (pg_dump / pg_restore).
3. Configure the Kafka consumer to point to MSK (new env vars).
4. Deploy updated backend pointing to RDS + MSK + S3.
5. Once stable, remove in-cluster PostgreSQL, MinIO, and Kafka-proxy StatefulSets
   from the Kustomize manifests.
6. Remove `k8s/postgresql.yaml`, `k8s/minio.yaml` from `k8s/kustomization.yaml`.
7. Update CI/CD to push to ECR instead of Docker Hub.

---

## 3. Key Decisions

| Decision | Rationale |
|---|---|
| **AWS as cloud provider** | Team chose AWS. EKS, RDS, MSK, and S3 cover all current in-cluster services with managed equivalents. |
| **Local state initially** | Simplest start. Migrate to S3 + DynamoDB locking once the Terraform config is stable and a second person needs to run `terraform apply`. |
| **Separate `terraform/` directory** | Clear separation from `k8s/` manifests. No config bloat in the monorepo root. |
| **Full infrastructure scope (not cluster-only)** | The biggest pain points are in-cluster PostgreSQL, MinIO, and Kafka. Just provisioning EKS without migrating to managed services would leave all the operational burden in place. |
| **MSK with IAM auth** | No client certificate management, no SCRAM passwords to rotate. The consumer code needs a library update (add `aws-msk-iam-auth`), but the ongoing ops cost is near zero. |
| **ECR over Docker Hub** | IAM-based access control, no separate Docker Hub credentials in CI/CD secrets, same AWS account as everything else. |
| **Helm for add-ons, Terraform for infra** | Helm manages in-cluster controllers (LB controller, external-dns, cert-manager, ingress-nginx) because they are Kubernetes resources with CRDs. Terraform manages the cluster itself and AWS services. |
| **Migration alongside existing infra** | Provision new RDS/MSK/S3 while old in-cluster services still run. Cut over by updating env vars. Rollback by reverting env vars. No downtime window. |
| **IRSA for pod-level AWS access** | Each pod gets an IAM role mapped to a K8s ServiceAccount. No hardcoded AWS keys in secrets. |

### Rejected alternatives

| Alternative | Why rejected |
|---|---|
| **Stay cluster-agnostic (existing approach)** | Proved insufficient — no DNS, no TLS, no managed DB/Kafka, no repro cluster provisioning. |
| **Pulumi** | Less team familiarity; smaller AWS module ecosystem than Terraform. |
| **CDK8s** | Manages K8s resources, not AWS infrastructure. Would duplicate Kustomize. |
| **Terraform Cloud state immediately** | Adds process overhead (RBAC, teams, workspace management) before the config is proven. Start local, migrate later. |
| **GKE / Google Cloud** | Team chose AWS. |
| **Self-hosted Kafka in-cluster (Strimzi)** | Adds operator complexity; MSK removes all Kafka ops. |

---

## 4. Open Questions

1. **Terraform workflow in CI/CD**: Should `terraform plan` run on every PR, or
   should infra changes be a manual `terraform apply` workflow? Proposed: plan in
   CI on all PRs touching `terraform/`, apply manually from a dev machine
   (at least initially).

2. **Single-state or environment-per-state**: One state file per environment
   (dev/staging/prod) via workspaces or separate backend configs? Proposed:
   separate backend configs initially (`terraform/backend-dev.tf`,
   `terraform/backend-prod.tf`) — clearer than workspaces for infrastructure.

3. **MSK topic creation**: Terraform `aws_msk_serverless_cluster` and
   `aws_msk_cluster` resources do not manage topics natively. Topics must be
   created via a provisioner, a separate script, or via the MSK Admin API from
   within the cluster. Should we add a post-deploy script or use a Kafka admin
   container Job?

4. **Vault replacement**: With AWS Secrets Manager available, should we
   eventually replace Vault entirely and use ASM + ESO? Proposed: defer to
   follow-up. Keep Vault for now; ESO can source from both ASM and Vault.

5. **Pre-provisioned vs. Terraform-managed ACM certificate**: ACM certificates
   in `us-east-1` are required for CloudFront. The main app uses `us-west-2`.
   Should the spec handle cross-region ACM or keep both in the same region?

6. **EBS CSI driver add-on**: ChromaDB and Vault use StatefulSets with PVCs. The
   EBS CSI driver needs the `ebs-csi-driver` add-on and an IRSA role. Should
   this be in the initial scope or tracked separately?

---

## 5. Implementation Plan

### Phase 1 — Foundation (1 session)

| Step | Files | What | Verification |
|---|---|---|---|
| 1 | `terraform/versions.tf` | Terraform + provider version constraints | `terraform init` succeeds |
| 2 | `terraform/backend.tf` | Local state config | `terraform plan` succeeds with no resources |
| 3 | `terraform/provider.tf` | AWS, Kubernetes, Helm providers | `terraform plan` succeeds |
| 4 | `terraform/locals.tf` | Common tags, region, name prefix | — |
| 5 | `terraform/variables.tf` | Input variables: `region`, `environment`, `name_prefix` | — |
| 6 | `terraform/outputs.tf` | Stub outputs file | — |

### Phase 2 — Networks + EKS (1-2 sessions)

| Step | Files | What | Verification |
|---|---|---|---|
| 7 | `terraform/networks/main.tf` | VPC, subnets, NAT, IGW, SGs | `terraform apply` creates VPC |
| 8 | `terraform/eks/main.tf` | EKS cluster, node groups, KMS key, add-ons | `kubectl get nodes` returns 3 ready nodes |
| 9 | `terraform/eks/irsa.tf` | IAM roles for add-ons | Pod in cluster can assume role via SA |

### Phase 3 — Managed services (2 sessions)

| Step | Files | What | Verification |
|---|---|---|---|
| 10 | `terraform/rds/main.tf` | RDS PostgreSQL, subnet group, secret in ASM | `psql` connects from EKS pod |
| 11 | `terraform/msk/main.tf` | MSK cluster, IAM auth, broker list in ASM | Kafka consumer can produce/consume using IAM |
| 12 | `terraform/s3/main.tf` | S3 buckets + IAM policies | Pod can read/write via IRSA |
| 13 | `terraform/ecr/main.tf` | ECR repositories | `docker push` succeeds |

### Phase 4 — DNS + TLS + Helm add-ons (1 session)

| Step | Files | What | Verification |
|---|---|---|---|
| 14 | `terraform/dns/main.tf` | Route53 zone, ACM cert, validation | `dig` returns NS records; cert status is ISSUED |
| 15 | `terraform/helm/aws-lb-controller.tf` | ALB controller Helm chart | LoadBalancer Service creates ALB |
| 16 | `terraform/helm/external-dns.tf` | external-dns Helm chart | New Ingress creates Route53 record |
| 17 | `terraform/helm/cert-manager.tf` | cert-manager + ClusterIssuer | TLS certificate auto-provisioned |
| 18 | `terraform/helm/ingress-nginx.tf` | nginx-ingress controller | Ingress works with TLS |

### Phase 5 — Migration + CI/CD (2 sessions)

| Step | Files | What | Verification |
|---|---|---|---|
| 19 | `k8s/kustomization.yaml` | Remove `postgresql.yaml`, `minio.yaml` | `kustomize build` no longer includes them |
| 20 | `k8s/ingress.yaml` | Update hostnames, add TLS section | HTTPS works, Route53 resolves |
| 21 | `.github/workflows/build-deploy.yml` | Replace Docker Hub with ECR | CI pipeline pushes to ECR |
| 22 | `backend/kafka_consumer.py` | Update to use IAM auth for MSK | Consumer connects to MSK with no SASL creds |
| 23 | `backend/kafka_producer.py` | Update to use IAM auth | Producer connects to MSK |
| 24 | `backend/db/repository.py` | No change (SQLAlchemy reads `DATABASE_URL`) | — |
| 25 | `pyproject.toml` | Add `aws-msk-iam-auth` dependency | Pip install succeeds |
| 26 | Data migration | pg_dump in-cluster PG → RDS | All products, orders, invoices preserved |

### Verification criteria

- `terraform plan` succeeds with no errors on the full config
- `terraform apply` provisions all resources within 30 minutes
- `kubectl get nodes` shows 3 ready nodes
- `psql $DATABASE_URL` connects to RDS
- Kafka producer/consumer works with MSK over IAM auth
- `curl https://api.ecommerce.example.com/api/products` returns product data
- `curl https://chat.ecommerce.example.com/health` returns OK
- CI/CD pushes to ECR and deploys to cluster
