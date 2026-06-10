import sys
from src.agents.orchestrator import run_pipeline
from src.db.engine import init_db, SessionLocal
from src.db.loader import _upsert_accounts
from loguru import logger
import pandas as pd
import os


def load_reference_data():
    """Load reference CSVs into DB at startup. Skips if already loaded."""
    ref_path = "reference_data/accounts_ref.csv"
    if not os.path.exists(ref_path):
        logger.warning("No accounts_ref.csv found — skipping reference load")
        return
    session = SessionLocal()
    try:
        df = pd.read_csv(ref_path, dtype=str)
        count = _upsert_accounts(df, session)
        session.commit()
        if count > 0:
            logger.info(f"✅ Reference data loaded: {count} accounts")
        else:
            logger.info("✅ Reference data already up to date")
    except Exception as e:
        session.rollback()
        logger.error(f"Reference data load failed: {e}")
    finally:
        session.close()


if __name__ == "__main__":
    # Initialize DB tables
    init_db()

    # Load reference data (accounts, etc.)
    load_reference_data()

    # Get CSV path from argument or use default
    csv_path = sys.argv[1] if len(sys.argv) > 1 else "data/input/transactions.csv"

    # Run pipeline
    final_state = run_pipeline(csv_path)

    # Exit with error code if pipeline failed
    if final_state.get("error"):
        print(f"\n❌ Pipeline failed: {final_state['error']}")
        sys.exit(1)
    else:
        print(f"\n✅ Pipeline completed successfully")