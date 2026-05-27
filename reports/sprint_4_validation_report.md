# Sprint 4 Validation Report
## Project Insight : Agentic Conversational BI
### F-13 Conversational UI · F-14 Dual-Audience · F-15 JSONL Logging · ADR-042

**Run by:** Manu Mohandas
**Sprint:** 4 
**Run timestamp:** 2026-02-04 20:38:13  
**Methodology:** Track A — Automated unit tests (no server, no Gemini); Track B — Manual UI checklist  

> **Track A approach:** `app.py`, `src/logger.py`, and `src/nl2sql.py` imported directly. `streamlit` replaced with `MagicMock()` before import so module-level `st.set_page_config()` is harmless. JSONL tests use `tempfile.TemporaryDirectory()` for full isolation. Gemini not called — mock result dicts used throughout.


---

## Section 1 — F-15: JSONL Logging Infrastructure

All tests use `tempfile.TemporaryDirectory()` for full isolation. `log_turn()` called directly against mock result dicts — no Gemini or DuckDB calls required.

- ✅ **F15-T01**: All 14 canonical JSONL fields present in written entry (missing: none)
- ✅ **F15-T02**: ADR-042 fields `suggested_chart_type` and `rendered_chart_type` present
- ✅ **F15-T03**: `raw_nl2sql` and `raw_narrative` absent from log entry (too large — ADR-041)
- ✅ **F15-T04**: Error turn: `success_flag=False`, `generated_sql=None`, `error_stage='execution'`
- ✅ **F15-T05**: Resumed turn: `resumed=True`, `resumed_at='2025-01-31T10:00:00Z'` preserved in entry
- ✅ **F15-T06**: `logs/` directory auto-created by `_ensure_log_dir()` on first write
- ✅ **F15-T07**: `LogWriteError` raised (non-crash) when file write fails — caller sees warning, not crash
- ✅ **F15-T08**: `load_past_sessions()` groups 3 entries (2 sessions) → got 2 group(s)
- ✅ **F15-T09**: `load_past_sessions()` newest-first: first=`sid-NEW` (expect `sid-NEW`)
- ✅ **F15-T10**: `read_turns_from_jsonl()` filters by session_id — got 2/3 entries (expect 2)
- ✅ **F15-T11**: `read_turns_from_jsonl()` excludes `resumed=True` entries — got 1/2 (expect 1)
- ✅ **F15-T12**: `read_turns_from_jsonl()` excludes `success_flag=False` entries — got 1/2 (expect 1)
- ✅ **F15-T13**: `read_turns_from_jsonl()` sorted by `turn_id` ascending — got [1, 2, 3]

**Section 1 result: 13/13 tests passed**


---

## Section 2 — ADR-042: Chart Type Resolution Priority Chain

Tests the three-level priority chain: **P1** prompt keyword → **P2** Gemini annotation → **P3** DataFrame heuristic → **P4** default `'bar'`. Synthetic DataFrames only — no Gemini calls.

### `_keyword_hint()` — Priority 1 keyword detection

- ✅ **KW-01**: Keyword 'share' → `'pie'` — got `'pie'`
- ✅ **KW-02**: Keyword 'vs ' → `'scatter'` — got `'scatter'`
- ✅ **KW-03**: Keyword 'weekly' → `'line'` — got `'line'`
- ✅ **KW-04**: Keyword 'compare' → `'bar'` — got `'bar'`
- ✅ **KW-05**: Keyword 'table' → `'table'` — got `'table'`
- ✅ **KW-06**: No keyword → `None` — got `None`

### `_heuristic()` — Priority 3 DataFrame shape rules

- ✅ **HEU-01**: ≥2 numeric + ≥1 cat → `'scatter'` — got `'scatter'`
- ✅ **HEU-02**: 1 numeric + 1 temporal cat (`'week'`) → `'line'` — got `'line'`
- ✅ **HEU-03**: 1 numeric + 1 non-temporal cat (`'brand'`) → `'bar'` — got `'bar'`
- ✅ **HEU-04**: Empty df → `'table'` — got `'table'`
- ✅ **HEU-05**: 1 numeric + 2 non-numeric — no rule fires → `'table'` — got `'table'`

