"""
eda_viz.py
----------
AM1 Sprint 1 / F-03 — EDA Visualisation Script

Generates 8 report-quality Plotly Express plots documenting all deliberate
quality issues injected by inject_quality_issues.py.  Reads from data/raw/
(clean baseline) and data/raw/qi-injected/ (dirty layer) so it can run at any
point in the pipeline without depending on preprocess.py having been run first.

Plots generated
---------------
    01_casing_cardinality.png        — QI-01/02: unique pack_type & variant values before vs after
    02_data_quality_overview.png     — All quality issues: NULL/zero rates across tables
    03_volume_deviation_hist.png     — QI-04: volume deviation from expected with IQR outer fence
    04_volume_outlier_scatter.png    — QI-04: baseline_volume vs volume_units, outliers highlighted
    05_null_mechanic.png             — QI-05: promotion mechanic distribution including NULL
    06_temporal_gap_heatmap.png      — QI-08: missing weeks per banner × brand pair
    07_weekly_volume_trends.png      — Weekly brand volume trends: NitroBoost growth, ValuMart decline, seasonal dip
    08_price_index_by_tier.png       — Derived price_index distribution by price tier

Output directory
----------------
    data/eda_plots/   (created if absent)

Dependencies
------------
    pip install plotly kaleido
    All other dependencies already in project venv (pandas, numpy, pyarrow)

    kaleido is required for write_image() PNG export.
    Verify with: python -c "import kaleido; print(kaleido.__version__)"

Execution
---------
    python scripts/eda_viz.py    # from project root
    python eda_viz.py            # from scripts/ directory

IQR fence
---------
    IQR_MULTIPLIER = 3.0 (Tukey outer fence) — must match preprocess.py exactly
    so the fence annotation in plot 03 is consistent with what preprocess.py flags.
"""

import os

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

# ──────────────────────────────────────────────────────────────────────────────
# PATHS
# ──────────────────────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RAW_DIR = os.path.join(BASE_DIR, "..", "data", "raw")
DIRTY_DIR = os.path.join(BASE_DIR, "..", "data", "raw", "qi-injected")
PLOTS_DIR = os.path.join(BASE_DIR, "..", "data", "eda_plots")
os.makedirs(PLOTS_DIR, exist_ok=True)

# ──────────────────────────────────────────────────────────────────────────────
# CONSTANTS
# ──────────────────────────────────────────────────────────────────────────────
IQR_MULTIPLIER = 3.0  # Tukey outer fence — must match preprocess.py
SAMPLE_HIST = 500_000  # rows sampled for histogram (performance)
SAMPLE_SCATTER = 30_000  # normal rows sampled for scatter (readability)

# Plot dimensions (px)
PLOT_W = 1200
PLOT_H = 650

# ──────────────────────────────────────────────────────────────────────────────
# COLOUR PALETTE  — consistent across all 8 plots
# ──────────────────────────────────────────────────────────────────────────────
C_CLEAN = "#1565C0"  # dark blue    — clean / raw baseline
C_DIRTY = "#BF360C"  # dark red     — injected / corrupted values
C_FLAG = "#E65100"  # deep orange  — flagged rows
C_OK = "#2E7D32"  # dark green   — valid / passing
C_NEUTRAL = "#455A64"  # blue-grey    — reference / neutral
C_NULL = "#7B1FA2"  # purple       — NULL values
C_ACCENT = "#00838F"  # teal         — accent / derived

TEMPLATE = "plotly_white"

# ──────────────────────────────────────────────────────────────────────────────
# HELPERS
# ──────────────────────────────────────────────────────────────────────────────


def _save(fig: go.Figure, filename: str, height: int = PLOT_H) -> None:
    """
    Saves figure as PNG to PLOTS_DIR and prints confirmation.

    Args:
        fig      : Plotly figure object.
        filename : Output filename (written to PLOTS_DIR).
        height   : Override figure height in px.  Defaults to PLOT_H (650).
                   Pass a larger value for multi-panel plots (e.g. 900 for
                   plot 07 which has 3 subplot rows).
    """
    path = os.path.join(PLOTS_DIR, filename)
    fig.write_image(path, width=PLOT_W, height=height, scale=2)
    print(f"  ✓  {filename}")


def _load_parquet(directory: str, name: str) -> pd.DataFrame:
    return pd.read_parquet(os.path.join(directory, f"{name}.parquet"))


def _wrap_annotation(text: str, width: int = 95) -> str:
    """
    Inserts Plotly <br> tags at word boundaries so annotation text wraps
    within the figure frame rather than overflowing horizontally.

    Args:
        text  : Full annotation string (spaces as word separators).
        width : Max characters per line before inserting a break.
                95 chars fits comfortably at font size 11 in a 1200px figure.

    Returns:
        str with <br> inserted at word boundaries.
    """
    words = text.split(" ")
    lines = []
    current = ""
    for word in words:
        if len(current) + len(word) + 1 <= width:
            current = f"{current} {word}".strip()
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return "<br>".join(lines)


# ==============================================================================
# PLOT 01 — QI-01/02: Casing cardinality before vs after injection
# ==============================================================================


