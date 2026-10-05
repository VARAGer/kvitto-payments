from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, Tariff

TARIFFS = (
    (1, "basic", 990000),
    (2, "standard", 1990000),
    (3, "premium", 2990000),
)


def setup_database(database_url: str):
    engine = create_engine(
        database_url,
        connect_args={"check_same_thread": False} if database_url.startswith("sqlite") else {},
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(engine, expire_on_commit=False)
    with session_factory() as session:
        for tariff_id, title, price in TARIFFS:
            if session.get(Tariff, tariff_id) is None:
                session.add(Tariff(id=tariff_id, title=title, price=price))
        session.commit()
    return engine, session_factory
