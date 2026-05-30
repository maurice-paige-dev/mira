import sys
from pathlib import Path
from typing import Optional
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from sentence_transformers import SentenceTransformer
import chromadb
from chromadb.config import Settings

BASE = Path(__file__).resolve().parent.parent
DB_DIR = BASE / "data" / "chroma_shipping_db"

model: Optional[SentenceTransformer] = None
collection: Optional[chromadb.Collection] = None


@asynccontextmanager
async def lifespan(application: FastAPI):
    global model, collection
    if not DB_DIR.exists():
        print("[FATAL] ChromaDB not found. Run `python -m backend.vector_store --no-interactive` first.")
        sys.exit(1)

    print("Loading embedding model\u2026")
    model = SentenceTransformer("all-MiniLM-L6-v2")

    print("Opening ChromaDB\u2026")
    client = chromadb.PersistentClient(
        path=str(DB_DIR),
        settings=Settings(anonymized_telemetry=False),
    )
    collection = client.get_collection("shipping_advisor")
    count = collection.count()
    print(f"Collection 'shipping_advisor' ready \u2013 {count} documents")

    yield
    print("Shutting down\u2026")


app = FastAPI(
    title="Shipping Cost Advisor API",
    description="RAG-based chatbot for inventory, purchases, and shipping orders",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    query: str
    n_results: int = 5


class ChatResponse(BaseModel):
    answer: str
    results: list[dict]
    total_docs: int


class HealthResponse(BaseModel):
    status: str
    chroma_docs: int
    model_name: str


def query_shipping(collection, model, query: str, n_results: int = 5) -> list[dict]:
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


def build_answer(query: str, results: list[dict]) -> str:
    if not results:
        return "I couldn't find any relevant information to answer your question. Please try rephrasing it."

    lines = []
    lines.append(f"Based on your question about \"{query}\", here's what I found:\n")

    mentioned_products = set()
    mentioned_shippers = set()
    mentioned_vendors = set()
    mentioned_customers = set()

    for r in results:
        meta = r["metadata"]
        text = r["text"]
        source = meta.get("source", "")
        product = meta.get("product_name", "")
        shipper = meta.get("shipper", "")
        vendor = meta.get("vendor_name", "")
        customer = meta.get("customer", "")
        total_price = meta.get("total_price", "")
        avg_total = meta.get("avg_total", "")

        parts = []
        if product and product not in mentioned_products:
            parts.append(f"Product: {product}")
            mentioned_products.add(product)
        if shipper and shipper not in mentioned_shippers:
            parts.append(f"Shipper: {shipper}")
            mentioned_shippers.add(shipper)
        if vendor and vendor not in mentioned_vendors:
            parts.append(f"Vendor: {vendor}")
            mentioned_vendors.add(vendor)
        if customer and customer not in mentioned_customers:
            parts.append(f"Customer: {customer}")
            mentioned_customers.add(customer)

        price_info = ""
        if total_price:
            price_info = f" [Total: ${total_price}]"
        elif avg_total:
            price_info = f" [Avg: ${avg_total}]"

        prefix = "  \u2022 "
        if parts:
            prefix += f"({' | '.join(parts)}) "

        display_text = text[:300]
        lines.append(f"{prefix}{display_text}{price_info}")

    lines.append(
        "\n\u2728 Tip: You can ask follow-up questions like "
        "\"What's the average cost?\", "
        "\"Which vendor supplies this?\", or "
        "\"Show me details for a specific order.\""
    )

    return "\n".join(lines)


@app.get("/health", response_model=HealthResponse)
def health():
    if collection is None or model is None:
        raise HTTPException(status_code=503, detail="Not initialized")
    return HealthResponse(
        status="ok",
        chroma_docs=collection.count(),
        model_name=model.__class__.__name__,
    )


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    global collection, model
    if collection is None or model is None:
        raise HTTPException(status_code=503, detail="System not initialized")

    if not req.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty")

    n = min(max(req.n_results, 1), 20)

    results = query_shipping(collection, model, req.query, n_results=n)
    answer = build_answer(req.query, results)
    total = collection.count()

    serializable_results = []
    for r in results:
        meta = {}
        for k, v in r["metadata"].items():
            if isinstance(v, (int, float, str, bool)):
                meta[k] = v
            elif v is None:
                meta[k] = None
            else:
                meta[k] = str(v)
        serializable_results.append({
            "text": r["text"],
            "metadata": meta,
            "similarity": r["similarity"],
        })

    return ChatResponse(
        answer=answer,
        results=serializable_results,
        total_docs=total,
    )


if __name__ == "__main__":
    uvicorn.run(
        "backend.api_rag:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
    )
