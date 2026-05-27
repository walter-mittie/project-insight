"""
scripts/benchmark_duckdb.py
---------------------------
F-03 acceptance benchmark — AM1 Agentic Conversational BI prototype.

Standalone script (run once, not part of the application).  Validates that:

  1. All four processed Parquet files are loadable via get_connection().
  2. Three benchmark queries (Q1–Q3) each complete in under 2 seconds on the
     full dataset (~2.3M rows in fact_sales).
  3. Three derived measure validation queries (V1–V3) confirm that the
     market_share_volume_pct, price_index, and numeric_distribution_pct
     columns computed by preprocess.py are non-null and within plausible ranges
     on clean rows.

Execution
---------
    python scripts/benchmark_duckdb.py   # from project root

Exit codes
----------
    0 — all benchmarks and validations passed (F-03 PASS)
    1 — one or more checks failed (F-03 FAIL)
"""

import os
import sys
import time

# ── Ensure the project root is on sys.path so `from src.db` resolves ─────────
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.join(_SCRIPT_DIR, "..")
sys.path.insert(0, os.path.abspath(_PROJECT_ROOT))

from src.db import get_connection  # noqa: E402 (import after sys.path manipulation)

# ──────────────────────────────────────────────────────────────────────────────
# CONSTANTS
# ──────────────────────────────────────────────────────────────────────────────
BENCHMARK_THRESHOLD_S: float = 2.0  # seconds — F-03 acceptance criterion


# ──────────────────────────────────────────────────────────────────────────────
# BENCHMARK QUERIES
# ──────────────────────────────────────────────────────────────────────────────

Q1 = """
-- Q1: GROUP BY aggregation
-- Total net_revenue_gbp and volume_units by brand and year,
-- excluding is_zero_price rows, on fact_sales joined to dim_product.
SELECT
    p.brand,
    f.year,
    SUM(f.net_revenue_gbp)  AS total_net_revenue_gbp,
    SUM(f.volume_units)     AS total_volume_units
FROM fact_sales  f
JOIN dim_product p ON f.product_id = p.product_id
WHERE f.is_zero_price = FALSE
GROUP BY p.brand, f.year
ORDER BY p.brand, f.year
"""

Q2 = """
-- Q2: Multi-table JOIN
-- Top 10 SKUs by net_revenue_gbp in 2025, joining fact_sales to dim_product
-- and dim_customer, with channel and banner in the output.
SELECT
    p.product_id,
    p.brand,
    p.sub_category,
    c.channel,
    c.banner,
    SUM(f.net_revenue_gbp) AS total_net_revenue_gbp
FROM fact_sales  f
JOIN dim_product  p ON f.product_id  = p.product_id
JOIN dim_customer c ON f.customer_id = c.customer_id
WHERE f.year = 2025
  AND f.is_zero_price = FALSE
GROUP BY p.product_id, p.brand, p.sub_category, c.channel, c.banner
ORDER BY total_net_revenue_gbp DESC
LIMIT 10
"""

Q3 = """
-- Q3: Window function
-- Weekly net_revenue_gbp per brand with a 4-week rolling average,
-- limited to the Beverages category.
WITH weekly AS (
    SELECT
        p.brand,
        f.week_date,
        SUM(f.net_revenue_gbp) AS weekly_net_revenue_gbp
    FROM fact_sales  f
    JOIN dim_product p ON f.product_id = p.product_id
    WHERE p.category     = 'Beverages'
      AND f.is_zero_price = FALSE
    GROUP BY p.brand, f.week_date
)
SELECT
    brand,
    week_date,
    weekly_net_revenue_gbp,
    AVG(weekly_net_revenue_gbp) OVER (
        PARTITION BY brand
        ORDER BY week_date
        ROWS BETWEEN 3 PRECEDING AND CURRENT ROW
    ) AS rolling_4wk_avg_revenue_gbp
FROM weekly
ORDER BY brand, week_date
"""


# ──────────────────────────────────────────────────────────────────────────────
# VALIDATION QUERIES
# ──────────────────────────────────────────────────────────────────────────────

V1 = """
-- V1: market_share_volume_pct — non-null and between 0 and 100
-- Scope: rows where is_vol_violation = FALSE (clean rows — violation flag
--        excluded from share calculations by preprocess.py design).
SELECT
    COUNT(*) AS n_rows_checked,
    COUNT(*) FILTER (WHERE market_share_volume_pct IS NULL) AS n_null,
    COUNT(*) FILTER (WHERE market_share_volume_pct < 0
                        OR market_share_volume_pct > 100)           
            AS n_out_of_range
FROM fact_market
WHERE is_vol_violation = FALSE
"""

