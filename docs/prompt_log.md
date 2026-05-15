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

## Sprint 3 live validation — additional failure patterns (NL2SQL)

The following failure patterns were identified during the Sprint 3 live
validation (sprint_3_validation_report.md, 2026-05-13).  They do NOT trigger
a prompt version change in Sprint 3 — the v1.2 baseline remains frozen for
Sprint 5 evaluation.  They are documented here for Sprint 5 iteration.

**FP-05 — Incorrect promotional uplift formula.**
N3 query: "What was the average volume uplift for promoted SKUs compared to
non-promoted SKUs in 2024?"
Generated SQL: `AVG(incremental_volume)` — this is an absolute average of
incremental units per transaction row, not a meaningful uplift ratio.
Correct formula: `SUM(incremental_volume) / SUM(baseline_volume) * 100`.
Additionally, `is_zero_price = FALSE` was applied to a volume-focused query
— an unnecessary filter that the schema (Section 7) does not mandate for
this KPI.
Root cause: schema_data_dictionary.md defines `incremental_volume` and
`baseline_volume` as stored columns but does not specify the standard
formula for "promotional uplift %" as a named KPI.  The model defaults to
`AVG(incremental_volume)` in the absence of explicit formula guidance.
Fix required: add a dedicated KPI definition for `promotional_uplift_pct`
in Section 5 of the schema (alongside P1–P4), with the formula and an
explicit note that this is a ratio, not an average of raw units.

**FP-06 — Category revenue denominator ambiguous for multi-category brands.**
N5 query: "Compare the top 5 brands by net revenue in 2025, showing each
brand's total and percentage share of category revenue."
Generated SQL: `relevant_category_revenue` CTE groups by `brand`, making
each brand's denominator the sum of all categories it operates in.  If two
top-5 brands share a category, each includes the full category revenue in
its own denominator — the percentages are not comparable and do not sum to
100%.  The model also omitted the `category` column from the output, making
the shares uninterpretable.
Root cause: "percentage share of category revenue" is underspecified when
brands span multiple categories.  The schema has no guidance on how to
handle cross-category brand portfolios in share-of-category metrics.
Fix required: add a schema note (Section 5 or Section 8) clarifying that
"share of category revenue" is only well-defined within a single category,
and that queries involving multi-category brands should either (a) restrict
to a named category, or (b) use total portfolio revenue as the denominator
with explicit labelling.

*Log updated at Sprint 3 closure. Prompt v1.2 remains frozen as the Sprint 5
evaluation baseline. FP-05 and FP-06 are candidates for a v1.3 iteration
during Sprint 5 if the 20-query benchmark confirms these failure modes at
meaningful rates.*



# Narrative Prompt Log
**AM1: Agentic Conversational BI | F-12 | Manu Mohandas / TCS**

---

## Purpose

This section logs every change to the narrative generation system prompt in
`src/narrative.py → NARRATIVE_SYSTEM_PROMPT`.  The narrative prompt is a
separate component from the NL2SQL CoT prompt above — it drives the second
Gemini call that converts a query result DataFrame into a plain-English
paragraph for non-technical FMCG users.

Format mirrors the NL2SQL section: one entry per version.

---

## Narrative v1.0 — Initial prompt (Sprint 3)

**Date:** 2026-05-11

**Change made:**
Initial narrative system prompt authored.  Core rules:
- 2 to 4 sentences, no bullet points
- Reference specific figures (brand names, values, percentages, dates)
- No question repetition verbatim
- No hedging language ("it appears", "it seems")
- No SQL or technical terms in output
- 0-row results: explain no data found, do not fabricate
- Use £ for GBP, % for percentages

**Failure pattern that prompted the change:**
N/A — initial version.  Prompt designed pre-emptively based on known
tendencies of LLMs producing narrative text: over-hedging, omitting specific
figures, and reproducing the question verbatim as the first sentence.

**Location:** `src/narrative.py` → `NARRATIVE_SYSTEM_PROMPT` constant
**MAX_SUMMARY_ROWS at this version:** 10

---

## Narrative v1.1 — Synthesis rules + directional language (Sprint 3 closure)

**Date:** 2026-05-13

**Change made:**
Three additions to the prompt prompted by Sprint 3 live validation findings
(sprint_3_validation_report.md):

1. **Synthesise-not-enumerate rule:** for results with more than 3 rows,
   the model must not list every row individually.  It must identify the
   single most important finding, then characterise the overall pattern in
   a single phrase.  Good/bad examples included inline.
2. **Result-shape guidance:** specific instructions for four result types:
   - Trend data (time series): describe direction + magnitude + inflection
   - Rankings: lead with winner + gap to second, then characterise the field
   - Comparisons: identify the standout finding (biggest gap, outlier,
     reversal of expectation)
   - Cross-segment: highlight the most commercially significant difference
3. **Directional language rules:** when all values in the key metric are
   negative, the top-ranked item must be described as "the smallest decline"
   or "the least negative change" — never "the strongest growth".  When
   values are a mix of positive and negative, direction must be explicit
   for each item.

**Additionally:** `MAX_SUMMARY_ROWS` increased from 10 to 50 (not a prompt
change, but a co-located configuration change applied at the same time).

**Failure patterns that prompted the change:**

*FP-N01 — Negative-metric language (T3):*
T3 multi-turn query returned YoY revenue growth rates for three brands:
Velvet Dairy −1.29%, CocoaEthos −2.00%, BerryBliss −2.51%.  The v1.0
narrative described Velvet Dairy as having "the strongest revenue growth
from 2024 to 2025" — incorrect because all three brands declined.  The
correct description is "the smallest decline".  The model correctly reported
the figure (−1.29%) but chose inappropriate framing language.
Fix: directional language rule added (item 3 above).

*FP-N02 — Row enumeration for long tables:*
Multiple v1.0 narratives (T4 channel breakdown, N4 sub-category prices,
N5 multi-brand comparison) listed rows mechanically one by one rather than
synthesising a business insight.  For N4 (22 sub-categories), the result
was a run-on sentence enumerating eight sub-categories with no interpretive
value beyond reading the table aloud.
Fix: synthesise-not-enumerate rule and result-shape guidance added (items
1 and 2 above).

*FP-N03 — Truncated narrative for long trend tables (T5):*
T5 asked for weekly volume trend for Velvet Dairy in H2 2025 (26 rows).
MAX_SUMMARY_ROWS = 10 sent only the first 10 weeks to the narrative model,
producing an incomplete narrative that covered weeks 27–36 only and could
not comment on the remainder of H2.  The narrative noted it was working
from "truncated data", which is not acceptable output for a business user.
Fix: MAX_SUMMARY_ROWS increased from 10 to 50.  At 50 rows, the full H2
weekly trend (26 rows) and any other expected FMCG result shape is covered.
The 50-row limit remains trivial against Gemini 2.5 Flash's 1M token window.

**Location:** `src/narrative.py` → `NARRATIVE_SYSTEM_PROMPT` constant
**MAX_SUMMARY_ROWS at this version:** 50

---

*Narrative prompt v1.1 is the baseline entering Sprint 4 (Streamlit UI).
Next iteration (if needed) will be v1.2 during Sprint 5 based on 20-query
benchmark narrative quality assessment.*
