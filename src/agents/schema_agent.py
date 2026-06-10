import json
from loguru import logger
from groq import Groq
from config.settings import settings
from src.agents.state import ETLState
from src.utils.schema_cache import get_cached_schema, save_schema
from prompts.schema_detection import get_schema_detection_prompt

client = Groq(api_key=settings.GROQ_API_KEY)


def _ask_ai(headers: list[str]) -> dict:
    """AI touchpoint 1 — only called on cache miss."""
    prompt = get_schema_detection_prompt(headers)
    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}]
    )
    raw = response.choices[0].message.content.strip()
    # Strip markdown fences if AI adds them
    raw = raw.replace("```json", "").replace("```", "").strip()
    return json.loads(raw)


def _human_confirm(entity_type: str, headers: list[str]) -> bool:
    """Ask human to confirm AI detection via CLI."""
    print(f"\n🤖 AI detected entity type: {entity_type}")
    print(f"   Headers: {headers}")
    answer = input("   Confirm? (y/n): ").strip().lower()
    return answer == "y"


def _handle_partial_match(state: ETLState, cached: dict) -> ETLState:
    """Handle schema drift — columns added or removed."""
    base = cached["base_schema"]
    added = cached["added"]
    removed = cached["removed"]

    print(f"\n⚠️  Schema change detected for {base['entity_type']}")
    if added:
        print(f"   New columns  : {added}")
        ans = input("   Include new columns? (y/n): ").strip().lower()
        if ans != "y":
            logger.info("  New columns ignored by user")

    if removed:
        print(f"   Missing columns: {removed}")
        logger.warning(f"  Columns removed vs cached schema: {removed}")

    # Proceed with base entity type
    state["entity_type"] = base["entity_type"]
    state["schema_info"] = base
    state["schema_cached"] = True
    logger.info(f"✅ Proceeding as {base['entity_type']} (partial match accepted)")
    return state


def schema_agent(state: ETLState) -> ETLState:
    logger.info("🤖 SchemaAgent started")
    headers = state["headers"]

    # Step 1 — check cache
    cached = get_cached_schema(headers)

    # Exact cache hit — no AI needed
    if cached and not cached.get("partial_match"):
        logger.info(f"✅ Cache hit — entity: {cached['entity_type']}")
        state["entity_type"] = cached["entity_type"]
        state["schema_info"] = cached
        state["schema_cached"] = True
        return state

    # Partial match — schema drift
    if cached and cached.get("partial_match"):
        return _handle_partial_match(state, cached)

    # Cache miss — call AI
    logger.info("  Cache miss — calling AI for schema detection...")
    try:
        result = _ask_ai(headers)
        entity_type = result["entity_type"]
        mandatory_fields = result["mandatory_fields"]
        enrichment_key = result["enrichment_key"]

        logger.info(f"  AI detected: {entity_type} (confidence: {result.get('confidence')})")

        # Human confirmation
        if not _human_confirm(entity_type, headers):
            state["error"] = "Schema rejected by user"
            logger.error("❌ Schema rejected by user")
            return state

        # Save to cache
        save_schema(headers, entity_type, mandatory_fields, enrichment_key)

        state["entity_type"] = entity_type
        state["schema_info"] = {
            "entity_type": entity_type,
            "mandatory_fields": mandatory_fields,
            "enrichment_key": enrichment_key,
            "headers": headers
        }
        state["schema_cached"] = False
        logger.info(f"✅ SchemaAgent done — {entity_type} cached for next run")

    except Exception as e:
        state["error"] = f"SchemaAgent failed: {e}"
        logger.error(state["error"])

    return state