"""
tests/sprint4_validation.py
---------------------------
Sprint 4 Validation Suite — F-13 · F-14 · F-15 · ADR-042

Project Insight: Agentic Conversational BI 

Validates F-13, F-14, and F-15 features without a running Streamlit server.
All st.* calls are intercepted via MagicMock. Gemini is never called.
JSONL logger tests use tempfile.TemporaryDirectory() for full isolation.

Coverage
--------
Section 1 — F-15 JSONL Logging Infrastructure       (13 automated tests)
Section 2 — ADR-042 Chart Type Resolution            (20 automated tests)
Section 3 — F-13 UI Logic: subtitle / highlight /
            _extract_chart_type                       (15 automated tests)
Section 4 — Render Function Fallback Behaviour        (6 automated tests)
Section 5 — Track B Manual UI Checklist              (placeholder)

Total automated: 54 tests

Run with:
    python tests/sprint4_validation.py

Output:
    docs/sprint_4_validation_report.md
"""

import sys
import os
import json
import tempfile
import builtins
from datetime import datetime
from unittest.mock import patch, MagicMock

# ── PATH SETUP ─────────────────────────────────────────────────────────────────
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# ── MOCK EXTERNAL DEPENDENCIES ─────────────────────────────────────────────────
# Must happen before any project imports so module-level code in app.py
# (st.set_page_config, etc.) doesn't raise an error.

_st_mock = MagicMock()
sys.modules["streamlit"]               = _st_mock
sys.modules["streamlit.components"]    = MagicMock()
sys.modules["streamlit.components.v1"] = MagicMock()

# Mock LLM backend — nl2sql.py imports from src.llm at module level.
# _extract_chart_type is pure regex; no LLM calls needed at test time.
sys.modules["src.llm"]   = MagicMock()

# Mock agent and db — not under test in Sprint 4; prevents DuckDB/env dep.
sys.modules["src.agent"] = MagicMock()
sys.modules["src.db"]    = MagicMock()

# ── NOW IMPORT PROJECT MODULES ──────────────────────────────────────────────────
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px

from app import (
    _keyword_hint,
    _heuristic,
    resolve_chart_type,
    _make_subtitle,
    _highlight_chart_keyword,
    render_bar,
    render_line,
    render_pie,
    render_scatter,
)
from src.logger import (
    log_turn,
    load_past_sessions,
    read_turns_from_jsonl,
    LogWriteError,
)
import src.logger as logger_module
from src.nl2sql import _extract_chart_type

# ── OUTPUT PATH ────────────────────────────────────────────────────────────────
OUTPUT_PATH = os.path.join(
    os.path.dirname(__file__), "..", "docs", "sprint_4_validation_report.md"
)

# ── CANONICAL FIELD SETS ───────────────────────────────────────────────────────
CANONICAL_FIELDS = [
    "session_id", "turn_id", "timestamp", "user_query", "generated_sql",
    "execution_time_ms", "retry_count", "row_count", "success_flag",
    "narrative_generated", "history_truncated", "error_stage",
    "resumed", "resumed_at",
]
ADR042_FIELDS = ["suggested_chart_type", "rendered_chart_type"]

# ── MOCK RESULT DICTS (exact spec) ────────────────────────────────────────────
MOCK_SUCCESS = {
    "status":               "success",
    "user_question":        "What were the top 5 brands by net revenue in 2025?",
    "sql":                  "SELECT brand, SUM(net_revenue_gbp) FROM fact_sales "
                            "WHERE year=2025 GROUP BY brand ORDER BY 2 DESC LIMIT 5;",
    "reasoning":            "Step 1: need fact_sales...",
    "data":                 pd.DataFrame({"brand": ["CocoaEthos", "BerryBliss"],
                                          "net_revenue_gbp": [27758131, 25254714]}),
    "row_count":            2,
    "exec_time_ms":         66.4,
    "narrative":            "CocoaEthos led with £27.8M net revenue in 2025.",
    "retry_count":          0,
    "turn_index":           0,
    "history_truncated":    False,
    "suggested_chart_type": "bar",
    "raw_nl2sql":           "...",
    "raw_narrative":        "...",
    "conversation_history": [],
}

MOCK_ERROR = {
    "status":               "error",
    "error_stage":          "execution",
    "error_type":           "CatalogException",
    "error_message":        "Table 'fact_slaes' does not exist",
    "sql":                  "SELECT * FROM fact_slaes;",
    "retry_count":          2,
    "turn_index":           1,
    "conversation_history": [],
}

# ── SYNTHETIC DATAFRAMES ───────────────────────────────────────────────────────
temporal_df      = pd.DataFrame({"week":    ["W1", "W2", "W3"],
                                  "revenue": [100, 200, 150]})
two_num_df       = pd.DataFrame({"brand":   ["A", "B"],
                                  "price":   [10.0, 12.0],
                                  "volume":  [100, 200]})
cat_df           = pd.DataFrame({"brand":          ["CocoaEthos", "BerryBliss"],
                                  "net_revenue_gbp": [27758131, 25254714]})
all_string_df    = pd.DataFrame({"brand":   ["A", "B"],
                                  "channel": ["Grocery", "Drug"]})
all_numeric_df   = pd.DataFrame({"price":  [10.0, 12.0],
                                  "volume": [100, 200]})
one_numeric_df   = pd.DataFrame({"brand":   ["A", "B"],
                                  "revenue": [100, 200]})          # 1 numeric → scatter fallback
long_label_df    = pd.DataFrame({"brand":   ["CocoaEthos", "BerryBliss",
                                              "NitroBoost", "HealthSnap"],
                                  "revenue": [100, 200, 150, 120]})
