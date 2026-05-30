# Event-Driven Product Ingestion — Kafka Streaming Pipeline

## 1. Motivation

The current MLOps pipeline uses a batch-oriented CronJob that polls `data/ingest/`
every minute, processes all pending files through four Prefect agents, appends
results to CSV, and triggers a full ChromaDB rebuild as a subprocess. This
approach has several limitations:

| Problem | Impact |
|---|---|
| **1-minute polling latency** | Files sit idle for up to 60s before processing begins |
| **Full ChromaDB rebuild on every run** | O(N) embedding generation even for a single new product; wastes compute as the corpus grows |
| **CSV append-only** | No upsert semantics; no way to update a previously ingested record |
| **Batch granularity** | One corrupted row stalls the entire file; no dead-letter isolation |
| **Manual scaling** | CronJob concurrency is `Forbid`; cannot parallelize within a single file |
| **Prefect dependency** | Adds operational complexity for a simple file→DB pipeline |
| **No file upload API** | Currently files must be placed in the ingest directory out-of-band |

Replacing the batch CronJob with an event-driven Kafka pipeline solves all of
these: files stream through as individual messages, products are processed
immediately, records are upserted into PostgreSQL and ChromaDB incrementally,
and the system scales by adding consumer replicas.

---

## 2. Proposed Approach

### Architecture

```
                          ┌──────────────────────┐
                          │   Upload API          │
  HTTP POST /api/upload   │  (POST /api/upload)   │
  ──────────────────────▶ │  reads file, produces │
                          │  per-record messages   │
                          └──────────┬───────────┘
                                     │ Kafka messages
                                     │ (one per product row)
  ┌──────────────────┐              ▼
  │  MinIO Bucket     │      ┌───────────────┐
  │  ingest/          │─────▶│  Kafka Topic  │
  │  (s3:ObjectCreated)│     │ product-ingest│
  └──────────────────┘      │ partitions: 3 │
                            └───────┬───────┘
                                    │
                          ┌─────────▼────────┐
                          │  Kafka Consumer   │
                          │  (Deployment,     │
                          │   group: product- │
                          │   ingestion)      │
                          │                  │
                          │  1. Parse & tag   │
                          │  2. Transform     │
                          │  3. Validate      │
                          │  4. Write PG      │
                          │  5. Upsert Chroma │
                          └──┬───────────┬───┘
                             │           │
                             ▼           ▼
                      ┌──────────┐ ┌──────────┐
                      │PostgreSQL│ │ ChromaDB │
                      │ products │ │ shipping │
                      │ shipping │ │_advisor  │
                      │ orders   │ │          │
                      │ ...      │ │          │
                      └──────────┘ └──────────┘
```

Two event sources produce to the same Kafka topic:
- **Upload API**: Accepts file uploads via `POST /api/upload`, reads the file,
  and publishes one Kafka message per product record.
- **MinIO bucket events**: When a file is uploaded to the `ingest/` bucket,
  MinIO sends an `s3:ObjectCreated:*` notification to Kafka. A lightweight
  handler fetches the file from MinIO and publishes per-record messages
  (same format as the upload API).

### Topic design

| Property | Value |
|---|---|
| **Topic name** | `product-ingest` |
| **Partitions** | 3 (scales with consumer replicas up to 3) |
| **Replication factor** | 3 (managed by external Kafka service) |
| **Message key** | `product_id` (ensures same product → same partition → ordered processing) |
| **Message value** | JSON — single product record with metadata |
| **Retention** | 7 days (allows replay / recovery) |
| **Cleanup policy** | `delete` |

### Message envelope

```json
{
  "source": "upload_api|minio_event",
  "source_file": "products_march.jsonl",
  "ingested_at": "2026-05-29T12:00:00",
  "target": "inventory",
  "record": {
    "id": "PROD-001",
    "name": "Ultra-light Hiking Boot",
    "category": "Footwear",
    "unit_price": 120.00,
    "units_in_stock": 50,
    "units_sold": 200,
    "report_period": "2026-05"
  }
}
```

Messages are small (single product, no blobs). Heavy payloads (images, 10KB+
text) use the **Claim Check pattern**: upload to MinIO/S3 and pass only the
object key in the message.

### Consumer service

A Python service (new module `backend/kafka_consumer.py`) that:

1. Subscribes to `product-ingest` as a Kafka consumer group `product-ingestion`.
2. Polls messages in micro-batches (up to 100 at a time).
3. For each message, runs the existing agent pipeline functions:
   - `ingestion_agent` — parse + tag (already done; message is pre-parsed)
   - `transformation_agent.transform()` — map fields to canonical schema
   - `quality_agent.quality_report()` — validate
