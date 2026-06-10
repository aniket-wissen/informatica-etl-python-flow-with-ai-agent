from sqlalchemy import (
    Column, String, Date, Time, DateTime,
    Numeric, Integer, Text, CHAR, func
)
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class Account(Base):
    __tablename__ = "accounts"

    account_id       = Column(String(30),  primary_key=True)
    account_type     = Column(String(20))
    customer_id      = Column(String(30),  nullable=False)
    customer_name    = Column(String(100))
    customer_email   = Column(String(150))
    customer_phone   = Column(String(15))
    customer_segment = Column(String(30))
    customer_timezone= Column(String(50))
    risk_rating      = Column(String(20))
    credit_limit     = Column(Numeric(18, 2))
    effective_date   = Column(Date)
    is_active        = Column(CHAR(1), default="Y")
    load_timestamp   = Column(DateTime, server_default=func.now())


class Transaction(Base):
    __tablename__ = "transactions"

    transaction_id       = Column(String(50),  primary_key=True)
    transaction_date     = Column(Date)
    transaction_time     = Column(Time)
    amount               = Column(Numeric(18, 2))
    currency             = Column(CHAR(5))
    account_id           = Column(String(30))
    merchant_name        = Column(String(150))
    merchant_city        = Column(String(80))
    merchant_country     = Column(CHAR(3))
    channel              = Column(String(30))
    payment_method       = Column(String(30))
    transaction_type     = Column(String(10))
    status               = Column(String(10))
    notes                = Column(Text)
    # Enriched fields from accounts table
    account_type         = Column(String(20))
    customer_id          = Column(String(30))
    customer_name        = Column(String(100))
    customer_segment     = Column(String(30))
    risk_rating          = Column(String(20))
    # AI inference flags
    ai_inferred          = Column(CHAR(1), default="N")
    ai_confidence        = Column(String(10))
    load_timestamp       = Column(DateTime, server_default=func.now())


class FailedRecord(Base):
    __tablename__ = "failed_records"

    error_sk         = Column(Integer, primary_key=True, autoincrement=True)
    source_file      = Column(String(100))
    entity_type      = Column(String(30))
    row_identifier   = Column(String(50))
    error_type       = Column(String(50))
    error_field      = Column(String(60))
    error_reason     = Column(String(255))
    raw_record       = Column(Text)
    load_timestamp   = Column(DateTime, server_default=func.now())