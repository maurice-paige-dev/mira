import os
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.db.migrations import create_tables
from backend.db.repository import (
    upsert_product,
    insert_shipping_order,
)


def _db_url(tmp_path: Path, name: str) -> str:
    return f"sqlite:///{tmp_path / name}"


def _make_session(db_url: str) -> Session:
    engine = create_engine(db_url)
    return Session(engine)


def _seed_db(db_url: str):
    create_tables(db_url)
    session = _make_session(db_url)
    upsert_product(session, {
        "product_name": "Chai", "category": "Beverages",
        "unit_price": 18.0, "units_in_stock": 39,
        "units_sold": 120, "report_period": "2025-01",
    })
    upsert_product(session, {
        "product_name": "Tofu", "category": "Produce",
        "unit_price": 12.0, "units_in_stock": 100,
        "units_sold": 50, "report_period": "2025-01",
    })
    upsert_product(session, {
        "product_name": "Green Tea", "category": "Beverages",
        "unit_price": 15.0, "units_in_stock": 0,
        "units_sold": 30, "report_period": "2025-01",
    })
    insert_shipping_order(session, {
        "order_id": "S001", "product_name": "Chai",
        "shipper_name": "Speedy Express", "total_price": 25.0,
        "quantity": 2, "ship_country": "USA",
    })
    session.close()


def _build_app(db_url: str):
    os.environ["DATABASE_URL"] = db_url
    import importlib
    import backend.api_catalog as mod
    importlib.reload(mod)
    return mod.app


class TestHealth:
    def test_health(self, tmp_path):
        db = _db_url(tmp_path, "test.db")
        _seed_db(db)
        app = _build_app(db)
        with TestClient(app) as client:
            resp = client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["database_url_configured"] is True


class TestListProducts:
    def test_empty(self, tmp_path):
        db = _db_url(tmp_path, "empty.db")
        create_tables(db)
        app = _build_app(db)
        with TestClient(app) as client:
            resp = client.get("/api/products")
        assert resp.status_code == 200
        data = resp.json()
        assert data["products"] == []
        assert data["total"] == 0

    def test_with_data(self, tmp_path):
        db = _db_url(tmp_path, "data.db")
        _seed_db(db)
        app = _build_app(db)
        with TestClient(app) as client:
            resp = client.get("/api/products")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["products"]) == 3
        assert data["total"] == 3

    def test_filter_by_category(self, tmp_path):
        db = _db_url(tmp_path, "cat.db")
        _seed_db(db)
        app = _build_app(db)
        with TestClient(app) as client:
            resp = client.get("/api/products?category=Beverages")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["products"]) == 2
        assert all(p["category"] == "Beverages" for p in data["products"])

    def test_search(self, tmp_path):
        db = _db_url(tmp_path, "search.db")
        _seed_db(db)
        app = _build_app(db)
        with TestClient(app) as client:
            resp = client.get("/api/products?search=green")
        assert resp.status_code == 200
        assert len(resp.json()["products"]) == 1

    def test_in_stock_only(self, tmp_path):
        db = _db_url(tmp_path, "stock.db")
        _seed_db(db)
        app = _build_app(db)
        with TestClient(app) as client:
            resp = client.get("/api/products?in_stock_only=true")
        assert resp.status_code == 200
        data = resp.json()
        assert all(p["units_in_stock"] > 0 for p in data["products"])

    def test_pagination(self, tmp_path):
        db = _db_url(tmp_path, "page.db")
        _seed_db(db)
        app = _build_app(db)
        with TestClient(app) as client:
            resp = client.get("/api/products?page=1&per_page=2")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["products"]) == 2
        assert data["total"] == 3
        assert data["page"] == 1
        assert data["per_page"] == 2

    def test_categories_in_response(self, tmp_path):
        db = _db_url(tmp_path, "cats.db")
        _seed_db(db)
        app = _build_app(db)
        with TestClient(app) as client:
            resp = client.get("/api/products")
        assert resp.status_code == 200
        data = resp.json()
        assert "Beverages" in data["categories"]
        assert "Produce" in data["categories"]


class TestListCategories:
    def test_categories(self, tmp_path):
        db = _db_url(tmp_path, "cats2.db")
        _seed_db(db)
        app = _build_app(db)
        with TestClient(app) as client:
            resp = client.get("/api/categories")
        assert resp.status_code == 200
        data = resp.json()
        cat_map = {c["category"]: c for c in data["categories"]}
        assert "Beverages" in cat_map
        assert cat_map["Beverages"]["product_count"] == 2

    def test_empty(self, tmp_path):
        db = _db_url(tmp_path, "empty_cats.db")
        create_tables(db)
        app = _build_app(db)
        with TestClient(app) as client:
            resp = client.get("/api/categories")
        assert resp.status_code == 200
        assert resp.json()["categories"] == []


class TestProductDetail:
    def test_found(self, tmp_path):
        db = _db_url(tmp_path, "detail.db")
        _seed_db(db)
        app = _build_app(db)
        with TestClient(app) as client:
            resp = client.get("/api/products/Chai")
        assert resp.status_code == 200
        assert resp.json()["product_name"] == "Chai"

    def test_not_found(self, tmp_path):
        db = _db_url(tmp_path, "notfound.db")
        _seed_db(db)
        app = _build_app(db)
        with TestClient(app) as client:
            resp = client.get("/api/products/Nonexistent")
        assert resp.status_code == 404


class TestQuote:
    def test_valid_quote(self, tmp_path):
        db = _db_url(tmp_path, "quote.db")
        _seed_db(db)
        app = _build_app(db)
        with TestClient(app) as client:
            resp = client.post("/api/quote", json={
                "items": [{"product_name": "Chai", "quantity": 2}],
            })
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["line_items"]) == 1
        assert data["line_items"][0]["product_name"] == "Chai"
        assert data["line_items"][0]["quantity"] == 2
        assert data["line_items"][0]["unit_price"] == 18.0
        assert data["line_items"][0]["line_total"] == 36.0
        assert data["subtotal_product"] == 36.0
        assert data["grand_total"] > 0

    def test_out_of_stock(self, tmp_path):
        db = _db_url(tmp_path, "oos.db")
        _seed_db(db)
        app = _build_app(db)
        with TestClient(app) as client:
            resp = client.post("/api/quote", json={
                "items": [{"product_name": "Green Tea", "quantity": 1}],
            })
        assert resp.status_code == 200
        data = resp.json()
        assert data["line_items"][0]["stock_status"] == "out_of_stock"

    def test_partial_match(self, tmp_path):
        db = _db_url(tmp_path, "partial.db")
        _seed_db(db)
        app = _build_app(db)
        with TestClient(app) as client:
            resp = client.post("/api/quote", json={
                "items": [
                    {"product_name": "Chai", "quantity": 1},
                    {"product_name": "Nonexistent", "quantity": 1},
                ],
            })
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["line_items"]) == 1
        assert "Nonexistent" in str(data["notes"])

    def test_no_valid_products(self, tmp_path):
        db = _db_url(tmp_path, "novalid.db")
        _seed_db(db)
        app = _build_app(db)
        with TestClient(app) as client:
            resp = client.post("/api/quote", json={
                "items": [{"product_name": "Nonexistent", "quantity": 1}],
            })
        assert resp.status_code == 400
