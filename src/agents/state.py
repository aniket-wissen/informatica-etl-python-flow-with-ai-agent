from typing import TypedDict, Optional
import pandas as pd


class ETLState(TypedDict):
    # Input
    csv_path:          str
    headers:           list[str]
    total_rows:        int

    # Schema
    entity_type:       Optional[str]   # transactions | accounts
    schema_info:       Optional[dict]  # full schema config
    schema_cached:     bool

    # Data frames at each stage
    raw_df:            Optional[pd.DataFrame]
    clean_df:          Optional[pd.DataFrame]
    failed_df:         Optional[pd.DataFrame]
    enriched_df:       Optional[pd.DataFrame]

    # Counts
    clean_count:       int
    failed_count:      int
    enriched_count:    int
    loaded_count:      int
    ai_inferred_count: int

    # AI
    audit_summary:     str

    # Control
    error:             Optional[str]