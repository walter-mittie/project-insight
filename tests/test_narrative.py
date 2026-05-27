"""
tests/test_narrative.py
-----------------------
F-12 · Narrative Response Generation — Unit Tests

Project Insight: Agentic Conversational BI 

All Gemini API calls are mocked.  Tests verify the narrative module in
isolation: correct prompt construction, DataFrame summarisation, return
dict contract, error handling, and no-raise guarantee.

Mocking strategy
----------------
narrative.py calls get_llm_response() from src.llm.  We patch:
    src.narrative.get_llm_response

Run with:
    python -m pytest tests/test_narrative.py -v
"""

import sys
import os

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.join(_TESTS_DIR, "..")
sys.path.insert(0, os.path.abspath(_PROJECT_ROOT))

from unittest.mock import patch
import pandas as pd
import pytest

from src.narrative import generate_narrative, _summarise_df, MAX_SUMMARY_ROWS
from src.llm import LLMError


# ──────────────────────────────────────────────────────────────────────────────
# HELPERS
# ──────────────────────────────────────────────────────────────────────────────


def _small_df(n: int = 3) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "brand": [f"Brand{i}" for i in range(n)],
            "revenue": [float((i + 1) * 1000) for i in range(n)],
        }
    )


def _large_df(n: int = 20) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "brand": [f"Brand{i}" for i in range(n)],
            "revenue": [float((i + 1) * 1000) for i in range(n)],
        }
    )


# ──────────────────────────────────────────────────────────────────────────────
# F-12 · NARRATIVE GENERATION  (AC1, AC2, AC3, AC4)
# ──────────────────────────────────────────────────────────────────────────────


class TestGenerateNarrative:
    def test_success_dict_structure(self):
        """AC1 + AC3: success response contains status, narrative, raw_narrative."""
        with patch(
            "src.narrative.get_llm_response",
            return_value="Brand2 had the highest revenue at £3,000.",
        ):
            result = generate_narrative("Top brands?", _small_df())

        assert result["status"] == "success"
        assert "narrative" in result
        assert "raw_narrative" in result
        assert result["narrative"] == "Brand2 had the highest revenue at £3,000."

    def test_llm_is_called(self):
        """AC1: get_llm_response is invoked on every generate_narrative call."""
        with patch(
            "src.narrative.get_llm_response", return_value="Some narrative."
        ) as mock_llm:
            generate_narrative("Revenue?", _small_df())

        mock_llm.assert_called_once()

    def test_question_in_user_prompt(self):
        """AC1: the original user question is included in the prompt sent to the LLM."""
        captured = []

        def capture(prompt, system_prompt):
            captured.append(prompt)
            return "Narrative text."

        with patch("src.narrative.get_llm_response", side_effect=capture):
            generate_narrative("What were the top brands in Q3 2025?", _small_df())

        assert len(captured) == 1
        assert "What were the top brands in Q3 2025?" in captured[0]

    def test_data_values_in_user_prompt(self):
        """AC1: DataFrame content (at least one data value) appears in the prompt."""
        df = _small_df(3)
        captured = []

        def capture(prompt, system_prompt):
            captured.append(prompt)
            return "Narrative text."

        with patch("src.narrative.get_llm_response", side_effect=capture):
            generate_narrative("Revenue?", df)

        # "Brand0" and "1000.0" should both appear in the prompt summary.
        assert "Brand0" in captured[0]
        assert "1000" in captured[0]

    def test_llm_error_returns_error_dict(self):
        """Error path: LLMError → structured error dict with correct keys."""
        with patch(
            "src.narrative.get_llm_response",
            side_effect=LLMError("Rate limit exceeded"),
        ):
            result = generate_narrative("Revenue?", _small_df())

        assert result["status"] == "error"
        assert result["error_type"] == "llm_error"
        assert "Rate limit exceeded" in result["error_message"]
        assert result["narrative"] == ""
        assert result["raw_narrative"] == ""

    def test_never_raises_on_llm_error(self):
        """Safety: generate_narrative must not propagate LLMError."""
        with patch(
            "src.narrative.get_llm_response", side_effect=LLMError("API failure")
        ):
            try:
                result = generate_narrative("Revenue?", _small_df())
                assert result["status"] == "error"
            except Exception as exc:
                pytest.fail(f"generate_narrative raised unexpectedly: {exc}")

    def test_empty_dataframe_does_not_raise(self):
        """Edge case: empty DataFrame is handled gracefully, LLM still called."""
        with patch(
            "src.narrative.get_llm_response",
            return_value="No data was found for this query.",
        ):
            result = generate_narrative("Revenue?", pd.DataFrame())

        assert result["status"] == "success"
        assert result["narrative"] == "No data was found for this query."

    def test_error_dict_has_all_keys(self):
        """Error dict contains all four required keys for agent.py handling."""
        with patch("src.narrative.get_llm_response", side_effect=LLMError("fail")):
            result = generate_narrative("Q?", _small_df())

        for key in (
            "status",
            "error_type",
            "error_message",
            "narrative",
            "raw_narrative",
        ):
            assert key in result, f"Missing key: {key}"


# ──────────────────────────────────────────────────────────────────────────────
# DATAFRAME SUMMARISATION  (_summarise_df helper)
# ──────────────────────────────────────────────────────────────────────────────


class TestSummariseDf:
    def test_empty_df_returns_placeholder(self):
        """Empty DataFrame → '(no rows returned)' rather than an empty string."""
        result = _summarise_df(pd.DataFrame())
        assert result == "(no rows returned)"

    def test_small_df_renders_all_rows(self):
        """DataFrame with <= MAX_SUMMARY_ROWS rows: all rows included."""
        df = _small_df(MAX_SUMMARY_ROWS)
        summary = _summarise_df(df)
        # All brand values should appear.
        for i in range(MAX_SUMMARY_ROWS):
            assert f"Brand{i}" in summary

    def test_large_df_truncated_with_note(self):
        """DataFrame with > MAX_SUMMARY_ROWS rows: truncation note appended."""
        df = _large_df(MAX_SUMMARY_ROWS + 5)
        summary = _summarise_df(df)
        assert f"showing first {MAX_SUMMARY_ROWS}" in summary
        # Rows beyond MAX_SUMMARY_ROWS must not appear.
        assert f"Brand{MAX_SUMMARY_ROWS}" not in summary

    def test_large_df_shows_total_row_count(self):
        """Truncation note includes total row count so the LLM knows data exists."""
        total = MAX_SUMMARY_ROWS + 7
        summary = _summarise_df(_large_df(total))
        assert str(total) in summary

    def test_small_df_no_truncation_note(self):
        """Small results must not include a spurious truncation note."""
        summary = _summarise_df(_small_df(3))
        assert "showing first" not in summary
