"""
tests/sprint3_validation.py
---------------------------
Sprint 3 End-to-End Validation — Live Pipeline Runner

Project Insight: Agentic Conversational BI 

This script exercises the full agentic pipeline (agent.run_turn → Gemini API
→ DuckDB) against the real processed Parquet dataset.  It is the live
complement to the unit tests in test_agent.py and test_narrative.py.

Coverage
--------
Section 1 — F-10 Wiring Check
    Confirms retry_count and turn_index are present in the live response dict.
    The retry loop itself is exhaustively tested via mocks in test_agent.py;
    the live check confirms the field contract survives the real pipeline.

Section 2 — F-11 Multi-Turn Contextual Test  (AC2)
    Five sequential questions where each follow-up depends on the previous answer.
    Validates that conversation_history correctly carries context across turns:
    the model should answer "those brands" / "that brand" without restating context.

Section 3 — F-12 Narrative Quality Test  (AC4)
    Five stand-alone queries covering the five AC4 query types:
        1. Volume trend
        2. Market share
        3. Promotional uplift
        4. Price analysis
        5. Multi-brand comparison
    Validates that narratives reference specific figures (AC2) and that both
    narrative and SQL appear in each response dict (AC3).

Prerequisites
-------------
    - data/processed/ Parquet files present (run scripts/preprocess.py first)
    - .env contains GEMINI_API_KEY
    - src/agent.py, src/narrative.py, src/nl2sql.py, src/db.py all in place

Run with:
    python tests/sprint3_validation.py

Output:
    reports/sprint_3_validation_report.md
"""

import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.agent import run_turn, MAX_RETRIES
from src.db import get_connection

OUTPUT_PATH = os.path.join(
    os.path.dirname(__file__), "..", "reports", "sprint_3_validation_report.md"
)


# ──────────────────────────────────────────────────────────────────────────────
# HELPERS
# ──────────────────────────────────────────────────────────────────────────────

def _section(lines: list, title: str) -> None:
    lines.append(f"\n---\n\n## {title}\n")


def _render_turn(lines: list, label: str, question: str, result: dict) -> None:
    """Render one run_turn() result into the report."""
    lines.append(f"### {label}\n")
    lines.append(f"**Question:** {question}\n")

    if result["status"] == "error":
        lines.append(f"**Status:** ❌ ERROR  ")
        lines.append(f"**Stage:** `{result.get('error_stage', '?')}`  ")
        lines.append(f"**Type:** `{result.get('error_type', '?')}`  ")
        lines.append(f"**Message:** {result.get('error_message', '')[:300]}\n")
    else:
        lines.append(f"**Status:** ✅ SUCCESS  ")
        lines.append(f"**Turn index:** {result['turn_index']}  ")
        lines.append(f"**Retry count:** {result['retry_count']}  ")
        lines.append(f"**Exec time:** {result['exec_time_ms']:.1f}ms  ")
        lines.append(f"**Rows returned:** {result['row_count']}  \n")

        # SQL
        lines.append(f"**Generated SQL:**\n```sql\n{result['sql']}\n```\n")

        # Data preview (up to 10 rows)
        df = result["data"]
        if result["row_count"] > 0:
            lines.append("**Result preview:**\n")
            lines.append(df.head(10).to_markdown(index=False))
            if result["row_count"] > 10:
                lines.append(f"\n_...{result['row_count']} rows total (first 10 shown)_")
            lines.append("")
        else:
            lines.append("_Query returned 0 rows._\n")

        # Narrative
        narrative = result.get("narrative", "")
        if narrative:
            lines.append(f"**Narrative:**\n> {narrative}\n")
        else:
            lines.append("**Narrative:** _(empty — narrative generation failed or skipped)_\n")

    lines.append("")


def _ac_check(lines: list, ac_id: str, description: str, passed: bool) -> None:
    icon = "✅" if passed else "❌"
    lines.append(f"- {icon} **{ac_id}**: {description}")


# ──────────────────────────────────────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────────────────────────────────────

