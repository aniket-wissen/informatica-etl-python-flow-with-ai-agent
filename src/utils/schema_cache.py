import json
import hashlib
import os
from loguru import logger

CACHE_FILE = "data/schema_cache/schemas.json"


def get_fingerprint(headers: list[str]) -> str:
    key = ",".join(sorted(headers))
    return hashlib.md5(key.encode()).hexdigest()


def load_cache() -> dict:
    if not os.path.exists(CACHE_FILE):
        return {}
    with open(CACHE_FILE, "r") as f:
        return json.load(f)


def save_cache(cache: dict):
    with open(CACHE_FILE, "w") as f:
        json.dump(cache, f, indent=2)
    logger.info("✅ Schema cache updated")


def get_cached_schema(headers: list[str]) -> dict | None:
    fingerprint = get_fingerprint(headers)
    cache = load_cache()

    # Exact match
    if fingerprint in cache:
        logger.info(f"✅ Schema cache hit — reusing cached schema")
        return cache[fingerprint]

    # Partial match — same entity, columns differ
    incoming = set(headers)
    for fp, schema in cache.items():
        cached_headers = set(schema.get("headers", []))
        common = incoming & cached_headers
        overlap = len(common) / len(cached_headers) if cached_headers else 0

        if overlap >= 0.70:
            added   = incoming - cached_headers
            removed = cached_headers - incoming
            logger.warning(f"⚠️  Partial schema match detected")
            logger.warning(f"   Base entity : {schema['entity_type']}")
            logger.warning(f"   Columns added  : {added}")
            logger.warning(f"   Columns removed: {removed}")
            return {
                "partial_match": True,
                "base_schema": schema,
                "added": list(added),
                "removed": list(removed),
                "fingerprint": fp
            }

    return None


def save_schema(headers: list[str], entity_type: str, mandatory_fields: list[str], enrichment_key: str):
    fingerprint = get_fingerprint(headers)
    cache = load_cache()
    cache[fingerprint] = {
        "entity_type":      entity_type,
        "headers":          headers,
        "mandatory_fields": mandatory_fields,
        "enrichment_key":   enrichment_key,
        "fingerprint":      fingerprint
    }
    save_cache(cache)
    return fingerprint