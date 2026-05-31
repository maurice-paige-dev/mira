# Test Suite — KPIs

> Covers all files in `tests/`. Tests are the safety net for every code change. When new specs add code, tests must follow.

## 1. Coverage

| KPI | Definition | Source | Target |
|---|---|---|---|
| Overall Line Coverage | `pytest --cov=backend` line coverage | CI (`build-deploy.yml`) | ≥ 70% |
| Per-Package Coverage | Coverage by module (backend.agents, backend.db, etc.) | CI step (XML parse) | each ≥ 60% |
| Coverage Trend | 30-day change in coverage | CI history | Monotonic or flat |

**Degradation signals:** Coverage drops below 70% fail CI. Per-package drops below 60% flag risky areas.

## 2. Test Health

| KPI | Definition | Source | Target |
|---|---|---|---|
| Test Pass Rate | Passing / total tests | `pytest` exit code | 100% |
| Test Count | Total test functions | `pytest --collect-only` | Monotonic增长 |
| Test Execution Time | Total CI test time | GitHub Actions | < 5 minutes |
| Flaky Test Rate | Tests that pass intermittently | Manual / CI retry | 0% |
| Skipped Tests | Tests explicitly skipped | `pytest -v` output | 0 |

## 3. Coverage by Module

| Module | Test File | Current Coverage (goal) | Critical Path |
|---|---|---|---|
| `backend/agents/` | `test_ingestion_agent.py`, `test_transformation_agent.py`, `test_quality_agent.py`, `test_integration_agent.py` | ≥ 70% | Pipeline data integrity |
| `backend/db/` | `test_db_repository.py`, `test_db_migrations.py` | ≥ 70% | All data persistence |
| `backend/api_catalog.py` | `test_api_catalog.py` | ≥ 70% | Customer-facing API |
| `backend/api_rag.py` | `test_api_rag.py`, `test_rag_smoke.py` | ≥ 70% | Customer-facing API |
| `backend/api_upload.py` | `test_api_upload.py` | ≥ 70% | Data ingestion entry point |
| `backend/kafka_consumer.py` | `test_kafka_consumer.py` | ≥ 70% | Streaming pipeline |
| `backend/kafka_producer.py` | `test_kafka_producer.py` | ≥ 70% | Streaming pipeline |
| `backend/aggregator.py` | (in test_integration_agent.py) | ≥ 60% | RAG freshness |

## 4. Test Types

| Type | Definition | Target |
|---|---|---|
| Unit Tests | Test single function/class in isolation | ≥ 70% of all tests |
| Integration Tests | Test across module boundaries (e.g., agent → DB) | ≥ 20% of all tests |
| Smoke Tests | Test critical end-to-end paths | ≥ 1 per API |
| Regression Tests | Tests for past bugs | Added with every bug fix |

## Spec Assessment Checklist

When a spec proposes code changes:

- [ ] Are new test files created in `tests/` or existing files extended?
- [ ] Are there unit tests for each new function?
- [ ] Are there integration tests for multi-step operations (agent → DB → ChromaDB)?
- [ ] Are mock objects used to avoid external dependencies (Kafka, ChromaDB, PostgreSQL)?
- [ ] Do tests run in CI via `pytest --cov=backend --cov-fail-under=70`?
- [ ] Are conftest.py fixtures reused where appropriate?
- [ ] Is coverage > 70% for the new code?
