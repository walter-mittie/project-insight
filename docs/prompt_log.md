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

*Log updated as prompt versions are iterated during Sprint 2 testing (AC4).*
*Target: 15 manual test queries across single-table filter, aggregation,*
*multi-table join, ambiguous term, and time-period filter categories (F-08 AC3).*

---
## Design Decision — Structured Output vs CoT Delimiter Approach

**Date:** 2026-05-08

**Decision:** Retain ```sql delimiter parsing over JSON mode / response_schema
for Sprint 2. Revisit after 15-query manual test suite.

**Options considered:**

Option A — Raw JSON mode: force `response_mime_type="application/json"` with
no schema. Eliminates conversational fluff and markdown wrapping. Rejected
because JSON mode suppresses chain-of-thought reasoning — the model prioritises
satisfying the structural constraint over reasoning through tables, constraints,
and disambiguation steps.

Option B — Gemini response_schema (structured output): enforces a typed JSON
object with `reasoning` (str) and `sql` (str) fields. Preserves CoT in the
reasoning field; sql field returns clean SQL with no backticks or markdown.
Parsing becomes json.loads() — no regex. This is the preferred upgrade path
if delimiter failures are observed in testing.

Option C — Current approach (```sql delimiter + regex): zero-shot CoT
reasoning preserved in full; SQL extracted via _SQL_PATTERN regex. Introduces
a `no_sql_delimiter` failure path that Option B would eliminate entirely.

**Why not change it now:** The 15-query manual test suite (F-08 AC3) is the
diagnostic. Switching before failure data exists is premature optimisation.
If `no_sql_delimiter` errors appear in more than 1-2 of the 15 queries,
migrate to response_schema in Sprint 3 when nl2sql.py is already being
modified for conversation history.

**Upgrade path (if needed):**
- Add `response_mime_type="application/json"` and `response_schema` to
  GenerateContentConfig in src/llm.py
- Replace _extract_sql() and _extract_reasoning() in src/nl2sql.py with
  json.loads(response.text)
- Update prompt — instruct model to populate reasoning and sql fields
  directly, no ```sql block needed
- Log as prompt v2.0 in this file

**KSB mapping:** K1, K3

---
## Design Decision — Few-Shot Examples (docs/few_shot_examples.json)

**Date:** 2026-05-08

**Decision:** Scaffold built now; population deferred until after 15-query
manual test suite identifies real failure patterns.

**Rationale:**
Few-shot Q+SQL pairs are one of the most reliable levers for FMCG-specific
intent mapping — teaching the model that "top 5 brands" means
ORDER BY [metric] DESC LIMIT 5, that "revenue" defaults to net_revenue_gbp,
and that "last year" = 2025 in this dataset. However, writing examples before
failure data exists means guessing at which quirks need teaching.

**Correct sequence:**
1. Run 15-query test suite (zero-shot baseline)
2. Identify failure patterns — which query categories fail and why
3. Write few-shot examples that target exactly those failure patterns
4. Re-run failed queries with examples injected — measure improvement
5. Log each example as a prompt_log entry with before/after evidence

**Assessment value:**
Zero-shot accuracy on the 15-query benchmark = baseline (H0).
Few-shot accuracy after targeted examples = treatment (H1).
This is a legitimate before/after comparison for Sprint 5 hypothesis
testing (K26). Jumping straight to few-shot collapses this experiment.

**Scaffold location:** docs/few_shot_examples.json
**Loader function:** load_few_shot_examples() — to be added to src/llm.py
**Injection point in generate_sql():**
    system_prompt = f"{schema_text}\n\n{few_shot_block}\n\n---\n\n{COT_INSTRUCTION}"
    (schema first → examples second → CoT instruction last)

**Graceful degradation:** if few_shot_examples.json absent or empty,
system runs zero-shot without error — no code change required to
switch between zero-shot and few-shot modes.

**KSB mapping:** K1, K3, K26