### `resolve_chart_type()` — Full priority chain (ADR-042 canonical test cases)

- ✅ **RCT-01**: P1 keyword `'share'/'pie chart'` overrides Gemini `'bar'` ✓ — got `'pie'`
- ✅ **RCT-02**: P1 keyword `'vs '` overrides Gemini `'bar'` ✓ — got `'scatter'`
- ✅ **RCT-03**: P1 keyword `'weekly'` overrides heuristic ✓ — got `'line'`
- ✅ **RCT-04**: P2 Gemini `'pie'` wins when no keyword — `'top '` correctly absent from P1 keywords — got `'pie'`
- ✅ **RCT-05**: P3 heuristic `'bar'` wins (no keyword, Gemini=`'auto'`, cat df) — got `'bar'`
- ✅ **RCT-06**: P3 heuristic: no keyword, `'auto'`, temporal df → `'line'` — got `'line'`
- ✅ **RCT-07**: P3 heuristic: cat df → `'bar'` — got `'bar'`
- ✅ **RCT-08**: P3 heuristic: 2-num df → `'scatter'` — got `'scatter'`
- ✅ **RCT-09**: P4 default: heuristic→`'table'` → resolve→`'bar'` — got `'bar'`

**Section 2 result: 20/20 tests passed**


---

## Section 3 — F-13: UI Logic (Automated)

Tests `_make_subtitle()`, `_highlight_chart_keyword()`, and `_extract_chart_type()` by importing functions directly from `app.py` and `src/nl2sql.py` — no server required.

### `_make_subtitle()` — subtitle strip and truncation

- ✅ **SUB-01**: Strips `' as a line chart'` suffix — got `'2025 quarterly revenue growth'`
- ✅ **SUB-02**: Strips `' as a pie chart'` suffix — got `'Revenue share'`
- ✅ **SUB-03**: Strips `' as a bar chart'` suffix — got `'Top brands by revenue'`
- ✅ **SUB-05**: Strips `' as a scatter plot'` suffix (added in ADR-042) — got `'Top SKUs by margin'`
- ✅ **SUB-06**: Strips `' as a scatter'` suffix (added in ADR-042) — got `'Top SKUs by margin'`
- ✅ **SUB-04**: 80-char input truncated to ≤59 chars with `'…'` — got len=56

### `_highlight_chart_keyword()` — chart keyword HTML pill

- ✅ **HLT-01**: Returns `<span` for keyword `'line chart'` (span_found=True)
- ✅ **HLT-02**: Returns `<span` for keyword `'pie chart'` (span_found=True)
- ✅ **HLT-03**: No keyword → unchanged string, no `<span` (span_found=False)
- ✅ **HLT-04**: Original capitalisation preserved inside `<span>` — 'AS A LINE CHART' in span: True

### `_extract_chart_type()` — Gemini annotation parser (`src/nl2sql.py`)

- ✅ **ECT-01**: Parses `CHART_TYPE: pie` correctly — got `'pie'`
- ✅ **ECT-02**: Missing annotation → `'auto'` — got `'auto'`
- ✅ **ECT-03**: `'donut'` not in VALID_CHART_TYPES → `'auto'` (regex alternation rejects it) — got `'auto'`
- ✅ **ECT-04**: Parses `CHART_TYPE: scatter` correctly — got `'scatter'`
- ✅ **ECT-05**: Case-insensitive match: `'BAR'` → `'bar'` via `.lower()` — got `'bar'`

**Section 3 result: 15/15 tests passed**


---

## Section 4 — F-13: Render Function Fallback Behaviour

Verifies each render function falls back to `st.dataframe()` on malformed input, and that `go.Bar(orientation='h')` is triggered for long categorical labels. `st.*` calls intercepted via the `MagicMock` injected into `sys.modules['streamlit']`.

