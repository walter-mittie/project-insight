"""
src/agent.py
------------
F-10 · Self-Correction Agentic Retry Loop
F-11 · Conversation History Management (orchestration layer)

Project Insight: Agentic Conversational BI 

Provides the single public function:

    run_turn(user_question, conversation_history, conn) -> dict

This is the top-level orchestration entry point for the entire agentic
pipeline.  Sprint 4 (Streamlit UI) calls run_turn() exclusively — it has
no direct dependency on nl2sql.py, executor.py, or narrative.py.

Pipeline flow per turn
----------------------
    1. generate_sql(user_question, conversation_history)
       → produces candidate SQL (or error dict on LLM/parse failure)
    2. execute_sql(sql, conn)
       → executes against DuckDB; returns structured success or error dict
    3. Self-correction retry loop (F-10):
       → on execution error, format correction signal and regenerate SQL
       → retry up to MAX_RETRIES times (ADR-031: 2 retries = 3 total attempts)
       → hard cap enforced — no infinite retry
    4. generate_narrative(user_question, df)
       → second Gemini call; produces plain-English paragraph from result
    5. Append completed turn to conversation_history (F-11)
    6. Return unified response dict

Self-correction signal format (F-10)
--------------------------------------
On execution error, the correction signal is appended to the user question
as a structured block before re-calling generate_sql():

    [CORRECTION — Attempt N of 3]
    The previous SQL failed to execute. Fix the SQL and try again.

    Error type:    <executor error_type, e.g. CatalogException>
    Error message: <executor error_message>

    Previous (failed) SQL:
    ```sql
    <failed_sql>
    ```

This injects the exact DuckDB exception class name and message, giving the
model the structured signal it needs to identify and fix the failure (e.g.
a hallucinated column name in a CatalogException, a missing semicolon in
a ParserException).  The correction signal is appended to the question
string only — conversation_history is NOT modified during retries, so
the history passed to generate_sql() remains the same across all attempts
within a single turn.

Conversation history management (F-11)
----------------------------------------
agent.py owns the history lifecycle:
- Reads the caller-supplied history on each turn (Sprint 4 Streamlit will
  store this in session_state and pass it on every call).
- Passes it to generate_sql() for context injection.
- On successful execution, appends a new entry and returns the updated list.
- On failure, does NOT append — a failed turn is not added to history.
- History entry format:
    {
        "turn_index":     int,   # 0-based, incremented by agent.py
        "user_question":  str,
        "sql":            str,   # the SQL that actually executed successfully
        "result_summary": str,   # compact text summary of the DataFrame
    }
- result_summary is built by _summarise_result_for_history(), capped at
  HISTORY_RESULT_ROWS rows to prevent context bloat.

Return structure
----------------
Success:
    {
        "status":               "success",
        "user_question":        str,
        "sql":                  str,
        "reasoning":            str,
        "data":                 pd.DataFrame,
        "row_count":            int,
        "exec_time_ms":         float,
        "narrative":            str,
        "retry_count":          int,   # F-10 AC4: 0 = no retry needed
        "turn_index":           int,   # F-11 AC4: 0-based turn counter
        "history_truncated":    bool,  # True if history was pruned this turn
        "raw_nl2sql":           str,   # full LLM response (JSONL logging, Sprint 4)
        "raw_narrative":        str,   # full narrative response (JSONL logging)
        "conversation_history": list   # updated history list (append new turn)
    }

Error (at any pipeline stage):
    {
        "status":               "error",
        "error_stage":          str,   # "nl2sql" | "execution" | "narrative"
        "error_type":           str,   # structured error type string
        "error_message":        str,
        "sql":                  str | None,  # None if NL2SQL failed before SQL
        "retry_count":          int,
        "turn_index":           int,
        "conversation_history": list   # unchanged — failed turns not appended
    }

Narrative errors are non-fatal: if generate_narrative() fails, run_turn()
returns "status": "success" with "narrative": "" and logs a warning.  The
data result is still usable — the failure is surfaced in the return dict
and flagged for JSONL logging in Sprint 4.

ADR references
--------------
- ADR-031: retry limit = 2 retries (3 total attempts)
- ADR-040: agent.py as single orchestration entry point
"""

import logging

import duckdb
import pandas as pd

from src.nl2sql import generate_sql
from src.executor import execute_sql
from src.narrative import generate_narrative

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# CONFIGURATION
# ──────────────────────────────────────────────────────────────────────────────

# Maximum retries on execution failure (ADR-031).
# 2 retries = 3 total attempts (1 initial + 2 corrective).
MAX_RETRIES = 2

# Maximum rows of the result DataFrame included in the history result_summary.
# Kept deliberately short — the history entry is context for the model, not
# a full data snapshot.  The full DataFrame is in the run_turn() return dict
# for the calling layer (Streamlit / Sprint 5 evaluator).
HISTORY_RESULT_ROWS = 15


# ──────────────────────────────────────────────────────────────────────────────
# PRIVATE HELPERS
# ──────────────────────────────────────────────────────────────────────────────


