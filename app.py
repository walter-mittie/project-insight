"""
app.py
------
F-13 · Streamlit Conversational UI
F-14 · Dual-Audience Output Design
F-15 · JSONL Logging Infrastructure (via src/logger.py)

Project Insight: Agentic Conversational BI 

Sprint 4 Streamlit UI for Project Insight: Conversational BI.
Entry point: `streamlit run app.py`

Design decisions
----------------
- Calls run_turn() exclusively — no direct dependency on nl2sql, executor, or narrative.
- DuckDB connection opened once per session and stored in session_state (critical).
- Chart type inferred by frontend heuristic (ADR-041, Option A) — no backend involvement.
- Dual-audience: business users see narrative + chart/table; technical reviewers access SQL, latency, and retry count via collapsible expander only.
- Session resumption: three-state model (pending → running → complete) matching mockup spec.
"""

import logging
import uuid
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime
import calendar

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

# ── Chart type constants (ADR-042 — Option B priority chain) ─────────────────
# Keyword → chart type mapping (Priority 1: explicit user intent)
PROMPT_KEYWORDS = {
    "pie": [
        "share",
        "mix",
        "split",
        "proportion",
        "composition",
        "breakdown",
        "% of",
        "percent of",
        "pie chart",
        "donut",
    ],
    "scatter": [
        "vs ",
        "versus",
        "scatter",
        "correlation",
        "against",
        "price vs",
        "spend vs",
        "margin vs",
        "bubble",
    ],
    "line": [
        "trend",
        "over time",
        "weekly",
        "monthly",
        "quarterly",
        "daily",
        "by week",
        "by month",
        "by quarter",
        "line chart",
        "line graph",
    ],
    "bar": [
        "bar chart",
        "bar graph",
        "column chart",
        "ranking",
        "compare",
        "comparison",
    ],
    "table": ["table", "list", "show me all", "breakdown", "detail"],
}

# Colour palette — cycles for bars; used by pie and scatter too
BAR_COLORS = [
    "#0e7c86",
    "#2ca58d",
    "#5bbfb0",
    "#38a3a5",
    "#2dd4bf",
    "#0d9488",
    "#14b8a6",
    "#5eead4",
]

# Human-readable labels for each chart type (used in radio toggle)
CHART_LABELS = {
    "bar": "Bar chart",
    "line": "Line chart",
    "pie": "Pie chart",
    "scatter": "Scatter plot",
    "table": "Table",
}

EXAMPLE_PROMPTS = [
    "Top 10 SKUs by net revenue in 2025 as a bar chart",
    "2025 quarterly revenue trend of top 5 brands as a line chart",
    "Revenue mix by category in 2025 as a pie chart",
]


# ══════════════════════════════════════════════════════════════════════════════
# SESSION STATE INITIALISATION
# ══════════════════════════════════════════════════════════════════════════════


def _new_session_id() -> str:
    return str(uuid.uuid4())


