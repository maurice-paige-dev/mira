import io
import os

os.environ["DATABASE_URL"] = "sqlite:///:memory:"

from fastapi.testclient import TestClient

from backend.api_catalog import app


class TestUpload:
    def test_csv_upload(self, mock_kafka_producer, monkeypatch):
        monkeypatch.setattr("backend.api_upload.KProducer", lambda **kw: mock_kafka_producer(**kw))
        content = "Product Name,Unit Price,Quantity\nChai,18.0,10\n"
        with TestClient(app) as client:
            resp = client.post(
                "/api/upload",
                files={"file": ("test.csv", io.BytesIO(content.encode()), "text/csv")},
                data={"target": "inventory"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["accepted"] is True
        assert data["record_count"] == 1
        assert data["file"] == "test.csv"
        assert data["target"] == "inventory"

    def test_json_upload(self, mock_kafka_producer, monkeypatch):
        monkeypatch.setattr("backend.api_upload.KProducer", lambda **kw: mock_kafka_producer(**kw))
        content = b'[{"name": "Chai", "price": 18.0}]'
        with TestClient(app) as client:
            resp = client.post(
                "/api/upload",
                files={"file": ("test.json", io.BytesIO(content), "application/json")},
                data={"target": "inventory"},
            )
        assert resp.status_code == 200
        assert resp.json()["record_count"] == 1

    def test_jsonl_upload(self, mock_kafka_producer, monkeypatch):
        monkeypatch.setattr("backend.api_upload.KProducer", lambda **kw: mock_kafka_producer(**kw))
        content = b'{"name": "Chai"}\n{"name": "Tofu"}\n'
        with TestClient(app) as client:
            resp = client.post(
                "/api/upload",
                files={"file": ("test.jsonl", io.BytesIO(content), "application/jsonl")},
                data={"target": "inventory"},
            )
        assert resp.status_code == 200
        assert resp.json()["record_count"] == 2

    def test_invalid_target(self, mock_kafka_producer, monkeypatch):
        monkeypatch.setattr("backend.api_upload.KProducer", lambda **kw: mock_kafka_producer(**kw))
        with TestClient(app) as client:
            resp = client.post(
                "/api/upload",
                files={"file": ("test.csv", io.BytesIO(b"a,b\n1,2"), "text/csv")},
                data={"target": "invalid_target"},
            )
        assert resp.status_code == 400
        assert "Invalid target" in resp.json()["detail"]

    def test_unsupported_file_type(self, mock_kafka_producer, monkeypatch):
        monkeypatch.setattr("backend.api_upload.KProducer", lambda **kw: mock_kafka_producer(**kw))
        with TestClient(app) as client:
            resp = client.post(
                "/api/upload",
                files={"file": ("test.txt", io.BytesIO(b"data"), "text/plain")},
                data={"target": "inventory"},
            )
        assert resp.status_code == 400
        assert "Unsupported file type" in resp.json()["detail"]

    def test_empty_file(self, mock_kafka_producer, monkeypatch):
        monkeypatch.setattr("backend.api_upload.KProducer", lambda **kw: mock_kafka_producer(**kw))
        with TestClient(app) as client:
            resp = client.post(
                "/api/upload",
                files={"file": ("empty.csv", io.BytesIO(b"Header\n"), "text/csv")},
                data={"target": "inventory"},
            )
        assert resp.status_code == 400
