from loguru import logger
from groq import Groq
from config.settings import settings
from src.agents.state import ETLState
from prompts.audit import get_audit_prompt

client = Groq(api_key=settings.GROQ_API_KEY)


def audit_agent(state: ETLState) -> ETLState:
    """
    AI touchpoint 3 — one Groq call per run.
    Summarizes the pipeline run with a data quality score.
    """
    logger.info("🤖 AuditAgent started — analyzing with Groq")

    # Build failed reasons summary
    failed_df = state.get("failed_df")
    failed_reasons = []
    if failed_df is not None and len(failed_df) > 0:
        failed_reasons = failed_df.groupby("error_reason")["row_identifier"].apply(list).to_dict()

    # Build AI inferred accounts summary
    enriched_df = state.get("enriched_df")
    ai_inferred_accounts = []
    if enriched_df is not None and len(enriched_df) > 0:
        ai_rows = enriched_df[enriched_df.get("ai_inferred", "N") == "Y"] if "ai_inferred" in enriched_df.columns else []
        if len(ai_rows) > 0:
            ai_inferred_accounts = ai_rows["account_id"].tolist()

    stats = {
        "total_rows":          state.get("total_rows", 0),
        "clean_rows":          state.get("clean_count", 0),
        "failed_rows":         state.get("failed_count", 0),
        "enriched_rows":       state.get("enriched_count", 0),
        "loaded_rows":         state.get("loaded_count", 0),
        "ai_inferred":         state.get("ai_inferred_count", 0),
        "failed_reasons":      failed_reasons,
        "ai_inferred_accounts": ai_inferred_accounts
    }

    try:
        prompt = get_audit_prompt(stats)
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}]
        )
        summary = response.choices[0].message.content.strip()
        state["audit_summary"] = summary
        logger.success("✅ AuditAgent done")
        logger.info(f"\n{'═'*50}\n{summary}\n{'═'*50}")

    except Exception as e:
        state["audit_summary"] = f"Audit failed: {e}"
        logger.error(f"AuditAgent failed: {e}")

    return state