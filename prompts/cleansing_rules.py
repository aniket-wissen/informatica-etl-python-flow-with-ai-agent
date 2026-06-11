def build_cleansing_rules_prompt(entity_type: str, headers: list, sample_rows: list, known_tables: list) -> str:
    return f"""You are an ETL data quality expert.
Given this new entity type and its fields, generate cleansing rules and enrichment config.

Entity: {entity_type}
Fields: {headers}
Sample data (3 rows): {sample_rows}
Known DB tables available for enrichment: {known_tables}

Generate:
1. Cleansing rules for each field
2. Enrichment config — which field links to which existing table

Rule types available:
- mandatory: field must not be null/empty
- unique: field must be unique across rows
- positive_number: must be > 0
- date: must be valid date
- email: must be valid email format
- enum: must be one of given values (infer from sample data)

Return ONLY JSON, no explanation:
{{
  "cleansing_rules": {{
    "field_name": {{"type": "mandatory|positive_number|date|email|enum|unique", "unique": true/false, "values": ["only for enum"]}}
  }},
  "enrichment_key": "field_name_or_null",
  "enrichment_source": "existing_table_name_or_null"
}}"""