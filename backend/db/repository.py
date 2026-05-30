from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.db.models import Product, PurchaseOrder, ShippingOrder, Invoice


def get_session(database_url: str) -> Session:
    engine = create_engine(database_url, pool_pre_ping=True)
    return Session(engine)


def upsert_product(session: Session, data: dict) -> Product:
    product = Product(**data)
    session.add(product)
    session.commit()
    return product


def insert_purchase_order(session: Session, data: dict) -> PurchaseOrder:
    record = PurchaseOrder(**data)
    session.add(record)
    session.commit()
    return record


def insert_shipping_order(session: Session, data: dict) -> ShippingOrder:
    record = ShippingOrder(**data)
    session.add(record)
    session.commit()
    return record


def insert_invoice(session: Session, data: dict) -> Invoice:
    record = Invoice(**data)
    session.add(record)
    session.commit()
    return record


def get_products(
    session: Session,
    category: str | None = None,
    search: str | None = None,
    in_stock_only: bool = False,
) -> list[dict]:
    query = session.query(Product)
    if category:
        query = query.filter(Product.category == category)
    if search:
        query = query.filter(Product.product_name.ilike(f"%{search}%"))
    if in_stock_only:
        query = query.filter(Product.units_in_stock > 0)
    rows = query.order_by(Product.ingested_at.desc()).all()

    seen = set()
    results = []
    for r in rows:
        key = r.product_name.lower()
        if key in seen:
            continue
        seen.add(key)
        results.append({
            "product_name": r.product_name,
            "category": r.category,
            "unit_price": r.unit_price or 0.0,
            "units_in_stock": r.units_in_stock or 0,
            "units_sold": r.units_sold or 0,
            "report_period": r.report_period or "",
        })
    return results


def get_categories(session: Session) -> list[dict]:
    from sqlalchemy import func

    rows = (
        session.query(
            Product.category,
            func.count(func.distinct(Product.product_name)).label("product_count"),
            func.coalesce(func.sum(Product.units_in_stock), 0).label("total_stock"),
            func.avg(Product.unit_price).label("avg_price"),
        )
        .filter(Product.category.isnot(None))
        .group_by(Product.category)
        .all()
    )
    return [
        {
            "category": r.category,
            "product_count": r.product_count,
            "total_stock": int(r.total_stock),
            "avg_price": round(float(r.avg_price or 0), 2),
        }
        for r in rows
    ]


def get_product_by_name(session: Session, product_name: str) -> dict | None:
    rows = (
        session.query(Product)
        .filter(Product.product_name.ilike(product_name))
        .order_by(Product.ingested_at.desc())
        .all()
    )
    if not rows:
        return None
    r = rows[0]
    return {
        "product_name": r.product_name,
        "category": r.category or "",
        "category_id": 0,
        "unit_price": r.unit_price or 0.0,
        "units_in_stock": r.units_in_stock or 0,
        "units_sold": r.units_sold or 0,
        "report_period": r.report_period or "",
    }


def get_shipping_cost(session: Session, product_name: str) -> list[dict]:
    rows = (
        session.query(ShippingOrder)
        .filter(ShippingOrder.product_name.ilike(product_name))
        .all()
    )
    return [
        {
            "total_price": r.total_price or 0.0,
            "quantity": r.quantity or 1,
            "shipper_name": r.shipper_name or "Unknown",
            "ship_country": r.ship_country or "",
        }
        for r in rows
    ]


def get_aggregated_top_categories(session: Session, months: int = 3) -> list[dict]:
    from datetime import datetime, timedelta
    from sqlalchemy import func

    cutoff = (datetime.now() - timedelta(days=months * 30)).strftime("%Y-%m")
    rows = (
        session.query(
            Product.category,
            func.sum(Product.units_sold).label("total_sold"),
            func.avg(Product.unit_price).label("avg_price"),
            func.count(Product.id).label("product_count"),
        )
        .filter(Product.report_period >= cutoff)
        .filter(Product.category.isnot(None))
        .group_by(Product.category)
        .order_by(func.sum(Product.units_sold).desc())
        .all()
    )
    return [
        {
            "category": r.category,
            "total_sold": int(r.total_sold or 0),
            "avg_price": round(float(r.avg_price or 0), 2),
            "product_count": r.product_count,
        }
        for r in rows
    ]