4. On success:
   - Writes to PostgreSQL (product table, shipping orders table, etc.)
   - Generates embedding via `sentence-transformers/all-MiniLM-L6-v2`
   - Upserts to ChromaDB with `product_id` as document ID
   - Commits the Kafka offset
5. On validation failure:
   - Routes the message to a dead-letter topic `product-ingest-dlq`
   - Commits the offset (does not block the partition)
6. On transient error (PG down, ChromaDB unavailable):
   - Does NOT commit the offset (message is retried on rebalance)

### PostgreSQL schema

The catalog API currently reads from CSV files at startup. With the Kafka
pipeline, data is written to PostgreSQL so all readers get a consistent,
queryable view.

| Table | Columns | Source |
|---|---|---|
| `products` | `id`, `name`, `category`, `unit_price`, `units_in_stock`, `units_sold`, `report_period`, `source_file`, `ingested_at`, `updated_at` | Inventory files |
| `shipping_orders` | `id`, `product_name`, `shipper_name`, `unit_shipping`, `total_price`, `quantity`, `ship_country`, `source_file`, `ingested_at` | Shipping order files |
| `purchase_orders` | (per existing schema) | PO files |

The consumer creates tables on first run via a migration module
(`backend/db/migrations.py`) or uses an init container with a SQL script.

### ChromaDB incremental upsert

The current `vector_store.py` performs a full rebuild — reads all CSVs, builds
all document types, and creates a fresh ChromaDB collection. This is slow and
wasteful for single-product updates.

The consumer instead calls a new incremental upsert function that:

1. Takes a single product record (already transformed and validated)
2. Formats it as a natural-language document string (same format as the current
   `build_inventory_documents()`)
3. Generates a 384-dim embedding via `sentence-transformers/all-MiniLM-L6-v2`
4. Upserts to the `shipping_advisor` ChromaDB collection with:
   - **ID**: `product_{product_id}` (enables idempotent overwrite)
   - **Metadata**: product name, category, price, report period
   - **Document**: the formatted text

Aggregated / composite documents (vendor summaries, cross-product analytics)
cannot be built from a single record. These are handled by a separate
periodic Job (`chroma-aggregator`) that runs a lightweight rebuild from
PostgreSQL (not CSV) — no file-system dependency, reads only aggregate
queries.

### File upload

#### Upload API

New endpoint: `POST /api/upload`

```http
POST /api/upload
Content-Type: multipart/form-data

file: <products.csv / .json / .jsonl>
target: inventory
```

Accepts CSV, JSON, and JSONL files. The endpoint:
1. Saves a copy to MinIO `ingest/` for archival (optional, can be skipped)
2. Reads the file, iterates records
3. Publishes each record as a Kafka message to `product-ingest`
4. Returns `{"accepted": true, "record_count": N, "file": "filename.ext"}`

The endpoint is added to the **catalog** service (port 8001) or deployed as a
separate service.

#### MinIO bucket events

MinIO event notification is configured at the bucket level:

```
mc event add ingest/ arn:minio:sqs::kafka:kafka \
  --event put \
  --access-key ... \
  --secret-key ...
```

A separate lightweight consumer (or the same consumer with a topic filter)
listens for MinIO events on a `minio-events` topic, fetches the file from
MinIO, and re-publishes per-record messages to `product-ingest`.

This path is **Phase 2** (see Implementation Plan).

### Dead-letter queue

A second Kafka topic `product-ingest-dlq` stores rejected messages:
- Validation failures
- Unparseable records
- Records that exceed max retries

A separate monitoring script or UI can inspect the DLQ for manual reprocessing.

---

## 3. Key Decisions

| Decision | Rationale |
|---|---|
| **External managed Kafka** (Confluent / Redpanda) | Zero ops burden; no StatefulSet to manage; built-in replication, monitoring, and Schema Registry |
| **PostgreSQL instead of CSV** | Enables upserts, consistent reads across services, removes shared filesystem dependency |
| **PostgreSQL + ChromaDB** (not ChromaDB only) | The catalog/quoting API needs structured queries (category filters, aggregations, stock levels) that ChromaDB cannot do efficiently; PG is the source of truth |
| **Local sentence-transformers** (not OpenAI) | No API cost; no external dependency; model is already used by the RAG API |
| **Incremental ChromaDB upsert** (not full rebuild) | O(1) per product instead of O(N); removes the subprocess dependency; enables real-time updates |
| **Aggregator Job for composite docs** | Cross-product aggregates (vendor summaries, top-selling categories) need full-dataset queries; separate Job keeps the main consumer fast |
| **Kafka consumer group** | Auto-rebalance across replicas; offset-based exactly-once semantics |
| **DLQ for bad messages** | One corrupt record does not block the partition; monitoring can alert on DLQ depth |
| **Claim Check for heavy payloads** | Kafka message size limit (default 1MB); large blobs go to S3/MinIO |