def plot_casing_cardinality(dp_raw: pd.DataFrame, dp_dirty: pd.DataFrame) -> None:
    """
    Grouped bar chart: unique value counts for pack_type and variant in the
    raw (clean) layer vs the QI-injected (dirty) layer.

    The cardinality explosion — from canonical counts to corrupted-form counts —
    is the core EDA signal for QI-01 and QI-02.  Without normalisation, any
    GROUP BY on pack_type or variant would silently split identical physical
    values across multiple rows.
    """
    records = [
        {
            "Dimension": "pack_type",
            "Layer": "Raw (clean)",
            "Unique Values": dp_raw["pack_type"].nunique(),
        },
        {
            "Dimension": "pack_type",
            "Layer": "QI-Injected",
            "Unique Values": dp_dirty["pack_type"].nunique(),
        },
        {
            "Dimension": "variant",
            "Layer": "Raw (clean)",
            "Unique Values": dp_raw["variant"].nunique(),
        },
        {
            "Dimension": "variant",
            "Layer": "QI-Injected",
            "Unique Values": dp_dirty["variant"].nunique(),
        },
    ]
    df_plot = pd.DataFrame(records)

    fig = px.bar(
        df_plot,
        x="Dimension",
        y="Unique Values",
        color="Layer",
        barmode="group",
        color_discrete_map={"Raw (clean)": C_OK, "QI-Injected": C_DIRTY},
        text="Unique Values",
        title="QI-01/02 — Casing Corruption: Unique Value Cardinality Before vs After Injection",
        labels={
            "Unique Values": "Distinct Values in Column",
            "Dimension": "dim_product Column",
        },
        template=TEMPLATE,
    )
    fig.update_traces(textposition="outside", textfont_size=14)
    fig.update_layout(
        legend_title_text="Data Layer",
        font=dict(size=13),
        title_font_size=15,
        yaxis=dict(range=[0, df_plot["Unique Values"].max() * 1.25]),
        annotations=[
            dict(
                x=0.5,
                y=-0.14,
                xref="paper",
                yref="paper",
                showarrow=False,
                text=(
                    _wrap_annotation(
                        "Corruption introduces lowercase, abbreviation and mixed-case forms — each appearing as a "
                        "distinct value in GROUP BY queries without normalisation."
                    )
                ),
                font=dict(size=11, color=C_NEUTRAL),
            )
        ],
        margin=dict(b=130),
    )

    _save(fig, "01_casing_cardinality.png")


# ==============================================================================
# PLOT 02 — Data quality overview: all NULL / zero rates
# ==============================================================================


def plot_quality_overview(
    dc_dirty: pd.DataFrame,
    fs_dirty: pd.DataFrame,
    fm_dirty: pd.DataFrame,
) -> None:
    """
    Horizontal bar chart summarising every deliberate quality issue rate
    across all three tables.  Provides a single-slide view for the assessor
    presentation before diving into individual issue plots.
    """
    promo_rows = fs_dirty[fs_dirty["is_promoted"] == True]
    null_mech_r = promo_rows["promotion_mechanic"].isna().mean()
    zero_price_r = (fs_dirty["sku_net_price_gbp"] == 0).mean()

    outlier_dev = (
        fs_dirty["volume_units"]
        - fs_dirty["baseline_volume"]
        - fs_dirty["incremental_volume"]
    )
    q1 = outlier_dev.quantile(0.25)
    q3 = outlier_dev.quantile(0.75)
    iqr = q3 - q1
    fence = q3 + IQR_MULTIPLIER * iqr
    outlier_r = (outlier_dev > fence).mean()

    non_ecomm = dc_dirty[dc_dirty["channel"] != "eCommerce"]
    null_territory_r = dc_dirty["territory"].isna().mean()
    null_store_r = non_ecomm["store_count"].isna().mean()

    zero_shelf_r = (fm_dirty["avg_shelf_price_gbp"] == 0).mean()
    vol_viol_r = (
        fm_dirty["brand_volume_units"] > fm_dirty["total_category_volume_units"]
    ).mean()

    records = [
        # dim_customer
        {
            "Issue": "NULL territory (dim_customer)",
            "Rate %": round(null_territory_r * 100, 1),
            "Table": "dim_customer",
            "QI": "Raw",
        },
        {
            "Issue": "NULL store_count — non-eComm (dim_customer)",
            "Rate %": round(null_store_r * 100, 1),
            "Table": "dim_customer",
            "QI": "Raw",
        },
        # fact_sales
        {
            "Issue": "Zero sku_net_price_gbp (QI-03)",
            "Rate %": round(zero_price_r * 100, 1),
            "Table": "fact_sales",
            "QI": "QI-03",
        },
        {
            "Issue": "Volume outliers — Tukey 3× (QI-04)",
            "Rate %": round(outlier_r * 100, 2),
            "Table": "fact_sales",
            "QI": "QI-04",
        },
        {
            "Issue": "NULL mechanic on promoted rows (QI-05)",
            "Rate %": round(null_mech_r * 100, 1),
            "Table": "fact_sales",
            "QI": "QI-05",
        },
        # fact_market
        {
            "Issue": "Zero avg_shelf_price_gbp (QI-06)",
            "Rate %": round(zero_shelf_r * 100, 1),
            "Table": "fact_market",
            "QI": "QI-06",
        },
        {
            "Issue": "brand_vol > cat_vol (QI-07)",
            "Rate %": round(vol_viol_r * 100, 1),
            "Table": "fact_market",
            "QI": "QI-07",
        },
    ]
    df_plot = pd.DataFrame(records).sort_values("Rate %", ascending=True)

    colour_map = {
        "dim_customer": C_NEUTRAL,
        "fact_sales": C_FLAG,
        "fact_market": C_DIRTY,
    }

    fig = px.bar(
        df_plot,
        x="Rate %",
        y="Issue",
        color="Table",
        orientation="h",
        color_discrete_map=colour_map,
        text="Rate %",
        title="Data Quality Overview — NULL / Zero Injection Rates Across All Tables",
        labels={"Rate %": "Affected Rows (%)", "Issue": ""},
        template=TEMPLATE,
    )
    fig.update_traces(
        texttemplate="%{x:.1f}%",
        textposition="outside",
        textfont_size=12,
    )
    fig.update_layout(
        font=dict(size=12),
        title_font_size=15,
        xaxis=dict(range=[0, df_plot["Rate %"].max() * 1.35], ticksuffix="%"),
        legend_title_text="Source Table",
        margin=dict(l=340, b=130),
    )

    _save(fig, "02_data_quality_overview.png")


