from collections.abc import Generator

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings


class Base(DeclarativeBase):
    pass


connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


@event.listens_for(engine, "connect")
def configure_sqlite(dbapi_connection, _connection_record):
    if settings.database_url.startswith("sqlite"):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")


def init_db() -> None:
    from . import models  # noqa: F401

    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(text("""
            CREATE VIRTUAL TABLE IF NOT EXISTS evidence_fts
            USING fts5(evidence_id UNINDEXED, content, source_path)
        """))


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
