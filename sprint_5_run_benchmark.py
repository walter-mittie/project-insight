"""
run_benchmark.py
----------------
F-17 · Benchmark Runner — Sprint 5 Evaluation

Project Insight: Agentic Conversational BI 

Runs the 20-prompt benchmark suite under two conditions:
    baseline  — stripped schema (table/column names only, no semantics)
    treatment — full semantic data dictionary (prompt v1.2, production path)

Produces:
    docs/experiment_results.csv    — 40 rows; sql_correct + failure_mode filled manually
    logs/benchmark_results.jsonl   — structured log (separate from interactions.jsonl)

Usage
-----
    python run_benchmark.py

No Streamlit dependency. Run from the project root.

Design notes
------------
- DuckDB connection opened once and reused across all 40 calls (performance).
- log_turn() from src/logger.py is NOT used here: it hardcodes LOG_PATH to
  logs/interactions.jsonl, which must remain a live-session-only log (Sprint 6
  evidence capture depends on this separation). Benchmark JSONL entries are
  built and written directly in this script using the same canonical field
  schema (ADR-041).
- Q20 is multi-turn: T1 runs silently to seed conversation history; T2 is the
  evaluation target and the only turn logged/written to CSV for Q20.
- If ground_truth_sql == "N/A" (out-of-vocab prompt), sql_correct and
  failure_mode are auto-filled as "N/A" in the CSV.
- Run order: all 20 prompts under baseline first, then all 20 under treatment.
  This minimises context bleed between conditions.
"""

import csv
import json
import logging
import os
import sys
from datetime import datetime, timezone

import duckdb

# ── Project imports ────────────────────────────────────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.agent import run_turn
from src.db import get_connection

# ── Logging ────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("benchmark")

# ──────────────────────────────────────────────────────────────────────────────
# PATHS
# ──────────────────────────────────────────────────────────────────────────────

BENCHMARK_JSON  = "docs/benchmark.json"
RESULTS_CSV     = "docs/experiment_results.csv"
BENCHMARK_LOG   = "logs/benchmark_results.jsonl"

# ──────────────────────────────────────────────────────────────────────────────
# BASELINE SCHEMA
# Stripped schema: table names and column names only.
# No data types, no semantic definitions, no business rules, no flag patterns.
# This is the control condition — the model receives the minimum structural
# information needed to attempt SQL generation.
# ──────────────────────────────────────────────────────────────────────────────

BASELINE_SCHEMA = """
Tables: dim_product, dim_customer, fact_sales, fact_market

dim_product columns: product_id, sku_name, brand, sub_category, category, is_active
dim_customer columns: customer_id, banner_name, region, channel
fact_sales columns: sale_id, product_id, customer_id, year, quarter, month, week_number, week_date, net_revenue_gbp, gross_revenue_gbp, trade_discount_gbp, volume_units, is_zero_price, is_volume_outlier
fact_market columns: market_id, sub_category, banner_name, brand, year, quarter, week_number, week_date, brand_volume_units, total_category_volume_units, brand_value_gbp, total_category_value_gbp, market_share_volume_pct, market_share_value_pct, numeric_distribution_pct, weighted_distribution_pct, price_index
""".strip()

# ──────────────────────────────────────────────────────────────────────────────
# CSV SCHEMA
# ──────────────────────────────────────────────────────────────────────────────

CSV_FIELDNAMES = [
    "benchmark_id",
    "tier",
    "condition",
    "sql_generated",
    "exec_success",
    "retry_count",
    "exec_time_ms",
    "suggested_chart_type",
    "sql_correct",       # manual: 1 / 0 / N/A
    "failure_mode",      # manual: FP-01…FP-06 / new-FP / none / N/A
]


# ──────────────────────────────────────────────────────────────────────────────
# INTERNAL HELPERS
# ──────────────────────────────────────────────────────────────────────────────


