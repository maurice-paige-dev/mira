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

    class FakePersistentClient:
        def __init__(self, path, settings=None):
            pass

        def get_collection(self, name):
            return FakeCollection()

    monkeypatch.setattr("chromadb.PersistentClient", FakePersistentClient)
    monkeypatch.setattr("backend.api_rag._graph", None)
    monkeypatch.setattr("sentence_transformers.SentenceTransformer", lambda *a, **kw: _fake_model())





class TestChat:
    def test_valid_query(self):
        with TestClient(_app()) as client:
            resp = client.post("/chat", json={"query": "shipping costs"})
        assert resp.status_code == 200
        data = resp.json()
        assert "session_id" in data
        assert "stream_url" in data

    def test_empty_query(self):
        with TestClient(_app()) as client:
            resp = client.post("/chat", json={"query": ""})
        assert resp.status_code == 400

    def test_blank_query(self):
        with TestClient(_app()) as client:
            resp = client.post("/chat", json={"query": "   "})
        assert resp.status_code == 400

    def test_not_initialized(self, monkeypatch):
        import backend.api_rag as rag
        monkeypatch.setattr(rag, "collection", None)
        monkeypatch.setattr(rag, "model", None)
        with TestClient(rag.app, raise_server_exceptions=False) as client:
            # The lifespan runs on enter and sets collection/model.
            # Re-null them immediately after lifespan completes.
            rag.collection = None
            rag.model = None
            resp = client.post("/chat", json={"query": "test"})
        assert resp.status_code == 503


class TestHealth:
    def test_health(self):
        with TestClient(_app()) as client:
            resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["chroma_docs"] == 3

    def test_health_not_initialized(self, monkeypatch):
        import backend.api_rag as rag
        monkeypatch.setattr(rag, "collection", None)
        monkeypatch.setattr(rag, "model", None)
        with TestClient(rag.app, raise_server_exceptions=False) as client:
            rag.collection = None
            rag.model = None
            resp = client.get("/health")
        assert resp.status_code == 503


class TestQueryChromadb:
    def test_query_returns_results(self):
        from backend.api_rag import query_chromadb
        results = query_chromadb("test query", n_results=2)
        assert len(results) == 2
        assert all("text" in r for r in results)
        assert all("metadata" in r for r in results)
        assert all("similarity" in r for r in results)

    def test_query_empty(self):
        from backend.api_rag import query_chromadb
        import backend.api_rag as rag
        old = rag.collection
        rag.collection = FakeEmptyCollection()
        results = query_chromadb("test")
        assert results == []
        rag.collection = old


class FakeEmptyCollection:
    def count(self):
        return 0
    def query(self, **kw):
        return {"ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]]}


class TestBuildFallbackAnswer:
    def test_build_answer_with_results(self):
        from backend.api_rag import build_fallback_answer
        results = [
            {"text": "Chai tea product", "metadata": {"product_name": "Chai", "total_price": "25.0", "source": "inventory"}, "similarity": 0.95},
        ]
        answer = build_fallback_answer("shipping costs", results)
        assert "Chai" in answer
        assert "shipping costs" in answer

    def test_build_answer_empty(self):
        from backend.api_rag import build_fallback_answer
        answer = build_fallback_answer("test", [])
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


def test_history_endpoint():
    with TestClient(_app()) as client:
        chat_resp = client.post("/chat", json={"query": "hello"})
        assert chat_resp.status_code == 200
        session_id = chat_resp.json()["session_id"]
        hist_resp = client.get(f"/chat/history/{session_id}")
        assert hist_resp.status_code == 200
        data = hist_resp.json()
        assert data["session_id"] == session_id
        assert len(data["messages"]) > 0
