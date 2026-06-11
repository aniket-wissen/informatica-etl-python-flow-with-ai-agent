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
    
def alter_table_for_new_columns(table_name: str, new_columns: list[str]):
    """
    Dynamically add new columns to an existing table.
    Called when schema agent detects and approves new columns.
    """
    from sqlalchemy import text
    with engine.connect() as conn:
        for col in new_columns:
            try:
                conn.execute(text(f'ALTER TABLE {table_name} ADD COLUMN IF NOT EXISTS "{col}" TEXT'))
                conn.commit()
                logger.info(f"✅ Added column '{col}' to {table_name}")
            except Exception as e:
                logger.warning(f"  Could not add column '{col}': {e}")
                
def create_table_from_df(table_name: str, df) -> bool:
    """
    Dynamically create a new table based on DataFrame columns.
    Infers column types from pandas dtypes.
    Adds standard audit columns: load_timestamp, source_file, run_id.
    """
    from sqlalchemy import Column, String, Numeric, Date, DateTime, Text, MetaData, Table, inspect
    from sqlalchemy.sql import func
    import pandas as pd

    inspector = inspect(engine)
    if inspector.has_table(table_name):
        logger.info(f"  Table '{table_name}' already exists — skipping create")
        return True

    def _infer_type(col_name: str, series):
        """Infer SQLAlchemy type from pandas series."""
        col_lower = col_name.lower()
        if any(k in col_lower for k in ["date", "time", "timestamp"]):
            return DateTime
        if any(k in col_lower for k in ["amount", "value", "price", "cost", "balance", "limit", "points"]):
            return Numeric(18, 2)
        if col_lower.endswith("_id") or col_lower in ["id", "status", "type", "code", "currency"]:
            return String(50)
        dtype = str(series.dtype)
        if "int" in dtype:
            return Numeric(18, 0)
        if "float" in dtype:
            return Numeric(18, 4)
        return Text

    metadata = MetaData()
    columns = [
        Column("_row_id", String(50), primary_key=True, default=lambda: str(__import__('uuid').uuid4()))
    ]

    for col in df.columns:
        col_type = _infer_type(col, df[col])
        columns.append(Column(col, col_type, nullable=True))

    # Standard audit columns — same for all dynamic entities
    columns.extend([
        Column("ai_inferred",    String(1),   nullable=True, default="N"),
        Column("ai_confidence",  String(20),  nullable=True),
        Column("load_timestamp", DateTime,    server_default=func.now()),
        Column("source_file",    String(200), nullable=True),
        Column("run_id",         String(50),  nullable=True),
    ])

    table = Table(table_name, metadata, *columns)

    try:
        metadata.create_all(bind=engine)
        logger.success(f"✅ Table '{table_name}' created with {len(df.columns)} columns")
        return True
    except Exception as e:
        logger.error(f"  Failed to create table '{table_name}': {e}")
        return False