from pathlib import Path

from sqlalchemy import create_engine, inspect

from backend.db.migrations import create_tables


def test_create_tables(tmp_path: Path):
    db_url = f"sqlite:///{tmp_path / 'test.db'}"
    create_tables(db_url)
    engine = create_engine(db_url)
    inspector = inspect(engine)
    tables = inspector.get_table_names()
    assert "products" in tables
    assert "purchase_orders" in tables
    assert "shipping_orders" in tables
    assert "invoices" in tables
    engine.dispose()


def test_create_tables_idempotent(tmp_path: Path):
    db_url = f"sqlite:///{tmp_path / 'test2.db'}"
    create_tables(db_url)
    create_tables(db_url)
    engine = create_engine(db_url)
    inspector = inspect(engine)
    tables = inspector.get_table_names()
    assert len(tables) == 4
    engine.dispose()
