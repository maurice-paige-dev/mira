#!/usr/bin/env python3
"""
Parse PDF files from all directories in CompanyDocuments and generate CSV files.
One row per product line item, with parent order/report info carried over.
Each row includes a "Source File" column to trace back to the original PDF.

Uses UTF-8 BOM for Excel compatibility with special characters.
"""

import fitz  # PyMuPDF
import csv
import os
from pathlib import Path

BASE_DIR = Path(__file__).parent


def parse_purchase_orders(pdf_path):
    """
    Parse PurchaseOrders PDFs - order header + product table.
    Products appear as 4-line groups (ID, Name, Qty, Price).
    Multi-page PDFs repeat headers which must be ignored.
    """
    doc = fitz.open(pdf_path)
    text = ""
    for page in doc:
        text += page.get_text()
    doc.close()

    all_lines = text.split("\n")
    # Strip trailing whitespace, keep empty lines for boundary detection
    lines = [l.strip() for l in all_lines]
    
    order_id = ""
    order_date = ""
    customer_name = ""
    source_file = os.path.basename(pdf_path)
    
    # Find first occurrence of header to get order info
    for i in range(len(lines)):
        if lines[i] == "Order ID" and i + 5 < len(lines):
            order_id = lines[i + 3]
            order_date = lines[i + 4]
            customer_name = lines[i + 5]
            break
    
    # Lines to skip entirely when in product parsing mode
    header_labels = {
        "Purchase Orders", "Order ID", "Order Date", "Customer Name",
        "Products", "Product ID:", "Product:", "Quantity:", "Unit Price:",
        "", "Products",
    }
    
    # Find the first actual "Product ID:" - that's where data starts
    start_idx = -1
    for i, line in enumerate(lines):
        if line == "Product ID:":
            start_idx = i
            break
    
    if start_idx < 0:
        return []
    
    rows = []
    product_buffer = []
    
    for line in lines[start_idx + 1:]:
        if line in header_labels:
            continue
        if line.startswith("Page"):
            continue
        
        product_buffer.append(line)
        if len(product_buffer) == 4:
            rows.append({
                "Source File": source_file,
                "Order ID": order_id,
                "Order Date": order_date,
                "Customer Name": customer_name,
                "Product ID": product_buffer[0],
                "Product Name": product_buffer[1],
                "Quantity": product_buffer[2],
                "Unit Price": product_buffer[3],
            })
            product_buffer = []
    
    return rows


def parse_invoices(pdf_path):
    """Parse invoices PDFs"""
    doc = fitz.open(pdf_path)
    text = ""
    for page in doc:
        text += page.get_text()
    doc.close()

    lines = [l.strip() for l in text.split("\n") if l.strip()]
    
    order_id = ""
    customer_id = ""
    order_date = ""
    contact_name = ""
    address = ""
    city = ""
    postal_code = ""
    country = ""
    phone = ""
    fax = ""
    total_price = ""
    source_file = os.path.basename(pdf_path)
    
    for i, line in enumerate(lines):
        if line.startswith("Order ID:"):
            order_id = line.split(":", 1)[1].strip()
        elif line.startswith("Customer ID:"):
            customer_id = line.split(":", 1)[1].strip()
        elif line.startswith("Order Date:"):
            order_date = line.split(":", 1)[1].strip()
        elif line.startswith("Contact Name:"):
            if i + 1 < len(lines):
                contact_name = lines[i + 1]
        elif line.startswith("Address:"):
            if i + 1 < len(lines):
                address = lines[i + 1]
        elif line.startswith("City:"):
            if i + 1 < len(lines):
                city = lines[i + 1]
        elif line.startswith("Postal Code:"):
            if i + 1 < len(lines):
                postal_code = lines[i + 1]
        elif line.startswith("Country:"):
            if i + 1 < len(lines):
                country = lines[i + 1]
        elif line.startswith("Phone:"):
            if i + 1 < len(lines):
                phone = lines[i + 1]
        elif line.startswith("Fax:"):
            if i + 1 < len(lines):
                fax = lines[i + 1]
    
    # TotalPrice appears as "TotalPrice" on one line and the value on the next, or "TotalPrice440.0"
    for i, line in enumerate(lines):
        if line.startswith("TotalPrice"):
            val = line[len("TotalPrice"):].strip()
            if val:
                total_price = val
            elif i + 1 < len(lines):
                total_price = lines[i + 1]
            break
    
    # Parse product table - after "Product ID\nProduct Name\nQuantity\nUnit Price" header
    rows = []
    in_products = False
    product_buffer = []
    
    for i, line in enumerate(lines):
        if line == "Product ID":
            if (i + 1 < len(lines) and lines[i + 1] == "Product Name" and
                i + 2 < len(lines) and lines[i + 2] == "Quantity" and
                i + 3 < len(lines) and lines[i + 3] == "Unit Price"):
                in_products = True
                continue
        
        if not in_products:
            continue
        if line in ("Product Name", "Quantity", "Unit Price", "Product Details:"):
            continue
        if line.startswith("Page"):
            continue
        if line.startswith("TotalPrice"):
            in_products = False
            continue
        
        product_buffer.append(line)
        if len(product_buffer) == 4:
            rows.append({
                "Source File": source_file,
                "Order ID": order_id,
                "Customer ID": customer_id,
                "Order Date": order_date,
                "Contact Name": contact_name,
                "Address": address,
                "City": city,
                "Postal Code": postal_code,
                "Country": country,
                "Phone": phone,
                "Fax": fax,
                "Product ID": product_buffer[0],
                "Product Name": product_buffer[1],
                "Quantity": product_buffer[2],
                "Unit Price": product_buffer[3],
                "Total Price": total_price,
            })
            product_buffer = []
    
    return rows


