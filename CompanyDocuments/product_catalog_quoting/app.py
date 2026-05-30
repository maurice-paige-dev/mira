#!/usr/bin/env python3
"""
Product Catalog Management & Quoting System
============================================
Loads inventory data from inventory_monthly.csv and inventory_monthly_category.csv,
provides a product catalog browser and a quoting system that estimates product
costs plus shipping costs for customer orders.
"""

import pandas as pd
import json
import math
from pathlib import Path
from typing import Optional
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# ── Paths ─────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent.resolve()
DATA_DIR = BASE_DIR.parent  # CompanyDocuments directory

# ── Global state ──────────────────────────────────────────
inventory_df: Optional[pd.DataFrame] = None
inventory_cat_df: Optional[pd.DataFrame] = None
shipping_df: Optional[pd.DataFrame] = None
purchase_df: Optional[pd.DataFrame] = None

# ── Data Loading ──────────────────────────────────────────
def load_data():
    global inventory_df, inventory_cat_df, shipping_df, purchase_df

    inv_path = DATA_DIR / "inventory_monthly.csv"
    inv_cat_path = DATA_DIR / "inventory_monthly_category.csv"
    ship_path = DATA_DIR / "shipping_orders.csv"
    po_path = DATA_DIR / "PurchaseOrders.csv"

    if inv_path.exists():
        inventory_df = pd.read_csv(inv_path)
        print(f"  Loaded inventory_monthly.csv: {len(inventory_df)} rows")
    if inv_cat_path.exists():
        inventory_cat_df = pd.read_csv(inv_cat_path)
        print(f"  Loaded inventory_monthly_category.csv: {len(inventory_cat_df)} rows")
    if ship_path.exists():
        shipping_df = pd.read_csv(ship_path)
        print(f"  Loaded shipping_orders.csv: {len(shipping_df)} rows")
    if po_path.exists():
        purchase_df = pd.read_csv(po_path)
        print(f"  Loaded PurchaseOrders.csv: {len(purchase_df)} rows")


