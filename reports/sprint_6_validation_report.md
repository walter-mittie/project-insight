# Sprint 6 Validation Report
## Project Insight : Agentic Conversational BI
### F-19 Edge Case Hardening · F-20 Evidence Capture · ADR-044 · FP-07

**Run by:** Manu Mohandas 
**Sprint:** 6
**Run timestamp:** 2026-02-14 07:55:19  
**Methodology:** Track A — Automated regression (54/54 test suite); Track B — Manual app verification; Track C — Evidence artefact checklist

> **Track A approach:** Sprint 6 introduces no new test-covered features. The Sprint 4 automated suite (`tests/sprint4_validation.py`) is the regression gate. All Sprint 6 code fixes must pass 54/54 before evidence capture begins.
> **Track B approach:** `streamlit run app.py` — manual verification of deprecation fixes and edge case behaviour.
> **Track C approach:** Evidence artefact checklist confirming all F-20 capture items are complete and traceable.

---

## Section 1 — Pre-Sprint Regression Gate

Run before any Sprint 6 code changes to confirm baseline:

```bash
python tests/sprint4_validation.py
```

- ✅ **PRE-01**: Sprint 4 automated suite — 54/54 PASS at Sprint 6 start (RND-05 fixed: `px.bar` assertion corrected from `go.Bar`) ✓

> **RND-05 fix note:** The pre-existing failure (53/54) was a test mock gap — the test asserted `go.Bar(orientation='h')` but the simple bar path calls `px.bar(orientation='h')`. The fix updated the assertion to patch `px.bar` with `wraps=px.bar`, which correctly captures the `orientation='h'` kwarg while still allowing the real figure to be created. This is a test infrastructure correction, not a code change.

**Section 1 result: 1/1 gate passed**

---

## Section 2 — F-19: Edge Case Hardening

### Fix A — `render_bar()` deprecated `use_container_width` (app.py)

- ✅ **F19-A-01**: `st.plotly_chart(fig, use_container_width=True)` in `render_bar()` replaced with `st.plotly_chart(fig, width='stretch')` ✓
- ✅ **F19-A-02**: Verification: `grep -n "use_container_width" app.py | grep -v "st.button"` — returns empty (all remaining instances are multi-line `st.button` calls, not deprecated) ✓

### Fix B — `components.html` scroll helper (app.py)

- ✅ **F19-B-01**: `components.html(...)` scroll-to-latest helper (5 lines) removed from `handle_question()` ✓
- ✅ **F19-B-02**: `import streamlit.components.v1 as components` (line 25) removed — no remaining `components.*` calls ✓
- ✅ **F19-B-03**: Verification: `grep -n "components\." app.py` — returns empty ✓

### Fix C — DuckDB timeout wrapper (`src/executor.py`)

- ✅ **F19-C-01**: `import concurrent.futures` added to `executor.py` imports ✓
- ✅ **F19-C-02**: `QUERY_TIMEOUT_SECONDS = 30` constant added at module level ✓
- ✅ **F19-C-03**: `_run_query(conn, sql)` inner function added ✓
- ✅ **F19-C-04**: `execute_with_timeout(conn, sql, timeout)` wrapper implemented using `ThreadPoolExecutor(max_workers=1)` with `future.result(timeout=timeout)` — raises `TimeoutError` on expiry ✓
- ✅ **F19-C-05**: `execute_sql()` updated to call `execute_with_timeout(conn, sql)` in place of `conn.execute(sql).df()` ✓
- ✅ **F19-C-06**: `TimeoutError` is subclass of `Exception` — caught by existing `except Exception as exc:` block in `execute_sql()`. Returns `{"status": "error", "error_type": "TimeoutError", ...}` without raising. No changes needed to `agent.py` or `app.py` ✓
- ✅ **F19-C-07**: Verification: `grep -n "execute_with_timeout\|QUERY_TIMEOUT_SECONDS\|concurrent.futures" src/executor.py` — returns 3 hits ✓