# ==============================================================================
# PLOT 03 — QI-04: Volume deviation histogram with IQR outer fence
# ==============================================================================


def plot_volume_deviation_hist(fs_dirty: pd.DataFrame) -> None:
    """
    Histogram of (volume_units − baseline_volume − incremental_volume).

    For clean rows this deviation is exactly 0 by construction.
    For QI-04 injected outlier rows, volume_units was overwritten to
    5–10× baseline while baseline + incremental were left unchanged,
    producing a large positive deviation.

    The vertical dashed line marks the minimum deviation among rows
    flagged by the primary IQR detection (IQR on raw volume_units —
    matching preprocess.py).  A fence on the deviation distribution
    itself is not used because 98% of rows have deviation = 0, making
    Q1 = Q3 = 0 and IQR = 0 — the fence would collapse to zero and
    render at the wrong position.

    Log y-scale is used because the distribution has a dominant 0-spike
    alongside a thin but meaningful extreme tail.
    """
    # ── 1. Sample for histogram performance ───────────────────────────────────
    sample = fs_dirty.sample(n=min(SAMPLE_HIST, len(fs_dirty)), random_state=42)
    dev_sample = (
        sample["volume_units"]
        - sample["baseline_volume"]
        - sample["incremental_volume"]
    )

    # ── 2. Primary detection fence: IQR on raw volume_units (full dataset) ────
    # Matches preprocess.py exactly — used to derive n_outliers and to
    # identify which rows are flagged so we can find the visual separator.
    q1_vol    = fs_dirty["volume_units"].quantile(0.25)
    q3_vol    = fs_dirty["volume_units"].quantile(0.75)
    iqr_vol   = q3_vol - q1_vol
    fence_vol = q3_vol + IQR_MULTIPLIER * iqr_vol
    n_outliers = (fs_dirty["volume_units"] > fence_vol).sum()

    # ── 3. Deviation on full dataset ──────────────────────────────────────────
    dev_full = (
        fs_dirty["volume_units"]
        - fs_dirty["baseline_volume"]
        - fs_dirty["incremental_volume"]
    )

    # ── 4. Visual separator = minimum deviation among flagged rows ────────────
    # The IQR fence is in volume_units space; this histogram is in deviation
    # space.  Rather than computing a fence on the degenerate deviation
    # distribution (98% zeros → IQR = 0 → fence collapses to zero), we find
    # the leftmost edge of the outlier cluster: the smallest deviation value
    # among rows the primary detection already flagged.
    flagged_mask   = fs_dirty["volume_units"] > fence_vol
    fence_dev_line = dev_full[flagged_mask].min()

    # ── 5. Build histogram ────────────────────────────────────────────────────
    df_plot = pd.DataFrame({"Volume Deviation": dev_sample})

    fig = px.histogram(
        df_plot,
        x="Volume Deviation",
        nbins=120,
        log_y=True,
        color_discrete_sequence=[C_CLEAN],
        title=(
            "QI-04 — Volume Deviation from Expected "
            "(volume_units − baseline_volume − incremental_volume)"
        ),
        labels={
            "Volume Deviation": "Deviation from Expected (units)",
            "count": "Row Count (log scale)",
        },
        template=TEMPLATE,
    )

    # ── 6. Vertical separator line ────────────────────────────────────────────
    fig.add_vline(
        x=fence_dev_line,
        line_dash="dash",
        line_color=C_DIRTY,
        line_width=2.5,
    )

    # ── 7. Annotation ─────────────────────────────────────────────────────────
    fig.add_annotation(
        x=fence_dev_line,
        y=1,
        xref="x",
        yref="paper",
        text=_wrap_annotation(
            f"Leftmost flagged deviation: {fence_dev_line:,.0f}  |  "
            f"{n_outliers:,} rows flagged as is_volume_outlier ({n_outliers / len(fs_dirty):.1%})  |  "
            f"Primary detection: IQR on raw volume_units (fence = {fence_vol:,.0f})"
        ),
        showarrow=True,
        arrowhead=2,
        ax=80,
        ay=-60,
        font=dict(size=11, color=C_DIRTY),
        bordercolor=C_DIRTY,
        borderwidth=1,
        bgcolor="white",
    )

    # ── 8. Layout ─────────────────────────────────────────────────────────────
    fig.update_layout(
        font=dict(size=13),
        title_font_size=15,
        xaxis=dict(title="Deviation from Expected (units)"),
        yaxis=dict(title="Row Count (log scale)"),
        annotations=list(fig.layout.annotations) + [
            dict(
                x=0.5,
                y=-0.13,
                xref="paper",
                yref="paper",
                showarrow=False,
                text=_wrap_annotation(
                    "Deviation = 0 for all clean rows (volume_units = baseline + incremental "
                    "by construction).  Injected outliers at 5–10× baseline produce large "
                    "positive deviations.  Vertical line marks the leftmost flagged deviation — "
                    "all points to its right were flagged via IQR on raw volume_units "
                    "in preprocess.py."
                ),
                font=dict(size=11, color=C_NEUTRAL),
            )
        ],
        margin=dict(b=130),
    )

    _save(fig, "03_volume_deviation_hist.png")
    

