"""
tests/test_agent.py
-------------------
F-10 · Self-Correction Agentic Retry Loop — Unit Tests
F-11 · Conversation History Management — Unit Tests

Project Insight: Agentic Conversational BI 

All Gemini API calls, DuckDB execution, and narrative generation are mocked.
Tests are runnable in CI with no .env file, no Parquet files, and no network.

Mocking strategy
----------------
agent.py binds the three dependencies at import time:
    from src.nl2sql   import generate_sql
    from src.executor import execute_sql
    from src.narrative import generate_narrative

We patch the names as they appear in the agent module namespace:
    src.agent.generate_sql
    src.agent.execute_sql
    src.agent.generate_narrative

Run with:
    python -m pytest tests/test_agent.py -v
"""

import sys
import os

_TESTS_DIR    = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.join(_TESTS_DIR, "..")
sys.path.insert(0, os.path.abspath(_PROJECT_ROOT))

from unittest.mock import patch, MagicMock, call
import duckdb
import pandas as pd
import pytest

from src.agent import run_turn, MAX_RETRIES


# ──────────────────────────────────────────────────────────────────────────────
# FIXTURES & HELPERS
# ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def conn():
    """Minimal in-memory DuckDB connection — agent.py never calls it directly
    when execute_sql is mocked, but run_turn requires a conn argument."""
    c = duckdb.connect(database=":memory:")
    yield c
    c.close()


def _nl2sql_ok(sql: str = "SELECT 1 AS val;") -> dict:
    return {"reasoning": "Step 1: use fixture. Step 2: no constraints.", "sql": sql, "raw": "<raw>"}


def _exec_ok(n: int = 3) -> dict:
    df = pd.DataFrame({"brand": [f"Brand{i}" for i in range(n)],
                       "revenue": [float(i * 100) for i in range(n)]})
    return {"status": "success", "data": df, "row_count": n, "exec_time_ms": 4.2}


def _exec_err(error_type: str = "CatalogException",
              message: str = "Column 'bad_col' not found") -> dict:
    return {"status": "error", "error_type": error_type, "error_message": message}


def _narrative_ok(text: str = "Brand0 had the highest revenue at £200.") -> dict:
    return {"status": "success", "narrative": text, "raw_narrative": text}


def _narrative_err() -> dict:
    return {"status": "error", "error_type": "llm_error",
            "error_message": "API unavailable", "narrative": "", "raw_narrative": ""}


# ──────────────────────────────────────────────────────────────────────────────
# F-10 · SELF-CORRECTION RETRY LOOP  (AC1, AC2, AC3, AC4)
# ──────────────────────────────────────────────────────────────────────────────

