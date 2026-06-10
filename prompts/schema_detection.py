def get_schema_detection_prompt(headers: list[str]) -> str:
    return f"""
You are a financial data expert analyzing CSV headers to identify the entity type.

Headers: {headers}

Your job:
1. Identify the entity type — MUST be one of: transactions, accounts
2. Identify mandatory fields that cannot be null
3. Identify the enrichment key (the field used to join/lookup other data)

Rules:
- transactions: usually has transaction_id, amount, date, account_id, status
- accounts: usually has account_id, customer_id, customer_name, email

Return ONLY valid JSON in this exact format, nothing else:
{{
    "entity_type": "transactions",
    "mandatory_fields": ["transaction_id", "amount", "account_id"],
    "enrichment_key": "account_id",
    "confidence": "high"
}}
"""