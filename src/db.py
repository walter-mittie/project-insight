"""
src/db.py
---------
DuckDB connection module — AM1 Agentic Conversational BI prototype.

Design
------
Opens a DuckDB in-memory connection and registers all four processed Parquet
files as named SQL views.  The views are the sole entry point for all SQL
executed by the NL2SQL layer (F-09) and the benchmark script (F-03).

Why in-memory DuckDB over a persistent .db file
------------------------------------------------
The processed Parquet files in data/processed/ are the store of record —
they are versioned, reproducible (re-runnable via preprocess.py), and already
columnar-optimised for OLAP queries.  Maintaining a separate persistent DuckDB
file would duplicate storage and introduce a sync risk: if preprocess.py is
re-run the .db file becomes stale unless explicitly rebuilt.  DuckDB's native
read_parquet() eliminates this risk — every get_connection() call reads from
the current processed layer with no staleness window.

Why DuckDB over alternatives (see ADR-019 in docs/decision_log.md)
-------------------------------------------------------------------
- Pandas: no SQL interface; the NL2SQL layer produces SQL strings which cannot
  be executed by Pandas without an additional translation layer.
- SQLite: row-oriented; aggregation performance on the ~2.3M row fact_sales
  would not meet the <2-second benchmark targets.
- Cloud DW (BigQuery / Snowflake): requires infrastructure, credentials, and
  network access — incompatible with a local zero-dependency prototype.

Raw data layers (data/raw/ and data/raw/qi-injected/) are never referenced
here.  The application has no knowledge of upstream pipeline stages.

Usage
-----
    from src.db import get_connection

    con = get_connection()
    df  = con.execute("SELECT COUNT(*) FROM fact_sales").df()
"""

import os

import duckdb

# ──────────────────────────────────────────────────────────────────────────────
# PATHS — resolved relative to this file's location (src/db.py → ../data/processed)
# ──────────────────────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROCESSED_DIR = os.path.join(BASE_DIR, "..", "data", "processed")

_PARQUET_VIEWS: dict[str, str] = {
    "dim_product": os.path.join(PROCESSED_DIR, "dim_product.parquet"),
    "dim_customer": os.path.join(PROCESSED_DIR, "dim_customer.parquet"),
    "fact_sales": os.path.join(PROCESSED_DIR, "fact_sales.parquet"),
    "fact_market": os.path.join(PROCESSED_DIR, "fact_market.parquet"),
}


def get_connection() -> duckdb.DuckDBPyConnection:
    """
    Return a DuckDB in-memory connection with all four processed Parquet files
    registered as named SQL views.

    Views registered
    ----------------
    - dim_product   — 552 rows (normalised casing, is_active bool, launch_date date)
    - dim_customer  — 240 rows (imputed territory & store_count)
    - fact_sales    — ~2.3M rows (is_zero_price, is_volume_outlier flags appended)
    - fact_market   — ~44K rows (is_zero_shelf_price, is_vol_violation flags;
                                  derived measures: market_share_volume_pct,
                                  market_share_value_pct, numeric_distribution_pct,
                                  price_index)

    Returns
    -------
    duckdb.DuckDBPyConnection
        In-memory connection ready for SQL execution.  Callers should not close
        this connection — it is intended to be held for the application lifetime.

    Raises
    ------
    FileNotFoundError
        If any processed Parquet file is missing.  Run scripts/preprocess.py first.
    """
    # Validate all files exist before opening the connection.
    for view_name, path in _PARQUET_VIEWS.items():
        abs_path = os.path.abspath(path)
        if not os.path.exists(abs_path):
            raise FileNotFoundError(
                f"Processed Parquet file not found for view '{view_name}': {abs_path}\n"
                "Run scripts/preprocess.py to generate the processed layer."
            )

    con = duckdb.connect(database=":memory:")

    for view_name, path in _PARQUET_VIEWS.items():
        abs_path = os.path.abspath(path)
        con.execute(
            f"CREATE VIEW {view_name} AS SELECT * FROM read_parquet('{abs_path}')"
        )

    return con
