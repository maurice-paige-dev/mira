"""
Smoke test for the RAG pipeline — validates the core query → answer flow
using a real (or mocked) ChromaDB and embedding model.

Replaces the old manual `tests/test_rag.py` script with proper assertions.
"""

import numpy as np
import pytest

from backend.chroma_upsert import get_model, get_collection, upsert_product


class TestRagSmoke:
    def test_embedding_and_query_flow(self, chroma_dir):
        model = get_model()
        collection = get_collection(chroma_dir)

        product = {
            "product_name": "Chai",
            "category": "Beverages",
            "unit_price": 18.0,
            "units_in_stock": 39,
        }
        upsert_product(product, model, collection)
        assert collection.count() == 1

        results = collection.query(
            query_embeddings=model.encode(["tea"]).tolist(),
            n_results=5,
            include=["documents", "metadatas", "distances"],
        )
        assert len(results["ids"][0]) == 1
        assert results["ids"][0][0] == "product_Chai"

    def test_empty_collection(self, chroma_dir):
        model = get_model()
        collection = get_collection(chroma_dir)
        assert collection.count() == 0

    def test_multiple_products_queried(self, chroma_dir):
        model = get_model()
        collection = get_collection(chroma_dir)

        for name, cat in [("Chai", "Beverages"), ("Tofu", "Produce"), ("Tea", "Beverages")]:
            upsert_product(
                {"product_name": name, "category": cat, "unit_price": 10.0},
                model,
                collection,
            )

        assert collection.count() == 3

        results = collection.query(
            query_embeddings=model.encode(["beverage"]).tolist(),
            n_results=5,
            include=["metadatas"],
        )
        ids = results["ids"][0]
        metas = results["metadatas"][0]
        beverage_results = [
            i for i, m in enumerate(metas)
            if m.get("category") == "Beverages"
        ]
        assert len(beverage_results) >= 2
