import json
import os
from datetime import date
from loguru import logger

REGISTRY_FILE = "data/schema_registry.json"


def load_registry() -> dict:
    if not os.path.exists(REGISTRY_FILE):
        return {"version": 1, "entities": {}}
    with open(REGISTRY_FILE) as f:
        return json.load(f)


def save_registry(registry: dict):
    with open(REGISTRY_FILE, "w") as f:
        json.dump(registry, f, indent=2)


def get_entity(entity_type: str) -> dict | None:
    return load_registry()["entities"].get(entity_type)


def register_entity(entity_type: str, mandatory_fields: list,
                    enrichment_key: str | None, canonical_headers: list,
                    field_descriptions: dict, cleansing_rules: dict = None,
                    enrichment_source: str | None = None,
                    registered_by: str = "human"):
    registry = load_registry()
    registry["entities"][entity_type] = {
        "mandatory_fields":   mandatory_fields,
        "enrichment_key":     enrichment_key,
        "enrichment_source":  enrichment_source,
        "canonical_headers":  canonical_headers,
        "cleansing_rules":    cleansing_rules or {},
        "field_descriptions": field_descriptions,
        "version":            1,
        "registered_on":      str(date.today()),
        "registered_by":      registered_by
    }
    save_registry(registry)
    logger.info(f"✅ Entity '{entity_type}' registered in schema registry")


def match_entity(incoming_headers: list) -> tuple[str | None, float]:
    """
    Rule-based matching. Returns (entity_type, confidence).
    Confidence = overlap of incoming headers with mandatory fields.
    No AI involved.
    """
    registry   = load_registry()
    incoming   = set(h.lower().strip() for h in incoming_headers)
    best_match = None
    best_score = 0.0

    for entity_type, schema in registry["entities"].items():
        mandatory = set(f.lower() for f in schema["mandatory_fields"])
        canonical = set(f.lower() for f in schema["canonical_headers"])

        # Score = mandatory fields found / total mandatory fields
        mandatory_hit = len(incoming & mandatory) / len(mandatory)

        # Bonus: extra canonical fields also present
        canonical_hit = len(incoming & canonical) / len(canonical)
        score = (mandatory_hit * 0.8) + (canonical_hit * 0.2)

        if score > best_score:
            best_score = score
            best_match = entity_type

    logger.info(f"  Rule match: {best_match} (confidence={best_score:.2f})")
    return best_match, best_score