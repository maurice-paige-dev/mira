import numpy as np
import pytest

from backend.chroma_upsert import (
    _build_document_text,
    get_model,
    get_collection,
    upsert_product,
    delete_product,
    upsert_aggregate_document,
)


class TestBuildDocumentText:
    def test_minimal_product(self):
        text = _build_document_text({"product_name": "Chai"})
        assert "Product Name: Chai." in text
        assert "Category: General." in text

    def test_full_product(self):
        text = _build_document_text({
            "product_name": "Chai",
            "category": "Beverages",
            "unit_price": 18.0,
            "units_in_stock": 39,
            "units_sold": 120,
            "report_period": "2025-01",
        })
        assert "Product Name: Chai." in text
        assert "Category: Beverages." in text
        assert "Price: $18.00." in text
        assert "Units in Stock: 39." in text
        assert "Units Sold: 120." in text
        assert "Report Period: 2025-01." in text

    def test_zero_values_omitted(self):
        text = _build_document_text({
            "product_name": "Tofu",
            "category": "Produce",
            "unit_price": 0,
            "units_in_stock": 0,
            "units_sold": 0,
        })
        assert "Price" not in text
        assert "Units in Stock" not in text
        assert "Units Sold" not in text

    def test_alt_keys(self):
        text = _build_document_text({"name": "Chai", "price": 18.0, "stock": 39})
        assert "Product Name: Chai." in text
        assert "Price: $18.00." in text
        assert "Units in Stock: 39." in text


class TestCollection:
    def test_get_collection_creates(self, chroma_dir):
        col = get_collection(chroma_dir, "test_collection")
        assert col.name == "test_collection"
        assert col.count() == 0

    def test_get_collection_reuses(self, chroma_dir):
        col1 = get_collection(chroma_dir, "reuse")
        col2 = get_collection(chroma_dir, "reuse")
        assert col1.name == col2.name


class TestGetModel:
    def test_get_model(self):
        model = get_model()
        emb = model.encode(["test text"])
        assert isinstance(emb, np.ndarray)
        assert emb.shape == (1, 384)


class TestUpsertProduct:
    def test_upsert_and_query(self, chroma_dir):
        model = get_model()
        col = get_collection(chroma_dir)

        product = {
            "product_name": "Chai",
            "category": "Beverages",
            "unit_price": 18.0,
            "units_in_stock": 39,
        }
        doc_id = upsert_product(product, model, col)
        assert doc_id == "product_Chai"

        results = col.query(
            query_embeddings=model.encode(["tea"]).tolist(),
            n_results=1,
        )
        assert len(results["ids"][0]) == 1
        assert results["ids"][0][0] == "product_Chai"

    def test_upsert_overwrites(self, chroma_dir):
        model = get_model()
        col = get_collection(chroma_dir)

        upsert_product({"product_name": "Chai", "category": "Beverages", "unit_price": 18.0}, model, col)
        upsert_product({"product_name": "Chai", "category": "Beverages", "unit_price": 20.0}, model, col)

        assert col.count() == 1


class TestDeleteProduct:
    def test_delete_existing(self, chroma_dir):
        model = get_model()
        col = get_collection(chroma_dir)

        upsert_product({"product_name": "Chai"}, model, col)
        delete_product("Chai", col)
        assert col.count() == 0

    def test_delete_nonexistent(self, chroma_dir):
        model = get_model()
        col = get_collection(chroma_dir)

        delete_product("Nonexistent", col)


class TestUpsertAggregate:
    def test_upsert_aggregate_document(self, chroma_dir):
        model = get_model()
        col = get_collection(chroma_dir)

        upsert_aggregate_document(
            doc_id="agg_top_categories",
            text="Top categories summary",
            metadata={"type": "aggregate", "aggregate": "top_categories"},
            model=model,
            collection=col,
        )
        assert col.count() == 1

        results = col.query(
            query_embeddings=model.encode(["test"]).tolist(),
            n_results=1,
        )
        assert results["ids"][0][0] == "agg_top_categories"
        assert results["metadatas"][0][0]["aggregate"] == "top_categories"
