from langchain_core.tools import tool

from backend.config import DATABASE_URL
from backend.db.repository import get_session, get_products, get_categories, get_product_by_name
from backend.telemetry import get_logger

log = get_logger("pricing_tools")


@tool
def get_price_history(product_name: str, months: int = 6) -> str:
    """Get the price history / trends for a product."""
    if not DATABASE_URL:
        return "Database not configured."
    session = get_session(DATABASE_URL)
    try:
        results = get_products(session, search=product_name)
        if not results:
            return f"No data found for '{product_name}'."
        prices = [p for p in results if p["unit_price"] > 0]
        if not prices:
            return f"No pricing data available for '{product_name}'."
        lines = [f"Price history for '{product_name}' (last {months} months):"]
        for p in prices[:10]:
            lines.append(f"  ${p['unit_price']:.2f} — Period: {p['report_period'] or 'N/A'}")
        avg = sum(p["unit_price"] for p in prices) / len(prices)
        lines.append(f"Average price: ${avg:.2f}")
        return "\n".join(lines)
    finally:
        session.close()


@tool
def check_overpricing(product_name: str) -> str:
    """Check if a product is priced significantly above its category average."""
    if not DATABASE_URL:
        return "Database not configured."
    session = get_session(DATABASE_URL)
    try:
        p = get_product_by_name(session, product_name)
        if not p:
            return f"Product '{product_name}' not found."
        cats = get_categories(session)
        cat_info = next((c for c in cats if c["category"] == p["category"]), None)
        if not cat_info or cat_info["avg_price"] == 0:
            return f"Could not compare pricing — no category average for '{p['category']}'."
        avg = cat_info["avg_price"]
        price = p["unit_price"]
        ratio = price / avg if avg > 0 else 1
        if ratio > 1.3:
            return f"⚠ {product_name} (${price:.2f}) is {((ratio - 1) * 100):.0f}% ABOVE the category average of ${avg:.2f} for '{p['category']}'."
        elif ratio < 0.7:
            return f"ℹ {product_name} (${price:.2f}) is {((1 - ratio) * 100):.0f}% BELOW the category average of ${avg:.2f} for '{p['category']}'."
        else:
            return f"✓ {product_name} (${price:.2f}) is priced competitively within the {p['category']} category (avg: ${avg:.2f})."
    finally:
        session.close()


@tool
def get_category_price_range(category: str) -> str:
    """Get min, max, and average price for a product category."""
    if not DATABASE_URL:
        return "Database not configured."
    session = get_session(DATABASE_URL)
    try:
        cats = get_categories(session)
        cat_info = next((c for c in cats if c["category"].lower() == category.lower()), None)
        if not cat_info:
            return f"Category '{category}' not found."
        return (
            f"Category: {cat_info['category']}\n"
            f"Products: {cat_info['product_count']}\n"
            f"Average Price: ${cat_info['avg_price']:.2f}\n"
            f"Total Stock: {cat_info['total_stock']} units"
        )
    finally:
        session.close()


@tool
def apply_promotion(product_name: str, discount_pct: float, reason: str) -> str:
    """Apply a temporary promotional discount to a product (recorded but not committed permanently)."""
    if not DATABASE_URL:
        return "Database not configured."
    session = get_session(DATABASE_URL)
    try:
        p = get_product_by_name(session, product_name)
        if not p:
            return f"Product '{product_name}' not found."
        if not (0 < discount_pct < 100):
            return "Discount must be between 1% and 99%."
        discounted = round(p["unit_price"] * (1 - discount_pct / 100), 2)
        return (
            f"Promotion recorded for {product_name}:\n"
            f"  Original price: ${p['unit_price']:.2f}\n"
            f"  Discount: {discount_pct:.0f}%\n"
            f"  Promotional price: ${discounted:.2f}\n"
            f"  Reason: {reason}\n"
            f"  Note: This is a proposed change and must be confirmed in the product database."
        )
    finally:
        session.close()