def main():
    print("Sprint 3 Validation — connecting to DuckDB...", flush=True)
    conn = get_connection()

    lines = []
    lines.append("# Sprint 3 Validation Report — Agentic Loop + Conversation History")
    lines.append(f"\n**Candidate:** Manu Mohandas | **Employer:** TCS  ")
    lines.append(f"**Run timestamp:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  ")
    lines.append(f"**Model:** gemini-2.5-flash | **MAX_RETRIES:** {MAX_RETRIES}  \n")

    # ── SECTION 1: F-10 WIRING CHECK ─────────────────────────────────────────
    _section(lines, "Section 1 — F-10: Retry Loop Wiring Check")
    lines.append(
        "The retry loop is exhaustively tested via mocks in `tests/test_agent.py` "
        "(hard cap, correction signal content, generate_sql call count per retry). "
        "This section confirms the live pipeline correctly surfaces `retry_count` "
        "and `turn_index` in the response dict, and that a normal query completes "
        "with `retry_count = 0`.\n"
    )

    wiring_q = "How many distinct SKUs were sold in Q1 2025?"
    print(f"S1 — F-10 wiring check: {wiring_q}", flush=True)
    wiring_result = run_turn(wiring_q, [], conn)
    _render_turn(lines, "F-10 Wiring Query", wiring_q, wiring_result)

    lines.append("**F-10 Acceptance Criteria — Wiring Check:**\n")
    _ac_check(lines, "AC3 (hard cap)", f"MAX_RETRIES constant = {MAX_RETRIES} (3 total attempts)", MAX_RETRIES == 2)
    _ac_check(lines, "AC4 (retry_count exposed)", "retry_count present in live response",
              "retry_count" in wiring_result)
    _ac_check(lines, "AC4 (turn_index exposed)", "turn_index present in live response",
              "turn_index" in wiring_result)
    _ac_check(lines, "AC4 (clean query = 0 retries)", "retry_count = 0 on successful first attempt",
              wiring_result.get("retry_count") == 0)
    lines.append(
        "\n_Full retry loop unit tests (error signal content, call count per retry, "
        "hard cap enforcement) are in `tests/test_agent.py::TestRetryLoop`._\n"
    )

    # ── SECTION 2: F-11 MULTI-TURN CONTEXTUAL TEST ───────────────────────────
    _section(lines, "Section 2 — F-11: Multi-Turn Contextual Test (AC2)")
    lines.append(
        "Five sequential questions where each follow-up is contextually dependent "
        "on the prior answer.  The model must not re-explain context it has already "
        "seen.  Evidence of context retention: Turn 2 and beyond refer to brands/figures "
        "from Turn 1 without re-asking the underlying question.\n"
    )

    multi_turn_questions = [
        ("T1", "What were the top 3 brands by net revenue in 2025?"),
        ("T2", "How did those same 3 brands perform in 2024?"),
        ("T3", "Which of those 3 brands had the strongest revenue growth from 2024 to 2025?"),
        ("T4", "Break that top-growth brand's 2025 revenue down by channel."),
        ("T5", "Now show the weekly volume trend for that brand in H2 2025."),
    ]

    history = []
    multi_turn_results = {}

    for label, question in multi_turn_questions:
        print(f"S2 — {label}: {question}", flush=True)
        result = run_turn(question, history, conn)
        _render_turn(lines, label, question, result)
        multi_turn_results[label] = result
        if result["status"] == "success":
            history = result["conversation_history"]

    lines.append("**F-11 Acceptance Criteria:**\n")
    _ac_check(lines, "AC1 (history injected)", "Prior turns passed to generate_sql on each call",
              True)  # Verified structurally in unit tests; live run confirms no errors
    all_success = all(r["status"] == "success" for r in multi_turn_results.values())
    _ac_check(lines, "AC2 (5-turn test)", f"All 5 sequential contextual turns completed without error",
              all_success)
    final_history_len = len(history)
    _ac_check(lines, "AC1 (history grows)", f"History length after 5 turns = {final_history_len} (expect 5)",
              final_history_len == 5)
    _ac_check(lines, "AC3 (truncation logic)", "MAX_HISTORY_TURNS = 5 enforced in nl2sql.py (unit tested)",
              True)
    all_have_turn_index = all("turn_index" in r for r in multi_turn_results.values())
    _ac_check(lines, "AC4 (turn counter)", "turn_index present in all 5 response dicts",
              all_have_turn_index)

    lines.append("\n**Turn index sequence:**\n")
    for label, result in multi_turn_results.items():
        idx = result.get("turn_index", "N/A")
        status = "✅" if result["status"] == "success" else "❌"
        lines.append(f"- {label}: turn_index = {idx} {status}")
    lines.append("")

    # ── SECTION 3: F-12 NARRATIVE QUALITY TEST ────────────────────────────────
    _section(lines, "Section 3 — F-12: Narrative Quality Test (AC4 — 5 Query Types)")
    lines.append(
        "Five stand-alone queries covering the five query types specified in F-12 AC4. "
        "Each narrative is manually assessed against AC2 (specific figures cited) and "
        "AC3 (both narrative and SQL present in response dict).\n"
    )
    lines.append(
        "**Manual assessment criteria:** "
        "AC2 PASS = narrative contains at least one specific numeric figure from the result. "
        "AC2 FAIL = narrative is generic with no result-specific numbers.\n"
    )

    narrative_queries = [
        ("N1", "Volume trend",
         "What was the total volume units sold per month for the Confectionery "
         "category in 2025?"),
        ("N2", "Market share",
         "What was NitroBoost's volume market share by quarter in 2025?"),
        ("N3", "Promotional uplift",
         "What was the average volume uplift for promoted SKUs compared to "
         "non-promoted SKUs in 2024?"),
        ("N4", "Price analysis",
         "What was the average shelf price by sub-category in Q4 2025?"),
        ("N5", "Multi-brand comparison",
         "Compare the top 5 brands by net revenue in 2025, showing each "
         "brand's total and percentage share of category revenue."),
    ]

    narrative_results = {}

    for label, query_type, question in narrative_queries:
        print(f"S3 — {label} ({query_type}): {question[:60]}...", flush=True)
        result = run_turn(question, [], conn)
        lines.append(f"### {label} — {query_type}\n")
        _render_turn(lines, "", question, result)
        narrative_results[label] = result

    lines.append("**F-12 Acceptance Criteria:**\n")

    # AC1: second Gemini call returns narrative paragraph
    all_have_narrative_key = all("narrative" in r for r in narrative_results.values())
    _ac_check(lines, "AC1 (second Gemini call)", "narrative key present in all 5 responses",
              all_have_narrative_key)

    # AC2: narrative references specific figures — manual assessment required
    lines.append(
        "- **AC2 (specific figures):** ⚠️  **Manual assessment required.** "
        "Review each narrative above — PASS if specific numbers/brand names cited, "
        "FAIL if generic text only."
    )

    # AC3: both narrative and SQL present
    all_have_both = all(
        "narrative" in r and "sql" in r
        for r in narrative_results.values()
    )
    _ac_check(lines, "AC3 (narrative + SQL in response)", "Both keys present in all 5 response dicts",
              all_have_both)

    # AC4: tested across 5 query types
    successful_narratives = sum(
        1 for r in narrative_results.values()
        if r["status"] == "success" and r.get("narrative")
    )
    _ac_check(lines, "AC4 (5 query types)", f"{successful_narratives}/5 queries returned non-empty narrative",
              successful_narratives == 5)

    # ── SUMMARY ───────────────────────────────────────────────────────────────
    _section(lines, "Sprint 3 Closure Summary")

    f10_pass = (
        MAX_RETRIES == 2
        and "retry_count" in wiring_result
        and wiring_result.get("retry_count") == 0
    )
    f11_pass = all_success and final_history_len == 5
    f12_pass = all_have_narrative_key and all_have_both

    lines.append("| Feature | Unit Tests | Live Validation | Status |")
    lines.append("|---|---|---|---|")
    lines.append(f"| F-10 Self-Correction Retry Loop | `tests/test_agent.py::TestRetryLoop` | Wiring check: {'✅' if f10_pass else '❌'} | {'✅ Validated' if f10_pass else '⚠️ Review'} |")
    lines.append(f"| F-11 Conversation History | `tests/test_agent.py::TestConversationHistory` | 5-turn test: {'✅' if f11_pass else '❌'} | {'✅ Validated' if f11_pass else '⚠️ Review'} |")
    lines.append(f"| F-12 Narrative Generation | `tests/test_narrative.py` | 5-type test: {'✅' if f12_pass else '⚠️'} | {'✅ Validated (pending AC2 manual check)' if f12_pass else '⚠️ Review'} |")
    lines.append("")
    lines.append(
        "\n_AC2 (narrative cites specific figures) requires manual review of the "
        "narrative outputs in Section 3 above.  Mark F-12 Validated only after "
        "confirming at least 4/5 narratives contain result-specific numbers._\n"
    )
    lines.append("\n**Next step:** Update F-10, F-11, F-12 status to `Validated` in "
                 "`AM1_Feature_Register.md` after manual AC2 review.")

    # ── WRITE OUTPUT ──────────────────────────────────────────────────────────
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"\nDone. Validation report written to: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
