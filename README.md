# Financial ETL Pipeline

A Python-based ETL pipeline that replaces Informatica ETL workflows. Reads financial CSV files, enriches with metadata, transforms, and loads into a database. Fully database agnostic — switching databases requires only a `.env` change.

---

## Architecture Overview

```
CSV File
    ↓
IngestionAgent → SchemaAgent → CleansingAgent → EnrichmentAgent → LoaderAgent → AuditAgent
                                     ↓
                               failed_records
```

Every agent shares an `ETLState` dictionary (LangGraph typed state). If any agent sets `state["error"]`, the orchestrator stops and routes to the AuditAgent for a failure report.

**3 target tables:** `transactions`, `accounts`, `failed_records` (+ dynamic tables for new entities)

---

## AI Strategy — Used Only Where Rules Fail

| Step | Approach | Reason |
|---|---|---|
| Schema detection (known file) | Rule-based registry match | 0.001s, free, deterministic |
| Schema detection (repeat file) | MD5 fingerprint cache | Never calls AI twice for same headers |
| Schema detection (aliased columns) | AI semantic mapping | Rules can't map `txn_no → transaction_id` |
| Schema detection (unknown entity) | AI entity discovery | No rules exist for never-seen-before files |
| Enrichment (known account_id) | DB lookup | Instant, no AI needed |
| Enrichment (unknown account_id) | AI batch inference | DB has no record — AI fills the gap |
| Audit summary | AI always | Human-readable quality report |

**Maximum 3 AI calls per run.** Schema detection is cached after first use — same headers never trigger AI again.

---

## Schema Agent — 4-Tier Decision Tree

The most critical agent. Identifies what entity type a CSV contains.

```
Tier 1 — MD5 fingerprint cache
  Headers → sorted → MD5 hash → lookup in schemas.json
  HIT  → return entity instantly (0 AI calls)
  MISS → continue

Tier 2 — Rule-based registry match
  Score = (mandatory fields matched × 0.8) + (canonical fields matched × 0.2)
  Score ≥ 0.70 → entity identified (0 AI calls)
  Score < 0.70 → continue

Tier 3 — AI semantic mapping  [AI Call 1]
  Only if 0.40 ≤ score < 0.70
  AI maps column aliases to canonical names
  e.g. txn_no → transaction_id, txn_value → amount
  Human approves → result cached

Tier 4 — AI entity discovery  [AI Call 1]
  Only if score < 0.40 (completely unknown file)
  AI identifies entity type, mandatory fields, enrichment key
  Human approves → entity registered → table created if needed
```

---

## Cleansing Agent — Pure Python, No AI

Validates data before enrichment. Bad rows go to `failed_records` with exact reason — nothing is silently dropped.

**Transactions rules:** non-null `transaction_id`, unique IDs, positive numeric `amount`, valid `currency` (INR/USD/EUR/...), valid `status` and `channel`. Rows with `status=FAILED` are also rejected.

**Accounts rules:** non-null `account_id` and `customer_id`, valid email format.

**Generic (new entities):** non-null primary key, no completely empty rows.

**Example:**

```
TXN008 | amount=null    → failed_records (Missing amount)
TXN009 | currency=XYZ   → failed_records (Invalid currency: XYZ)
TXN001 | duplicate ID   → failed_records (Duplicate transaction_id)
TXN005 | status=FAILED  → failed_records (Transaction status is FAILED)
```

---

## Enrichment Agent

Only applies to `transactions`. All other entity types pass through unchanged.

```
For each transaction row:
  Step 1 — DB lookup: account_id found in accounts table?
    YES → attach account_type, customer_name, segment, risk_rating
          mark ai_inferred=N
    NO  → collect in unmatched list

  Step 2 — AI batch call (one call for ALL unmatched rows)  [AI Call 2]
    AI infers: account_type, segment, risk_rating
    Based on: amount, merchant name, channel patterns
    mark ai_inferred=Y, ai_confidence=low/medium
```

**Example:**

```
ACC001 found in DB  → Rahul Sharma, RETAIL, LOW risk    (ai_inferred=N)
ACC999 not in DB    → AI infers CORPORATE, HIGH risk    (ai_inferred=Y)
```

---

## Human Intervention Points

Human input is required at 3 points. Decisions are cached — same prompt never appears twice.

**1. New entity discovered**

```
⚠️  New entity: 'orders' (AI confidence=85%)
  [1] Register + create table + load
  [2] Register only — skip loading
  [3] Rename before registering
  [4] Reject file
```

**2. Schema evolution (new columns detected)**

```
⚠️  New columns in transactions: merchant_category, loyalty_points
  [1] Accept — ALTER TABLE + update cache
  [2] Accept — drop new columns, keep old schema
  [3] Reject — stop pipeline
```

**3. Column alias mapping**

