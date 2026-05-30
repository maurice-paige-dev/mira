import pandas as pd
import json
import os
import sys
import shutil
from pathlib import Path

from sentence_transformers import SentenceTransformer

import chromadb
from chromadb.config import Settings

BASE = Path(__file__).resolve().parent.parent
CSV_DIR = BASE / "data" / "csv"
DB_DIR = BASE / "data" / "chroma_shipping_db"


def load_all_data() -> dict:
    csv_map = {}
    for csv_name in [
        "shipping_orders.csv",
        "PurchaseOrders.csv",
        "invoices.csv",
        "inventory_monthly.csv",
        "inventory_monthly_category.csv",
    ]:
        path = CSV_DIR / csv_name
        if not path.exists():
            print(f"  [WARN] {csv_name} not found – skipping")
            continue
        df = pd.read_csv(path)
        stem = csv_name.replace(".csv", "")
        csv_map[stem] = df
        print(f"  Loaded {csv_name}: {len(df)} rows, {len(df.columns)} columns")
    return csv_map


def _to_float(val, default=0.0) -> float:
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _to_int(val, default=0) -> int:
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return default


def build_shipping_documents(so: pd.DataFrame) -> list[dict]:
    docs = []
    for _, row in so.iterrows():
        total = _to_float(row.get("Total Price"))
        product_total = _to_float(row.get("Product Total"))
        qty = _to_int(row.get("Quantity"))
        unit_price = _to_float(row.get("Unit Price"))
        product = str(row.get("Product Name", ""))
        shipper = str(row.get("Shipper Name", ""))
        customer = str(row.get("Customer Name", ""))
        city = str(row.get("Ship City", ""))
        country = str(row.get("Ship Country", ""))
        ship_name = str(row.get("Ship Name", ""))

        doc = (
            f"Shipping Order #{row['Order ID']} for {customer} ({ship_name}) "
            f"shipped via {shipper} to {city}, {country}. "
            f"Product: {product}, Quantity: {qty}, Unit Price: ${unit_price}, "
            f"Product Total: ${product_total}. "
            f"Total Shipping Cost for this order: ${total}."
        )
        docs.append({
            "id": f"ship_{row['Order ID']}_{product}",
            "text": doc,
            "metadata": {
                "source": "shipping_orders",
                "order_id": str(row["Order ID"]),
                "product_name": product,
                "shipper": shipper,
                "customer": customer,
                "ship_city": city,
                "ship_country": country,
                "quantity": qty,
                "unit_price": unit_price,
                "product_total": product_total,
                "total_price": total,
                "order_date": str(row.get("Order Date", "")),
                "shipped_date": str(row.get("Shipped Date", "")),
            },
        })
    return docs


def build_inventory_documents(inv: pd.DataFrame) -> list[dict]:
    docs = []
    for _, row in inv.iterrows():
        unit_price = _to_float(row.get("Unit Price"), 0.0)
        doc = (
            f"Inventory report {row.get('Report Period', '')}: "
            f"Category {row.get('Category', '')}, "
            f"Product {row.get('Product Name', '')}, "
            f"Units Sold: {row.get('Units Sold', '')}, "
            f"Units in Stock: {row.get('Units in Stock', '')}, "
            f"Unit Price: ${unit_price}."
        )
        docs.append({
            "id": f"inv_{row.name}",
            "text": doc,
            "metadata": {
                "source": "inventory",
                "product_name": str(row.get("Product Name", "")),
                "category": str(row.get("Category", "")),
                "report_period": str(row.get("Report Period", "")),
                "units_sold": _to_int(row.get("Units Sold")),
                "units_in_stock": _to_int(row.get("Units in Stock")),
                "unit_price": unit_price,
            },
        })
    return docs


def build_purchase_order_documents(po: pd.DataFrame) -> list[dict]:
    docs = []
    for _, row in po.iterrows():
        doc = (
            f"Purchase Order #{row['Order ID']} dated {row.get('Order Date', '')} "
            f"for customer {row.get('Customer Name', '')}. "
            f"Product: {row.get('Product Name', '')}, "
            f"Product ID: {row.get('Product ID', '')}, "
            f"Quantity: {row.get('Quantity', '')}, "
            f"Unit Price: ${_to_float(row.get('Unit Price'))}."
        )
        docs.append({
            "id": f"po_{row['Order ID']}_{row.get('Product Name', '')}",
            "text": doc,
            "metadata": {
                "source": "purchase_orders",
                "order_id": str(row["Order ID"]),
                "product_name": str(row.get("Product Name", "")),
                "product_id": str(row.get("Product ID", "")),
                "quantity": _to_int(row.get("Quantity")),
                "unit_price": _to_float(row.get("Unit Price")),
                "order_date": str(row.get("Order Date", "")),
                "vendor_name": str(row.get("Customer Name", "")),
            },
        })
    return docs


