import pytest

from backend.agents.quality_agent import validate, quality_report


class TestValidate:
    def test_valid_inventory(self):
        rows = [{"Product Name": "Chai", "Unit Price": "18.00", "Units Sold": "10"}]
        errors = validate(rows, "inventory")
        assert errors == []

    def test_required_field_missing(self):
        rows = [{"Product Name": "Chai"}]  # missing Unit Price
        errors = validate(rows, "inventory")
        assert len(errors) == 1
        assert errors[0]["field"] == "Unit Price"

    def test_required_field_empty(self):
        rows = [{"Product Name": "Chai", "Unit Price": ""}]
        errors = validate(rows, "inventory")
        assert len(errors) == 1

    def test_numeric_field_non_numeric(self):
        rows = [{"Product Name": "Chai", "Unit Price": "abc"}]
        errors = validate(rows, "inventory")
        assert any(e["field"] == "Unit Price" for e in errors)

    def test_negative_quantity(self):
        rows = [{"Order ID": "PO001", "Product Name": "Chai", "Quantity": "-5", "Unit Price": "10"}]
        errors = validate(rows, "purchase_order")
        assert any("must be >= 0" in e["message"] for e in errors)

    def test_product_name_too_short(self):
        rows = [{"Product Name": "A", "Unit Price": "10"}]
        errors = validate(rows, "inventory")
        assert any("too short" in e["message"] for e in errors)

    def test_unknown_target(self):
        with pytest.raises(ValueError, match="Unknown target"):
            validate([], "nonexistent")

    def test_multiple_errors(self):
        rows = [
            {"Product Name": "Chai", "Unit Price": "abc"},
            {"Product Name": "X", "Unit Price": "10"},
        ]
        errors = validate(rows, "inventory")
        assert len(errors) >= 2

    def test_purchase_order_required(self):
        rows = [{"Product Name": "Chai", "Unit Price": "10"}]  # missing Order ID, Quantity
        errors = validate(rows, "purchase_order")
        fields = {e["field"] for e in errors}
        assert "Order ID" in fields
        assert "Quantity" in fields


class TestQualityReport:
    def test_pass(self):
        report = quality_report([{"Product Name": "Chai", "Unit Price": "10"}], "inventory")
        assert report["passed"] is True
        assert report["error_count"] == 0

    def test_fail(self):
        report = quality_report([{"Product Name": "Chai"}], "inventory")
        assert report["passed"] is False
        assert report["error_count"] > 0
