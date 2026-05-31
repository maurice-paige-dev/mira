"""
Schema mappings for transforming incoming product data into the existing
CSV structures used by the RAG pipeline.

Each target defines:
  - field_map:     list of candidate input field names → canonical output field
  - required:      fields that must be present after mapping
  - defaults:      default values for optional fields
  - transformers:  optional value-transformation functions
"""

import re
from datetime import datetime


def _generate_source_file() -> str:
    return f"ingest_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"


def _parse_price(v):
    if isinstance(v, (int, float)):
        return float(v)
    s = re.sub(r'[^0-9.]', '', str(v))
    return float(s) if s else 0.0


def _parse_int(v):
    if isinstance(v, (int, float)):
        return int(v)
    s = re.sub(r'[^0-9]', '', str(v))
    return int(s) if s else 0


def _ensure_report_period(val):
    """Normalise a date-like value to YYYY-MM format."""
    val = str(val).strip()
    if re.match(r'^\d{4}-\d{2}$', val):
        return val
    m = re.match(r'^(\d{4})[/-]?(\d{1,2})', val)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}"
    return val


INVENTORY_MONTHLY_SCHEMA = {
    "target": "inventory_monthly.csv",
    "field_map": {
        "Source File":    ["_generated"],
        "Report Period":  ["report_period", "period", "report_date", "month"],
        "Category":       ["category", "product_category", "cat", "department"],
        "Product Name":   ["product_name", "name", "product", "item_name", "title"],
        "Units Sold":     ["units_sold", "sold", "sales_volume", "quantity_sold"],
        "Units in Stock": ["units_in_stock", "stock", "inventory", "quantity_on_hand", "on_hand"],
        "Unit Price":     ["unit_price", "price", "unit_cost", "cost", "retail_price"],
    },
    "required": ["Product Name", "Unit Price"],
    "defaults": {
        "Source File": _generate_source_file,
        "Report Period": lambda: datetime.now().strftime("%Y-%m"),
        "Category": "Uncategorized",
        "Unit Price": 0.0,
        "Units Sold": 0,
        "Units in Stock": 0,
    },
    "transformers": {
        "Unit Price": _parse_price,
        "Units Sold": _parse_int,
        "Units in Stock": _parse_int,
        "Report Period": _ensure_report_period,
    },
}

INVENTORY_CATEGORY_SCHEMA = {
    "target": "inventory_monthly_category.csv",
    "field_map": {
        "Source File":    ["_generated"],
        "Report Period":  ["report_period", "period", "report_date", "month"],
        "Category":       ["category", "product_category", "cat", "department"],
        "Category ID":    ["category_id", "cat_id", "department_id"],
        "Product Name":   ["product_name", "name", "product", "item_name", "title"],
        "Units Sold":     ["units_sold", "sold", "sales_volume", "quantity_sold"],
        "Units in Stock": ["units_in_stock", "stock", "inventory", "quantity_on_hand", "on_hand"],
        "Unit Price":     ["unit_price", "price", "unit_cost", "cost", "retail_price"],
    },
    "required": ["Product Name", "Unit Price", "Category ID"],
    "defaults": {
        "Source File": _generate_source_file,
        "Report Period": lambda: datetime.now().strftime("%Y-%m"),
        "Category": "Uncategorized",
        "Units Sold": 0,
        "Units in Stock": 0,
    },
    "transformers": {
        "Unit Price": _parse_price,
        "Units Sold": _parse_int,
        "Units in Stock": _parse_int,
        "Report Period": _ensure_report_period,
    },
}

PURCHASE_ORDER_SCHEMA = {
    "target": "PurchaseOrders.csv",
    "field_map": {
        "Source File":    ["_generated"],
        "Order ID":       ["order_id", "order", "po_number", "ponumber"],
        "Order Date":     ["order_date", "date", "po_date"],
        "Customer Name":  ["customer_name", "vendor", "supplier", "vendor_name"],
        "Product ID":     ["product_id", "sku", "item_id", "part_number"],
        "Product Name":   ["product_name", "name", "product", "item_name"],
        "Quantity":       ["quantity", "qty", "count"],
        "Unit Price":     ["unit_price", "price", "unit_cost", "cost"],
    },
    "required": ["Order ID", "Product Name", "Quantity", "Unit Price"],
    "defaults": {
        "Source File": _generate_source_file,
        "Order Date": lambda: datetime.now().strftime("%Y-%m-%d"),
        "Customer Name": "Unknown Vendor",
        "Product ID": "N/A",
    },
    "transformers": {
        "Unit Price": _parse_price,
        "Quantity": _parse_int,
    },
}