def build_invoice_documents(inv: pd.DataFrame) -> list[dict]:
    docs = []
    for _, row in inv.iterrows():
        doc = (
            f"Invoice #{row['Order ID']} for customer {row.get('Customer Name', '')} "
            f"({row.get('Contact Name', '')}) at {row.get('Address', '')}, {row.get('City', '')}, "
            f"{row.get('Country', '')}. "
            f"Product: {row.get('Product Name', '')}, "
            f"Quantity: {row.get('Quantity', '')}, "
            f"Unit Price: ${_to_float(row.get('Unit Price'))}, "
            f"Total Invoice: ${_to_float(row.get('Total Price'))}."
        )
        docs.append({
            "id": f"inv_{row['Order ID']}_{row.get('Product Name', '')}",
            "text": doc,
            "metadata": {
                "source": "invoices",
                "order_id": str(row["Order ID"]),
                "product_name": str(row.get("Product Name", "")),
                "customer": str(row.get("Customer Name", "")),
                "city": str(row.get("City", "")),
                "country": str(row.get("Country", "")),
                "quantity": _to_int(row.get("Quantity")),
                "unit_price": _to_float(row.get("Unit Price")),
                "total_price": _to_float(row.get("Total Price")),
            },
        })
    return docs


def build_vendor_warehouse_documents(
    po: pd.DataFrame,
    so: pd.DataFrame,
    inv: pd.DataFrame | None = None,
) -> list[dict]:
    docs = []

    if po is None or po.empty:
        return docs
    if so is None or so.empty:
        return docs

    for vendor, vgrp in po.groupby("Customer Name"):
        products = vgrp["Product Name"].unique()
        product_ids = vgrp["Product ID"].unique()
        total_qty = int(vgrp["Quantity"].sum())

        prod_list = ", ".join(sorted(products))

        doc = (
            f"Third-party vendor {vendor} supplies the following products: "
            f"{prod_list}. "
            f"Total quantity ordered from this vendor: {total_qty} units. "
            f"Products are fulfilled from the vendor's distribution warehouse(s). "
            f"Shipping costs depend on the distance between the customer's location "
            f"and the nearest vendor distribution warehouse."
        )
        docs.append({
            "id": f"vendor_{vendor}_catalog",
            "text": doc,
            "metadata": {
                "source": "vendor_warehouse",
                "vendor_name": vendor,
                "products": prod_list,
                "product_ids": list(map(str, product_ids)),
                "total_quantity": total_qty,
                "data_type": "vendor_catalog",
            },
        })

        for prod in products:
            pgrp = vgrp[vgrp["Product Name"] == prod]
            unit_price = _to_float(pgrp["Unit Price"].iloc[0])
            qty = int(pgrp["Quantity"].sum())

            doc2 = (
                f"Third-party vendor {vendor} supplies {prod} "
                f"(unit price ${unit_price:.2f}). "
                f"Total of {qty} units ordered. "
                f"When a customer orders {prod}, the system routes the order "
                f"through {vendor}'s nearest distribution warehouse based on "
                f"customer location proximity."
            )
            docs.append({
                "id": f"vendor_{vendor}_{prod}",
                "text": doc2,
                "metadata": {
                    "source": "vendor_warehouse",
                    "vendor_name": vendor,
                    "product_name": prod,
                    "unit_price": unit_price,
                    "quantity": qty,
                    "data_type": "vendor_product",
                },
            })

    po_with_dest = po.merge(
        so[["Order ID", "Ship Country", "Ship City", "Ship Region"]].drop_duplicates(),
        on="Order ID",
        how="inner",
    )

    for vendor, vgrp in po_with_dest.groupby("Customer Name"):
        countries = vgrp["Ship Country"].unique()
        regions = vgrp["Ship Region"].unique()
        cities = vgrp["Ship City"].unique()

        country_list = ", ".join(sorted(countries))
        region_list = ", ".join(sorted(regions))

        doc3 = (
            f"Vendor distribution warehouse reach for {vendor}: "
            f"serves customers in {country_list} "
            f"(regions: {region_list}). "
            f"Orders are fulfilled from the distribution warehouse closest "
            f"to the customer's location to minimize shipping costs. "
            f"Products supplied by this third-party vendor may ship from "
            f"different warehouses depending on customer proximity."
        )
        docs.append({
            "id": f"vendor_{vendor}_warehouse_reach",
            "text": doc3,
            "metadata": {
                "source": "vendor_warehouse",
                "vendor_name": vendor,
                "countries": country_list,
                "regions": region_list,
                "num_countries": int(len(countries)),
                "data_type": "warehouse_reach",
            },
        })

    return docs


