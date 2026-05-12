---
title: AM1 Feature Register
project: "Agentic Conversational BI: LLM-Driven Ad-Hoc Data Exploration"
candidate: Manu Mohandas
employer: Tata Consultancy Services
build_window: "Apr 16 – May 22, 2026"
report_due: "Jun 7, 2026"
last_updated: "2026-05-10"
tags: [AM1, BCS-L7, feature-register, sprint-tracking]
---

# AM1 Feature Register
## Agentic Conversational BI: LLM-Driven Ad-Hoc Data Exploration

> **Candidate:** Manu Mohandas | **Employer:** Tata Consultancy Services
> **Build window:** Apr 16 – May 22, 2026 | **Report due:** Jun 7, 2026

Update the **Status** field at the start and end of each sprint.
Valid statuses: `Planned` / `Building` / `Testing` / `Validated`

**KSB colour key:** K = Knowledge | S = Skill | B = Behaviour

---

## Sprint 1 — Foundation: Data & Environment
`Apr 16–20 | 18 hrs`

---

### F-01 · Synthetic FMCG Dataset Generation
| Field | Detail |
|---|---|
| **Sprint** | S1 |
| **KSB** | K5 · K13 · S9 · S10 · S17 |
| **Status** | `Validated` |

**Problem Statement**
No real production data can be used in an academic prototype. Synthetic FMCG data must mirror real commercial data quality conditions — including known imperfections — to make EDA and preprocessing activities meaningful rather than cosmetic. Clean generated data would trivialise the preprocessing step and undermine its evidential value.

**Acceptance Criteria**
1. Four tables generated as Parquet: `dim_product` (~552 rows, ~497 active), `dim_customer` (240 rows), `fact_sales` (~2.3M rows covering 104 ISO weeks: 1 Jan 2024 – 31 Dec 2025), `fact_market` (~44K rows, same window). All PKs non-null. FK relationships intact across all joins. Two complete calendar years chosen deliberately to enable full-year YoY comparisons (2024 vs 2025), four complete quarters per year, and two full seasonal cycles.
2. `fact_market` at raw measurement grain (week × brand × sub_category × banner): `brand_volume_units`, `brand_value_gbp`, `total_category_volume_units`, `total_category_value_gbp`, `numeric_distribution_outlets`, `total_outlets_in_banner`, `avg_shelf_price_gbp`. No pre-calculated share or index columns. Value columns computed at RSP (`avg_shelf_price_gbp`) consistent with Nielsen/Kantar panel measurement convention. `manufacturer_net_price_gbp` is NOT stored in `fact_market` — panel providers cannot observe bilateral trade terms. Retailer margin is derivable via cross-table join to `fact_sales.sku_net_price_gbp`.
3. Deliberate quality issues injected via a separate `inject_quality_issues.py` script (documented and version-controlled): ~3% zero `sku_net_price_gbp` in `fact_sales`; ~2% volume outliers; 22% NULL `promotion_mechanic` where `is_promoted=True`; inconsistent casing/abbreviations in `dim_product` `pack_type` and `variant`; `is_active` as Y/N string; `launch_date` as string; ~15% NULL `territory` in `dim_customer`; ~10% NULL `store_count`; ~5% `avg_shelf_price_gbp=0` in `fact_market`; `brand_volume` exceeding `category_volume` in ~1% of `fact_market` rows; 3–4 week gaps for select banner–brand combinations.
4. `inject_quality_issues.py` is a standalone, documented script — its existence proves issues are deliberate design choices and not oversights, forming the basis of the EDA narrative in the report.
5. Four intentional performance signals built into baseline_volume generation parameters (applied before promotion, never to total volume): (1) NitroBoost volume growth 2024→2025 (+18% baseline multiplier); (2) Porridge & Oats Q3 seasonal decline (ISO weeks 26–39, ×0.65 factor, both years — genuine cold-weather category pattern); (3) Ice Cream Q4 seasonal decline (ISO weeks 40–52, ×0.60 factor, both years — summer impulse category drops in winter); (4) ValuMart banner deterioration across 2025 (linear 1.00→0.82 applied to baseline by ISO week — structural market share loss independent of promotion). Signals verified via baseline_volume summary queries before proceeding.

