import json
from loguru import logger
from langchain_groq import ChatGroq
from langchain_core.messages import HumanMessage
from src.agents.state import ETLState
from src.utils.schema_cache import (
    get_fingerprint, get_cached_schema, save_schema, load_cache, save_cache
)
from src.utils.schema_registry import match_entity, register_entity, get_entity
from src.utils.human_approval import request_approval, confirm
from prompts.schema_semantic_mapping import build_mapping_prompt
from prompts.schema_evolution import build_evolution_prompt
from prompts.schema_discovery import build_discovery_prompt
from config.settings import settings


CONFIDENCE_THRESHOLD = 0.70


def _get_llm():
    return ChatGroq(
        api_key=settings.GROQ_API_KEY,
        model="llama-3.3-70b-versatile",
        temperature=0
    )


def _call_ai(prompt: str) -> dict:
    """Single AI call. Returns parsed JSON or empty dict."""
    try:
        llm = _get_llm()
        response = llm.invoke([HumanMessage(content=prompt)])
        text = response.content.strip()
        text = text.replace("```json", "").replace("```", "").strip()
        return json.loads(text)
    except Exception as e:
        logger.error(f"  AI call failed: {e}")
        return {}


def _apply_column_mapping(df, mapping: dict):
    """Rename dataframe columns using approved mapping."""
    rename = {k: v for k, v in mapping.items() if k in df.columns}
    if rename:
        logger.info(f"  Renaming columns: {rename}")
        df = df.rename(columns=rename)
    return df


def _handle_semantic_mapping(state: ETLState, entity_type: str) -> ETLState:
    """AI semantic mapping — only when header overlap < threshold."""
    headers  = state["headers"]
    schema   = get_entity(entity_type)
    if not schema:
        return state

    canonical = schema["canonical_headers"]

    # Check approved mappings cache first
    cache = load_cache()
    mapping_key = f"mapping_{get_fingerprint(headers)}"
    if mapping_key in cache:
        logger.info("✅ Column mapping cache hit — reusing approved mapping")
        state["raw_df"] = _apply_column_mapping(state["raw_df"], cache[mapping_key]["mapping"])
        state["headers"] = list(state["raw_df"].columns)
        state["entity_type"] = entity_type.strip().lower()
        return state

    # AI call — one prompt for all columns
    logger.info("  🤖 AI semantic mapping called")
    result = _call_ai(build_mapping_prompt(headers, canonical))
    mappings  = result.get("mappings", {})
    unmapped  = result.get("unmapped", [])

    if not mappings:
        logger.warning("  AI could not map columns — pipeline will attempt with original headers")
        state["entity_type"] = entity_type
        return state

    # Human approval
    choice = request_approval(
        title=f"AI column mapping for '{entity_type}'",
        details={
            "Mapped columns": {k: v for k, v in mappings.items()},
            "Unmapped columns": unmapped or ["none"]
        },
        options=["Accept mapping", "Reject — use original headers", "Reject — mark as unknown"]
    )

    if choice == "Accept mapping":
        state["raw_df"] = _apply_column_mapping(state["raw_df"], mappings)
        state["headers"] = list(state["raw_df"].columns)
        # Cache approved mapping
        cache[mapping_key] = {"mapping": mappings, "entity_type": entity_type}
        save_cache(cache)
        logger.info("✅ Column mapping approved and cached")
    elif choice == "Reject — mark as unknown":
        state["entity_type"] = "unknown"
        return state

    state["entity_type"] = entity_type.strip().lower()
    return state


