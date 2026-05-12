# Prompt Log — NL2SQL Chain-of-Thought Prompts
**AM1: Agentic Conversational BI | F-08 | Manu Mohandas / TCS**

---

## Purpose

This log records every change to the NL2SQL system prompt.  One entry per
version.  Maintained per F-08 AC4 requirement.

Each entry records:
- **Version** — semantic version (v1.0, v1.1, …)
- **Date** — when the change was made
- **Change made** — what was altered in the prompt
- **Failure pattern that prompted the change** — the observed model behaviour
  that necessitated the revision
- **Location** — the constant in source code holding this prompt version

---

## v1.0 — Initial prompt (Sprint 2)

**Date:** 2026-05-07

**Change made:**
Initial CoT instruction block authored.  Four-step structure:
1. Identify tables and columns
2. Check semantic constraints C1–C6
3. Clarify ambiguous FMCG terms (revenue = gross vs net; time periods)
4. Write SQL inside ```sql ... ``` block

Rules added:
- Flag exclusion patterns required (is_zero_price, is_vol_violation etc.)
- C3 join pattern enforced: fact_sales must be aggregated before joining fact_market
- Time period interpretation: "last year" = 2025, "Q3" = quarter = 3
- No SELECT * on fact tables
- SQL terminated with semicolon
- Reasoning must precede the ```sql block

**Failure pattern that prompted the change:**
N/A — this is the initial version.  Prompt structure designed pre-emptively
based on known model failure modes for NL2SQL tasks:
- Models frequently omit flag filters when not explicitly instructed
- "Revenue" is ambiguous in FMCG without explicit disambiguation
- fact_sales → fact_market direct joins are a known hallucination risk
  given the grain mismatch (C3)

**Location:** `src/nl2sql.py` → `COT_INSTRUCTION` constant

---

## v1.1 — Schema v1.1 alignment (Sprint 2)

**Date:** 2026-05-08

**Change made:**
COT_INSTRUCTION updated to align with schema_data_dictionary.md v1.1.
Three additions to Step 2 and two additions to Step 4 rules:

Step 2 additions:
1. Grain-locked column warning — explicit instruction to NEVER SUM or AVG
   the pre-computed columns (market_share_volume_pct, market_share_value_pct,
   numeric_distribution_pct, price_index) across any dimension. Directs model
   to recompute from numerator/denominator components using P1–P4 patterns
   in Section 5 of the schema.
2. Pattern A vs Pattern B join selection — explicit decision criteria:
   Pattern A (4-key join including sub_category) for sub_category-level queries;
   Pattern B (3-key join with dual pre-aggregation of both fact_sales AND
   fact_market) for brand-total queries. Explicit warning against joining
   a 3-key sales_agg to the 4-key fact_market grain.

Step 4 rule additions:
3. KPI queries must use P1–P4 computation patterns, never the grain-locked
   pre-computed columns for aggregated queries.
4. Cross-table join queries must select Pattern A or B as described in Step 2.

**Failure pattern that prompted the change:**
Schema_data_dictionary.md was enriched to v1.1 in a parallel session
("Project Insight | Schema Documentation") with two new sections:
- Section 5: KPI Computation Patterns (P1–P4) with worked example showing
  why AVG(share) produces incorrect results
- Section 8: Expanded from one join example to Pattern A (sub_category-level)
  and Pattern B (brand-total with dual pre-aggregation)

The v1.0 COT_INSTRUCTION referenced C1–C6 constraints but did not address
the grain-locked column risk or the Pattern A/B selection. Without these
additions, the model could produce arithmetically incorrect KPI aggregations
(summing percentages across weeks) and fan-out joins (3-key to 4-key grain
mismatch) — both silent correctness failures that would pass SQL execution
but return wrong business answers.

**Location:** `src/nl2sql.py` → `COT_INSTRUCTION` constant

---

## v1.1 — Empirical results (15-query manual test suite)

**Date:** 2026-05-09 (test run) / 2026-05-10 (validation completed)

**Test suite:** 15 queries across 5 categories (F-08 AC3):
- Cat 1: Single-table filter (Q01–Q03)
- Cat 2: Aggregation / KPI (Q04–Q06)
- Cat 3: Multi-table join (Q07–Q09)
- Cat 4: Ambiguous FMCG term (Q10–Q12)
- Cat 5: Time-period filter (Q13–Q15)

**Model:** gemini-2.5-flash | **Run timestamp:** 2026-05-09 16:53:29

**Methodology:** Ground-truth SQL hand-written in DuckDB UI for all 15
queries, independently of LLM output.  Ground truth validated for schema
correctness against C1–C6, flag exclusion patterns (Section 7), and KPI
patterns P1–P4.  LLM output then compared against validated ground truth
per query.

### Results summary

| Verdict | Count | Queries |
|---|---|---|
| PASS | 10 | Q01, Q02, Q03, Q04, Q05, Q06, Q07, Q09, Q13, Q14 |
| FAIL | 1 | Q11 (FP-03: silent correctness — brand shares sum to 102.41%) |
| PARTIAL FAIL | 1 | Q08 (FP-02 + FP-03: no DISTINCT on dim_customer; over-broad is_volume_outlier) |
| DIVERGE | 2 | Q10 (FP-02), Q15 (FP-04) |
| N/A | 1 | Q12 (out-of-vocab entity "Tesco" — not in synthetic banner list; both GT and LLM return empty) |

### Execution success rate

15/15 queries (100%) produced parseable SQL that executed without error
against DuckDB.  No delimiter extraction failures.  No ParserExceptions.

### Failure patterns identified

**FP-01 — RESOLVED by v1.1.**
Q06 (P4 price index): Under v1.0 the model produced an incomplete SQL
fragment — a bare expression without SELECT/FROM wrapper, causing a
ParserException.  Under v1.1 the model produces a complete CTE-based query
with proper P4 formula, DISTINCT fan-out prevention on the dim_product
mapping, and correct flag filters.  Returns `price_index = 100.07` for
Dairy 2025.  This is the primary success story of the v1.0 → v1.1 iteration.

**FP-02 — Inconsistent application of `is_volume_outlier` to revenue queries.**
The model applies `is_volume_outlier = FALSE` to revenue aggregations in
Q08 and Q10 but does NOT apply it in Q02, Q04, Q07, Q14 — all of which are
also revenue queries.  The inconsistency is non-deterministic: the same
semantic context produces different filter decisions across queries.
Root cause: the model sometimes activates a derivational rule ("net_revenue
is derived from volume, so exclude outlier rows") that is not explicitly
stated in Section 7 of the schema.  Non-determinism on this semantic question
would confound Sprint 5 evaluation metrics.

**FP-03 — Failure to DISTINCT-collapse a finer-grain dimension before joining.**
Two manifestations:
- Q08 (mild): `JOIN dim_customer ON fm.banner = dc.banner` without DISTINCT.
  dim_customer has 18–28 rows per Grocery banner.  The join inflates fact_market
  volumes by customer count.  The share ratio survives by cancellation but the
  share is now customer-count-weighted across banners rather than a clean total.
- Q11 (severe): `JOIN dim_product ON fm.brand = dp.brand AND fm.sub_category =
  dp.sub_category` without DISTINCT in the BrandVolumeInBeverages CTE.  SKU-count
  fan-out inflates the brand volume numerator while the denominator (separately
  computed via SELECT DISTINCT) is correct.  Result: brand volume shares sum to
  102.41% — mathematically impossible and a silent correctness failure.
  Notably, the model correctly applies DISTINCT in the CorrectCategoryMarketVolume
  CTE within the same query, demonstrating that it knows the rule but applies it
  inconsistently.

**FP-04 — ISO year vs calendar quarter boundary anomaly.**
Q15: `week_date = 2024-12-30` has `year = 2025, quarter = 4, week_number = 1`
due to the ISO/calendar year boundary mismatch in the data generator.  The
model follows data labels strictly (defensible); ground truth applies a
defensive `week_number > 1` filter to exclude the anomalous row.  Root cause
is a data-design issue, not a prompt issue.  Documented in
schema_data_dictionary.md v1.2 as a temporal column note.

---

## v1.2 — FP-02 / FP-03 fixes (Sprint 2 closure)

**Date:** 2026-05-10

**Change made:**
COT_INSTRUCTION updated with two additions to Step 2 and one modification
to Step 4, aligned with schema_data_dictionary.md v1.2.

Step 2 addition — Dimension fan-out prevention rule:
Explicit instruction that when joining a fact table to a dimension on a key
set coarser than the dimension's grain, the dimension must be pre-aggregated
to DISTINCT join columns before the join.  Two common cases documented:
dim_customer on banner (multiple accounts per banner) and dim_product on
(brand, sub_category) (multiple SKUs per pair).  Without DISTINCT,
SUM/COUNT aggregations on the fact side are silently inflated by the
dimension's row count per key.

Step 4 modification — Flag exclusion adherence rule:
Strengthened from "Apply flag exclusion patterns as specified in Section 7"
to "Apply flag exclusion patterns EXACTLY as specified in Section 7 ...
check Section 7 to determine which flags must be excluded ... do not add
exclusions beyond what Section 7 specifies."  Explicit callout that
`is_volume_outlier = TRUE` must be excluded from BOTH volume AND revenue
aggregations per the updated Section 7.

**Parallel schema change:**
schema_data_dictionary.md updated to v1.2:
- Section 7 flag table: `is_volume_outlier` exclusion scope extended to
  include revenue KPIs (net_revenue_gbp, gross_revenue_gbp) with rationale
  that revenue = volume × list_price and is therefore inflated on outlier rows.
- Section 3: Temporal column note added documenting the ISO/calendar year
  boundary quirk (FP-04).
- See ADR-037 (schema enrichment rationale) and ADR-038 (DISTINCT rule).

**Failure patterns that prompted the change:**
- FP-02: `is_volume_outlier` applied inconsistently to revenue queries across
  the 15-query test suite.  Schema enrichment (Section 7) makes the rule
  explicit; the strengthened Step 4 instruction ensures strict adherence.
- FP-03: DISTINCT pre-aggregation omitted when joining fact_market to
  dim_customer (Q08) and dim_product (Q11), producing customer-count-weighted
  shares and SKU-count-inflated volumes respectively.  The new Step 2 rule
  makes DISTINCT pre-aggregation mandatory for all coarser-grain joins.

**Location:** `src/nl2sql.py` → `COT_INSTRUCTION` constant

---

*Log updated at Sprint 2 closure. Prompt v1.2 frozen as the baseline for
Sprint 5 evaluation (F-16, F-17). Next iteration (if needed) will be v1.3
during Sprint 5 based on 20-query benchmark suite results.*