### AC1 — Empty result set guard (`app.py`)

- ✅ **F19-AC1-01**: `df.empty` guard added before chart dispatch in `_render_response_card()` — displays `st.info("No data found for this query — try broadening the filters or rephrasing.")` when `df` is empty ✓
- ✅ **F19-AC1-02**: Guard placed before the `render_type` dispatch block — no chart rendered, no blank panel shown ✓

### AC2 — Malformed LLM output (pre-validated)

- ✅ **F19-AC2-01**: SQL delimiter missing path handled by Sprint 3 retry loop and `error_stage='nl2sql'` classification — pre-validated in `tests/test_agent.py`. Live verification: "What was the out-of-stock rate and lost sales value by region in Q4 2025?" triggered `no_sql_delimiter` error correctly, logged `error_stage: nl2sql`, `retry_count: 0` ✓

### AC4 — Conversation history pruning (pre-validated)

- ✅ **F19-AC4-01**: `MAX_HISTORY_TURNS` pruning with `history_truncated: True` flag — fully implemented in F-11 (Sprint 3). Confirmed in Sprint 3 closure notes. Pre-validated ✓

### Documentation updates

- ✅ **F19-DOC-01**: ADR-044 added to `docs/decision_log.md` — `MODEL_FALLBACK = "gemini-2.5-pro"` decision documented with context (free-tier 20 RPD constraint encountered in Sprint 5), rationale, alternatives considered, and KSB mapping (K13, S15) ✓
- ✅ **F19-DOC-02**: FP-07 added to `docs/prompt_log.md` — flag over-application pattern documented with root cause analysis and v1.3 remediation proposal. Status: Logged. Not fixed in v1.2 (evaluation prompt frozen) ✓

**Section 2 result: 19/19 checks passed**

---

## Section 3 — Sprint 6 Regression Gate (Post-Fix)

Run after all F-19 changes applied:

```bash
python tests/sprint4_validation.py
```

- ✅ **POST-01**: 54/54 PASS after all Sprint 6 code changes — no regression introduced ✓
  - S1 F-15 JSONL Logging: 13/13 ✅
  - S2 ADR-042 Chart Resolution: 20/20 ✅
  - S3 UI Logic: 15/15 ✅
  - S4 Render Fallback: 6/6 ✅ (including RND-05 fix)

**Section 3 result: 1/1 gate passed**

---

## Section 4 — App Startup Verification (Track B)

```bash
streamlit run app.py
```

- ✅ **APP-01**: App starts cleanly — no deprecation warnings in terminal output ✓
- ✅ **APP-02**: No `StreamlitDeprecationWarning` for `use_container_width` ✓
- ✅ **APP-03**: No `StreamlitDeprecationWarning` for `components.html` ✓
- ✅ **APP-04**: Local URL accessible — `http://localhost:8501` responds ✓

**Section 4 result: 4/4 checks passed**

---

## Section 5 — F-20: Evidence Capture Checklist (Track C)

All evidence captured after F-19 completion gate (54/54 tests, clean terminal).

### Screenshots

| # | Label | Content | Status |
|---|---|---|---|
| 1 | `ss_01_ui_overview` | Empty state — 3 example chips visible, no conversation | ✅ Captured |
| 2 | `ss_02_business_output` | "Top 10 SKUs by net revenue 2025 as a bar chart" — completed card with narrative + bar chart | ✅ Captured |
| 3 | `ss_03_chart_keyword_pie` | "Revenue mix by category 2025 as a pie chart" — pie chart rendered | ✅ Captured |
| 4 | `ss_04_sql_expander` | SQL expander open — SQL text, latency ms, retry count, turn ID visible simultaneously | ✅ Captured |
| 5 | `ss_05_jsonl_log` | `logs/interactions.jsonl` single entry — all 16 fields visible | ✅ Captured |
| 6 | `ss_06_eval_results` | `docs/sprint_5_evaluation_report.md` correctness rates table — baseline 70% vs treatment 95% | ✅ Captured |
| 7 | `ss_07_retry_badge` | `logs/benchmark_results.jsonl` grep output — 4 baseline entries with `retry_count: 1` (Q06, Q08, Q09, Q12) | ✅ Captured |
| 8 | `ss_08_session_restore` | Past session loaded — State 1: dashed ChartPlaceholder boxes, locked input visible | ✅ Captured |

