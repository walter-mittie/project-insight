# Sprint 2 Validation Report
## Project Insight : Agentic Conversational BI
### F-08 · Chain-of-Thought NL2SQL Generation — 15-Query Manual Test Suite

**Sprint:** 2
**Date:** 2026-01-16 (test run) / 2026-01-17 (validation)
**Model:** gemini-2.5-flash | **Prompt version tested:** v1.1
**Prompt version issued at closure:** v1.2

---

## 1. Methodology

The validation followed a ground-truth-first approach to avoid anchoring
bias from the LLM output:

1. Hand-wrote ground-truth SQL for all 15 queries in DuckDB UI,
   independently of any LLM output.
2. Validated each ground-truth query against the schema data dictionary
   (v1.1): constraints C1–C6, flag exclusion patterns (Section 7), KPI
   computation patterns P1–P4 (Section 5), and join patterns A/B (Section 8).
3. Ran the 15-query test suite via `tests/15_prompts.py` against the live
   pipeline (schema injection → Gemini 2.5 Flash → SQL extraction → DuckDB
   execution).  Full output captured in `15_prompts_llm_output.md`.
4. Compared LLM-generated SQL against validated ground truth per query.
   Scored as PASS / FAIL / PARTIAL FAIL / DIVERGE / N/A.
5. Identified failure patterns (FP-XX) from divergences.  Designed and
   implemented prompt v1.2 fixes for addressable patterns.

This methodology evidences K23 (model evaluation), K26 (experiment design),
S22 (critical evaluation of test data), and K7 (analysis of test results).

---

## 2. Query Categories (F-08 AC3)

| Category | Queries | Tests |
|---|---|---|
| Cat 1 — Single-table filter | Q01, Q02, Q03 | Basic WHERE, COUNT DISTINCT, TOP-N |
| Cat 2 — Aggregation / KPI | Q04, Q05, Q06 | Channel agg, P1 volume share, P4 price index |
| Cat 3 — Multi-table join | Q07, Q08, Q09 | Region×category, Pattern B cross-table, P3 distribution |
| Cat 4 — Ambiguous FMCG term | Q10, Q11, Q12 | "Revenue" disambiguation, "top N brands", out-of-vocab entity |
| Cat 5 — Time-period filter | Q13, Q14, Q15 | Year comparison, month filter, H2 weekly trend |

---

## 3. Results Summary

| Verdict | Count | Queries |
|---|---|---|
| PASS | 10 | Q01, Q02, Q03, Q04, Q05, Q06, Q07, Q09, Q13, Q14 |
| FAIL | 1 | Q11 |
| PARTIAL FAIL | 1 | Q08 |
| DIVERGE | 2 | Q10, Q15 |
| N/A | 1 | Q12 |

**Execution success rate:** 15/15 (100%) — all queries produced parseable
SQL that executed without error against DuckDB.

**Business answer correctness rate (v1.1):** 10/14 scoreable queries (71.4%).
Excludes Q12 (out-of-vocab, N/A).

---

## 4. Per-Query Verdicts

### Q01 — How many distinct SKUs were sold in Q1 2024?  ✅ PASS
Both GT and LLM produce equivalent `COUNT(DISTINCT product_id)` with
`year = 2024 AND quarter = 1`.  LLM correctly identified no flag exclusions
needed for an existence check.  Result: 497 distinct SKUs.

### Q02 — Top 10 SKUs by net revenue in 2025, active only?  ✅ PASS
Both apply `is_active = TRUE`, `is_zero_price = FALSE`, `year = 2025`.
Both group by `(product_id, sku_name)`, order desc, limit 10.  LLM did
not apply `is_volume_outlier` here (correctly per v1.1 schema).

### Q03 — Total incremental volume from promo in 2024?  ✅ PASS
Both apply `is_volume_outlier = FALSE`.  LLM defensively adds
`is_promoted = TRUE` (redundant — `incremental_volume = 0` for non-promoted
rows by schema definition) and correctly cites C1 in reasoning.  Result:
~17.2M units.

