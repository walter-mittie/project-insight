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

*Log updated as prompt versions are iterated during Sprint 2 testing (AC4).*
*Target: 15 manual test queries across single-table filter, aggregation,*
*multi-table join, ambiguous term, and time-period filter categories (F-08 AC3).*
