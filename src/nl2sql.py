"""
src/nl2sql.py
-------------
F-08 · Chain-of-Thought NL2SQL Generation
F-11 · Conversation History Management (Sprint 3)

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
System prompt layout (order enforced, static-first per ADR-028):
    [SCHEMA DICT]            — load_schema_dict() output, injected first
    [CONVERSATION HISTORY]   — <conversation_history> block (F-11, Sprint 3)
    [TASK INSTRUCTION]       — CoT instruction block (see COT_INSTRUCTION below)

The static-first ordering (schema before history before question) maximises
Gemini implicit cache hit probability: the schema prefix is shared across all
turns and qualifies for caching at ~2,600 tokens (ADR-028 / ADR-030).

The CoT instruction block directs the model to:
    1. Identify which tables and columns are required before writing SQL
    2. Note any C1–C6 semantic constraint that applies
    3. Output SQL inside a ```sql ... ``` fenced block
    4. Keep reasoning outside the SQL block (only the fenced block is parsed)

SQL extraction (F-08)
---------------------
Parsed between ```sql and ``` delimiters.  Leading/trailing whitespace
stripped.  If delimiter not found → error dict returned (not raised).

Conversation history format (F-11)
-----------------------------------
Each entry in conversation_history is a dict:
    {
        "turn_index":      int,   # 0-based turn counter
        "user_question":   str,   # original user question for that turn
        "sql":             str,   # SQL that was successfully executed
        "result_summary":  str,   # compact text summary of the DataFrame result
    }

History is injected as a <conversation_history> XML-tagged block between the
schema and the CoT instruction.  Oldest turns pruned first if history exceeds
MAX_HISTORY_TURNS (F-11 AC3).  Truncation is logged at WARNING level.

agent.py is responsible for building and maintaining the history list and
passing it on each call.  nl2sql.py is responsible only for formatting it
into the system prompt.

Prompt iteration log
--------------------
All prompt changes must be recorded in docs/prompt_log.md with version
number, change made, and failure pattern that prompted the change (F-08 AC4).
v1.2 is the Sprint 5 evaluation baseline — CoT instruction frozen.
"""

import re
import logging

from src.llm import get_llm_response, load_schema_dict, LLMError

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# CONVERSATION HISTORY CONFIG  (F-11)
# ──────────────────────────────────────────────────────────────────────────────

# Maximum number of prior turns to inject into the system prompt.
# Oldest turns are pruned first when this limit is exceeded (F-11 AC3).
# Rationale: 5 turns × ~500 tokens each = ~2,500 tokens history overhead.
# Combined with schema (~2,600), CoT instruction (~660), and user question
# (~195), total system prompt remains well under 10,000 tokens — a safe
# margin against Gemini 2.5 Flash's 1M-token context window (ADR-027).
MAX_HISTORY_TURNS = 5


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
# CONVERSATION HISTORY FORMATTING  (F-11)
# ──────────────────────────────────────────────────────────────────────────────


def _format_conversation_history(history: list[dict]) -> str:
    """
    Format conversation history as a <conversation_history> XML-tagged block
    for injection into the Gemini system prompt.

    Each turn renders as:
        Turn N:
          Question: <user_question>
          SQL: <sql> (first 300 chars if long, with truncation note)
          Result: <result_summary>

    Parameters
    ----------
    history : list[dict]
        Each dict has keys: turn_index, user_question, sql, result_summary.
        Must already be truncated to MAX_HISTORY_TURNS by the caller.

    Returns
    -------
    str
        Formatted XML block, or empty string if history is empty.
    """
    if not history:
        return ""

    lines = ["<conversation_history>"]
    for entry in history:
        turn_num = entry.get("turn_index", 0) + 1  # 1-based for readability
        question = entry.get("user_question", "").strip()
        sql = entry.get("sql", "").strip()
        result = entry.get("result_summary", "").strip()

        # Truncate very long SQL to avoid context bloat while keeping
        # enough structure for the model to understand the prior query pattern.
        sql_display = sql if len(sql) <= 300 else sql[:297] + "..."

        lines.append(f"\nTurn {turn_num}:")
        lines.append(f"  Question: {question}")
        lines.append(f"  SQL: {sql_display}")
        lines.append(f"  Result: {result}")

    lines.append("\n</conversation_history>")
    return "\n".join(lines)


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
    chain-of-thought prompting with full schema injection and conversation
    history context.

    Parameters
    ----------
    user_question : str
        The analyst's natural language question (e.g. "What were the top 5
        brands by net revenue in Q3 2024?").
    conversation_history : list[dict]
        Prior conversation turns. Each entry is a dict:
            {
                "turn_index":     int,   # 0-based turn counter
                "user_question":  str,   # original question for that turn
                "sql":            str,   # SQL executed successfully
                "result_summary": str,   # compact DataFrame text summary
            }
        Pass as [] on the first turn. agent.py builds and maintains this list.
        If len > MAX_HISTORY_TURNS (5), oldest turns are pruned here with a
        WARNING log (F-11 AC3).

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
                "error":   "llm_error",
                "message": str,
                "raw":     ""
            }

    Notes
    -----
    - Does not raise on any path — all errors returned as structured dicts.
    - System prompt order: schema → history → CoT instruction (ADR-028:
      static-first ordering for implicit cache hit on the schema prefix).
    """
    # ── History truncation (F-11 AC3) ─────────────────────────────────────────
    if len(conversation_history) > MAX_HISTORY_TURNS:
        dropped = len(conversation_history) - MAX_HISTORY_TURNS
        conversation_history = conversation_history[-MAX_HISTORY_TURNS:]
        logger.warning(
            "generate_sql | conversation history truncated: %d oldest turn(s) "
            "pruned to stay within MAX_HISTORY_TURNS=%d. "
            "[F-11 AC3: oldest turns pruned first]",
            dropped,
            MAX_HISTORY_TURNS,
        )

    # ── Build system prompt (schema → history → CoT instruction) ──────────────
    schema_text = load_schema_dict()
    history_block = _format_conversation_history(conversation_history)

    if history_block:
        system_prompt = (
            f"{schema_text}\n\n---\n\n{history_block}\n\n---\n\n{COT_INSTRUCTION}"
        )
        logger.info(
            "generate_sql | %d prior turn(s) injected into system prompt",
            len(conversation_history),
        )
    else:
        # First turn — no history block, matches original Sprint 2 prompt shape.
        system_prompt = f"{schema_text}\n\n---\n\n{COT_INSTRUCTION}"
        logger.info("generate_sql | no conversation history (first turn)")

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