### Q04 — Gross revenue and trade discount by channel in 2025?  ✅ PASS
Equivalent.  Both join dim_customer, apply `is_zero_price = FALSE`, group
by channel.

### Q05 — NitroBoost volume market share in 2024 by quarter?  ✅ PASS
Both apply P1 correctly: `SUM(brand_volume_units) * 100.0 / NULLIF(...)`.
Both filter `is_vol_violation = FALSE`.  LLM explicitly cites grain-locked
column warning and recomputes from components.

### Q06 — Price index for Dairy across all banners in 2025?  ✅ PASS
**FP-01 RESOLVED.** Under v1.0 this query produced an incomplete SQL fragment
(bare P4 expression without SELECT/FROM wrapper).  Under v1.1 the LLM
produces a complete CTE with `SELECT DISTINCT brand, sub_category, category
FROM dim_product`, applies P4 formula correctly, and returns `price_index =
100.07`.  This is the primary success story of the v1.0 → v1.1 iteration.

### Q07 — Net revenue by region and category in Q4 2025?  ✅ PASS
Equivalent three-table join.  LLM explicitly anticipates NULL region for
eCommerce customers in its reasoning — strong self-awareness.

### Q08 — Grocery: net revenue and volume share by brand in 2025?  ⚠️ PARTIAL FAIL
Two issues:
- **FP-02:** LLM applied `is_volume_outlier = FALSE` on the sales side for
  net_revenue — over-broad per v1.1 schema (schema did not list revenue under
  `is_volume_outlier` exclusion).  Revenue numbers are lower than GT by the
  outlier-row contribution.
- **FP-03:** LLM joined `fact_market` to `dim_customer` on banner without
  DISTINCT.  dim_customer has 18–28 customer rows per Grocery banner.  The
  fan-out inflates both numerator and denominator by customer count, preserving
  the ratio, but the share becomes customer-count-weighted rather than a clean
  total.  GT correctly uses `SELECT DISTINCT banner, channel FROM dim_customer`.
Pattern B structure is otherwise correct: dual pre-aggregation, 3-key join.

### Q09 — Numeric distribution for Snacks by banner in 2024?  ✅ PASS
Both use P3 pattern with `SELECT DISTINCT sub_category, category FROM
dim_product`.  Equivalent results.

### Q10 — Total revenue by brand in 2024?  ↔️ DIVERGE (FP-02)
LLM correctly disambiguates "revenue" as net_revenue_gbp.  However, applies
`is_volume_outlier = FALSE` — same FP-02 as Q08.  Revenue totals are lower
than GT.  Divergence is interpretive: the LLM's derivational reasoning is
correct business logic but was not codified in the v1.1 schema.  Resolved by
schema enrichment in v1.2 (ADR-037).

### Q11 — Market share of top 3 brands in Beverages?  ❌ FAIL (FP-03)
Interpretive divergence (GT uses top-3 brand×sub_category combos; LLM uses
top-3 brands aggregated across sub-categories) PLUS a silent correctness
failure.  The LLM's `BrandVolumeInBeverages` CTE joins `fact_market` to
`dim_product` on `(brand, sub_category)` without DISTINCT — SKU-count
fan-out inflates brand volumes.  The denominator CTE
(`CorrectCategoryMarketVolume`) correctly uses `SELECT DISTINCT` to
de-duplicate.  Result: inflated numerator / correct denominator → brand
shares sum to 102.41% (LeafRitual 45.55% + NitroBoost 28.51% + PurePulse
28.35%).  A sum exceeding 100% is the mathematical smoking gun of the
fan-out.

### Q12 — Average price of Dairy products sold through Tesco?  ⚖️ N/A
"Tesco" is a real-world UK grocer not present in the 15 synthetic banners.
Both GT and LLM query `banner = 'Tesco'` and receive empty/NaN results.
Neither implementation detects the out-of-vocab entity.  LLM uses
`AVG(avg_shelf_price_gbp)` (simple average); GT uses
`SUM(brand_value)/SUM(brand_volume)` (volume-weighted average) — different
approaches, but both return empty so no numerical comparison possible.
Out-of-vocab entity detection is a future improvement, not a Sprint 2 scope.