def parse_shipping_orders(pdf_path):
    """Parse Shipping orders PDFs"""
    doc = fitz.open(pdf_path)
    text = ""
    for page in doc:
        text += page.get_text()
    doc.close()

    lines = [l.strip() for l in text.split("\n") if l.strip()]
    
    data = {}
    rows = []
    data["Source File"] = os.path.basename(pdf_path)
    
    for line in lines:
        if "Order ID:" in line and "Shipping Details:" not in line:
            data["Order ID"] = line.split(":", 1)[1].strip()
        elif "Ship Name:" in line:
            data["Ship Name"] = line.split(":", 1)[1].strip()
        elif "Ship Address:" in line:
            data["Ship Address"] = line.split(":", 1)[1].strip()
        elif "Ship City:" in line:
            data["Ship City"] = line.split(":", 1)[1].strip()
        elif "Ship Region:" in line:
            data["Ship Region"] = line.split(":", 1)[1].strip()
        elif "Ship Postal Code:" in line:
            data["Ship Postal Code"] = line.split(":", 1)[1].strip()
        elif "Ship Country:" in line:
            data["Ship Country"] = line.split(":", 1)[1].strip()
        elif "Customer ID:" in line:
            data["Customer ID"] = line.split(":", 1)[1].strip()
        elif "Customer Name:" in line:
            data["Customer Name"] = line.split(":", 1)[1].strip()
        elif "Employee Name:" in line:
            data["Employee Name"] = line.split(":", 1)[1].strip()
        elif "Shipper ID:" in line:
            data["Shipper ID"] = line.split(":", 1)[1].strip()
        elif "Shipper Name:" in line:
            data["Shipper Name"] = line.split(":", 1)[1].strip()
        elif "Order Date:" in line and "Shipping Details:" not in line:
            data["Order Date"] = line.split(":", 1)[1].strip()
        elif "Shipped Date:" in line:
            data["Shipped Date"] = line.split(":", 1)[1].strip()
    
    # Parse total price (value on the line after "Total Price:")
    for i, line in enumerate(lines):
        if line.startswith("Total Price:") and i + 1 < len(lines):
            val = lines[i + 1]
            if ":" in val:
                data["Total Price"] = val.split(":", 1)[1].strip()
            else:
                data["Total Price"] = val
            break
    
    in_product = False
    current_product = {}
    
    for line in lines:
        if line.startswith("---"):
            if in_product and current_product:
                rows.append({
                    "Source File": data.get("Source File", ""),
                    "Order ID": data.get("Order ID", ""),
                    "Ship Name": data.get("Ship Name", ""),
                    "Ship Address": data.get("Ship Address", ""),
                    "Ship City": data.get("Ship City", ""),
                    "Ship Region": data.get("Ship Region", ""),
                    "Ship Postal Code": data.get("Ship Postal Code", ""),
                    "Ship Country": data.get("Ship Country", ""),
                    "Customer ID": data.get("Customer ID", ""),
                    "Customer Name": data.get("Customer Name", ""),
                    "Employee Name": data.get("Employee Name", ""),
                    "Shipper ID": data.get("Shipper ID", ""),
                    "Shipper Name": data.get("Shipper Name", ""),
                    "Order Date": data.get("Order Date", ""),
                    "Shipped Date": data.get("Shipped Date", ""),
                    "Product Name": current_product.get("Product", ""),
                    "Quantity": current_product.get("Quantity", ""),
                    "Unit Price": current_product.get("Unit Price", ""),
                    "Product Total": current_product.get("Total", ""),
                    "Total Price": data.get("Total Price", ""),
                })
                current_product = {}
            in_product = True
            continue
        
        if in_product:
            if ":" in line:
                key, _, value = line.partition(":")
                current_product[key.strip()] = value.strip()
    
    if current_product:
        rows.append({
            "Source File": data.get("Source File", ""),
            "Order ID": data.get("Order ID", ""),
            "Ship Name": data.get("Ship Name", ""),
            "Ship Address": data.get("Ship Address", ""),
            "Ship City": data.get("Ship City", ""),
            "Ship Region": data.get("Ship Region", ""),
            "Ship Postal Code": data.get("Ship Postal Code", ""),
            "Ship Country": data.get("Ship Country", ""),
            "Customer ID": data.get("Customer ID", ""),
            "Customer Name": data.get("Customer Name", ""),
            "Employee Name": data.get("Employee Name", ""),
            "Shipper ID": data.get("Shipper ID", ""),
            "Shipper Name": data.get("Shipper Name", ""),
            "Order Date": data.get("Order Date", ""),
            "Shipped Date": data.get("Shipped Date", ""),
            "Product Name": current_product.get("Product", ""),
            "Quantity": current_product.get("Quantity", ""),
            "Unit Price": current_product.get("Unit Price", ""),
            "Product Total": current_product.get("Total", ""),
            "Total Price": data.get("Total Price", ""),
        })
    
    return rows


