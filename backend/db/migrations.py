from sqlalchemy import create_engine

from backend.db.models import Base


def create_tables(database_url: str) -> None:
    engine = create_engine(database_url)
    Base.metadata.create_all(engine)
    engine.dispose()