**Design Decisions**

| Decision | Rationale | Alternative Considered |
|---|---|---|
| Performance signals applied to `baseline_volume` before promotion draw | Isolates structural trend from promo mix distortion. NitroBoost growth and ValuMart decline are structural — not promotional artefacts. Querying baseline vs total volume produces meaningfully different, defensible answers | Signals applied to total volume — rejected: promo mix variance would dilute or inflate signals unpredictably |
| `incremental_volume` drawn independently (20–50% uplift, promo rows only); non-promo rows carry zero incremental | Keeps baseline analytically clean as structural demand signal. Incremental = mechanistic promo uplift only | Back-calculating baseline as fraction of total volume — rejected: would pollute baseline with noise |
| Lognormal distribution for base volume | Always positive; right-skewed (mirrors real FMCG velocity data where most weeks are moderate but occasional peaks occur); median ≈ 55 units at Convenience scale. Gap between mean and median (55 vs 66) reflects natural skew | Normal distribution — rejected: allows negatives, symmetric, not representative of sales data |
| Channel volume scaling applied as multiplier on lognormal base | Preserves consistent within-channel variance shape; only the level shifts by channel. Grocery ×4.0, eCommerce ×3.0, Discounter ×2.0, Foodservice ×2.0, Convenience ×0.5 | Separate lognormal per channel — rejected: redundant, harder to tune consistently |
| `CHANNEL_CATEGORY_UNLISTED` final set: Frozen/Convenience, Frozen/eCommerce, Snacks/eCommerce | Frozen/Convenience: no freezer logistics in small-format retail. Frozen/eCommerce: consumer last-mile frozen not viable. Snacks/eCommerce: low value density, uneconomic per-unit delivery. Foodservice retains Frozen (commercial kitchens use frozen), Dairy (core catering ingredient), and Confectionery (hotels, canteens) | Earlier version also excluded Dairy/eCommerce and Confectionery/Foodservice — both reversed after real-world review (Ocado/FreshDoor-type eComm for dairy; hospitality confectionery stocking) |
| `how="cross"` for all cross-joins in `generate_fact_market`; `_k` dummy column pattern removed | Native pandas cross-join is explicit, readable, and doesn't mutate input DataFrames. `_k` pattern required defensive `.copy()` on source frames and left junk columns on `active` | `_k` merge pattern — replaced as part of code quality review |
| `fact_market` grain stays at brand × sub_category × banner × week | Matches real Nielsen/Kantar panel data licence grain. SKU-level market data would imply retailer EPOS (a different source). Grain mismatch between `fact_sales` (SKU level) and `fact_market` (brand level) is architecturally correct | SKU-banner grain — rejected: misrepresents the data source; Nielsen does not report at SKU level in standard licences |
| `selling_price_gbp` renamed to `sku_net_price_gbp` in `fact_sales` | Unambiguous industry term — net price means post-discount manufacturer realised price in FMCG commercial finance. `selling_price` is ambiguous between shelf and invoice price | `sku_sales_price` — rejected: ambiguous on which side of the trade transaction |
| `manufacturer_net_price_gbp` removed from `fact_market`; `avg_shelf_price_gbp` is the sole price column | Panel providers cannot observe bilateral trade terms. Storing manufacturer net in `fact_market` implied Nielsen knows trade terms — factually wrong. RSP is the only price panel data can measure. Retailer margin derivable via cross-table join to `fact_sales.sku_net_price_gbp` | Storing both prices in `fact_market` — rejected: manufacturer net does not belong in panel data |
| `snap_to_realistic_price()` NOT applied to `sku_net_price_gbp` or `fact_market` price columns | `sku_net_price_gbp` is manufacturer trade net — calculated as % discount off list, lands at arbitrary pence. Pence snapping belongs only on consumer-facing list prices in `dim_product`. Applying it to 2M rows via scalar function would also be prohibitively slow | Apply pence endings to net price — rejected: wrong data layer, wrong semantics |
| Retailer margin not modelled in `fact_sales` | Requires off-invoice rates and bill-back accruals — neither is modelled. Computing `selling_price - list_price` would be manufacturer discount, not retailer margin. Misleading rather than useful | Add retailer margin to `fact_sales` — deferred: correct data would require trade terms tables not in scope |