class TestRetryLoop:

    def test_no_retry_when_execution_succeeds(self, conn):
        """Happy path: execution succeeds on first attempt → retry_count = 0."""
        with patch("src.agent.generate_sql", return_value=_nl2sql_ok()), \
             patch("src.agent.execute_sql",  return_value=_exec_ok()), \
             patch("src.agent.generate_narrative", return_value=_narrative_ok()):

            result = run_turn("Top brands?", [], conn)

        assert result["status"] == "success"
        assert result["retry_count"] == 0  # AC4

    def test_one_retry_on_single_execution_error(self, conn):
        """AC2: execution fails once → generate_sql called again → second execution
        succeeds → retry_count = 1, final status = success."""
        exec_responses = [_exec_err(), _exec_ok()]

        with patch("src.agent.generate_sql", return_value=_nl2sql_ok()) as mock_gen, \
             patch("src.agent.execute_sql",  side_effect=exec_responses), \
             patch("src.agent.generate_narrative", return_value=_narrative_ok()):

            result = run_turn("Top brands?", [], conn)

        assert result["status"] == "success"
        assert result["retry_count"] == 1         # AC4
        assert mock_gen.call_count == 2           # initial + 1 correction

    def test_two_retries_before_success(self, conn):
        """AC2: execution fails twice, succeeds on third attempt → retry_count = 2."""
        exec_responses = [_exec_err(), _exec_err(), _exec_ok()]

        with patch("src.agent.generate_sql", return_value=_nl2sql_ok()) as mock_gen, \
             patch("src.agent.execute_sql",  side_effect=exec_responses), \
             patch("src.agent.generate_narrative", return_value=_narrative_ok()):

            result = run_turn("Top brands?", [], conn)

        assert result["status"] == "success"
        assert result["retry_count"] == 2
        assert mock_gen.call_count == 3

    def test_hard_cap_enforced_returns_error(self, conn):
        """AC3: execution always fails → loop exits after MAX_RETRIES (2) → error."""
        with patch("src.agent.generate_sql", return_value=_nl2sql_ok()) as mock_gen, \
             patch("src.agent.execute_sql",  return_value=_exec_err()), \
             patch("src.agent.generate_narrative", return_value=_narrative_ok()):

            result = run_turn("Top brands?", [], conn)

        assert result["status"] == "error"
        assert result["error_stage"] == "execution"
        assert result["retry_count"] == MAX_RETRIES               # AC3: hard cap = 2
        assert mock_gen.call_count == MAX_RETRIES + 1             # 1 initial + 2 retries

    def test_correction_signal_contains_error_type(self, conn):
        """AC1: the correction prompt passed to generate_sql on retry contains
        the structured error_type from executor.py."""
        exec_responses = [_exec_err("CatalogException", "Column x not found"), _exec_ok()]
        captured_prompts = []

        def capture_generate_sql(question, history):
            captured_prompts.append(question)
            return _nl2sql_ok()

        with patch("src.agent.generate_sql",     side_effect=capture_generate_sql), \
             patch("src.agent.execute_sql",       side_effect=exec_responses), \
             patch("src.agent.generate_narrative", return_value=_narrative_ok()):

            run_turn("Top brands?", [], conn)

        # First call: original question. Second call: correction prompt.
        assert len(captured_prompts) == 2
        correction_prompt = captured_prompts[1]
        assert "CatalogException" in correction_prompt    # AC1: error_type in signal
        assert "Column x not found" in correction_prompt  # AC1: error_message in signal
        assert "CORRECTION" in correction_prompt           # AC1: correction block present

    def test_correction_signal_contains_failed_sql(self, conn):
        """AC1: correction prompt includes the previous failed SQL."""
        failed_sql = "SELECT bad_col FROM fact_sales;"
        exec_responses = [_exec_err(), _exec_ok()]
        captured_prompts = []

        def capture_generate_sql(question, history):
            captured_prompts.append(question)
            return _nl2sql_ok(sql=failed_sql)

        with patch("src.agent.generate_sql",     side_effect=capture_generate_sql), \
             patch("src.agent.execute_sql",       side_effect=exec_responses), \
             patch("src.agent.generate_narrative", return_value=_narrative_ok()):

            run_turn("Top brands?", [], conn)

        assert failed_sql in captured_prompts[1]  # AC1: failed SQL in correction signal

    def test_retry_count_present_in_success_dict(self, conn):
        """AC4: retry_count key exposed in success response for downstream logging."""
        with patch("src.agent.generate_sql",      return_value=_nl2sql_ok()), \
             patch("src.agent.execute_sql",        return_value=_exec_ok()), \
             patch("src.agent.generate_narrative", return_value=_narrative_ok()):

            result = run_turn("Top brands?", [], conn)

        assert "retry_count" in result

    def test_retry_count_present_in_error_dict(self, conn):
        """AC4: retry_count key exposed in error response (execution failure path)."""
        with patch("src.agent.generate_sql",      return_value=_nl2sql_ok()), \
             patch("src.agent.execute_sql",        return_value=_exec_err()), \
             patch("src.agent.generate_narrative", return_value=_narrative_ok()):

            result = run_turn("Top brands?", [], conn)

        assert result["status"] == "error"
        assert "retry_count" in result

    def test_run_turn_never_raises(self, conn):
        """Safety: run_turn must not raise even when all three dependencies fail."""
        with patch("src.agent.generate_sql",      return_value=_nl2sql_ok()), \
             patch("src.agent.execute_sql",        return_value=_exec_err()), \
             patch("src.agent.generate_narrative", return_value=_narrative_err()):

            try:
                result = run_turn("Top brands?", [], conn)
                assert result["status"] == "error"
            except Exception as exc:
                pytest.fail(f"run_turn raised unexpectedly: {exc}")

    def test_nl2sql_error_returns_error_without_retrying(self, conn):
        """NL2SQL failures (LLM error / no sql delimiter) are not retried —
        the retry loop only handles execution errors."""
        nl2sql_error = {"error": "no_sql_delimiter", "raw": "Model output had no SQL."}

        with patch("src.agent.generate_sql",      return_value=nl2sql_error) as mock_gen, \
             patch("src.agent.execute_sql",        return_value=_exec_ok()) as mock_exec, \
             patch("src.agent.generate_narrative", return_value=_narrative_ok()):

            result = run_turn("Top brands?", [], conn)

        assert result["status"] == "error"
        assert result["error_stage"] == "nl2sql"
        mock_exec.assert_not_called()   # execute_sql never reached
        assert mock_gen.call_count == 1  # no retry on generation error


# ──────────────────────────────────────────────────────────────────────────────
# F-11 · CONVERSATION HISTORY MANAGEMENT  (AC1, AC3, AC4)
# ──────────────────────────────────────────────────────────────────────────────

