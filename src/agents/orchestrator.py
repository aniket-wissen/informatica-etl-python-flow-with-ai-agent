from langgraph.graph import StateGraph, END
from loguru import logger
from src.agents.state import ETLState
from src.agents.ingestion_agent import ingestion_agent
from src.agents.schema_agent import schema_agent
from src.agents.cleansing_agent import cleansing_agent
from src.agents.enrichment_agent import enrichment_agent
from src.db.loader import loader_agent
from src.agents.audit_agent import audit_agent


def should_continue_after_ingestion(state: ETLState) -> str:
    """Stop pipeline if ingestion failed."""
    if state.get("error"):
        logger.error(f"Pipeline stopping after ingestion: {state['error']}")
        return "end"
    return "schema"


def should_continue_after_schema(state: ETLState) -> str:
    """Stop pipeline if schema detection failed or rejected."""
    if state.get("error"):
        logger.error(f"Pipeline stopping after schema: {state['error']}")
        return "end"
    if not state.get("entity_type"):
        logger.error("No entity type detected — stopping pipeline")
        return "end"
    return "cleansing"


def should_continue_after_cleansing(state: ETLState) -> str:
    """Stop pipeline if all rows failed cleansing."""
    if state.get("error"):
        logger.error(f"Pipeline stopping after cleansing: {state['error']}")
        return "end"
    if state.get("clean_count", 0) == 0:
        logger.warning("No clean rows after cleansing — loading failed records only")
        return "load"
    return "enrichment"


def should_continue_after_enrichment(state: ETLState) -> str:
    """Stop pipeline if enrichment failed."""
    if state.get("error"):
        logger.error(f"Pipeline stopping after enrichment: {state['error']}")
        return "end"
    return "load"


def build_pipeline() -> StateGraph:
    """Build the LangGraph state machine."""
    graph = StateGraph(ETLState)

    # Add all agent nodes
    graph.add_node("ingestion",    ingestion_agent)
    graph.add_node("schema",       schema_agent)
    graph.add_node("cleansing",    cleansing_agent)
    graph.add_node("enrichment",   enrichment_agent)
    graph.add_node("load",         loader_agent)
    graph.add_node("audit",      audit_agent)

    # Set entry point
    graph.set_entry_point("ingestion")

    # Add conditional edges
    graph.add_conditional_edges(
        "ingestion",
        should_continue_after_ingestion,
        {"schema": "schema", "end": END}
    )
    graph.add_conditional_edges(
        "schema",
        should_continue_after_schema,
        {"cleansing": "cleansing", "end": END}
    )
    graph.add_conditional_edges(
        "cleansing",
        should_continue_after_cleansing,
        {"enrichment": "enrichment", "load": "load", "end": END}
    )
    graph.add_conditional_edges(
        "enrichment",
        should_continue_after_enrichment,
        {"load": "load", "end": END}
    )

    # Load always goes to end
    graph.add_edge("load", "audit")
    graph.add_edge("audit", END)

    return graph.compile()


def run_pipeline(csv_path: str) -> ETLState:
    """Run the full ETL pipeline for a given CSV file."""
    logger.info(f"═══════════════ LANGGRAPH ETL PIPELINE START ═══════════════")
    logger.info(f"Input: {csv_path}")

    pipeline = build_pipeline()

    initial_state = ETLState(
        csv_path=csv_path,
        headers=[], total_rows=0,
        entity_type=None, schema_info=None, schema_cached=False,
        raw_df=None, clean_df=None, failed_df=None, enriched_df=None,
        clean_count=0, failed_count=0, enriched_count=0,
        loaded_count=0, ai_inferred_count=0,
        audit_summary="", error=None
    )

    final_state = pipeline.invoke(initial_state)

    logger.info(f"═══════════════ PIPELINE COMPLETE ═══════════════")
    logger.info(f"  Total rows    : {final_state.get('total_rows')}")
    logger.info(f"  Clean rows    : {final_state.get('clean_count')}")
    logger.info(f"  Failed rows   : {final_state.get('failed_count')}")
    logger.info(f"  Enriched rows : {final_state.get('enriched_count')}")
    logger.info(f"  Loaded rows   : {final_state.get('loaded_count')}")
    logger.info(f"  AI inferred   : {final_state.get('ai_inferred_count')}")
    
    if final_state.get("audit_summary"):
        logger.info(f"\n{'═'*50}")
        logger.info("AUDIT SUMMARY")
        logger.info(f"{'═'*50}")
        logger.info(final_state["audit_summary"])

    return final_state