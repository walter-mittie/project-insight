"""
src/narrative.py
----------------
F-12 · Narrative Response Generation

Project Insight: Agentic Conversational BI 

Provides the public function:

    generate_narrative(user_question, df) -> dict

Makes a second Gemini call (via llm.get_llm_response) that receives the
original user question and a compact summary of the query result DataFrame,
and returns a plain-English narrative paragraph for non-technical users.

Design rationale
----------------
The NL2SQL pipeline (nl2sql.py + executor.py) returns tabular data.  For
a non-technical FMCG stakeholder — a category manager, a commercial director —
raw tabular output requires interpretation: which brand won, by how much,
is that a big gap?  F-12 provides a second-pass LLM interpretation that
bridges the gap between machine-readable data and human-readable insight.

This separation of concerns (SQL generation vs. narrative interpretation)
is intentional: the narrative call receives ONLY the result data and the
original question.  It does not see the schema, the CoT reasoning, or the
SQL.  This keeps the narrative prompt short, focused, and low-latency, and
ensures the model narrates from evidence rather than from its own SQL
interpretation (which could diverge from the executed result).

Gemini call configuration
--------------------------
- Reuses get_llm_response() from llm.py — no separate API wrapper needed.
- System prompt: NARRATIVE_SYSTEM_PROMPT (narrative prompt v1.1).
- User prompt: original question + formatted DataFrame summary.
- No schema injection — the narrative model interprets results, not SQL.

DataFrame summarisation
-----------------------
_summarise_df() formats the DataFrame into a compact text representation:
- Up to MAX_SUMMARY_ROWS rows (50) to cover all expected FMCG result shapes:
  26-week H2 trends, 22 sub-categories, top-N brand tables, etc.
  50 rows is trivial against Gemini 2.5 Flash's 1M token context window.
  Changed from 10 to 50 at Sprint 3 closure after T5 (weekly volume trend,
  26 rows) was incorrectly truncated, producing an incomplete narrative.
  Note: MAX_SUMMARY_ROWS (narrative prompt budget) is intentionally larger
  than HISTORY_RESULT_ROWS in agent.py (5 rows), which is accumulated across
  all prior turns and must stay compact.
- Uses df.to_string() for faithful column/value rendering.
- Appends row count and truncation note if result exceeds MAX_SUMMARY_ROWS.

Narrative prompt versioning
----------------------------
v1.0 (Sprint 3 initial): basic rules — 2–4 sentences, cite specific figures,
  no SQL language, no hedging, handle 0-row results.
v1.1 (Sprint 3 closure): three additions prompted by live validation findings:
  1. Synthesise-not-enumerate rule: for >3-row results, identify the key
     finding then characterise the pattern — do not list every row.
  2. Trend/ranking/comparison guidance: specific instructions for each result
     shape covering direction, magnitude, inflection, and standout findings.
  3. Directional language rules: when all metric values are negative, describe
     the "best" performer as having "the smallest decline" — never "strongest
     growth". Triggered by T3 (all three brands declined YoY; narrative
     incorrectly described Velvet Dairy as having "the strongest revenue growth"
     when the correct description is "the smallest decline").
  See docs/prompt_log.md — Narrative Prompt section, v1.0 → v1.1.

Return structure
----------------
Success:
    {
        "status":         "success",
        "narrative":      str,   # plain-English paragraph (F-12 AC1, AC2)
        "raw_narrative":  str    # full raw response (for JSONL logging, Sprint 4)
    }

Error:
    {
        "status":         "error",
        "error_type":     "llm_error",
        "error_message":  str,
        "narrative":      "",
        "raw_narrative":  ""
    }

Never raises — all error paths return a structured dict so agent.py can
handle narrative failure gracefully without crashing the turn.
"""

import logging

import pandas as pd

from src.llm import get_llm_response, LLMError

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# CONFIGURATION
# ──────────────────────────────────────────────────────────────────────────────

# Maximum rows of the DataFrame to include in the narrative prompt.
# 50 covers all expected FMCG result shapes (26-week trends, 22 sub-categories,
# top-N brand tables). Changed 10→50 at Sprint 3 closure after weekly trend
# narrative (T5, 26 rows) was incorrectly truncated at 10 rows.
# Keep distinct from HISTORY_RESULT_ROWS in agent.py (5) — different concern.
MAX_SUMMARY_ROWS = 50


# ──────────────────────────────────────────────────────────────────────────────
# NARRATIVE SYSTEM PROMPT  (v1.1 — see docs/prompt_log.md, Narrative section)
# ──────────────────────────────────────────────────────────────────────────────