### Q13 — Compare net revenue and volume by category, 2024 vs 2025?  ✅ PASS
Both use CASE-WHEN for metric-specific flag exclusion (is_zero_price for
revenue, is_volume_outlier for volume).  LLM produces long-format output
(12 rows); GT uses DuckDB PIVOT for wide format (6 rows).  Same data,
different presentation.

### Q14 — Total net revenue by channel in January 2025?  ✅ PASS
Equivalent.  Both filter `year = 2025, month = 1, is_zero_price = FALSE`,
group by channel, order by revenue descending.

### Q15 — Weekly volume trend for Confectionery in H2 2025?  ↔️ DIVERGE (FP-04)
LLM follows data labels strictly: `year = 2025 AND quarter IN (3, 4)` picks
up `week_date = 2024-12-30` (ISO week 1 of 2025, calendar Q4 of 2024).
GT applies defensive filter `week_number > 1` to exclude this anomalous row.
Both approaches are defensible.  Root cause is a data-design mismatch (ISO
year + calendar quarter), not a prompt or model issue.  Documented in
schema_data_dictionary.md v1.2 (ADR-039).

---

## 5. Failure Pattern Register

| ID | Pattern | Severity | Queries | Fix | ADR |
|---|---|---|---|---|---|
| FP-01 | P4 price index produces incomplete SQL fragment | High | Q06 | **RESOLVED** in v1.1 | — |
| FP-02 | `is_volume_outlier` inconsistently applied to revenue | Medium | Q08, Q10 | Schema v1.2 + prompt v1.2 | ADR-037 |
| FP-03 | DISTINCT pre-aggregation omitted on finer-grain dimension join | High | Q08, Q11 | Prompt v1.2 Step 2 rule | ADR-038 |
| FP-04 | ISO/calendar year boundary anomaly | Low | Q15 | Schema v1.2 note | ADR-039 |

---

## 6. Prompt Iteration Narrative

The Sprint 2 prompt evolved through three versions:

**v1.0 (2026-01-12):** Initial CoT instruction.  Pre-emptive design based on
known NL2SQL failure modes.  Addressed flag filter omission, revenue ambiguity,
and C3 join pattern.

**v1.1 (2026-01-15):** Aligned with schema v1.1.  Added grain-locked column
warning, P1–P4 recomputation instruction, and Pattern A/B selection criteria.
Directly resolved FP-01 (Q06 P4 fragment failure → complete CTE-based SQL).

**v1.2 (2026-01-16):** Aligned with schema v1.2.  Added DISTINCT fan-out
prevention rule (FP-03 fix) and strengthened Section 7 adherence instruction
(FP-02 fix).  Frozen as Sprint 5 evaluation baseline.

This three-step iteration demonstrates empirical prompt engineering: observe
failure → diagnose root cause → design minimal fix → verify.  Each iteration
is traceable via the prompt log, the ADR entries, and this validation report.

---

## 7. Sprint 2 Closure Decision

All four Sprint 2 features (F-06, F-07, F-08, F-09) are Validated.  The
15-query manual test suite satisfies F-08 AC3.  The prompt log (v1.0 → v1.1
→ v1.2) satisfies F-08 AC4.  Prompt v1.2 is frozen as the Sprint 5 baseline.

**Evidence artefacts produced:**
- `tests/15_prompts.py` — test runner script
- `15_prompts_llm_output.md` — LLM output (v1.1 run, 2026-01-16)
- `15_prompt_manual_sql_validation.md` — hand-written ground-truth SQL
- `docs/sprint_2_validation_report.md` — this document
- `docs/prompt_log.md` — v1.0 / v1.1 / v1.2 entries with FP register
- `docs/decision_log.md` — ADR-037, ADR-038, ADR-039

**Pending for Sprint 5:**
- Re-run 15-query suite (or expanded 20-query benchmark) under v1.2 to
  verify FP-02 and FP-03 are resolved.  This is Sprint 5 scope (F-16 AC1)
  and intentionally not done in Sprint 2 to maintain a clean sprint boundary.