def _init_session_state() -> None:
    if "llm_mode" not in st.session_state:
            st.session_state.llm_mode = "cloud"
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
    if "pending_question" not in st.session_state:
        st.session_state.pending_question = None  # question submitted, awaiting run_turn()


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

    /* ── Native header: dark background only ── */
    header[data-testid="stHeader"] {
        background: #1a2332 !important;
        box-shadow: 0 2px 12px rgba(0,0,0,0.18) !important;
    }

    /* ── Hide decoration line only — toggle buttons handled below ── */
    [data-testid="stDecoration"] {
        display: none !important;
    }

    /* ── Make ALL native header icons/buttons white on dark background ── */
    /* Cast wide net across Streamlit's varying button data-testids */
    header[data-testid="stHeader"] button,
    header[data-testid="stHeader"] a {
        color: white !important;
        opacity: 1 !important;
    }
    header[data-testid="stHeader"] button svg,
    header[data-testid="stHeader"] button svg path,
    header[data-testid="stHeader"] button svg rect,
    header[data-testid="stHeader"] button svg line,
    header[data-testid="stHeader"] button svg circle,
    header[data-testid="stHeader"] button svg polyline,
    header[data-testid="stHeader"] button svg polygon {
        fill: white !important;
        stroke: white !important;
        color: white !important;
    }

    /* ── Main content: Streamlit manages offset with visible native header ── */
    .main .block-container {
        max-width: 860px !important;
        padding-top: 1.5rem !important;
        padding-bottom: 90px !important;
    }

    /* ── Sidebar ── */
    [data-testid="stSidebar"] {
        background: white !important;
        border-right: 1px solid #e8edf2 !important;
    }
    [data-testid="stSidebar"] .stMarkdown p {
        font-family: 'DM Sans', sans-serif;
        font-size: 0.88rem;
    }
    /* ══ Sidebar toggle buttons ══════════════════════════════════════════════════
    Confirmed via DevTools inspection (Streamlit 1.4x):

    OPEN (expand) button in header when sidebar is collapsed:
        data-testid="stExpandSidebarButton"  kind="headerNoPadding"
        Icon is a Material icon text node (keyboard_double_arrow_right),
        NOT an SVG — so fill/stroke rules are irrelevant; target color + span.

    CLOSE (collapse) button inside the open sidebar:
        data-testid="stSidebarCollapseButton"
        Same Material icon pattern.

    Also hide Deploy button and main menu (three-dot) from header.
    ═══════════════════════════════════════════════════════════════════════════ */

    /* Expand button: white on dark header */
    button[data-testid="stExpandSidebarButton"],
    button[data-testid="stExpandSidebarButton"] span,
    button[data-testid="stExpandSidebarButton"] span[data-testid="stIconMaterial"] {
        color: white !important;
        opacity: 1 !important;
    }

    /* Collapse button: dark on white sidebar */
    button[data-testid="stSidebarCollapseButton"],
    button[data-testid="stSidebarCollapseButton"] span,
    button[data-testid="stSidebarCollapseButton"] span[data-testid="stIconMaterial"] {
        color: #1a2332 !important;
        opacity: 1 !important;
    }

    /* Hide Deploy button and main menu (three-dot) */
    button[data-testid="stBaseButton-header"],
    button[data-testid="stMainMenuButton"],
    [data-testid="stAppDeployButton"],
    [data-testid="stMainMenu"] {
        display: none !important;
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
        color: #7a8fa6 !important;          /* unselected label colour */
    }
    div[data-testid="stRadio"] > div > label[data-checked="true"],
    div[data-testid="stRadio"] > div > label:has(input:checked) {
        background: white !important;
        color: #0e7c86 !important;          /* selected label colour */
        box-shadow: 0 1px 2px rgba(0,0,0,0.06);
    }
    /* Hide the actual radio dot — keep only the pill labels */
    div[data-testid="stRadio"] > div > label > div:first-child {
        display: none !important;
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
    [data-testid="stCode"] pre {
        background: #1a2332 !important;
        margin: 0 !important;
        padding: 0.85rem 1.1rem !important;
    }
    [data-testid="stCode"] code {
        font-family: 'DM Mono', monospace !important;
        font-size: 0.78rem !important;
        color: #a8d8dc !important;
        line-height: 1.7 !important;
        background: transparent !important;
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
    [data-testid="stChatInput"] textarea {
        padding: 10px 12px !important;
        min-height: 56px !important;   /* was 42px — increase this value */
        max-height: 56px !important;   /* pin the ceiling to match */
        height: 56px !important;       /* explicit height overrides stretching */
        resize: none !important;       /* prevents manual resize handle appearing */
    }

    /* ── st.warning / st.error / st.info banners ── */
    [data-testid="stAlert"][data-baseweb="notification"][kind="warning"] {
        background: #fffbeb !important;
        border: 1px solid #fcd34d !important;
        color: #92400e !important;
        font-family: 'DM Sans', sans-serif !important;
        font-size: 0.82rem !important;
    }

    /* ── Chat input bottom bar + footer line ── */
    [data-testid="stBottom"] {
        background: white !important;
        border-top: 1px solid #e8edf2 !important;
        box-shadow: 0 -4px 20px rgba(0,0,0,0.07) !important;
        padding: 8px 16px 4px !important;  /* tight: top 8, sides 16, bottom 4 */
    }
    [data-testid="stBottom"]::after {
        content: "Enter to send · Shift+Enter for new line";
        display: block;
        text-align: center;
        font-size: 12px;
        color: #a0b0bf;
        font-family: 'DM Mono', monospace;
        padding: 2px 0 4px;
        margin-top: 2px;
    }

    /* ── Hide Streamlit default menu/footer ── */
    #MainMenu, footer { visibility: hidden; }
    </style>
    """,
        unsafe_allow_html=True,
    )


# ══════════════════════════════════════════════════════════════════════════════
# CHART HELPERS (ADR-042 — Option B: three-level priority chain)
# Priority: prompt keyword → Gemini annotation → DataFrame heuristic → bar
# ══════════════════════════════════════════════════════════════════════════════


def _keyword_hint(question: str) -> str | None:
    """
    Scan user question for explicit chart-type keywords (Priority 1).

    Priority order matches PROMPT_KEYWORDS dict order: pie, scatter, line,
    bar, table. First match wins — returns None if no keyword found.
    This is entirely frontend; never passed to the backend or Gemini.
    """
    q = question.lower()
    for chart_type, keywords in PROMPT_KEYWORDS.items():
        if any(kw in q for kw in keywords):
            return chart_type
    return None


def _heuristic(df: pd.DataFrame) -> str:
    """
    DataFrame shape heuristic — Priority 3 (last resort before default bar).

    Rules (applied in order):
    1. Two or more numeric cols + one non-numeric col:
       - If column names suggest an X/Y comparison (e.g. 'price_vs_volume',
         'spend' paired with 'uplift') → scatter.
       - Otherwise → bar (stacked bar rendered by render_bar when len(num)>=2).
    2. Exactly one numeric + one non-numeric col → check for temporal values
       → line chart; otherwise bar chart.
    3. All other shapes (all-numeric, all-categorical, etc.) → "table".

    Returns: "scatter" | "line" | "bar" | "table"
    """
    if df is None or df.empty:
        return "table"

    numeric_cols = df.select_dtypes(include="number").columns.tolist()
    non_numeric = [c for c in df.columns if c not in numeric_cols]

    # Two numeric dims + at least one label column
    if len(numeric_cols) >= 2 and len(non_numeric) >= 1:
        # Only treat as scatter when column names imply an X/Y axis comparison.
        # A pair like (baseline_volume, incremental_volume) is a stacked bar,
        # not a scatter — the values are measures of the same entity per row.
        scatter_tokens = ["price", "spend", "cost", "margin", "rate", "index",
                          "elasticity", "vs", "versus", "against", "correlation"]
        col_names_lower = " ".join(numeric_cols).lower()
        if any(t in col_names_lower for t in scatter_tokens):
            return "scatter"
        return "bar"  # stacked bar — render_bar handles len(num_cols) >= 2

    # One numeric + one non-numeric → bar or line
    if len(numeric_cols) == 1 and len(non_numeric) == 1:
        col_name = non_numeric[0].lower()
        sample = str(df[non_numeric[0]].iloc[0]).lower() if not df.empty else ""
        temporal_tokens = [
            "w1",
            "w2",
            "week",
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
            "20",
        ]
        if any(t in col_name or t in sample for t in temporal_tokens):
            return "line"
        return "bar"

    return "table"


def resolve_chart_type(
    question: str,
    suggested_chart_type: str,
    df: pd.DataFrame,
) -> str:
    """
    Resolve the final chart type using the ADR-042 three-level priority chain.

    Priority (highest to lowest):
    1. Prompt keyword — explicit user intent overrides everything.
    2. Gemini annotation — semantic understanding of query intent.
    3. DataFrame shape heuristic — structural fallback.
    4. Default: "bar" — never returns "table" unless keyword/annotation forced it.

    Returns one of: "bar" | "line" | "pie" | "scatter" | "table"
    """
    # P1: keyword override
    keyword = _keyword_hint(question)
    if keyword:
        return keyword

    # P2: Gemini annotation
    if suggested_chart_type and suggested_chart_type not in ("auto", ""):
        return suggested_chart_type

    # P3: heuristic
    h = _heuristic(df)
    if h != "table":
        return h

    # P4: default
    return "bar"


# ── Shared layout helpers ─────────────────────────────────────────────────────


def _base_layout() -> dict:
    """Base Plotly layout applied to all chart types."""
    return dict(
        paper_bgcolor="white",
        plot_bgcolor="white",
        margin=dict(t=28, b=8, l=8, r=8),
        font=dict(family="DM Sans, sans-serif", size=12, color="#1a2332"),
        xaxis=dict(
            showgrid=False,
            zeroline=False,
            showline=False,
            tickfont=dict(family="DM Mono, monospace", size=11, color="#7a8fa6"),
        ),
        yaxis=dict(
            showgrid=True,
            gridcolor=C["border"],
            zeroline=False,
            showline=False,
            tickfont=dict(family="DM Mono, monospace", size=11, color="#7a8fa6"),
        ),
    )


def _axis_label(df: pd.DataFrame) -> str:
    """Generate uppercase DM Mono axis label from the first numeric column name."""
    num_cols = df.select_dtypes(include="number").columns.tolist()
    if not num_cols:
        return ""
    return num_cols[0].replace("_", " ").upper()


def _format_axis_labels(df: pd.DataFrame) -> pd.DataFrame:
    """
    Format temporal dimension columns for display: Q→'Q2', W→'W12', month→'Jan'.
    Returns a copy — never mutates the original DataFrame.

    Matching rules (substring matching is intentionally avoided):
    - Quarter: col name IS 'quarter', or ends with '_quarter', or starts with 'quarter_'
      Excludes: 'quarterly_revenue', 'quarterly_growth_pct', 'q_on_q_growth', etc.
    - Week:    same boundary rule, plus col must be integer-typed
      Excludes: 'week_date', 'weekly_revenue', 'by_week', etc.
    - Month:   same boundary rule, integer-typed only
    """
    df = df.copy()
    for col in df.columns:
        col_l = col.lower()

        is_quarter_dim = (
            col_l == "quarter"
            or col_l.endswith("_quarter")
            or col_l.startswith("quarter_")
        )
        is_week_dim = (
            (col_l == "week_number" or col_l == "week"
             or col_l.endswith("_week") or col_l.startswith("week_"))
            and "date" not in col_l
            and df[col].dtype in ("int64", "int32", "float64")
        )
        is_month_dim = (
            col_l == "month"
            or col_l.endswith("_month")
            or col_l.startswith("month_")
        ) and df[col].dtype in ("int64", "int32", "float64")

        if is_quarter_dim and df[col].dtype in ("int64", "int32", "float64"):
            df[col] = df[col].apply(
                lambda v: f"Q{int(v)}" if pd.notna(v) else v
            )
        elif is_week_dim:
            df[col] = df[col].apply(
                lambda v: f"W{int(v)}" if pd.notna(v) else v
            )
        elif is_month_dim:
            df[col] = df[col].apply(
                lambda v: calendar.month_abbr[int(v)]
                if pd.notna(v) and 1 <= int(v) <= 12 else v
            )
    return df

# ── Chart render functions ────────────────────────────────────────────────────


def render_bar(df: pd.DataFrame) -> None:
    """
    Render a bar chart.

    Modes (auto-detected from DataFrame shape):
    - Stacked bar: one categorical col + two or more numeric cols.
      Each numeric col becomes a stacked segment (e.g. baseline + incremental).
      Horizontal orientation when average label length > 4 chars.
    - Simple bar:  one categorical col + exactly one numeric col.
      Bar colours cycle through BAR_COLORS.
      Horizontal orientation when average label length > 4 chars.

    Falls back to st.dataframe when no numeric or no categorical column found.
    """
    df = _format_axis_labels(df)

    # ── Reclassify integer year/quarter/week/month columns as categorical ──
    # Prevents year being treated as a numeric measure in stacked bar mode.
    temporal_dim_names = {"year", "quarter", "month", "week", "week_number"}
    for col in df.select_dtypes(include="number").columns:
        if col.lower() in temporal_dim_names:
            df[col] = df[col].astype(str)

    num_cols = df.select_dtypes(include="number").columns.tolist()
    cat_cols = df.select_dtypes(exclude="number").columns.tolist()
    if not num_cols or not cat_cols:
        st.dataframe(df, width='stretch', hide_index=True)
        return

    x_col = cat_cols[0]
    avg_label_len = df[x_col].astype(str).str.len().mean() if not df.empty else 0
    layout = _base_layout()

    if len(num_cols) >= 2:
        # ── Stacked bar (multiple measures per category) ───────────────────────
        # Typical case: sku × (total_volume, baseline_volume, incremental_volume)
        # or brand × (gross_revenue, net_revenue).
        # Use the first num_col as the primary label source for the axis header.
        label = num_cols[0].replace("_", " ").upper()
        if label:
            st.markdown(
                f'<p style="font-size:0.7rem;color:{C["text_muted"]};'
                f"font-family:'DM Mono',monospace;margin-bottom:0.4rem;"
                f'letter-spacing:0.05em;text-transform:uppercase">{label}</p>',
                unsafe_allow_html=True,
            )

        fig = go.Figure()
        horizontal = avg_label_len > 4
        for i, y_col in enumerate(num_cols):
            clean_name = y_col.replace("_", " ").title()
            if horizontal:
                fig.add_trace(go.Bar(
                    y=df[x_col],
                    x=df[y_col],
                    name=clean_name,
                    orientation="h",
                    marker=dict(color=BAR_COLORS[i % len(BAR_COLORS)], line=dict(width=0)),
                ))
            else:
                fig.add_trace(go.Bar(
                    x=df[x_col],
                    y=df[y_col],
                    name=clean_name,
                    marker=dict(color=BAR_COLORS[i % len(BAR_COLORS)], line=dict(width=0)),
                ))

        layout["barmode"] = "stack"
        layout["showlegend"] = True
        layout["legend"] = dict(
            font=dict(family="DM Sans, sans-serif", size=11),
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="left",
            x=0,
        )
        if horizontal:
            layout["height"] = max(200, 40 * len(df) + 80)
            layout["xaxis"]["showgrid"] = True
            layout["yaxis"]["showgrid"] = False
            layout["yaxis"]["autorange"] = "reversed"
        else:
            layout["height"] = 300
        fig.update_layout(**layout)
        st.plotly_chart(fig, width='stretch')

    else:
        # ── Simple or grouped bar (one measure) ───────────────────────────────
        y_col = num_cols[0]
        label = y_col.replace("_", " ").upper()
        if label:
            st.markdown(
                f'<p style="font-size:0.7rem;color:{C["text_muted"]};'
                f"font-family:'DM Mono',monospace;margin-bottom:0.4rem;"
                f'letter-spacing:0.05em;text-transform:uppercase">{label}</p>',
                unsafe_allow_html=True,
            )

        horizontal = avg_label_len > 4

        # If a second categorical col exists, use it as a colour/group dimension
        color_col = cat_cols[1] if len(cat_cols) >= 2 else None

        if horizontal:
            fig = px.bar(
                df, y=x_col, x=y_col,
                color=color_col,
                orientation="h",
                barmode="group",
                color_discrete_sequence=BAR_COLORS,
            )
            layout["xaxis"]["title"] = None
            layout["yaxis"]["title"] = None
        else:
            fig = px.bar(
                df, x=x_col, y=y_col,
                color=color_col,
                barmode="group",
                color_discrete_sequence=BAR_COLORS,
            )
            layout["xaxis"]["title"] = None
            layout["yaxis"]["title"] = None

        fig.update_layout(**layout)
        st.plotly_chart(fig, width='stretch')


def render_line(df: pd.DataFrame) -> None:
    # Preserve original sort order before formatting changes dtypes
    df = df.copy()

    # ── Temporal column detection ─────────────────────────────────────────────
    # Priority: more granular periods preferred as x-axis.
    # date=0 (finest) … year=4 (coarsest).
    # Columns with ≤1 unique value (e.g. year=2025 throughout) are skipped.
    #
    # IMPORTANT: use strict word-boundary matching, NOT substring.
    # "quarterly_net_revenue_gbp" contains "quarter" as a substring but is
    # a metric, not a temporal dimension.  Boundary rules:
    #   exact  → col_l == token
    #   suffix → col_l.endswith("_quarter")  e.g. fiscal_quarter
    #   prefix → col_l.startswith("quarter_") e.g. quarter_id
    # This mirrors the rule in _format_axis_labels().
    _TEMPORAL_PRIORITY = {
        "date": 0, "week": 1, "month": 2,
        "quarter": 3, "period": 3, "year": 4,
    }

    def _is_temporal_dim(col_l: str, token: str) -> bool:
        return (
            col_l == token
            or col_l.endswith(f"_{token}")
            or col_l.startswith(f"{token}_")
        )

    _all_temporal_cols: set[str] = set()
    temporal_col: str | None = None
    best_priority = 999

    for col in df.columns:
        col_l = col.lower()
        for token, priority in _TEMPORAL_PRIORITY.items():
            if _is_temporal_dim(col_l, token):
                _all_temporal_cols.add(col)
                if df[col].nunique() > 1 and priority < best_priority:
                    best_priority = priority
                    temporal_col = col
                break  # one token match per column is enough

    # ── Sort key: capture numeric order BEFORE label formatting ──────────────
    sort_key = "_sort_key"
    if temporal_col and df[temporal_col].dtype in ("int64", "int32", "float64"):
        df[sort_key] = df[temporal_col]
    else:
        df[sort_key] = range(len(df))

    # ── Format temporal labels (quarter→Q2, month→Jan, week→W12) ─────────────
    df = _format_axis_labels(df)

    num_cols = [c for c in df.select_dtypes(include="number").columns if c != sort_key]
    cat_cols = df.select_dtypes(exclude="number").columns.tolist()

    if not num_cols:
        st.dataframe(df.drop(columns=[sort_key], errors="ignore"),
                     width="stretch", hide_index=True)
        return

    # All-numeric df with no temporal or categorical dimension: no meaningful
    # x-axis for a line chart (plotting price vs volume is a scatter concern).
    # Fall back to table rather than producing a semantically meaningless chart.
    if temporal_col is None and not cat_cols:
        st.dataframe(df.drop(columns=[sort_key], errors="ignore"),
                     width="stretch", hide_index=True)
        return

    x_col = temporal_col or (cat_cols[0] if cat_cols else df.columns[0])

    # Exclude temporal dimensions from y_candidates — they are axis labels,
    # not measures.  e.g. 'year' (int 2025) must not become the y-axis.
    y_candidates = [
        c for c in num_cols
        if c != x_col and c not in _all_temporal_cols
    ]
    if not y_candidates:
        # Relaxed fallback: accept any non-x numeric, but sort temporal cols
        # to the END so a genuine measure is still preferred over a time dim.
        y_candidates = sorted(
            [c for c in num_cols if c != x_col],
            key=lambda c: (1 if c in _all_temporal_cols else 0),
        )
    if not y_candidates:
        st.dataframe(df.drop(columns=[sort_key], errors="ignore"),
                     width="stretch", hide_index=True)
        return

    y_col = y_candidates[0]
    series_col = next((c for c in cat_cols if c != x_col), None)

    # Axis label (above chart) — derived from y column name
    label = y_col.replace("_", " ").upper() if y_col else ""
    if label:
        st.markdown(
            f'<p style="font-size:0.7rem;color:{C["text_muted"]};'
            f"font-family:'DM Mono',monospace;margin-bottom:0.4rem;"
            f'letter-spacing:0.05em;text-transform:uppercase">{label}</p>',
            unsafe_allow_html=True,
        )

    # Build traces — sort by numeric sort_key to preserve correct period order
    fig = go.Figure()
    if series_col:
        for i, (name, grp) in enumerate(df.groupby(series_col, sort=False)):
            grp = grp.sort_values(sort_key)
            fig.add_trace(go.Scatter(
                x=grp[x_col], y=grp[y_col],
                mode="lines+markers", name=str(name),
                line=dict(color=BAR_COLORS[i % len(BAR_COLORS)], width=2.5),
                marker=dict(size=7, line=dict(width=0)),
            ))
    else:
        df_sorted = df.sort_values(sort_key)
        fig.add_trace(go.Scatter(
            x=df_sorted[x_col], y=df_sorted[y_col],
            mode="lines+markers",
            line=dict(color=C["teal"], width=2.5),
            marker=dict(color=C["teal"], size=7, line=dict(width=0)),
        ))

    layout = _base_layout()
    layout["height"] = 280
    layout["xaxis"]["showgrid"] = False
    layout["yaxis"]["showgrid"] = True
    layout["showlegend"] = series_col is not None
    fig.update_layout(**layout)

    # Force categorical axis only when x was originally numeric (e.g. quarter int)
    if temporal_col and pd.api.types.is_numeric_dtype(df[sort_key]):
        fig.update_xaxes(type="category")

    # Drop internal sort key before any fallback dataframe render
    df.drop(columns=[sort_key], inplace=True, errors="ignore")
    st.plotly_chart(fig, width="stretch")


def render_pie(df: pd.DataFrame) -> None:
    """
    Render a donut/pie chart (hole=0.42).
    First non-numeric col = labels; first numeric col = values.
    Colours cycle through BAR_COLORS; legend shown.
    """
    cat_cols = df.select_dtypes(exclude="number").columns.tolist()
    num_cols = df.select_dtypes(include="number").columns.tolist()
    if not cat_cols or not num_cols:
        # No label column — reshape: use column names as labels, row 0 as values
        if num_cols and len(df) == 1:
            reshaped = pd.DataFrame({
                "metric": num_cols,
                "value":  df[num_cols].iloc[0].values,
            })
            cat_cols = ["metric"]
            num_cols = ["value"]
            df = reshaped
        else:
            st.dataframe(df, width='stretch', hide_index=True)
            return

    label_col, value_col = cat_cols[0], num_cols[0]
    fig = go.Figure(
        data=[
            go.Pie(
                labels=df[label_col],
                values=df[value_col],
                hole=0.42,
                marker=dict(colors=BAR_COLORS),
                textfont=dict(family="DM Sans, sans-serif", size=12),
                hovertemplate="%{label}: %{value} (%{percent})<extra></extra>",
            )
        ]
    )
    fig.update_layout(
        paper_bgcolor="white",
        margin=dict(t=20, b=20, l=20, r=20),
        font=dict(family="DM Sans, sans-serif", size=12, color="#1a2332"),
        legend=dict(font=dict(family="DM Sans, sans-serif", size=12)),
        showlegend=True,
    )
    st.plotly_chart(fig, width='stretch')


def render_scatter(df: pd.DataFrame) -> None:
    """
    Render a scatter plot.
    First two numeric cols = x/y axes.
    First non-numeric col (if present) = point label and colour.
    """
    num_cols = df.select_dtypes(include="number").columns.tolist()
    cat_cols = df.select_dtypes(exclude="number").columns.tolist()
    if len(num_cols) < 2:
        st.dataframe(df, width='stretch', hide_index=True)
        return

    x_col, y_col = num_cols[0], num_cols[1]
    label_col = cat_cols[0] if cat_cols else None

    fig = px.scatter(
        df,
        x=x_col,
        y=y_col,
        text=label_col,
        color=label_col if label_col else None,
        color_discrete_sequence=BAR_COLORS,
    )
    fig.update_traces(
        marker=dict(size=10, opacity=0.82),
        textposition="top center",
        textfont=dict(family="DM Sans, sans-serif", size=11, color="#1a2332"),
    )
    layout = _base_layout()
    layout["showlegend"] = label_col is not None
    fig.update_layout(**layout)
    st.plotly_chart(fig, width='stretch')


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
        " as a pie chart",
        " as a scatter plot",
        " as a scatter",
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
        "as a pie chart",
        "as a donut chart",
        "as a scatter",
        "as a scatter plot",
        "as a table",
        "as a chart",
        "as a graph",
        "line chart",
        "bar chart",
        "pie chart",
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
    No custom HTML rendered here.
    The native Streamlit header provides the dark bar and hamburger button,
    styled via CSS. Project Insight branding lives in the sidebar header,
    consistent with the pattern used by Claude.ai and ChatGPT.
    New Chat is the primary button at the top of the sidebar.
    """
    pass


# ══════════════════════════════════════════════════════════════════════════════
# SIDEBAR — past sessions
# ══════════════════════════════════════════════════════════════════════════════


def _render_sidebar() -> None:
    """
    Sidebar: LLM Toggle · Branding · New Chat button · past sessions · Clear Log footer.
    Active session highlighted with teal left border.
    """
    with st.sidebar:

        # ── LLM Mode toggle (placeholder — data governance feature) ───────────
        mode = st.session_state.get("llm_mode", "cloud")
        col_cloud, col_local = st.columns(2)
        with col_cloud:
            if st.button(
                "☁ Cloud",
                key="llm_cloud_btn",
                use_container_width=True,
                type="primary" if mode == "cloud" else "secondary",
            ):
                st.session_state.llm_mode = "cloud"
                st.rerun()
        with col_local:
            if st.button(
                "🔒 Local",
                key="llm_local_btn",
                use_container_width=True,
                type="primary" if mode == "local" else "secondary",
            ):
                st.session_state.llm_mode = "local"
                st.rerun()

        if mode == "local":
            st.markdown(
                f"""<div style="
                    background:{C["amber_bg"]};border:1px solid {C["amber_border"]};
                    border-radius:6px;padding:0.4rem 0.75rem;margin-bottom:0.5rem;
                    font-size:0.72rem;color:{C["amber"]};font-family:'DM Mono',monospace;
                ">⚠ Local mode — not active in this prototype</div>""",
                unsafe_allow_html=True,
            )
        st.markdown(
            '<hr style="border:none;border-top:1px solid #e8edf2;margin:0.5rem 0 0.75rem"/>',
            unsafe_allow_html=True,
        )

        # ── Branding ──────────────────────────────────────────────────────────
        st.markdown(
            """<div style="display:flex;align-items:center;gap:0.6rem;
            padding:0.4rem 0 0.75rem;border-bottom:1px solid #e8edf2;margin-bottom:0.75rem">
            <svg width="24" height="24" viewBox="0 0 28 28" fill="none" aria-hidden="true">
                <rect x="2"  y="16" width="5" height="10" rx="1.5" fill="#2ca58d" opacity="0.5"/>
                <rect x="10" y="9"  width="5" height="17" rx="1.5" fill="#2ca58d" opacity="0.75"/>
                <rect x="18" y="3"  width="5" height="23" rx="1.5" fill="#2ca58d"/>
                <circle cx="7" cy="9" r="5" fill="white" stroke="#2ca58d" stroke-width="1.5"/>
                <path d="M5 9h4M7 7v4" stroke="#2ca58d" stroke-width="1.5" stroke-linecap="round"/>
            </svg>
            <div>
                <div style="font-weight:600;font-size:0.88rem;color:#1a2332;
                            font-family:'DM Sans',sans-serif;line-height:1.2">Project Insight</div>
            </div>
            </div>""",
            unsafe_allow_html=True,
        )

        # ── New Chat — primary action ──────────────────────────────────────────
        if st.button("＋ New Chat", key="new_chat_sidebar",
                     use_container_width=True, type="primary"):
            _start_new_session()

        st.markdown(
            '<hr style="border:none;border-top:1px solid #e8edf2;margin:0.75rem 0 0.6rem"/>',
            unsafe_allow_html=True,
        )

        # ── Past sessions ─────────────────────────────────────────────────────
        st.markdown(
            "<p style=\"font-family:'DM Sans',sans-serif;font-weight:600;"
            "font-size:0.82rem;color:#7a8fa6;margin:0 0 0.5rem;letter-spacing:0.04em\">"
            "PAST SESSIONS</p>",
            unsafe_allow_html=True,
        )

        sessions = load_past_sessions()

        if not sessions:
            st.markdown(
                '<p style="font-size:0.78rem;color:#7a8fa6;'
                "font-family:'DM Mono',monospace;margin:0\">No past sessions yet.</p>",
                unsafe_allow_html=True,
            )
        else:
            active_sid = st.session_state.session_id
            for s in sessions:
                is_active = s["id"] == active_sid
                label = f"{s['date']} · Q{s['q_count']} · {s['preview'][:38]}…"
                if is_active:
                    st.markdown(
                        f"""<div style="
                            border-left:3px solid {C["teal_dark"]};
                            background:{C["teal_muted"]};
                            border-radius:0 6px 6px 0;
                            padding:0.45rem 0.75rem;
                            font-size:0.8rem;
                            color:{C["teal_dark"]};
                            font-family:'DM Sans',sans-serif;
                            margin-bottom:4px;
                            cursor:default;
                            line-height:1.4;
                        ">{label}</div>""",
                        unsafe_allow_html=True,
                    )
                else:
                    if st.button(label, key=f"session_{s['id']}",
                                 use_container_width=True):
                        _load_session(s["id"])

        # ── Footer: Clear Log ─────────────────────────────────────────────────
        st.markdown(
            '<div style="border-top:1px solid #e8edf2;margin-top:1.25rem;'
            'padding-top:0.75rem">',
            unsafe_allow_html=True,
        )
        if st.button("🗑 Clear log", key="clear_log_btn",
                     use_container_width=True):
            import os
            if os.path.exists("logs/interactions.jsonl"):
                os.remove("logs/interactions.jsonl")
            _start_new_session()

        st.markdown(
            '<p style="font-size:0.7rem;color:#a0b0bf;'
            "font-family:'DM Mono',monospace;margin-top:0.5rem;text-align:center\">"
            "Session History · Read-only</p></div>",
            unsafe_allow_html=True,
        )


# ══════════════════════════════════════════════════════════════════════════════
# BANNERS — context window warning + resumed session
# ══════════════════════════════════════════════════════════════════════════════


def _render_banners() -> None:
    """
    Render zero, one, or two banners at the top of the thread:
    Amber context window notice (if any turn has history_truncated=True)
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

def _render_restore_bar() -> None:
    """
    Resumed session banner (three states: pending / running / complete)
    """
    if st.session_state.resumed_from is None:
        return

    resumed_date = st.session_state.resumed_from
    turns_raw = st.session_state.turns_raw
    n_total = len(turns_raw)
    n_restored = len(st.session_state.turns)

    if st.session_state.restore_running and not st.session_state.restore_complete:
        st.markdown(
            f"""
            <div style="
                background:{C["teal_muted"]};border:1px solid {C["teal"]};
                border-radius:8px;padding:0.6rem 1rem;margin-bottom:1.25rem;
                font-size:0.82rem;color:{C["teal_dark"]};font-family:'DM Sans',sans-serif;
                display:flex;align-items:center;gap:0.6rem;flex-wrap:wrap;
            ">
                <span>↺ Restoring session… please wait</span>
                <span style="margin-left:auto;font-size:0.78rem;
                            font-family:'DM Mono',monospace;color:{C["text_muted"]}">
                    ← use sidebar for new session
                </span>
            </div>
            """,
            unsafe_allow_html=True,
        )

    elif st.session_state.restore_complete:
        return
    
    else:
        # State 1 — pending
        col_msg, col_restore = st.columns([7, 2])
        with col_msg:
            st.markdown(
                f"""
                <div style="
                    background:{C["teal_muted"]};border:1px solid {C["teal"]};
                    border-radius:8px;padding:0.6rem 1rem;margin-bottom:0;
                    font-size:0.82rem;color:{C["teal_dark"]};font-family:'DM Sans',sans-serif;
                ">
                    ↩ Resumed · {resumed_date} — SQL loaded.
                    Restore to view charts &amp; narrative.
                </div>
                """,
                unsafe_allow_html=True,
            )
        with col_restore:
            if st.button("↺ Restore", key="restore_btn", type="primary"):
                st.session_state.restore_running = True
                st.rerun()
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
            <p style="font-size:1.25rem;font-family:'DM Sans',sans-serif;color:#7a8fa6;margin:0 0 0.4rem">
                Project Insight
            </p>
            <p style="font-size:0.9rem;font-family:'DM Mono',monospace;color:#a0b0bf;margin:0 0 2rem">
                Conversational BI powered by Streamlit · Gemini 2.5 Flash · DuckDB
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
        Chart data not loaded — click ↺ Restore below.
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
        1. Check prompt keyword override first (_keyword_hint)
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
        suggested = result.get("suggested_chart_type", "auto")
        resolved = resolve_chart_type(result.get("user_question", ""), suggested, df)

        # Build toggle: primary label (resolved type) + secondary (Table or Chart)
        if resolved == "table":
            toggle_opts = ["Table", "Bar chart"]
        else:
            toggle_opts = [CHART_LABELS.get(resolved, "Chart"), "Table"]

        # Apply saved per-turn preference
        pref = st.session_state.view_prefs.get(turn_index)
        index_default = 0
        if pref == "table" and "Table" in toggle_opts:
            index_default = toggle_opts.index("Table")
        elif pref == "chart":
            index_default = 0

        view = st.radio(
            "Chart view",  # non-empty label
            toggle_opts,
            horizontal=True,
            index=index_default,
            key=f"view_{turn_index}",
            label_visibility="collapsed",  # hides the label correctly
        )

        # Persist preference
        st.session_state.view_prefs[turn_index] = (
            "table" if view == "Table" else "chart"
        )

        # Determine actual render type (handles "table" resolved + user switched to chart)
        if view == "Table":
            render_type = "table"
        elif resolved in ("bar", "line", "pie", "scatter"):
            render_type = resolved
        else:
            render_type = "bar"  # resolved=="table" but user picked the chart option

        # Dispatch to render function
        if df.empty:
            st.info("No data found for this query — try broadening the filters or rephrasing.")
        elif render_type == "table":
            st.dataframe(df, width='stretch', hide_index=True)
        elif render_type == "pie":
            render_pie(df)
        elif render_type == "scatter":
            render_scatter(df)
        elif render_type == "line":
            render_line(df)
        else:
            render_bar(df)

        # Record what was actually shown — picked up by log_turn() in handle_question()
        result["rendered_chart_type"] = render_type

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
    """Clear all session state and start a fresh session."""
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
        "_confirm_new",
        "_confirm_clear",
        "pending_question",
        "llm_mode"
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
    result = run_turn(
        past_turn["user_query"],
        st.session_state.history,
        st.session_state.conn,
    )

    st.session_state.history = result["conversation_history"]

    if result["status"] == "success":
        result["_timestamp"] = past_turn.get("timestamp", "")[:10]
        result["_resumed_turn"] = n_restored == 0  # first restored turn gets divider
        # Correct the turn_index so turn_id in the log continues from prior turns
        result["turn_index"] = n_restored
        st.session_state.turns.append(result)
        try:
            log_turn(
                result,
                session_id=st.session_state.session_id,
                rendered_chart_type=result.get("rendered_chart_type", "auto"),
                resumed=True,
                resumed_at=datetime.now().isoformat(),
            )
        except LogWriteError:
            st.toast("Log write failed — turn not recorded.", icon="⚠️")

    # Trigger next step
    st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# QUESTION HANDLER
# ══════════════════════════════════════════════════════════════════════════════


def _resolve_rendered_chart_type(result: dict) -> str:
    """
    Resolve the chart type that will be rendered for this result, using the
    same priority chain as _render_response_card(), without rendering anything.
    Used by handle_question() to capture rendered_chart_type before log_turn().
    """
    df = result.get("data")
    if df is None or df.empty:
        return "none"
    suggested = result.get("suggested_chart_type", "auto")
    return resolve_chart_type(result.get("user_question", ""), suggested, df)


def handle_question(question: str) -> None:
    """
    Stage 1 of 2: store question in pending_question and rerun immediately.
    This causes main() to render the user bubble before the LLM call starts,
    so the user sees their question echoed back instantly on pressing Enter.
    The actual run_turn() call happens in _execute_pending_question(), which
    main() calls on the next rerun when pending_question is set.
    """
    st.session_state.pending_question = question
    st.rerun()


def _execute_pending_question() -> None:
    """
    Stage 2 of 2: called by main() when pending_question is set.
    Runs run_turn(), clears pending state, logs, and reruns to show the
    response card. The user bubble was already rendered in this rerun by
    main() before this function is called.
    """
    question = st.session_state.pending_question
    conn = st.session_state.conn

    with st.spinner("Analysing…"):
        result = run_turn(question, st.session_state.history, conn)

    # Clear pending immediately — whether success or error
    st.session_state.pending_question = None

    # Always assign history back — failed turns return unchanged history
    st.session_state.history = result["conversation_history"]

    if result["status"] == "error":
        stage = result.get("error_stage", "unknown")
        if stage == "nl2sql":
            st.toast(
                "⚠ Could not generate a query for that question. "
                "Please try rephrasing.",
                icon="🚫",
            )
        elif stage == "execution":
            st.toast(
                "⚠ The query failed to execute after retries. "
                "Please try a simpler question.",
                icon="🚫",
            )
        else:
            st.toast(f"⚠ An error occurred ({stage}). Please try again.", icon="🚫")

        # Log error turn — success_flag=False, rendered_chart_type="none"
        try:
            log_turn(
                result,
                session_id=st.session_state.session_id,
                rendered_chart_type="none",
            )
        except LogWriteError:
            pass  # non-fatal; don't surface a second warning on error path

    else:
        # Resolve rendered_chart_type now so the log entry is accurate
        rendered_ct = _resolve_rendered_chart_type(result)
        result["rendered_chart_type"] = rendered_ct

        st.session_state.turns.append(result)

        try:
            log_turn(
                result,
                session_id=st.session_state.session_id,
                rendered_chart_type=rendered_ct,
            )
        except LogWriteError:
            st.toast("Log write failed — turn not recorded.", icon="⚠️")

    st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# FOOTER
# ══════════════════════════════════════════════════════════════════════════════


def _render_footer() -> None:
    is_resumed = st.session_state.resumed_from is not None

    if is_resumed and not st.session_state.restore_complete:
        return  # ← ADD THIS: silent before restore completes

    if is_resumed and st.session_state.restore_complete:
        date = st.session_state.resumed_from
        n = len(st.session_state.turns)
        footer_text = f"Continuing session from {date} · {n} question{'s' if n != 1 else ''} in history"
    else:
        footer_text = "Enter to send · Shift+Enter for new line"

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
            # Divider: between last restored turn and first new question
            if (
                resumed_date
                and st.session_state.restore_complete
                and not result.get("_resumed_turn", False)
                and not first_resumed_done
            ):
                _render_resumed_divider(resumed_date)
                first_resumed_done = True

            _render_user_bubble(result["user_question"])
            _render_response_card(result)

    # ── Pending question: render bubble immediately, then execute ─────────────
    # When handle_question() stores a question and reruns, we arrive here with
    # pending_question set. Render the bubble first so it's visible, then call
    # _execute_pending_question() which blocks on run_turn() and reruns again
    # to show the completed response card.
    if st.session_state.pending_question:
        _render_user_bubble(st.session_state.pending_question)
        _execute_pending_question()
        return  # _execute_pending_question always reruns; nothing below executes
    
    # ── Restore bar (resumed sessions only) ──────────────────────────────
    _render_restore_bar()

    # ── Restore step (one question per rerun, State 2) ────────────────────────
    if st.session_state.restore_running and not st.session_state.restore_complete:
        _run_restore_step()
        return  # _run_restore_step() always calls st.rerun()

    # ── Input bar ────────────────────────────────────────────────────────
    input_disabled = (
        st.session_state.resumed_from is not None
        and not st.session_state.restore_complete
    )

    placeholder = (
        "Click ↺ Restore to continue this session…"
        if input_disabled
        else 'Ask a question — e.g. "2025 quarterly revenue trend of top 5 brands as a line chart"'
    )

    if question := st.chat_input(placeholder, disabled=input_disabled):
        handle_question(question)

    _render_footer()

if __name__ == "__main__":
    main()
