def build_mapping_prompt(incoming_headers: list, canonical_headers: list) -> str:
    return f"""Map these CSV headers to canonical field names.

Incoming: {', '.join(incoming_headers)}
Canonical: {', '.join(canonical_headers)}

Return ONLY JSON, no explanation:
{{"mappings": {{"incoming_col": "canonical_col"}}, "unmapped": ["col1"]}}
Rules:
- Only map when confident
- Leave unmapped if no clear match
- Use exact canonical names"""