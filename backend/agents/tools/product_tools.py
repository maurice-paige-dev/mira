from langchain_core.tools import tool

from backend.config import DATABASE_URL
from backend.db.repository import get_session, get_products, get_categories, get_product_by_name
from backend.telemetry import get_logger

log = get_logger("product_tools")


@tool
def search_products(search: str = "", category: str = "", in_stock_only: bool = False) -> str:
    """Search products by name, category, and stock availability."""
    if not DATABASE_URL:
        return "Database not configured."
    session = get_session(DATABASE_URL)
    try:
        results = get_products(
            session,
            category=category or None,
            search=search or None,
            in_stock_only=in_stock_only,
        )
        if not results:
            return "No products found matching your criteria."
        lines = [f"Found {len(results)} product(s):"]
        for p in results[:20]:
            stock = f"{p['units_in_stock']} in stock" if p['units_in_stock'] > 0 else "OUT OF STOCK"
            lines.append(f"- {p['product_name']} | ${p['unit_price']:.2f} | {stock} | Category: {p['category']}")
        return "\n".join(lines)
    finally:
        session.close()


@tool
def get_categories_tool() -> str:
    """List all product categories with counts and average prices."""
    if not DATABASE_URL:
        return "Database not configured."
    session = get_session(DATABASE_URL)
    try:
        cats = get_categories(session)
        if not cats:
            return "No categories found."
        lines = ["Product categories:"]
        for c in cats:
            lines.append(f"- {c['category']}: {c['product_count']} products, avg ${c['avg_price']:.2f}, {c['total_stock']} units in stock")
        return "\n".join(lines)
    finally:
        session.close()


@tool
def get_product_by_name_tool(product_name: str) -> str:
    """Get detailed information about a specific product by name."""
    if not DATABASE_URL:
        return "Database not configured."
    session = get_session(DATABASE_URL)
    try:
        p = get_product_by_name(session, product_name)
        if not p:
            return f"Product '{product_name}' not found."
        stock = f"{p['units_in_stock']} in stock" if p['units_in_stock'] > 0 else "OUT OF STOCK"
        return (
            f"Product: {p['product_name']}\n"
            f"Category: {p['category']}\n"
            f"Unit Price: ${p['unit_price']:.2f}\n"
            f"Stock: {stock}\n"
            f"Units Sold: {p['units_sold']}\n"
            f"Report Period: {p['report_period']}"
        )
    finally:
        session.close()