# ==============================================================================
# PLOT 04 — QI-04: Baseline vs actual volume scatter, outliers highlighted
# ==============================================================================


def plot_volume_outlier_scatter(fs_dirty: pd.DataFrame) -> None:
    """
    Scatter plot of baseline_volume (x) vs volume_units (y).

    Outlier rows sit far above the reference diagonal (volume_units =
    baseline_volume), reflecting the 5–10× multiplier injected by QI-04.
    Normal promoted rows cluster above the diagonal by 20–50% (incremental
    uplift); non-promoted rows sit on or near the diagonal.

    Sampling strategy
    -----------------
    Compute the IQR fence on the full dataset first (single source of truth,
    identical to preprocess.py), then split into flagged / normal groups and
    sample each group independently to controlled sizes:
        - Flagged : up to SAMPLE_OUTLIER rows  (2,000 — enough to show the
                    cluster without dominating the visual)
        - Normal  : up to SAMPLE_SCATTER rows  (30,000 — dense context)

    This prevents the bug where all ~46K outlier rows were included while
    normals were capped at 30K, making outliers appear ~60% of the chart
    rather than their true ~2%.
    """
    SAMPLE_OUTLIER = 2_000  # outlier sample cap — local constant

    # ── 1. Compute IQR fence on raw volume_units (matches preprocess.py) ──────
    # Primary detection method: univariate IQR on volume_units directly,
    # independent of baseline/incremental decomposition.
    q1    = fs_dirty["volume_units"].quantile(0.25)
    q3    = fs_dirty["volume_units"].quantile(0.75)
    iqr   = q3 - q1
    fence = q3 + IQR_MULTIPLIER * iqr

    # ── 2. Apply flag to full dataset, then split ─────────────────────────────
    fs_flagged = fs_dirty.copy()
    fs_flagged["Outlier"] = (fs_flagged["volume_units"] > fence).map(
        {True: "Flagged (is_volume_outlier)", False: "Normal"}
    )

    all_outliers = fs_flagged[fs_flagged["Outlier"] == "Flagged (is_volume_outlier)"]
    all_normals = fs_flagged[fs_flagged["Outlier"] == "Normal"]
    n_total_outliers = len(all_outliers)
    n_total_rows = len(fs_dirty)

    # ── 3. Sample each group to controlled sizes ──────────────────────────────
    outlier_sample = all_outliers.sample(
        n=min(SAMPLE_OUTLIER, len(all_outliers)), random_state=42
    )
    normal_sample = all_normals.sample(
        n=min(SAMPLE_SCATTER, len(all_normals)), random_state=42
    )

    combined = pd.concat([outlier_sample, normal_sample], ignore_index=True)

    fig = px.scatter(
        combined,
        x="baseline_volume",
        y="volume_units",
        color="Outlier",
        color_discrete_map={
            "Flagged (is_volume_outlier)": C_DIRTY,
            "Normal": C_CLEAN,
        },
        opacity=0.5,
        size_max=6,
        title="QI-04 — Volume Outlier Scatter: baseline_volume vs volume_units",
        labels={
            "baseline_volume": "baseline_volume (units)",
            "volume_units": "volume_units (units)",
            "Outlier": "Row Classification",
        },
        template=TEMPLATE,
    )

    # Reference line: volume_units = baseline_volume (non-promoted ceiling)
    max_val = combined["baseline_volume"].quantile(0.999)
    fig.add_trace(
        go.Scatter(
            x=[0, max_val],
            y=[0, max_val],
            mode="lines",
            line=dict(color=C_NEUTRAL, dash="dot", width=1.5),
            name="y = x (no uplift)",
            showlegend=True,
        )
    )

    fig.update_layout(
        font=dict(size=13),
        title_font_size=15,
        legend_title_text="Row Classification",
        annotations=[
            dict(
                x=0.5,
                y=-0.13,
                xref="paper",
                yref="paper",
                showarrow=False,
                text=(
                    _wrap_annotation(
                        f"Dotted line = volume_units = baseline_volume (zero incremental).  "
                        f"Normal promoted rows sit 20–50% above the line.  "
                        f"Injected outliers (5–10× baseline): {n_total_outliers:,} rows "
                        f"({n_total_outliers / n_total_rows:.1%} of fact_sales) — "
                        f"scatter shows sampled subset for readability."
                    )
                ),
                font=dict(size=11, color=C_NEUTRAL),
            )
        ],
        margin=dict(b=130),
    )

    _save(fig, "04_volume_outlier_scatter.png")


