"""
Legacy smoke test — kept for manual verification against a real ChromaDB.
Use test_rag_smoke.py for automated CI testing.
"""

if __name__ == "__main__":
    from backend.chroma_upsert import get_model, get_collection, upsert_product
    from backend.chroma_upsert import _build_document_text
    from pathlib import Path

    CHROMA_DIR = Path(__file__).resolve().parent.parent / "data" / "chroma_shipping_db"
    if not CHROMA_DIR.exists():
        print("ChromaDB not found. Skipping smoke test.")
        exit(0)

    model = get_model()
    collection = get_collection(str(CHROMA_DIR))

    count = collection.count()
    print(f"Collection has {count} documents")

    queries = [
        "show me tea products and their pricing",
        "what is the most expensive product in stock",
        "latest purchase orders",
        "how is the shipping cost calculated for orders to the USA",
        "identify slow-moving inventory items",
        "what are the top selling categories",
        "who is our primary shipper and what are the costs",
        "show me all products with low stock levels",
        "what is the total value of our current inventory",
        "which products are out of stock",
    ]

    for q in queries:
        print(f"\nQuery: {q}")
        results = collection.query(
            query_embeddings=model.encode([q]).tolist(),
            n_results=3,
            include=["documents", "metadatas", "distances"],
        )
        for i, (doc, meta, dist) in enumerate(
            zip(results["documents"][0], results["metadatas"][0], results["distances"][0])
        ):
            print(f"  [{1 - dist:.3f}] {doc[:120]}...")
