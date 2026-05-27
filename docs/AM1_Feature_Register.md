
# Project Insight - Agentic Conversational BI: LLM-Driven Ad-Hoc Data Exploration

> **By:** Manu Mohandas
> **Build window:** Jan 03 – Feb 13, 2026

Update the **Status** field at the start and end of each sprint.
Valid statuses: `Planned` / `Building` / `Testing` / `Validated`

**KSB colour key:** K = Knowledge | S = Skill | B = Behaviour

---

## Sprint 1 — Foundation: Data & Environment
`Jan 03–09 | 18 hrs`

---

### F-01 · Synthetic FMCG Dataset Generation
| Field      | Detail                    |
| ---------- | ------------------------- |
| **Sprint** | S1                        |
| **KSB**    | K5 · K13 · S9 · S10 · S17 |
| **Status** | `Validated`               |

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
| Field      | Detail                              |
| ---------- | ----------------------------------- |
| **Sprint** | S1                                  |
| **KSB**    | K3 · K5 · K13 · S2 · S9 · S17 · S22 |
| **Status** | `Validated`                         |

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
| Field      | Detail                |
| ---------- | --------------------- |
| **Sprint** | S1                    |
| **KSB**    | K13 · K14 · S15 · S25 |
| **Status** | `Validated`           |

**Problem Statement**
The system requires zero-infrastructure OLAP query execution without a database server, eliminating deployment complexity and data egress risk. DuckDB operates against the clean Parquet layer produced by preprocessing, ensuring the query engine always runs on validated, quality-resolved data.

**Acceptance Criteria**
1. Clean Parquet files (`data/processed/`) loadable via DuckDB Python API in a single connection object. Raw files (`data/raw/`) never directly queried by the application.
2. Three benchmark queries (GROUP BY aggregation, multi-table JOIN, window function) each execute in under 2 seconds on the full ~2M row `fact_sales`.
3. Derived measure queries (e.g. market share computed from raw brand and category volumes) verified to return correct results against known expected values.
4. DuckDB selection over alternatives (Pandas, SQLite, cloud DW) documented with rationale in design notes.

---

### F-04 · Schema & Semantic Data Dictionary
| Field      | Detail        |
| ---------- | ------------- |
| **Sprint** | S1            |
| **KSB**    | K1 · K5 · S27 |
| **Status** | `Validated`   |

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
`Jan 10–16 | 22 hrs`

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
`Jan 17–23 | 22 hrs`

---

### F-10 · Self-Correction Agentic Retry Loop
| Field | Detail |
|---|---|
| **Sprint** | S3 |
| **KSB** | K1 · K13 · K23 · S15 |
| **Status** | `Validated` |

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
| **Status** | `Validated` |

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
| **Status** | `Validated` |

**Problem Statement**
Non-technical FMCG users need answers in plain English, not raw tabular output. A dedicated second LLM call generates a business-language explanation of the result, serving the non-technical audience explicitly.

**Acceptance Criteria**
1. Second Gemini call receives query result DataFrame summary + original user question and returns narrative paragraph.
2. Narrative references specific figures from the result — not generic placeholder text.
3. Both narrative and SQL present in the response object returned to the orchestration layer.
4. Tested across 5 diverse query types: volume trend, market share, promotional uplift, price analysis, and multi-brand comparison.

---

## Sprint 4 — Streamlit UI + JSONL Logging
`Jan 24–30 Validated | 22 hrs`

---

### F-13 · Streamlit Conversational UI
| Field | Detail |
|---|---|
| **Sprint** | S4 |
| **KSB** | K6 · K14 · S15 · S24 · B2 |
| **Status** | `Validated` |

**Problem Statement**
The agentic NL2SQL pipeline has no user-facing interface. A conversational UI is required to demonstrate the end-to-end system to business and technical assessors, and to capture the multi-turn interaction pattern that distinguishes this project from a single-shot SQL generator.

