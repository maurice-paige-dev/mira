# Testing Strategy

## 1. Motivation

The repo has zero automated tests in CI and one manually-run smoke-test script (`tests/test_rag.py`). The recent Kafka ingestion rewrite introduced critical integration points (PostgreSQL, ChromaDB, Kafka) with no test coverage. Bugs in the pipeline go undetected until runtime in production.

## 2. Current State

| Aspect | Status |
|---|---|
| Test framework | None. `pyproject.toml` has no `[project.optional-dependencies]` for test/dev. |
| Existing tests | `tests/test_rag.py` — 108-line script that runs 12 hardcoded queries against a live ChromaDB. Not pytest, no assertions. |
| CI test step | Missing in `.github/workflows/build-deploy.yml`. Pipeline builds images — no testing. |
| Frontend tests | `package.json` has no test runner (no Vitest, no Jest, no Testing Library). |
| Coverage tool | Not configured. |
| Python modules | 21 files (agents, APIs, DB, Kafka, vector store). Zero unit tests. |

### What could break and why

| Module | Risk | Failure mode |
|---|---|---|
| `api_catalog.py` | DB queries, shipping estimation, pagination | Wrong prices, wrong stock counts, broken pagination |
| `api_rag.py` | Embedding model load, ChromaDB query, answer builder | 500 on `/chat`, garbled answers, crash on startup |
| `api_upload.py` | File parsing, Kafka producer config, SASL auth | Rejected uploads, silent message drops, unhandled file types |
| `kafka_consumer.py` | Poll loop, message routing, DLQ, retry logic | Messages silently dropped, infinite retry loops, crash on bad data |
| `kafka_producer.py` | SASL config, serialization, flush/batch | Data loss, connection leaks |
| `chroma_upsert.py` | Embedding, collection lifecycle, upsert semantics | Duplicate documents, wrong metadata, collection not found |
| `db/repository.py` | SQL queries, dedup, aggregation | Wrong product lists, broken quotes, bad RAG context |
| `db/models.py` | ORM mapping, column types | Silent truncation, type errors at query time |
| `ingestion_agent.py` | CSV/JSON/JSONL parser, file archiving | Parse errors not surfaced, file loss |
| `transformation_agent.py` | Field mapping, aliasing, transformers | Wrong data in canonical fields |
| `quality_agent.py` | Required field checks, type validation, range checks | Bad data passes through validation |
| `integration_agent.py` | PG write, ChromaDB upsert, rollback | Partial writes, DB corruption, missing rollback |
| `aggregator.py` | SQL aggregation queries, ChromaDB document building | Wrong aggregate docs in RAG context |
| `orchestrator.py`, `pipeline.py` | Prefect flow orchestration | Pipelines don't run or fail silently |
| `watcher.py` | File system watcher, Prefect deployment registration | New files never ingested |
| `vector_store.py` | Full ChromaDB rebuild | Long rebuild times, stale data |

## 3. Proposed Approach

### 3.1 Test framework

Add `pytest` with plugins to `pyproject.toml`:

```
[project.optional-dependencies]
test = [
    "pytest>=8.0",
    "pytest-cov>=5.0",
    "pytest-asyncio>=0.24",
    "httpx>=0.27",       # FastAPI TestClient
    "respx>=0.21",       # HTTP mock (for external API calls if any)
    "sqlalchemy>=2.0",   # already a dep, needed for test fixtures
]

[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = ["test_*.py"]
asyncio_mode = "auto"
```

### 3.2 Directory structure

```
tests/
├── conftest.py              # shared fixtures (db session, chroma mock, kafka mock)
├── test_api_catalog.py      # endpoints: GET /api/products, /api/categories, /api/quote, POST /api/upload
├── test_api_rag.py          # endpoints: POST /chat, GET /health
├── test_api_upload.py       # upload parsing, validation, Kafka producer interaction
├── test_db_repository.py    # CRUD, filtering, dedup, aggregation queries
├── test_db_migrations.py    # table creation is idempotent
├── test_chroma_upsert.py    # _build_document_text, upsert_product, delete_product, upsert_aggregate_document
├── test_kafka_producer.py   # config, publish_record, publish_batch, close
├── test_kafka_consumer.py   # _process_message, _send_to_dlq, routing by target
├── test_integration_agent.py # _write_to_postgres, _upsert_chromadb, integrate()
├── test_ingestion_agent.py  # parse_file (csv/json/jsonl), tag_records, move_to_processed
├── test_transformation_agent.py  # _match_field, transform (all 5 targets)
├── test_quality_agent.py    # validate (required fields, types, ranges)
├── test_aggregator.py       # _build_top_categories_doc, _build_summary_doc, run()
└── test_rag_smoke.py        # new assertion-based version of existing smoke test
```

### 3.3 Test layers

#### Unit tests (fast, no I/O)

