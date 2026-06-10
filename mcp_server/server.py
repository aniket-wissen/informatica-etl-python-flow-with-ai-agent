import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastmcp import FastMCP
from loguru import logger
from src.db.engine import SessionLocal, init_db
from src.db.models import Transaction, FailedRecord, Account
from src.utils.schema_cache import get_cached_schema, load_cache
import pandas as pd

mcp = FastMCP("Financial ETL Pipeline Server")


@mcp.tool()
def run_pipeline(csv_path: str, db_engine: str = "postgresql") -> str:
    """
    Run the full ETL pipeline for a given CSV file.
    Triggers ingestion → schema → cleansing → enrichment → load → audit.
    Returns a summary of the pipeline run.
    """
    try:
        logger.info(f"[MCP] run_pipeline called — {csv_path}")

        if not os.path.exists(csv_path):
            return f"ERROR: File not found: {csv_path}"

        from src.agents.orchestrator import run_pipeline as _run
        final_state = _run(csv_path)

        if final_state.get("error"):
            return f"FAILED: {final_state['error']}"

        return (
            f"SUCCESS\n"
            f"Total rows    : {final_state.get('total_rows')}\n"
            f"Clean rows    : {final_state.get('clean_count')}\n"
            f"Failed rows   : {final_state.get('failed_count')}\n"
            f"Enriched rows : {final_state.get('enriched_count')}\n"
            f"Loaded rows   : {final_state.get('loaded_count')}\n"
            f"AI inferred   : {final_state.get('ai_inferred_count')}\n\n"
            f"Audit Summary:\n{final_state.get('audit_summary', 'N/A')}"
        )
    except Exception as e:
        logger.error(f"[MCP] run_pipeline error: {e}")
        return f"ERROR: {e}"


@mcp.tool()
def validate_csv(csv_path: str) -> str:
    """
    Validate a CSV file before running the pipeline.
    Checks file existence, headers, row count and schema cache status.
    Does NOT run the full pipeline.
    """
    try:
        logger.info(f"[MCP] validate_csv called — {csv_path}")

        if not os.path.exists(csv_path):
            return f"ERROR: File not found: {csv_path}"

        df = pd.read_csv(csv_path, dtype=str, nrows=5)
        headers = list(df.columns)
        total_rows = sum(1 for _ in open(csv_path)) - 1

        if total_rows == 0:
            return "ERROR: CSV file is empty"

        # Check schema cache
        cached = get_cached_schema(headers)
        if cached and not cached.get("partial_match"):
            cache_status = f"CACHE HIT — entity: {cached['entity_type']}"
        elif cached and cached.get("partial_match"):
            cache_status = f"PARTIAL MATCH — base entity: {cached['base_schema']['entity_type']}"
        else:
            cache_status = "CACHE MISS — AI schema detection will be triggered"

        return (
            f"VALID\n"
            f"File          : {os.path.basename(csv_path)}\n"
            f"Rows          : {total_rows}\n"
            f"Columns       : {len(headers)}\n"
            f"Headers       : {headers}\n"
            f"Schema Status : {cache_status}"
        )
    except Exception as e:
        logger.error(f"[MCP] validate_csv error: {e}")
        return f"ERROR: {e}"


@mcp.tool()
def get_pipeline_status() -> str:
    """
    Get current status of the pipeline — row counts per table.
    Shows transactions, accounts and failed records loaded in DB.
    """
    try:
        logger.info("[MCP] get_pipeline_status called")
        session = SessionLocal()

        txn_count      = session.query(Transaction).count()
        acc_count      = session.query(Account).count()
        failed_count   = session.query(FailedRecord).count()
        ai_count       = session.query(Transaction).filter(Transaction.ai_inferred == "Y").count()
        high_risk      = session.query(Transaction).filter(Transaction.risk_rating == "HIGH").count()

        session.close()

        return (
            f"PIPELINE STATUS\n"
            f"Transactions loaded : {txn_count}\n"
            f"Accounts loaded     : {acc_count}\n"
            f"Failed records      : {failed_count}\n"
            f"AI inferred rows    : {ai_count}\n"
            f"High risk rows      : {high_risk}"
        )
    except Exception as e:
        logger.error(f"[MCP] get_pipeline_status error: {e}")
        return f"ERROR: {e}"


@mcp.tool()
def query_failed_records(error_type: str = "") -> str:
    """
    Query failed_records table.
    Optionally filter by error_type keyword e.g. 'currency', 'amount', 'duplicate'.
    Returns all failed records if no filter provided.
    """
    try:
        logger.info(f"[MCP] query_failed_records called — filter: '{error_type}'")
        session = SessionLocal()

        query = session.query(FailedRecord)
        if error_type:
            query = query.filter(
                FailedRecord.error_reason.ilike(f"%{error_type}%")
            )

        records = query.all()
        session.close()

        if not records:
            return f"No failed records found{' for filter: ' + error_type if error_type else ''}"

        lines = [f"Found {len(records)} failed record(s):\n"]
        for r in records:
            lines.append(
                f"  [{r.row_identifier}] "
                f"field={r.error_field} "
                f"reason={r.error_reason} "
                f"file={r.source_file}"
            )

        return "\n".join(lines)
    except Exception as e:
        logger.error(f"[MCP] query_failed_records error: {e}")
        return f"ERROR: {e}"


@mcp.tool()
def discover_schema(csv_path: str) -> str:
    """
    Detect the entity type of a CSV file using schema cache or AI.
    Returns entity type, mandatory fields and enrichment key.
    Does NOT run the full pipeline.
    """
    try:
        logger.info(f"[MCP] discover_schema called — {csv_path}")

        if not os.path.exists(csv_path):
            return f"ERROR: File not found: {csv_path}"

        df = pd.read_csv(csv_path, dtype=str, nrows=1)
        headers = list(df.columns)

        cached = get_cached_schema(headers)

        if cached and not cached.get("partial_match"):
            return (
                f"SCHEMA DETECTED (from cache)\n"
                f"Entity type       : {cached['entity_type']}\n"
                f"Mandatory fields  : {cached['mandatory_fields']}\n"
                f"Enrichment key    : {cached['enrichment_key']}\n"
                f"Cache status      : HIT"
            )

        if cached and cached.get("partial_match"):
            base = cached["base_schema"]
            return (
                f"SCHEMA DETECTED (partial match)\n"
                f"Entity type       : {base['entity_type']}\n"
                f"New columns       : {cached['added']}\n"
                f"Missing columns   : {cached['removed']}\n"
                f"Cache status      : PARTIAL"
            )

        # Cache miss — call AI
        from src.agents.schema_agent import _ask_ai
        result = _ask_ai(headers)
        return (
            f"SCHEMA DETECTED (via AI)\n"
            f"Entity type       : {result['entity_type']}\n"
            f"Mandatory fields  : {result['mandatory_fields']}\n"
            f"Enrichment key    : {result['enrichment_key']}\n"
            f"Confidence        : {result.get('confidence')}\n"
            f"Cache status      : MISS — run full pipeline to cache"
        )

    except Exception as e:
        logger.error(f"[MCP] discover_schema error: {e}")
        return f"ERROR: {e}"


if __name__ == "__main__":
    init_db()
    print("Starting Financial ETL Pipeline MCP Server on http://127.0.0.1:8001")
    mcp.run(transport="http", host="127.0.0.1", port=8001)