- ✅ **RND-01**: `render_bar()` with all-string df (no numeric cols) → `st.dataframe()` called, `st.plotly_chart()` not called
- ✅ **RND-02**: `render_line()` with all-numeric df (no cat cols) → `st.dataframe()` called, `st.plotly_chart()` not called
- ✅ **RND-03**: `render_pie()` with all-string df (no numeric cols) → `st.dataframe()` called, `st.plotly_chart()` not called
- ✅ **RND-04**: `render_scatter()` with only 1 numeric col → `st.dataframe()` called (need ≥2 numeric for scatter)
- ✅ **RND-05**: `render_bar()` avg label len>4 (CocoaEthos≈10 chars) → `go.Bar(orientation='h')` + `st.plotly_chart()` called (horizontal=True)
- ✅ **RND-06**: `render_line()` year+quarter+brand+revenue df → temporal priority selects `quarter` (n_unique=4) over `year` (n_unique=1); `st.plotly_chart()` called (chart_rendered=True)

**Section 4 result: 6/6 tests passed**


---

## Section 5 — Track B: Manual UI Checklist (`streamlit run app.py`)

Run `streamlit run app.py` and update each row with ✅ PASS / ❌ FAIL / ⚠️ N/A.

### F-13 — Core Conversational UI

| #   | Item                        | Expected                                                                                   | Result |
| --- | --------------------------- | ------------------------------------------------------------------------------------------ | ------ |
| 1   | Empty-state chips           | 3 chips rendered; chip click submits question                                              | ✅ PASS |
| 2   | Immediate user bubble       | User bubble appears immediately on Enter — BEFORE spinner (two-rerun pattern)              | ✅ PASS |
| 3   | Spinner                     | 'Analysing…' visible below user bubble during `run_turn()` call                            | ✅ PASS |
| 4   | User bubble                 | Right-aligned, teal background, chart keyword highlighted via `_highlight_chart_keyword()` | ✅ PASS |
| 5   | Response card               | Q-badge, subtitle (from `_make_subtitle()`), timestamp all visible                         | ✅ PASS |
| 6   | ⟳ Refined badge             | Badge shown when `retry_count > 0`                                                         | ✅ PASS |
| 7   | Toggle label                | Radio label matches resolved chart type (e.g. `'Pie chart / Table'`)                       | ✅ PASS |
| 8   | Toggle persistence          | Chart/table preference retained when next question submitted                               | ✅ PASS |
| 9   | Input locked during restore | `st.chat_input` disabled + `'Click ↺ Restore…'` placeholder                                | ✅ PASS |
| 10  | Scroll-to-latest            | Thread auto-scrolls to bottom on each new answer                                           | ✅ PASS |

### F-14 — Dual-Audience Output Design

| #   | Item                         | Expected                                                            | Result |
| --- | ---------------------------- | ------------------------------------------------------------------- | ------ |
| 1   | Narrative visible by default | Business user can interpret result without expanding SQL panel      | ✅ PASS |
| 2   | Narrative font               | Lora serif — verify via browser devtools → Computed styles          | ✅ PASS |
| 3   | SQL expander collapsed       | Collapsed by default; summary label shows row count + latency       | ✅ PASS |
| 4   | Dark code block              | SQL code inside expander has `#1a2332` dark background              | ✅ PASS |
| 5   | nl2sql error state           | Toast notification shown (auto-dismisses); no SQL expander rendered | ✅ PASS |
| 6   | Empty narrative warning      | `st.warning()` shown when narrative empty but SQL succeeded         | ✅ PASS |

### F-15 — Logging (Live Verification)

| #   | Item                              | Expected                                                       | Result |
| --- | --------------------------------- | -------------------------------------------------------------- | ------ |
| 1   | `logs/interactions.jsonl` created | File present after first question                              | ✅ PASS |
| 2   | Entry field count                 | 14 canonical + 2 ADR-042 fields all present                    | ✅ PASS |
| 3   | Resumed entry flagging            | `resumed=true` + `resumed_at` ISO string after session restore | ✅ PASS |

### F-13 — Session Resumption (Three States)

