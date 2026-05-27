"""
src/executor.py
---------------
F-09 · SQL Execution Layer

Project Insight: Agentic Conversational BI 

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

import concurrent.futures

logger = logging.getLogger(__name__)

QUERY_TIMEOUT_SECONDS = 30  # configurable — increase for complex aggregations

def _run_query(conn: duckdb.DuckDBPyConnection, sql: str) -> pd.DataFrame:
    """Inner function submitted to the thread executor."""
    return conn.execute(sql).df()


def execute_with_timeout(
    conn: duckdb.DuckDBPyConnection,
    sql: str,
    timeout: int = QUERY_TIMEOUT_SECONDS,
) -> pd.DataFrame:
    """
    Execute a DuckDB query with a timeout.
    Raises TimeoutError if execution exceeds timeout seconds.
    Used internally by execute_sql().
    """
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_run_query, conn, sql)
        try:
            return future.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            raise TimeoutError(
                f"Query timed out after {timeout}s. Try a simpler question."
            )

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
        df: pd.DataFrame = execute_with_timeout(conn, sql)
        exec_time_ms = (time.perf_counter() - t_start) * 1000.0

        row_count = len(df)
        logger.info(
            "execute_sql | success | %d rows | %.1f ms",
            row_count,
            exec_time_ms,
        )

        return {
            "status": "success",
            "data": df,
            "row_count": row_count,
            "exec_time_ms": exec_time_ms,
        }

    except Exception as exc:
        exec_time_ms = (time.perf_counter() - t_start) * 1000.0
        error_type = type(exc).__name__
        error_message = str(exc)

        logger.warning(
            "execute_sql | error | %s: %s",
            error_type,
            error_message[:200],
        )

        return {
            "status": "error",
            "error_type": error_type,
            "error_message": error_message,
        }