def _build_correction_prompt(
    original_question: str,
    failed_sql: str,
    error_type: str,
    error_message: str,
    attempt: int,
) -> str:
    """
    Construct the user-turn prompt for a self-correction retry attempt.

    Appends a structured correction signal to the original question so the
    model sees both the intent (question) and the failure evidence (error).

    Parameters
    ----------
    original_question : str
        The unmodified user question from this turn.
    failed_sql : str
        The SQL string that caused the execution error.
    error_type : str
        DuckDB exception class name from executor.py (e.g. "CatalogException").
    error_message : str
        DuckDB exception message from executor.py.
    attempt : int
        Current attempt number (1-based: attempt=1 means first retry).

    Returns
    -------
    str
        Augmented prompt string passed to generate_sql() for the retry call.
    """
    total_attempts = MAX_RETRIES + 1
    return (
        f"{original_question}\n\n"
        f"[CORRECTION — Attempt {attempt + 1} of {total_attempts}]\n"
        f"The previous SQL failed to execute. Fix the SQL and try again.\n\n"
        f"Error type:    {error_type}\n"
        f"Error message: {error_message}\n\n"
        f"Previous (failed) SQL:\n"
        f"```sql\n{failed_sql}\n```"
    )


def _summarise_result_for_history(df: pd.DataFrame) -> str:
    """
    Build a compact result summary for appending to conversation_history.

    Uses the first HISTORY_RESULT_ROWS rows of the DataFrame, formatted as
    a plain-text table.  Includes a row count note if the result is larger.

    Parameters
    ----------
    df : pd.DataFrame
        Executed query result.

    Returns
    -------
    str
        Compact text summary for the history entry's result_summary field.
    """
    if df.empty:
        return "0 rows returned"

    total = len(df)
    preview = df.head(HISTORY_RESULT_ROWS).to_string(index=False)

    if total <= HISTORY_RESULT_ROWS:
        return f"{total} row{'s' if total != 1 else ''}:\n{preview}"
    else:
        return (
            f"{total} rows total (showing first {HISTORY_RESULT_ROWS}):\n"
            f"{preview}"
        )


# ──────────────────────────────────────────────────────────────────────────────
# PUBLIC FUNCTION
# ──────────────────────────────────────────────────────────────────────────────


