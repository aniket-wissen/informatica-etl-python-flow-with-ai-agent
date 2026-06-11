def build_discovery_prompt(headers: list, sample_rows: list) -> str:
    return f"""Identify this CSV entity type from headers and samples.

Headers: {headers}
Samples (first 3 rows): {sample_rows}

Return ONLY JSON:
{{"entity_type": "name", "mandatory_fields": ["f1","f2"], "enrichment_key": "field_or_null", "field_descriptions": {{"field": "meaning"}}, "confidence": 0.0_to_1.0}}"""