def build_third_party_vendor_summary_documents(
    data: dict,
) -> list[dict]:
    docs = []
    po = data.get("PurchaseOrders")
    so = data.get("shipping_orders")

    if po is None or po.empty:
        return docs

    vendors = po["Customer Name"].unique()
    total_po_value = (po["Quantity"] * po["Unit Price"]).sum()
    total_items = po["Quantity"].sum()

    vendor_list = ", ".join(sorted(vendors))

    doc = (
        f"The company works with {len(vendors)} third-party vendors who supply products: "
        f"{vendor_list}. "
        f"Total purchase order value: ${total_po_value:.2f}, "
        f"total items: {total_items}. "
        f"When a customer places an order for a product supplied by a third-party "
        f"vendor, the system determines which vendor distribution warehouse is "
        f"closest to the customer's location. This proximity-based routing "
        f"minimizes shipping costs and delivery times. "
        f"Products may come from one or more different warehouses depending on "
        f"the customer's geographic proximity to the vendor's distribution centers."
    )
    docs.append({
        "id": "vendor_summary_overview",
        "text": doc,
        "metadata": {
            "source": "vendor_summary",
            "num_vendors": int(len(vendors)),
            "total_po_value": float(total_po_value),
            "total_items": int(total_items),
            "data_type": "overview",
        },
    })

    if so is not None and not so.empty:
        for prod, pgrp in po.groupby("Product Name"):
            vendors_for_product = pgrp["Customer Name"].unique()
            quantities = pgrp["Quantity"].sum()
            avg_price = (pgrp["Quantity"] * pgrp["Unit Price"]).sum() / quantities if quantities > 0 else 0

            vendor_str = ", ".join(vendors_for_product)

            prod_ship = so[so["Product Name"] == prod]
            if not prod_ship.empty:
                avg_ship = prod_ship["Total Price"].mean()
                ship_info = f"Average shipping cost when ordered: ${avg_ship:.2f}."
            else:
                ship_info = ""

            doc2 = (
                f"Product {prod} is supplied by {len(vendors_for_product)} third-party vendor(s): "
                f"{vendor_str}. "
                f"Total quantity purchased: {int(quantities)} units, "
                f"average unit cost: ${avg_price:.2f}. "
                f"{ship_info} "
                f"The fulfillment warehouse is selected based on customer proximity "
                f"to the vendor's distribution network."
            )
            docs.append({
                "id": f"vendor_prod_summary_{prod}",
                "text": doc2,
                "metadata": {
                    "source": "vendor_summary",
                    "product_name": prod,
                    "vendors": vendor_str,
                    "num_vendors": int(len(vendors_for_product)),
                    "total_quantity": int(quantities),
                    "avg_unit_price": float(avg_price),
                    "data_type": "product_vendor_summary",
                },
            })

    return docs


