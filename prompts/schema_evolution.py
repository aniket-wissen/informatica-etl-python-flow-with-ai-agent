def build_evolution_prompt(entity_type: str, added: list, removed: list, samples: list) -> str:
    return f"""Schema change detected for entity: {entity_type}

Added columns: {added or 'none'}
Removed columns: {removed or 'none'}
Sample values of new columns: {samples}

Return ONLY JSON:
{{"added_analysis": [{{"column": "x", "likely_meaning": "y", "canonical_name": "z", "retain": true}}], "removed_analysis": [{{"column": "x", "impact": "low|medium|high"}}], "summary": "one line"}}"""