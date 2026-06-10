import json
import pandas as pd
from loguru import logger
from groq import Groq
from config.settings import settings
from src.agents.state import ETLState
from prompts.enrichment_gaps import get_enrichment_gaps_prompt

client = Groq(api_key=settings.GROQ_API_KEY)


def _load_accounts_lookup() -> dict:
    """
    Load accounts reference data from DB into a dict
    keyed by account_id for fast lookup.
    """
    from src.db.engine import SessionLocal
    from src.db.models import Account

    session = SessionLocal()
    try:
        accounts = session.query(Account).all()
        lookup = {}
        for acc in accounts:
            lookup[acc.account_id] = {
                "account_type":      acc.account_type,
                "customer_id":       acc.customer_id,
                "customer_name":     acc.customer_name,
                "customer_segment":  acc.customer_segment,
                "risk_rating":       acc.risk_rating,
            }
        logger.info(f"  Loaded {len(lookup)} accounts into lookup")
        return lookup
    finally:
        session.close()


def _ai_fill_gaps(unmatched_rows: list[dict]) -> dict:
    """
    AI touchpoint 2 — one batch call for all unmatched account_ids.
    Returns dict keyed by account_id with inferred metadata.
    """
    logger.info(f"  Sending {len(unmatched_rows)} unmatched rows to AI as one batch...")
    prompt = get_enrichment_gaps_prompt(unmatched_rows)
    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}]
    )
    raw = response.choices[0].message.content.strip()
    raw = raw.replace("```json", "").replace("```", "").strip()
    results = json.loads(raw)

    # Key by account_id for easy lookup
    return {r["account_id"]: r for r in results}


def enrichment_agent(state: ETLState) -> ETLState:
    logger.info("🤖 EnrichmentAgent started")

    clean_df = state["clean_df"].copy()
    entity_type = state["entity_type"]

    # Only transactions need enrichment
    if entity_type != "transactions":
        logger.info("  Accounts entity — no enrichment needed")
        state["enriched_df"] = clean_df
        state["enriched_count"] = len(clean_df)
        return state

    # Step 1 — load accounts lookup from DB
    accounts_lookup = _load_accounts_lookup()

    if not accounts_lookup:
        logger.warning("  No accounts in DB yet — all rows will go to AI enrichment")

    enriched_rows = []
    unmatched = []

    # Step 2 — DB lookup for each transaction
    for _, row in clean_df.iterrows():
        account_id = str(row.get("account_id", "")).strip()
        match = accounts_lookup.get(account_id)

        if match:
            # Found in DB — attach metadata directly
            row = row.copy()
            row["account_type"]     = match["account_type"]
            row["customer_id"]      = match["customer_id"]
            row["customer_name"]    = match["customer_name"]
            row["customer_segment"] = match["customer_segment"]
            row["risk_rating"]      = match["risk_rating"]
            row["ai_inferred"]      = "N"
            row["ai_confidence"]    = None
            enriched_rows.append(row)
        else:
            # Not found — collect for AI batch
            unmatched.append(row.to_dict())

    logger.info(f"  DB matched: {len(enriched_rows)} rows")
    logger.info(f"  Unmatched (going to AI): {len(unmatched)} rows")

    # Step 3 — AI batch call for unmatched rows
    ai_inferred_count = 0
    if unmatched:
        try:
            ai_results = _ai_fill_gaps(unmatched)
            for row_dict in unmatched:
                account_id = str(row_dict.get("account_id", "")).strip()
                ai_match = ai_results.get(account_id, {})
                row = pd.Series(row_dict)
                row["account_type"]     = ai_match.get("account_type", "UNKNOWN")
                row["customer_id"]      = "AI_INFERRED"
                row["customer_name"]    = ai_match.get("customer_name", "UNKNOWN")
                row["customer_segment"] = ai_match.get("customer_segment", "UNKNOWN")
                row["risk_rating"]      = ai_match.get("risk_rating", "UNKNOWN")
                row["ai_inferred"]      = "Y"
                row["ai_confidence"]    = ai_match.get("ai_confidence", "low")
                enriched_rows.append(row)
                ai_inferred_count += 1
                logger.info(f"  🤖 AI enriched [{account_id}]: "
                           f"segment={row['customer_segment']}, "
                           f"risk={row['risk_rating']} "
                           f"(confidence={row['ai_confidence']})")
        except Exception as e:
            logger.error(f"  AI enrichment failed: {e}")
            # Add unmatched rows without enrichment rather than losing them
            for row_dict in unmatched:
                row = pd.Series(row_dict)
                row["account_type"]     = "UNKNOWN"
                row["customer_id"]      = "UNKNOWN"
                row["customer_name"]    = "UNKNOWN"
                row["customer_segment"] = "UNKNOWN"
                row["risk_rating"]      = "UNKNOWN"
                row["ai_inferred"]      = "Y"
                row["ai_confidence"]    = "failed"
                enriched_rows.append(row)

    enriched_df = pd.DataFrame(enriched_rows)
    state["enriched_df"]       = enriched_df
    state["enriched_count"]    = len(enriched_df)
    state["ai_inferred_count"] = ai_inferred_count

    logger.success(f"✅ EnrichmentAgent done — "
                  f"{len(enriched_df)} rows enriched, "
                  f"{ai_inferred_count} AI inferred")
    return state