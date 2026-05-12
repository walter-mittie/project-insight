"""
src/nl2sql.py
-------------
F-08 · Chain-of-Thought NL2SQL Generation

AM1: Agentic Conversational BI — Manu Mohandas / TCS

Provides the public function:

    generate_sql(user_question, conversation_history) -> dict

The function combines F-06 (Gemini API) and F-07 (schema injection) to
produce a structured dict containing:
    - "reasoning" : the model's CoT reasoning (tables, columns, constraints)
    - "sql"        : extracted SQL string (no backticks, whitespace-stripped)
    - "raw"        : full raw model response (for JSONL logging in Sprint 4)

On extraction failure:
    - {"error": "no_sql_delimiter", "raw": <raw_response>}

Prompt architecture (F-08)
--------------------------
System prompt layout (order enforced):
    [SCHEMA DICT]        — load_schema_dict() output, injected first
    [TASK INSTRUCTION]   — CoT instruction block (see COT_INSTRUCTION below)

The CoT instruction block directs the model to:
    1. Identify which tables and columns are required before writing SQL
    2. Note any C1–C6 semantic constraint that applies
    3. Output SQL inside a ```sql ... ``` fenced block
    4. Keep reasoning outside the SQL block (only the fenced block is parsed)

SQL extraction (F-08)
---------------------
Parsed between ```sql and ``` delimiters.  Leading/trailing whitespace
stripped.  If delimiter not found → error dict returned (not raised).

Conversation history (F-08 / Sprint 2 scope)
---------------------------------------------
Accepted as a parameter for interface stability but not yet wired into
the prompt in Sprint 2.  Sprint 3 will prepend the history as a
<conversation_history> block in the system prompt.

Prompt iteration log
--------------------
All prompt changes must be recorded in docs/prompt_log.md with version
number, change made, and failure pattern that prompted the change (F-08 AC4).
"""

import re
import logging

from src.llm import get_llm_response, load_schema_dict, LLMError

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# CoT INSTRUCTION BLOCK  (prompt v1.2 — see docs/prompt_log.md)
# ──────────────────────────────────────────────────────────────────────────────

COT_INSTRUCTION = """
## Your Task: Convert a natural language question into a DuckDB SQL query.

Work through the following steps IN ORDER. Do not skip steps.

### Step 1 — Identify tables and columns
State which tables you need and which columns you will use.
Reference only columns listed in the schema above.

### Step 2 — Check semantic constraints and KPI computation rules
Review constraints C1–C6 in the schema. State which constraints apply to
this query and how you will handle them (e.g., which flag filters to apply).

Additionally, check for these critical rules:

**Grain-locked columns — NEVER aggregate these directly:**
fact_market contains pre-computed columns: market_share_volume_pct,
market_share_value_pct, numeric_distribution_pct, price_index.
These are valid ONLY for exact point lookups at the native grain
(brand × sub_category × banner × week). NEVER SUM or AVG them across
any dimension — the result is arithmetically incorrect. Instead, always
recompute from the underlying numerator/denominator components using
patterns P1–P4 in Section 5 of the schema.

**Join pattern selection (when query involves both fact_sales and fact_market):**
- If the question involves sub_category-level market data → use Pattern A
  (join on week_date · brand · sub_category · banner — all four keys).
- If the question is brand-level only → use Pattern B (pre-aggregate BOTH
  fact_sales AND fact_market to brand × banner × week before joining).
- NEVER join a 3-key sales_agg directly to the 4-key fact_market grain —
  this produces a fan-out.

**Dimension fan-out prevention (applies to ALL fact-to-dimension joins):**
When joining a fact table to a dimension table on a key set that is coarser
than the dimension's grain, always pre-aggregate the dimension to DISTINCT
join columns BEFORE joining. Without this, SUM/COUNT aggregations on the
fact side will be silently inflated by the dimension's row count per key.
Common cases requiring DISTINCT:
- Joining fact_market to dim_customer on banner: dim_customer has many
  accounts per banner. Use: SELECT DISTINCT banner, channel FROM dim_customer.
- Joining fact_market to dim_product on (brand, sub_category): dim_product
  has many SKUs per (brand, sub_category) pair. Use: SELECT DISTINCT brand,
  sub_category, category FROM dim_product.

### Step 3 — Clarify any ambiguous business terms
If the question uses ambiguous FMCG terms, state your interpretation before
writing SQL. Common ambiguities:
- "revenue" → default to net_revenue_gbp unless "gross" is explicitly stated
- "market share" → default to volume share unless "value share" is specified
- "top N brands" → state the metric used for ranking (e.g. net_revenue_gbp)
- "price" → distinguish between sku_net_price_gbp (manufacturer net) and
  avg_shelf_price_gbp (consumer shelf price from fact_market)

### Step 4 — Write the SQL
Write valid DuckDB SQL inside a fenced code block exactly like this:

```sql
SELECT ...
```

Rules for the SQL block:
- Use only tables and columns defined in the schema.
- Apply flag exclusion patterns EXACTLY as specified in Section 7 of the
  schema. For each KPI being computed, check Section 7 to determine which
  flags must be excluded. Apply all listed exclusions; do not add exclusions
  beyond what Section 7 specifies. In particular: is_volume_outlier = TRUE
  must be excluded from BOTH volume AND revenue aggregations per Section 7.
- For KPI queries (market share, price index, distribution), always
  recompute from numerator/denominator components using P1–P4 patterns.
  Never SELECT the pre-computed grain-locked columns for aggregated queries.
- For any query involving both fact_sales and fact_market, select Pattern A
  or Pattern B as described in Step 2 above and Section 8 of the schema.
- Use week_date for temporal filters — never assume a column called "date".
- Time period rules (dataset covers 2024-01-01 to 2025-12-29 only):
  "last year" = year = 2024; "this year" = year = 2025 (latest available);
  "Q3" = quarter = 3; "H1" = quarter IN (1, 2); "H2" = quarter IN (3, 4).
- Never SELECT * on fact tables — select only the columns required.
- Terminate the SQL with a semicolon.

Your reasoning (Steps 1–3) must appear BEFORE the ```sql block.
The ```sql block is the only parseable output — keep it clean.
""".strip()