# ==============================================================================
# PLOT 05 — QI-05: Promotion mechanic distribution including NULL
# ==============================================================================


def plot_null_mechanic(fs_dirty: pd.DataFrame) -> None:
    """
    Horizontal bar chart of promotion_mechanic value counts for rows where
    is_promoted = True.  NULLs are surfaced as 'NULL — Not Captured' and
    highlighted in a distinct colour.

    This plot directly demonstrates the QI-05 issue: 22% of promoted rows
    carry NULL mechanic — filtering on mechanic IS NOT NULL would silently
    exclude more than one-fifth of promoted volume.
    """
    promo = fs_dirty[fs_dirty["is_promoted"] == True].copy()

    # Replace NaN with a labelled string so it appears as a bar
    promo["promotion_mechanic"] = promo["promotion_mechanic"].fillna(
        "NULL — Not Captured"
    )

    counts = promo["promotion_mechanic"].value_counts().reset_index()
    counts.columns = ["Mechanic", "Row Count"]
    counts = counts.sort_values("Row Count", ascending=True)

    # Assign colour: NULL bar gets distinct colour
    counts["Colour"] = counts["Mechanic"].apply(
        lambda m: C_NULL if m == "NULL — Not Captured" else C_CLEAN
    )

    fig = px.bar(
        counts,
        x="Row Count",
        y="Mechanic",
        orientation="h",
        color="Mechanic",
        color_discrete_map={
            m: (C_NULL if m == "NULL — Not Captured" else C_CLEAN)
            for m in counts["Mechanic"]
        },
        text="Row Count",
        title=(
            "QI-05 — Promotion Mechanic Distribution (is_promoted = True rows only)<br>"
            "<sup>NULL mechanic ≠ non-promotional — filter on is_promoted, not on mechanic IS NOT NULL</sup>"
        ),
        labels={
            "Row Count": "Rows (is_promoted = True)",
            "Mechanic": "promotion_mechanic",
        },
        template=TEMPLATE,
    )
    fig.update_traces(texttemplate="%{x:,}", textposition="outside", textfont_size=11)
    fig.update_layout(
        font=dict(size=13),
        title_font_size=14,
        showlegend=False,
        xaxis=dict(range=[0, counts["Row Count"].max() * 1.2]),
        margin=dict(l=200, b=130),
        annotations=[
            dict(
                x=0.5,
                y=-0.13,
                xref="paper",
                yref="paper",
                showarrow=False,
                text=(
                    _wrap_annotation(
                        "NULL — Not Captured represents ~22% of is_promoted=True rows.  "
                        "These are genuine promotions with incomplete mechanic data from POS/TPM handshake gaps."
                    )
                ),
                font=dict(size=11, color=C_NEUTRAL),
            )
        ],
    )

    _save(fig, "05_null_mechanic.png")


# ==============================================================================
# PLOT 06 — QI-08: Temporal gap heatmap (banner × brand)
# ==============================================================================


def plot_temporal_gap_heatmap(fm_dirty: pd.DataFrame) -> None:
    """
    Heatmap of missing-week count per banner × brand pair.

    The full 104-week calendar is inferred from the data. For each observed
    (banner, brand) pair, missing weeks = 104 − actual distinct week count.
    QI-08 injected 3–4 week gaps for exactly 4 pairs; all other pairs show 0.

    Only pairs with at least one missing week are shown in the main heatmap;
    the subtitle reports the total count of zero-gap pairs for context.
    """
    all_weeks = fm_dirty["week_date"].nunique()
    pair_counts = (
        fm_dirty.groupby(["banner", "brand"])["week_date"]
        .nunique()
        .reset_index(name="weeks_present")
    )
    pair_counts["missing_weeks"] = all_weeks - pair_counts["weeks_present"]

    n_zero_gap = (pair_counts["missing_weeks"] == 0).sum()
    gap_pairs = pair_counts[pair_counts["missing_weeks"] > 0].copy()

    if gap_pairs.empty:
        print("  ⚠  No temporal gaps found — skipping plot 06")
        return

    # Pivot to banner (row) × brand (col) matrix for heatmap
    pivot = gap_pairs.pivot_table(
        index="banner", columns="brand", values="missing_weeks", fill_value=0
    )

    fig = px.imshow(
        pivot,
        color_continuous_scale=[
            [0.0, "#FFFFFF"],
            [0.5, "#FFCC80"],
            [1.0, C_DIRTY],
        ],
        text_auto=True,
        aspect="auto",
        title=(
            "QI-08 — Temporal Gap Heatmap: Missing Weeks per Banner × Brand Pair<br>"
            f"<sup>Showing {len(gap_pairs)} pairs with gaps.  "
            f"{n_zero_gap:,} additional pairs have complete 104-week coverage.</sup>"
        ),
        labels={"x": "Brand", "y": "Banner", "color": "Missing Weeks"},
        template=TEMPLATE,
    )
    fig.update_coloraxes(showscale=True, colorbar_title="Missing<br>Weeks")
    fig.update_layout(
        font=dict(size=12),
        title_font_size=14,
        xaxis=dict(tickangle=-30),
        annotations=[
            dict(
                x=0.5,
                y=-0.16,
                xref="paper",
                yref="paper",
                showarrow=False,
                text=(
                    _wrap_annotation(
                        "Missing rows ≠ zero sales.  A gap means the panel measurement is absent, not that the brand sold zero units.  "
                        "Always use COUNT(DISTINCT week_date) per group — do not assume 104 weeks."
                    )
                ),
                font=dict(size=11, color=C_NEUTRAL),
            )
        ],
        margin=dict(b=130),
    )

    _save(fig, "06_temporal_gap_heatmap.png")


