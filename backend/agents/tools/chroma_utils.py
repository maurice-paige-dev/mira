from pathlib import Path

from sentence_transformers import SentenceTransformer
import chromadb
from chromadb.config import Settings

BASE = Path(__file__).resolve().parent.parent.parent.parent
DB_DIR = BASE / "data" / "chroma_shipping_db"

_model = None
_collection = None


def _ensure_loaded():
    global _model, _collection
    if _model is not None and _collection is not None:
        return
    if not DB_DIR.exists():
        raise RuntimeError(f"ChromaDB not found at {DB_DIR}")
    _model = SentenceTransformer("all-MiniLM-L6-v2")
    client = chromadb.PersistentClient(
        path=str(DB_DIR),
        settings=Settings(anonymized_telemetry=False),
    )
    _collection = client.get_collection("shipping_advisor")


def query_chromadb(query: str, n_results: int = 5) -> list[dict]:
    _ensure_loaded()
    q_emb = _model.encode([query]).tolist()
    results = _collection.query(
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
