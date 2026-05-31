from sqlalchemy import Column, Integer, String, Float, DateTime, func
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, autoincrement=True)
    product_name = Column(String(255), nullable=False, index=True)
    category = Column(String(255), default="Uncategorized")
    unit_price = Column(Float, default=0.0)
    units_in_stock = Column(Integer, default=0)
    units_sold = Column(Integer, default=0)
    report_period = Column(String(50))
    source_file = Column(String(255))
    ingested_at = Column(DateTime, server_default=func.current_timestamp())


class PurchaseOrder(Base):
    __tablename__ = "purchase_orders"

    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(String(255), nullable=False, index=True)
    order_date = Column(String(50))
    customer_name = Column(String(255), default="Unknown Vendor")
    product_id = Column(String(255), default="N/A")
    product_name = Column(String(255), nullable=False)
    quantity = Column(Integer, default=0)
    unit_price = Column(Float, default=0.0)
    source_file = Column(String(255))
    ingested_at = Column(DateTime, server_default=func.current_timestamp())


class ShippingOrder(Base):
    __tablename__ = "shipping_orders"

    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(String(255), nullable=False, index=True)
    ship_name = Column(String(255), default="")
    ship_address = Column(String(500), default="")
    ship_city = Column(String(255), default="")
    ship_region = Column(String(255), default="")
    ship_postal_code = Column(String(50), default="")
    ship_country = Column(String(255), default="")
    customer_id = Column(String(255), default="")
    customer_name = Column(String(255), default="")
    employee_name = Column(String(255), default="")
    shipper_id = Column(String(255), default="")
    shipper_name = Column(String(255), default="Unknown")
    order_date = Column(String(50))
    shipped_date = Column(String(50), default="")
    product_name = Column(String(255), nullable=False)
    quantity = Column(Integer, default=0)
    unit_price = Column(Float, default=0.0)
    product_total = Column(Float, default=0.0)
    total_price = Column(Float, default=0.0)
    source_file = Column(String(255))
    ingested_at = Column(DateTime, server_default=func.current_timestamp())


class Invoice(Base):
    __tablename__ = "invoices"

    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(String(255), nullable=False, index=True)
    customer_id = Column(String(255), default="")
    order_date = Column(String(50))
    contact_name = Column(String(255), default="")
    address = Column(String(500), default="")
    city = Column(String(255), default="")
    postal_code = Column(String(50), default="")
    country = Column(String(255), default="")
    phone = Column(String(100), default="")
    fax = Column(String(100), default="")
    product_id = Column(String(255), default="")
    product_name = Column(String(255), nullable=False)
    quantity = Column(Integer, default=0)
    unit_price = Column(Float, default=0.0)
    total_price = Column(Float, default=0.0)
    source_file = Column(String(255))
    ingested_at = Column(DateTime, server_default=func.current_timestamp())