---

### F-02 · EDA & Data Preprocessing
| Field | Detail |
|---|---|
| **Sprint** | S1 |
| **KSB** | K3 · K5 · K13 · S2 · S9 · S17 · S22 |
| **Status** | `Planned` |

**Problem Statement**
Assessment criteria require evidence of principled data quality decisions, not just data profiling. EDA must surface the injected quality issues and produce documented, defensible handling decisions that feed directly into the schema dictionary used for LLM grounding. Preprocessing outputs become the clean Parquet layer that the query engine operates on.

**Acceptance Criteria**
1. Profiling completed for all four tables: row counts, null rates per column, value distribution (`describe()`), cardinality of categoricals, and FK referential integrity checks. Findings documented in `eda_report.md`.
2. Quality issues identified and resolution decisions documented for each: zero `selling_price` (exclude from revenue aggregations, flag column added); volume outliers (IQR-based detection, flagged not removed — removal rationale documented); NULL `promotion_mechanic` (documented as known sparseness, not imputed — LLM instructed via schema dictionary to treat NULL mechanic as unknown type, not non-promotional); inconsistent `pack_type`/`variant` casing (normalised to title case via mapping table); `is_active` encoded to boolean; `launch_date` parsed to date type; NULL `territory` imputed with channel-level aggregate label `Unknown-[Channel]`; NULL `store_count` imputed with channel median (median chosen over mean due to skewed distribution — decision documented).
3. `fact_market` derived measures computed and validated as new columns appended to the clean layer: `market_share_volume_pct`, `market_share_value_pct`, `numeric_distribution_pct`, `weighted_distribution_pct` (weighted by `store_count`), `price_index`. Rows where `brand_volume` exceeds `category_volume` flagged and excluded from share calculations with documented rationale.
4. Temporal gap analysis performed on `fact_market`: banner–brand combinations with 3+ consecutive missing weeks identified and listed. Handling decision documented: gaps left sparse (not interpolated) to preserve data integrity; LLM schema dictionary notes sparseness pattern so the model does not misinterpret missing weeks as zero sales.
5. Clean Parquet files written as a separate layer (`data/processed/`): preprocessing pipeline is reproducible as a standalone script (`preprocess.py`). Raw files preserved in `data/raw/` unchanged.

---

### F-03 · DuckDB + Parquet Storage Layer
| Field | Detail |
|---|---|
| **Sprint** | S1 |
| **KSB** | K13 · K14 · S15 · S25 |
| **Status** | `Planned` |

**Problem Statement**
The system requires zero-infrastructure OLAP query execution without a database server, eliminating deployment complexity and data egress risk. DuckDB operates against the clean Parquet layer produced by preprocessing, ensuring the query engine always runs on validated, quality-resolved data.

**Acceptance Criteria**
1. Clean Parquet files (`data/processed/`) loadable via DuckDB Python API in a single connection object. Raw files (`data/raw/`) never directly queried by the application.
2. Three benchmark queries (GROUP BY aggregation, multi-table JOIN, window function) each execute in under 2 seconds on the full ~2M row `fact_sales`.
3. Derived measure queries (e.g. market share computed from raw brand and category volumes) verified to return correct results against known expected values.
4. DuckDB selection over alternatives (Pandas, SQLite, cloud DW) documented with rationale in design notes.

---

### F-04 · Schema & Semantic Data Dictionary
| Field | Detail |
|---|---|
| **Sprint** | S1 |
| **KSB** | K1 · K5 · S27 |
| **Status** | `Planned` |

**Problem Statement**
The LLM requires a grounding document anchored to the clean, preprocessed data layer — not the raw schema. It must convey which measures are derived (and how), which fields carry known sparseness, and how to join `fact_market` to `fact_sales` correctly. Without this, the model will either misinterpret raw columns as pre-computed KPIs or attempt impossible direct joins.

