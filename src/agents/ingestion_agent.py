import pandas as pd
from loguru import logger
from src.agents.state import ETLState


def ingestion_agent(state: ETLState) -> ETLState:
    logger.info("🤖 IngestionAgent started")
    try:
        csv_path = state["csv_path"]
        df = pd.read_csv(csv_path, dtype=str)
        logger.info(f"  Read {len(df)} rows, {len(df.columns)} columns")
        logger.info(f"  Headers: {list(df.columns)}")
        state["raw_df"]      = df
        state["headers"]     = list(df.columns)
        state["total_rows"]  = len(df)
    except Exception as e:
        state["error"] = f"IngestionAgent failed: {e}"
        logger.error(state["error"])
    return state