def run_turn(
    user_question: str,
    conversation_history: list[dict],
    conn: duckdb.DuckDBPyConnection,
    schema_override: str | None = None,
) -> dict:
    """
    Execute one full agentic turn: NL2SQL → execution → retry loop → narrative.

    This is the single entry point for the agentic pipeline.  Sprint 4
    Streamlit UI calls this function exclusively.

    Parameters
    ----------
    user_question : str
        The analyst's natural language question for this turn.
    conversation_history : list[dict]
        Prior turns managed by the caller (Streamlit session_state in Sprint 4,
        or a plain list in Sprint 3 tests).  Each entry:
            {
                "turn_index":     int,
                "user_question":  str,
                "sql":            str,
                "result_summary": str,
            }
        Pass [] on the first turn.  Returned updated at end of a successful turn.
    conn : duckdb.DuckDBPyConnection
        Live DuckDB connection with all four Parquet views registered.
        Obtain via: from src.db import get_connection; conn = get_connection()
        Do NOT open a new connection per turn.

    Returns
    -------
    dict
        See module docstring for full return structure.

    Notes
    -----
    - Does not raise on any path.
    - Narrative errors are non-fatal: the turn is still marked "success" if
      SQL execution succeeded, and narrative="" is set with a log warning.
    - conversation_history is never mutated — a shallow copy is taken at entry
      and all operations are performed on that copy.  The caller's original
      list is always left unchanged.  The updated history is returned in the
      dict; callers must assign it explicitly:
          history = result["conversation_history"]
    - On error paths, the returned conversation_history is the original
      unmodified list (no new entry appended — failed turns are not recorded).
    """
    # Copy at entry — the caller's list is never touched (see Notes above).
    history = list(conversation_history)

    turn_index = len(history)  # 0-based (F-11 AC4)
    retry_count = 0
    history_truncated = False

    logger.info(
        "run_turn | turn_index=%d | question: %s",
        turn_index,
        user_question[:100],
    )

    # ── Detect if history will be truncated this turn ──────────────────────────
    # nl2sql.py performs the actual truncation; we detect it here for the
    # return dict flag so Sprint 4 Streamlit can surface a notification.
    from src.nl2sql import MAX_HISTORY_TURNS
    if len(history) > MAX_HISTORY_TURNS:
        history_truncated = True

    # ── Stage 1: Initial SQL generation ───────────────────────────────────────
    nl2sql_result = generate_sql(user_question, history, schema_override=schema_override)

    if "error" in nl2sql_result:
        # LLM API failure or missing ```sql delimiter — not retryable at this
        # stage (retry loop targets execution errors, not generation errors).
        logger.error(
            "run_turn | nl2sql error at turn %d: %s",
            turn_index,
            nl2sql_result.get("error"),
        )
        return {
            "status":               "error",
            "error_stage":          "nl2sql",
            "error_type":           nl2sql_result.get("error", "unknown"),
            "error_message":        nl2sql_result.get("message", nl2sql_result.get("raw", ""))[:500],
            "sql":                  None,
            "retry_count":          0,
            "turn_index":           turn_index,
            "conversation_history": conversation_history,
        }

    current_sql = nl2sql_result["sql"]
    current_reasoning = nl2sql_result["reasoning"]
    current_raw_nl2sql = nl2sql_result["raw"]
    current_suggested_chart_type = nl2sql_result.get("suggested_chart_type", "auto")

    # ── Stage 2: Execution + self-correction retry loop (F-10) ────────────────
    exec_result = execute_sql(current_sql, conn)

    while exec_result["status"] == "error" and retry_count < MAX_RETRIES:
        retry_count += 1

        logger.warning(
            "run_turn | execution error on attempt %d/%d | turn=%d | "
            "%s: %s | retrying...",
            retry_count,
            MAX_RETRIES + 1,
            turn_index,
            exec_result["error_type"],
            exec_result["error_message"][:120],
        )

        # Build correction prompt: original question + error signal + failed SQL.
        correction_prompt = _build_correction_prompt(
            original_question=user_question,
            failed_sql=current_sql,
            error_type=exec_result["error_type"],
            error_message=exec_result["error_message"],
            attempt=retry_count,
        )

        # Regenerate SQL with error context visible.
        # history is unchanged across retries — it represents completed prior
        # turns, not the current (still-failing) turn.
        retry_nl2sql = generate_sql(correction_prompt, history)

        if "error" in retry_nl2sql:
            # Generation failed during retry — break out and return execution
            # error from the last successful generation attempt.
            logger.error(
                "run_turn | nl2sql error during retry %d at turn %d: %s",
                retry_count,
                turn_index,
                retry_nl2sql.get("error"),
            )
            break

        # Update current SQL for the next execution attempt.
        current_sql = retry_nl2sql["sql"]
        current_reasoning = retry_nl2sql["reasoning"]
        current_raw_nl2sql = retry_nl2sql["raw"]
        current_suggested_chart_type = retry_nl2sql.get("suggested_chart_type", "auto")

        exec_result = execute_sql(current_sql, conn)

    # ── Stage 2b: Handle persistent execution failure ─────────────────────────
    if exec_result["status"] == "error":
        logger.error(
            "run_turn | execution failed after %d attempt(s) | turn=%d | "
            "%s: %s",
            retry_count + 1,
            turn_index,
            exec_result["error_type"],
            exec_result["error_message"][:200],
        )
        return {
            "status":               "error",
            "error_stage":          "execution",
            "error_type":           exec_result["error_type"],
            "error_message":        exec_result["error_message"],
            "sql":                  current_sql,
            "retry_count":          retry_count,
            "turn_index":           turn_index,
            "conversation_history": conversation_history,  # original — unchanged
        }

    # ── Stage 3: Narrative generation (F-12) ──────────────────────────────────
    df: pd.DataFrame = exec_result["data"]
    narrative_result = generate_narrative(user_question, df)

    if narrative_result["status"] == "error":
        # Narrative failure is non-fatal: log warning, continue with empty narrative.
        logger.warning(
            "run_turn | narrative generation failed at turn %d: %s",
            turn_index,
            narrative_result.get("error_message", "unknown"),
        )
        narrative_text = ""
        raw_narrative = ""
    else:
        narrative_text = narrative_result["narrative"]
        raw_narrative = narrative_result["raw_narrative"]

    # ── Stage 4: Append completed turn to history copy (F-11) ────────────────
    result_summary = _summarise_result_for_history(df)
    history_entry = {
        "turn_index":     turn_index,
        "user_question":  user_question,
        "sql":            current_sql,
        "result_summary": result_summary,
    }
    history.append(history_entry)

    logger.info(
        "run_turn | turn %d complete | rows=%d | exec_time=%.1fms | "
        "retries=%d | narrative=%s | history_len=%d",
        turn_index,
        exec_result["row_count"],
        exec_result["exec_time_ms"],
        retry_count,
        "ok" if narrative_text else "empty",
        len(history),
    )

    return {
        "status":               "success",
        "user_question":        user_question,
        "sql":                  current_sql,
        "reasoning":            current_reasoning,
        "data":                 df,
        "row_count":            exec_result["row_count"],
        "exec_time_ms":         exec_result["exec_time_ms"],
        "narrative":            narrative_text,
        "retry_count":          retry_count,
        "turn_index":           turn_index,
        "history_truncated":    history_truncated,
        "suggested_chart_type": current_suggested_chart_type,  # ADR-042
        "raw_nl2sql":           current_raw_nl2sql,
        "raw_narrative":        raw_narrative,
        "conversation_history": history,  # updated copy — caller assigns explicitly
    }