class TestConversationHistory:

    def test_turn_index_zero_on_first_turn(self, conn):
        """AC4: turn_index = 0 when history is empty (first turn)."""
        with patch("src.agent.generate_sql",      return_value=_nl2sql_ok()), \
             patch("src.agent.execute_sql",        return_value=_exec_ok()), \
             patch("src.agent.generate_narrative", return_value=_narrative_ok()):

            result = run_turn("Q1?", [], conn)

        assert result["turn_index"] == 0

    def test_turn_index_increments_on_second_turn(self, conn):
        """AC4: turn_index = 1 on second call when history carries one entry."""
        with patch("src.agent.generate_sql",      return_value=_nl2sql_ok()), \
             patch("src.agent.execute_sql",        return_value=_exec_ok()), \
             patch("src.agent.generate_narrative", return_value=_narrative_ok()):

            r1 = run_turn("Q1?", [], conn)
            r2 = run_turn("Q2?", r1["conversation_history"], conn)

        assert r1["turn_index"] == 0
        assert r2["turn_index"] == 1

    def test_successful_turn_appended_to_history(self, conn):
        """AC1: on success, returned history contains one new entry with
        turn_index, user_question, sql, and result_summary."""
        question = "Top brands by revenue?"

        with patch("src.agent.generate_sql",      return_value=_nl2sql_ok("SELECT 1;")), \
             patch("src.agent.execute_sql",        return_value=_exec_ok()), \
             patch("src.agent.generate_narrative", return_value=_narrative_ok()):

            result = run_turn(question, [], conn)

        history = result["conversation_history"]
        assert len(history) == 1
        entry = history[0]
        assert entry["turn_index"] == 0
        assert entry["user_question"] == question
        assert entry["sql"] == "SELECT 1;"
        assert "result_summary" in entry
        assert len(entry["result_summary"]) > 0

    def test_failed_turn_not_appended_to_history(self, conn):
        """F-11: failed turns are not added to conversation_history."""
        history_before = []

        with patch("src.agent.generate_sql",      return_value=_nl2sql_ok()), \
             patch("src.agent.execute_sql",        return_value=_exec_err()), \
             patch("src.agent.generate_narrative", return_value=_narrative_ok()):

            result = run_turn("Bad query?", history_before, conn)

        assert result["status"] == "error"
        assert len(result["conversation_history"]) == 0

    def test_original_history_not_mutated(self, conn):
        """Copy-on-entry: caller's original list is never mutated by run_turn."""
        original = []

        with patch("src.agent.generate_sql",      return_value=_nl2sql_ok()), \
             patch("src.agent.execute_sql",        return_value=_exec_ok()), \
             patch("src.agent.generate_narrative", return_value=_narrative_ok()):

            result = run_turn("Q1?", original, conn)

        # Returned history has the new entry; original is still empty.
        assert len(result["conversation_history"]) == 1
        assert len(original) == 0  # caller's list untouched

    def test_history_passed_to_generate_sql(self, conn):
        """AC1: conversation_history is passed through to generate_sql on every turn."""
        existing_history = [
            {"turn_index": 0, "user_question": "Q0?",
             "sql": "SELECT 0;", "result_summary": "1 row: 0"},
        ]
        captured = []

        def capturing_generate_sql(question, history):
            captured.append(list(history))
            return _nl2sql_ok()

        with patch("src.agent.generate_sql",      side_effect=capturing_generate_sql), \
             patch("src.agent.execute_sql",        return_value=_exec_ok()), \
             patch("src.agent.generate_narrative", return_value=_narrative_ok()):

            run_turn("Q1?", existing_history, conn)

        # generate_sql should have received the existing history.
        assert len(captured) >= 1
        assert captured[0] == existing_history

    def test_five_turn_history_accumulates_correctly(self, conn):
        """AC2 (structural): five sequential calls build a history of five entries,
        each with the correct turn_index. (Live contextual test is in sprint3_validation.py.)"""
        history = []
        questions = [f"Question {i}?" for i in range(5)]

        with patch("src.agent.generate_sql",      return_value=_nl2sql_ok()), \
             patch("src.agent.execute_sql",        return_value=_exec_ok()), \
             patch("src.agent.generate_narrative", return_value=_narrative_ok()):

            for i, q in enumerate(questions):
                result = run_turn(q, history, conn)
                assert result["status"] == "success"
                assert result["turn_index"] == i
                history = result["conversation_history"]

        assert len(history) == 5
        for i, entry in enumerate(history):
            assert entry["turn_index"] == i
            assert entry["user_question"] == questions[i]

    def test_history_truncation_flag_set_when_overflow(self, conn):
        """AC3: history_truncated = True when len(history) > MAX_HISTORY_TURNS (5)."""
        # Build a history with 6 entries (one over MAX_HISTORY_TURNS=5).
        oversized_history = [
            {"turn_index": i, "user_question": f"Q{i}?",
             "sql": f"SELECT {i};", "result_summary": f"{i} rows"}
            for i in range(6)
        ]

        with patch("src.agent.generate_sql",      return_value=_nl2sql_ok()), \
             patch("src.agent.execute_sql",        return_value=_exec_ok()), \
             patch("src.agent.generate_narrative", return_value=_narrative_ok()):

            result = run_turn("Q6?", oversized_history, conn)

        assert result["history_truncated"] is True  # AC3

    def test_history_truncation_flag_false_within_limit(self, conn):
        """AC3: history_truncated = False when history is within MAX_HISTORY_TURNS."""
        normal_history = [
            {"turn_index": i, "user_question": f"Q{i}?",
             "sql": f"SELECT {i};", "result_summary": f"{i} rows"}
            for i in range(3)
        ]

        with patch("src.agent.generate_sql",      return_value=_nl2sql_ok()), \
             patch("src.agent.execute_sql",        return_value=_exec_ok()), \
             patch("src.agent.generate_narrative", return_value=_narrative_ok()):

            result = run_turn("Q3?", normal_history, conn)

        assert result["history_truncated"] is False

    def test_turn_index_in_success_dict(self, conn):
        """AC4: turn_index key present in success response."""
        with patch("src.agent.generate_sql",      return_value=_nl2sql_ok()), \
             patch("src.agent.execute_sql",        return_value=_exec_ok()), \
             patch("src.agent.generate_narrative", return_value=_narrative_ok()):

            result = run_turn("Q?", [], conn)

        assert "turn_index" in result

    def test_turn_index_in_error_dict(self, conn):
        """AC4: turn_index key present in error response."""
        with patch("src.agent.generate_sql",      return_value=_nl2sql_ok()), \
             patch("src.agent.execute_sql",        return_value=_exec_err()), \
             patch("src.agent.generate_narrative", return_value=_narrative_ok()):

            result = run_turn("Q?", [], conn)

        assert "turn_index" in result