def _utc_now() -> str:
    """ISO-8601 UTC timestamp."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ensure_dir(path: str) -> None:
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)


def _build_jsonl_entry(
    result: dict,
    session_id: str,
    benchmark_id: str,
    condition: str,
) -> dict:
    """
    Build a canonical JSONL entry from a run_turn() result dict.

    Mirrors the field schema used by src/logger.py (ADR-041) with two
    additional benchmark-specific fields: benchmark_id and condition.
    Written to BENCHMARK_LOG, never to interactions.jsonl.
    """
    is_success = result.get("status") == "success"
    turn_index = result.get("turn_index", 0)

    return {
        "session_id":          session_id,
        "turn_id":             turn_index + 1,
        "timestamp":           _utc_now(),
        "user_query":          result.get("user_question", ""),
        "generated_sql":       result.get("sql") if is_success else None,
        "execution_time_ms":   result.get("exec_time_ms") if is_success else None,
        "retry_count":         result.get("retry_count", 0),
        "row_count":           result.get("row_count") if is_success else None,
        "success_flag":        is_success,
        "narrative_generated": bool(result.get("narrative")) if is_success else False,
        "history_truncated":   result.get("history_truncated", False),
        "error_stage":         result.get("error_stage") if not is_success else None,
        "suggested_chart_type": result.get("suggested_chart_type", "auto"),
        "rendered_chart_type": "benchmark",   # sentinel value — no chart rendered
        "resumed":             False,
        "resumed_at":          None,
        # Benchmark-specific fields
        "benchmark_id":        benchmark_id,
        "condition":           condition,
    }


def _append_jsonl(entry: dict, path: str) -> None:
    """Append one entry to the benchmark JSONL log. Non-fatal on failure."""
    try:
        _ensure_dir(path)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError as exc:
        logger.warning("JSONL write failed for %s: %s", path, exc)


def _init_csv(path: str) -> None:
    """Write CSV header row. Called once at script start."""
    _ensure_dir(path)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_FIELDNAMES)
        writer.writeheader()


def _append_csv_row(
    result: dict,
    prompt: dict,
    condition: str,
    path: str,
) -> None:
    """
    Append one row to the results CSV.

    sql_correct and failure_mode are left blank for manual completion,
    except when ground_truth_sql == "N/A" (out-of-vocab prompt), where
    both are auto-filled as "N/A".
    """
    is_success = result.get("status") == "success"
    is_out_of_vocab = prompt.get("ground_truth_sql") == "N/A"

    row = {
        "benchmark_id":        prompt["id"],
        "tier":                prompt["tier"],
        "condition":           condition,
        "sql_generated":       result.get("sql", "") if is_success else "",
        "exec_success":        1 if is_success else 0,
        "retry_count":         result.get("retry_count", 0),
        "exec_time_ms":        round(result.get("exec_time_ms", 0), 1) if is_success else "",
        "suggested_chart_type": result.get("suggested_chart_type", "auto"),
        "sql_correct":         "N/A" if is_out_of_vocab else "",
        "failure_mode":        "N/A" if is_out_of_vocab else "",
    }

    with open(path, "a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_FIELDNAMES)
        writer.writerow(row)


# ──────────────────────────────────────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────────────────────────────────────


def main() -> None:
    logger.info("=" * 70)
    logger.info("Sprint 5 Benchmark Runner — F-17")
    logger.info("Benchmark JSON : %s", BENCHMARK_JSON)
    logger.info("Results CSV    : %s", RESULTS_CSV)
    logger.info("Benchmark log  : %s", BENCHMARK_LOG)
    logger.info("=" * 70)

    # ── Load benchmark prompts ─────────────────────────────────────────────────
    if not os.path.exists(BENCHMARK_JSON):
        logger.error("benchmark.json not found at %s — aborting.", BENCHMARK_JSON)
        sys.exit(1)

    with open(BENCHMARK_JSON, encoding="utf-8") as fh:
        benchmark_prompts = json.load(fh)

    logger.info("Loaded %d prompts from benchmark.json", len(benchmark_prompts))

    # ── Initialise output files ────────────────────────────────────────────────
    _init_csv(RESULTS_CSV)
    logger.info("CSV initialised: %s", RESULTS_CSV)

    # ── Open DuckDB connection once ────────────────────────────────────────────
    logger.info("Opening DuckDB connection...")
    conn = get_connection()
    logger.info("DuckDB connection ready.")

    # ── Run loop ───────────────────────────────────────────────────────────────
    total_calls   = 0
    error_count   = 0
    retry_total   = 0

    conditions = ["baseline", "treatment"]

    for condition in conditions:
        schema = BASELINE_SCHEMA if condition == "baseline" else None
        session_id = f"benchmark_{condition}"

        logger.info("")
        logger.info("─" * 70)
        logger.info("CONDITION: %s", condition.upper())
        logger.info("─" * 70)

        for prompt in benchmark_prompts:
            qid = prompt["id"]
            tier = prompt["tier"]
            is_multi_turn = prompt.get("multi_turn", False)

            logger.info(
                "[%s | %s | tier=%d]  %s",
                condition,
                qid,
                tier,
                prompt["question"][:80],
            )

            # ── Multi-turn: T1 run silently to seed history ────────────────────
            history = []
            if is_multi_turn:
                t1_question = prompt.get("t1_question", "")
                logger.info("  → T1 (silent): %s", t1_question[:80])
                t1_result = run_turn(
                    t1_question,
                    [],
                    conn,
                    schema_override=schema,
                )
                if t1_result["status"] == "success":
                    history = t1_result["conversation_history"]
                    logger.info(
                        "  → T1 success: %d rows, %.1fms",
                        t1_result["row_count"],
                        t1_result["exec_time_ms"],
                    )
                else:
                    logger.warning(
                        "  → T1 FAILED (%s): history will be empty for T2",
                        t1_result.get("error_stage"),
                    )

            # ── T2 (or single-turn): evaluation target ─────────────────────────
            result = run_turn(
                prompt["question"],
                history,
                conn,
                schema_override=schema,
            )

            total_calls += 1
            retries = result.get("retry_count", 0)
            retry_total += retries

            if result["status"] == "success":
                logger.info(
                    "  → ✅ SUCCESS  rows=%-4d  time=%-7.1fms  retries=%d  chart=%s",
                    result["row_count"],
                    result["exec_time_ms"],
                    retries,
                    result.get("suggested_chart_type", "auto"),
                )
            else:
                error_count += 1
                logger.warning(
                    "  → ❌ FAILED   stage=%-12s  error=%s",
                    result.get("error_stage", "unknown"),
                    str(result.get("error_message", ""))[:80],
                )

            # ── Write JSONL entry (benchmark log only) ─────────────────────────
            entry = _build_jsonl_entry(result, session_id, qid, condition)
            _append_jsonl(entry, BENCHMARK_LOG)

            # ── Write CSV row (sql_correct + failure_mode left blank) ──────────
            _append_csv_row(result, prompt, condition, RESULTS_CSV)

    # ── Summary ────────────────────────────────────────────────────────────────
    logger.info("")
    logger.info("=" * 70)
    logger.info("BENCHMARK COMPLETE")
    logger.info("  Total evaluation calls : %d", total_calls)
    logger.info("  Errors                 : %d", error_count)
    logger.info("  Total retries          : %d", retry_total)
    logger.info("  Exec success rate      : %.1f%%",
                100 * (total_calls - error_count) / total_calls if total_calls else 0)
    logger.info("")
    logger.info("Next steps:")
    logger.info("  1. Open %s", RESULTS_CSV)
    logger.info("     Fill in 'sql_correct' (1/0/N/A) and 'failure_mode'")
    logger.info("     for each of the %d scoreable rows", total_calls)
    logger.info("  2. Run F-18 McNemar analysis once scoring is complete.")
    logger.info("=" * 70)

    conn.close()


if __name__ == "__main__":
    main()
