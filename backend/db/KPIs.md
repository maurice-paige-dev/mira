# Database Layer — KPIs

> Tracked when changes occur in `backend/db/`. Database health directly impacts catalog API availability, quoting accuracy, and RAG completeness.

## 1. Models (`models.py`)

| KPI | Definition | Instrumentation | Target |
|---|---|---|---|
| Table Completeness | All 4 model tables exist (Product, PurchaseOrder, ShippingOrder, Invoice) | Static (code) | 4 / 4 |
| Index Coverage | Every `nullable=False` column has an index | Static (code review) | 100% |
| Column Type Consistency | Float fields used for prices, Integer for counts | Static (code review) | 100% |
| Migration Completeness | `create_tables()` covers all models | Static (code) | Yes |

**Degradation signals:** Missing indexes cause slow queries under load; type mismatches cause query failures.

## 2. Migrations (`migrations.py`)

| KPI | Definition | Instrumentation | Target |
|---|---|---|---|
| Idempotency | `create_tables()` is safe to run repeatedly | Static (code review) | Yes |
| Migration Latency | Time to create all tables | — | < 5s |
| Error Rate | Failures during table creation | — | 0% |

**Spec assessment:** Any new model must be registered in `Base.metadata` (via inheritance) and added to `create_tables()`.

## 3. Repository (`repository.py`)

| KPI | Definition | Instrumentation | Target |
|---|---|---|---|
| Query Latency p50 | Median DB query time | `db_query_duration_seconds{operation="upsert_product|get_products|..."}` | < 50ms |
| Query Latency p99 | Slowest 1% of queries | `histogram_quantile(0.99, rate(db_query_duration_seconds_bucket[1m]))` | < 500ms |
| Query Error Rate | Failed queries (connection/timeout) | Log-derived (exceptions) | < 0.1% |
| Upsert Correctness | `upsert_product` updates existing rows by product_name | Static (test `test_db_repository.py`) | Pass |
| Connection Pool | No connection leaks (session.close always called) | — | 0 leaked connections |
| Duplicate Product Rate | % of products that are deduplicated (seen in `get_products` set) | Log-derived (line 63-68) | — |

**Degradation signals:** High p99 latency indicates missing indexes or table bloat; connection leaks cause eventual outage.

## 4. Aggregated Queries (`get_aggregated_top_categories`)

| KPI | Definition | Instrumentation | Target |
|---|---|---|---|
| Aggregation Freshness | Age of last aggregator run | `time() - agg_last_run_timestamp` | < 24h |
| Category Coverage | Categories returned by aggregation | Log-derived | ≥ 1 |

## Spec Assessment Checklist

When a spec proposes changes in `backend/db/`, verify:

- [ ] Does a new model need to be added to `Base` subclasses and `create_tables()`?
- [ ] Are there new query patterns that need indexes?
- [ ] Are existing queries instrumented with `db_query_duration_seconds`?
- [ ] Do new repository functions close their sessions?
- [ ] Are tests added in `tests/test_db_repository.py` or `tests/test_db_migrations.py`?
- [ ] Does the aggregator (`backend/aggregator.py`) need updates for new query types?