> **Note on ss_07:** The treatment condition produced 0 retries during live session (the semantic schema injection is effective enough that no self-correction was needed). Evidence is sourced from `logs/benchmark_results.jsonl` baseline entries, where 4 prompts triggered `retry_count = 1` and all resolved successfully (`success_flag: true`). This is the canonical evidence for the agentic self-correction mechanism — the ⟳ Refined badge renders in the UI for any live turn where `retry_count > 0`.

> **Note on screen recording:** A screen recording was not produced. The submission portal accepts Word + PowerPoint only. All recording requirements are covered by the 8 screenshots, which are static, citable, and can be embedded directly in the Word report with captions.

**Section 5 result: 8/8 captures complete**

---

## Section 6 — F-20: JSONL Log Summary Statistics

### Live session log (`logs/interactions.jsonl`)

Extracted via Python at Sprint 6 close:

| Metric | Value |
|---|---|
| Total turns logged | 7 |
| Successful turns (`success_flag = True`) | 6 |
| Sessions | 1 |
| Charts generated (`rendered_chart_type` not in `none`, `benchmark`, `null`) | 6 |

### Benchmark log (`logs/benchmark_results.jsonl`)

| Metric | Value |
|---|---|
| Total benchmark turns | 40 |
| Successful executions | 39/40 |
| Sessions | `benchmark_baseline`, `benchmark_treatment` |
| Total retries | 4 |
| Baseline retries | 4 (Q06, Q08, Q09, Q12) |
| Treatment retries | 0 |
| Baseline correctness | 14/20 = 70.0% |
| Treatment correctness | 19/20 = 95.0% |

### Chart type match rate (AC5 formal metric — `logs/interactions.jsonl`)

| Metric | Value | Notes |
|---|---|---|
| Match rate (all turns) | 71.4% (5/7) | Includes 1 error turn where `rendered_chart_type = 'none'` |
| Match rate (successful turns only) | 83.3% (5/6) | Recommended primary metric |
| Single mismatch on successful turns | Turn 2 — "Compare the numbers for last year": Gemini annotated `pie`, rendered as `bar` | P1 keyword `'compare'` override — ADR-042 working as designed |
| Error turn mismatch | Turn 5 — `error_stage: nl2sql`: `suggested = auto`, `rendered = none` | Expected behaviour on failed generation |

- ✅ **AC5-01**: Chart type match rate computed and documented — 83.3% on successful turns ✓
- ✅ **AC5-02**: Single mismatch attributable to intentional P1 keyword override (ADR-042 design), not system error ✓

**Section 6 result: All metrics extracted and documented**

---

## Section 7 — Sprint 6 Closure Summary

**All checks passed: 33/33 (0 failures)**

| Area | Checks | Result |
|---|---|---|
| Pre-sprint regression gate | 1 | ✅ 1/1 |
| F-19 edge case hardening | 19 | ✅ 19/19 |
| Post-fix regression gate | 1 | ✅ 1/1 |
| App startup verification | 4 | ✅ 4/4 |
| F-20 evidence capture | 8 | ✅ 8/8 |

### Sprint 6 code changes summary

