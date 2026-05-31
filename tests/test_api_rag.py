from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient


class FakeCollection:
    def __init__(self):
        self._count = 3

    def count(self):
        return self._count

    def query(self, query_embeddings, n_results=5, include=None):
        n = min(n_results, self._count)
        return {
            "ids": [[f"doc_{i}" for i in range(n)]],
            "documents": [[f"Document {i} content" for i in range(n)]],
            "metadatas": [[{
                "product_name": f"Product {i}",
                "source": "inventory",
                "total_price": 10.0 * (i + 1),
            } for i in range(n)]],
            "distances": [[0.1 * (i + 1) for i in range(n)]],
        }


@pytest.fixture(autouse=True)
def mock_chromadb_lifespan(monkeypatch, tmp_path):
    chroma_dir = tmp_path / "chroma"
    chroma_dir.mkdir()
    monkeypatch.setattr("backend.api_rag.DB_DIR", chroma_dir)

    fake_client = FakeChromaClient()

    class FakePersistentClient:
        def __init__(self, path, settings=None):
            pass

        def get_collection(self, name):
            return fake_client.collection

    monkeypatch.setattr("chromadb.PersistentClient", FakePersistentClient)


class FakeChromaClient:
    def __init__(self):
        self.collection = FakeCollection()


class TestChat:
    def test_valid_query(self):
        with TestClient(_app()) as client:
            resp = client.post("/chat", json={"query": "shipping costs"})
        assert resp.status_code == 200
        data = resp.json()
        assert "answer" in data
        assert len(data["results"]) > 0
        assert data["total_docs"] == 3

    def test_empty_query(self):
        with TestClient(_app()) as client:
            resp = client.post("/chat", json={"query": ""})
        assert resp.status_code == 400

    def test_blank_query(self):
        with TestClient(_app()) as client:
            resp = client.post("/chat", json={"query": "   "})
        assert resp.status_code == 400

    def test_not_initialized(self):
        from backend.api_rag import chat, collection, model
        old_col = collection
        old_mod = model
        import backend.api_rag as rag
        rag.collection = None
        rag.model = None
        from fastapi import HTTPException
        import pytest
        with pytest.raises(HTTPException) as exc:
            chat({"query": "test"})
        assert exc.value.status_code == 503
        rag.collection = old_col
        rag.model = old_mod


class TestHealth:
    def test_health(self):
        with TestClient(_app()) as client:
            resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["chroma_docs"] == 3

    def test_health_not_initialized(self):
        from backend.api_rag import health, collection, model
        import backend.api_rag as rag
        old_col = rag.collection
        old_mod = rag.model
        rag.collection = None
        rag.model = None
        from fastapi import HTTPException
        import pytest
        with pytest.raises(HTTPException) as exc:
            health()
        assert exc.value.status_code == 503
        rag.collection = old_col
        rag.model = old_mod


class TestQueryShipping:
    def test_query_shipping_returns_results(self):
        from backend.api_rag import query_shipping
        col = FakeCollection()
        mdl = _fake_model()
        results = query_shipping(col, mdl, "test query", n_results=2)
        assert len(results) == 2
        assert all("text" in r for r in results)
        assert all("metadata" in r for r in results)
        assert all("similarity" in r for r in results)

    def test_query_shipping_empty_collection(self):
        from backend.api_rag import query_shipping

        class EmptyCollection:
            def count(self):
                return 0
            def query(self, **kw):
                return {"ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]]}

        results = query_shipping(EmptyCollection(), _fake_model(), "test")
        assert results == []


class TestBuildAnswer:
    def test_build_answer_with_results(self):
        from backend.api_rag import build_answer
        results = [
            {"text": "Chai tea product", "metadata": {"product_name": "Chai", "total_price": "25.0", "source": "inventory"}, "similarity": 0.95},
        ]
        answer = build_answer("shipping costs", results)
        assert "Chai" in answer
        assert "shipping costs" in answer

    def test_build_answer_empty(self):
        from backend.api_rag import build_answer
        answer = build_answer("test", [])
        assert "couldn't find" in answer.lower()


def _app():
    import backend.api_rag as rag
    return rag.app


def _fake_model():
    class FakeModel:
        def encode(self, texts, **kwargs):
            n = len(texts) if isinstance(texts, list) else 1
            return np.zeros((n, 384), dtype=np.float32)
    return FakeModel()