V2 = """
-- V2: price_index — non-null and plausible (between 50 and 200)
-- Scope: rows where is_vol_violation = FALSE AND is_zero_shelf_price = FALSE
--        (preprocess.py sets price_index to NaN for both corrupted conditions).
SELECT
    COUNT(*) AS n_rows_checked,
    COUNT(*) FILTER (WHERE price_index IS NULL) AS n_null,
    COUNT(*) FILTER (WHERE price_index < 50 OR price_index > 200) AS n_out_of_range
FROM fact_market
WHERE is_vol_violation   = FALSE
  AND is_zero_shelf_price = FALSE
"""

V3 = """
-- V3: numeric_distribution_pct — between 0 and 100
-- Scope: rows where total_outlets_in_banner > 0
--        (preprocess.py computes the ratio only when the denominator is valid).
SELECT
    COUNT(*) AS n_rows_checked,
    COUNT(*) FILTER (WHERE numeric_distribution_pct IS NULL) AS n_null,
    COUNT(*) FILTER (WHERE numeric_distribution_pct < 0
                        OR numeric_distribution_pct > 100)                
            AS n_out_of_range
FROM fact_market
WHERE total_outlets_in_banner > 0
"""


# ──────────────────────────────────────────────────────────────────────────────
# HELPERS
# ──────────────────────────────────────────────────────────────────────────────


def _tick(label: str, query: str, con) -> tuple[float, bool]:
    """Execute a query, return (elapsed_seconds, passed_threshold)."""
    t0 = time.perf_counter()
    _result = con.execute(query).fetchall()
    elapsed = time.perf_counter() - t0
    passed = elapsed < BENCHMARK_THRESHOLD_S
    return elapsed, passed


def _validate(label: str, query: str, con) -> tuple[int, bool]:
    """
    Execute a validation query and return (n_rows_checked, passed).

    The query must return exactly one row with columns:
        n_rows_checked, n_null, n_out_of_range
    """
    row = con.execute(query).fetchone()
    n_rows_checked = row[0]
    n_null = row[1]
    n_out_of_range = row[2]
    passed = (n_null == 0) and (n_out_of_range == 0)
    return n_rows_checked, passed


# ──────────────────────────────────────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────────────────────────────────────


def main() -> int:
    """
    Run all benchmarks and validations.  Returns exit code (0 = pass, 1 = fail).
    """
    print()
    print("╔══════════════════════════════════════════════════════════════════╗")
    print("║  benchmark_duckdb.py — F-03 Acceptance Benchmark               ║")
    print("║  Project Insight: Agentic Conversational BI           ║")
    print("╚══════════════════════════════════════════════════════════════════╝")
    print()

    # ── Connect ───────────────────────────────────────────────────────────────
    print("Connecting to DuckDB (in-memory) and registering Parquet views ...")
    t_conn0 = time.perf_counter()
    con = get_connection()
    t_conn = time.perf_counter() - t_conn0
    print(f"  Connection + view registration: {t_conn:.3f}s")
    print()

    # ── Benchmarks ────────────────────────────────────────────────────────────
    benchmark_results: list[tuple[str, float, bool]] = []

    for label, query in [
        ("Q1  GROUP BY aggregation  ", Q1),
        ("Q2  Multi-table JOIN      ", Q2),
        ("Q3  Window function       ", Q3),
    ]:
        elapsed, passed = _tick(label, query, con)
        benchmark_results.append((label, elapsed, passed))

    # ── Validations ───────────────────────────────────────────────────────────
    validation_results: list[tuple[str, int, bool]] = []

    for label, query in [
        ("V1  market_share_volume_pct range  ", V1),
        ("V2  price_index range              ", V2),
        ("V3  numeric_distribution_pct range ", V3),
    ]:
        n_rows, passed = _validate(label, query, con)
        validation_results.append((label, n_rows, passed))

    # ── Print structured summary ───────────────────────────────────────────────
    all_passed = True

    print("── Benchmark Results ─────────────────────────────────────────────────")
    for label, elapsed, passed in benchmark_results:
        symbol = "✓" if passed else "✗"
        if not passed:
            all_passed = False
        print(
            f"  {label}: {elapsed:5.3f}s  {symbol}"
            f"  (threshold: {BENCHMARK_THRESHOLD_S:.1f}s)"
        )

    print()
    print("── Derived Measure Validation ────────────────────────────────────────")
    for label, n_rows, passed in validation_results:
        symbol = "✓" if passed else "✗"
        if not passed:
            all_passed = False
        print(f"  {label}: {symbol}  ({n_rows:,} rows checked)")

    print()
    if all_passed:
        print("── F-03 Acceptance: PASS ─────────────────────────────────────────────")
        print()
        return 0
    else:
        print("── F-03 Acceptance: FAIL ─────────────────────────────────────────────")
        print("   One or more checks did not meet acceptance criteria.")
        print()
        return 1


if __name__ == "__main__":
    sys.exit(main())
