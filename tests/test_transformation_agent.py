import pytest

from backend.agents.transformation_agent import _match_field, transform


class TestMatchField:
    def test_exact_match(self):
        assert _match_field("Product Name", ["product_name", "name"]) is True

    def test_case_insensitive(self):
        assert _match_field("product name", ["Product Name"]) is True

    def test_underscores_normalized(self):
        assert _match_field("product_name", ["Product Name"]) is True

    def test_hyphens_normalized(self):
        assert _match_field("product-name", ["Product Name"]) is True

    def test_no_match(self):
        assert _match_field("unrelated", ["Product Name"]) is False

    def test_whitespace_stripped(self):
        assert _match_field("  unit_price  ", ["Unit Price"]) is True


class TestTransform:
    def test_unknown_target(self):
        with pytest.raises(ValueError, match="Unknown target"):
            transform([], "nonexistent")

    def test_inventory_basic(self):
        rows = [
            {
                "product_name": "Chai",
                "category": "Beverages",
                "unit_price": "18.00",
                "units_in_stock": "39",
                "units_sold": "120",
                "report_period": "2025-01",
            }
        ]
        result = transform(rows, "inventory")
        assert len(result) == 1
        r = result[0]
        assert r["Product Name"] == "Chai"
        assert r["Category"] == "Beverages"
        assert r["Unit Price"] == 18.0
        assert r["Units in Stock"] == 39
        assert r["Units Sold"] == 120
        assert r["Report Period"] == "2025-01"

    def test_inventory_field_aliasing(self):
        rows = [{"name": "Tofu", "price": "12.50", "stock": "100"}]
        result = transform(rows, "inventory")
        assert result[0]["Product Name"] == "Tofu"
        assert result[0]["Unit Price"] == 12.5
        assert result[0]["Units in Stock"] == 100

    def test_inventory_defaults(self):
        rows = [{"product_name": "Tofu"}]
        result = transform(rows, "inventory")
        assert result[0]["Units Sold"] == 0
        assert result[0]["Category"] == "Uncategorized"

    def test_inventory_category_requires_category_id(self):
        rows = [{"product_name": "Chai", "category_id": "5"}]
        result = transform(rows, "inventory_category")
        assert result[0]["Category ID"] == "5"

    def test_purchase_order(self):
        rows = [{"order_id": "PO001", "product_name": "Chai", "quantity": "10", "unit_price": "15.00"}]
        result = transform(rows, "purchase_order")
        assert result[0]["Order ID"] == "PO001"
        assert result[0]["Quantity"] == 10
        assert result[0]["Unit Price"] == 15.0

    def test_invoice(self):
        rows = [{"order_id": "INV001", "product_name": "Chai", "quantity": "5", "unit_price": "15.00"}]
        result = transform(rows, "invoice")
        assert result[0]["Order ID"] == "INV001"
        assert result[0]["Quantity"] == 5

    def test_shipping_order(self):
        rows = [{"order_id": "S001", "customer_name": "Alice", "product_name": "Chai", "quantity": "2"}]
        result = transform(rows, "shipping_order")
        assert result[0]["Order ID"] == "S001"
        assert result[0]["Customer Name"] == "Alice"
        assert result[0]["Quantity"] == 2

    def test_missing_required_gets_default(self):
        rows = [{"product_name": "Chai"}]  # missing unit_price
        result = transform(rows, "inventory")
        assert result[0]["Unit Price"] == 0.0  # default for missing
        assert result[0]["Product Name"] == "Chai"

    def test_transformer_price_parse(self):
        rows = [{"product_name": "Chai", "unit_price": "$18.00"}]
        result = transform(rows, "inventory")
        assert result[0]["Unit Price"] == 18.0

    def test_report_period_normalized(self):
        rows = [{"product_name": "Chai", "report_period": "2025/1"}]
        result = transform(rows, "inventory")
        assert result[0]["Report Period"] == "2025-01"
