def get_enrichment_gaps_prompt(unmatched_rows: list[dict]) -> str:
    return f"""
You are a financial data enrichment expert.
The following transaction rows have account_ids that do not exist in our accounts database.

Unmatched rows:
{unmatched_rows}

Your job:
- For each row, infer what you can about the account based on transaction patterns
- Provide best-guess values for: account_type, customer_name, customer_segment, risk_rating
- Base your inference on transaction amount, merchant, channel, currency patterns

Rules:
- High value transactions (>50000) → risk_rating = HIGH
- Medium value (10000-50000) → risk_rating = MEDIUM  
- Low value (<10000) → risk_rating = LOW
- Return ONLY valid JSON array, no explanation, no markdown
- Each object must have: account_id, account_type, customer_name, customer_segment, risk_rating, ai_confidence

Example:
[
  {{
    "account_id": "ACC999",
    "account_type": "SAVINGS",
    "customer_name": "UNKNOWN",
    "customer_segment": "RETAIL",
    "risk_rating": "HIGH",
    "ai_confidence": "medium"
  }}
]
"""