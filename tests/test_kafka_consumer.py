import pytest

from backend.kafka_consumer import _process_message


class FakeTransform:
    def __init__(self, result=None, exc=None):
        self.result = result
        self.exc = exc

    def transform(self, records, target):
        if self.exc:
            raise self.exc
        return self.result


class TestProcessMessage:
    def test_unknown_target(self, mock_kafka_consumer):
        dlq = _make_fake_dlq()
        result = _process_message(
            {"source": "test", "target": "nonexistent", "record": {"name": "Chai"}},
            dlq,
        )
        assert result is True
        assert len(dlq.sent) == 1
        assert "Unknown target" in dlq.sent[0].get("error", "")

    def test_transform_raises_exception(self, mock_kafka_consumer, monkeypatch):
        monkeypatch.setattr(
            "backend.kafka_consumer.transformation_agent.transform",
            lambda records, target: (_ for _ in ()).throw(Exception("transform error")),
        )
        dlq = _make_fake_dlq()
        result = _process_message(
            {"source": "test", "target": "inventory", "record": {"name": "Chai"}},
            dlq,
        )
        assert result is True
        assert len(dlq.sent) == 1
        assert "Transform failed" in dlq.sent[0].get("error", "")

    def test_transform_returns_empty(self, mock_kafka_consumer, monkeypatch):
        monkeypatch.setattr(
            "backend.kafka_consumer.transformation_agent.transform",
            lambda records, target: [],
        )
        dlq = _make_fake_dlq()
        result = _process_message(
            {"source": "test", "target": "inventory", "record": {"name": "Chai"}},
            dlq,
        )
        assert result is True
        assert len(dlq.sent) == 1
        assert "empty result" in dlq.sent[0].get("error", "")

    def test_quality_fails(self, mock_kafka_consumer, monkeypatch):
        monkeypatch.setattr(
            "backend.kafka_consumer.transformation_agent.transform",
            lambda records, target: [{"Product Name": "Chai"}],
        )
        monkeypatch.setattr(
            "backend.kafka_consumer.quality_agent.quality_report",
            lambda rows, target: {
                "passed": False,
                "errors": [{"field": "Unit Price", "message": "required field missing"}],
            },
        )
        dlq = _make_fake_dlq()
        result = _process_message(
            {"source": "test", "target": "inventory", "record": {"name": "Chai"}},
            dlq,
        )
        assert result is True
        assert len(dlq.sent) == 1
        assert "Validation failed" in dlq.sent[0].get("error", "")

    def test_integration_succeeds(self, mock_kafka_consumer, monkeypatch):
        monkeypatch.setattr(
            "backend.kafka_consumer.transformation_agent.transform",
            lambda records, target: [{"Product Name": "Chai", "Unit Price": 18.0}],
        )
        monkeypatch.setattr(
            "backend.kafka_consumer.quality_agent.quality_report",
            lambda rows, target: {"passed": True, "errors": []},
        )
        monkeypatch.setattr(
            "backend.kafka_consumer.integrate",
            lambda rows, target_key, database_url, chroma_path: {"rows_processed": 1},
        )
        dlq = _make_fake_dlq()
        result = _process_message(
            {"source": "test", "target": "inventory", "record": {"name": "Chai"}},
            dlq,
        )
        assert result is True
        assert len(dlq.sent) == 0

    def test_integration_raises(self, mock_kafka_consumer, monkeypatch):
        monkeypatch.setattr(
            "backend.kafka_consumer.transformation_agent.transform",
            lambda records, target: [{"Product Name": "Chai", "Unit Price": 18.0}],
        )
        monkeypatch.setattr(
            "backend.kafka_consumer.quality_agent.quality_report",
            lambda rows, target: {"passed": True, "errors": []},
        )
        def _raise(*a, **kw):
            raise Exception("DB connection failed")
        monkeypatch.setattr(
            "backend.kafka_consumer.integrate",
            _raise,
        )
        dlq = _make_fake_dlq()
        result = _process_message(
            {"source": "test", "target": "inventory", "record": {"name": "Chai"}},
            dlq,
        )
        assert result is False  # retry


def _make_fake_dlq():
    class FakeDlq:
        def __init__(self):
            self.sent = []
        def send(self, topic, value=None):
            self.sent.append(value)
        def flush(self):
            pass
        def close(self):
            pass
    return FakeDlq()
