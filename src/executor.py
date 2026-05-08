"""
src/executor.py
---------------
F-09 · SQL Execution Layer

AM1: Agentic Conversational BI — Manu Mohandas / TCS

Provides the public function:

    execute_sql(sql, conn) -> dict

Executes a SQL string against the live DuckDB connection and returns a
structured dict.  Never raises — all execution paths return a dict so that
the agentic loop (Sprint 3) can handle errors without try/except boilerplate
at every call site.

Return structures
-----------------
Success:
    {
        "status":        "success",
        "data":          pd.DataFrame,
        "row_count":     int,
        "exec_time_ms":  float
    }

Error:
    {
        "status":        "error",
        "error_type":    str,   # e.g. "CatalogException", "ParserException"
        "error_message": str
    }

Design notes
------------
- exec_time_ms is measured from immediately before to immediately after
  conn.execute(sql) using time.perf_counter() (F-09 AC4).
- Empty result (0 rows) is a success with an empty DataFrame — not an error
  (F-09 requirement 3).
- error_type is the class name of the DuckDB exception, captured via
  type(exc).__name__.  This gives structured, parseable error types
  ("CatalogException" for missing columns/tables, "ParserException" for
  syntax errors) for use in the Sprint 3 self-correction loop.
"""

import time
import logging

import duckdb
import pandas as pd

logger = logging.getLogger(__name__)


def execute_sql(sql: str, conn: duckdb.DuckDBPyConnection) -> dict:
    """
    Execute a SQL string against the provided DuckDB connection.

    Parameters
    ----------
    sql : str
        A DuckDB SQL query string.  Must be a single statement.
    conn : duckdb.DuckDBPyConnection
        Live DuckDB connection with Parquet views registered.
        Obtain via: from src.db import get_connection; conn = get_connection()
        Do not open a new connection per call — reuse the shared connection.

    Returns
    -------
    dict
        Success path:
            {
                "status":        "success",
                "data":          pd.DataFrame,
                "row_count":     int,
                "exec_time_ms":  float
            }
        Error path:
            {
                "status":        "error",
                "error_type":    str,
                "error_message": str
            }

    Notes
    -----
    - Does not raise on any code path.
    - exec_time_ms covers only conn.execute() + .df() — not result processing.
    - Empty result sets (0 rows) are returned as success with an empty DataFrame.
    """
    t_start = time.perf_counter()

    try:
        df: pd.DataFrame = conn.execute(sql).df()
        exec_time_ms = (time.perf_counter() - t_start) * 1000.0

        row_count = len(df)
        logger.info(
            "execute_sql | success | %d rows | %.1f ms",
            row_count,
            exec_time_ms,
        )

        return {
            "status":       "success",
            "data":         df,
            "row_count":    row_count,
            "exec_time_ms": exec_time_ms,
        }

    except Exception as exc:
        exec_time_ms = (time.perf_counter() - t_start) * 1000.0
        error_type    = type(exc).__name__
        error_message = str(exc)

        logger.warning(
            "execute_sql | error | %s: %s",
            error_type,
            error_message[:200],
        )

        return {
            "status":        "error",
            "error_type":    error_type,
            "error_message": error_message,
        }
