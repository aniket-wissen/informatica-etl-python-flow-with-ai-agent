import pandas as pd
from loguru import logger
from sqlalchemy import text
from src.db.engine import SessionLocal, engine
from src.db.models import Transaction, Account, FailedRecord
from src.agents.state import ETLState
from datetime import datetime, time as dt_time, date as dt_date

def _upsert_accounts(df: pd.DataFrame, session):
    """Load accounts — skip if already exists (DB agnostic)."""
    count = 0
    for _, row in df.iterrows():
        try:
            exists = session.query(Account).filter_by(
                account_id=row.get("account_id")
            ).first()
            if not exists:
                session.add(Account(
                    account_id=row.get("account_id"),
                    account_type=row.get("account_type"),
                    customer_id=row.get("customer_id"),
                    customer_name=row.get("customer_name"),
                    customer_email=row.get("customer_email"),
                    customer_phone=row.get("customer_phone"),
                    customer_segment=row.get("customer_segment"),
                    customer_timezone=row.get("customer_timezone"),
                    risk_rating=row.get("risk_rating"),
                    credit_limit=float(row["credit_limit"]) if pd.notna(row.get("credit_limit")) else None,
                    effective_date=_parse_date(row.get("effective_date")),
                    is_active=row.get("is_active", "Y"),
                ))
            else:
                exists.account_type     = row.get("account_type")
                exists.customer_name    = row.get("customer_name")
                exists.customer_segment = row.get("customer_segment")
                exists.risk_rating      = row.get("risk_rating")
            count += 1
        except Exception as e:
            logger.error(f"  Failed to upsert account {row.get('account_id')}: {e}")
    return count

def _parse_time(val) -> dt_time | None:
    """Dynamically convert any time-like value to Python time object."""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    if isinstance(val, dt_time):
        return val
    val_str = str(val).strip()
    if not val_str or val_str.lower() == "nan":
        return None
    for fmt in ("%H:%M:%S", "%H:%M", "%I:%M %p", "%I:%M:%S %p"):
        try:
            return datetime.strptime(val_str, fmt).time()
        except ValueError:
            continue
    return None


def _parse_date(val) -> dt_date | None:
    """Dynamically convert any date-like value to Python date object."""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    if isinstance(val, dt_date):
        return val
    try:
        return pd.to_datetime(str(val), errors="coerce").date()
    except Exception:
        return None

def _insert_transactions(df: pd.DataFrame, session):
    """Insert transactions — handles both fixed and dynamic new columns."""
    count = 0
    skipped = 0

    # Fixed columns that map to the Transaction model
    FIXED_COLUMNS = {
        "transaction_id", "date", "time", "amount", "currency",
        "account_id", "merchant_name", "merchant_city", "merchant_country",
        "channel", "payment_method", "transaction_type", "status", "notes",
        "account_type", "customer_id", "customer_name", "customer_segment",
        "risk_rating", "ai_inferred", "ai_confidence"
    }

    # Detect dynamic new columns not in the fixed model
    dynamic_columns = [col for col in df.columns if col.lower() not in FIXED_COLUMNS]
    if dynamic_columns:
        logger.info(f"  Dynamic columns detected: {dynamic_columns}")

    for _, row in df.iterrows():
        try:
            txn_id = str(row.get("transaction_id", "")).strip()
            if not txn_id:
                continue

            exists = session.query(Transaction).filter_by(
                transaction_id=txn_id
            ).first()
            if exists:
                skipped += 1
                continue

            # Insert fixed columns via model
            txn = Transaction(
                transaction_id=txn_id,
                transaction_date=_parse_date(row.get("date")),
                transaction_time=_parse_time(row.get("time")),
                amount=float(row.get("amount")) if pd.notna(row.get("amount", None)) else None,
                currency=str(row.get("currency", "")).strip() or None,
                account_id=str(row.get("account_id", "")).strip() or None,
                merchant_name=str(row.get("merchant_name", "")).strip() or None,
                merchant_city=str(row.get("merchant_city", "")).strip() or None,
                merchant_country=str(row.get("merchant_country", "")).strip() or None,
                channel=str(row.get("channel", "")).strip() or None,
                payment_method=str(row.get("payment_method", "")).strip() or None,
                transaction_type=str(row.get("transaction_type", "")).strip() or None,
                status=str(row.get("status", "")).strip() or None,
                notes=str(row.get("notes", "")).strip() or None,
                account_type=str(row.get("account_type", "")).strip() or None,
                customer_id=str(row.get("customer_id", "")).strip() or None,
                customer_name=str(row.get("customer_name", "")).strip() or None,
                customer_segment=str(row.get("customer_segment", "")).strip() or None,
                risk_rating=str(row.get("risk_rating", "")).strip() or None,
                ai_inferred=str(row.get("ai_inferred", "N")).strip(),
                ai_confidence=str(row.get("ai_confidence", "")).strip() or None,
            )
            session.add(txn)
            session.flush()  # flush so the row exists before UPDATE

            # Now UPDATE dynamic columns directly via raw SQL
            if dynamic_columns:
                updates = {}
                for col in dynamic_columns:
                    val = row.get(col)
                    updates[col] = str(val).strip() if pd.notna(val) else None

                set_clause = ", ".join([f'"{col}" = :{col}' for col in updates])
                params = {"txn_id": txn_id, **updates}
                session.execute(
                    text(f'UPDATE transactions SET {set_clause} WHERE transaction_id = :txn_id'),
                    params
                )

            count += 1

        except Exception as e:
            session.rollback()
            logger.error(f"  Failed to insert transaction {row.get('transaction_id')}: {e}")

    if skipped:
        logger.info(f"  Skipped {skipped} duplicate transactions")
    return count


