import pytest
from datetime import datetime

from backend.db.repository import (
    get_session,
    upsert_product,
    insert_purchase_order,
    insert_shipping_order,
    insert_invoice,
    get_products,
    get_categories,
    get_product_by_name,
    get_shipping_cost,
    get_aggregated_top_categories,
)
from backend.db.models import Product


class TestUpsertProduct:
    def test_insert_new_product(self, db_session):
        data = {
            "product_name": "Chai",
            "category": "Beverages",
            "unit_price": 18.0,
            "units_in_stock": 39,
            "units_sold": 120,
            "report_period": "2025-01",
        }
        upsert_product(db_session, data)
        rows = get_products(db_session)
        assert len(rows) == 1
        assert rows[0]["product_name"] == "Chai"

    def test_upsert_updates_existing_in_query(self, db_session):
        upsert_product(db_session, {
            "product_name": "Chai",
            "category": "Beverages",
            "unit_price": 18.0,
            "units_in_stock": 39,
            "units_sold": 120,
            "report_period": "2025-01",
        })
        upsert_product(db_session, {
            "product_name": "Chai",
            "category": "Beverages",
            "unit_price": 20.0,
            "units_in_stock": 50,
            "units_sold": 130,
            "report_period": "2025-02",
        })
        rows = get_products(db_session)
        assert len(rows) == 1
        assert rows[0]["unit_price"] == 20.0


class TestGetProducts:
    def test_empty_db(self, db_session):
        assert get_products(db_session) == []

    def test_filter_by_category(self, db_session):
        upsert_product(db_session, {"product_name": "Chai", "category": "Beverages", "unit_price": 18.0, "units_in_stock": 39, "units_sold": 120, "report_period": "2025-01"})
        upsert_product(db_session, {"product_name": "Tofu", "category": "Produce", "unit_price": 12.0, "units_in_stock": 100, "units_sold": 50, "report_period": "2025-01"})
        results = get_products(db_session, category="Beverages")
        assert len(results) == 1
        assert results[0]["product_name"] == "Chai"

    def test_search_case_insensitive(self, db_session):
        upsert_product(db_session, {"product_name": "Chai", "category": "Beverages", "unit_price": 18.0, "units_in_stock": 39, "units_sold": 120, "report_period": "2025-01"})
        results = get_products(db_session, search="chai")
        assert len(results) == 1

    def test_in_stock_only(self, db_session):
        upsert_product(db_session, {"product_name": "Chai", "category": "Beverages", "unit_price": 18.0, "units_in_stock": 0, "units_sold": 120, "report_period": "2025-01"})
        upsert_product(db_session, {"product_name": "Tofu", "category": "Produce", "unit_price": 12.0, "units_in_stock": 100, "units_sold": 50, "report_period": "2025-01"})
        results = get_products(db_session, in_stock_only=True)
        assert len(results) == 1
        assert results[0]["product_name"] == "Tofu"

    def test_dedup_by_name(self, db_session):
        upsert_product(db_session, {"product_name": "Chai", "category": "Beverages", "unit_price": 18.0, "units_in_stock": 39, "units_sold": 120, "report_period": "2025-01"})
        upsert_product(db_session, {"product_name": "Chai", "category": "Beverages", "unit_price": 20.0, "units_in_stock": 50, "units_sold": 130, "report_period": "2025-02"})
        results = get_products(db_session)
        assert len(results) == 1


class TestGetCategories:
    def test_empty_db(self, db_session):
        assert get_categories(db_session) == []

    def test_aggregation(self, db_session):
        upsert_product(db_session, {"product_name": "Chai", "category": "Beverages", "unit_price": 18.0, "units_in_stock": 39, "units_sold": 120, "report_period": "2025-01"})
        upsert_product(db_session, {"product_name": "Coffee", "category": "Beverages", "unit_price": 12.0, "units_in_stock": 100, "units_sold": 50, "report_period": "2025-01"})
        upsert_product(db_session, {"product_name": "Tofu", "category": "Produce", "unit_price": 10.0, "units_in_stock": 25, "units_sold": 80, "report_period": "2025-01"})
        cats = get_categories(db_session)
        cat_map = {c["category"]: c for c in cats}
        assert "Beverages" in cat_map
        assert cat_map["Beverages"]["product_count"] == 2
        assert cat_map["Beverages"]["total_stock"] == 139
        assert cat_map["Beverages"]["avg_price"] == 15.0
        assert cat_map["Produce"]["product_count"] == 1


class TestGetProductByName:
    def test_found(self, db_session):
        upsert_product(db_session, {"product_name": "Chai", "category": "Beverages", "unit_price": 18.0, "units_in_stock": 39, "units_sold": 120, "report_period": "2025-01"})
        result = get_product_by_name(db_session, "Chai")
        assert result is not None
        assert result["product_name"] == "Chai"

    def test_not_found(self, db_session):
        assert get_product_by_name(db_session, "Nonexistent") is None

    def test_case_insensitive(self, db_session):
        upsert_product(db_session, {"product_name": "Chai", "category": "Beverages", "unit_price": 18.0, "units_in_stock": 39, "units_sold": 120, "report_period": "2025-01"})
        result = get_product_by_name(db_session, "chai")
        assert result is not None


class TestGetShippingCost:
    def test_empty(self, db_session):
        assert get_shipping_cost(db_session, "Chai") == []

    def test_with_data(self, db_session):
        insert_shipping_order(db_session, {
            "order_id": "S001",
            "product_name": "Chai",
            "shipper_name": "Speedy Express",
            "total_price": 25.0,
            "quantity": 2,
            "ship_country": "USA",
        })
        results = get_shipping_cost(db_session, "Chai")
        assert len(results) == 1
        assert results[0]["shipper_name"] == "Speedy Express"
        assert results[0]["total_price"] == 25.0


class TestGetAggregatedTopCategories:
    def test_no_data(self, db_session):
        assert get_aggregated_top_categories(db_session) == []

    def test_within_cutoff(self, db_session):
        period = datetime.now().strftime("%Y-%m")
        upsert_product(db_session, {"product_name": "Chai", "category": "Beverages", "unit_price": 18.0, "units_in_stock": 39, "units_sold": 200, "report_period": period})
        upsert_product(db_session, {"product_name": "Tofu", "category": "Produce", "unit_price": 12.0, "units_in_stock": 100, "units_sold": 50, "report_period": period})
        results = get_aggregated_top_categories(db_session, months=6)
        assert len(results) == 2
        assert results[0]["category"] == "Beverages"
        assert results[0]["total_sold"] == 200

    def test_outside_cutoff(self, db_session):
        upsert_product(db_session, {"product_name": "Chai", "category": "Beverages", "unit_price": 18.0, "units_in_stock": 39, "units_sold": 200, "report_period": "2000-01"})
        results = get_aggregated_top_categories(db_session, months=3)
        assert len(results) == 0


class TestOtherInserts:
    def test_insert_purchase_order(self, db_session):
        result = insert_purchase_order(db_session, {
            "order_id": "PO001",
            "product_name": "Chai",
            "quantity": 10,
            "unit_price": 15.0,
        })
        assert result.order_id == "PO001"

    def test_insert_shipping_order(self, db_session):
        result = insert_shipping_order(db_session, {
            "order_id": "S001",
            "product_name": "Chai",
            "shipper_name": "UPS",
            "quantity": 1,
        })
        assert result.order_id == "S001"

    def test_insert_invoice(self, db_session):
        result = insert_invoice(db_session, {
            "order_id": "INV001",
            "product_name": "Chai",
            "quantity": 5,
            "unit_price": 15.0,
        })
        assert result.order_id == "INV001"
