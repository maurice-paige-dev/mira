import sys
import time
import json
import asyncio
import threading
from pathlib import Path
from typing import Optional
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, HTTPException, Request, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from sentence_transformers import SentenceTransformer
import chromadb
from chromadb.config import Settings

from langchain_core.messages import HumanMessage, AIMessage

from backend.telemetry import get_logger
from backend.metrics import metrics_endpoint, HTTP_REQUEST_COUNT, HTTP_REQUEST_DURATION
from backend.session_store import get_store
from backend.agents.graph import build_graph
from backend.config import OLLAMA_BASE_URL

log = get_logger("rag")

BASE = Path(__file__).resolve().parent.parent
DB_DIR = BASE / "data" / "chroma_shipping_db"

model: Optional[SentenceTransformer] = None
collection: Optional[chromadb.Collection] = None
_store = get_store()
_graph = None


@asynccontextmanager
async def lifespan(application: FastAPI):
    global model, collection, _graph
    if not DB_DIR.exists():
        log.critical("chromadb_not_found", detail="Run `python -m backend.vector_store --no-interactive` first.")
        sys.exit(1)

    log.info("loading_embedding_model")
    model = SentenceTransformer("all-MiniLM-L6-v2")

    log.info("opening_chromadb")
    client = chromadb.PersistentClient(
        path=str(DB_DIR),
        settings=Settings(anonymized_telemetry=False),
    )
    collection = client.get_collection("shipping_advisor")
    count = collection.count()
    log.info("collection_ready", collection="shipping_advisor", documents=count)

    try:
        _graph = build_graph()
        log.info("langgraph_graph_ready")
    except Exception as e:
        log.warning("langgraph_not_available", error=str(e))
        _graph = None

    yield
    log.info("shutting_down")


