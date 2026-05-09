"""
tests/test_executor.py
----------------------
F-09 Acceptance Tests — SQL Execution Layer

AM1: Agentic Conversational BI — Manu Mohandas / TCS

Tests cover:
    - Known-good SQL → status = "success", DataFrame returned (AC1, AC3)
    - SQL referencing non-existent column → status = "error",
      error_type captured (AC2, AC3)
    - SQL with syntax error → status = "error" (AC2, AC3)
    - Execution time recorded (AC4)
    - Empty result set → status = "success" (requirement 3)

These tests use an in-memory DuckDB connection with a minimal fixture
table — they do not require the processed Parquet files to be present,
making them runnable in CI and fresh environments.

Run with:
    python -m pytest tests/test_executor.py -v
"""

import sys
import os

# ── Ensure project root is on sys.path ────────────────────────────────────────
_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.join(_TESTS_DIR, "..")
sys.path.insert(0, os.path.abspath(_PROJECT_ROOT))

import duckdb
import pandas as pd
import pytest

from src.executor import execute_sql


# ──────────────────────────────────────────────────────────────────────────────
# FIXTURES
# ──────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def conn():
    """
    In-memory DuckDB connection with a minimal fixture table.

    Creates:
        sales_fixture (product_id INT, revenue FLOAT, units INT)

    Three rows:  (1, 100.0, 10), (2, 200.0, 20), (3, 0.0, 0)
    """
    c = duckdb.connect(database=":memory:")
    c.execute("""
        CREATE TABLE sales_fixture AS
        SELECT * FROM (VALUES
            (1, 100.0, 10),
            (2, 200.0, 20),
            (3,   0.0,  0)
        ) t(product_id, revenue, units)
    """)
    yield c
    c.close()


# ──────────────────────────────────────────────────────────────────────────────
# SUCCESS PATH
# ──────────────────────────────────────────────────────────────────────────────


def test_known_good_sql_returns_success(conn):
    """AC1 + AC3: known-good SQL returns status='success' with a DataFrame."""
    result = execute_sql(
        "SELECT product_id, revenue FROM sales_fixture ORDER BY product_id;",
        conn,
    )
    assert result["status"] == "success"
    assert isinstance(result["data"], pd.DataFrame)
    assert result["row_count"] == 3
    assert list(result["data"]["product_id"]) == [1, 2, 3]


def test_aggregation_sql_returns_correct_value(conn):
    """AC1: aggregation query returns correct scalar via DataFrame."""
    result = execute_sql(
        "SELECT SUM(revenue) AS total_revenue FROM sales_fixture;",
        conn,
    )
    assert result["status"] == "success"
    assert result["row_count"] == 1
    assert result["data"]["total_revenue"].iloc[0] == pytest.approx(300.0)


def test_empty_result_is_success(conn):
    """Requirement 3: 0-row result is success, not an error."""
    result = execute_sql(
        "SELECT * FROM sales_fixture WHERE revenue > 9999;",
        conn,
    )
    assert result["status"] == "success"
    assert result["row_count"] == 0
    assert isinstance(result["data"], pd.DataFrame)
    assert len(result["data"]) == 0


# ──────────────────────────────────────────────────────────────────────────────
# EXECUTION TIME
# ──────────────────────────────────────────────────────────────────────────────


def test_exec_time_recorded(conn):
    """AC4: exec_time_ms present and non-negative on success path."""
    result = execute_sql(
        "SELECT COUNT(*) AS n FROM sales_fixture;",
        conn,
    )
    assert result["status"] == "success"
    assert "exec_time_ms" in result
    assert result["exec_time_ms"] >= 0.0


# ──────────────────────────────────────────────────────────────────────────────
# ERROR PATHS  (AC2 + AC3)
# ──────────────────────────────────────────────────────────────────────────────


def test_nonexistent_column_returns_error(conn):
    """AC2 + AC3: SQL referencing a non-existent column returns error dict."""
    result = execute_sql(
        "SELECT nonexistent_column FROM sales_fixture;",
        conn,
    )
    assert result["status"] == "error"
    assert "error_type" in result
    assert "error_message" in result
    # DuckDB raises BinderException or CatalogException for unknown columns
    assert result["error_type"] in (
        "BinderException",
        "CatalogException",
        "duckdb.BinderException",
        "duckdb.CatalogException",
    )


def test_nonexistent_table_returns_error(conn):
    """AC2: SQL referencing a non-existent table returns error dict."""
    result = execute_sql(
        "SELECT * FROM table_that_does_not_exist;",
        conn,
    )
    assert result["status"] == "error"
    assert result["error_type"] in (
        "CatalogException",
        "duckdb.CatalogException",
        "BinderException",
        "duckdb.BinderException",
    )


def test_syntax_error_returns_error(conn):
    """AC2 + AC3: SQL with a syntax error returns error dict, not an exception."""
    result = execute_sql(
        "SELEKT * FORM sales_fixture;",  # deliberate typos
        conn,
    )
    assert result["status"] == "error"
    assert "error_type" in result
    assert "error_message" in result
    # DuckDB raises ParserException for syntax errors
    assert "Exception" in result["error_type"]


def test_no_exception_propagates(conn):
    """
    F-09 requirement 1: execute_sql never raises.
    Passes a completely broken SQL string — must return error dict, not raise.
    """
    try:
        result = execute_sql("THIS IS NOT SQL AT ALL ###;", conn)
        assert result["status"] == "error"
    except Exception as exc:
        pytest.fail(
            f"execute_sql raised an exception instead of returning error dict: {exc}"
        )


# ──────────────────────────────────────────────────────────────────────────────
# RETURN STRUCTURE COMPLETENESS
# ──────────────────────────────────────────────────────────────────────────────


def test_success_dict_has_all_keys(conn):
    """Success dict contains exactly the four required keys."""
    result = execute_sql(
        "SELECT 1 AS val;",
        conn,
    )
    assert result["status"] == "success"
    for key in ("status", "data", "row_count", "exec_time_ms"):
        assert key in result, f"Missing key: {key}"


def test_error_dict_has_all_keys(conn):
    """Error dict contains exactly the three required keys."""
    result = execute_sql(
        "SELECT col_not_there FROM sales_fixture;",
        conn,
    )
    assert result["status"] == "error"
    for key in ("status", "error_type", "error_message"):
        assert key in result, f"Missing key: {key}"
