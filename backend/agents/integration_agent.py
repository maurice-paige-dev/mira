"""
Integration Agent
─────────────────
Writes validated, transformed records to PostgreSQL and upserts to
ChromaDB so the new data is immediately queryable by the RAG chatbot.
"""

from pathlib import Path

from prefect import task

from backend.db.migrations import create_tables
from backend.db.repository import (
    get_session,
    upsert_product,
    insert_purchase_order,
    insert_shipping_order,
    insert_invoice,
)
from backend.chroma_upsert import get_model, get_collection, upsert_product as chroma_upsert

TARGET_MODEL_MAP = {
    "inventory": "upsert_product",
    "inventory_category": "upsert_product",
    "purchase_order": "insert_purchase_order",
    "invoice": "insert_invoice",
    "shipping_order": "insert_shipping_order",
}

CHROMA_TARGETS = {"inventory", "inventory_category"}


def _pg_field_names(target_key: str) -> dict:
    from backend.agents.schema_config import TARGETS

    schema = TARGETS[target_key]
    field_map = schema["field_map"]
    reverse = {}
    for canonical, candidates in field_map.items():
        reverse[canonical] = canonical
    return {v: v for v in field_map.keys()}


def _write_to_postgres(rows: list[dict], target_key: str, database_url: str) -> int:
    session = get_session(database_url)
    try:
        count = 0
        for row in rows:
            data = {k.lower(): v for k, v in row.items()}
            if target_key in ("inventory", "inventory_category"):
                product_data = {
                    "product_name": data.get("product_name", ""),
                    "category": data.get("category", "Uncategorized"),
                    "unit_price": float(data.get("unit_price", 0)),
                    "units_in_stock": int(data.get("units_in_stock", 0)),
                    "units_sold": int(data.get("units_sold", 0)),
                    "report_period": data.get("report_period", ""),
                    "source_file": data.get("source_file", ""),
                }
                upsert_product(session, product_data)
            elif target_key == "purchase_order":
                insert_purchase_order(session, data)
            elif target_key == "invoice":
                insert_invoice(session, data)
            elif target_key == "shipping_order":
                insert_shipping_order(session, data)
            count += 1
        return count
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _upsert_chromadb(rows: list[dict], target_key: str, chroma_path: str) -> int:
    model = get_model()
    collection = get_collection(chroma_path)
    count = 0
    for row in rows:
        try:
            chroma_upsert(row, model, collection)
            count += 1
        except Exception as e:
            print(f"  [integrate] ChromaDB upsert failed for row: {e}")
    return count


@task(retries=1, retry_delay_seconds=30)
def integrate(
    rows: list[dict],
    target_key: str,
    database_url: str | None = None,
    chroma_path: str | None = None,
    rebuild_rag: bool = True,
) -> dict:
    count_pg = 0
    count_chroma = 0

    if database_url:
        create_tables(database_url)
        count_pg = _write_to_postgres(rows, target_key, database_url)
        print(f"  [integrate] Wrote {count_pg} rows to PostgreSQL ({target_key})")
    else:
        print("  [integrate] Skipped PostgreSQL (no DATABASE_URL)")

    if rebuild_rag and chroma_path and target_key in CHROMA_TARGETS:
        count_chroma = _upsert_chromadb(rows, target_key, chroma_path)
        print(f"  [integrate] Upserted {count_chroma} embeddings to ChromaDB")
    else:
        print(f"  [integrate] Skipped ChromaDB (rebuild={rebuild_rag}, target={target_key})")

    return {
        "target": target_key,
        "rows_processed": len(rows),
        "pg_written": count_pg,
        "chroma_upserted": count_chroma,
    }