# ==============================================================================
# PLOT 07 — Weekly brand volume trends: embedded performance signals
# ==============================================================================


def plot_weekly_volume_trends(fm_dirty: pd.DataFrame) -> None:
    """
    Multi-panel line chart of weekly aggregated brand_volume_units for the
    four brands with the most prominent performance signals embedded in the
    synthetic data by generate_data.py:

        NitroBoost   — +18% YoY growth in 2025 (Functional/Energy)
        CocoaEthos   — Chocolate Bars sub-category: no signal, stable baseline
        Porridge&Oats brand in Porridge & Oats sub-cat — Q3 seasonal dip ×0.65
                      (ISO weeks 26–39, approximately July–September)
        ValuMart banner aggregate — 2025 linear decline from 1.00 → 0.82

    Why these four:
        - NitroBoost and the ValuMart decline are cross-category signals baked
          into fact_market baseline volume; they should be clearly visible as
          trend breaks between 2024 and 2025.
        - The Porridge & Oats Q3 dip is a within-year seasonal signal; it should
          appear as a consistent summer trough across both years.
        - A stable brand (CocoaEthos) provides a visual reference baseline,
          making the signal brands' departures more legible.

    Data note:
        Reads from qi-injected layer. QI-07 violations excluded (brand_vol >
        cat_vol rows) as they corrupt volume aggregations.  QI-08 temporal gaps
        are left sparse — missing weeks produce natural breaks in the line,
        correctly communicating absent panel measurements rather than zero sales.

    Limitation acknowledged:
        The market_share_volume_pct box plot was replaced by this plot because
        brand shares in the synthetic data were drawn independently from
        uniform(0.05, 0.40) without competitive sum-to-one constraints, producing
        uniform medians of ~22% across all sub-categories with no competitive
        structure differentiation.  The weekly volume trend directly evidences
        the structural performance signals which ARE genuinely embedded.
    """
    # ── 1. Exclude QI-07 violations ───────────────────────────────────────────
    fm = fm_dirty[
        fm_dirty["brand_volume_units"] <= fm_dirty["total_category_volume_units"]
    ].copy()

    # Ensure week_date is datetime for proper time-series ordering
    fm["week_date"] = pd.to_datetime(fm["week_date"])

    # ── 2. Panel A — NitroBoost vs CocoaEthos: YoY trend comparison ──────────
    # Aggregate weekly brand volume across all banners for each brand
    trend_brands = ["NitroBoost", "CocoaEthos"]
    panel_a = (
        fm[fm["brand"].isin(trend_brands)]
        .groupby(["brand", "week_date"])["brand_volume_units"]
        .sum()
        .reset_index()
    )

    # ── 3. Panel B — Porridge & Oats sub-category: seasonal dip ──────────────
    # Sum all brands in sub-category to surface the sub-category-level signal
    panel_b = (
        fm[fm["sub_category"] == "Porridge & Oats"]
        .groupby("week_date")["brand_volume_units"]
        .sum()
        .reset_index()
        .rename(columns={"brand_volume_units": "total_volume_units"})
    )
    panel_b["series"] = "Porridge & Oats (sub-category total)"

    # ── 4. Panel C — ValuMart banner: 2025 linear decline ────────────────────
    panel_c = (
        fm[fm["banner"] == "ValuMart"]
        .groupby("week_date")["brand_volume_units"]
        .sum()
        .reset_index()
        .rename(columns={"brand_volume_units": "total_volume_units"})
    )
    panel_c["series"] = "ValuMart (all brands, total volume)"

    # ── 5. Build figure with 3 subplot rows ───────────────────────────────────
    from plotly.subplots import make_subplots

    fig = make_subplots(
        rows=3,
        cols=1,
        shared_xaxes=True,
        subplot_titles=[
            "Panel A — NitroBoost (+18% YoY 2025) vs CocoaEthos (stable baseline)",
            "Panel B — Porridge & Oats sub-category total (Q3 seasonal dip, ISO wks 26–39)",
            "Panel C — ValuMart banner total (linear decline 2025: 1.00 → 0.82)",
        ],
        vertical_spacing=0.10,
    )

    # ── Panel A traces ────────────────────────────────────────────────────────
    colour_map_a = {"NitroBoost": C_DIRTY, "CocoaEthos": C_NEUTRAL}
    for brand in trend_brands:
        df_b = panel_a[panel_a["brand"] == brand].sort_values("week_date")
        fig.add_trace(
            go.Scatter(
                x=df_b["week_date"],
                y=df_b["brand_volume_units"],
                mode="lines",
                name=brand,
                line=dict(color=colour_map_a[brand], width=2),
                showlegend=True,
            ),
            row=1,
            col=1,
        )

    # 2024 / 2025 boundary line on panel A
    boundary = pd.Timestamp("2025-01-01")
    fig.add_vline(
        x=boundary.timestamp() * 1000,
        line_dash="dot",
        line_color=C_NEUTRAL,
        line_width=1,
        row=1,
        col=1,
    )
    fig.add_annotation(
        x=boundary,
        y=1,
        xref="x",
        yref="y domain",
        text="2025 →",
        showarrow=False,
        font=dict(size=10, color=C_NEUTRAL),
        xanchor="left",
    )

    # ── Panel B trace ─────────────────────────────────────────────────────────
    pb_sorted = panel_b.sort_values("week_date")
    fig.add_trace(
        go.Scatter(
            x=pb_sorted["week_date"],
            y=pb_sorted["total_volume_units"],
            mode="lines",
            name="Porridge & Oats",
            line=dict(color=C_ACCENT, width=2),
            showlegend=True,
        ),
        row=2,
        col=1,
    )

    # Shade Q3 dip windows (ISO weeks 26–39 ≈ late June – late September)
    for year in [2024, 2025]:
        dip_start = pd.Timestamp(f"{year}-06-23")  # approx week 26
        dip_end = pd.Timestamp(f"{year}-09-29")  # approx week 39
        fig.add_vrect(
            x0=dip_start,
            x1=dip_end,
            fillcolor=C_ACCENT,
            opacity=0.08,
            line_width=0,
            row=2,
            col=1,
        )

    # ── Panel C trace ─────────────────────────────────────────────────────────
    pc_sorted = panel_c.sort_values("week_date")
    fig.add_trace(
        go.Scatter(
            x=pc_sorted["week_date"],
            y=pc_sorted["total_volume_units"],
            mode="lines",
            name="ValuMart total",
            line=dict(color=C_CLEAN, width=2),
            showlegend=True,
        ),
        row=3,
        col=1,
    )

    # Shade 2025 decline period
    fig.add_vrect(
        x0=pd.Timestamp("2025-01-01"),
        x1=pd.Timestamp("2025-12-31"),
        fillcolor=C_CLEAN,
        opacity=0.06,
        line_width=0,
        row=3,
        col=1,
    )

    # ── 6. Layout ─────────────────────────────────────────────────────────────
    fig.update_layout(
        title=dict(
            text=(
                "Performance Signals Embedded in Synthetic Data — Weekly Brand Volume Trends<br>"
                "<sup>Aggregated from fact_market (qi-injected layer)  |  "
                "QI-07 violations excluded  |  QI-08 gaps left sparse</sup>"
            ),
            font=dict(size=15),
        ),
        height=900,
        template=TEMPLATE,
        font=dict(size=11),
        legend=dict(
            orientation="h",
            y=-0.06,
            x=0.5,
            xanchor="center",
        ),
        margin=dict(t=100, b=150),
        annotations=list(fig.layout.annotations)
        + [
            dict(
                x=0.5,
                y=-0.12,
                xref="paper",
                yref="paper",
                showarrow=False,
                text=_wrap_annotation(
                    "NitroBoost shows a clear volume step-up in 2025 vs CocoaEthos stable baseline (Panel A).  "
                    "Porridge & Oats dips consistently in Q3 each year — shaded bands mark ISO weeks 26–39 (Panel B).  "
                    "ValuMart total volume trends downward through 2025 — shaded region marks the decline period (Panel C)."
                ),
                font=dict(size=11, color=C_NEUTRAL),
            ),
        ],
    )

    # Y-axis labels per panel
    fig.update_yaxes(title_text="Volume Units", row=1, col=1)
    fig.update_yaxes(title_text="Volume Units", row=2, col=1)
    fig.update_yaxes(title_text="Volume Units", row=3, col=1)
    fig.update_xaxes(title_text="Week", row=3, col=1)

    _save(fig, "07_weekly_volume_trends.png", height=900)