Test pure functions in isolation. Mock/skip all external services (DB, Kafka, ChromaDB, embedding model).

| Module | What to test | Mock strategy |
|---|---|---|
| `chroma_upsert._build_document_text` | Document string formatting for various product dict shapes | No mocks needed — pure function |
| `transformation_agent._match_field` | Case-insensitive matching, whitespace/underscore normalization | Pure function |
| `transformation_agent.transform` | All 5 targets, field aliasing, defaults, transformers | Pure function (no I/O in transform) |
| `quality_agent.validate` | Required fields missing, type errors, negative quantities, short names | Pure function |
| `db.models` | ORM model construction | In-memory SQLite |
| `kafka_producer.create_producer` | Config dict construction with/without SASL | Pure function (don't create actual producer) |
| `ingestion_agent._parse_csv`, `_parse_json`, `_parse_jsonl` | Various file formats, edge cases (empty, BOM, whitespace) | Pure function |

#### Repository tests (SQLite)

Test `db/repository.py` against an in-memory SQLite database. No PostgreSQL needed.

| Function | What to test |
|---|---|
| `upsert_product` | Insert new, update existing (same name), verify ORM mapping |
| `get_products` | Filter by category, search (ilike), in_stock_only, dedup by name, ordering |
| `get_categories` | Aggregation: count, sum stock, avg price |
| `get_product_by_name` | Case-insensitive lookup, return None for missing |
| `get_shipping_cost` | Filter by product_name ilike, empty results |
| `get_aggregated_top_categories` | Report period filtering, ordering by total_sold |

#### API tests (httpx TestClient + SQLite)

Test FastAPI endpoints with `TestClient` and in-memory SQLite. Mock ChromaDB with a fake.

| Endpoint | What to test |
|---|---|
| `GET /api/health` | Returns ok |
| `GET /api/products` | Pagination, category filter, search, in_stock_only, empty DB |
| `GET /api/categories` | Returns aggregation data, empty DB |
| `GET /api/products/{name}` | Found, not found (404) |
| `POST /api/quote` | Valid request, missing products, out-of-stock, partial match |
| `POST /api/upload` | CSV upload, JSON upload, invalid target, unsupported file type, empty file |
| `POST /chat` | Valid query, empty query (400), uninitialized (503) |
| `GET /health` (RAG) | Returns doc count and model name |

#### Consumer unit tests

Test `_process_message`, `_send_to_dlq`, routing logic.
Mock `transformation_agent.transform`, `quality_agent.quality_report`, `integrate`.

| Scenario | Expected behavior |
|---|---|
| Unknown target | Sent to DLQ, returns True |
| Transform raises exception | Sent to DLQ, returns True |
| Transform returns empty | Sent to DLQ, returns True |
| Quality fails | Sent to DLQ with error detail |
| Integration succeeds | Returns True, message committed |
| Integration raises | Returns False (retry) |

#### Agent integration tests (real ChromaDB + SQLite)

Test `integration_agent.integrate` with actual ChromaDB (temp directory) and SQLite.

| Scenario | What to verify |
|---|---|
| inventory target | Write to products table + upsert to ChromaDB |
| shipping_order target | Write to shipping_orders table, no ChromaDB upsert |
| No DATABASE_URL | Skip PG, may still do ChromaDB |
| No chroma_path | Skip ChromaDB, still write PG |

#### Aggregator tests

Test `_build_top_categories_doc` and `_build_summary_doc` with seeded SQLite data.

| Scenario | Expected |
|---|---|
| No data returns None | Graceful skip |
| Normal data | Correct text formatting, metadata |
| `run()` without env vars | Early return, no crash |

### 3.4 Conftest fixtures

```python
# tests/conftest.py

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from backend.db.models import Base

@pytest.fixture
def db_session():
    """In-memory SQLite session for repository tests."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture
def chroma_dir(tmp_path):
    """Temporary directory for ChromaDB persistent client."""
    return tmp_path / "chroma_test"


@pytest.fixture(autouse=True)
def mock_sentence_transformer(monkeypatch):
    """Replace real embedding model with a zero-vector stub."""
    import numpy as np

    class FakeModel:
        def encode(self, texts, **kwargs):
            n = len(texts) if isinstance(texts, list) else 1
            return np.zeros((n, 384), dtype=np.float32)

    monkeypatch.setattr(
        "sentence_transformers.SentenceTransformer",
        lambda *a, **kw: FakeModel(),
    )


@pytest.fixture
def mock_kafka_producer(monkeypatch):
    """Prevent real Kafka connections in tests."""
    class FakeProducer:
        def __init__(self, **kwargs):
            self.sent = []
        def send(self, topic, key=None, value=None):
            self.sent.append((topic, key, value))
        def flush(self):
            pass
        def close(self):
            pass

    monkeypatch.setattr("kafka.KafkaProducer", FakeProducer)
    monkeypatch.setattr("kafka.KafkaConsumer", lambda *a, **kw: MockConsumer())
    return FakeProducer
```

### 3.5 CI integration

Add a `test` job to `.github/workflows/build-deploy.yml` that runs before the build:

```yaml
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -e ".[test]"
      - run: pytest --cov=backend --cov-fail-under=70 --cov-report=term-missing

  build-and-push:
    needs: [test]
    # ... existing steps
```

Coverage threshold: 70% minimum. If CI has no secrets for Docker push (PR from fork), the `test` job still runs independently.

### 3.6 Frontend testing (future)

The React chatbot has zero tests. A follow-up should add:

```
cd frontend/chatbot
npm install -D vitest @testing-library/react @testing-library/jest-dom jsdom
```

Coverage for:
- `ChatBot.jsx` — renders, sends query, displays results
- `App.jsx` — renders without crash

Not included in this spec's scope — flag as open question.

## 4. Key Decisions

1. **SQLite over testcontainers for DB tests**: Setting up PostgreSQL via testcontainers adds Docker dependency, slows tests, and is overkill for repository logic. SQLite covers the ORM layer and query logic. A separate integration test suite can target a real PG if needed.

2. **Fake embedding model over real sentence-transformers**: The model is 80MB+ and takes ~2s to load. Tests skip it entirely with a zero-vector stub. This preserves `chroma_upsert` logic (collection ops, embedding shape) without the download overhead.

3. **No live Kafka in CI**: Consumer logic is tested by injecting mock producers/consumers. An integration smoke test with a real Kafka broker is a future item.

4. **Single conftest.py**: Keep all shared fixtures in one file rather than per-directory conftest files. The test suite is small enough that a single file is clearer.

5. **pytest-cov with 70% floor**: 70% is achievable (all pure functions + API routes + repository) without requiring integration-heavy modules to be fully covered. Raise to 80% once ChromaDB and Kafka integration tests land.

## 5. Open Questions

1. **Should the existing `tests/test_rag.py` be replaced or kept?** It's a manual smoke test against real ChromaDB. Should we migrate it to a pytest benchmark test, or just delete it?

2. **Frontend testing scope**: Should the initial spec include Vitest setup for the React chatbot, or leave it for a separate PR?

3. **Prefect flow tests**: `orchestrator.py` and `pipeline.py` define Prefect flows. Testing these requires running Prefect in test mode. Worth adding `prefect.testing` utilities, but it adds complexity.

4. **End-to-end tests**: Should we add a `docker-compose.yml` or `kind`-based E2E suite that spins up PG + ChromaDB + Kafka + the app and runs a full ingestion → query scenario? This would catch integration bugs but adds significant CI cost.

5. **Test data files**: Should CSV/JSON fixtures live under `tests/fixtures/` or reuse existing `data/csv/` files?

## 6. Implementation Plan

### Phase 1 — Foundation (1 session)

1. Add `[project.optional-dependencies] test = [...]` to `pyproject.toml`
2. Add `[tool.pytest.ini_options]` to `pyproject.toml`
3. Create `tests/conftest.py` — db_session, chroma_dir, mock_sentence_transformer, mock_kafka_producer
4. Create `tests/test_db_repository.py` — all CRUD + aggregation tests
5. Create `tests/test_db_migrations.py` — idempotency test
6. Run `pytest` — verify all pass

### Phase 2 — Pure-function tests (1 session)

7. `tests/test_transformation_agent.py` — _match_field + transform (all 5 targets)
8. `tests/test_quality_agent.py` — validate + quality_report
9. `tests/test_chroma_upsert.py` — _build_document_text (pure function only; collection tests use mock with chroma_dir)
10. `tests/test_kafka_producer.py` — config dict construction
11. `tests/test_ingestion_agent.py` — parse_file formats + tag_records

### Phase 3 — API tests (1 session)

12. `tests/test_api_catalog.py` — all endpoints with SQLite-backed TestClient
13. `tests/test_api_upload.py` — upload with mock Kafka
14. `tests/test_api_rag.py` — chat + health with mock ChromaDB

### Phase 4 — Integration/consumer tests (1-2 sessions)

15. `tests/test_integration_agent.py` — PG write + ChromaDB upsert via sqlite + chroma_dir
16. `tests/test_kafka_consumer.py` — _process_message routing, DLQ, retry
17. `tests/test_aggregator.py` — doc building with seeded data
18. `tests/test_rag_smoke.py` — assertion-based replacement for old smoke test

### Phase 5 — CI (1 session)

19. Add `test` job to `.github/workflows/build-deploy.yml` with `needs: [test]` on build
20. Verify CI passes on a PR

### Verification criteria

- `pytest` passes with 0 failures
- `pytest --cov=backend --cov-fail-under=70` passes
- CI test job runs before build-and-push
- Existing `tests/test_rag.py` either deleted or migrated
