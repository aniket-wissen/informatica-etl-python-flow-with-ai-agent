import pandas as pd
from loguru import logger
from src.agents.state import ETLState

VALID_CURRENCIES = {"INR", "USD", "EUR", "GBP", "AED", "SGD", "JPY"}
VALID_STATUSES = {"SUCCESS", "FAILED", "PENDING"}
VALID_CHANNELS = {"UPI", "APP", "POS", "NET", "ATM"}
VALID_PAYMENT_METHODS = {"UPI", "CARD", "NEFT", "RTGS", "IMPS", "CASH", "WALLET"}
VALID_TRANSACTION_TYPES = {"DEBIT", "CREDIT"}


def _flag_failed(row: pd.Series, reason: str, field: str, source_file: str, entity_type: str) -> dict:
    """Build a failed_record dict from a bad row."""
    return {
        "source_file": source_file,
        "entity_type": entity_type,
        "row_identifier": row.get("transaction_id") or row.get("account_id") or "UNKNOWN",
        "error_type": "VALIDATION_FAILED",
        "error_field": field,
        "error_reason": reason,
        "raw_record": str(row.to_dict())
    }


def _cleanse_transactions(df: pd.DataFrame, source_file: str) -> tuple[pd.DataFrame, list[dict]]:
    """Apply transaction-specific validation rules."""
    clean_rows = []
    failed_rows = []
    seen_ids = set()

    for _, row in df.iterrows():
        errors = []

        # Duplicate transaction_id
        txn_id = str(row.get("transaction_id", "")).strip()
        if not txn_id:
            errors.append(("transaction_id", "Missing transaction_id"))
        elif txn_id in seen_ids:
            errors.append(("transaction_id", f"Duplicate transaction_id: {txn_id}"))
        else:
            seen_ids.add(txn_id)

        # Null or invalid amount
        raw_amount = row.get("amount")
        if raw_amount is None or str(raw_amount).strip() == "" or str(raw_amount).strip().lower() == "nan":
            errors.append(("amount", "Missing amount"))
        else:
            try:
                amount = float(raw_amount)
                if amount <= 0:
                    errors.append(("amount", f"Amount must be positive, got: {amount}"))
            except (ValueError, TypeError):
                errors.append(("amount", f"Invalid amount: {raw_amount}"))

        # Invalid currency
        currency = str(row.get("currency", "")).strip().upper()
        if currency not in VALID_CURRENCIES:
            errors.append(("currency", f"Invalid currency: {currency}"))

        # Missing account_id
        account_id = str(row.get("account_id", "")).strip()
        if not account_id:
            errors.append(("account_id", "Missing account_id"))

        # Invalid status
        status = str(row.get("status", "")).strip().upper()
        if status not in VALID_STATUSES:
            errors.append(("status", f"Invalid status: {status}"))

        # FAILED status rows go to failed_records
        if status == "FAILED":
            errors.append(("status", "Transaction status is FAILED"))

        # Invalid channel
        channel = str(row.get("channel", "")).strip().upper()
        if channel not in VALID_CHANNELS:
            errors.append(("channel", f"Invalid channel: {channel}"))

        if errors:
            for field, reason in errors:
                failed_rows.append(_flag_failed(row, reason, field, source_file, "transactions"))
        else:
            clean_rows.append(row)

    clean_df = pd.DataFrame(clean_rows) if clean_rows else pd.DataFrame(columns=df.columns)
    return clean_df, failed_rows


def _cleanse_accounts(df: pd.DataFrame, source_file: str) -> tuple[pd.DataFrame, list[dict]]:
    """Apply accounts-specific validation rules."""
    clean_rows = []
    failed_rows = []

    for _, row in df.iterrows():
        errors = []

        if not str(row.get("account_id", "")).strip():
            errors.append(("account_id", "Missing account_id"))

        if not str(row.get("customer_id", "")).strip():
            errors.append(("customer_id", "Missing customer_id"))

        email = str(row.get("customer_email", "")).strip()
        if email and "@" not in email:
            errors.append(("customer_email", f"Invalid email: {email}"))

        if errors:
            for field, reason in errors:
                failed_rows.append(_flag_failed(row, reason, field, source_file, "accounts"))
        else:
            clean_rows.append(row)

    clean_df = pd.DataFrame(clean_rows) if clean_rows else pd.DataFrame(columns=df.columns)
    return clean_df, failed_rows

