from langchain_core.tools import tool

from backend.config import DATABASE_URL
from backend.db.repository import get_session, get_shipping_cost
from backend.api_catalog import _estimate_shipping
from backend.telemetry import get_logger

log = get_logger("shipping_tools")


@tool
def estimate_shipping(product_name: str, quantity: int = 1, destination_country: str = "") -> str:
    """Estimate shipping cost for a product to a destination country."""
    if not DATABASE_URL:
        return "Database not configured."
    session = get_session(DATABASE_URL)
    try:
        result = _estimate_shipping(session, product_name, quantity, destination_country)
        return (
            f"Shipping estimate for {quantity}x {product_name}:\n"
            f"Estimated Cost: ${result['estimated_shipping']:.2f}\n"
            f"Shipper: {result['shipper']}\n"
            f"Notes: {result['notes']}"
        )
    finally:
        session.close()


@tool
def get_shipping_history(product_name: str) -> str:
    """Get past shipping records for a product."""
    if not DATABASE_URL:
        return "Database not configured."
    session = get_session(DATABASE_URL)
    try:
        records = get_shipping_cost(session, product_name)
        if not records:
            return f"No shipping history found for '{product_name}'."
        lines = [f"Shipping history for {product_name} ({len(records)} records):"]
        for r in records[:10]:
            lines.append(f"- Shipper: {r['shipper_name']} | Total: ${r['total_price']:.2f} | Qty: {r['quantity']} | Country: {r['ship_country']}")
        return "\n".join(lines)
    finally:
        session.close()