def _handle_schema_evolution(state: ETLState, base_schema: dict,
                              added: list, removed: list) -> ETLState:
    """AI explains schema drift. Human decides what to do."""
    entity_type = base_schema["entity_type"]
    samples = []
    df = state.get("raw_df")
    if df is not None and added:
        samples = df[added].head(3).to_dict(orient="records")

    logger.info("  🤖 AI schema evolution analysis called")
    result = _call_ai(build_evolution_prompt(entity_type, added, removed, samples))

    added_analysis   = result.get("added_analysis", [])
    removed_analysis = result.get("removed_analysis", [])
    summary          = result.get("summary", "Schema changed")

    details = {"Summary": summary}
    if added_analysis:
        details["New columns"] = [
            f"{a['column']} → {a.get('canonical_name', a['column'])}: {a.get('likely_meaning', '?')} (retain={a.get('retain', True)})"
            for a in added_analysis
        ]
    if removed_analysis:
        details["Removed columns"] = [
            f"{r['column']} (impact={r.get('impact', 'unknown')})"
            for r in removed_analysis
        ]

    choice = request_approval(
        title=f"Schema evolution detected for '{entity_type}'",
        details=details,
        options=[
            "Accept — update cache with new schema",
            "Accept — keep old schema, drop new columns",
            "Reject — stop pipeline"
        ]
    )

    if choice == "Reject — stop pipeline":
        state["error"] = "Pipeline stopped by operator — schema evolution rejected"
        return state

    if choice == "Accept — update cache with new schema":
        # ALTER TABLE to physically add new columns in DB
        if added:
            from src.db.engine import alter_table_for_new_columns
            entity_type = base_schema["entity_type"]
            alter_table_for_new_columns(entity_type, added)
            logger.info(f"✅ DB table '{entity_type}' altered with new columns: {added}")

    if choice == "Accept — keep old schema, drop new columns":
        if df is not None and added:
            state["raw_df"] = df.drop(columns=added, errors="ignore")
            state["headers"] = list(state["raw_df"].columns)

    state["entity_type"] = entity_type
    state["schema_cached"] = False
    return state


def _handle_unknown_entity(state: ETLState) -> ETLState:
    """AI discovers new entity type. Human registers it and decides on DB action."""
    headers = state["headers"]
    df      = state.get("raw_df")
    samples = df.head(3).to_dict(orient="records") if df is not None else []

    logger.info("  🤖 AI entity discovery called")
    result = _call_ai(build_discovery_prompt(headers, samples))

    entity_type    = result.get("entity_type", "unknown").strip().lower()
    mandatory      = result.get("mandatory_fields", [])
    enrichment_key = result.get("enrichment_key")
    descriptions   = result.get("field_descriptions", {})
    confidence     = result.get("confidence", 0.0)

    if not entity_type or entity_type == "unknown":
        logger.warning("  AI could not identify entity — skipping file")
        state["error"] = "Unknown entity type — could not process file"
        return state

    choice = request_approval(
        title=f"New entity discovered: '{entity_type}' (confidence={confidence:.0%})",
        details={
            "Entity type":      entity_type,
            "Mandatory fields": mandatory,
            "Enrichment key":   enrichment_key or "none",
            "Columns":          headers,
            "Field meanings":   descriptions
        },
        options=[
            f"Register '{entity_type}' + create table + load data",
            f"Register '{entity_type}' only — skip loading this run",
            "Rename entity type before registering",
            "Reject — skip this file"
        ]
    )

    if choice == "Reject — skip this file":
        state["error"] = f"Unknown entity '{entity_type}' rejected by operator"
        return state

    if choice == "Rename entity type before registering":
        entity_type = input("  Enter entity type name: ").strip().lower()

    # Generate cleansing rules + enrichment config via AI
    from prompts.cleansing_rules import build_cleansing_rules_prompt
    from src.utils.schema_registry import load_registry
    known_tables = list(load_registry()["entities"].keys())

    logger.info("  🤖 Generating cleansing rules for new entity...")
    rules_result = _call_ai(build_cleansing_rules_prompt(
        entity_type, headers,
        samples[:3],
        known_tables
    ))

    cleansing_rules   = rules_result.get("cleansing_rules", {})
    enrichment_key    = rules_result.get("enrichment_key") or enrichment_key
    enrichment_source = rules_result.get("enrichment_source")

    logger.info(f"  Generated {len(cleansing_rules)} cleansing rules")
    if enrichment_source:
        logger.info(f"  Enrichment: {enrichment_key} → {enrichment_source} table")

    entity_type = entity_type.replace("-", "_").replace(" ", "_").lower()
    register_entity(
        entity_type=entity_type,
        mandatory_fields=mandatory,
        enrichment_key=enrichment_key,
        enrichment_source=enrichment_source,
        canonical_headers=headers,
        field_descriptions=descriptions,
        cleansing_rules=cleansing_rules,
        registered_by="human"
    )
    save_schema(headers, entity_type, mandatory, enrichment_key)
    logger.success(f"✅ Entity '{entity_type}' registered with {len(cleansing_rules)} cleansing rules")

    state["entity_type"]   = entity_type
    state["schema_cached"] = True

    if "create table" in choice:
        # Dynamically create the table in DB
        from src.db.engine import create_table_from_df
        target_df = state.get("raw_df")
        if target_df is not None:
            sanitized = entity_type.replace("-", "_").replace(" ", "_").lower()
            created = create_table_from_df(sanitized, target_df)
            state["entity_type"] = sanitized
            if created:
                logger.success(f"✅ Table '{entity_type}' ready for loading")
            else:
                state["error"] = f"Failed to create table '{entity_type}'"
                return state
    else:
        # Register only — mark as skip load
        logger.info(f"  '{entity_type}' registered — loading skipped this run")
        state["skip_load"] = True

    return state