### Rejected alternatives

| Alternative | Why rejected |
|---|---|
| **Keep CSV + CronJob** | Does not solve the listed problems; no upsert, no real-time, full rebuild |
| **Prefect with Kafka trigger** | Extra complexity; Prefect's value (retry UI, run history) is minimal for a single linear pipeline |
| **In-memory queue (Redis / RabbitMQ)** | No offset-based replay, no partition ordering, no consumer group rebalance |
| **Direct SQS / PubSub** | Vendor lock-in; Kafka gives a uniform abstraction across cloud and on-prem |

---

## 4. Changes Summary

### New modules

| Module | Purpose |
|---|---|
| `backend/kafka_consumer.py` | Main consumer loop: poll, process, write PG, upsert Chroma, commit/DLQ |
| `backend/kafka_producer.py` | Shared producer helpers (publish single record, publish batch) |
| `backend/db/models.py` | SQLAlchemy models for PostgreSQL tables (products, shipping_orders, etc.) |
| `backend/db/migrations.py` | `CREATE TABLE IF NOT EXISTS` on startup |
| `backend/db/repository.py` | CRUD operations (upsert product, insert shipping order, etc.) |
| `backend/chroma_upsert.py` | Single-record embedding generation + ChromaDB upsert |
| `backend/api_upload.py` | FastAPI router with `POST /api/upload` endpoint |
| `backend/aggregator.py` | Periodic Job logic for composite ChromaDB documents |

### Modified modules

| Module | Change |
|---|---|
| `backend/api_catalog.py` | Replace CSV `load_data()` with PostgreSQL queries; add upload router |
| `backend/api_rag.py` | No change (already reads ChromaDB) |
| `backend/vector_store.py` | Add `upsert_product(product: dict)` function; keep full rebuild for aggregator |
| `backend/agents/ingestion_agent.py` | Add `parse_record(record: dict) -> dict` for single-record parsing |
| `backend/agents/integration_agent.py` | Replace CSV append + subprocess with PG write + Chroma upsert |
| `backend/orchestrator.py` | Keep `run_pipeline()` for backward compat; mark as deprecated |
| `k8s/pipeline.yaml` | **Removed** — CronJob and associated PVCs/csv-pvc |
| `k8s/backend.yaml` | Add Kafka env vars (`KAFKA_BOOTSTRAP_SERVERS`, `KAFKA_TOPIC`); update catalog command to include upload router |
| `k8s/kustomization.yaml` | Remove pipeline.yaml; add consumer deployment |
| `k8s/chromadb.yaml` | No change (ChromaDB StatefulSet stays) |
| `k8s/postgresql.yaml` | No change (already deployed) |

### New K8s manifests

| Manifest | Purpose |
|---|---|
| `k8s/kafka-consumer.yaml` | Deployment + Service for the Kafka consumer (1–3 replicas) |
| `k8s/kafka-aggregator.yaml` | CronJob for periodic composite document rebuild (runs nightly) |

### Removed resources

| Resource | Reason |
|---|---|
| `k8s/pipeline.yaml` (CronJob) | Replaced by Kafka consumer |
| `mlops-csv-pvc` (ReadWriteMany PVC) | CSV no longer used |
| `mlops-pipeline` ServiceAccount + Role + RoleBinding | CronJob removed |
| `pipeline-config` ConfigMap (S3_ENDPOINT, S3_BUCKET, etc.) | Replaced by Kafka bootstrap config |

### Environment variables

| Variable | Used by | Purpose |
|---|---|---|
| `KAFKA_BOOTSTRAP_SERVERS` | Consumer, upload API | Kafka cluster address |
| `KAFKA_SASL_USERNAME` | Consumer, upload API | SASL/SSL auth (managed Kafka) |
| `KAFKA_SASL_PASSWORD` | Consumer, upload API | SASL/SSL auth |
| `KAFKA_TOPIC_PRODUCT_INGEST` | Consumer, upload API | Topic name (`product-ingest`) |
| `KAFKA_TOPIC_DLQ` | Consumer | Dead-letter topic name |
| `KAFKA_GROUP_ID` | Consumer | Consumer group (`product-ingestion`) |
| `DATABASE_URL` | Consumer, catalog API | PostgreSQL connection string |
| `CHROMA_DB_PATH` | Consumer, chatbot API | ChromaDB persist directory |

---

## 5. Migration Strategy

### Phase 1 — Kafka consumer + Upload API (this spec)

1. Deploy the consumer as a Deployment alongside the existing CronJob.
2. Keep the CronJob running during transition (both paths write to PostgreSQL
   and ChromaDB; consistent schema ensures no conflicts).
