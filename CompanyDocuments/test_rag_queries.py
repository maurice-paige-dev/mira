#!/usr/bin/env python3
"""
Non-interactive test queries for the Shipping Cost Advisor RAG system.
Uses the already-built ChromaDB vector store.
"""

import sys
from pathlib import Path

from sentence_transformers import SentenceTransformer
import chromadb
from chromadb.config import Settings

BASE_DIR = Path(__file__).parent


def query_shipping(collection, model, query: str, n_results: int = 5) -> list[dict]:
    """Embed the query and retrieve most relevant documents."""
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
            "similarity": 1.0 - dist,
        })
    return out


def main():
    print("=" * 60)
    print("  RAG Shipping Cost Advisor – Test Queries")
    print("=" * 60)

    db_path = BASE_DIR / "chroma_shipping_db"
    if not db_path.exists():
        print("[ERROR] ChromaDB not found. Run rag_shipping_advisor.py first.")
        sys.exit(1)

    # Load model & collection
    print("\n  Loading embedding model …")
    model = SentenceTransformer("all-MiniLM-L6-v2")

    print("  Opening ChromaDB …")
    client = chromadb.PersistentClient(
        path=str(db_path),
        settings=Settings(anonymized_telemetry=False),
    )
    collection = client.get_collection("shipping_advisor")
    count = collection.count()
    print(f"  Collection 'shipping_advisor' has {count} documents")

    # ── Test queries ──
    test_queries = [
        # Original queries
        "What is the average shipping cost for Queso Cabrales?",
        "Which shipper is cheapest for shipping?",
        "Shipping costs for orders shipped to France",
        "What is the most expensive product to ship?",
        "Compare shipping costs between Federal Shipping and Speedy Express",
        "How much does it cost to ship Tofu?",
        # Vendor / third-party warehouse queries
        "Which third-party vendors supply Queso Cabrales?",
        "What products does third-party vendor Paul Henriot supply?",
        "How does vendor warehouse proximity affect shipping costs?",
        "Which countries does vendor Mario Pontes ship to?",
        "What is the vendor warehouse reach for Karin Josephs?",
        "How many third-party vendors does the company work with?",
    ]

    for q in test_queries:
        print(f"\n{'─' * 60}")
        print(f"  ❓ Query: {q}")
        print(f"{'─' * 60}")

        results = query_shipping(collection, model, q, n_results=3)
        for i, r in enumerate(results, 1):
            meta = r["metadata"]
            sim = r["similarity"]
            source = meta.get("source", "?")
            product = meta.get("product_name", "")
            shipper = meta.get("shipper", "")
            total = meta.get("total_price", "")
            avg_total = meta.get("avg_total", "")
            vendor = meta.get("vendor_name", "")
            data_type = meta.get("data_type", "")

            print(f"\n  [{i}] sim={sim:.3f} | source={source}")
            if product:
                print(f"      Product : {product}")
            if shipper:
                print(f"      Shipper : {shipper}")
            if vendor:
                print(f"      Vendor  : {vendor}")
            if total:
                print(f"      Total   : ${total}")
            if avg_total:
                print(f"      Avg     : ${avg_total}")
            if data_type:
                print(f"      Type    : {data_type}")
            # Show first 250 chars of text
            text_preview = r["text"][:250]
            print(f"      {text_preview}")

    print(f"\n{'=' * 60}")
    print("  All test queries completed.")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()