def _insert_failed_records(df: pd.DataFrame, session):
    """Insert all failed/rejected rows."""
    count = 0
    for _, row in df.iterrows():
        try:
            record = FailedRecord(
                source_file=str(row.get("source_file", "")),
                entity_type=str(row.get("entity_type", "")),
                row_identifier=str(row.get("row_identifier", "")),
                error_type=str(row.get("error_type", "")),
                error_field=str(row.get("error_field", "")),
                error_reason=str(row.get("error_reason", "")),
                raw_record=str(row.get("raw_record", "")),
            )
            session.add(record)
            count += 1
        except Exception as e:
            logger.error(f"  Failed to insert failed record: {e}")
    return count


def loader_agent(state: ETLState) -> ETLState:
    logger.info("🤖 LoaderAgent started")

    session = SessionLocal()
    try:
        entity_type  = state["entity_type"]
        loaded_count = 0
        source_file  = state["csv_path"].split("/")[-1].split("\\")[-1]

        if entity_type == "transactions":
            enriched_df = state.get("enriched_df")
            if enriched_df is not None and len(enriched_df) > 0:
                loaded_count = _insert_transactions(enriched_df, session)
                logger.success(f"  Transactions inserted: {loaded_count}")

        elif entity_type == "accounts":
            clean_df = state.get("clean_df")
            if clean_df is not None and len(clean_df) > 0:
                loaded_count = _upsert_accounts(clean_df, session)
                logger.success(f"  Accounts upserted: {loaded_count}")

        else:
            if state.get("skip_load"):
                logger.info(f"  '{entity_type}' registered only — skipping load this run")
            else:
                logger.info(f"  Unknown entity '{entity_type}' — using generic loader")
                target_df = state.get("enriched_df")
                if target_df is None or target_df.empty:
                    target_df = state.get("clean_df")
                if target_df is not None and len(target_df) > 0:
                    loaded_count = _generic_loader(entity_type, target_df, source_file)

        # Load failed records
        failed_df    = state.get("failed_df")
        failed_count = 0
        if failed_df is not None and len(failed_df) > 0:
            failed_count = _insert_failed_records(failed_df, session)
            logger.success(f"  Failed records inserted: {failed_count}")

        session.commit()
        state["loaded_count"] = loaded_count
        logger.success(f"✅ LoaderAgent done — loaded={loaded_count}, failed={failed_count}")

    except Exception as e:
        session.rollback()
        state["error"] = f"LoaderAgent failed: {e}"
        logger.error(state["error"])
    finally:
        session.close()

    return state

def _generic_loader(table_name: str, df: pd.DataFrame, source_file: str) -> int:
    """
    Load any DataFrame into any table dynamically.
    Used for new entity types discovered at runtime.
    """
    import uuid
    count = 0

    # Add audit columns
    df = df.copy()
    df["source_file"] = source_file
    df["run_id"]      = str(uuid.uuid4())[:8]

    # Generate _row_id for each row
    df["_row_id"] = [str(uuid.uuid4()) for _ in range(len(df))]
    
    # Sanitize table name — replace hyphens and spaces with underscores
    table_name = table_name.replace("-", "_").replace(" ", "_").lower()
    
    try:
        df.to_sql(
            name=table_name,
            con=engine,
            if_exists="append",
            index=False,
            method="multi"
        )
        count = len(df)
        logger.success(f"  Generic loader — {count} rows loaded into '{table_name}'")
    except Exception as e:
        logger.error(f"  Generic loader failed for '{table_name}': {e}")
        # Fallback — row by row
        for _, row in df.iterrows():
            try:
                pd.DataFrame([row]).to_sql(
                    name=table_name,
                    con=engine,
                    if_exists="append",
                    index=False
                )
                count += 1
            except Exception as row_err:
                logger.error(f"  Row failed: {row_err}")

    return count