def get_consolidated_inventory() -> pd.DataFrame:
    """
    Merge inventory_monthly and inventory_monthly_category into a unified
    product catalog with the latest stock information and categories.

    Priority: inventory_monthly_category.csv is the primary source since it has
    clean category data. inventory_monthly.csv supplements with any products
    not found in the primary source, but has corrupted rows that must be handled.
    """
    # ── Primary: category file ──
    cat_data = None
    if inventory_cat_df is not None and not inventory_cat_df.empty:
        df = inventory_cat_df.copy()
        # Ensure we have exactly the right columns
        if "Category ID" in df.columns and "Category" in df.columns:
            # Build a category mapping
            cat_map = df[["Category ID", "Category"]].drop_duplicates().set_index("Category ID")["Category"].to_dict()
            df = df.rename(columns={
                "Category ID": "category_id",
                "Category": "category",
                "Product Name": "product_name",
                "Units Sold": "units_sold",
                "Units in Stock": "units_in_stock",
                "Unit Price": "unit_price",
                "Report Period": "report_period",
            })
            cat_data = df

    # ── Secondary: monthly file (has corrupted rows) ──
    monthly_data = None
    if inventory_df is not None and not inventory_df.empty:
        # The CSV has 7 columns but some rows have more due to truncated product names with commas.
        # We parse it carefully: only keep rows with exactly 7 valid columns.
        df = inventory_df.copy()
        # Rename known columns
        col_map = {
            "Source File": "source_file",
            "Report Period": "report_period",
            "Category": "category",
            "Product Name": "product_name",
            "Units Sold": "units_sold",
            "Units in Stock": "units_in_stock",
            "Unit Price": "unit_price",
        }
        # Only rename columns that actually exist
        rename_dict = {k: v for k, v in col_map.items() if k in df.columns}
        df = df.rename(columns=rename_dict)

        # Ensure numeric columns are numeric
        for col in ["unit_price", "units_sold", "units_in_stock"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        # Drop rows with NaN in critical columns (indicates corruption)
        before = len(df)
        df = df.dropna(subset=["product_name", "units_sold", "units_in_stock", "unit_price"])
        if before > len(df):
            print(f"  [WARN] Dropped {before - len(df)} corrupted rows from inventory_monthly.csv")

        # Filter out rows where product_name looks corrupted (contains too many commas / extra data)
        if "product_name" in df.columns:
            df = df[df["product_name"].str.len() >= 3]  # must have meaningful name
            df = df[df["product_name"].str.contains(r"^[A-Za-z0-9 \.\-'À-ÿ]+$", na=False)]
            df = df[~df["product_name"].str.contains(r"^\d+$", na=False)]  # not just numbers

        if not df.empty:
            monthly_data = df

    # ── Combine ──
    records = []

    # Process category data first (primary)
    used_products = set()
    if cat_data is not None and not cat_data.empty:
        for _, row in cat_data.iterrows():
            pname = str(row.get("product_name", "")).strip()
            if not pname or pname == "nan":
                continue
            used_products.add(pname.lower())
            records.append({
                "product_name": pname,
                "category": str(row.get("category", "Uncategorized")).strip(),
                "category_id": int(row.get("category_id", 0)) if pd.notna(row.get("category_id")) else 0,
                "unit_price": float(row.get("unit_price", 0)),
                "units_in_stock": int(row.get("units_in_stock", 0)),
                "units_sold": int(row.get("units_sold", 0)),
                "report_period": str(row.get("report_period", "")).strip(),
            })

    # Supplement with monthly data for products not in category file
    if monthly_data is not None and not monthly_data.empty:
        for _, row in monthly_data.iterrows():
            pname = str(row.get("product_name", "")).strip()
            if not pname or pname == "nan":
                continue
            if pname.lower() in used_products:
                continue
            used_products.add(pname.lower())
            records.append({
                "product_name": pname,
                "category": str(row.get("category", "Uncategorized")).strip(),
                "category_id": 0,
                "unit_price": float(row.get("unit_price", 0)),
                "units_in_stock": int(row.get("units_in_stock", 0)),
                "units_sold": int(row.get("units_sold", 0)),
                "report_period": str(row.get("report_period", "")).strip(),
            })

    result = pd.DataFrame(records)
    if result.empty:
        return result

    # For each product, take the most recent report period's data
    result["report_sort"] = result["report_period"].astype(str)
    result = result.sort_values("report_sort", ascending=False)
    result = result.drop_duplicates(subset=["product_name"], keep="first").reset_index(drop=True)
    result = result.drop(columns=["report_sort"])

    # Clean categories
    result["category"] = result["category"].fillna("Uncategorized")
    # Remove any categories that are actually product names (corruption artifacts)
    valid_categories = {
        "Beverages", "Condiments", "Confections", "Dairy Products",
        "Grains/Cereals", "Meat/Poultry", "Produce", "Seafood", "Uncategorized",
    }
    result.loc[~result["category"].isin(valid_categories), "category"] = "Uncategorized"

    return result


def get_categories() -> list:
    """Get unique categories with product counts."""
    inv = get_consolidated_inventory()
    if inv.empty:
        return []
    cats = inv.groupby("category").agg(
        product_count=("product_name", "nunique"),
        total_stock=("units_in_stock", "sum"),
        avg_price=("unit_price", "mean"),
    ).reset_index()
    return cats.to_dict(orient="records")


def estimate_shipping_cost(product_name: str, quantity: int, destination_country: str = "") -> dict:
    """
    Estimate shipping cost based on historical shipping data for the product.
    Returns a dict with cost breakdown.
    """
    if shipping_df is None or shipping_df.empty:
        return {"estimated_shipping": 0, "notes": "No shipping data available", "shipper": "Unknown"}

    # Filter shipping data for this product
    prod_ship = shipping_df[shipping_df["Product Name"].str.strip().str.lower() == product_name.strip().lower()]

    if prod_ship.empty:
        # Fallback: use all products' average shipping
        avg_shipping = shipping_df["Total Price"].mean()
        return {
            "estimated_shipping": round(avg_shipping, 2),
            "notes": "Estimated from overall average shipping cost",
            "shipper": "Average across all shippers",
        }

    # Calculate per-unit shipping cost
    prod_ship = prod_ship.copy()
    prod_ship["unit_shipping"] = prod_ship["Total Price"] / prod_ship["Quantity"].clip(lower=1)

    avg_unit_shipping = prod_ship["unit_shipping"].mean()
    most_common_shipper = prod_ship["Shipper Name"].mode().iloc[0] if not prod_ship["Shipper Name"].mode().empty else "Unknown"

    # Adjust for destination if available
    dest_adjustment = 1.0
    if destination_country:
        dest_ship = prod_ship[prod_ship["Ship Country"].str.lower() == destination_country.lower()]
        if not dest_ship.empty:
            dest_avg = (dest_ship["Total Price"] / dest_ship["Quantity"].clip(lower=1)).mean()
            dest_adjustment = dest_avg / avg_unit_shipping if avg_unit_shipping > 0 else 1.0

    total_shipping = avg_unit_shipping * quantity * dest_adjustment

    return {
        "estimated_shipping": round(total_shipping, 2),
        "notes": f"Based on historical data for {product_name} via {most_common_shipper}",
        "shipper": most_common_shipper,
        "avg_unit_shipping": round(avg_unit_shipping, 2),
        "destination_adjustment": round(dest_adjustment, 2),
        "historical_records": len(prod_ship),
    }


# ── FastAPI App ────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Loading data …")
    load_data()
    print("Ready!")
    yield


app = FastAPI(
    title="Product Catalog & Quoting System",
    description="Browse products and get purchase + shipping quotes",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Serve Static Frontend ─────────────────────────────────
STATIC_DIR = BASE_DIR / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", response_class=HTMLResponse)
def index():
    """Serve the main frontend page."""
    html_path = STATIC_DIR / "index.html"
    if html_path.exists():
        return HTMLResponse(content=html_path.read_text(encoding="utf-8"))
    return HTMLResponse(content="<h1>Frontend not found</h1>", status_code=404)


# ── API Models ────────────────────────────────────────────
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


# ── API Endpoints ─────────────────────────────────────────
@app.get("/api/products")
def list_products(
    category: str = Query("", description="Filter by category"),
    search: str = Query("", description="Search product names"),
    in_stock_only: bool = Query(False, description="Only show products in stock"),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
):
    """List products from the consolidated inventory catalog."""
    inv = get_consolidated_inventory()
    if inv.empty:
        return {"products": [], "total": 0, "page": page, "per_page": per_page, "categories": []}

    # Filters
    if category:
        inv = inv[inv["category"].str.lower() == category.lower()]
    if search:
        inv = inv[inv["product_name"].str.lower().str.contains(search.lower(), na=False)]
    if in_stock_only:
        inv = inv[inv["units_in_stock"] > 0]

    total = len(inv)
    categories = sorted(inv["category"].unique().tolist())

    # Pagination
    start = (page - 1) * per_page
    end = start + per_page
    page_data = inv.iloc[start:end]

    products = []
    for _, row in page_data.iterrows():
        prod = {
            "product_name": row.get("product_name", ""),
            "category": row.get("category", ""),
            "unit_price": float(row.get("unit_price", 0)),
            "units_in_stock": int(row.get("units_in_stock", 0)),
            "units_sold": int(row.get("units_sold", 0)),
            "report_period": str(row.get("report_period", "")),
            "in_stock": int(row.get("units_in_stock", 0)) > 0,
        }
        products.append(prod)

    return {
        "products": products,
        "total": total,
        "page": page,
        "per_page": per_page,
        "categories": categories,
    }


@app.get("/api/categories")
def list_categories():
    """Get all product categories with summary stats."""
    return {"categories": get_categories()}


@app.get("/api/products/{product_name}")
def product_detail(product_name: str):
    """Get detailed info about a specific product."""
    inv = get_consolidated_inventory()
    if inv.empty:
        raise HTTPException(status_code=404, detail="No inventory data")

    match = inv[inv["product_name"].str.lower() == product_name.lower()]
    if match.empty:
        raise HTTPException(status_code=404, detail=f"Product '{product_name}' not found")

    row = match.iloc[0]
    return {
        "product_name": row.get("product_name", ""),
        "category": row.get("category", ""),
        "category_id": int(row.get("category_id", 0)),
        "unit_price": float(row.get("unit_price", 0)),
        "units_in_stock": int(row.get("units_in_stock", 0)),
        "units_sold": int(row.get("units_sold", 0)),
        "report_period": str(row.get("report_period", "")),
        "in_stock": int(row.get("units_in_stock", 0)) > 0,
    }


@app.post("/api/quote", response_model=QuoteResponse)
def generate_quote(req: QuoteRequest):
    """
    Generate a quote for purchasing products with shipping cost estimates.
    """
    inv = get_consolidated_inventory()
    if inv.empty:
        raise HTTPException(status_code=400, detail="No inventory data available")

    line_items = []
    subtotal_product = 0.0
    total_shipping = 0.0
    notes = []

    for item in req.items:
        match = inv[inv["product_name"].str.lower() == item.product_name.strip().lower()]

        if match.empty:
            notes.append(f"⚠ Product '{item.product_name}' not found in catalog. Skipped.")
            continue

        row = match.iloc[0]
        unit_price = float(row.get("unit_price", 0))
        stock = int(row.get("units_in_stock", 0))
        qty = max(item.quantity, 1)

        # Check stock availability
        stock_status = "in_stock"
        stock_warning = ""
        if stock <= 0:
            stock_status = "out_of_stock"
            stock_warning = "OUT OF STOCK"
            notes.append(f"⚠ {item.product_name} is currently out of stock.")
        elif qty > stock:
            stock_status = "limited"
            stock_warning = f"Only {stock} in stock"
            notes.append(f"⚠ Only {stock} units of {item.product_name} available (requested {qty}).")

        # Product line cost
        line_product_total = round(unit_price * qty, 2)
        subtotal_product += line_product_total

        # Shipping estimate
        ship_estimate = estimate_shipping_cost(
            item.product_name, qty, req.destination_country
        )
        line_shipping = ship_estimate["estimated_shipping"]
        total_shipping += line_shipping

        line_items.append({
            "product_name": item.product_name,
            "quantity": qty,
            "unit_price": unit_price,
            "line_total": line_product_total,
            "estimated_shipping": line_shipping,
            "shipper": ship_estimate.get("shipper", "Unknown"),
            "stock_status": stock_status,
            "stock_warning": stock_warning,
            "shipping_note": ship_estimate.get("notes", ""),
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


@app.get("/api/health")
def health():
    """Health check."""
    return {
        "status": "ok",
        "inventory_rows_loaded": len(inventory_df) if inventory_df is not None else 0,
        "inventory_cat_rows_loaded": len(inventory_cat_df) if inventory_cat_df is not None else 0,
        "shipping_rows_loaded": len(shipping_df) if shipping_df is not None else 0,
    }


# ── Main Entry Point ──────────────────────────────────────
if __name__ == "__main__":
    print("=" * 60)
    print("  Product Catalog Management & Quoting System")
    print("=" * 60)
    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=8001,
        reload=False,
    )