```
⚠️  AI mapped: txn_no→transaction_id, txn_value→amount
  [1] Accept mapping
  [2] Reject — use original headers
  [3] Reject — mark as unknown
```

---

## 4 Tested Scenarios

### 1. Standard transactions file

```
transactions.csv → Tier 2 rule match (confidence=0.98) → 0 AI calls for schema
Cleansing: 8 clean, 4 failed | Enrichment: 5 DB matched, 3 AI inferred
Result: 8 loaded, 4 failed_records | Audit: 8/10
```

### 2. Aliased column names

```
transactions_aliases.csv (txn_no, txn_value, cust_acct)
→ Tier 3 semantic mapping → AI maps aliases → human approves → cached
→ Pipeline continues as transactions entity
```

### 3. Schema evolution

```
transactions_evolved.csv (+ merchant_category, loyalty_points)
→ Partial match detected → human approves → ALTER TABLE adds columns
→ Loader uses fixed model for known cols + raw UPDATE for new cols
→ Audit: 10/10
```

### 4. Completely new entity

```
orders.csv (order_id, product_name, quantity, order_amount)
→ Tier 4 discovery → AI detects 'orders' → human approves
→ Table created dynamically → generic cleansing + generic loader
→ 3 rows loaded with audit columns (source_file, run_id, load_timestamp)
```

---

## Repository Structure

```
financial-etl-v2/
├── src/
│   ├── agents/
│   │   ├── state.py                 ← LangGraph state definition
│   │   ├── orchestrator.py          ← LangGraph state machine
│   │   ├── ingestion_agent.py       ← reads CSV into DataFrame
│   │   ├── schema_agent.py          ← detects entity type (4-tier logic)
│   │   ├── cleansing_agent.py       ← validates and rejects bad rows
│   │   ├── enrichment_agent.py      ← joins account/security metadata
│   │   └── audit_agent.py           ← AI audit summary per run
│   ├── db/
│   │   ├── engine.py                ← SQLAlchemy engine, dynamic table creation
│   │   ├── models.py                ← Transaction, Account, FailedRecord models
│   │   └── loader.py                ← fixed + generic loader
│   └── utils/
│       ├── schema_cache.py          ← MD5 fingerprint cache
│       └── schema_registry.py       ← entity registry + alias resolution
├── prompts/
│   ├── schema_detection.py          ← AI prompt: entity discovery
│   ├── schema_semantic_mapping.py   ← AI prompt: alias mapping
│   ├── schema_evolution.py          ← AI prompt: schema drift analysis
│   └── audit.py                     ← AI prompt: run summary
├── mcp_server/
│   └── server.py                    ← FastMCP server (5 pipeline tools)
├── reference_data/
│   └── accounts_ref.csv             ← account metadata lookup
├── data/
│   ├── input/                       ← drop CSV files here
│   ├── schema_cache/schemas.json    ← cached header fingerprints
│   └── schema_registry.json         ← registered entity types
├── scripts/
│   └── verify_db.py                 ← DB verification report
├── config/
│   └── settings.py                  ← pydantic settings, DB URL builder
├── ui/
│   └── financial_etl_runner.html    ← browser UI dashboard
├── .env
├── requirements.txt
└── main.py                          ← pipeline entry point
```

---

## Database Agnostic Design

```env
# Switch DB by changing 3 lines in .env — zero code changes

DB_ENGINE=postgresql   # or mssql or sqlite
DB_HOST=localhost
DB_PORT=5433
```

`Settings.database_url` in `config/settings.py` builds the correct SQLAlchemy connection string per engine automatically.

---

## Setup

```bash
# Clone and setup
git clone <repo-url>
cd financial-etl-v2
python -m venv venv && venv\Scripts\activate
pip install -r requirements.txt

# Start PostgreSQL
docker run -d --name postgres-local -e POSTGRES_PASSWORD=postgres -p 5433:5432 postgres:16

# Configure .env
DB_ENGINE=postgresql
DB_HOST=localhost
DB_PORT=5433
DB_NAME=financial_etl_v2
DB_USER=postgres
DB_PASSWORD=postgres
GROQ_API_KEY=your_key_here

# Run pipeline
python main.py data/input/transactions.csv

# Verify results
python -m scripts.verify_db

# Optional — start MCP server
python mcp_server/server.py
```

---

## Key Design Principles

- **AI as last resort** — two rule-based tiers run before any AI call. Cached results mean the same file format never calls AI twice.
- **Nothing silently dropped** — every rejected row saved to `failed_records` with exact field and reason.
- **Human decisions cached** — schema approvals, alias mappings and entity registrations stored and reused automatically.
- **Fault tolerant** — row-level exception handling means one bad row never aborts the entire load.
- **Database agnostic** — SQLAlchemy abstracts all DB operations including dynamic table creation and schema evolution.
