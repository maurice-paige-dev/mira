from pathlib import Path

import chromadb
from chromadb.config import Settings
from sentence_transformers import SentenceTransformer

from backend.telemetry import get_logger
from backend.metrics import CHROMA_DOCUMENTS

log = get_logger("chroma_upsert")


def _build_document_text(product: dict) -> str:
    name = product.get("product_name", product.get("name", "Unknown"))
    category = product.get("category", "General")
    price = product.get("unit_price", product.get("price", 0))
    stock = product.get("units_in_stock", product.get("stock", 0))
    sold = product.get("units_sold", product.get("sold", 0))
    period = product.get("report_period", "")

    parts = [f"Product Name: {name}.", f"Category: {category}."]
    if price:
        parts.append(f"Price: ${float(price):.2f}.")
    if stock:
        parts.append(f"Units in Stock: {int(stock)}.")
    if sold:
        parts.append(f"Units Sold: {int(sold)}.")
    if period:
        parts.append(f"Report Period: {period}.")
    return " ".join(parts)


def get_model(model_name: str = "all-MiniLM-L6-v2") -> SentenceTransformer:
    return SentenceTransformer(model_name)


def get_collection(
    persist_dir: str | Path,
    collection_name: str = "shipping_advisor",
) -> chromadb.Collection:
    client = chromadb.PersistentClient(
        path=str(persist_dir),
        settings=Settings(anonymized_telemetry=False),
    )
    return client.get_or_create_collection(
        name=collection_name,
        metadata={"hnsw:space": "cosine"},
    )


def upsert_product(
    product: dict,
    model: SentenceTransformer,
    collection: chromadb.Collection,
) -> str:
    doc_text = _build_document_text(product)
    doc_id = f"product_{product.get('product_name', product.get('id', 'unknown'))}"
    metadata = {
        "product_name": product.get("product_name", product.get("name", "")),
        "category": product.get("category", ""),
        "unit_price": float(product.get("unit_price", product.get("price", 0))),
        "report_period": product.get("report_period", ""),
    }

    embedding = model.encode(doc_text).tolist()

    collection.upsert(
        ids=[doc_id],
        embeddings=[embedding],
        metadatas=[metadata],
        documents=[doc_text],
    )
    CHROMA_DOCUMENTS.labels(collection=collection.name).set(collection.count())
    log.debug("product_upserted", doc_id=doc_id)
    return doc_id


def delete_product(
    product_name: str,
    collection: chromadb.Collection,
) -> None:
    doc_id = f"product_{product_name}"
    try:
        collection.delete(ids=[doc_id])
        CHROMA_DOCUMENTS.labels(collection=collection.name).set(collection.count())
    except Exception:
        log.warning("delete_failed", doc_id=doc_id)


def upsert_aggregate_document(
    doc_id: str,
    text: str,
    metadata: dict,
    model: SentenceTransformer,
    collection: chromadb.Collection,
) -> None:
    embedding = model.encode(text).tolist()
    collection.upsert(
        ids=[doc_id],
        embeddings=[embedding],
        metadatas=[metadata],
        documents=[text],
    )
    CHROMA_DOCUMENTS.labels(collection=collection.name).set(collection.count())
    log.debug("aggregate_upserted", doc_id=doc_id)