# ──────────────────────────────────────────────────────────────────────────────
# F-12 · NARRATIVE INTEGRATION IN AGENT  (AC3)
# ──────────────────────────────────────────────────────────────────────────────

class TestNarrativeIntegration:

    def test_narrative_present_in_success_dict(self, conn):
        """AC3: narrative key present in unified response object."""
        with patch("src.agent.generate_sql",      return_value=_nl2sql_ok()), \
             patch("src.agent.execute_sql",        return_value=_exec_ok()), \
             patch("src.agent.generate_narrative", return_value=_narrative_ok("Revenue was £300.")):

            result = run_turn("Revenue?", [], conn)

        assert "narrative" in result
        assert result["narrative"] == "Revenue was £300."

    def test_sql_present_alongside_narrative(self, conn):
        """AC3: both sql and narrative keys present in the same response dict."""
        with patch("src.agent.generate_sql",      return_value=_nl2sql_ok("SELECT 42;")), \
             patch("src.agent.execute_sql",        return_value=_exec_ok()), \
             patch("src.agent.generate_narrative", return_value=_narrative_ok()):

            result = run_turn("Revenue?", [], conn)

        assert result["sql"] == "SELECT 42;"
        assert "narrative" in result

    def test_narrative_failure_is_nonfatal(self, conn):
        """Narrative errors must not fail the turn — status=success with narrative=''."""
        with patch("src.agent.generate_sql",      return_value=_nl2sql_ok()), \
             patch("src.agent.execute_sql",        return_value=_exec_ok()), \
             patch("src.agent.generate_narrative", return_value=_narrative_err()):

            result = run_turn("Revenue?", [], conn)

        assert result["status"] == "success"
        assert result["narrative"] == ""

    def test_success_dict_has_all_required_keys(self, conn):
        """Full key contract for success response dict."""
        required_keys = {
            "status", "user_question", "sql", "reasoning", "data",
            "row_count", "exec_time_ms", "narrative", "retry_count",
            "turn_index", "history_truncated", "raw_nl2sql",
            "raw_narrative", "conversation_history",
        }

        with patch("src.agent.generate_sql",      return_value=_nl2sql_ok()), \
             patch("src.agent.execute_sql",        return_value=_exec_ok()), \
             patch("src.agent.generate_narrative", return_value=_narrative_ok()):

            result = run_turn("Q?", [], conn)

        missing = required_keys - set(result.keys())
        assert missing == set(), f"Missing keys in success dict: {missing}"