# ==============================================================================
# PLOT 08 — Price index distribution by price tier
# ==============================================================================


def plot_price_index_by_tier(
    fm_dirty: pd.DataFrame,
    dp_raw: pd.DataFrame,
) -> None:
    """
    Violin plot of computed price_index by price tier (from dim_product).

    price_index = avg_shelf_price_gbp / category_avg_RSP × 100
    category_avg_RSP = total_category_value_gbp / total_category_volume_units

    Rows are excluded where:
        - avg_shelf_price_gbp == 0    (QI-06 zero price)
        - brand_volume_units > total_category_volume_units  (QI-07 violation)
        - total_category_volume_units == 0  (division guard)

    Expected result: Premium brands index above 100 (above category average);
    Value brands index below 100 — demonstrates that the synthetic data
    preserves realistic brand-tier RSP positioning.
    """
    # Join price_tier from dim_product (brand → tier is a brand-level attribute)
    brand_tier = dp_raw[["brand", "price_tier"]].drop_duplicates(subset=["brand"])
    fm = fm_dirty.merge(brand_tier, on="brand", how="left")

    # Exclude flagged rows
    valid = fm[
        (fm["avg_shelf_price_gbp"] > 0)
        & (fm["brand_volume_units"] <= fm["total_category_volume_units"])
        & (fm["total_category_volume_units"] > 0)
        & (fm["total_category_value_gbp"] > 0)
    ].copy()

    valid["price_index"] = (
        valid["avg_shelf_price_gbp"]
        / (valid["total_category_value_gbp"] / valid["total_category_volume_units"])
        * 100
    )

    # Tier order: Premium → Mainstream → Value
    tier_order = ["Premium", "Mainstream", "Value"]
    valid["price_tier"] = pd.Categorical(
        valid["price_tier"], categories=tier_order, ordered=True
    )
    valid = valid.sort_values("price_tier")

    fig = px.violin(
        valid,
        x="price_tier",
        y="price_index",
        color="price_tier",
        box=True,
        points=False,
        color_discrete_map={
            "Premium": C_CLEAN,
            "Mainstream": C_ACCENT,
            "Value": C_NEUTRAL,
        },
        category_orders={"price_tier": tier_order},
        title=(
            "Derived: Price Index Distribution by Brand Price Tier "
            "(QI-06 and QI-07 rows excluded)"
        ),
        labels={
            "price_tier": "Brand Price Tier",
            "price_index": "Price Index (category avg = 100)",
        },
        template=TEMPLATE,
    )

    # Reference line at 100 (= category average RSP)
    fig.add_hline(
        y=100,
        line_dash="dash",
        line_color=C_DIRTY,
        line_width=1.5,
        annotation_text="Category avg RSP = 100",
        annotation_position="top right",
        annotation_font=dict(size=11, color=C_DIRTY),
    )

    fig.update_layout(
        showlegend=False,
        font=dict(size=13),
        title_font_size=15,
        yaxis=dict(title="Price Index (category avg = 100)"),
        annotations=[
            dict(
                x=0.5,
                y=-0.13,
                xref="paper",
                yref="paper",
                showarrow=False,
                text=(
                    _wrap_annotation(
                        "Price Index > 100 → brand RSP above category average.  "
                        "Premium brands should cluster above 100; Value brands below.  "
                        "Violin width = density of observations at each price index level."
                    )
                ),
                font=dict(size=11, color=C_NEUTRAL),
            )
        ],
        margin=dict(b=130),
    )

    _save(fig, "08_price_index_by_tier.png")


