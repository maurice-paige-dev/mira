import pytest

from backend.agents.integration_agent import (
    integrate,
    _write_to_postgres,
    _upsert_chromadb,
)
from backend.db.migrations import create_tables
from backend.db.repository import get_session, get_products, get_shipping_cost


class TestWriteToPostgres:
    def test_inventory_target(self, db_session, monkeypatch):
        monkeypatch.setattr(
            "backend.agents.integration_agent.get_session",
            lambda url: db_session,
        )
        rows = [{
            "Product Name": "Chai",
            "Category": "Beverages",
            "Unit Price": 18.0,
            "Units in Stock": 39,
            "Units Sold": 120,
            "Report Period": "2025-01",
        }]
        count = _write_to_postgres(rows, "inventory", "sqlite:///:memory:")
        assert count == 1
        products = get_products(db_session)
        assert len(products) == 1
        assert products[0]["product_name"] == "Chai"

    def test_shipping_order_target(self, db_session, monkeypatch):
        monkeypatch.setattr(
            "backend.agents.integration_agent.get_session",
            lambda url: db_session,
        )
        rows = [{
            "Order ID": "S001",
            "Product Name": "Chai",
            "Customer Name": "Alice",
            "Quantity": 2,
        }]
        count = _write_to_postgres(rows, "shipping_order", "sqlite:///:memory:")
        assert count == 1
        costs = get_shipping_cost(db_session, "Chai")
        assert len(costs) == 1

    def test_no_database_url_skips_pg(self, monkeypatch):
        result = integrate(
            rows=[{"Product Name": "Chai"}],
            target_key="inventory",
            database_url=None,
            chroma_path=None,
        )
        assert result["pg_written"] == 0
        assert result["chroma_upserted"] == 0


class TestUpsertChromadb:
    def test_upserts_to_chroma(self, chroma_dir):
        rows = [{
            "product_name": "Chai",
            "category": "Beverages",
            "unit_price": 18.0,
        }]
        count = _upsert_chromadb(rows, "inventory", str(chroma_dir))
        assert count == 1

    def test_chroma_skip_for_non_inventory(self, chroma_dir):
        rows = [{"Order ID": "S001"}]
        result = integrate(
            rows=rows,
            target_key="shipping_order",
            database_url=None,
            chroma_path=str(chroma_dir),
        )
        assert result["chroma_upserted"] == 0


class TestIntegrate:
    def test_integrate_inventory(self, db_session, chroma_dir, monkeypatch):
        monkeypatch.setattr(
            "backend.agents.integration_agent.get_session",
            lambda url: db_session,
        )
        rows = [{
            "Product Name": "Chai",
            "Category": "Beverages",
            "Unit Price": 18.0,
            "Units in Stock": 39,
            "Units Sold": 120,
        }]
        result = integrate(
            rows=rows,
            target_key="inventory",
            database_url="sqlite:///:memory:",
            chroma_path=str(chroma_dir),
        )
        assert result["rows_processed"] == 1
        assert result["pg_written"] == 1
        assert result["chroma_upserted"] == 1
        assert result["target"] == "inventory"

    def test_integrate_no_chroma_path(self, db_session, monkeypatch):
        monkeypatch.setattr(
            "backend.agents.integration_agent.get_session",
            lambda url: db_session,
        )
        rows = [{
            "Product Name": "Chai",
            "Category": "Beverages",
            "Unit Price": 18.0,
        }]
        result = integrate(
            rows=rows,
            target_key="inventory",
            database_url="sqlite:///:memory:",
            chroma_path=None,
        )
        assert result["pg_written"] == 1
        assert result["chroma_upserted"] == 0