**Acceptance Criteria**
1. Document covers all 4 clean-layer tables: column names, data types, FK relationships, and business-semantic definitions for every field.
2. Derived measure definitions explicit: `market_share_volume_pct = brand_volume_units / total_category_volume_units × 100`. Price index, distribution %, and weighted distribution % defined equivalently. Model must not treat these as stored raw columns.
3. Documented sparseness patterns: NULL `promotion_mechanic` means unknown type (not non-promotional); temporal gaps in `fact_market` are true missing data (not zero sales).
4. Explicit join guidance: to compare `fact_sales` with `fact_market`, aggregate `fact_sales` to banner level via `dim_customer` first, then join on `week_date`, `brand`, `banner`. Document injectable as plain text. Schema update requires only document edit, no code change.

---

### F-05 · Project Environment & Scaffolding
| Field | Detail |
|---|---|
| **Sprint** | S1 |
| **KSB** | K6 · S24 · S25 · B2 |
| **Status** | `Validated` |

**Problem Statement**
A clean, reproducible project structure supports iterative development, software engineering collaboration standards, and the audit traceability required by the assessment criteria.

**Acceptance Criteria**
1. Folder structure established: `data/`, `src/`, `scripts/`, `logs/`, `tests/`, `docs/`. (`scripts/` holds one-time batch pipeline scripts: `generate_data.py`, `inject_quality_issues.py`, `preprocess.py`. `src/` holds application source code: Streamlit UI, NL2SQL engine, agentic loop.)
2. `requirements.txt` complete with pinned package versions. Virtual environment documented.
3. `.env.example` created. Actual `.env` excluded from Git via `.gitignore`.
4. Git repo initialised. README with setup and run instructions written. Gemini API key verified working via first test call.

---

## Sprint 2 — NL2SQL Core
`Apr 21–27 | 22 hrs`

---

### F-06 · Gemini 2.5 Flash API Integration
| Field | Detail |
|---|---|
| **Sprint** | S2 |
| **KSB** | K1 · K13 · S15 · S25 |
| **Status** | `Validated` |

**Problem Statement**
The cloud reasoning layer must be connected before NL2SQL can be tested. Gemini 2.5 Flash is selected for its extended context window — essential for full-schema RAG — and strong chain-of-thought performance on structured output tasks.

**Acceptance Criteria**
1. API key loaded from `.env` via `python-dotenv`. Key not hardcoded anywhere in the codebase.
2. Single test prompt returns valid parsed text response. Response parsing extracts clean text reliably.
3. Model version pinned in config file (not hardcoded inline) to protect against unintended model changes.
4. HTTP errors and rate limit responses caught and handled gracefully — not raised as unhandled exceptions.

---

### F-07 · RAG-Based Schema Injection
| Field | Detail |
|---|---|
| **Sprint** | S2 |
| **KSB** | K1 · K3 · S15 |
| **Status** | `Validated` |

**Problem Statement**
Without schema grounding, the LLM will hallucinate table and column names. RAG injection of the full schema and data dictionary constrains the solution space on every call, without requiring model fine-tuning.

**Acceptance Criteria**
1. Full schema + semantic data dictionary injected into system prompt on every API call.
2. Token count of injected schema verified to be within Gemini 2.5 Flash context window limit.
3. Schema injection is file-based: updating the schema document requires no code changes.
4. Verified: model references correct column names from schema rather than inventing alternatives, on at least 10 test queries.

---

### F-08 · Chain-of-Thought NL2SQL Generation
| Field | Detail |
|---|---|
| **Sprint** | S2 |
| **KSB** | K1 · K3 · K26 · S22 |
| **Status** | `Validated` |

**Problem Statement**
Ambiguous business questions require multi-step decomposition before SQL can be generated reliably. CoT prompting instructs the model to reason through the query before producing SQL, reducing semantic errors on complex queries.