**Acceptance Criteria**
1. Conversational thread renders turns in order with user and assistant roles visually distinct. User bubble right-aligned (teal), assistant response in a structured card with Q-badge, subtitle, and timestamp.
2. Chart keyword in user question highlighted via `_highlight_chart_keyword()` in the user bubble display.
3. Chart/table toggle rendered per response card. Toggle preference persists across subsequent questions in the same session. Toggle label matches resolved chart type (e.g. `'Pie chart / Table'`).
4. Spinner (`'Analysing…'`) visible during `run_turn()` call. Thread auto-scrolls to latest response.
5. ⟳ Refined badge shown on card header when `retry_count > 0`.
6. Empty-state chips (3 example questions) rendered on session start. Chip click submits the question.
7. Session resumption implemented as a three-state model: State 1 (Pending — dashed ChartPlaceholder boxes, input locked), State 2 (Running — progressive per-turn restore with spinner), State 3 (Complete — full charts visible, input re-enabled). Resumed divider shown between original and continued turns.
8. Manual Track B checklist completed: all items in Section 5 of `docs/sprint_4_validation_report.md` marked PASS.

---

### F-14 · Dual-Audience Output Design
| Field | Detail |
|---|---|
| **Sprint** | S4 |
| **KSB** | K6 · K14 · S24 · B3 |
| **Status** | `Validated` |

**Problem Statement**
The response object contains both a natural language narrative (for business users) and raw SQL with execution metadata (for technical reviewers). Without explicit design, one audience is always disadvantaged. The dual-audience design must be the primary output pattern across the entire application.

**Acceptance Criteria**
1. Natural language narrative displayed by default, rendered in Lora serif font. Business user can interpret the answer without interacting with any UI control.
2. Technical panel: generated SQL displayed with execution metadata (latency ms, retry count, turn ID). Panel collapsible (collapsed by default). Summary label shows row count + latency.
3. Dark code block (`#1a2332` background) inside SQL expander for readability.
4. On `status == "error"`, `st.error()` shown with error stage message; no SQL expander rendered.
5. On `status == "success"` with empty narrative, `st.warning()` shown in narrative position.
6. Both panels populated from the same response dict. Tested with two distinct user personas across 5 query types.

---

### F-15 · JSONL Logging Infrastructure
| Field | Detail |
|---|---|
| **Sprint** | S4 |
| **KSB** | K6 · K23 · S17 · S24 |
| **Status** | `Validated` |

**Problem Statement**
Every interaction must be logged for reproducibility, audit, and Sprint 5 evaluation. JSONL format requires no schema migration as logging fields evolve, and is directly parseable for metric computation. The log must also support session resumption (State 1–3 in F-13) by providing a queryable record of prior turns.

**Acceptance Criteria**
1. Each turn logged as a single JSON line appended to `logs/interactions.jsonl` at the end of each turn.
2. **14 canonical log fields captured per turn:** `session_id`, `turn_id`, `timestamp`, `user_query`, `generated_sql`, `execution_time_ms`, `retry_count`, `row_count`, `success_flag`, `narrative_generated`, `history_truncated`, `error_stage`, `resumed`, `resumed_at`.
3. **2 ADR-042 chart audit fields captured per turn:** `suggested_chart_type` (Gemini annotation from NL2SQL layer), `rendered_chart_type` (final resolved type after priority chain). Total: 16 fields per entry.
4. `raw_nl2sql` and `raw_narrative` payloads intentionally excluded from log (too large for append-only log; only rendered outputs logged per ADR-041).
5. `logs/` directory auto-created on first write if absent (`_ensure_log_dir()`).
6. Log file persists across Streamlit sessions. Readable via standard Python `json` library without custom parser.
7. Log write failure raises `LogWriteError` (not an unhandled exception); Streamlit app displays warning and continues.
8. `load_past_sessions(log_path)` returns sessions grouped by `session_id`, sorted newest-first, for sidebar display.
9. `read_turns_from_jsonl(session_id, log_path)` returns successful, non-resumed turns sorted by `turn_id` ascending, for session restore.
10. All logging behaviours validated by `tests/sprint4_validation.py` Section 1 (13/13 automated tests passing).

---

## Sprint 5 — Evaluation + Hypothesis Testing
`Jan 31 – Feb 06, 2026 | 22 hrs`

---

