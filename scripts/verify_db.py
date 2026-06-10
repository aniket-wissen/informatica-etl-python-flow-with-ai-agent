import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.db.engine import SessionLocal
from src.db.models import Transaction, Account, FailedRecord
from config.settings import settings
from loguru import logger


def verify_db():
    print("\n" + "═" * 55)
    print("  FINANCIAL ETL — DATABASE VERIFICATION REPORT")
    print("═" * 55)
    print(f"  DB Engine : {settings.DB_ENGINE}")
    print(f"  DB Name   : {settings.DB_NAME}")
    print("═" * 55)

    session = SessionLocal()

    try:
        # ── Transactions ──────────────────────────────────────
        txn_total    = session.query(Transaction).count()
        txn_ai       = session.query(Transaction).filter(Transaction.ai_inferred == "Y").count()
        txn_db       = session.query(Transaction).filter(Transaction.ai_inferred == "N").count()
        txn_high     = session.query(Transaction).filter(Transaction.risk_rating == "HIGH").count()
        txn_medium   = session.query(Transaction).filter(Transaction.risk_rating == "MEDIUM").count()
        txn_low      = session.query(Transaction).filter(Transaction.risk_rating == "LOW").count()

        print(f"\n  📊 TRANSACTIONS TABLE")
        print(f"  {'─'*45}")
        print(f"  Total loaded        : {txn_total}")
        print(f"  DB matched          : {txn_db}")
        print(f"  AI inferred         : {txn_ai}")
        print(f"  High risk           : {txn_high}")
        print(f"  Medium risk         : {txn_medium}")
        print(f"  Low risk            : {txn_low}")

        # Sample rows
        sample = session.query(Transaction).limit(3).all()
        print(f"\n  Sample rows:")
        for t in sample:
            print(f"    [{t.transaction_id}] "
                  f"acc={t.account_id} "
                  f"amt={t.amount} "
                  f"risk={t.risk_rating} "
                  f"ai={t.ai_inferred}")

        # ── Accounts ──────────────────────────────────────────
        acc_total    = session.query(Account).count()
        acc_active   = session.query(Account).filter(Account.is_active == "Y").count()

        print(f"\n  👤 ACCOUNTS TABLE")
        print(f"  {'─'*45}")
        print(f"  Total loaded        : {acc_total}")
        print(f"  Active accounts     : {acc_active}")

        # Sample rows
        sample = session.query(Account).limit(3).all()
        print(f"\n  Sample rows:")
        for a in sample:
            print(f"    [{a.account_id}] "
                  f"name={a.customer_name} "
                  f"segment={a.customer_segment} "
                  f"risk={a.risk_rating}")

        # ── Failed Records ────────────────────────────────────
        fail_total   = session.query(FailedRecord).count()

        print(f"\n  ❌ FAILED RECORDS TABLE")
        print(f"  {'─'*45}")
        print(f"  Total failed        : {fail_total}")

        # Group by error reason
        failed = session.query(FailedRecord).all()
        reasons = {}
        for r in failed:
            reasons[r.error_reason] = reasons.get(r.error_reason, 0) + 1

        print(f"\n  Breakdown by reason:")
        for reason, count in reasons.items():
            print(f"    {count}x  {reason}")

        # ── Summary ───────────────────────────────────────────
        total_processed = txn_total + fail_total
        success_rate = round((txn_total / total_processed) * 100, 1) if total_processed > 0 else 0

        print(f"\n  {'═'*45}")
        print(f"  SUMMARY")
        print(f"  {'─'*45}")
        print(f"  Total processed     : {total_processed}")
        print(f"  Successfully loaded : {txn_total}")
        print(f"  Failed              : {fail_total}")
        print(f"  Success rate        : {success_rate}%")
        print(f"{'═'*55}\n")

    except Exception as e:
        logger.error(f"Verification failed: {e}")
    finally:
        session.close()


if __name__ == "__main__":
    verify_db()