def build_summary_documents(data: dict) -> list[dict]:
    docs = []
    so = data.get("shipping_orders")
    if so is None or so.empty:
        return docs

    for shipper, grp in so.groupby("Shipper Name"):
        avg_total = grp["Total Price"].mean()
        min_total = grp["Total Price"].min()
        max_total = grp["Total Price"].max()
        num_orders = grp["Order ID"].nunique()
        doc = (
            f"Shipper: {shipper}. "
            f"Shipped {num_orders} orders. "
            f"Average total shipping cost: ${avg_total:.2f}, "
            f"Min: ${min_total:.2f}, Max: ${max_total:.2f}."
        )
        docs.append({
            "id": f"summary_shipper_{shipper}",
            "text": doc,
            "metadata": {
                "source": "summary",
                "shipper": shipper,
                "avg_total": float(avg_total),
                "min_total": float(min_total),
                "max_total": float(max_total),
                "num_orders": int(num_orders),
            },
        })

    for prod, grp in so.groupby("Product Name"):
        avg_total = grp["Total Price"].mean()
        avg_product_total = grp["Product Total"].mean()
        count = len(grp)
        doc = (
            f"Product: {prod}. "
            f"Ordered {count} times across different orders. "
            f"Average total shipping cost per order containing this product: ${avg_total:.2f}. "
            f"Average product line total: ${avg_product_total:.2f}."
        )
        docs.append({
            "id": f"summary_product_{prod}",
            "text": doc,
            "metadata": {
                "source": "summary",
                "product_name": prod,
                "avg_total": float(avg_total),
                "avg_product_total": float(avg_product_total),
                "count": int(count),
            },
        })

    for cust, grp in so.groupby("Customer Name"):
        if len(grp) < 5:
            continue
        avg_total = grp["Total Price"].mean()
        total_spent = grp["Total Price"].sum()
        doc = (
            f"Customer: {cust}. "
            f"Placed {grp['Order ID'].nunique()} orders ({len(grp)} line items). "
            f"Total shipping cost across all orders: ${total_spent:.2f}. "
            f"Average shipping cost per order: ${avg_total:.2f}."
        )
        docs.append({
            "id": f"summary_customer_{cust}",
            "text": doc,
            "metadata": {
                "source": "summary",
                "customer": cust,
                "num_orders": int(grp["Order ID"].nunique()),
                "line_items": int(len(grp)),
                "total_shipping_cost": float(total_spent),
                "avg_shipping_cost": float(avg_total),
            },
        })

    return docs


def build_vector_store(docs: list[dict], persist_dir: str | None = None):
    model = SentenceTransformer("all-MiniLM-L6-v2")
    print(f"\n  Embedding model: all-MiniLM-L6-v2 (384-dim)")

    db_path = Path(persist_dir) if persist_dir else DB_DIR
    if db_path.exists():
        shutil.rmtree(db_path)

    client = chromadb.PersistentClient(
        path=str(db_path),
        settings=Settings(anonymized_telemetry=False),
    )
    collection = client.create_collection(
        name="shipping_advisor",
        metadata={"hnsw:space": "cosine"},
    )

    ids = []
    texts = []
    metadatas = []

    for d in docs:
        ids.append(d["id"])
        texts.append(d["text"])
        metadatas.append(d["metadata"])

    BATCH = 128
    for i in range(0, len(texts), BATCH):
        batch_end = min(i + BATCH, len(texts))
        batch_texts = texts[i:batch_end]
        batch_ids = ids[i:batch_end]
        batch_metas = metadatas[i:batch_end]

        embeddings = model.encode(batch_texts, show_progress_bar=False).tolist()
        collection.add(
            ids=batch_ids,
            documents=batch_texts,
            embeddings=embeddings,
            metadatas=batch_metas,
        )

    print(f"  Added {len(docs)} documents to ChromaDB collection 'shipping_advisor'")
    return collection, model


def query_shipping(collection, model, query: str, n_results: int = 5) -> list[dict]:
    q_emb = model.encode([query]).tolist()
    results = collection.query(
        query_embeddings=q_emb,
        n_results=n_results,
        include=["documents", "metadatas", "distances"],
    )
    out = []
    for doc, meta, dist in zip(
        results["documents"][0],
        results["metadatas"][0],
        results["distances"][0],
    ):
        out.append({
            "text": doc,
            "metadata": meta,
            "similarity": 1.0 - dist,
        })
    return out