INVOICE_SCHEMA = {
    "target": "invoices.csv",
    "field_map": {
        "Source File":    ["_generated"],
        "Order ID":       ["order_id", "invoice_id", "invoice", "inv_number"],
        "Customer ID":    ["customer_id", "cust_id", "client_id"],
        "Order Date":     ["order_date", "invoice_date", "date"],
        "Contact Name":   ["contact_name", "contact", "attention"],
        "Address":        ["address", "street", "street_address"],
        "City":           ["city", "town"],
        "Postal Code":    ["postal_code", "zip", "zip_code"],
        "Country":        ["country"],
        "Phone":          ["phone", "telephone", "phone_number"],
        "Fax":            ["fax", "fax_number"],
        "Product ID":     ["product_id", "sku", "item_id"],
        "Product Name":   ["product_name", "name", "product", "item_name"],
        "Quantity":       ["quantity", "qty", "count"],
        "Unit Price":     ["unit_price", "price", "unit_cost"],
        "Total Price":    ["total_price", "total", "invoice_total", "amount"],
    },
    "required": ["Order ID", "Product Name", "Quantity", "Unit Price"],
    "defaults": {
        "Source File": _generate_source_file,
        "Order Date": lambda: datetime.now().strftime("%Y-%m-%d"),
        "Customer ID": "",
        "Contact Name": "",
        "Address": "",
        "City": "",
        "Postal Code": "",
        "Country": "",
        "Phone": "",
        "Fax": "",
        "Product ID": "",
        "Total Price": 0.0,
    },
    "transformers": {
        "Unit Price": _parse_price,
        "Total Price": _parse_price,
        "Quantity": _parse_int,
    },
}

SHIPPING_ORDER_SCHEMA = {
    "target": "shipping_orders.csv",
    "field_map": {
        "Source File":       ["_generated"],
        "Order ID":          ["order_id", "order", "ship_order_id"],
        "Ship Name":         ["ship_name", "recipient", "consignee"],
        "Ship Address":      ["ship_address", "shipping_address", "destination_address"],
        "Ship City":         ["ship_city", "destination_city", "city"],
        "Ship Region":       ["ship_region", "region", "state", "province"],
        "Ship Postal Code":  ["ship_postal_code", "ship_zip", "destination_zip"],
        "Ship Country":      ["ship_country", "destination_country", "country"],
        "Customer ID":       ["customer_id", "cust_id"],
        "Customer Name":     ["customer_name", "customer"],
        "Employee Name":     ["employee_name", "employee", "sales_person"],
        "Shipper ID":        ["shipper_id"],
        "Shipper Name":      ["shipper_name", "shipper", "carrier"],
        "Order Date":        ["order_date", "date"],
        "Shipped Date":      ["shipped_date", "ship_date", "dispatch_date"],
        "Product Name":      ["product_name", "name", "product", "item_name"],
        "Quantity":          ["quantity", "qty", "count"],
        "Unit Price":        ["unit_price", "price", "unit_cost"],
        "Product Total":     ["product_total", "line_total", "subtotal"],
        "Total Price":       ["total_price", "total", "shipping_total", "freight"],
    },
    "required": ["Order ID", "Customer Name", "Product Name", "Quantity"],
    "defaults": {
        "Source File": _generate_source_file,
        "Ship Name": "",
        "Ship Address": "",
        "Ship City": "",
        "Ship Region": "",
        "Ship Postal Code": "",
        "Ship Country": "",
        "Customer ID": "",
        "Employee Name": "",
        "Shipper ID": "",
        "Shipper Name": "Unknown",
        "Order Date": lambda: datetime.now().strftime("%Y-%m-%d"),
        "Shipped Date": "",
        "Unit Price": 0.0,
        "Product Total": 0.0,
        "Total Price": 0.0,
    },
    "transformers": {
        "Unit Price": _parse_price,
        "Product Total": _parse_price,
        "Total Price": _parse_price,
        "Quantity": _parse_int,
    },
}

TARGETS = {
    "inventory": INVENTORY_MONTHLY_SCHEMA,
    "inventory_category": INVENTORY_CATEGORY_SCHEMA,
    "purchase_order": PURCHASE_ORDER_SCHEMA,
    "invoice": INVOICE_SCHEMA,
    "shipping_order": SHIPPING_ORDER_SCHEMA,
}