app = FastAPI(
    title="Shipping Cost Advisor API",
    description="RAG chatbot with LangGraph multi-agent system",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def metrics_and_logging(request: Request, call_next):
    method = request.method
    path = request.url.path
    start = time.monotonic()
    response = await call_next(request)
    elapsed = time.monotonic() - start
    HTTP_REQUEST_COUNT.labels(method=method, path=path, status=response.status_code).inc()
    HTTP_REQUEST_DURATION.labels(method=method, path=path).observe(elapsed)
    log.info("request", method=method, path=path, status=response.status_code, elapsed_ms=round(elapsed * 1000))
    return response


app.add_route("/metrics", metrics_endpoint)


def query_chromadb(query: str, n_results: int = 5) -> list[dict]:
    q_emb = model.encode([query]).tolist()
    results = collection.query(
        query_embeddings=q_emb,
        n_results=n_results,
        include=["documents", "metadatas", "distances"],
    )
    out = []
    for doc, meta, dist in zip(
        results["documents"][0],
        results["metadatas"][0],
        results["distances"][0],
    ):
        out.append({
            "text": doc,
            "metadata": meta,
            "similarity": round(1.0 - dist, 4),
        })
    return out


def build_fallback_answer(query: str, results: list[dict]) -> str:
    if not results:
        return "I couldn't find any relevant information to answer your question. Please try rephrasing it."
    lines = [f"Based on your question about \"{query}\", here's what I found:\n"]
    for r in results:
        meta = r["metadata"]
        text = r["text"]
        product = meta.get("product_name", "")
        shipper = meta.get("shipper", "")
        prefix = "  \u2022 "
        parts = [p for p in [product, shipper] if p]
        if parts:
            prefix += f"({' | '.join(parts)}) "
        lines.append(f"{prefix}{text[:300]}")
    return "\n".join(lines)


class ChatRequest(BaseModel):
    query: str
    session_id: str | None = None


class ChatResponse(BaseModel):
    session_id: str
    stream_url: str


class HealthResponse(BaseModel):
    status: str
    chroma_docs: int
    model_name: str
    langgraph_available: bool


@app.get("/health", response_model=HealthResponse)
def health():
    if collection is None or model is None:
        raise HTTPException(status_code=503, detail="Not initialized")
    return HealthResponse(
        status="ok",
        chroma_docs=collection.count(),
        model_name=model.__class__.__name__,
        langgraph_available=_graph is not None,
    )


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    global _graph
    if collection is None or model is None:
        raise HTTPException(status_code=503, detail="System not initialized")

    if not req.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty")

    session_id = req.session_id
    if not session_id or _store.get_state(session_id) is None:
        session_id = _store.create_session()

    state = _store.get_state(session_id)
    state["messages"].append(HumanMessage(content=req.query))
    _store.update_state(session_id, state)

    _store.append_event(session_id, {"type": "user_message", "content": req.query})

    def _run_agent():
        try:
            _run_agent_sync(session_id, state)
        except Exception as e:
            _store.append_event(session_id, {"type": "error", "content": str(e)})
            log.error("agent_error", session=session_id, error=str(e))
        finally:
            _store.append_event(session_id, {"type": "done"})

    if _graph is not None:
        thread = threading.Thread(target=_run_agent, daemon=True)
        thread.start()
    else:
        _run_fallback(session_id, req.query)

    return ChatResponse(
        session_id=session_id,
        stream_url=f"/chat/stream/{session_id}",
    )


def _run_agent_sync(session_id: str, state):
    try:
        _store.append_event(session_id, {"type": "agent_start", "agent": "supervisor", "input": state["messages"][-1].content if state["messages"] else ""})
        config = {"configurable": {"thread_id": session_id}}
        for chunk in _graph.stream(state, config, stream_mode="updates"):
            for node_name, update in chunk.items():
                if "messages" in update and update["messages"]:
                    msg = update["messages"][-1]
                    content = msg.content if hasattr(msg, "content") else str(msg)
                    _store.append_event(session_id, {"type": "agent_end", "agent": node_name, "output": content})
                update_session = _store.get_state(session_id)
                if update_session:
                    for k, v in update.items():
                        if k != "messages":
                            update_session[k] = v
                    if "messages" in update:
                        update_session["messages"] = list(update_session["messages"]) + list(update["messages"])
                    _store.update_state(session_id, update_session)
        final_state = _store.get_state(session_id)
        if final_state and final_state["messages"]:
            last = final_state["messages"][-1]
            content = last.content if hasattr(last, "content") else str(last)
            _store.append_event(session_id, {"type": "message", "role": "assistant", "content": content})
    except Exception as e:
        log.error("agent_run_failed", session=session_id, error=str(e))
        _run_fallback(session_id, state["messages"][-1].content if state["messages"] else "")


def _run_fallback(session_id: str, query: str):
    try:
        results = query_chromadb(query, n_results=5)
        answer = build_fallback_answer(query, results)
        state = _store.get_state(session_id)
        if state:
            state["messages"].append(AIMessage(content=answer))
            _store.update_state(session_id, state)
        _store.append_event(session_id, {"type": "message", "role": "assistant", "content": answer})
    except Exception as e:
        _store.append_event(session_id, {"type": "error", "content": str(e)})
    finally:
        _store.append_event(session_id, {"type": "done"})


@app.get("/chat/stream/{session_id}")
async def stream_events(session_id: str):
    state = _store.get_state(session_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Session not found")

    since_index = len(_store.get_events_since(session_id, 0))

    async def event_generator():
        last_index = since_index
        max_wait = 60
        waited = 0
        while waited < max_wait:
            events = _store.get_events_since(session_id, last_index)
            for event in events:
                event_type = event.get("type", "message")
                data = json.dumps(event)
                yield f"event: {event_type}\ndata: {data}\n\n"
                last_index += 1
                if event_type == "done":
                    return
            if last_index < len(_store.get_events_since(session_id, 0)):
                continue
            await asyncio.sleep(0.1)
            waited += 0.1
        yield "event: timeout\ndata: {}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


class HistoryResponse(BaseModel):
    session_id: str
    messages: list[dict]
    context: dict


@app.get("/chat/history/{session_id}", response_model=HistoryResponse)
def chat_history(session_id: str):
    state = _store.get_state(session_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Session not found")

    msgs = []
    for m in state["messages"]:
        role = "user" if isinstance(m, HumanMessage) else "assistant"
        msgs.append({"role": role, "content": m.content})

    ctx = {k: v for k, v in state["session_context"].items() if v is not None}
    return HistoryResponse(session_id=session_id, messages=msgs, context=ctx)


if __name__ == "__main__":
    log.info("starting", port=8000)
    uvicorn.run(
        "backend.api_rag:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
    )