def interactive_query(collection, model):
    print("\n" + "\u2550" * 60)
    print("  Shipping Cost Advisor \u2013 RAG Query Mode")
    print("  Type your questions about shipping costs.")
    print("  Examples:")
    print('    "What is the average shipping cost for Queso Cabrales?"')
    print('    "Which shipper is cheapest?"')
    print('    "Shipping costs for orders to France"')
    print('    "Compare shipping costs across products"')
    print('    "What affects shipping cost the most?"')
    print('    "Which third-party vendors supply Tofu?"')
    print('    "How does vendor warehouse proximity affect shipping?"')
    print("  Type 'quit' or 'exit' to stop.")
    print("\u2550" * 60)

    while True:
        try:
            q = input("\n\u2753 Query: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not q:
            continue
        if q.lower() in ("quit", "exit", "q"):
            break

        results = query_shipping(collection, model, q, n_results=7)
        print(f"\n  Top {len(results)} results:")
        print("  " + "-" * 60)
        for i, r in enumerate(results, 1):
            meta = r["metadata"]
            sim = r["similarity"]
            source = meta.get("source", "?")
            product = meta.get("product_name", "")
            shipper = meta.get("shipper", "")
            total = meta.get("total_price", "")
            vendor = meta.get("vendor_name", "")
            data_type = meta.get("data_type", "")
            print(f"  {i}. [sim={sim:.3f}] [{source}]")
            if product:
                print(f"     Product : {product}")
            if shipper:
                print(f"     Shipper : {shipper}")
            if vendor:
                print(f"     Vendor  : {vendor}")
            if total:
                print(f"     Total   : ${total}")
            if data_type:
                print(f"     Type    : {data_type}")
            print(f"     {r['text'][:200]}")
            print("  " + "-" * 40)


def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="RAG Shipping Cost Advisor \u2013 build vector store and optionally query."
    )
    parser.add_argument(
        "--no-interactive", "--build-only",
        action="store_true",
        help="Build the vector store and exit without entering interactive query mode.",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("  RAG Shipping Cost Advisor \u2013 Data Pipeline")
    print("=" * 60)

    print("\n[1/4] Loading CSV data \u2026")
    data = load_all_data()
    if "shipping_orders" not in data:
        print("  [FATAL] shipping_orders.csv is required. Exiting.")
        sys.exit(1)

    print("\n[2/4] Building text documents from data \u2026")
    docs = []

    ship_docs = build_shipping_documents(data["shipping_orders"])
    docs.extend(ship_docs)
    print(f"  Shipping-order line-item docs: {len(ship_docs)}")

    if "inventory_monthly" in data:
        inv_docs = build_inventory_documents(data["inventory_monthly"])
        docs.extend(inv_docs)
        print(f"  Inventory docs: {len(inv_docs)}")
    if "inventory_monthly_category" in data:
        inv_docs2 = build_inventory_documents(data["inventory_monthly_category"])
        docs.extend(inv_docs2)
        print(f"  Inventory (category) docs: {len(inv_docs2)}")
    if "PurchaseOrders" in data:
        po_docs = build_purchase_order_documents(data["PurchaseOrders"])
        docs.extend(po_docs)
        print(f"  Purchase-order docs: {len(po_docs)}")
    if "invoices" in data:
        invc_docs = build_invoice_documents(data["invoices"])
        docs.extend(invc_docs)
        print(f"  Invoice docs: {len(invc_docs)}")

    if "PurchaseOrders" in data and "shipping_orders" in data:
        vendor_docs = build_vendor_warehouse_documents(
            data["PurchaseOrders"],
            data["shipping_orders"],
            data.get("inventory_monthly"),
        )
        docs.extend(vendor_docs)
        print(f"  Vendor warehouse / third-party docs: {len(vendor_docs)}")

        vendor_summary_docs = build_third_party_vendor_summary_documents(data)
        docs.extend(vendor_summary_docs)
        print(f"  Third-party vendor summary docs: {len(vendor_summary_docs)}")

    summary_docs = build_summary_documents(data)
    docs.extend(summary_docs)
    print(f"  Summary / aggregate docs: {len(summary_docs)}")

    print(f"\n  Total documents: {len(docs)}")

    print("\n[3/4] Building ChromaDB vector store \u2026")
    collection, model = build_vector_store(docs)

    if args.no_interactive:
        print("\n" + "=" * 60)
        print("  Build complete. Vector DB persisted at data/chroma_shipping_db/")
        print("=" * 60)
        return

    print("\n[4/4] Ready!")
    interactive_query(collection, model)

    print("\n" + "=" * 60)
    print("  Done. Vector DB persisted at data/chroma_shipping_db/")
    print("=" * 60)


if __name__ == "__main__":
    main()
