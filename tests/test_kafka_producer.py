from backend.kafka_producer import create_producer, publish_record, publish_batch, close_producer


class TestCreateProducerConfig:
    def test_without_sasl(self, monkeypatch):
        captured = {}

        def fake_producer(**kw):
            captured["config"] = kw
            class Fake:
                def send(self, **kw): pass
                def flush(self): pass
                def close(self): pass
            return Fake()

        monkeypatch.setattr("backend.kafka_producer.KafkaProducer", fake_producer)
        create_producer(bootstrap_servers="localhost:9092")

        assert captured["config"]["bootstrap_servers"] == "localhost:9092"
        assert captured["config"]["acks"] == "all"

    def test_with_sasl(self, monkeypatch):
        captured = {}

        def fake_producer(**kw):
            captured["config"] = kw
            class Fake:
                def send(self, **kw): pass
                def flush(self): pass
                def close(self): pass
            return Fake()

        monkeypatch.setattr("backend.kafka_producer.KafkaProducer", fake_producer)
        create_producer(
            bootstrap_servers="localhost:9092",
            sasl_username="user",
            sasl_password="pass",
        )

        assert captured["config"]["security_protocol"] == "SASL_SSL"
        assert captured["config"]["sasl_mechanism"] == "PLAIN"
        assert captured["config"]["sasl_plain_username"] == "user"
        assert captured["config"]["sasl_plain_password"] == "pass"


class TestPublishRecord:
    def test_sends_with_key(self, monkeypatch):
        sent = []

        class FakeProducer:
            def send(self, topic=None, key=None, value=None):
                sent.append((topic, key, value))
            def flush(self): pass
            def close(self): pass

        producer = FakeProducer()
        publish_record(producer, "test-topic", {"name": "Chai"}, key="Chai")
        assert sent[0][0] == "test-topic"
        assert sent[0][1] == "Chai"

    def test_generates_key_from_record(self, monkeypatch):
        sent = []

        class FakeProducer:
            def send(self, topic=None, key=None, value=None):
                sent.append((topic, key, value))
            def flush(self): pass
            def close(self): pass

        producer = FakeProducer()
        publish_record(producer, "test-topic", {"id": 42, "name": "Chai"})
        assert sent[0][1] == "42"


class TestPublishBatch:
    def test_publishes_all(self, monkeypatch):
        sent = []

        class FakeProducer:
            def send(self, topic=None, key=None, value=None):
                sent.append((topic, key, value))
            def flush(self): pass
            def close(self): pass

        producer = FakeProducer()
        records = [{"id": 1}, {"id": 2}, {"id": 3}]
        count = publish_batch(producer, "test", records, key_field="id")
        assert count == 3
        assert len(sent) == 3


class TestCloseProducer:
    def test_flushes_and_closes(self, monkeypatch):
        flushed = False
        closed = False

        class FakeProducer:
            def flush(self):
                nonlocal flushed
                flushed = True
            def close(self):
                nonlocal closed
                closed = True

        close_producer(FakeProducer())
        assert flushed
        assert closed