**Acceptance Criteria**
1. System prompt instructs model to state reasoning before the SQL block, separated by a defined delimiter (` ```sql `).
2. Generated output consistently separates reasoning text from SQL block. SQL extractable via delimiter parsing without failures.
3. Tested across 15 manual queries: single-table filter, aggregation, multi-table join, ambiguous FMCG term, and time-period filter.
4. Prompt iteration log maintained: each prompt version and observed failure pattern documented for Sprint 5 evaluation.

---

### F-09 · SQL Execution Layer
| Field | Detail |
|---|---|
| **Sprint** | S2 |
| **KSB** | K23 · S15 · S25 |
| **Status** | `Validated` |

**Problem Statement**
Generated SQL must be executed against DuckDB and results returned as structured data. Execution errors must be captured as structured signals for the retry loop, not surfaced as raw exceptions to the user.

**Acceptance Criteria**
1. SQL string passed to DuckDB connection. Result returned as pandas DataFrame on success.
2. Execution errors caught and returned as structured dict with `error_type` and `error_message` fields — not raised.
3. Both success and error paths covered by unit tests using known-good and known-bad SQL strings.
4. Execution time recorded in milliseconds per query and included in the result object for logging.

---

## Sprint 3 — Agentic Loop + Conversation History
`Apr 28 – May 4 | 22 hrs`

---

### F-10 · Self-Correction Agentic Retry Loop
| Field | Detail |
|---|---|
| **Sprint** | S3 |
| **KSB** | K1 · K13 · K23 · S15 |
| **Status** | `Planned` |

**Problem Statement**
LLM-generated SQL will sometimes fail execution due to schema mismatches or hallucinated column names. An agentic retry loop that feeds the error back to the model creates a self-healing system without requiring human intervention.

**Acceptance Criteria**
1. On SQL execution error, error message formatted as a correction signal and appended to the prompt context.
2. Model regenerates SQL with the error context visible. Regenerated SQL re-executed against DuckDB automatically.
3. Loop retries up to max N=3 times. Hard cap enforced — no infinite retry possible.
4. Retry count logged per turn. Loop tested with deliberately invalid queries covering: syntax errors, wrong column names, and invalid joins.

---

### F-11 · Conversation History Management
| Field | Detail |
|---|---|
| **Sprint** | S3 |
| **KSB** | K1 · K5 · S15 |
| **Status** | `Planned` |

**Problem Statement**
Contextual follow-up questions (e.g. "now filter that by the North region") require the model to retain prior turns. Without history, every query is independent and analytical context is lost between turns.

**Acceptance Criteria**
1. Prior turns (user query, generated SQL, result summary) appended to prompt context on each new turn.
2. Multi-turn test of 5 sequential contextual questions passes without context loss across turns.
3. History truncation logic prevents context window overflow for long conversations (oldest turns pruned first with user notification).
4. Conversation turn counter incremented and exposed in response object for downstream logging.

---

### F-12 · Narrative Response Generation
| Field | Detail |
|---|---|
| **Sprint** | S3 |
| **KSB** | K28 · S4 · S5 · B6 |
| **Status** | `Planned` |

**Problem Statement**
Non-technical FMCG users need answers in plain English, not raw tabular output. A dedicated second LLM call generates a business-language explanation of the result, serving the non-technical audience explicitly.

**Acceptance Criteria**
1. Second Gemini call receives query result DataFrame summary + original user question and returns narrative paragraph.
2. Narrative references specific figures from the result — not generic placeholder text.
3. Both narrative and SQL present in the response object returned to the orchestration layer.
4. Tested across 5 diverse query types: volume trend, market share, promotional uplift, price analysis, and multi-brand comparison.

---

## Sprint 4 — Streamlit UI + JSONL Logging
`May 5–11 | 22 hrs`

---

### F-13 · Streamlit Conversational UI
| Field | Detail |
|---|---|
| **Sprint** | S4 |
| **KSB** | K6 · K14 · S15 · S18 · S24 |
| **Status** | `Planned` |

**Problem Statement**
The system requires a web interface that non-technical users can interact with without running Python scripts. Streamlit provides Python-native session state, critical for maintaining conversation history across turns without a separate backend service.

**Acceptance Criteria**
1. App launches via `streamlit run app.py` with no additional configuration steps.
2. Chat input accepts natural language. Message history displays chronologically in a thread format.
3. Loading indicator shown during API call. Input disabled while a query is processing.
4. Session state correctly persists conversation history within a session. Tested across 10 end-to-end query flows without state loss.

---

### F-14 · Dual-Audience Output Design
| Field | Detail |
|---|---|
| **Sprint** | S4 |
| **KSB** | K6 · K28 · S4 · S5 · B6 |
| **Status** | `Planned` |

**Problem Statement**
The system must serve two distinct user types simultaneously: non-technical FMCG business users who need narrative insights, and technical reviewers who require SQL traceability for audit and validation purposes.

**Acceptance Criteria**
1. Business panel: narrative text displayed and result auto-rendered as chart or table based on result shape (numeric series = chart, categorical = table).
2. Technical panel: generated SQL displayed with execution metadata (latency ms, retry count, turn ID).
3. Technical panel is collapsible so business users are not distracted by SQL output.
4. Both panels populated from the same response object. Tested with two distinct user personas across 5 query types.

---

### F-15 · JSONL Logging Infrastructure
| Field | Detail |
|---|---|
| **Sprint** | S4 |
| **KSB** | K6 · K23 · S17 · S24 |
| **Status** | `Planned` |

**Problem Statement**
Every interaction must be logged for reproducibility, audit, and Sprint 5 evaluation. JSONL format requires no schema migration as logging fields evolve, and is directly parseable for metric computation.

**Acceptance Criteria**
1. Each turn logged as a single JSON line appended to `interactions.jsonl` at the end of each turn.
2. Log fields captured: `turn_id`, `timestamp`, `user_query`, `generated_sql`, `execution_time_ms`, `retry_count`, `row_count`, `success_flag`, `narrative_generated`.
3. Log file persists across Streamlit sessions. Readable via standard Python `json` library without custom parser.
4. Log write failure does not crash the application (wrapped in `try/except` with warning displayed).

---

## Sprint 5 — Evaluation + Hypothesis Testing
`May 12–18 | 22 hrs`

---

### F-16 · Benchmark Prompt Suite Design
| Field | Detail |
|---|---|
| **Sprint** | S5 |
| **KSB** | K5 · K23 · K26 · S22 |
| **Status** | `Planned` |

**Problem Statement**
Systematic evaluation requires a pre-defined, reproducible set of test prompts covering the full range of query complexity. Without a benchmark suite, evaluation is anecdotal rather than scientific and not defensible in the assessment report.

**Acceptance Criteria**
1. 20 benchmark prompts defined across 5 complexity tiers: (1) single-table filter, (2) aggregation, (3) multi-table join, (4) ambiguous FMCG business term, (5) multi-turn contextual chain.
2. Expected result or expected SQL pattern defined for each prompt and documented in `benchmark.json`.
3. Benchmark suite runnable via a single script: `python run_benchmark.py`.
4. Suite covers both baseline and treatment conditions and produces structured output suitable for metric computation.

---

### F-17 · Baseline vs Treatment Experiment
| Field | Detail |
|---|---|
| **Sprint** | S5 |
| **KSB** | K3 · K26 · S2 · S3 · S22 |
| **Status** | `Planned` |

**Problem Statement**
The core hypothesis — that semantic data dictionary injection reduces SQL semantic errors — must be tested empirically. A controlled experiment with two conditions provides the scientific evidence base required by the report.

**Acceptance Criteria**
1. Baseline condition defined: system prompt with schema only, no semantic data dictionary definitions.
2. Treatment condition defined: system prompt with schema plus full semantic data dictionary.
3. Both conditions run against all 20 benchmark prompts. Results recorded in `experiment_results.csv`.
4. Hypothesis stated formally (H0/H1) before running the experiment. Statistical comparison of correctness rates computed. Hypothesis confirmed or rejected with documented evidence.

---

### F-18 · Metrics Computation & Failure Mode Analysis
| Field | Detail |
|---|---|
| **Sprint** | S5 |
| **KSB** | K23 · K26 · S2 · S3 · S22 |
| **Status** | `Planned` |

**Problem Statement**
The four evaluation metrics in the project sign-off must be computed from JSONL logs and documented. Failure mode categorisation provides the qualitative analysis layer the report needs alongside the quantitative metrics.

**Acceptance Criteria**
1. SQL Execution Success Rate computed: percentage of benchmark prompts producing executable SQL.
2. Business Answer Correctness Rate computed: human-evaluated rate of answers matching expected result.
3. Query Latency p50 and p95 computed across both baseline and treatment benchmark runs.
4. Retry Rate computed: percentage of turns triggering at least one retry. Failure modes categorised by type (syntax error, wrong join, wrong aggregation, hallucinated column, semantic misunderstanding) and documented in `evaluation_report.md`.

---

## Sprint 6 — Hardening + Evidence Capture
`May 19–22 | 8 hrs`

---

### F-19 · Edge Case Hardening
| Field | Detail |
|---|---|
| **Sprint** | S6 |
| **KSB** | K13 · S15 · B2 |
| **Status** | `Planned` |

**Problem Statement**
Unhandled exceptions during a presentation or assessor demo would undermine credibility. Key edge cases identified during development must be explicitly tested and handled before evidence is captured.

**Acceptance Criteria**
1. Empty result set: informative message displayed ("No data found for this query"), not a blank panel.
2. Malformed LLM output (SQL delimiter missing): graceful fallback message displayed, not a Python stack trace.
3. DuckDB execution timeout: error surfaced to user with a suggestion to simplify the query.
4. Conversation history exceeding context limit: oldest turns pruned automatically with user notification. All four edge cases tested and passing.

---

### F-20 · Evidence Capture & Report Outline
| Field | Detail |
|---|---|
| **Sprint** | S6 |
| **KSB** | K6 · K14 · K28 · S24 · B2 |
| **Status** | `Planned` |

**Problem Statement**
The AM1 report and presentation require specific evidence artefacts. Capturing these systematically before the report writing phase prevents gaps and ensures the report is written from evidence, not memory.

**Acceptance Criteria**
1. Screen recording of end-to-end demo captured (minimum 5 minutes, covering multi-turn conversation, dual-audience output, SQL inspection, and chart rendering).
2. 8 key screenshots taken and labelled: UI overview, business output panel, SQL panel, chart output, JSONL log extract, evaluation results table, retry loop trigger, schema dictionary.
3. JSONL log summary statistics extracted: total turns, overall SQL success rate, average latency, retry rate, and correctness rate.
4. Report outline drafted with section headings and KSB mappings identified per section. Ready for report writing phase from May 23.

---

## Sprint Progress Summary

| Sprint | Features | Status |
|---|---|---|
| S1 — Foundation: Data & Environment (Apr 16–20) | F-01 · F-02 · F-03 · F-04 · F-05 | F-01 ✅ · F-02 ✅ · F-03 ✅ · F-04 ✅ · F-05 ✅ |
| S2 — NL2SQL Core (Apr 21–27) | F-06 · F-07 · F-08 · F-09 | F-06 ✅ · F-07 ✅ · F-08 ✅ · F-09 ✅ · Prompt v1.2 frozen |
| S3 — Agentic Loop + Conversation History (Apr 28–May 4) | F-10 · F-11 · F-12 | 📋 Planned |
| S4 — Streamlit UI + JSONL Logging (May 5–11) | F-13 · F-14 · F-15 | 📋 Planned |
| S5 — Evaluation + Hypothesis Testing (May 12–18) | F-16 · F-17 · F-18 | 📋 Planned |
| S6 — Hardening + Evidence Capture (May 19–22) | F-19 · F-20 | 📋 Planned |

**Sprint 2 closure notes (2026-05-10):**
15-query manual test suite validated under prompt v1.1 (10 PASS, 1 FAIL, 1 PARTIAL, 2 DIVERGE, 1 N/A).
FP-01 (P4 fragment) resolved by v1.1. FP-02 (is_volume_outlier inconsistency) and FP-03 (DISTINCT fan-out)
fixed in v1.2 via schema enrichment (ADR-037) + prompt update (ADR-038). FP-04 (ISO/calendar boundary)
documented in schema v1.2 (ADR-039). Prompt v1.2 frozen as Sprint 5 evaluation baseline.

✅ Validated · 🔨 Building · 🧪 Testing · 📋 Planned