def parse_stock_report_monthly(pdf_path):
    """
    Parse Inventory Report monthly stock reports.
    Format: 5-line groups (Category, Product, UnitsSold, UnitsInStock, UnitPrice)
    """
    doc = fitz.open(pdf_path)
    text = ""
    for page in doc:
        text += page.get_text()
    doc.close()

    lines = [l.strip() for l in text.split("\n") if l.strip()]
    source_file = os.path.basename(pdf_path)
    
    report_period = ""
    if lines and lines[0].startswith("Stock Report for"):
        report_period = lines[0].split("for", 1)[1].strip()
    
    rows = []
    header_found = False
    data_buffer = []
    
    for line in lines:
        if line == "Category":
            header_found = True
            continue
        if not header_found:
            continue
        if line in ("Product", "Units Sold", "Units in Stock", "Unit Price"):
            continue
        if line.startswith("Stock Report"):
            continue
        
        data_buffer.append(line)
        if len(data_buffer) == 5:
            rows.append({
                "Source File": source_file,
                "Report Period": report_period,
                "Category": data_buffer[0],
                "Product Name": data_buffer[1],
                "Units Sold": data_buffer[2],
                "Units in Stock": data_buffer[3],
                "Unit Price": data_buffer[4],
            })
            data_buffer = []
    
    return rows


