## Process

- **Specs before code**: Every change must start with a written spec. No implementation without an approved design document.
- Specs live in a directory matching the change scope: `specs/` for pipeline/agent changes, `k8s/` for Kubernetes/infrastructure changes.
- A spec must cover: motivation, proposed approach, key decisions, open questions, implementation plan.
- **KPIs before spec**: Every spec must include a "KPIs Affected" section referencing the relevant subdirectory `KPIs.md` (see `docs/KPIs.md` for the full index). When KPIs change, the per-area `KPIs.md` must be updated.
- Once the spec is written and confirmed, implementation begins.
- After implementation, update `README.md` architecture diagram and docs table.
- After implementation, verify the per-area `KPIs.md` spec assessment checklist was completed.

## Code conventions

- Python: 4-space indent, type annotations on all public functions.
- Keep functions small and composable.
- No comments unless explaining *why*, not *what*.
- All errors propagate via exceptions; no silent swallows.
- Agents use LangGraph with `@tool` decorators for tool interfaces.
- New features require tests in `tests/` (pytest, coverage >= 70%).

## Running

```bash
# Full test suite
pytest

# Catalog API (port 8001)
uvicorn backend.api_catalog:app --reload

# Chatbot API (port 8000)
uvicorn backend.api_rag:app --reload

# Agentic chat requires Ollama running locally:
#   ollama pull llama3.1
#   OLLAMA_BASE_URL=http://localhost:11434

# Prefect server (persistent orchestration + UI):
prefect server start

# Kafka consumer (requires Kafka + PostgreSQL):
python -m backend.kafka_consumer
```