NARRATIVE_SYSTEM_PROMPT = """
You are an FMCG commercial analytics assistant helping non-technical business
users understand query results.

Your task: read a query result table and write a clear, direct narrative
paragraph that answers the user's question.

Core rules:
- Write 2 to 4 sentences. No bullet points.
- Reference specific numbers from the result (brand names, values, percentages,
  dates). Do not use vague language like "some brands" or "various periods".
- Do not repeat the question verbatim in your answer.
- Do not hedge with "it appears", "it seems", or "it looks like". State facts.
- Do not mention SQL, tables, columns, or technical terms.
- If the result contains 0 rows, say so clearly and suggest the question may
  reference a period or entity not present in the dataset.
- Use £ for monetary values (GBP). Use % for percentages. Round large values
  to 2 decimal places where appropriate.

Synthesise — do not enumerate:
- For results with more than 3 rows, do NOT list every row individually.
  Identify the single most important finding, then characterise the overall
  pattern or range across the remaining rows in a single phrase.
  Good: "CocoaEthos led with £27.8M, nearly £2.5M ahead of BerryBliss.
  The remaining three brands clustered between £17.5M and £20.1M."
  Bad: "Brand A had £X. Brand B had £Y. Brand C had £Z. Brand D had £W."
- For trend data (weekly, monthly, quarterly time series): describe the overall
  direction (rising, falling, flat) and magnitude across the full period. Call
  out any notable inflection point, peak, or trough by its period label and
  value. Do not recite each period's value in sequence.
- For rankings: lead with the winner and the gap to second place, then
  characterise the rest of the field in a single phrase.
- For comparisons across brands or segments: identify the standout finding —
  the biggest gap, the unexpected outlier, or the reversal of expectation.

Directional language rules:
- When all values in the key metric are negative (e.g. all year-on-year
  growth rates are below zero), describe the top-ranked item as having
  "the smallest decline" or "the least negative change" — never as
  "the strongest growth" or "the best performance" without qualification.
- When values are a mix of positive and negative, make the direction explicit
  for each: "Brand A grew by 3.1% while Brand B declined by 1.8%."
- Never infer that a result is commercially good or bad beyond what the
  numbers directly show.
""".strip()


# ──────────────────────────────────────────────────────────────────────────────
# DATAFRAME SUMMARISATION
# ──────────────────────────────────────────────────────────────────────────────


def _summarise_df(df: pd.DataFrame) -> str:
    """
    Convert a DataFrame to a compact text summary for the narrative prompt.

    For results with <= MAX_SUMMARY_ROWS rows, the full DataFrame is rendered
    via df.to_string().  For larger results, the first MAX_SUMMARY_ROWS rows
    are shown with a truncation note indicating total row count.

    Parameters
    ----------
    df : pd.DataFrame
        Query result from execute_sql().

    Returns
    -------
    str
        Text representation suitable for inclusion in the narrative prompt.
    """
    if df.empty:
        return "(no rows returned)"

    total_rows = len(df)

    if total_rows <= MAX_SUMMARY_ROWS:
        return df.to_string(index=False)
    else:
        preview = df.head(MAX_SUMMARY_ROWS).to_string(index=False)
        return (
            f"{preview}\n"
            f"... [{total_rows} rows total — showing first {MAX_SUMMARY_ROWS}]"
        )


# ──────────────────────────────────────────────────────────────────────────────
# PUBLIC FUNCTION
# ──────────────────────────────────────────────────────────────────────────────


def generate_narrative(
    user_question: str,
    df: pd.DataFrame,
) -> dict:
    """
    Generate a plain-English narrative paragraph interpreting a query result.

    Makes a second Gemini API call (distinct from the NL2SQL call in nl2sql.py)
    with the original user question and a formatted DataFrame summary.

    Parameters
    ----------
    user_question : str
        The original natural language question from the user — used to frame
        the narrative answer.
    df : pd.DataFrame
        The query result from execute_sql().  May be empty (0 rows).

    Returns
    -------
    dict
        On success:
            {
                "status":         "success",
                "narrative":      str,   # plain-English answer paragraph
                "raw_narrative":  str    # full raw response (for JSONL logging)
            }
        On error:
            {
                "status":         "error",
                "error_type":     str,   # "llm_error"
                "error_message":  str,
                "narrative":      "",
                "raw_narrative":  ""
            }

    Notes
    -----
    - Does not raise on any path.
    - The narrative is NOT guaranteed to be factually correct if the DataFrame
      is wrong (garbage in, garbage out).  Correctness of the underlying SQL
      is the responsibility of nl2sql.py + executor.py.
    - For 0-row results, the narrative model is instructed to explain that no
      data was found (per NARRATIVE_SYSTEM_PROMPT) — not to fabricate figures.
    """
    data_summary = _summarise_df(df)
    row_count = len(df)

    user_prompt = (
        f"Question: {user_question}\n\n"
        f"Query result ({row_count} row{'s' if row_count != 1 else ''}):\n"
        f"{data_summary}\n\n"
        f"Write a narrative paragraph that directly answers the question "
        f"using the numbers in the result above."
    )

    logger.info(
        "generate_narrative | question: %s | result: %d rows",
        user_question[:80],
        row_count,
    )

    try:
        raw = get_llm_response(
            prompt=user_prompt,
            system_prompt=NARRATIVE_SYSTEM_PROMPT,
        )
    except LLMError as exc:
        logger.error("LLMError in generate_narrative: %s", exc)
        return {
            "status":        "error",
            "error_type":    "llm_error",
            "error_message": str(exc),
            "narrative":     "",
            "raw_narrative": "",
        }

    narrative = raw.strip()
    logger.info(
        "generate_narrative | narrative generated (%d chars)",
        len(narrative),
    )

    return {
        "status":        "success",
        "narrative":     narrative,
        "raw_narrative": raw,
    }