| State              | Expected                                                               | Result |
| ------------------ | ---------------------------------------------------------------------- | ------ |
| State 1 — Pending  | Dashed ChartPlaceholder boxes visible; `st.chat_input` locked          | ✅ PASS |
| State 2 — Running  | Progressive per-turn card restore with spinner; one rerun per question | ✅ PASS |
| State 3 — Complete | Full charts rendered; `st.chat_input` re-enabled                       | ✅ PASS |
| Resumed divider    | Separator between original and continued turns                         | ✅ PASS |


---

## ADR-042 Reference: `suggested_chart_type` vs `rendered_chart_type`

Demonstrates the priority chain across all canonical test queries. `suggested_chart_type` = Gemini annotation; `rendered_chart_type` = final resolved output after all three priority levels.

| Query (abbreviated) | Gemini annotation | Keyword? | Rendered | Priority level |
|---|---|---|---|---|
| Brand revenue share as a pie chart? | `bar` | Yes → `pie` | `pie` | P1 — keyword |
| CocoaEthos vs BerryBliss revenue | `bar` | Yes → `scatter` | `scatter` | P1 — keyword |
| Weekly revenue trend for NitroBoost | `auto` | Yes → `line` | `line` | P1 — keyword |
| Top brands by revenue in 2025 | `pie` | No | `pie` | P2 — Gemini |
| Top brands by revenue in 2025 | `auto` | No | `bar` | P3 — heuristic (cat df) |
| Top brands revenue (temporal df) | `auto` | No | `line` | P3 — heuristic (temporal) |
| Top brands revenue (cat df) | `auto` | No | `bar` | P3 — heuristic (bar) |
| Top brands revenue (2-num df) | `auto` | No | `scatter` | P3 — heuristic (scatter) |
| Top brands revenue (1num+2cat df) | `auto` | No | `bar` | P4 — default (heuristic→table) |


---

## Sprint 4 Closure Summary

**Automated result: 54/54 tests passed (✅ all pass)** 

| Feature                      | Sections | Automated tests  | Automated result | Manual checklist | Sprint status |
| ---------------------------- | -------- | ---------------- | ---------------- | ---------------- | ------------- |
| **F-15** JSONL Logging       | §1       | 13               | ✅ 13/13          | §5 F-15          | ✅ Validated   |
| **ADR-042** Chart resolution | §2       | 20               | ✅ 20/20          | N/A              | ✅ Validated   |
| **F-13** UI Logic (auto)     | §3–4     | 21               | ✅ 21/21          | §5 F-13          | ✅ Validated   |
| **F-14** Dual-Audience       | —        | N/A (CSS/layout) | N/A              | §5 F-14          | ✅ Validated   |

### Findings from automated test run

| # | Finding | Severity | Status | Resolution |
|---|---|---|---|---|
| F-1 | `'top '` in `PROMPT_KEYWORDS['bar']` was over-firing on ranking queries, overriding P2/P3 when no explicit chart type was requested. | Medium | ✅ **RESOLVED** | `'top '` removed from `PROMPT_KEYWORDS['bar']`. Explicit `'bar chart'`/`'bar graph'`/`'ranking'` keywords still match correctly. |
| F-2 | `_make_subtitle()` strip list omitted `' as a pie chart'` and `' as a scatter plot'`. Subtitle retained chart-type suffix as visible text in the response card. | Low | ✅ **RESOLVED** | Added `' as a pie chart'`, `' as a scatter plot'`, `' as a scatter'` to strip list. SUB-02, SUB-05, SUB-06 now pass. |

### Post-fix changes not covered by automated tests

The following changes were applied during Sprint 4 after the initial validation run. They are verified by updated automated tests above and/or the Track B manual checklist.

- **Immediate user bubble** (`handle_question` two-rerun pattern): user question echoed before LLM call starts. Verified manually — Track B F-13 item 2.
- **Toast error notifications**: `st.error()` replaced with `st.toast()` on all error paths. Verified manually — Track B F-14 item 5.
- **`render_line()` temporal priority**: `year`+`quarter` queries now correctly select `quarter` as x-axis. Verified by RND-06.
- **`MODEL_FALLBACK`**: updated from retired `gemini-1.5-flash` → `gemini-2.5-flash-lite`. Infrastructure change, no automated test required.