# ==============================================================================
# MAIN
# ==============================================================================


def main() -> None:
    print("\n╔══════════════════════════════════════════════════════════════════╗")
    print("║  eda_viz.py — AM1 Sprint 1 / F-03 EDA Visualisation            ║")
    print("║  Reads  : data/raw/  +  data/raw/qi-injected/                  ║")
    print("║  Writes : data/eda_plots/  (8 PNG files)                       ║")
    print("╚══════════════════════════════════════════════════════════════════╝\n")

    # ── 1. Load data ──────────────────────────────────────────────────────────
    print("Loading Parquet files ...")

    dp_raw = _load_parquet(RAW_DIR, "dim_product")
    dc_raw = _load_parquet(RAW_DIR, "dim_customer")
    dp_dirty = _load_parquet(DIRTY_DIR, "dim_product")
    dc_dirty = _load_parquet(DIRTY_DIR, "dim_customer")
    fs_dirty = _load_parquet(DIRTY_DIR, "fact_sales")
    fm_dirty = _load_parquet(DIRTY_DIR, "fact_market")

    print(f"  dim_product  raw     : {len(dp_raw):>7,} rows")
    print(f"  dim_product  dirty   : {len(dp_dirty):>7,} rows")
    print(f"  dim_customer raw     : {len(dc_raw):>7,} rows")
    print(f"  dim_customer dirty   : {len(dc_dirty):>7,} rows")
    print(f"  fact_sales   dirty   : {len(fs_dirty):>7,} rows")
    print(f"  fact_market  dirty   : {len(fm_dirty):>7,} rows")

    # ── 2. Generate plots ─────────────────────────────────────────────────────
    print(f"\nGenerating plots → {PLOTS_DIR}")

    print("\n[01/08] Casing cardinality (QI-01/02)")
    plot_casing_cardinality(dp_raw, dp_dirty)

    print("[02/08] Data quality overview")
    plot_quality_overview(dc_dirty, fs_dirty, fm_dirty)

    print("[03/08] Volume deviation histogram (QI-04)")
    plot_volume_deviation_hist(fs_dirty)

    print("[04/08] Volume outlier scatter (QI-04)")
    plot_volume_outlier_scatter(fs_dirty)

    print("[05/08] NULL mechanic distribution (QI-05)")
    plot_null_mechanic(fs_dirty)

    print("[06/08] Temporal gap heatmap (QI-08)")
    plot_temporal_gap_heatmap(fm_dirty)

    print("[07/08] Weekly volume trends: embedded performance signals")
    plot_weekly_volume_trends(fm_dirty)

    print("[08/08] Price index by tier")
    plot_price_index_by_tier(fm_dirty, dp_raw)

    print(f"\n╔══════════════════════════════════════════════════════════════════╗")
    print(f"║  eda_viz.py — COMPLETE  ({8} plots written to data/eda_plots/)  ║")
    print(f"╚══════════════════════════════════════════════════════════════════╝\n")


if __name__ == "__main__":
    main()