### F-16 · Benchmark Prompt Suite Design
| Field      | Detail               |
| ---------- | -------------------- |
| **Sprint** | S5                   |
| **KSB**    | K5 · K23 · K26 · S22 |
| **Status** | `Validated`          |

**Problem Statement**
Systematic evaluation requires a pre-defined, reproducible set of test prompts covering the full range of query complexity. Without a benchmark suite, evaluation is anecdotal rather than scientific and not defensible in the assessment report. The Sprint 2 15-query suite provides a validated starting point that should be extended rather than discarded.

**Acceptance Criteria**
1. **20 benchmark prompts** across 5 complexity tiers: (1) single-table filter, (2) aggregation, (3) multi-table join, (4) ambiguous FMCG business term, (5) multi-turn contextual chain. Implemented as **15 prompts carried forward from Sprint 2** (tier coverage already validated; ground-truth SQL available) **+ 5 new prompts** explicitly targeting known failure modes: FP-02 (`is_volume_outlier` on revenue), FP-03 (DISTINCT fan-out), FP-05 and FP-06 (from Sprint 3 narrative failures), and the promotional uplift query class.
2. Expected result or expected SQL pattern defined for each prompt and documented in `docs/benchmark.json`. The 15 Sprint 2 prompts already have ground-truth SQL from `15_prompt_manual_sql_validation.md`; only the 5 new prompts require new ground-truth authoring.
3. Benchmark suite runnable via a single script: `python run_benchmark.py`. Script writes results to the same JSONL format established in F-15, enabling direct use by F-18 metrics computation without format conversion.
4. Benchmark output per turn includes all 16 F-15 log fields plus `condition` (`'baseline'` or `'treatment'`), enabling side-by-side comparison in F-17.
5. Suite covers both baseline and treatment conditions defined in F-17 and produces structured output suitable for metric computation in F-18.

---

### F-17 · Baseline vs Treatment Experiment
| Field      | Detail                   |
| ---------- | ------------------------ |
| **Sprint** | S5                       |
| **KSB**    | K3 · K26 · S2 · S3 · S22 |
| **Status** | `Validated`              |

**Problem Statement**
The core hypothesis — that semantic data dictionary injection reduces SQL semantic errors — must be tested empirically. A controlled experiment with two conditions provides the scientific evidence base required by the report.

**Sprint-start dependency:** Sprint 4 validation identified two code gaps. Both must be fixed and `tests/sprint4_validation.py` must reach 51/51 before any experiment run. This ensures the chart type resolution layer is clean and the evaluation data is untainted. (Fix 1: remove `'top '` from `PROMPT_KEYWORDS['bar']`; Fix 2: add pie/scatter suffixes to `_make_subtitle()` — both are 1–2 line changes in `app.py`.)

**Acceptance Criteria**
1. Baseline condition defined: system prompt with schema table definitions only, no semantic data dictionary definitions, no KPI computation patterns, no disambiguation rules.
2. Treatment condition defined: system prompt with schema plus full semantic data dictionary (prompt v1.2 — frozen Sprint 2 baseline).
3. Both conditions run against all 20 benchmark prompts. Results recorded in `docs/experiment_results.csv` with `condition`, `prompt_id`, `tier`, and all F-18 metric fields.
4. Hypothesis stated formally (H0/H1) before running the experiment. H0: semantic data dictionary injection has no effect on SQL correctness rate. H1: treatment correctness rate > baseline correctness rate. Statistical comparison computed. Hypothesis confirmed or rejected with documented evidence.
5. **(Optional scope — include if time allows)** Chart type stability analysis: compare `suggested_chart_type` distributions across baseline and treatment conditions. Assess whether Gemini's chart annotation is more consistent than the keyword-based P1 heuristic on standard ranking queries (e.g. `'Top N brands…'`). This directly supports the ADR-042 design decision narrative in the report by providing empirical evidence for or against keyword-first resolution. If conducted, results documented in `docs/experiment_results.csv` as additional columns.

---

### F-18 · Metrics Computation & Failure Mode Analysis
| Field      | Detail                    |
| ---------- | ------------------------- |
| **Sprint** | S5                        |
| **KSB**    | K23 · K26 · S2 · S3 · S22 |
| **Status** | `Validated`               |

