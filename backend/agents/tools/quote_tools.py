from langchain_core.tools import tool

from backend.config import DATABASE_URL
from backend.db.repository import get_session, get_product_by_name
from backend.api_catalog import _estimate_shipping
from backend.telemetry import get_logger

log = get_logger("quote_tools")


@tool
def check_stock(product_name: str, quantity: int = 1) -> str:
    """Check if a product has enough stock for the requested quantity."""
    if not DATABASE_URL:
        return "Database not configured."
    session = get_session(DATABASE_URL)
    try:
        p = get_product_by_name(session, product_name)
        if not p:
            return f"Product '{product_name}' not found."
        stock = int(p["units_in_stock"])
        if stock >= quantity:
            return f"✓ {quantity}x {product_name} is available ({stock} in stock)."
        elif stock > 0:
            return f"⚠ Only {stock} of {product_name} in stock (requested {quantity}). Partial fulfillment possible."
        else:
            return f"✗ {product_name} is OUT OF STOCK."
    finally:
        session.close()


@tool
def build_quote_tool(items_json: str, destination_country: str = "", customer_name: str = "") -> str:
    """Build a price quote for one or more products. Provide items as a JSON array of {\"product_name\": str, \"quantity\": int}."""
    import json
    from backend.api_catalog import QuoteLineItem, QuoteRequest

    if not DATABASE_URL:
        return "Database not configured."
    try:
        items_data = json.loads(items_json)
    except json.JSONDecodeError:
        return "Invalid items JSON. Provide an array of {\"product_name\": \"...\", \"quantity\": N}."

    line_items = []
    for it in items_data:
        line_items.append(QuoteLineItem(
            product_name=it.get("product_name", ""),
            quantity=it.get("quantity", 1),
        ))

    req = QuoteRequest(
        items=line_items,
        destination_country=destination_country,
        customer_name=customer_name,
    )

    session = get_session(DATABASE_URL)
    try:
        from backend.db.repository import get_products
        all_products = get_products(session)
    finally:
        session.close()

    prod_map = {p["product_name"].lower(): p for p in all_products}
    lines = []
    subtotal = 0.0
    total_shipping = 0.0

    for item in line_items:
        key = item.product_name.strip().lower()
        match = prod_map.get(key)
        if not match:
            lines.append(f"- {item.product_name}: NOT FOUND, skipped.")
            continue

        unit_price = float(match.get("unit_price", 0))
        qty = max(item.quantity, 1)
        line_total = round(unit_price * qty, 2)
        subtotal += line_total

        stock = int(match.get("units_in_stock", 0))
        stock_note = ""
        if stock <= 0:
            stock_note = " [OUT OF STOCK]"
        elif qty > stock:
            stock_note = f" [only {stock} available]"

        s = _estimate_shipping(get_session(DATABASE_URL) if DATABASE_URL else None, item.product_name, qty, destination_country)
        ship_cost = s["estimated_shipping"]
        total_shipping += ship_cost

        lines.append(f"- {item.product_name} x{qty}: ${unit_price:.2f} each = ${line_total:.2f} | Shipping: ${ship_cost:.2f}{stock_note}")

    grand_total = round(subtotal + total_shipping, 2)
    lines.append(f"---\nSubtotal (products): ${subtotal:.2f}")
    lines.append(f"Total Shipping: ${total_shipping:.2f}")
    lines.append(f"Grand Total: ${grand_total:.2f}")

    return "\n".join(lines)