| Fix | File | Change |
|---|---|---|
| Fix A | `app.py` | `use_container_width=True` → `width='stretch'` in `render_bar()` |
| Fix B | `app.py` | Removed `components.html` scroll helper (5 lines) |
| Fix B | `app.py` | Removed `import streamlit.components.v1 as components` (line 25) |
| Fix C | `src/executor.py` | Added `concurrent.futures` import, `QUERY_TIMEOUT_SECONDS = 30`, `_run_query()`, `execute_with_timeout()`, updated `execute_sql()` |
| AC1 | `app.py` | Added `df.empty` guard before chart dispatch in `_render_response_card()` |
| RND-05 | `tests/sprint4_validation.py` | Fixed test mock: `go.Bar` assertion → `px.bar` assertion for horizontal bar detection |
| ADR-044 | `docs/decision_log.md` | Added ADR-044 — `MODEL_FALLBACK = "gemini-2.5-pro"` |
| FP-07 | `docs/prompt_log.md` | Added FP-07 — flag over-application pattern (logged, not fixed in v1.2) |

### Final project state

| Sprint | Features | Status |
|---|---|---|
| S1 — Foundation | F-01 to F-05 | ✅ Validated |
| S2 — NL2SQL Core | F-06 to F-09 | ✅ Validated |
| S3 — Agentic Loop | F-10 to F-12 | ✅ Validated |
| S4 — Streamlit UI + Logging | F-13, F-14, F-15 | ✅ Validated — 54/54 tests |
| S5 — Evaluation + Hypothesis Testing | F-16, F-17, F-18 | ✅ Validated |
| S6 — Hardening + Evidence Capture | F-19, F-20 | ✅ Validated |

**All 20 features (F-01 through F-20) validated. Project build complete.**

### Report readiness checklist

- ✅ 54/54 automated tests passing
- ✅ Clean Streamlit startup (no deprecation warnings)
- ✅ 8 evidence screenshots captured
- ✅ All JSONL log statistics extracted and locked
- ✅ AC5 chart type match rate computed (83.3% on successful turns)
- ✅ ADR-044 and FP-07 documented
- ✅ Sprint 4 Track B manual checklist updated to ✅ PASS
- ✅ Employer verification statement requested
- ✅ Report handover prompt generated (v2, BCS gaps resolved)

**Sprint 6 validated: 12 February 2026 · Project Insight · AM1 · Manu Mohandas**

---

## Appendix — Locked Evidence Numbers (Sprint 6 close state)

The following figures are confirmed from validated artefacts and must be used unchanged in the AM1 report.

| Fact | Value | Source |
|---|---|---|
| Baseline correctness | 14/20 = 70.0% | `docs/experiment_results.csv` |
| Treatment correctness | 19/20 = 95.0% | `docs/experiment_results.csv` |
| McNemar p-value (one-tailed) | 0.0625 | `docs/sprint_5_evaluation_report.md` |
| Discordant pairs | 7 (b1t0=1, b0t1=6) | `docs/sprint_5_evaluation_report.md` |
| Baseline retries | 4 | `logs/benchmark_results.jsonl` |
| Treatment retries | 0 | `logs/benchmark_results.jsonl` |
| Baseline mean exec time | 43.8ms | `docs/sprint_5_evaluation_report.md` |
| Treatment mean exec time | 37.0ms | `docs/sprint_5_evaluation_report.md` |
| Treatment p50 | 38.0ms | `docs/sprint_5_evaluation_report.md` |
| Treatment p95 | 72.1ms | `docs/sprint_5_evaluation_report.md` |
| Automated tests | 54/54 | `tests/sprint4_validation.py` |
| Sprint 2 correctness (v1.1) | 10/14 = 71.4% | `docs/sprint_2_validation_report.md` |
| ADR count | 44 (ADR-001 to ADR-044) | `docs/decision_log.md` |
| Chart type match rate (live) | 83.3% on successful turns (5/6) | `logs/interactions.jsonl` |
| Statistical power at n=20 | ~34% | `docs/sprint_5_evaluation_report.md` |
| Prompts for 87% power | ~40 | `docs/sprint_5_evaluation_report.md` |

---

*Sprint 6 validated: 12 February 2026 · Project Insight · AM1 · Manu Mohandas*