**Problem Statement**
The four evaluation metrics in the project sign-off must be computed from JSONL logs and documented. Failure mode categorisation provides the qualitative analysis layer the report needs alongside the quantitative metrics. The F-15 16-field JSONL log provides all raw data needed for metrics AC1–AC3 and retry rate (AC4) without additional instrumentation.

**Acceptance Criteria**
1. SQL Execution Success Rate computed: percentage of benchmark prompts producing executable SQL. Computable directly from `success_flag` in JSONL log.
2. Business Answer Correctness Rate computed: human-evaluated rate of answers matching expected result from `docs/benchmark.json`. Correctness assessed against ground-truth SQL output for the 15 carried-forward prompts; manual judgement for the 5 new prompts.
3. Query Latency p50 and p95 computed from `execution_time_ms` across both baseline and treatment benchmark runs.
4. Retry Rate computed from `retry_count > 0` across benchmark turns. Failure modes categorised by type and documented in `docs/evaluation_report.md`. **Six failure mode categories:** (1) syntax error, (2) wrong join, (3) wrong aggregation, (4) hallucinated column name, (5) semantic misunderstanding of FMCG term, (6) chart-type-override (cases where `rendered_chart_type` ≠ `suggested_chart_type` due to P1 keyword override — evidences ADR-042 priority chain behaviour in evaluation context).
5. **Chart type accuracy metric:** percentage of benchmark turns where `rendered_chart_type` matches `suggested_chart_type` (i.e. Gemini's annotation was not overridden by keyword or heuristic). Reported separately for baseline and treatment conditions. Metric is low-effort (both fields already in JSONL) and high-value: directly evidences the ADR-042 design decision and quantifies the impact of removing `'top '` from `PROMPT_KEYWORDS['bar']` (Fix 1 from Sprint 4 validation).

---

## Sprint 6 — Hardening + Evidence Capture
`Feb 07–13, 2026 | 8 hrs`

---

### F-19 · Edge Case Hardening
| Field      | Detail         |
| ---------- | -------------- |
| **Sprint** | S6             |
| **KSB**    | K13 · S15 · B2 |
| **Status** | `Validated`    |

**Problem Statement**
Unhandled exceptions during a presentation or assessor demo would undermine credibility. Key edge cases identified during development must be explicitly tested and handled before evidence is captured. Note: Sprints 3 and 4 pre-built several of these cases — the Sprint 6 task for those cases is verification and documentation, not re-implementation.

**Acceptance Criteria**
1. Empty result set (`row_count == 0`): informative message `"No data found for this query — try broadening the filters or rephrasing."` displayed in narrative position. Not a blank panel. Verify against current `app.py` handling and add explicit branch if absent.
2. Malformed LLM output (SQL delimiter missing): **verify** — handled by Sprint 3 retry loop and `error_stage='nl2sql'` path in `app.py`. Run the relevant `tests/test_agent.py` case to confirm. Document as pre-validated.
3. DuckDB execution timeout: error surfaced to user with suggestion `"Query timed out — try a simpler question."`. Requires implementation of a timeout wrapper (e.g. `concurrent.futures.ThreadPoolExecutor` with `timeout` parameter) in `src/executor.py`. This is the only substantial new implementation item in Sprint 6.
4. Conversation history exceeding context limit: oldest turns pruned automatically with user notification. **Verify** — fully implemented in F-11 (Sprint 3, `MAX_HISTORY_TURNS` pruning). Confirmed in Sprint 3 closure notes. Document as pre-validated.
5. **Apply Sprint 4 code fixes and confirm validation suite at 51/51:** (a) Remove `'top '` from `PROMPT_KEYWORDS['bar']` in `app.py` (Fix 1 — ADR-043); (b) add `' as a pie chart'`, `' as a scatter plot'`, `' as a scatter'` to `_make_subtitle()` strip list in `app.py` (Fix 2). Run `python tests/sprint4_validation.py` and confirm 51/51 before any evidence capture session.

---

### F-20 · Evidence Capture & Report Outline
| Field      | Detail                    |
| ---------- | ------------------------- |
| **Sprint** | S6                        |
| **KSB**    | K6 · K14 · K28 · S24 · B2 |
| **Status** | `Validated`               |

**Problem Statement**
The AM1 report and presentation require specific evidence artefacts. Capturing these systematically before the report writing phase prevents gaps and ensures the report is written from evidence, not memory.

**Acceptance Criteria**
1. Screen recording of end-to-end demo captured (minimum 5 minutes, covering: multi-turn conversation with contextual resolution, dual-audience output with SQL expander, chart rendering showing at least two different chart types, and session resumption State 1→3 transition).
2. **8 key screenshots taken and labelled:**
   - UI overview — empty state with 3 example chips
   - Business output panel — narrative visible, chart rendered (bar or line)
   - Chart type resolution — a pie or scatter chart triggered by a keyword query (demonstrating ADR-042 P1 keyword priority)
   - SQL expander open — showing generated SQL, latency ms, retry count, turn ID
   - JSONL log extract — showing all 16 fields per entry (14 canonical + 2 ADR-042 chart audit fields)
   - Evaluation results table — baseline vs treatment comparison from Sprint 5
   - Retry loop trigger — a question that caused at least one retry, showing ⟳ Refined badge
   - Session resumption — State 1 (Pending) view with dashed ChartPlaceholder boxes and locked input
3. JSONL log summary statistics extracted from the Sprint 5 benchmark runs: total turns logged, overall SQL success rate, average latency ms, retry rate, and correctness rate (from F-18). Formatted as a summary table for inclusion in the report.
4. Report outline drafted with section headings and KSB mappings identified per section. ADR-042 (chart type resolution design decision) included as a named section.

---

## Sprint Progress Summary

| Sprint                                                                                  | Features                         | Status                                                 |
| --------------------------------------------------------------------------------------- | -------------------------------- | ------------------------------------------------------ |
| S1 — Foundation: Data & Environment <br>(Planned: Jan 03–09 → Completed: Jan 10)        | F-01 · F-02 · F-03 · F-04 · F-05 | F-01 ✅ · F-02 ✅ · F-03 ✅ · F-04 ✅ · F-05 ✅             |
| S2 — NL2SQL Core <br>(Planned: Jan 10–16 → Completed: Jan 17)                           | F-06 · F-07 · F-08 · F-09        | F-06 ✅ · F-07 ✅ · F-08 ✅ · F-09 ✅ · Prompt v1.2 frozen |
| S3 — Agentic Loop + Conversation History <br>(Planned: Jan 17–23 → Completed: Jan 25)   | F-10 · F-11 · F-12               | F-10 ✅ · F-11 ✅ · F-12 ✅                               |
| S4 — Streamlit UI + JSONL Logging <br>(Planned: Jan 24–30 → Completed: Feb 04)          | F-13 · F-14 · F-15               | F-13 ✅ · F-14 ✅ · F-15 ✅                               |
| S5 — Evaluation + Hypothesis Testing <br>(Planned: Jan 31 – Feb 06 → Completed: Feb 10) | F-16 · F-17 · F-18               | F-16 ✅ · F-17 ✅ · F-18 ✅                               |
| S6 — Hardening + Evidence Capture <br>(Planned: Feb 07–13 → Completed: Feb 14)          | F-19 · F-20                      | F-19 ✅ · F-20 ✅                                        |
**Sprint 1 closure notes (2026-01-10):** F-01 (synthetic dataset): 73/73 manual validation checks passed across all four tables. dim_product: 552 rows, 497 active, 6 categories, 12 SKUs per brand–subcategory. dim_customer: 240 rows, 15 banners, structural NULLs (~15% territory, ~10% store_count) verified. fact_sales: ~2.3M rows, 104 ISO weeks (2024-01-01–2025-12-29), FK integrity confirmed. fact_market: ~44K rows at brand × sub_category × banner × week grain — mirrors Nielsen/Kantar panel licence convention; manufacturer_net_price_gbp deliberately excluded. F-02 (quality injection): all 8 quality issues (QI-01 through QI-08) injected and verified; data/raw/ originals unchanged — immutability confirmed. F-03 (EDA and preprocessing): all 5 boolean flags derived (is_zero_price, is_volume_outlier, is_vol_violation, is_zero_shelf_price), all 4 derived fact_market measures computed (market_share_volume_pct, market_share_value_pct, numeric_distribution_pct, price_index), 8 EDA plots generated, eda_report.md auto-generated with all quality-issue handling decisions documented. Key preprocessing decisions: Tukey outer fence IQR×3.0 for volume outlier detection; channel median (not mean) for store_count imputation; QI-05 NULL promotion_mechanic not imputed; QI-08 temporal gaps not interpolated. F-04 (schema data dictionary): all 4 clean-layer tables covered with semantic definitions, KPI formulas, sparseness patterns, and join guidance documented; schema injectable as plain text. F-05 (environment): folder structure, requirements.txt, .env.example, .gitignore, git init, README, Gemini API key verified. No open items — all 5 features Validated. Sprint 2 dependency confirmed: data/processed/ and docs/schema_data_dictionary.md ready for F-07 RAG injection.

**Sprint 2 closure notes (2026-01-17):** F-06 (Gemini API integration): API key loaded from `.env`, model version pinned in config, HTTP errors and rate-limit responses handled gracefully — not raised as unhandled exceptions. Single test prompt returning valid parsed text confirmed. F-07 (RAG schema injection): full schema data dictionary (~2,600 tokens) injected into system prompt on every call; token count verified within Gemini 2.5 Flash context window; schema file-based so updates require no code changes; model references correct column names on at least 10 test queries. F-08 (chain-of-thought NL2SQL): 15-query manual test suite run under prompt v1.1 — 10 PASS, 1 FAIL, 1 PARTIAL, 2 DIVERGE, 1 N/A (10/14 scoreable = 71.4% correctness). Prompt iteration: v1.0 (2026-05-07) — initial CoT instruction, addressed flag filter omission and C3 join pattern; v1.1 (2026-05-08) — added grain-locked column warning, P1–P4 recomputation instruction, Pattern A/B selection criteria; directly resolved FP-01 (Q06 P4 fragment — bare expression replaced with complete CTE-based query). v1.2 (2026-05-10) — added DISTINCT fan-out prevention rule (FP-03 fix, ADR-038) and strengthened Section 7 flag adherence instruction (FP-02 fix, ADR-037); schema v1.2 updated with temporal column note for FP-04 (ADR-039). Prompt v1.2 frozen as Sprint 5 evaluation baseline. F-09 (SQL execution layer): DuckDB connection established, results returned as pandas DataFrame on success, execution errors caught and returned as structured dict with `error_type` and `error_message` fields — not raised. Failure pattern register: FP-01 resolved v1.1; FP-02 (is_volume_outlier inconsistency) and FP-03 (DISTINCT fan-out) fixed in v1.2; FP-04 (ISO/calendar boundary anomaly on Q15) documented in schema — root cause is data-design mismatch, not a prompt issue. Evidence artefacts: `tests/15_prompts.py`, `15_prompts_llm_output.md`, `15_prompt_manual_sql_validation.md`, `docs/prompt_log.md` (v1.0/v1.1/v1.2 entries), `docs/decision_log.md` (ADR-037, ADR-038, ADR-039). Pending for Sprint 5: re-run benchmark under v1.2 to confirm FP-02 and FP-03 resolved — intentionally deferred to maintain clean sprint boundary.

**Sprint 3 closure notes (2026-01-25):** F-10 (self-correction retry loop): 10/10 unit tests passing (`tests/test_agent.py::TestRetryLoop` — hard cap enforcement, correction signal content, generate_sql call count per retry). Live wiring check confirmed `retry_count=0` and `turn_index` present in response dict on clean query. Hard cap MAX_RETRIES=2 (3 total attempts) enforced per ADR-031 — no infinite retry path. Correction signal format: original question + `[CORRECTION — Attempt N of 3]` block containing `error_type`, `error_message`, and failed SQL — history NOT modified during retries, correction signal appended to question string only. F-11 (conversation history): 11/11 unit tests passing. 5-turn multi-turn contextual test passed — T1: "top 3 brands by net revenue 2025"; T2–T5: progressively dependent follow-ups; model correctly resolved "those brands" / "that brand" across all turns using injected `<conversation_history>` block. History copy-on-entry pattern prevents caller list mutation; history appended only on successful turns, not on failures. `turn_index` is 0-based internally — Sprint 4 Streamlit displays `turn_index+1`. F-12 (narrative generation): 13/13 unit tests passing. 5 query types tested live (volume trend, market share, promotional uplift, price analysis, multi-brand comparison). AC2 manual review: 4/5 narratives cited specific figures — PASS. One exception: N3 (promotional uplift) generated a narrative but the underlying SQL formula was incorrect (logged as FP-05 in `prompt_log.md` — SQL generation issue, not a narrative layer issue). Narrative prompt updated v1.0→v1.1 (synthesise-not-enumerate rule, directional language rules, MAX_SUMMARY_ROWS 10→50). Additional failure pattern FP-06 (incorrect aggregation level on brand × channel queries) logged for Sprint 5 prompt iteration. `run_turn()` established as single orchestration entry point per ADR-040 — Sprint 4 Streamlit has no direct dependency on `nl2sql.py`, `executor.py`, or `narrative.py`.

**Sprint 4 closure notes (2026-02-04):** F-13 (Streamlit UI): automated tests passing (`sprint4_validation.py` §2–4). Manual Track B checklist (§5 of `sprint_4_validation_report.md`) completed — all items marked ✅ PASS. Session resumption (3-state model: Pending → Running → Complete) built beyond original F-13 AC scope; dashed ChartPlaceholder boxes, locked `st.chat_input`, progressive per-turn restore with spinner, and resumed-session divider all verified. Immediate user bubble pattern (two-rerun: user message echoed before spinner starts) implemented and confirmed. F-14 (dual-audience): dual-panel layout built and verified — business user sees Lora serif narrative paragraph + chart; technical reviewer expands collapsible SQL panel showing generated SQL, latency ms, retry count, and turn ID without mode switching. `st.error()` replaced with `st.toast()` on all error paths. F-15 (JSONL logging): 13/13 automated tests passing (`sprint4_validation.py` §1). Log schema expanded from 9 fields (original spec) to 16 fields (14 canonical + 2 ADR-042 chart audit fields: `suggested_chart_type`, `rendered_chart_type`). `raw_nl2sql` and `raw_narrative` intentionally excluded per ADR-041. `load_past_sessions()` and `read_turns_from_jsonl()` support session restoration; `LogWriteError` raised on write failure (non-crash). ADR-042 (chart type resolution): three-level priority chain built and validated — P1 prompt keyword → P2 Gemini annotation → P3 DataFrame heuristic → P4 default `'bar'`. `render_line()` temporal priority corrected: `quarter` (n_unique=4) correctly selected over `year` (n_unique=1) as x-axis. MODEL_FALLBACK updated from retired `gemini-1.5-flash` to `gemini-2.5-pro`. Two code gaps found by `sprint4_validation.py`: (1) `'top '` keyword over-fires on ranking queries — ADR-043 fix: remove from `PROMPT_KEYWORDS['bar']`; (2) `_make_subtitle()` strip list omits `' as a pie chart'`, `' as a scatter plot'`, `' as a scatter'` suffixes. Both are 1–2 line fixes in `app.py`. Both applied and re-run confirmed 54/54 (up from 51/51 original spec — suite expanded by 3 ADR-042 tests during Sprint 4). Apply fixes before Sprint 5 experiment runs to ensure evaluation data is untainted.

**Sprint 5 closure notes (2026-02-10):** F-16 (benchmark suite): 20-prompt benchmark built across 5 tiers (T1 single-table filter ×3, T2 aggregation KPI ×4, T3 multi-table join ×5, T4 ambiguous FMCG term ×4, T5 complex/multi-turn ×4). 15 prompts carried forward from Sprint 2 with frozen ground-truth SQL; 5 new prompts targeting FP-02, FP-03, FP-05, FP-06, and the promotional uplift query class. docs/benchmark.json complete with ground-truth SQL for all 20 prompts. run_benchmark.py operational at project root — no Streamlit dependency; writes to JSONL format with condition field. Sprint 4 code fixes (ADR-043: remove 'top ' from PROMPT_KEYWORDS['bar']; _make_subtitle() pie/scatter suffixes) applied before any experiment run, confirming 54/54 tests passing as pre-experiment gate. F-17 (hypothesis testing): baseline condition defined (721-character stripped schema — table and column names only, no semantic definitions); treatment condition = prompt v1.2 (frozen Sprint 2). Both conditions run against all 20 prompts. H0: schema injection has no effect on correctness. H1 (one-tailed): treatment correctness > baseline. McNemar's exact test (n discordant pairs=7): p=0.0625 — fails to reject H0 at α=0.05. Post-hoc power analysis: ~34% power at n=20; ~40 prompts needed for 87% power. Key secondary finding: retry rate 4→0 independently supports H1. New failure pattern FP-07 identified: treatment model over-applied exclusion flags (is_zero_price, is_volume_outlier) to COUNT(DISTINCT product_id) on Q01 — model generalised correctly-learned schema rules to cardinality aggregations where they are semantically irrelevant. Logged in prompt_log.md; not fixed in v1.2 (evaluation prompt frozen). F-18 (metrics and failure modes): baseline correctness 14/20=70.0%; treatment correctness 19/20=95.0%; baseline mean exec 43.8ms; treatment mean exec 37.0ms; treatment p95 72.1ms. Tier 4 produced largest gain (+50pp: 2/4→4/4) — schema resolves FMCG terminology ambiguity. AC5 (chart type match rate) deferred to Sprint 6 — benchmark runner uses sentinel value 'benchmark' for rendered_chart_type; metric computable only from live logs/interactions.jsonl. Evidence artefacts in place: docs/benchmark.json, docs/experiment_results.csv (40 rows, all sql_correct populated), logs/benchmark_results.jsonl (40 entries), docs/sprint_5_evaluation_report.md (11 sections, 3,566 words). schema_override parameter added to generate_sql() and run_turn() — backward-compatible, no existing tests affected.

**Sprint 6 closure notes (2026-02-14):** F-19 (edge case hardening): three deprecation fixes applied — Fix A: st.plotly_chart(use_container_width=True) replaced with width='stretch' in render_bar(); Fix B: components.html scroll helper removed and import streamlit.components.v1 as components removed (grep confirms no remaining components. calls); Fix C: execute_with_timeout() wrapper implemented in src/executor.py using concurrent.futures.ThreadPoolExecutor(max_workers=1) with QUERY_TIMEOUT_SECONDS=30 — TimeoutError caught by existing except Exception block, surfaces as error_type='TimeoutError' in response dict without raising. Empty result set guard added to _render_response_card(): df.empty branch shows st.info() before chart dispatch. AC2 (malformed LLM output) and AC4 (history pruning) confirmed pre-validated via Sprint 3. RND-05 test mock gap fixed: go.Bar assertion replaced with px.bar assertion (wraps=px.bar) — suite reaches 54/54. ADR-044 added to decision_log.md (MODEL_FALLBACK = "gemini-2.5-pro"; free-tier 20 RPD constraint documented). FP-07 added to prompt_log.md (flag over-application; v1.3 remediation proposed, not implemented). F-20 (evidence capture): 8 screenshots captured after clean app startup (no deprecation warnings). ss_07 sourced from logs/benchmark_results.jsonl baseline entries (4 prompts: Q06, Q08, Q09, Q12 with retry_count=1, success_flag=true) — treatment condition produced 0 live retries (schema effectiveness). Screen recording not produced — submission portal accepts Word + PowerPoint only; all recording requirements covered by 8 screenshots. AC5 chart type match rate computed from logs/interactions.jsonl: 83.3% on successful turns (5/6); single mismatch is P1 keyword override of Gemini annotation on "Compare the numbers for last year" — ADR-042 working as designed. All 20 features (F-01 through F-20) Validated. Project build complete. Report handover prompt v2 generated with all BCS mandatory elements confirmed present.

✅ Validated · 🔨 Building · 🧪 Testing · 📋 Planned
