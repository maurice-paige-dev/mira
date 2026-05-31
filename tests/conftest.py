from collections import defaultdict
from pathlib import Path

import numpy as np
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.db.models import Base


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture
def chroma_dir(tmp_path) -> Path:
    return tmp_path / "chroma_test"


@pytest.fixture(autouse=True)
def mock_sentence_transformer(monkeypatch):
    class FakeModel:
        def encode(self, texts, **kwargs):
            n = len(texts) if isinstance(texts, list) else 1
            return np.zeros((n, 384), dtype=np.float32)

        def __class__(self):
            return type("SentenceTransformer", (), {})

    monkeypatch.setattr(
        "sentence_transformers.SentenceTransformer",
        lambda *a, **kw: FakeModel(),
    )


@pytest.fixture
def mock_kafka_producer(monkeypatch):
    class FakeProducer:
        def __init__(self, **kwargs):
            self.sent = []

        def send(self, topic, key=None, value=None):
            self.sent.append((topic, key, value))

        def flush(self):
            pass

        def close(self):
            pass

    monkeypatch.setattr("kafka.KafkaProducer", lambda **kw: FakeProducer())
    monkeypatch.setattr(
        "kafka.KafkaConsumer",
        lambda *a, **kw: _FakeConsumer(),
    )
    return FakeProducer


class _FakeConsumer:
    def __init__(self):
        self._closed = False

    def poll(self, timeout_ms=1000, max_records=100):
        return {}

    def close(self):
        self._closed = True


@pytest.fixture
def mock_kafka_consumer(monkeypatch):
    messages = []

    class FakeConsumer:
        def __init__(self, *a, **kw):
            self.messages = messages
            self._closed = False
            self._committed = set()

        def poll(self, timeout_ms=1000, max_records=100):
            if not self.messages:
                return {}
            tp_partition = type("TP", (), {"topic": "test", "partition": 0})()
            batch = []
            while self.messages and len(batch) < max_records:
                batch.append(self.messages.pop(0))
            return {tp_partition: batch}

        def commit(self):
            pass

        def close(self):
            self._closed = True

    class FakeDlqProducer:
        def __init__(self, **kw):
            self.sent = []

        def send(self, topic, value=None):
            self.sent.append(value)

        def flush(self):
            pass

        def close(self):
            pass

    monkeypatch.setattr("backend.kafka_consumer.KafkaConsumer", FakeConsumer)
    monkeypatch.setattr("backend.kafka_consumer.DlqProducer", FakeDlqProducer)

    def add_message(msg: dict):
        messages.append(msg)

    return add_message


@pytest.fixture(autouse=True)
def mock_prefect(monkeypatch):
    def noop_decorator(*a, **kw):
        def passthrough(fn):
            return fn
        return passthrough

    monkeypatch.setattr("prefect.task", noop_decorator)
