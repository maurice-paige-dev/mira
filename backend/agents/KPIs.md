# Pipeline Agents — KPIs

> Tracked when changes occur in `backend/agents/` or when new agent specs are written. All metrics are monitored through Prometheus (`backend/metrics.py`) and surfaced in the Pipeline Metrics and Operational Overview Grafana dashboards.

## 1. Ingestion Agent (`ingestion_agent.py`)

| KPI | Definition | Instrumentation | Target |
|---|---|---|---|
| Discovery Rate | New files found in `data/ingest/` per minute | Log-derived (`ingest_complete`) | — |
| Parse Success Rate | Percentage of files that parse without error | Log-derived (`ingest_complete` / `parse_error`) | ≥ 99% |
| Parse Latency | Time to parse a single file | — | < 2s per 10k rows |
| Empty File Rate | Files that contain zero records | Log-derived (empty CSV/JSONL) | 0% |

**Degradation signals:** Files silently skipped, repeated `ValueError`, archiving to `processed/` without records.

## 2. Transformation Agent (`transformation_agent.py`)

| KPI | Definition | Instrumentation | Target |
|---|---|---|---|
| Mapping Coverage | % of source fields successfully mapped to target schema | Log-derived (`transform_complete` record count vs input) | ≥ 95% |
| Transformer Failure Rate | Field-level transformer exceptions | Log-derived (`transformer_failed`) | < 1% of records |
| Unknown Target Rate | Requests for undefined target keys | — | 0 |

**Degradation signals:** High `transformer_failed` logs, output row count significantly less than input.

## 3. Quality Agent (`quality_agent.py`)

| KPI | Definition | Instrumentation | Target |
|---|---|---|---|
| Validation Pass Rate | % of record batches that pass all quality rules | Log-derived (`validation_passed` / `validation_failed`) | ≥ 95% |
| Error Distribution | Most common validation failure fields | Log-derived (error field names) | — |
| Reject Rate | Records sent to DLQ due to validation failure | `kafka_dlq_messages_total{reason=~"Validation.*"}` | < 2% |

**Degradation signals:** Batch-wide validation failures suggest schema drift; single-field errors suggest data quality issues upstream.

## 4. Integration Agent (`integration_agent.py`)

| KPI | Definition | Instrumentation | Target |
|---|---|---|---|
| PG Write Rate | Rows written to PostgreSQL per batch | `products_ingested_total` | matches batch size |
| ChromaDB Upsert Rate | Embeddings written per batch | Log-derived (`chromadb_upsert_complete`) | matches PG count |
| Integration Success Rate | % of batches that commit without rollback | Log-derived (`pg_write_complete` / `integration_failed`) | ≥ 99% |
| Rollback Rate | Transactions rolled back due to error | Log-derived (exception in `_write_to_postgres`) | 0% |

**Degradation signals:** Rollbacks mean data loss risk; ChromaDB < PG count means RAG gaps.

## 5. Schema Config (`schema_config.py`)

| KPI | Definition | Instrumentation | Target |
|---|---|---|---|
| Schema Coverage | Number of supported target schemas | Static (code) | ≥ 4 (inventory, purchase_order, invoice, shipping_order) |
| Required Field Coverage | All required fields present in each schema | Static (code) | 100% |
| Datatype Validity | Every required numeric field has `transformers` entry | Static (code review) | 100% |

**Degradation signals:** Missing required fields cause silent empty writes at integration time.

## Spec Assessment Checklist

When a spec proposes changes in `backend/agents/`, verify:

- [ ] Do new agent types require new Prometheus metrics (counter, histogram, gauge)?
- [ ] Do new schemas in `schema_config.py` have required fields, defaults, and transformers?
- [ ] Is a new Grafana dashboard panel needed for the new agent?
- [ ] Do DLQ routing rules need updating?
- [ ] Are there integration tests in `tests/` for the new agent?
- [ ] Are retry policies appropriate for the agent type (idempotent vs. non-idempotent operations)?
