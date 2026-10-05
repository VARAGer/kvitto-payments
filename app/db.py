from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.models import Tariff

TARIFFS = (
    (1, "basic", 990000),
    (2, "standard", 1990000),
    (3, "premium", 2990000),
)


def create_db_engine(database_url: str):
    engine = create_engine(
        database_url,
        connect_args={"check_same_thread": False} if database_url.startswith("sqlite") else {},
    )
    if engine.dialect.name == "sqlite":
        @event.listens_for(engine, "connect")
        def enable_foreign_keys(connection, connection_record):
            cursor = connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


def setup_database(database_url: str):
    engine = create_db_engine(database_url)
    session_factory = sessionmaker(engine, expire_on_commit=False)
    with session_factory() as session:
        for tariff_id, title, price in TARIFFS:
            if session.get(Tariff, tariff_id) is None:
                session.add(Tariff(id=tariff_id, title=title, price=price))
        session.commit()
    return engine, session_factory