def _cleanse_generic(df: pd.DataFrame, source_file: str, entity_type: str) -> tuple[pd.DataFrame, list[dict]]:
    """
    Generic cleansing for unknown entity types.
    Applies basic rules — no nulls in first column, no fully empty rows.
    """
    clean_rows  = []
    failed_rows = []

    # First column is assumed to be the primary key
    pk_column = df.columns[0] if len(df.columns) > 0 else None

    for _, row in df.iterrows():
        errors = []

        # Check primary key not null
        if pk_column:
            pk_val = str(row.get(pk_column, "")).strip()
            if not pk_val or pk_val.lower() == "nan":
                errors.append((pk_column, f"Missing primary key: {pk_column}"))

        # Check row is not completely empty
        non_null = sum(1 for v in row if str(v).strip() and str(v).strip().lower() != "nan")
        if non_null == 0:
            errors.append(("row", "Completely empty row"))

        if errors:
            for field, reason in errors:
                failed_rows.append({
                    "source_file":    source_file,
                    "entity_type":    entity_type,
                    "row_identifier": str(row.get(pk_column, "UNKNOWN")),
                    "error_type":     "VALIDATION_FAILED",
                    "error_field":    field,
                    "error_reason":   reason,
                    "raw_record":     str(row.to_dict())
                })
        else:
            clean_rows.append(row)

    clean_df = pd.DataFrame(clean_rows) if clean_rows else pd.DataFrame(columns=df.columns)
    return clean_df, failed_rows

def _cleanse_dynamic(df: pd.DataFrame, entity_type: str, source_file: str) -> tuple[pd.DataFrame, list[dict]]:
    """Dynamic cleansing using rules from schema registry."""
    from src.utils.schema_registry import get_entity
    import pycountry
    from email_validator import validate_email, EmailNotValidError

    schema = get_entity(entity_type)
    if not schema:
        logger.warning(f"  No schema found for '{entity_type}' — skipping cleansing")
        return df, []

    rules      = schema.get("cleansing_rules", {})
    clean_rows = []
    failed_rows = []
    seen_ids   = {}

    logger.info(f"  Applying {len(rules)} dynamic rules for '{entity_type}'")

    for _, row in df.iterrows():
        errors = []

        for field, rule in rules.items():
            val     = row.get(field)
            val_str = str(val).strip() if val is not None else ""
            rule_type = rule.get("type", "")

            # mandatory
            if rule_type == "mandatory" or rule.get("unique"):
                if not val_str or val_str.lower() in ("nan", "none", ""):
                    errors.append((field, f"Missing {field}"))
                    continue

            # unique
            if rule.get("unique"):
                if val_str in seen_ids.get(field, set()):
                    errors.append((field, f"Duplicate {field}: {val_str}"))
                    continue
                seen_ids.setdefault(field, set()).add(val_str)

            # positive_number
            if rule_type == "positive_number":
                try:
                    if float(val_str) <= 0:
                        errors.append((field, f"{field} must be positive"))
                except (ValueError, TypeError):
                    errors.append((field, f"Invalid number for {field}: {val_str}"))

            # date
            if rule_type == "date":
                try:
                    pd.to_datetime(val_str)
                except Exception:
                    errors.append((field, f"Invalid date for {field}: {val_str}"))

            # email
            if rule_type == "email" and val_str:
                try:
                    validate_email(val_str, check_deliverability=False)
                except EmailNotValidError:
                    errors.append((field, f"Invalid email: {val_str}"))

            # enum
            if rule_type == "enum":
                allowed = [v.upper() for v in rule.get("values", [])]
                if allowed and val_str.upper() not in allowed:
                    errors.append((field, f"Invalid {field}: {val_str}. Allowed: {allowed}"))

        if errors:
            for field, reason in errors:
                failed_rows.append(_flag_failed(row, reason, field, source_file, entity_type))
        else:
            clean_rows.append(row)

    clean_df = pd.DataFrame(clean_rows) if clean_rows else pd.DataFrame(columns=df.columns)
    return clean_df, failed_rows

def cleansing_agent(state: ETLState) -> ETLState:
    logger.info("🤖 CleansingAgent started")

    df = state["raw_df"]
    entity_type = state["entity_type"]
    source_file = state["csv_path"].split("/")[-1].split("\\")[-1]

    if entity_type == "transactions":
        clean_df, failed_rows = _cleanse_transactions(df, source_file)
    elif entity_type == "accounts":
        clean_df, failed_rows = _cleanse_accounts(df, source_file)
    else:
        logger.info(f"  Using dynamic cleansing for '{entity_type}'")
        clean_df, failed_rows = _cleanse_dynamic(df, entity_type, source_file)

    failed_df = pd.DataFrame(failed_rows) if failed_rows else pd.DataFrame()

    state["clean_df"] = clean_df
    state["failed_df"] = failed_df
    state["clean_count"] = len(clean_df)
    state["failed_count"] = len(failed_rows)

    logger.success(f"✅ CleansingAgent done — clean={len(clean_df)}, failed={len(failed_rows)}")
    return state