3. Once the consumer is stable and all data sources are migrated to the
   upload API or MinIO events, remove the CronJob.

### Phase 2 — MinIO bucket events

1. Configure MinIO event notification to Kafka.
2. Deploy the MinIO event handler (or add a topic route in the consumer).
3. Remove the file-watch polling path from the old pipeline.

### Phase 3 — Aggregator Job

1. Build the aggregate-document CronJob.
2. Switch the ChromaDB upsert from full-rebuild mode to incremental-only.
3. Remove the full-rebuild subprocess from `vector_store.py`.

---

## 6. Resolved Decisions

| Question | Decision | Rationale |
|---|---|---|
| Kafka bootstrap endpoint + SASL creds | Deploy-time K8s Secret (sourced from Vault via ESO, same pattern as postgres/minio). | No hardcoded values; consistent with existing secrets flow. |
| Upload API — save to MinIO first? | Produce to Kafka directly; optionally copy to MinIO for archival. | Fast API path; archival is async and fire-and-forget. |
| sentence-transformers model cache | Shared PVC with chatbot API (`SENTENCE_TRANSFORMERS_HOME`). | ~90MB model downloads once; avoids per-pod download on consumer startup. |
| Aggregator — composite docs | SQL aggregation queries against PostgreSQL. | Simple, debuggable, no extra infra. Revisit if latency becomes an issue. |

The aggregator CronJob will query PostgreSQL with `GROUP BY`, `SUM`, `AVG`
and format results as ChromaDB document strings. Example query for
top-selling categories:

```sql
SELECT category, SUM(units_sold) as total_sold, AVG(unit_price) as avg_price
FROM products
WHERE report_period >= NOW() - INTERVAL '3 months'
GROUP BY category
ORDER BY total_sold DESC;
```

The aggregator runs nightly and upserts composite documents with IDs like
`agg_top_categories`, `agg_vendor_summary`, etc.

---

## 7. Implementation Plan

| Step | Files | What | Verification |
|---|---|---|---|
| 1 | `backend/db/models.py` | SQLAlchemy models for products, shipping_orders, purchase_orders | `python -c "from backend.db.models import Product; print(Product.__tablename__)"` |
| 2 | `backend/db/migrations.py` | `create_tables()` — idempotent table creation | Run against a test PG; `\dt` shows tables |
| 3 | `backend/db/repository.py` | `upsert_product()`, `insert_shipping_order()`, `get_product()`, etc. | Unit test with a local PG |
| 4 | `backend/chroma_upsert.py` | `upsert_product_embedding()` — embed + ChromaDB upsert | Manual test: upsert a product, query it back |
| 5 | `backend/agents/integration_agent.py` | Replace CSV append + subprocess with PG write + Chroma upsert | `python -c "from backend.agents.integration_agent import integrate; integrate(...)"` |
| 6 | `backend/kafka_producer.py` | `publish_record(producer, topic, product)` | Produce a test message, consume it manually |
| 7 | `backend/kafka_consumer.py` | Main loop: poll, transform, validate, integrate, commit/DLQ | Run locally with a test Kafka instance; verify product appears in PG + ChromaDB |
| 8 | `backend/api_upload.py` | FastAPI router: `POST /api/upload` → produce to Kafka | `curl -F "file=@test.jsonl" http://localhost:8001/api/upload` → consumer picks it up |
| 9 | `backend/api_catalog.py` | Replace CSV `load_data()` with PG queries; add upload router | `/api/products` returns same data as before |
| 10 | `backend/aggregator.py` | Composite document builder from PG | Run manually; verify ChromaDB contains summary docs |
| 11 | `k8s/kafka-consumer.yaml` | Deployment with consumer image, Kafka env vars, PG secret, chroma PVC | `kubectl get pods -l app=kafka-consumer` — ready |
| 12 | `k8s/kafka-aggregator.yaml` | CronJob for nightly aggregate rebuild | First run completes without error |
| 13 | `k8s/backend.yaml` | Add Kafka env vars to catalog + chatbot | Catalog pod reads from PG instead of CSV |
| 14 | `k8s/pipeline.yaml` | **Remove** CronJob, PVS, SA, ConfigMap | `kubectl -n ecommerce get cronjob mlops-pipeline` → not found |
| 15 | `k8s/kustomization.yaml` | Remove pipeline.yaml; add kafka-consumer.yaml, kafka-aggregator.yaml | `kustomize build k8s/` succeeds |
| 16 | `Dockerfile.backend` | Add `kafka-python` or `confluent-kafka` dependency; add `psycopg2` | `docker build` succeeds |
| 17 | `pyproject.toml` | Add `kafka-python`, `psycopg2-binary`, `sqlalchemy` | `pip install -e .` succeeds |
