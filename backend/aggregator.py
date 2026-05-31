"""
Aggregator
──────────
Builds composite / aggregate ChromaDB documents from PostgreSQL data.
Runs as a scheduled CronJob to supplement the per-record incremental upserts.
"""

import os
from datetime import datetime

from backend.chroma_upsert import get_model, get_collection, upsert_aggregate_document
from backend.db.migrations import create_tables
from backend.db.repository import get_session, get_aggregated_top_categories
from backend.telemetry import get_logger

log = get_logger("aggregator")

DATABASE_URL = os.environ.get("DATABASE_URL", "")
CHROMA_PATH = os.environ.get("CHROMA_DB_PATH", "")


def _build_top_categories_doc(session) -> dict | None:
    rows = get_aggregated_top_categories(session, months=3)
    if not rows:
        return None

    lines = ["Top Product Categories (Last 3 Months):"]
    for i, r in enumerate(rows[:10], 1):
        lines.append(
            f"{i}. {r['category']} — {r['total_sold']} units sold, "
            f"avg price ${r['avg_price']:.2f}, {r['product_count']} products"
        )
    text = "\n".join(lines)

    metadata = {
        "type": "aggregate",
        "aggregate": "top_categories",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "category_count": len(rows),
    }
    return {"id": "agg_top_categories", "text": text, "metadata": metadata}


def _build_summary_doc(session) -> dict | None:
    from sqlalchemy import func
    from backend.db.models import Product

    result = (
        session.query(
            func.count(func.distinct(Product.product_name)).label("unique_products"),
            func.sum(Product.units_in_stock).label("total_stock"),
            func.sum(Product.units_sold).label("total_sold"),
            func.avg(Product.unit_price).label("avg_price"),
        )
        .first()
    )
    if not result or not result.unique_products:
        return None

    text = (
        f"Catalog Summary: {result.unique_products} unique products, "
        f"{int(result.total_stock or 0)} total units in stock, "
        f"{int(result.total_sold or 0)} total units sold, "
        f"average price ${float(result.avg_price or 0):.2f}."
    )
    metadata = {
        "type": "aggregate",
        "aggregate": "catalog_summary",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }
    return {"id": "agg_catalog_summary", "text": text, "metadata": metadata}


def run() -> None:
    if not DATABASE_URL or not CHROMA_PATH:
        log.error("missing_config", detail="DATABASE_URL and CHROMA_DB_PATH are required")
        return

    create_tables(DATABASE_URL)
    session = get_session(DATABASE_URL)
    model = get_model()
    collection = get_collection(CHROMA_PATH)

    docs = []
    try:
        cat_doc = _build_top_categories_doc(session)
        if cat_doc:
            docs.append(cat_doc)

        sum_doc = _build_summary_doc(session)
        if sum_doc:
            docs.append(sum_doc)
    finally:
        session.close()

    for doc in docs:
        upsert_aggregate_document(
            doc_id=doc["id"],
            text=doc["text"],
            metadata=doc["metadata"],
            model=model,
            collection=collection,
        )
        log.info("upserted", doc_id=doc["id"])

    log.info("done", aggregate_docs=len(docs))


if __name__ == "__main__":
    run()
