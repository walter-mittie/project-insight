"""
app.py
------
F-13 · Streamlit Conversational UI
F-14 · Dual-Audience Output Design
F-15 · JSONL Logging Infrastructure (via src/logger.py)

AM1: Agentic Conversational BI — Manu Mohandas / TCS

Sprint 4 Streamlit UI for Project Insight: Conversational BI.
Entry point: `streamlit run app.py`

Design decisions
----------------
- Calls run_turn() exclusively — no direct dependency on nl2sql, executor, or narrative.
- DuckDB connection opened once per session and stored in session_state (critical).
- Chart type inferred by frontend heuristic (ADR-041, Option A) — no backend involvement.
- Dual-audience: business users see narrative + chart/table; technical reviewers access
  SQL, latency, and retry count via collapsible expander only.
- Session resumption: three-state model (pending → running → complete) matching mockup spec.
"""

import logging
import uuid
import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime

from src.agent import run_turn
from src.db import get_connection
from src.logger import (
    log_turn,
    load_past_sessions,
    read_turns_from_jsonl,
    LogWriteError,
)

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════════════
# PAGE CONFIG — must be first Streamlit call
# ══════════════════════════════════════════════════════════════════════════════

st.set_page_config(
    page_title="Project Insight",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ══════════════════════════════════════════════════════════════════════════════
# COLOUR TOKENS — match sprint4_mockup_v2.jsx exactly
# ══════════════════════════════════════════════════════════════════════════════

C = {
    "page_bg": "#f0f4f6",
    "header": "#1a2332",
    "card_bg": "#ffffff",
    "border": "#e8edf2",
    "border_mid": "#d1dce6",
    "teal": "#2ca58d",
    "teal_dark": "#0e7c86",
    "teal_muted": "#e6f4f1",
    "amber": "#92400e",
    "amber_bg": "#fffbeb",
    "amber_border": "#fcd34d",
    "navy": "#1a2332",
    "text_primary": "#1a2332",
    "text_muted": "#7a8fa6",
    "text_body": "#2d3e50",
    "code_bg": "#1a2332",
    "code_text": "#a8d8dc",
    "bar_colors": ["#0e7c86", "#2ca58d", "#5bbfb0", "#38a3a5"],
}

CHART_KEYWORDS = {
    "line": [
        "line chart",
        "line graph",
        "trend",
        "over time",
        "weekly",
        "monthly",
        "quarterly",
        "daily",
        "by week",
        "by month",
    ],
    "bar": ["bar chart", "bar graph", "column chart", "compare", "comparison"],
    "table": ["table", "list", "show me", "breakdown", "detail"],
}

EXAMPLE_PROMPTS = [
    "2025 quarterly revenue growth of top 5 brands as a line chart",
    "Which retailers drove the most promotional volume uplift in April?",
    "Top 10 SKUs by gross margin contribution — last 12 weeks",
]


# ══════════════════════════════════════════════════════════════════════════════
# SESSION STATE INITIALISATION
# ══════════════════════════════════════════════════════════════════════════════


def _new_session_id() -> str:
    return str(uuid.uuid4())


def _init_session_state() -> None:
    if "turns" not in st.session_state:
        st.session_state.turns = []  # result dicts for display
    if "history" not in st.session_state:
        st.session_state.history = []  # conversation_history for agent
    if "conn" not in st.session_state:
        st.session_state.conn = get_connection()  # DuckDB — open ONCE per session
    if "session_id" not in st.session_state:
        st.session_state.session_id = _new_session_id()
    if "session_start" not in st.session_state:
        st.session_state.session_start = datetime.now()
    if "resumed_from" not in st.session_state:
        st.session_state.resumed_from = None  # date string when resumed
    if "restore_complete" not in st.session_state:
        st.session_state.restore_complete = False
    if "restore_running" not in st.session_state:
        st.session_state.restore_running = False
    if "turns_raw" not in st.session_state:
        st.session_state.turns_raw = []  # JSONL entries (pending state)
    if "view_prefs" not in st.session_state:
        st.session_state.view_prefs = {}  # {turn_index: "chart"|"table"}
    if "warning_dismissed" not in st.session_state:
        st.session_state.warning_dismissed = False


# ══════════════════════════════════════════════════════════════════════════════
# CSS + FONT INJECTION
# ══════════════════════════════════════════════════════════════════════════════


def _inject_global_css() -> None:
    st.markdown(
        """
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600&family=DM+Mono:wght@400;500&family=Lora:ital,wght@0,400;1,400&display=swap');

/* ── Page background ── */
.stApp, [data-testid="stAppViewContainer"] {
    background: #f0f4f6 !important;
}

/* ── Dark sticky header ── */
header[data-testid="stHeader"] {
    background: #1a2332 !important;
    box-shadow: 0 2px 12px rgba(0,0,0,0.18);
}

/* ── Sidebar styling ── */
[data-testid="stSidebar"] {
    background: white !important;
    border-right: 1px solid #e8edf2;
}
[data-testid="stSidebar"] .stMarkdown p {
    font-family: 'DM Sans', sans-serif;
    font-size: 0.88rem;
}

/* ── Main thread container ── */
.main .block-container {
    max-width: 860px !important;
    padding-top: 1.5rem !important;
    padding-bottom: 140px !important;
}

/* ── Global font ── */
html, body, [class*="css"] {
    font-family: 'DM Sans', sans-serif !important;
}

/* ── Radio button: chart/table toggle styling ── */
div[data-testid="stRadio"] > label {
    font-family: 'DM Mono', monospace !important;
    font-size: 0.78rem !important;
    color: #7a8fa6 !important;
    display: none; /* hide the "No label" */
}
div[data-testid="stRadio"] > div {
    background: #f0f4f6;
    border: 1px solid #e8edf2;
    border-radius: 7px;
    padding: 3px;
    display: inline-flex;
    gap: 2px;
}
div[data-testid="stRadio"] > div > label {
    padding: 4px 14px !important;
    border-radius: 5px !important;
    font-family: 'DM Sans', sans-serif !important;
    font-size: 0.75rem !important;
    cursor: pointer !important;
}

/* ── Plotly chart: remove default margin ── */
[data-testid="stPlotlyChart"] {
    margin-bottom: 0 !important;
}

/* ── Dataframe: DM Mono numerics ── */
[data-testid="stDataFrame"] td {
    font-family: 'DM Mono', monospace !important;
    font-size: 0.8rem !important;
}
[data-testid="stDataFrame"] th {
    font-family: 'DM Sans', sans-serif !important;
    font-size: 0.72rem !important;
    text-transform: uppercase !important;
    letter-spacing: 0.05em !important;
    color: #7a8fa6 !important;
    background: #f7fafa !important;
}

/* ── Expander: SQL panel styling ── */
details[data-testid="stExpander"] {
    border: 1px solid #e8edf2 !important;
    border-radius: 0 0 8px 8px !important;
    border-top: none !important;
    background: white !important;
}
details[data-testid="stExpander"] summary {
    font-family: 'DM Mono', monospace !important;
    font-size: 0.78rem !important;
    color: #7a8fa6 !important;
    letter-spacing: 0.04em !important;
    padding: 0.6rem 1.2rem !important;
    background: white !important;
}
details[data-testid="stExpander"] summary:hover {
    background: #f7fafa !important;
}

/* ── Code block: dark background ── */
[data-testid="stCode"] {
    background: #1a2332 !important;
}
[data-testid="stCode"] code {
    font-family: 'DM Mono', monospace !important;
    font-size: 0.78rem !important;
    color: #a8d8dc !important;
    line-height: 1.7 !important;
}

/* ── st.chat_input styling ── */
[data-testid="stChatInput"] {
    border-color: #d1dce6 !important;
    border-radius: 10px !important;
    font-family: 'DM Sans', sans-serif !important;
    font-size: 0.925rem !important;
}
[data-testid="stChatInput"]:focus-within {
    border-color: #0e7c86 !important;
}

/* ── st.warning / st.error / st.info banners ── */
[data-testid="stAlert"][data-baseweb="notification"][kind="warning"] {
    background: #fffbeb !important;
    border: 1px solid #fcd34d !important;
    color: #92400e !important;
    font-family: 'DM Sans', sans-serif !important;
    font-size: 0.82rem !important;
}

/* ── Chat input bottom bar ── */
[data-testid="stBottom"] {
    background: white !important;
    border-top: 1px solid #e8edf2 !important;
    box-shadow: 0 -4px 20px rgba(0,0,0,0.07) !important;
}

/* ── Hide Streamlit default menu/footer ── */
#MainMenu, footer { visibility: hidden; }
</style>
""",
        unsafe_allow_html=True,
    )


# ══════════════════════════════════════════════════════════════════════════════
# CHART HELPERS (ADR-041 — Option A: heuristic, frontend-only)
# ══════════════════════════════════════════════════════════════════════════════


def detect_chart_hint(question: str) -> str:
    """
    Parse user question for explicit chart type keywords.

    Priority: first keyword match wins. Returns "auto" if no keyword found.
    This is purely frontend — never passed to the backend or Gemini.

    Returns: "line" | "bar" | "table" | "auto"
    """
    q = question.lower()
    for chart_type, keywords in CHART_KEYWORDS.items():
        if any(kw in q for kw in keywords):
            return chart_type
    return "auto"


def auto_detect_chart(df: pd.DataFrame) -> str:
    """
    Heuristic chart type detection from DataFrame structure (ADR-041).

    Rules (applied in order):
    1. Exactly one numeric col + one non-numeric col → chart candidate.
    2. Non-numeric col contains temporal values (week, date, month, quarter
       keywords) → line chart.
    3. Non-numeric col is categorical → bar chart.
    4. All other shapes → "table" (dataframe fallback).

    Returns: "line" | "bar" | "table"
    """
    num_cols = df.select_dtypes(include="number").columns.tolist()
    cat_cols = df.select_dtypes(exclude="number").columns.tolist()

    if len(num_cols) != 1 or len(cat_cols) < 1:
        return "table"

    # Temporal signal: check column name and sample values
    temporal_tokens = [
        "week",
        "w1",
        "w2",
        "w3",
        "w4",
        "w5",
        "w6",
        "w7",
        "w8",
        "jan",
        "feb",
        "mar",
        "apr",
        "may",
        "jun",
        "jul",
        "aug",
        "sep",
        "oct",
        "nov",
        "dec",
        "q1",
        "q2",
        "q3",
        "q4",
        "date",
        "month",
        "quarter",
        "daily",
    ]
    x_col = cat_cols[0]
    col_name_lower = x_col.lower()
    sample_lower = str(df[x_col].iloc[0]).lower() if not df.empty else ""

    if any(tok in col_name_lower or tok in sample_lower for tok in temporal_tokens):
        return "line"

    return "bar"


def _build_plotly_chart(df: pd.DataFrame, chart_type: str) -> go.Figure:
    """
    Build a Plotly figure for the given DataFrame and inferred chart type.

    Bar chart colours cycle through C["bar_colors"].
    Horizontal bar used when avg categorical label length > 4 chars.
    Line chart: single teal line (#2ca58d), strokeWidth 2.5, circular dots.
    Both: no axis lines, no tick lines, horizontal #e8edf2 gridlines only.
    """
    num_cols = df.select_dtypes(include="number").columns.tolist()
    cat_cols = df.select_dtypes(exclude="number").columns.tolist()

    if not num_cols or not cat_cols:
        return None

    x_col = cat_cols[0]
    y_col = num_cols[0]
    bar_colors = C["bar_colors"]

    layout_common = dict(
        paper_bgcolor="white",
        plot_bgcolor="white",
        margin=dict(t=8, b=8, l=0, r=16),
        height=200,
        font=dict(family="DM Sans, sans-serif", size=12, color="#4a5568"),
        showlegend=False,
    )
    axis_common = dict(
        showgrid=False,
        zeroline=False,
        showline=False,
        tickfont=dict(family="DM Mono, monospace", size=11, color="#7a8fa6"),
    )
    xaxis_style = {
        **axis_common,
        "tickfont": dict(family="DM Sans, sans-serif", size=12, color="#4a5568"),
    }

    if chart_type == "line":
        fig = go.Figure()
        fig.add_trace(
            go.Scatter(
                x=df[x_col],
                y=df[y_col],
                mode="lines+markers",
                line=dict(color=C["teal"], width=2.5),
                marker=dict(color=C["teal"], size=7, line=dict(width=0)),
            )
        )
        fig.update_layout(
            **layout_common,
            xaxis=dict(**xaxis_style, showgrid=False),
            yaxis=dict(
                **axis_common, showgrid=True, gridcolor=C["border"], gridwidth=1
            ),
        )
        return fig

    # Bar chart
    avg_label_len = df[x_col].astype(str).str.len().mean() if not df.empty else 0
    use_horizontal = avg_label_len > 4

    colors = [bar_colors[i % len(bar_colors)] for i in range(len(df))]

    if use_horizontal:
        fig = go.Figure()
        fig.add_trace(
            go.Bar(
                x=df[y_col],
                y=df[x_col],
                orientation="h",
                marker=dict(color=colors, line=dict(width=0)),
            )
        )
        fig.update_layout(
            **layout_common,
            height=max(200, 40 * len(df) + 40),
            xaxis=dict(
                **axis_common, showgrid=True, gridcolor=C["border"], gridwidth=1
            ),
            yaxis=dict(**xaxis_style, showgrid=False, autorange="reversed"),
        )
    else:
        fig = go.Figure()
        fig.add_trace(
            go.Bar(
                x=df[x_col],
                y=df[y_col],
                marker=dict(color=colors, line=dict(width=0)),
            )
        )
        fig.update_layout(
            **layout_common,
            xaxis=dict(**xaxis_style, showgrid=False),
            yaxis=dict(
                **axis_common, showgrid=True, gridcolor=C["border"], gridwidth=1
            ),
        )
    return fig


def _chart_axis_label(df: pd.DataFrame, question: str) -> str:
    """Generate 11px DM Mono uppercase axis label from DataFrame column names."""
    num_cols = df.select_dtypes(include="number").columns.tolist()
    if not num_cols:
        return ""
    return num_cols[0].replace("_", " ").upper()


# ══════════════════════════════════════════════════════════════════════════════
# SUBTITLE GENERATION
# ══════════════════════════════════════════════════════════════════════════════


def _make_subtitle(question: str, sql: str = "") -> str:
    """Generate a concise card subtitle from the user question."""
    q = question.strip()
    # Strip explicit chart type suffixes
    for suffix in [
        " as a line chart",
        " as a bar chart",
        " as a table",
        " as a chart",
        " as line chart",
        " as bar chart",
    ]:
        q = q.replace(suffix, "")
    if len(q) > 58:
        q = q[:55] + "…"
    return q


def _highlight_chart_keyword(question: str) -> str:
    """
    Return question HTML with chart-type keyword highlighted in a translucent pill
    (matches user bubble specification).
    """
    q_lower = question.lower()
    pill = (
        "background:rgba(255,255,255,0.18);border-radius:4px;"
        "padding:1px 6px;font-size:0.85rem"
    )
    for kw in [
        "as a line chart",
        "as a bar chart",
        "as a table",
        "line chart",
        "bar chart",
    ]:
        if kw in q_lower:
            idx = q_lower.index(kw)
            phrase = question[idx : idx + len(kw)]
            return (
                question[:idx]
                + f'<span style="{pill}">{phrase}</span>'
                + question[idx + len(kw) :]
            )
    return question


# ══════════════════════════════════════════════════════════════════════════════
# HEADER
# ══════════════════════════════════════════════════════════════════════════════


def _render_header() -> None:
    """
    Dark navy header: hamburger + logo + title + Conversational BI subtitle
    on the left; ● READY badge on the right.
    """
    st.markdown(
        f"""
<div style="
    background:{C["header"]};color:white;
    padding:0 1.5rem 0 1rem;height:54px;
    display:flex;align-items:center;justify-content:space-between;
    position:sticky;top:0;z-index:100;
    box-shadow:0 2px 12px rgba(0,0,0,0.18);
    margin:-1.5rem -1.5rem 1.5rem -1.5rem;
">
  <div style="display:flex;align-items:center;gap:0.75rem">
    <!-- Logo SVG -->
    <svg width="28" height="28" viewBox="0 0 28 28" fill="none" aria-hidden="true">
      <rect x="2"  y="16" width="5" height="10" rx="1.5" fill="#2ca58d" opacity="0.5"/>
      <rect x="10" y="9"  width="5" height="17" rx="1.5" fill="#2ca58d" opacity="0.75"/>
      <rect x="18" y="3"  width="5" height="23" rx="1.5" fill="#2ca58d"/>
      <circle cx="7" cy="9" r="5" fill="#1a2332" stroke="#2ca58d" stroke-width="1.5"/>
      <path d="M5 9h4M7 7v4" stroke="#2ca58d" stroke-width="1.5" stroke-linecap="round"/>
    </svg>
    <span style="font-weight:600;font-size:0.95rem;letter-spacing:0.01em;
                 font-family:'DM Sans',sans-serif">
      Project Insight
    </span>
    <span style="color:#4a7fa0;font-size:0.75rem;
                 font-family:'DM Mono',monospace">
      Conversational BI
    </span>
  </div>
  <div style="
      background:#2ca58d22;color:#2ca58d;
      padding:3px 10px;border-radius:4px;
      font-weight:500;font-size:0.75rem;
      font-family:'DM Mono',monospace;
      display:flex;align-items:center;gap:6px;
  ">
    <span style="width:6px;height:6px;border-radius:50%;
                 background:#2ca58d;display:inline-block"></span>
    READY
  </div>
</div>
""",
        unsafe_allow_html=True,
    )


# ══════════════════════════════════════════════════════════════════════════════
# SIDEBAR — past sessions
# ══════════════════════════════════════════════════════════════════════════════


def _render_sidebar() -> None:
    """
    st.sidebar past sessions panel.
    Reads JSONL log, groups by session_id, renders as a clickable list.
    Active session: teal left border + #e6f4f1 background.
    """
    with st.sidebar:
        st.markdown(
            "<p style=\"font-family:'DM Sans',sans-serif;font-weight:600;"
            'font-size:0.88rem;color:#1a2332;margin:0.5rem 0 0.75rem">Past sessions</p>',
            unsafe_allow_html=True,
        )

        sessions = load_past_sessions()

        if not sessions:
            st.markdown(
                '<p style="font-size:0.78rem;color:#7a8fa6;'
                "font-family:'DM Mono',monospace\">No past sessions yet.</p>",
                unsafe_allow_html=True,
            )
        else:
            active_sid = st.session_state.session_id
            for s in sessions:
                is_active = s["id"] == active_sid
                bg = C["teal_muted"] if is_active else "transparent"
                border_color = C["teal_dark"] if is_active else "transparent"
                date_color = C["teal_dark"] if is_active else C["text_muted"]
                badge_bg = C["teal_dark"] if is_active else C["page_bg"]
                badge_color = "white" if is_active else C["text_muted"]
                badge_border = C["teal_dark"] if is_active else C["border"]
                preview_color = C["navy"] if is_active else C["text_body"]
                preview_weight = 500 if is_active else 400

                label = f"{s['date']} · Q{s['q_count']} · {s['preview'][:40]}…"
                if st.button(label, key=f"session_{s['id']}", use_container_width=True):
                    _load_session(s["id"])

        st.markdown(
            '<p style="font-size:0.72rem;color:#7a8fa6;'
            "font-family:'DM Mono',monospace;margin-top:1rem;"
            'border-top:1px solid #e8edf2;padding-top:0.75rem">'
            "Sessions stored in audit log · read-only</p>",
            unsafe_allow_html=True,
        )


# ══════════════════════════════════════════════════════════════════════════════
# BANNERS — context window warning + resumed session
# ══════════════════════════════════════════════════════════════════════════════


def _render_banners() -> None:
    """
    Render zero, one, or two banners at the top of the thread:
    1. Amber context window notice (if any turn has history_truncated=True)
    2. Resumed session banner (three states: pending / running / complete)
    """
    # ── Amber context window banner ──────────────────────────────────────────
    any_truncated = any(
        t.get("history_truncated", False) for t in st.session_state.turns
    )
    if any_truncated and not st.session_state.warning_dismissed:
        col_warn, col_x = st.columns([11, 1])
        with col_warn:
            st.markdown(
                f"""
<div style="
    background:{C["amber_bg"]};border:1px solid {C["amber_border"]};
    border-radius:8px;padding:0.6rem 1rem;margin-bottom:1.25rem;
    font-size:0.82rem;color:{C["amber"]};font-family:'DM Sans',sans-serif;
">
    ⚠️ Context window notice — oldest questions have been summarised to fit
    within the model's context limit. Recent context is retained.
</div>
""",
                unsafe_allow_html=True,
            )
        with col_x:
            if st.button("×", key="dismiss_warning"):
                st.session_state.warning_dismissed = True
                st.rerun()

    # ── Resumed session banner ───────────────────────────────────────────────
    if st.session_state.resumed_from is None:
        return

    resumed_date = st.session_state.resumed_from
    turns_raw = st.session_state.turns_raw
    n_total = len(turns_raw)
    n_restored = len(st.session_state.turns)

    if st.session_state.restore_running and not st.session_state.restore_complete:
        # State 2 — running
        st.markdown(
            f"""
<div style="
    background:{C["teal_muted"]};border:1px solid {C["teal"]};
    border-radius:8px;padding:0.6rem 1rem;margin-bottom:1.25rem;
    font-size:0.82rem;color:{C["teal_dark"]};font-family:'DM Sans',sans-serif;
    display:flex;align-items:center;gap:0.6rem;flex-wrap:wrap;
">
    <span>↺ Restoring question {n_restored + 1} of {n_total}… please wait</span>
    <span style="margin-left:auto;font-size:0.78rem;
                 font-family:'DM Mono',monospace;color:{C["text_muted"]}">
        ← use sidebar for new session
    </span>
</div>
""",
            unsafe_allow_html=True,
        )

    elif st.session_state.restore_complete:
        # State 3 — complete
        col_msg, col_new = st.columns([8, 2])
        with col_msg:
            st.markdown(
                f"""
<div style="
    background:{C["teal_muted"]};border:1px solid {C["teal"]};
    border-radius:8px;padding:0.6rem 1rem;margin-bottom:1.25rem;
    font-size:0.82rem;color:{C["teal_dark"]};font-family:'DM Sans',sans-serif;
">
    ↩ Resumed · {resumed_date} — all {n_total} question{"s" if n_total != 1 else ""} restored.
    Ready to continue.
</div>
""",
                unsafe_allow_html=True,
            )
        with col_new:
            if st.button("← New session", key="new_session_complete"):
                _start_new_session()

    else:
        # State 1 — pending
        col_msg, col_restore, col_new = st.columns([5, 2, 2])
        with col_msg:
            st.markdown(
                f"""
<div style="
    background:{C["teal_muted"]};border:1px solid {C["teal"]};
    border-radius:8px;padding:0.6rem 1rem;margin-bottom:0;
    font-size:0.82rem;color:{C["teal_dark"]};font-family:'DM Sans',sans-serif;
">
    ↩ Resumed · {resumed_date} — narrative &amp; SQL loaded.
    Restore to view charts.
</div>
""",
                unsafe_allow_html=True,
            )
        with col_restore:
            if st.button("↺ Restore", key="restore_btn", type="primary"):
                st.session_state.restore_running = True
                st.rerun()
        with col_new:
            if st.button("← New session", key="new_session_pending"):
                _start_new_session()
        st.markdown("<div style='margin-bottom:1.25rem'></div>", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# EMPTY STATE
# ══════════════════════════════════════════════════════════════════════════════


def _render_empty_state() -> None:
    """Render centred empty state with three example prompt chip buttons."""
    st.markdown(
        """
<div style="text-align:center;padding:4rem 1rem;color:#7a8fa6">
    <svg width="40" height="40" viewBox="0 0 28 28" fill="none"
         style="margin-bottom:1rem;opacity:0.4" aria-hidden="true">
      <rect x="2"  y="16" width="5" height="10" rx="1.5" fill="#2ca58d" opacity="0.5"/>
      <rect x="10" y="9"  width="5" height="17" rx="1.5" fill="#2ca58d" opacity="0.75"/>
      <rect x="18" y="3"  width="5" height="23" rx="1.5" fill="#2ca58d"/>
      <circle cx="7" cy="9" r="5" fill="#f0f4f6" stroke="#2ca58d" stroke-width="1.5"/>
      <path d="M5 9h4M7 7v4" stroke="#2ca58d" stroke-width="1.5" stroke-linecap="round"/>
    </svg>
    <p style="font-size:1rem;font-family:'DM Sans',sans-serif;color:#7a8fa6;margin:0 0 0.4rem">
        Ask a question about your FMCG sales data to get started.
    </p>
    <p style="font-size:0.78rem;font-family:'DM Mono',monospace;color:#a0b0bf;margin:0 0 2rem">
        Powered by Gemini 2.5 Flash · DuckDB
    </p>
</div>
""",
        unsafe_allow_html=True,
    )

    cols = st.columns(3)
    for i, prompt in enumerate(EXAMPLE_PROMPTS):
        with cols[i]:
            st.markdown(
                f"""
<div style="
    background:white;border:1px solid #e8edf2;border-radius:10px;
    padding:0.75rem 0.9rem;font-size:0.8rem;color:#2d3e50;
    font-family:'DM Sans',sans-serif;line-height:1.45;
    cursor:pointer;min-height:60px;
">
    "{prompt}"
</div>
""",
                unsafe_allow_html=True,
            )
            if st.button("Ask this →", key=f"chip_{i}", use_container_width=True):
                handle_question(prompt)


# ══════════════════════════════════════════════════════════════════════════════
# USER BUBBLE
# ══════════════════════════════════════════════════════════════════════════════


def _render_user_bubble(question: str) -> None:
    """Right-aligned teal bubble with chart-type keyword highlighted."""
    highlighted = _highlight_chart_keyword(question)
    st.markdown(
        f'<div style="display:flex;justify-content:flex-end;margin-bottom:0.75rem">'
        f'<div style="background:#0e7c86;color:white;'
        f"border-radius:18px 18px 4px 18px;"
        f"padding:0.65rem 1.1rem;max-width:70%;"
        f"font-size:0.925rem;line-height:1.55;"
        f"font-family:'DM Sans',sans-serif\">"
        f"{highlighted}"
        f"</div></div>",
        unsafe_allow_html=True,
    )


# ══════════════════════════════════════════════════════════════════════════════
# CHART PLACEHOLDER (resumed session, pre-restore)
# ══════════════════════════════════════════════════════════════════════════════


def _render_chart_placeholder() -> None:
    st.markdown(
        """
<div style="
    height:148px;border-radius:8px;border:1.5px dashed #e8edf2;
    background:#f7fafa;display:flex;flex-direction:column;
    align-items:center;justify-content:center;margin-bottom:14px;gap:6px;
">
    <span style="font-size:20px;color:#7a8fa6;opacity:0.5">↺</span>
    <span style="font-size:12px;color:#7a8fa6;font-family:'DM Mono',monospace">
        Chart data not loaded — click ↺ Restore above
    </span>
</div>
""",
        unsafe_allow_html=True,
    )


# ══════════════════════════════════════════════════════════════════════════════
# RESUMED DIVIDER
# ══════════════════════════════════════════════════════════════════════════════


def _render_resumed_divider(original_date: str) -> None:
    st.markdown(
        f"""
<div style="display:flex;align-items:center;gap:0.75rem;margin:1.5rem 0">
    <div style="flex:1;height:1px;background:#e8edf2"></div>
    <div style="
        background:#e6f4f1;border:1px solid #2ca58d;border-radius:20px;
        padding:4px 12px;font-size:0.75rem;color:#0e7c86;
        font-family:'DM Mono',monospace;white-space:nowrap;
    ">
        ↩ Session resumed · continued from {original_date}
    </div>
    <div style="flex:1;height:1px;background:#e8edf2"></div>
</div>
""",
        unsafe_allow_html=True,
    )


# ══════════════════════════════════════════════════════════════════════════════
# RESPONSE CARD
# ══════════════════════════════════════════════════════════════════════════════


def _render_response_card(result: dict, is_pending: bool = False) -> None:
    """
    Render one full response card for a completed turn.

    Layout (Streamlit implementation):
        [Card header HTML]    ← Q-badge, subtitle, ⟳ Refined, timestamp
        [Chart/table toggle]  ← st.radio (horizontal)
        [Chart or Table]      ← st.plotly_chart / st.dataframe
        [Narrative]           ← st.markdown (Lora serif)
        [SQL expander]        ← st.expander + st.code

    Chart rendering heuristics (ADR-041 — documented here as per spec):
        1. Check prompt keyword override first (detect_chart_hint)
        2. DataFrame with exactly one numeric + one non-numeric col → chart candidate
        3. Non-numeric col contains temporal values → line chart
        4. Non-numeric col is categorical → bar chart
        5. Multiple numeric cols or ambiguous shape → st.dataframe fallback
        6. Horizontal bar if avg categorical label length > 4 chars

    Parameters
    ----------
    result : dict
        run_turn() success dict.
    is_pending : bool
        True when showing a JSONL-sourced card before DataFrame restore
        (State 1 — Pending). Chart/table area shows ChartPlaceholder.
    """
    turn_index = result.get("turn_index", 0)
    qnum = turn_index + 1
    subtitle = _make_subtitle(result.get("user_question", ""), result.get("sql", ""))
    has_retry = result.get("retry_count", 0) > 0
    retry_count = result.get("retry_count", 0)
    df = result.get("data")
    narrative = result.get("narrative", "")
    sql = result.get("sql", "")
    row_count = result.get("row_count", 0)
    exec_ms = result.get("exec_time_ms", 0.0)

    # Timestamp: full date+time for resumed turns; time-only for same-day turns
    card_ts_raw = result.get("_timestamp")  # set by load_session path
    if card_ts_raw:
        ts_display = card_ts_raw
    else:
        ts_display = datetime.now().strftime("%d %b %Y, %H:%M")

    # ── Card header ──────────────────────────────────────────────────────────
    refined_badge = ""
    if has_retry:
        refined_badge = (
            f'<span style="background:#fffbeb;border:1px solid #fcd34d;'
            f"border-radius:12px;padding:2px 9px;font-size:11px;color:#92400e;"
            f"font-family:'DM Sans',sans-serif;flex-shrink:0\">⟳ Refined</span>"
        )

    st.markdown(
        f"""
<div style="
    background:#fafcfc;border:1px solid #e8edf2;
    border-radius:4px 18px 4px 4px;border-bottom:none;
    padding:0.75rem 1.2rem;
    display:flex;align-items:center;gap:0.6rem;
    margin-top:0.25rem;
">
    <div style="
        width:26px;height:26px;border-radius:50%;
        background:#e6f4f1;border:1.5px solid #2ca58d;
        display:flex;align-items:center;justify-content:center;
        font-size:11px;font-weight:600;color:#0e7c86;
        flex-shrink:0;font-family:'DM Mono',monospace;
    ">Q{qnum}</div>
    <span style="font-size:13px;color:#7a8fa6;flex:1;
                 font-family:'DM Sans',sans-serif;overflow:hidden;
                 text-overflow:ellipsis;white-space:nowrap">
        {subtitle}
    </span>
    {refined_badge}
    <span style="font-size:11px;color:#7a8fa6;
                 font-family:'DM Mono',monospace;white-space:nowrap;margin-left:4px">
        {ts_display}
    </span>
</div>
<div style="
    background:white;border:1px solid #e8edf2;border-top:none;
    border-radius:0;padding:1.1rem 1.2rem 0.5rem;
">
""",
        unsafe_allow_html=True,
    )

    # ── Chart / table area ───────────────────────────────────────────────────
    if is_pending or df is None:
        _render_chart_placeholder()
    else:
        # Determine default chart type
        hint = detect_chart_hint(result.get("user_question", ""))
        if hint == "table":
            default_view = "Table"
        elif hint in ("line", "bar"):
            # Resolve chart type label for radio
            default_view = "Line chart" if hint == "line" else "Bar chart"
        else:
            auto = auto_detect_chart(df)
            if auto == "table":
                default_view = "Table"
            elif auto == "line":
                default_view = "Line chart"
            else:
                default_view = "Bar chart"

        # Chart/table toggle — persist preference across reruns
        pref = st.session_state.view_prefs.get(turn_index)
        is_line = default_view == "Line chart"
        toggle_opts = ["Line chart" if is_line else "Bar chart", "Table"]
        index_default = 0
        if pref == "table":
            index_default = 1
        elif pref in ("chart", "line", "bar"):
            index_default = 0

        view = st.radio(
            "",
            toggle_opts,
            horizontal=True,
            index=index_default,
            key=f"view_{turn_index}",
        )
        # Persist preference
        st.session_state.view_prefs[turn_index] = (
            "table" if view == "Table" else "chart"
        )

        if view == "Table":
            st.dataframe(
                df,
                use_container_width=True,
                hide_index=True,
            )
        else:
            # Resolve final chart type for Plotly
            if is_line or (hint == "auto" and auto_detect_chart(df) == "line"):
                chart_type = "line"
            else:
                chart_type = "bar"

            axis_label = _chart_axis_label(df, result.get("user_question", ""))
            if axis_label:
                st.markdown(
                    f'<p style="font-size:0.7rem;color:#7a8fa6;'
                    f"font-family:'DM Mono',monospace;margin-bottom:0.4rem;"
                    f'letter-spacing:0.05em;text-transform:uppercase">'
                    f"{axis_label}</p>",
                    unsafe_allow_html=True,
                )

            fig = _build_plotly_chart(df, chart_type)
            if fig is not None:
                st.plotly_chart(fig, use_container_width=True)
            else:
                # Fallback: df has unexpected shape
                st.dataframe(df, use_container_width=True, hide_index=True)

    # ── Narrative ────────────────────────────────────────────────────────────
    if narrative:
        st.markdown(
            f'<p style="font-family:Lora,Georgia,serif;font-size:0.975rem;'
            f"line-height:1.78;color:#1a2332;border-top:1px solid #e8edf2;"
            f'padding-top:1rem;margin-top:0.25rem;margin-bottom:1.1rem">'
            f"{narrative}"
            f"</p>",
            unsafe_allow_html=True,
        )
    else:
        st.warning("Narrative unavailable for this result.")

    st.markdown("</div>", unsafe_allow_html=True)

    # ── SQL expander ─────────────────────────────────────────────────────────
    retry_label = f" · ⟳ {retry_count} retry" if retry_count > 0 else ""
    expander_label = (
        f"SQL Output — Question {qnum} · {row_count} rows "
        f"· {exec_ms:.0f}ms{retry_label}"
    )
    with st.expander(expander_label):
        if retry_count > 0:
            st.warning(
                f"⚠️ SQL corrected after {retry_count} retry attempt(s). "
                "Initial query returned 0 rows or failed to execute."
            )
        st.code(sql or "(no SQL generated)", language="sql")

    # ── Card bottom spacer ───────────────────────────────────────────────────
    st.markdown('<div style="margin-bottom:1.5rem"></div>', unsafe_allow_html=True)


def _render_pending_card(raw_turn: dict, qnum: int) -> None:
    """
    Render a card from a JSONL entry (no DataFrame available — pending restore).
    Shows narrative + SQL from the log; chart area shows ChartPlaceholder.
    """
    question = raw_turn.get("user_query", "")
    subtitle = _make_subtitle(question)
    sql = raw_turn.get("generated_sql", "")
    narrative = raw_turn.get("_narrative", "")  # not logged; show placeholder
    row_count = raw_turn.get("row_count", 0) or 0
    exec_ms = raw_turn.get("execution_time_ms", 0) or 0
    retry_count = raw_turn.get("retry_count", 0) or 0
    ts_raw = raw_turn.get("timestamp", "")
    ts_display = ts_raw[:10] if ts_raw else ""

    _render_response_card(
        result={
            "turn_index": qnum - 1,
            "user_question": question,
            "sql": sql,
            "narrative": "",  # not available from JSONL
            "data": None,
            "row_count": row_count,
            "exec_time_ms": exec_ms,
            "retry_count": retry_count,
            "_timestamp": ts_display,
        },
        is_pending=True,
    )


# ══════════════════════════════════════════════════════════════════════════════
# SESSION RESUMPTION
# ══════════════════════════════════════════════════════════════════════════════


def _load_session(session_id: str) -> None:
    """
    Load a past session from the JSONL log (State 1 — Pending).
    DataFrames not available until ↺ Restore is clicked.
    """
    turns_raw = read_turns_from_jsonl(session_id)
    if not turns_raw:
        st.warning(f"No turns found for session {session_id[:8]}…")
        return

    st.session_state.turns_raw = turns_raw
    st.session_state.turns = []
    st.session_state.history = []
    st.session_state.session_id = session_id  # retain original session ID
    st.session_state.resumed_from = turns_raw[0].get("timestamp", "")[:10]
    st.session_state.restore_complete = False
    st.session_state.restore_running = False
    st.session_state.view_prefs = {}
    st.session_state.warning_dismissed = False
    st.rerun()


def _start_new_session() -> None:
    """Clear all state and start a fresh session."""
    for key in [
        "turns",
        "history",
        "session_id",
        "session_start",
        "resumed_from",
        "restore_complete",
        "restore_running",
        "turns_raw",
        "view_prefs",
        "warning_dismissed",
    ]:
        st.session_state.pop(key, None)
    st.rerun()


def _run_restore_step() -> None:
    """
    Execute ONE restore step per Streamlit rerun (State 2 — Running).
    Each rerun restores one question, allowing progressive card rendering.
    Calling st.rerun() after each step triggers the next.
    """
    turns_raw = st.session_state.turns_raw
    n_restored = len(st.session_state.turns)
    n_total = len(turns_raw)

    if n_restored >= n_total:
        st.session_state.restore_running = False
        st.session_state.restore_complete = True
        st.rerun()
        return

    past_turn = turns_raw[n_restored]
    with st.spinner(f"Restoring question {n_restored + 1} of {n_total}…"):
        result = run_turn(
            past_turn["user_query"],
            st.session_state.history,
            st.session_state.conn,
        )

    st.session_state.history = result["conversation_history"]

    if result["status"] == "success":
        result["_timestamp"] = past_turn.get("timestamp", "")[:10]
        result["_resumed_turn"] = n_restored == 0  # first restored turn gets divider
        st.session_state.turns.append(result)
        try:
            log_turn(
                result,
                session_id=st.session_state.session_id,
                resumed=True,
                resumed_at=datetime.now().isoformat(),
            )
        except LogWriteError:
            st.warning("Log write failed — turn not recorded.")

    # Trigger next step
    st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# QUESTION HANDLER
# ══════════════════════════════════════════════════════════════════════════════


def handle_question(question: str) -> None:
    """
    Execute one turn: call run_turn(), update session state, log, rerun.
    Error turns are NOT added to turns or history.
    """
    conn = st.session_state.conn

    with st.spinner("Analysing…"):
        result = run_turn(question, st.session_state.history, conn)

    # Always assign history back — failed turns return unchanged history
    st.session_state.history = result["conversation_history"]

    if result["status"] == "error":
        stage = result.get("error_stage", "unknown")
        if stage == "nl2sql":
            st.error(
                "Could not generate a query for that question. Please try rephrasing."
            )
        elif stage == "execution":
            st.error(
                "The query failed to execute after retries. "
                "Please try a simpler question."
            )
        else:
            st.error(f"An error occurred ({stage}). Please try again.")
        # Failed turns NOT added to turns or history
    else:
        st.session_state.turns.append(result)
        try:
            log_turn(result, session_id=st.session_state.session_id)
        except LogWriteError:
            st.warning("Log write failed — turn not recorded.")

    # Scroll to latest
    components.html(
        "<script>window.parent.document.querySelector('.main')"
        ".scrollTo(0, 999999);</script>",
        height=0,
    )
    st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# FOOTER
# ══════════════════════════════════════════════════════════════════════════════


def _render_footer() -> None:
    is_resumed = st.session_state.resumed_from is not None

    if is_resumed and st.session_state.restore_running:
        n = len(st.session_state.turns_raw)
        r = len(st.session_state.turns)
        footer_text = f"Restoring question {r + 1} of {n} — please wait"
    elif is_resumed and not st.session_state.restore_complete:
        footer_text = "Click ↺ Restore to reload chart data from previous session"
    elif is_resumed:
        date = st.session_state.resumed_from
        n = len(st.session_state.turns)
        footer_text = f"Continuing session from {date} · {n} question{'s' if n != 1 else ''} in history"
    else:
        footer_text = (
            "Powered by Gemini 2.5 Flash · DuckDB · "
            "Enter to send · Shift+Enter for new line"
        )

    st.markdown(
        f'<p style="text-align:center;font-size:11px;color:#a0b0bf;'
        f"font-family:'DM Mono',monospace;margin-top:0.4rem\">"
        f"{footer_text}</p>",
        unsafe_allow_html=True,
    )


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════


def main() -> None:
    _init_session_state()
    _inject_global_css()
    _render_header()
    _render_sidebar()

    # ── Restore step (one question per rerun, State 2) ────────────────────────
    if st.session_state.restore_running and not st.session_state.restore_complete:
        _run_restore_step()
        # _run_restore_step() always calls st.rerun() so nothing below executes
        return

    # ── Banners ───────────────────────────────────────────────────────────────
    _render_banners()

    # ── Thread ────────────────────────────────────────────────────────────────
    has_live_turns = bool(st.session_state.turns)
    has_pending_turns = (
        st.session_state.resumed_from is not None
        and not st.session_state.restore_complete
        and bool(st.session_state.turns_raw)
        and not has_live_turns
    )

    if not has_live_turns and not has_pending_turns:
        # Empty state: no session loaded, no turns yet
        _render_empty_state()

    elif has_pending_turns:
        # State 1 — Pending: show JSONL cards with ChartPlaceholder
        for i, raw_turn in enumerate(st.session_state.turns_raw):
            _render_user_bubble(raw_turn.get("user_query", ""))
            _render_pending_card(raw_turn, qnum=i + 1)

    else:
        # Normal / restored turns
        resumed_date = st.session_state.resumed_from
        first_resumed_done = False

        for result in st.session_state.turns:
            # Resumed divider: before the first turn that carries _resumed flag
            if (
                resumed_date
                and result.get("_resumed_turn", False)
                and not first_resumed_done
            ):
                _render_resumed_divider(resumed_date)
                first_resumed_done = True

            _render_user_bubble(result["user_question"])
            _render_response_card(result)

    # ── Input bar ─────────────────────────────────────────────────────────────
    input_disabled = (
        st.session_state.resumed_from is not None
        and not st.session_state.restore_complete
    )

    placeholder = (
        "Click ↺ Restore above to continue this session…"
        if input_disabled
        else 'Ask a question — e.g. "2025 quarterly revenue growth of top 5 brands as a line chart"'
    )

    if question := st.chat_input(placeholder, disabled=input_disabled):
        handle_question(question)

    # ── Footer ────────────────────────────────────────────────────────────────
    _render_footer()


if __name__ == "__main__":
    main()