# ──────────────────────────────────────────────────────────────────────────────
# SQL EXTRACTION
# ──────────────────────────────────────────────────────────────────────────────

_SQL_PATTERN = re.compile(r"```sql\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)


def _extract_sql(raw: str) -> str | None:
    """
    Extract the SQL string from a ```sql ... ``` fenced block.

    Returns the stripped SQL string, or None if the delimiter is not found.
    """
    match = _SQL_PATTERN.search(raw)
    if match:
        return match.group(1).strip()
    return None


# ──────────────────────────────────────────────────────────────────────────────
# REASONING EXTRACTION
# ──────────────────────────────────────────────────────────────────────────────


def _extract_reasoning(raw: str) -> str:
    """
    Extract the CoT reasoning text — everything before the ```sql block.

    If no SQL block is present, return the full raw response as reasoning.
    """
    sql_start = raw.find("```sql")
    if sql_start == -1:
        return raw.strip()
    return raw[:sql_start].strip()


# ──────────────────────────────────────────────────────────────────────────────
# PUBLIC FUNCTION
# ──────────────────────────────────────────────────────────────────────────────


def generate_sql(
    user_question: str,
    conversation_history: list[dict],
) -> dict:
    """
    Generate a DuckDB SQL query from a natural language question using
    chain-of-thought prompting with full schema injection.

    Parameters
    ----------
    user_question : str
        The analyst's natural language question (e.g. "What were the top 5
        brands by net revenue in Q3 2024?").
    conversation_history : list[dict]
        Prior conversation turns in the format:
            [{"role": "user", "content": str},
             {"role": "assistant", "content": str}, ...]
        Pass as empty list [] in Sprint 2 tests.
        Sprint 3 will prepend this history into the system prompt.

    Returns
    -------
    dict
        On success:
            {
                "reasoning": str,   # CoT reasoning (tables, constraints)
                "sql":       str,   # extracted SQL (no backticks)
                "raw":       str    # full raw response (for JSONL logging)
            }
        On SQL extraction failure:
            {
                "error": "no_sql_delimiter",
                "raw":   str
            }
        On LLM API failure:
            {
                "error": "llm_error",
                "message": str,
                "raw":   ""
            }

    Notes
    -----
    - Does not raise on any path — all errors returned as structured dicts.
    - conversation_history is accepted but not yet wired into the prompt
      (Sprint 3 responsibility).
    """
    # ── Build system prompt ────────────────────────────────────────────────────
    schema_text = load_schema_dict()
    system_prompt = f"{schema_text}\n\n---\n\n{COT_INSTRUCTION}"

    # ── Sprint 3 hook (conversation history) ──────────────────────────────────
    # In Sprint 3, prepend conversation_history as a <conversation_history>
    # block here before the CoT instruction.  For now, log if history is passed
    # so we know the parameter flows through correctly.
    if conversation_history:
        logger.debug(
            "conversation_history has %d turn(s) — not yet wired into prompt "
            "(Sprint 3 responsibility).",
            len(conversation_history),
        )

    # ── Call Gemini ────────────────────────────────────────────────────────────
    logger.info("generate_sql | question: %s", user_question[:120])
    try:
        raw = get_llm_response(
            prompt=user_question,
            system_prompt=system_prompt,
        )
    except LLMError as exc:
        logger.error("LLMError in generate_sql: %s", exc)
        return {
            "error": "llm_error",
            "message": str(exc),
            "raw": "",
        }

    # ── Extract SQL ────────────────────────────────────────────────────────────
    sql = _extract_sql(raw)
    if sql is None:
        logger.warning(
            "generate_sql | no ```sql delimiter found in response. "
            "Raw (first 200 chars): %s",
            raw[:200],
        )
        return {
            "error": "no_sql_delimiter",
            "raw": raw,
        }

    reasoning = _extract_reasoning(raw)

    logger.info(
        "generate_sql | SQL extracted (%d chars), reasoning (%d chars)",
        len(sql),
        len(reasoning),
    )

    return {
        "reasoning": reasoning,
        "sql": sql,
        "raw": raw,
    }
