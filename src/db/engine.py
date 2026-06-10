from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from src.db.models import Base
from config.settings import settings
from loguru import logger


def get_engine():
    db_url = settings.database_url
    logger.info(f"Connecting to: {settings.DB_ENGINE}")

    if settings.DB_ENGINE.lower() == "sqlite":
        engine = create_engine(
            db_url,
            connect_args={"check_same_thread": False},
            echo=False
        )
        @event.listens_for(engine, "connect")
        def set_sqlite_pragma(conn, _):
            conn.execute("PRAGMA foreign_keys=ON")
        return engine

    return create_engine(db_url, echo=False)


engine       = get_engine()
SessionLocal = sessionmaker(bind=engine)


def init_db():
    Base.metadata.create_all(bind=engine)
    logger.info(f"✅ Tables created on {settings.DB_ENGINE}")