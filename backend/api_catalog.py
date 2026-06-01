import os
import math
import time
from pathlib import Path
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from backend.api_upload import router as upload_router
from backend.db.migrations import create_tables
from backend.db.repository import (
    get_session,
    get_products,
    get_categories,
    get_product_by_name,
    get_shipping_cost,
)
from backend.telemetry import get_logger
from backend.metrics import metrics_endpoint, HTTP_REQUEST_COUNT, HTTP_REQUEST_DURATION

log = get_logger("catalog")

BASE = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE / "frontend" / "catalog"
DATABASE_URL = os.environ.get("DATABASE_URL", "")


def _get_db():
    return get_session(DATABASE_URL)


@asynccontextmanager
async def lifespan(application: FastAPI):
    if DATABASE_URL:
        create_tables(DATABASE_URL)
        log.info("database_tables_ready")
    else:
        log.info("no_database_url", detail="running without persistence")
    yield


app = FastAPI(
    title="Product Catalog & Quoting System",
    description="Browse products and get purchase + shipping quotes",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def metrics_and_logging(request: Request, call_next):
    method = request.method
    path = request.url.path
    start = time.monotonic()
    response = await call_next(request)
    elapsed = time.monotonic() - start
    HTTP_REQUEST_COUNT.labels(method=method, path=path, status=response.status_code).inc()
    HTTP_REQUEST_DURATION.labels(method=method, path=path).observe(elapsed)
    log.info("request", method=method, path=path, status=response.status_code, elapsed_ms=round(elapsed * 1000))
    return response


app.add_route("/metrics", metrics_endpoint)

app.include_router(upload_router)


if STATIC_DIR.exists():
    from fastapi.staticfiles import StaticFiles
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", response_class=HTMLResponse)
def index():
    html_path = STATIC_DIR / "index.html"
    if html_path.exists():
        return HTMLResponse(content=html_path.read_text(encoding="utf-8"))
    return HTMLResponse(content="<h1>Frontend not found</h1>", status_code=404)


@app.get("/api/products")
def list_products(
    category: str = Query("", description="Filter by category"),
    search: str = Query("", description="Search product names"),
    in_stock_only: bool = Query(False, description="Only show products in stock"),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
):
    if not DATABASE_URL:
        raise HTTPException(status_code=503, detail="Database not configured")

    session = _get_db()
    try:
        products = get_products(
            session,
            category=category or None,
            search=search or None,
            in_stock_only=in_stock_only,
        )
    finally:
        session.close()

    all_categories = sorted(set(p["category"] for p in products if p["category"])) if products else []
    total = len(products)
    start = (page - 1) * per_page
    page_data = products[start:start + per_page]

    return {
        "products": page_data,
        "total": total,
        "page": page,
        "per_page": per_page,
        "categories": all_categories,
    }


@app.get("/api/categories")
def list_categories():
    if not DATABASE_URL:
        raise HTTPException(status_code=503, detail="Database not configured")

    session = _get_db()
    try:
        cats = get_categories(session)
    finally:
        session.close()
    return {"categories": cats}


@app.get("/api/products/{product_name}")
def product_detail(product_name: str):
    if not DATABASE_URL:
        raise HTTPException(status_code=503, detail="Database not configured")

    session = _get_db()
    try:
        product = get_product_by_name(session, product_name)
    finally:
        session.close()

    if not product:
        raise HTTPException(status_code=404, detail=f"Product '{product_name}' not found")
    return product


class QuoteLineItem(BaseModel):
    product_name: str
    quantity: int = 1


class QuoteRequest(BaseModel):
    items: list[QuoteLineItem]
    destination_country: str = ""
    customer_name: str = ""


class QuoteResponse(BaseModel):
    line_items: list[dict]
    subtotal_product: float
    total_shipping: float
    grand_total: float
    notes: list[str]


@app.post("/api/quote", response_model=QuoteResponse)
def generate_quote(req: QuoteRequest):
    if not DATABASE_URL:
        raise HTTPException(status_code=503, detail="Database not configured")

    session = _get_db()
    try:
        all_products = get_products(session)
    finally:
        session.close()

    prod_map = {p["product_name"].lower(): p for p in all_products}
    line_items = []
    subtotal_product = 0.0
    total_shipping = 0.0
    notes = []

    for item in req.items:
        key = item.product_name.strip().lower()
        match = prod_map.get(key)
        if not match:
            notes.append(f"Product '{item.product_name}' not found in catalog. Skipped.")
            continue

        unit_price = float(match.get("unit_price", 0))
        stock = int(match.get("units_in_stock", 0))
        qty = max(item.quantity, 1)

        stock_status = "in_stock"
        stock_warning = ""
        if stock <= 0:
            stock_status = "out_of_stock"
            stock_warning = "OUT OF STOCK"
            notes.append(f"{item.product_name} is currently out of stock.")
        elif qty > stock:
            stock_status = "limited"
            stock_warning = f"Only {stock} in stock"
            notes.append(f"Only {stock} units of {item.product_name} available (requested {qty}).")

        line_product_total = round(unit_price * qty, 2)
        subtotal_product += line_product_total

        ship = _estimate_shipping(session, item.product_name, qty, req.destination_country)
        line_shipping = ship["estimated_shipping"]
        total_shipping += line_shipping

        line_items.append({
            "product_name": item.product_name,
            "quantity": qty,
            "unit_price": unit_price,
            "line_total": line_product_total,
            "estimated_shipping": line_shipping,
            "shipper": ship.get("shipper", "Unknown"),
            "stock_status": stock_status,
            "stock_warning": stock_warning,
            "shipping_note": ship.get("notes", ""),
        })

    grand_total = round(subtotal_product + total_shipping, 2)
    if not line_items:
        raise HTTPException(status_code=400, detail="No valid products found in quote request.")

    return QuoteResponse(
        line_items=line_items,
        subtotal_product=round(subtotal_product, 2),
        total_shipping=round(total_shipping, 2),
        grand_total=grand_total,
        notes=notes,
    )


def _estimate_shipping(session, product_name: str, quantity: int, destination: str) -> dict:
    try:
        records = get_shipping_cost(session, product_name)
    except Exception:
        records = []

    if not records:
        return {
            "estimated_shipping": 0.0,
            "notes": "No shipping data available",
            "shipper": "Unknown",
        }

    avg_unit = sum(r["total_price"] / max(r["quantity"], 1) for r in records) / len(records)
    common_shipper = max(set(r["shipper_name"] for r in records), key=lambda s: sum(1 for r in records if r["shipper_name"] == s))

    dest_adjustment = 1.0
    if destination:
        dest_records = [r for r in records if r["ship_country"].lower() == destination.lower()]
        if dest_records:
            dest_avg = sum(r["total_price"] / max(r["quantity"], 1) for r in dest_records) / len(dest_records)
            dest_adjustment = dest_avg / avg_unit if avg_unit > 0 else 1.0

    total = avg_unit * quantity * dest_adjustment
    return {
        "estimated_shipping": round(total, 2),
        "notes": f"Based on historical data for {product_name} via {common_shipper}",
        "shipper": common_shipper,
        "avg_unit_shipping": round(avg_unit, 2),
        "destination_adjustment": round(dest_adjustment, 2),
        "historical_records": len(records),
    }


import uuid
from fastapi import File, UploadFile, Form
from backend.db.repository import get_session, get_product_by_name
from backend.db.models import Product
from backend.config import S3_IMAGES_BUCKET, CDN_BASE_URL, AWS_REGION


def _s3_client():
    import boto3
    return boto3.client("s3", region_name=AWS_REGION)


@app.post("/api/images/upload")
async def upload_image(
    product_name: str = Form(...),
    variant: str = Form("full"),
    file: UploadFile = File(...),
):
    if not DATABASE_URL:
        raise HTTPException(status_code=503, detail="Database not configured")

    safe_name = product_name.lower().replace(" ", "-")
    ext = file.filename.rsplit(".", 1)[-1] if file.filename else "jpg"
    key = f"products/{safe_name}/{variant}.{ext}"

    contents = await file.read()
    content_type = file.content_type or "image/jpeg"

    s3 = _s3_client()
    try:
        s3.put_object(
            Bucket=S3_IMAGES_BUCKET,
            Key=key,
            Body=contents,
            ContentType=content_type,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"S3 upload failed: {e}")

    cdn_url = f"{CDN_BASE_URL}/{key}"

    session = _get_db()
    try:
        product = session.query(Product).filter(Product.product_name.ilike(product_name)).first()
        if product:
            product.image_cdn_url = cdn_url
            session.commit()
    finally:
        session.close()

    log.info("image_uploaded", product=product_name, variant=variant, size=len(contents), url=cdn_url)
    return {
        "product_name": product_name,
        "variant": variant,
        "cdn_url": cdn_url,
        "size_bytes": len(contents),
        "content_type": content_type,
    }


@app.get("/api/health")
def health():
    return {"status": "ok", "database_url_configured": bool(DATABASE_URL)}


if __name__ == "__main__":
    log.info("starting", port=8001)
    uvicorn.run(
        "backend.api_catalog:app",
        host="0.0.0.0",
        port=8001,
        reload=False,
    )