def parse_stock_report_category(pdf_path):
    """
    Parse Inventory Report monthly-Category stock reports.
    Format: 4-line groups (Product, UnitsSold, UnitsInStock, UnitPrice)
    """
    doc = fitz.open(pdf_path)
    text = ""
    for page in doc:
        text += page.get_text()
    doc.close()

    lines = [l.strip() for l in text.split("\n") if l.strip()]
    source_file = os.path.basename(pdf_path)
    
    report_period = ""
    category = ""
    category_id = ""
    
    for line in lines:
        if line.startswith("Stock Report for"):
            report_period = line.split("for", 1)[1].strip()
        elif line.startswith("Category :"):
            category = line.split(":", 1)[1].strip()
        elif line.startswith("id category :"):
            category_id = line.split(":", 1)[1].strip()
    
    rows = []
    header_found = False
    data_buffer = []
    
    for line in lines:
        if line == "Product":
            header_found = True
            continue
        if not header_found:
            continue
        if line in ("Units Sold", "Units in Stock", "Unit Price"):
            continue
        if line.startswith("Stock Report") or line.startswith("Category") or line.startswith("id category"):
            continue
        
        data_buffer.append(line)
        if len(data_buffer) == 4:
            rows.append({
                "Source File": source_file,
                "Report Period": report_period,
                "Category": category,
                "Category ID": category_id,
                "Product Name": data_buffer[0],
                "Units Sold": data_buffer[1],
                "Units in Stock": data_buffer[2],
                "Unit Price": data_buffer[3],
            })
            data_buffer = []
    
    return rows


def write_csv(filename, fieldnames, rows):
    """Write rows to CSV with UTF-8 BOM for Excel compatibility"""
    if not rows:
        print(f"  No data found for {filename}")
        return
    
    filepath = BASE_DIR / filename
    with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"  Wrote {len(rows)} rows to {filename}")


def process_directory(dir_path, parser_func, csv_filename, fieldnames):
    """Process all PDFs in a directory using the given parser"""
    if not dir_path.exists():
        print(f"Directory not found: {dir_path}")
        return
    
    pdf_files = sorted(dir_path.glob("*.pdf"))
    print(f"Processing {len(pdf_files)} PDFs from {dir_path}")
    
    all_rows = []
    for pdf_file in pdf_files:
        try:
            rows = parser_func(str(pdf_file))
            all_rows.extend(rows)
        except Exception as e:
            print(f"  Error parsing {pdf_file.name}: {e}")
    
    write_csv(csv_filename, fieldnames, all_rows)


def main():
    print("=" * 60)
    print("CompanyDocuments PDF Parser")
    print("=" * 60)
    
    # 1. PurchaseOrders
    print("\n--- PurchaseOrders ---")
    process_directory(
        BASE_DIR / "PurchaseOrders",
        parse_purchase_orders,
        "PurchaseOrders.csv",
        ["Source File", "Order ID", "Order Date", "Customer Name", "Product ID", "Product Name", "Quantity", "Unit Price"]
    )
    
    # 2. Invoices
    print("\n--- Invoices ---")
    process_directory(
        BASE_DIR / "invoices",
        parse_invoices,
        "invoices.csv",
        ["Source File", "Order ID", "Customer ID", "Order Date", "Contact Name", "Address", "City",
         "Postal Code", "Country", "Phone", "Fax", "Product ID", "Product Name", "Quantity", "Unit Price", "Total Price"]
    )
    
    # 3. Shipping orders
    print("\n--- Shipping Orders ---")
    process_directory(
        BASE_DIR / "Shipping orders",
        parse_shipping_orders,
        "shipping_orders.csv",
        ["Source File", "Order ID", "Ship Name", "Ship Address", "Ship City", "Ship Region", "Ship Postal Code",
         "Ship Country", "Customer ID", "Customer Name", "Employee Name", "Shipper ID", "Shipper Name",
         "Order Date", "Shipped Date", "Product Name", "Quantity", "Unit Price", "Product Total", "Total Price"]
    )
    
    # 4. Inventory Report - monthly
    print("\n--- Inventory Report (monthly) ---")
    process_directory(
        BASE_DIR / "Inventory Report" / "monthly" / "monthly",
        parse_stock_report_monthly,
        "inventory_monthly.csv",
        ["Source File", "Report Period", "Category", "Product Name", "Units Sold", "Units in Stock", "Unit Price"]
    )
    
    # 5. Inventory Report - monthly-Category
    print("\n--- Inventory Report (monthly-Category) ---")
    process_directory(
        BASE_DIR / "Inventory Report" / "monthly-Category" / "monthly-Category",
        parse_stock_report_category,
        "inventory_monthly_category.csv",
        ["Source File", "Report Period", "Category", "Category ID", "Product Name", "Units Sold", "Units in Stock", "Unit Price"]
    )
    
    print("\n" + "=" * 60)
    print("All done! CSV files generated in CompanyDocuments/")
    print("=" * 60)


if __name__ == "__main__":
    main()