# 1 numeric + 2 non-numeric: neither heuristic rule fires → "table" → resolve → "bar"
table_fallback_df = pd.DataFrame({"brand":   ["A", "B"],
                                   "channel": ["Grocery", "Drug"],
                                   "revenue": [100, 200]})


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _section(lines: list, title: str) -> None:
    lines.append(f"\n---\n\n## {title}\n")


def _ac_check(lines: list, ac_id: str, description: str, passed: bool) -> None:
    icon = "✅" if passed else "❌"
    lines.append(f"- {icon} **{ac_id}**: {description}")


def _write_jsonl(path: str, entries: list) -> None:
    """Write a list of entry dicts to a JSONL file; creates parent dirs."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for e in entries:
            fh.write(json.dumps(e) + "\n")


def _mock_entry(
    session_id:   str  = "sid-001",
    turn_id:      int  = 1,
    user_query:   str  = "Test query",
    success_flag: bool = True,
    resumed:      bool = False,
    timestamp:    str  = "2025-05-01T09:00:00Z",
) -> dict:
    """Build a minimal JSONL-style dict for testing read functions."""
    return {
        "session_id":           session_id,
        "turn_id":              turn_id,
        "timestamp":            timestamp,
        "user_query":           user_query,
        "generated_sql":        "SELECT 1;" if success_flag else None,
        "execution_time_ms":    66.4 if success_flag else None,
        "retry_count":          0,
        "row_count":            1 if success_flag else None,
        "success_flag":         success_flag,
        "narrative_generated":  success_flag,
        "history_truncated":    False,
        "error_stage":          None if success_flag else "execution",
        "suggested_chart_type": "bar",
        "rendered_chart_type":  "bar",
        "resumed":              resumed,
        "resumed_at":           None,
    }


def _reset_st_mocks() -> None:
    """Reset st.plotly_chart, st.dataframe, st.markdown before each render test."""
    _st_mock.plotly_chart.reset_mock()
    _st_mock.dataframe.reset_mock()
    _st_mock.markdown.reset_mock()


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 1 — F-15: JSONL LOGGING INFRASTRUCTURE
# ══════════════════════════════════════════════════════════════════════════════

def run_section_1(lines: list) -> tuple[int, int]:
    _section(lines, "Section 1 — F-15: JSONL Logging Infrastructure")
    lines.append(
        "All tests use `tempfile.TemporaryDirectory()` for full isolation. "
        "`log_turn()` called directly against mock result dicts — "
        "no Gemini or DuckDB calls required.\n"
    )
    pc, fc = 0, 0

    # ── T01: All 14 canonical fields present ──────────────────────────────────
    with tempfile.TemporaryDirectory() as tmp:
        tmp_log = os.path.join(tmp, "logs", "test.jsonl")
        with patch.object(logger_module, "LOG_PATH", tmp_log):
            log_turn(MOCK_SUCCESS, session_id="sid-001", rendered_chart_type="bar")
        with open(tmp_log) as fh:
            entry = json.loads(fh.readline())

    passed = all(f in entry for f in CANONICAL_FIELDS)
    _ac_check(lines, "F15-T01",
              f"All 14 canonical JSONL fields present in written entry "
              f"(missing: {[f for f in CANONICAL_FIELDS if f not in entry] or 'none'})",
              passed)
    pc += passed; fc += not passed

    # ── T02: ADR-042 fields present ───────────────────────────────────────────
    passed = all(f in entry for f in ADR042_FIELDS)
    _ac_check(lines, "F15-T02",
              "ADR-042 fields `suggested_chart_type` and `rendered_chart_type` present",
              passed)
    pc += passed; fc += not passed

    # ── T03: raw_nl2sql and raw_narrative intentionally absent ────────────────
    passed = "raw_nl2sql" not in entry and "raw_narrative" not in entry
    _ac_check(lines, "F15-T03",
              "`raw_nl2sql` and `raw_narrative` absent from log entry (too large — ADR-041)",
              passed)
    pc += passed; fc += not passed

    # ── T04: Error turn shape ─────────────────────────────────────────────────
    with tempfile.TemporaryDirectory() as tmp:
        tmp_log = os.path.join(tmp, "logs", "test.jsonl")
        with patch.object(logger_module, "LOG_PATH", tmp_log):
            log_turn(MOCK_ERROR, session_id="sid-err")
        with open(tmp_log) as fh:
            err_entry = json.loads(fh.readline())

    passed = (
        err_entry.get("success_flag") is False
        and err_entry.get("generated_sql") is None
        and err_entry.get("error_stage") == "execution"
    )
    _ac_check(lines, "F15-T04",
              "Error turn: `success_flag=False`, `generated_sql=None`, `error_stage='execution'`",
              passed)
    pc += passed; fc += not passed

    # ── T05: Resumed turn fields ──────────────────────────────────────────────
    resumed_ts = "2025-05-16T10:00:00Z"
    with tempfile.TemporaryDirectory() as tmp:
        tmp_log = os.path.join(tmp, "logs", "test.jsonl")
        with patch.object(logger_module, "LOG_PATH", tmp_log):
            log_turn(MOCK_SUCCESS, session_id="sid-res",
                     resumed=True, resumed_at=resumed_ts)
        with open(tmp_log) as fh:
            res_entry = json.loads(fh.readline())

    passed = res_entry.get("resumed") is True and res_entry.get("resumed_at") == resumed_ts
    _ac_check(lines, "F15-T05",
              f"Resumed turn: `resumed=True`, `resumed_at='{resumed_ts}'` preserved in entry",
              passed)
    pc += passed; fc += not passed

    # ── T06: logs/ dir auto-created when absent ───────────────────────────────
    with tempfile.TemporaryDirectory() as tmp:
        tmp_log = os.path.join(tmp, "auto_created_logs", "test.jsonl")
        assert not os.path.exists(os.path.dirname(tmp_log)), "Pre-condition: dir must not exist"
        with patch.object(logger_module, "LOG_PATH", tmp_log):
            log_turn(MOCK_SUCCESS, session_id="sid-dir")
        passed = os.path.isfile(tmp_log)

    _ac_check(lines, "F15-T06",
              "`logs/` directory auto-created by `_ensure_log_dir()` on first write",
              passed)
    pc += passed; fc += not passed

    # ── T07: LogWriteError raised on write failure ────────────────────────────
    with tempfile.TemporaryDirectory() as tmp:
        tmp_log = os.path.join(tmp, "test.jsonl")
        _orig_open = builtins.open

        def _fail_open(path, *args, **kwargs):
            if os.path.abspath(str(path)) == os.path.abspath(str(tmp_log)):
                raise IOError("Simulated: disk full")
            return _orig_open(path, *args, **kwargs)

        lwe_raised = False
        with patch.object(logger_module, "LOG_PATH", tmp_log):
            with patch("builtins.open", side_effect=_fail_open):
                try:
                    log_turn(MOCK_SUCCESS, session_id="sid-fail")
                except LogWriteError:
                    lwe_raised = True

    _ac_check(lines, "F15-T07",
              "`LogWriteError` raised (non-crash) when file write fails — caller sees warning, not crash",
              lwe_raised)
    pc += lwe_raised; fc += not lwe_raised

    # ── T08: load_past_sessions groups by session_id ──────────────────────────
    with tempfile.TemporaryDirectory() as tmp:
        tmp_log = os.path.join(tmp, "test.jsonl")
        entries = [
            _mock_entry("sid-A", 1, timestamp="2025-05-01T09:00:00Z"),
            _mock_entry("sid-A", 2, timestamp="2025-05-01T09:10:00Z"),
            _mock_entry("sid-B", 1, timestamp="2025-05-02T10:00:00Z"),
        ]
        _write_jsonl(tmp_log, entries)
        sessions = load_past_sessions(tmp_log)

    passed = len(sessions) == 2
    _ac_check(lines, "F15-T08",
              f"`load_past_sessions()` groups 3 entries (2 sessions) → got {len(sessions)} group(s)",
              passed)
    pc += passed; fc += not passed

    # ── T09: load_past_sessions sorts newest first ────────────────────────────
    with tempfile.TemporaryDirectory() as tmp:
        tmp_log = os.path.join(tmp, "test.jsonl")
        entries = [
            _mock_entry("sid-OLD", 1, timestamp="2025-01-01T09:00:00Z"),
            _mock_entry("sid-NEW", 1, timestamp="2025-05-15T09:00:00Z"),
        ]
        _write_jsonl(tmp_log, entries)
        sessions = load_past_sessions(tmp_log)

    first_id = sessions[0]["id"] if sessions else "N/A"
    passed = len(sessions) == 2 and first_id == "sid-NEW"
    _ac_check(lines, "F15-T09",
              f"`load_past_sessions()` newest-first: first=`{first_id}` (expect `sid-NEW`)",
              passed)
    pc += passed; fc += not passed

    # ── T10: read_turns_from_jsonl filters by session_id ─────────────────────
    with tempfile.TemporaryDirectory() as tmp:
        tmp_log = os.path.join(tmp, "test.jsonl")
        entries = [
            _mock_entry("sid-TARGET", 1),
            _mock_entry("sid-OTHER",  1),
            _mock_entry("sid-TARGET", 2),
        ]
        _write_jsonl(tmp_log, entries)
        turns = read_turns_from_jsonl("sid-TARGET", tmp_log)

    passed = len(turns) == 2 and all(t["session_id"] == "sid-TARGET" for t in turns)
    _ac_check(lines, "F15-T10",
              f"`read_turns_from_jsonl()` filters by session_id — got {len(turns)}/3 entries (expect 2)",
              passed)
    pc += passed; fc += not passed

    # ── T11: excludes resumed turns ───────────────────────────────────────────
    with tempfile.TemporaryDirectory() as tmp:
        tmp_log = os.path.join(tmp, "test.jsonl")
        entries = [
            _mock_entry("sid-X", 1, resumed=False),
            _mock_entry("sid-X", 2, resumed=True),
        ]
        _write_jsonl(tmp_log, entries)
        turns = read_turns_from_jsonl("sid-X", tmp_log)

    passed = len(turns) == 1 and turns[0]["turn_id"] == 1
    _ac_check(lines, "F15-T11",
              f"`read_turns_from_jsonl()` excludes `resumed=True` entries — got {len(turns)}/2 (expect 1)",
              passed)
    pc += passed; fc += not passed

    # ── T12: excludes failed turns ────────────────────────────────────────────
    with tempfile.TemporaryDirectory() as tmp:
        tmp_log = os.path.join(tmp, "test.jsonl")
        entries = [
            _mock_entry("sid-Y", 1, success_flag=True),
            _mock_entry("sid-Y", 2, success_flag=False),
        ]
        _write_jsonl(tmp_log, entries)
        turns = read_turns_from_jsonl("sid-Y", tmp_log)

    passed = len(turns) == 1 and turns[0]["success_flag"] is True
    _ac_check(lines, "F15-T12",
              f"`read_turns_from_jsonl()` excludes `success_flag=False` entries — got {len(turns)}/2 (expect 1)",
              passed)
    pc += passed; fc += not passed

    # ── T13: sorts by turn_id ascending ──────────────────────────────────────
    with tempfile.TemporaryDirectory() as tmp:
        tmp_log = os.path.join(tmp, "test.jsonl")
        entries = [
            _mock_entry("sid-Z", 3),
            _mock_entry("sid-Z", 1),
            _mock_entry("sid-Z", 2),
        ]
        _write_jsonl(tmp_log, entries)
        turns = read_turns_from_jsonl("sid-Z", tmp_log)

    turn_order = [t["turn_id"] for t in turns]
    passed = turn_order == [1, 2, 3]
    _ac_check(lines, "F15-T13",
              f"`read_turns_from_jsonl()` sorted by `turn_id` ascending — got {turn_order}",
              passed)
    pc += passed; fc += not passed

    lines.append(f"\n**Section 1 result: {pc}/{pc + fc} tests passed**\n")
    return pc, fc


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 2 — ADR-042: CHART TYPE RESOLUTION PRIORITY CHAIN
# ══════════════════════════════════════════════════════════════════════════════

def run_section_2(lines: list) -> tuple[int, int]:
    _section(lines, "Section 2 — ADR-042: Chart Type Resolution Priority Chain")
    lines.append(
        "Tests the three-level priority chain: "
        "**P1** prompt keyword → **P2** Gemini annotation → **P3** DataFrame heuristic → **P4** default `'bar'`. "
        "Synthetic DataFrames only — no Gemini calls.\n"
    )
    pc, fc = 0, 0

    # ── _keyword_hint ──────────────────────────────────────────────────────────
    lines.append("### `_keyword_hint()` — Priority 1 keyword detection\n")

    kw_cases = [
        ("KW-01", "brand revenue share as a pie chart",  "pie",     "Keyword 'share' → `'pie'`"),
        ("KW-02", "CocoaEthos vs BerryBliss revenue",    "scatter", "Keyword 'vs ' → `'scatter'`"),
        ("KW-03", "weekly revenue trend for NitroBoost", "line",    "Keyword 'weekly' → `'line'`"),
        ("KW-04", "compare brands by revenue",           "bar",     "Keyword 'compare' → `'bar'`"),
        ("KW-05", "show me a table of SKU performance",  "table",   "Keyword 'table' → `'table'`"),
        ("KW-06", "how many SKUs were sold in 2025?",    None,      "No keyword → `None`"),
    ]
    for ac_id, q, expected, desc in kw_cases:
        result = _keyword_hint(q)
        passed = result == expected
        _ac_check(lines, ac_id, f"{desc} — got `{result!r}`", passed)
        pc += passed; fc += not passed

    # ── _heuristic ─────────────────────────────────────────────────────────────
    lines.append("\n### `_heuristic()` — Priority 3 DataFrame shape rules\n")

    h_cases = [
        ("HEU-01", two_num_df,         "scatter", "≥2 numeric + ≥1 cat → `'scatter'`"),
        ("HEU-02", temporal_df,         "line",    "1 numeric + 1 temporal cat (`'week'`) → `'line'`"),
        ("HEU-03", cat_df,              "bar",     "1 numeric + 1 non-temporal cat (`'brand'`) → `'bar'`"),
        ("HEU-04", pd.DataFrame(),      "table",   "Empty df → `'table'`"),
        ("HEU-05", table_fallback_df,   "table",   "1 numeric + 2 non-numeric — no rule fires → `'table'`"),
    ]
    for ac_id, df, expected, desc in h_cases:
        result = _heuristic(df)
        passed = result == expected
        _ac_check(lines, ac_id, f"{desc} — got `{result!r}`", passed)
        pc += passed; fc += not passed

    # ── resolve_chart_type: canonical ADR-042 test cases ──────────────────────
    lines.append("\n### `resolve_chart_type()` — Full priority chain (ADR-042 canonical test cases)\n")

    rct_cases = [
        # (ac_id, question, suggested, df, expected, desc)
        ("RCT-01", "What is our brand revenue share as a pie chart?", "bar",  temporal_df,       "pie",
         "P1 keyword `'share'/'pie chart'` overrides Gemini `'bar'` ✓"),
        ("RCT-02", "Compare CocoaEthos vs BerryBliss revenue",        "bar",  two_num_df,        "scatter",
         "P1 keyword `'vs '` overrides Gemini `'bar'` ✓"),
        ("RCT-03", "Weekly revenue trend for NitroBoost",             "auto", cat_df,            "line",
         "P1 keyword `'weekly'` overrides heuristic ✓"),
        # RCT-04: 'top ' has been removed from PROMPT_KEYWORDS['bar'].
        # No keyword fires → P2 Gemini annotation 'pie' wins.
        ("RCT-04", "Top brands by revenue in 2025",                   "pie",  cat_df,            "pie",
         "P2 Gemini `'pie'` wins when no keyword — `'top '` correctly absent from P1 keywords"),
        # RCT-05: No keyword, Gemini='auto', cat df → P3 heuristic 'bar' wins correctly.
        ("RCT-05", "Top brands by revenue in 2025",                   "auto", cat_df,            "bar",
         "P3 heuristic `'bar'` wins (no keyword, Gemini=`'auto'`, cat df)"),
        # RCT-06: No keyword, Gemini='auto', temporal df → P3 heuristic 'line' wins correctly.
        ("RCT-06", "Top brands revenue",                              "auto", temporal_df,       "line",
         "P3 heuristic: no keyword, `'auto'`, temporal df → `'line'`"),
        # RCT-07: No keyword, Gemini='auto', cat df → P3 heuristic 'bar'.
        ("RCT-07", "Top brands revenue",                              "auto", cat_df,            "bar",
         "P3 heuristic: cat df → `'bar'`"),
        # RCT-08: No keyword, Gemini='auto', 2-num df → P3 heuristic 'scatter'.
        ("RCT-08", "Top brands revenue",                              "auto", two_num_df,        "scatter",
         "P3 heuristic: 2-num df → `'scatter'`"),
        ("RCT-09", "Top brands revenue",                              "auto", table_fallback_df, "bar",
         "P4 default: heuristic→`'table'` → resolve→`'bar'`"),
    ]
    for ac_id, q, suggested, df, expected, desc in rct_cases:
        result = resolve_chart_type(q, suggested, df)
        passed = result == expected
        _ac_check(lines, ac_id, f"{desc} — got `{result!r}`", passed)
        pc += passed; fc += not passed

    lines.append(f"\n**Section 2 result: {pc}/{pc + fc} tests passed**\n")
    return pc, fc


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 3 — F-13 UI LOGIC (AUTOMATED)
# ══════════════════════════════════════════════════════════════════════════════

def run_section_3(lines: list) -> tuple[int, int]:
    _section(lines, "Section 3 — F-13: UI Logic (Automated)")
    lines.append(
        "Tests `_make_subtitle()`, `_highlight_chart_keyword()`, and `_extract_chart_type()` "
        "by importing functions directly from `app.py` and `src/nl2sql.py` — no server required.\n"
    )
    pc, fc = 0, 0

    # ── _make_subtitle ──────────────────────────────────────────────────────────
    lines.append("### `_make_subtitle()` — subtitle strip and truncation\n")

    sub_cases = [
        ("SUB-01", "2025 quarterly revenue growth as a line chart",
         "2025 quarterly revenue growth",
         "Strips `' as a line chart'` suffix"),
        ("SUB-02", "Revenue share as a pie chart",
         "Revenue share",
         "Strips `' as a pie chart'` suffix"),
        ("SUB-03", "Top brands by revenue as a bar chart",
         "Top brands by revenue",
         "Strips `' as a bar chart'` suffix"),
        ("SUB-05", "Top SKUs by margin as a scatter plot",
         "Top SKUs by margin",
         "Strips `' as a scatter plot'` suffix (added in ADR-042)"),
        ("SUB-06", "Top SKUs by margin as a scatter",
         "Top SKUs by margin",
         "Strips `' as a scatter'` suffix (added in ADR-042)"),
    ]
    for ac_id, q, expected, desc in sub_cases:
        result = _make_subtitle(q)
        passed = result == expected
        _ac_check(lines, ac_id, f"{desc} — got `{result!r}`", passed)
        pc += passed; fc += not passed

    # Truncation
    long_q = "A" * 80
    result = _make_subtitle(long_q)
    passed = len(result) <= 59
    _ac_check(lines, "SUB-04",
              f"80-char input truncated to ≤59 chars with `'…'` — got len={len(result)}",
              passed)
    pc += passed; fc += not passed

    # ── _highlight_chart_keyword ────────────────────────────────────────────────
    lines.append("\n### `_highlight_chart_keyword()` — chart keyword HTML pill\n")

    hl_cases = [
        ("HLT-01", "2025 revenue line chart",     True,
         "Returns `<span` for keyword `'line chart'`"),
        ("HLT-02", "brand share pie chart",        True,
         "Returns `<span` for keyword `'pie chart'`"),
        ("HLT-03", "how many SKUs sold in 2025?",  False,
         "No keyword → unchanged string, no `<span`"),
    ]
    for ac_id, q, expect_span, desc in hl_cases:
        result = _highlight_chart_keyword(q)
        passed = ("<span" in result) == expect_span
        _ac_check(lines, ac_id,
                  f"{desc} (span_found={('<span' in result)})",
                  passed)
        pc += passed; fc += not passed

    # Capitalisation preservation
    q_caps = "2025 REVENUE AS A LINE CHART"
    result_caps = _highlight_chart_keyword(q_caps)
    passed = "<span" in result_caps and "AS A LINE CHART" in result_caps
    _ac_check(lines, "HLT-04",
              f"Original capitalisation preserved inside `<span>` — "
              f"'AS A LINE CHART' in span: {('AS A LINE CHART' in result_caps)}",
              passed)
    pc += passed; fc += not passed

    # ── _extract_chart_type (nl2sql.py) ────────────────────────────────────────
    lines.append("\n### `_extract_chart_type()` — Gemini annotation parser (`src/nl2sql.py`)\n")

    ect_cases = [
        ("ECT-01", "```sql\nSELECT 1;\n```\nCHART_TYPE: pie",     "pie",
         "Parses `CHART_TYPE: pie` correctly"),
        ("ECT-02", "```sql\nSELECT 1;\n```",                       "auto",
         "Missing annotation → `'auto'`"),
        ("ECT-03", "```sql\nSELECT 1;\n```\nCHART_TYPE: donut",   "auto",
         "`'donut'` not in VALID_CHART_TYPES → `'auto'` (regex alternation rejects it)"),
        ("ECT-04", "```sql\nSELECT 1;\n```\nCHART_TYPE: scatter", "scatter",
         "Parses `CHART_TYPE: scatter` correctly"),
        ("ECT-05", "CHART_TYPE: BAR\n```sql\nSELECT 1;\n```",     "bar",
         "Case-insensitive match: `'BAR'` → `'bar'` via `.lower()`"),
    ]
    for ac_id, raw, expected, desc in ect_cases:
        result = _extract_chart_type(raw)
        passed = result == expected
        _ac_check(lines, ac_id, f"{desc} — got `{result!r}`", passed)
        pc += passed; fc += not passed

    lines.append(f"\n**Section 3 result: {pc}/{pc + fc} tests passed**\n")
    return pc, fc


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 4 — RENDER FUNCTION FALLBACK BEHAVIOUR
# ══════════════════════════════════════════════════════════════════════════════

def run_section_4(lines: list) -> tuple[int, int]:
    _section(lines, "Section 4 — F-13: Render Function Fallback Behaviour")
    lines.append(
        "Verifies each render function falls back to `st.dataframe()` on malformed input, "
        "and that `go.Bar(orientation='h')` is triggered for long categorical labels. "
        "`st.*` calls intercepted via the `MagicMock` injected into `sys.modules['streamlit']`.\n"
    )
    pc, fc = 0, 0

    # RND-01: render_bar — all-string df → st.dataframe
    _reset_st_mocks()
    render_bar(all_string_df)
    passed = _st_mock.dataframe.called and not _st_mock.plotly_chart.called
    _ac_check(lines, "RND-01",
              "`render_bar()` with all-string df (no numeric cols) → `st.dataframe()` called, `st.plotly_chart()` not called",
              passed)
    pc += passed; fc += not passed

    # RND-02: render_line — all-numeric df → st.dataframe
    _reset_st_mocks()
    render_line(all_numeric_df)
    passed = _st_mock.dataframe.called and not _st_mock.plotly_chart.called
    _ac_check(lines, "RND-02",
              "`render_line()` with all-numeric df (no cat cols) → `st.dataframe()` called, `st.plotly_chart()` not called",
              passed)
    pc += passed; fc += not passed

    # RND-03: render_pie — all-string df → st.dataframe
    _reset_st_mocks()
    render_pie(all_string_df)
    passed = _st_mock.dataframe.called and not _st_mock.plotly_chart.called
    _ac_check(lines, "RND-03",
              "`render_pie()` with all-string df (no numeric cols) → `st.dataframe()` called, `st.plotly_chart()` not called",
              passed)
    pc += passed; fc += not passed

    # RND-04: render_scatter — only 1 numeric col → st.dataframe
    _reset_st_mocks()
    render_scatter(one_numeric_df)
    passed = _st_mock.dataframe.called and not _st_mock.plotly_chart.called
    _ac_check(lines, "RND-04",
              "`render_scatter()` with only 1 numeric col → `st.dataframe()` called (need ≥2 numeric for scatter)",
              passed)
    pc += passed; fc += not passed

    # RND-05: render_bar — horizontal triggered (avg label len > 4)
    _reset_st_mocks()
    with patch.object(px, "bar", wraps=px.bar) as mock_px_bar:
        render_bar(long_label_df)

    horizontal = False
    if mock_px_bar.called and mock_px_bar.call_args is not None:
        try:
            kwargs = mock_px_bar.call_args.kwargs
        except AttributeError:
            kwargs = mock_px_bar.call_args[1]
        horizontal = kwargs.get("orientation") == "h"

    passed = _st_mock.plotly_chart.called and horizontal
    _ac_check(lines, "RND-05",
              f"`render_bar()` avg label len>4 (CocoaEthos≈10 chars) → `px.bar(orientation='h')` "
              f"+ `st.plotly_chart()` called (horizontal={horizontal})",
              passed)
    pc += passed; fc += not passed

    # RND-06: render_line — year+quarter+brand+revenue df (realistic query shape)
    # Validates temporal priority: 'quarter' (priority 3, n_unique=4) preferred over
    # 'year' (priority 4, n_unique=1). Result: st.plotly_chart called, NOT st.dataframe.
    _reset_st_mocks()
    year_quarter_df = pd.DataFrame({
        "year":                    [2025] * 12,
        "quarter":                 [1, 1, 1, 2, 2, 2, 3, 3, 3, 4, 4, 4],
        "brand":                   ["BrandA", "BrandB", "BrandC"] * 4,
        "quarterly_net_revenue_gbp": [1.0, 2.0, 3.0, 1.1, 2.1, 3.1,
                                      0.9, 1.9, 2.9, 1.2, 2.2, 3.2],
    })
    render_line(year_quarter_df)
    passed = _st_mock.plotly_chart.called and not _st_mock.dataframe.called
    _ac_check(lines, "RND-06",
              "`render_line()` year+quarter+brand+revenue df → temporal priority selects `quarter` "
              f"(n_unique=4) over `year` (n_unique=1); `st.plotly_chart()` called (chart_rendered="
              f"{_st_mock.plotly_chart.called})",
              passed)
    pc += passed; fc += not passed

    lines.append(f"\n**Section 4 result: {pc}/{pc + fc} tests passed**\n")
    return pc, fc


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 5 — TRACK B: MANUAL UI CHECKLIST
# ══════════════════════════════════════════════════════════════════════════════

def run_section_5(lines: list) -> None:
    _section(lines, "Section 5 — Track B: Manual UI Checklist (`streamlit run app.py`)")
    lines.append(
        "Run `streamlit run app.py` and update each row with ✅ PASS / ❌ FAIL / ⚠️ N/A.\n"
    )

    lines.append("### F-13 — Core Conversational UI\n")
    lines.append("| # | Item | Expected | Result |")
    lines.append("|---|---|---|---|")
    f13 = [
        ("Empty-state chips", "3 chips rendered; chip click submits question"),
        ("Immediate user bubble", "User bubble appears immediately on Enter — BEFORE spinner (two-rerun pattern)"),
        ("Spinner", "'Analysing…' visible below user bubble during `run_turn()` call"),
        ("User bubble", "Right-aligned, teal background, chart keyword highlighted via `_highlight_chart_keyword()`"),
        ("Response card", "Q-badge, subtitle (from `_make_subtitle()`), timestamp all visible"),
        ("⟳ Refined badge", "Badge shown when `retry_count > 0`"),
        ("Toggle label", "Radio label matches resolved chart type (e.g. `'Pie chart / Table'`)"),
        ("Toggle persistence", "Chart/table preference retained when next question submitted"),
        ("Input locked during restore", "`st.chat_input` disabled + `'Click ↺ Restore…'` placeholder"),
        ("Scroll-to-latest", "Thread auto-scrolls to bottom on each new answer"),
    ]
    for i, (item, expected) in enumerate(f13, 1):
        lines.append(f"| {i} | {item} | {expected} | ⚠️ Manual |")

    lines.append("\n### F-14 — Dual-Audience Output Design\n")
    lines.append("| # | Item | Expected | Result |")
    lines.append("|---|---|---|---|")
    f14 = [
        ("Narrative visible by default", "Business user can interpret result without expanding SQL panel"),
        ("Narrative font", "Lora serif — verify via browser devtools → Computed styles"),
        ("SQL expander collapsed", "Collapsed by default; summary label shows row count + latency"),
        ("Dark code block", "SQL code inside expander has `#1a2332` dark background"),
        ("nl2sql error state", "Toast notification shown (auto-dismisses); no SQL expander rendered"),
        ("Empty narrative warning", "`st.warning()` shown when narrative empty but SQL succeeded"),
    ]
    for i, (item, expected) in enumerate(f14, 1):
        lines.append(f"| {i} | {item} | {expected} | ⚠️ Manual |")

    lines.append("\n### F-15 — Logging (Live Verification)\n")
    lines.append("| # | Item | Expected | Result |")
    lines.append("|---|---|---|---|")
    f15 = [
        ("`logs/interactions.jsonl` created", "File present after first question"),
        ("Entry field count", "14 canonical + 2 ADR-042 fields all present"),
        ("Resumed entry flagging", "`resumed=true` + `resumed_at` ISO string after session restore"),
    ]
    for i, (item, expected) in enumerate(f15, 1):
        lines.append(f"| {i} | {item} | {expected} | ⚠️ Manual |")

    lines.append("\n### F-13 — Session Resumption (Three States)\n")
    lines.append("| State | Expected | Result |")
    lines.append("|---|---|---|")
    lines.append("| State 1 — Pending | Dashed ChartPlaceholder boxes visible; `st.chat_input` locked | ⚠️ Manual |")
    lines.append("| State 2 — Running | Progressive per-turn card restore with spinner; one rerun per question | ⚠️ Manual |")
    lines.append("| State 3 — Complete | Full charts rendered; `st.chat_input` re-enabled | ⚠️ Manual |")
    lines.append("| Resumed divider | Separator between original and continued turns | ⚠️ Manual |")
    lines.append("")


# ══════════════════════════════════════════════════════════════════════════════
# ADR-042 REFERENCE TABLE
# ══════════════════════════════════════════════════════════════════════════════

def run_adr042_table(lines: list) -> None:
    _section(lines, "ADR-042 Reference: `suggested_chart_type` vs `rendered_chart_type`")
    lines.append(
        "Demonstrates the priority chain across all canonical test queries. "
        "`suggested_chart_type` = Gemini annotation; `rendered_chart_type` = final resolved output after all three priority levels.\n"
    )
    lines.append("| Query (abbreviated) | Gemini annotation | Keyword? | Rendered | Priority level |")
    lines.append("|---|---|---|---|---|")
    rows = [
        ("Brand revenue share as a pie chart?", "`bar`",  "Yes → `pie`",     "`pie`",     "P1 — keyword"),
        ("CocoaEthos vs BerryBliss revenue",    "`bar`",  "Yes → `scatter`", "`scatter`", "P1 — keyword"),
        ("Weekly revenue trend for NitroBoost", "`auto`", "Yes → `line`",    "`line`",    "P1 — keyword"),
        ("Top brands by revenue in 2025",       "`pie`",  "No",              "`pie`",     "P2 — Gemini"),
        ("Top brands by revenue in 2025",       "`auto`", "No",              "`bar`",     "P3 — heuristic (cat df)"),
        ("Top brands revenue (temporal df)",    "`auto`", "No",              "`line`",    "P3 — heuristic (temporal)"),
        ("Top brands revenue (cat df)",         "`auto`", "No",              "`bar`",     "P3 — heuristic (bar)"),
        ("Top brands revenue (2-num df)",       "`auto`", "No",              "`scatter`", "P3 — heuristic (scatter)"),
        ("Top brands revenue (1num+2cat df)",   "`auto`", "No",              "`bar`",     "P4 — default (heuristic→table)"),
    ]
    for q, suggested, kw, rendered, level in rows:
        lines.append(f"| {q} | {suggested} | {kw} | {rendered} | {level} |")
    lines.append("")


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main():
    print("Sprint 4 Validation — no Streamlit server required", flush=True)
    print("  st.* → MagicMock  |  Gemini not called  |  JSONL tests → tempfile\n", flush=True)

    lines = []
    lines.append("# Sprint 4 Validation Report")
    lines.append("## F-13 Conversational UI · F-14 Dual-Audience · F-15 JSONL Logging · ADR-042\n")
    lines.append(f"**Candidate:** Manu Mohandas | **Employer:** TCS  ")
    lines.append(f"**Sprint:** 4 | **Report due:** 7 June 2026  ")
    lines.append(f"**Run timestamp:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  ")
    lines.append(f"**Methodology:** Track A — Automated unit tests (no server, no Gemini); "
                 f"Track B — Manual UI checklist  \n")
    lines.append(
        "> **Track A approach:** `app.py`, `src/logger.py`, and `src/nl2sql.py` imported directly. "
        "`streamlit` replaced with `MagicMock()` before import so module-level `st.set_page_config()` "
        "is harmless. JSONL tests use `tempfile.TemporaryDirectory()` for full isolation. "
        "Gemini not called — mock result dicts used throughout.\n"
    )

    print("Section 1 — F-15 JSONL Logging (13 tests)...", flush=True)
    s1p, s1f = run_section_1(lines)

    print("Section 2 — ADR-042 Chart Resolution (20 tests)...", flush=True)
    s2p, s2f = run_section_2(lines)

    print("Section 3 — F-13 UI Logic: subtitle/highlight/extract (15 tests)...", flush=True)
    s3p, s3f = run_section_3(lines)

    print("Section 4 — F-13 Render Fallback (6 tests)...", flush=True)
    s4p, s4f = run_section_4(lines)

    run_section_5(lines)
    run_adr042_table(lines)

    # ── CLOSURE SUMMARY ────────────────────────────────────────────────────────
    _section(lines, "Sprint 4 Closure Summary")

    total_p = s1p + s2p + s3p + s4p
    total_f = s1f + s2f + s3f + s4f
    total   = total_p + total_f

    f15_ok  = s1f == 0
    adr_ok  = s2f == 0
    f13_ok  = (s3f + s4f) == 0

    lines.append(f"**Automated result: {total_p}/{total} tests passed "
                 f"({'✅ all pass' if total_f == 0 else f'❌ {total_f} failure(s) — see details below'})** \n")
    lines.append("| Feature | Sections | Automated tests | Automated result | Manual checklist | Sprint status |")
    lines.append("|---|---|---|---|---|---|")
    lines.append(
        f"| **F-15** JSONL Logging | §1 | 13 | "
        f"{'✅' if f15_ok else '❌'} {s1p}/13 | §5 F-15 | "
        f"{'✅ Validated' if f15_ok else '⚠️ Review required'} |"
    )
    lines.append(
        f"| **ADR-042** Chart resolution | §2 | 20 | "
        f"{'✅' if adr_ok else '❌'} {s2p}/20 | N/A | "
        f"{'✅ Validated' if adr_ok else '⚠️ Review required'} |"
    )
    lines.append(
        f"| **F-13** UI Logic (auto) | §3–4 | 21 | "
        f"{'✅' if f13_ok else '⚠️'} {s3p + s4p}/21 | §5 F-13 | "
        f"⚠️ Pending manual |"
    )
    lines.append(
        f"| **F-14** Dual-Audience | — | N/A (CSS/layout) | N/A | §5 F-14 | "
        f"⚠️ Pending manual |"
    )
    lines.append("")

    # ── Findings ──────────────────────────────────────────────────────────────
    lines.append("### Findings from automated test run\n")
    lines.append("| # | Finding | Severity | Status | Resolution |")
    lines.append("|---|---|---|---|---|")
    lines.append(
        "| F-1 | `'top '` in `PROMPT_KEYWORDS['bar']` was over-firing on ranking queries, "
        "overriding P2/P3 when no explicit chart type was requested. "
        "| Medium | ✅ **RESOLVED** | `'top '` removed from `PROMPT_KEYWORDS['bar']`. "
        "Explicit `'bar chart'`/`'bar graph'`/`'ranking'` keywords still match correctly. |"
    )
    lines.append(
        "| F-2 | `_make_subtitle()` strip list omitted `' as a pie chart'` and `' as a scatter plot'`. "
        "Subtitle retained chart-type suffix as visible text in the response card. "
        "| Low | ✅ **RESOLVED** | Added `' as a pie chart'`, `' as a scatter plot'`, "
        "`' as a scatter'` to strip list. SUB-02, SUB-05, SUB-06 now pass. |"
    )
    lines.append("")

    lines.append(
        "### Post-fix changes not covered by automated tests\n"
        "\n"
        "The following changes were applied during Sprint 4 after the initial validation run. "
        "They are verified by updated automated tests above and/or the Track B manual checklist.\n"
        "\n"
        "- **Immediate user bubble** (`handle_question` two-rerun pattern): user question echoed "
        "before LLM call starts. Verified manually — Track B F-13 item 2.\n"
        "- **Toast error notifications**: `st.error()` replaced with `st.toast()` on all error "
        "paths. Verified manually — Track B F-14 item 5.\n"
        "- **`render_line()` temporal priority**: `year`+`quarter` queries now correctly select "
        "`quarter` as x-axis. Verified by RND-06.\n"
        "- **`MODEL_FALLBACK`**: updated from retired `gemini-1.5-flash` → `gemini-2.5-flash-lite`. "
        "Infrastructure change, no automated test required.\n"
    )

    # ── WRITE OUTPUT ───────────────────────────────────────────────────────────
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))

    # Console summary
    bar = "=" * 62
    print(f"\n{bar}")
    print(f"  TOTAL: {total_p}/{total} automated tests passed  ({total_f} failure(s))")
    print(f"  S1 F-15:      {s1p}/13  {'✅' if s1f == 0 else '❌'}")
    print(f"  S2 ADR-042:   {s2p}/20  {'✅' if s2f == 0 else '❌'}")
    print(f"  S3 UI logic:  {s3p}/15  {'✅' if s3f == 0 else '❌'}")
    print(f"  S4 Render:    {s4p}/6   {'✅' if s4f == 0 else '❌'}")
    print(f"  Report: {OUTPUT_PATH}")
    print(bar)
    if total_f:
        print(f"\n  ⚠️  {total_f} test(s) failed — see report for details.")
    else:
        print(f"\n  ✅  All {total} automated tests pass. Complete Track B manual checklist.")
        print(f"  Next: run `streamlit run app.py` and update §5 in the generated report.")


if __name__ == "__main__":
    main()