def schema_agent(state: ETLState) -> ETLState:
    logger.info("🤖 SchemaAgent started")
    headers = state["headers"]

    # ── Tier 1: Exact fingerprint cache hit ──────────────────────────
    cached = get_cached_schema(headers)
    if cached and not cached.get("partial_match"):
        logger.info(f"✅ Schema cache hit — entity={cached['entity_type']}")
        state["entity_type"]   = cached["entity_type"]
        state["schema_info"]   = cached
        state["schema_cached"] = True
        return state

    # ── Tier 1.5: Approved column mapping cache hit ───────────────────
    mapping_key = f"mapping_{get_fingerprint(headers)}"
    cache = load_cache()
    if mapping_key in cache:
        approved = cache[mapping_key]
        logger.info(f"✅ Approved column mapping cache hit — entity={approved['entity_type']}")
        state["raw_df"]      = _apply_column_mapping(state["raw_df"], approved["mapping"])
        state["headers"]     = list(state["raw_df"].columns)
        state["entity_type"] = approved["entity_type"].strip().lower()
        state["schema_cached"] = True
        return state

    # ── Tier 2: Rule-based registry match ────────────────────────────
    entity_type, confidence = match_entity(headers)

    if cached and cached.get("partial_match"):
        # Known entity, columns drifted
        added   = cached.get("added", [])
        removed = cached.get("removed", [])
        logger.warning(f"⚠️  Schema evolution: +{added} -{removed}")
        state = _handle_schema_evolution(state, cached["base_schema"], added, removed)
        if state.get("error"):
            return state
        # Cache updated schema
        save_schema(state["headers"], state["entity_type"],
                    get_entity(state["entity_type"])["mandatory_fields"],
                    get_entity(state["entity_type"])["enrichment_key"])
        return state

    if confidence >= CONFIDENCE_THRESHOLD:
        logger.info(f"✅ Rule match — entity={entity_type} confidence={confidence:.0%}")

        # Check for schema evolution — new columns not in canonical schema
        schema        = get_entity(entity_type)
        canonical_set = set(h.lower() for h in schema["canonical_headers"])
        incoming_set  = set(h.lower() for h in headers)
        added         = list(incoming_set - canonical_set)
        removed       = list(canonical_set - incoming_set)

        if added:
            logger.warning(f"⚠️  New columns detected: {added}")
            state["entity_type"] = entity_type
            state = _handle_schema_evolution(
                state,
                {"entity_type": entity_type},
                added,
                removed
            )
            if state.get("error"):
                return state
            # Update canonical headers in registry with approved new columns
            if added and state.get("entity_type") == entity_type:
                from src.utils.schema_registry import load_registry, save_registry
                registry = load_registry()
                if entity_type in registry["entities"]:
                    existing = registry["entities"][entity_type]["canonical_headers"]
                    approved_added = [c for c in added if c not in existing]
                    registry["entities"][entity_type]["canonical_headers"].extend(approved_added)
                    registry["entities"][entity_type]["version"] += 1
                    save_registry(registry)
                    logger.info(f"✅ Registry updated with new columns: {approved_added}")
        else:
            save_schema(headers, entity_type,
                        schema["mandatory_fields"],
                        schema["enrichment_key"])

        state["entity_type"]   = entity_type
        state["schema_cached"] = False
        return state

    # ── Tier 3: Semantic mapping against all known entities ──────────
    # Try every known entity — AI maps aliases to canonical names
    from src.utils.schema_registry import load_registry
    all_entities = list(load_registry()["entities"].keys())
    # Try best rule match first, then others
    candidates = []
    if entity_type:
        candidates.append(entity_type)
    candidates += [e for e in all_entities if e != entity_type]

    for candidate in candidates:
        logger.info(f"  Trying semantic mapping against '{candidate}'")
        state = _handle_semantic_mapping(state, candidate)
        if state.get("entity_type") and state["entity_type"] not in ("unknown", None):
            return state
    
    # ── Tier 4: Unknown entity — AI discovery ────────────────────────
    logger.info("  No match found — running entity discovery")
    return _handle_unknown_entity(state)