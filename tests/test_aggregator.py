from datetime import datetime

import pytest

from backend.aggregator import _build_top_categories_doc, _build_summary_doc, run
from backend.db.repository import get_session, upsert_product


class TestBuildTopCategoriesDoc:
    def test_no_data_returns_none(self, db_session):
        assert _build_top_categories_doc(db_session) is None

    def test_with_data(self, db_session):
        period = datetime.now().strftime("%Y-%m")
        upsert_product(db_session, {
            "product_name": "Chai", "category": "Beverages",
            "unit_price": 18.0, "units_in_stock": 39,
            "units_sold": 120, "report_period": period,
        })
        upsert_product(db_session, {
            "product_name": "Tofu", "category": "Produce",
            "unit_price": 12.0, "units_in_stock": 100,
            "units_sold": 50, "report_period": period,
        })
        doc = _build_top_categories_doc(db_session)
        assert doc is not None
        assert doc["id"] == "agg_top_categories"
        assert "Beverages" in doc["text"]
        assert "Produce" in doc["text"]
        assert doc["metadata"]["type"] == "aggregate"
        assert doc["metadata"]["aggregate"] == "top_categories"
        assert doc["metadata"]["category_count"] == 2

    def test_only_recent_data(self, db_session):
        upsert_product(db_session, {
            "product_name": "Old Product", "category": "Old",
            "unit_price": 10.0, "units_in_stock": 5,
            "units_sold": 100, "report_period": "2000-01",
        })
        doc = _build_top_categories_doc(db_session)
        assert doc is None


class TestBuildSummaryDoc:
    def test_no_data_returns_none(self, db_session):
        assert _build_summary_doc(db_session) is None

    def test_with_data(self, db_session):
        period = datetime.now().strftime("%Y-%m")
        upsert_product(db_session, {
            "product_name": "Chai", "category": "Beverages",
            "unit_price": 18.0, "units_in_stock": 39,
            "units_sold": 120, "report_period": period,
        })
        upsert_product(db_session, {
            "product_name": "Tofu", "category": "Produce",
            "unit_price": 12.0, "units_in_stock": 100,
            "units_sold": 50, "report_period": period,
        })
        doc = _build_summary_doc(db_session)
        assert doc is not None
        assert doc["id"] == "agg_catalog_summary"
        assert "2 unique products" in doc["text"]
        assert "139 total units in stock" in doc["text"]
        assert "170 total units sold" in doc["text"]
        assert doc["metadata"]["type"] == "aggregate"
        assert doc["metadata"]["aggregate"] == "catalog_summary"


class TestRun:
    def test_run_without_env_vars(self, monkeypatch):
        monkeypatch.setattr("backend.aggregator.DATABASE_URL", "")
        monkeypatch.setattr("backend.aggregator.CHROMA_PATH", "")
        run()  # should not crash

    def test_run_with_partial_env_vars(self, monkeypatch):
        monkeypatch.setattr("backend.aggregator.DATABASE_URL", "sqlite:///:memory:")
        monkeypatch.setattr("backend.aggregator.CHROMA_PATH", "")
        run()  # should not crash
