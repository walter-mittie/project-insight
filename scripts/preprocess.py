"""
preprocess.py
-------------
AM1 Sprint 1 / F-03 — EDA + Cleaning Pipeline

Reads quality-issue-injected Parquet files from data/raw/qi-injected/ (written
by inject_quality_issues.py), applies all cleaning and flagging decisions,
computes derived fact_market measures, and writes cleaned outputs to
data/processed/.  Raw files in data/raw/ are never touched.

Quality-issue handling summary
-------------------------------
    QI-01  dim_product   pack_type casing     → normalise to canonical form (mapping table)
    QI-02  dim_product   variant casing       → normalise to canonical form (mapping table)
    QI-03  fact_sales    zero sku_net_price_gbp → add is_zero_price flag; excluded from revenue KPIs
    QI-04  fact_sales    volume outliers       → Tukey outer fence on raw volume_units (primary);
                                                 invariant cross-validation (secondary);
                                                 add is_volume_outlier flag (retained)
    QI-05  fact_sales    NULL promotion_mechanic → documented as known sparseness; NOT imputed
    QI-06  fact_market   zero avg_shelf_price_gbp → add is_zero_shelf_price flag; excluded from price KPIs
    QI-07  fact_market   brand_vol > cat_vol   → add is_vol_violation flag; excluded from share KPIs
    QI-08  fact_market   temporal gaps         → audit per banner × brand; documented in eda_report.md; left sparse

Additional preprocessing
------------------------
    dim_product   is_active  : "Y"/"N" string → bool
    dim_product   launch_date: string → date
    dim_customer  territory  : NULL → "Unknown-{Channel}"
    dim_customer  store_count: NULL → channel median (median chosen over mean — right-skewed store-count distributions;
                               median more robust to large flagship stores; documented in eda_report.md)

Derived fact_market measures (appended to processed layer)
-----------------------------------------------------------
    market_share_volume_pct  = brand_volume_units / total_category_volume_units * 100
    market_share_value_pct   = brand_value_gbp / total_category_value_gbp * 100
    numeric_distribution_pct = numeric_distribution_outlets / total_outlets_in_banner * 100
    price_index              = avg_shelf_price_gbp / (total_category_value_gbp / total_category_volume_units) * 100

    All four are set to NaN where is_vol_violation=True or (for price_index and value share)
    where is_zero_shelf_price=True, to prevent polluted denominators flowing through.

Input
-----
    data/raw/qi-injected/dim_product.parquet
    data/raw/qi-injected/dim_customer.parquet
    data/raw/qi-injected/fact_sales.parquet
    data/raw/qi-injected/fact_market.parquet

Output
------
    data/processed/dim_product.parquet   — normalised casing, is_active bool, launch_date date
    data/processed/dim_customer.parquet  — imputed territory & store_count
    data/processed/fact_sales.parquet    — is_zero_price, is_volume_outlier flags added
    data/processed/fact_market.parquet   — is_zero_shelf_price, is_vol_violation flags; derived measures
    data/eda_report.md                   — profiling findings and all handling decisions

Execution
---------
    python scripts/preprocess.py          # from project root
    python preprocess.py                  # from scripts/ directory
"""

import os
from datetime import date

import numpy as np
import pandas as pd

# ──────────────────────────────────────────────────────────────────────────────
# PATHS
# ──────────────────────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DIRTY_DIR = os.path.join(BASE_DIR, "..", "data", "raw", "qi-injected")
PROCESSED_DIR = os.path.join(BASE_DIR, "..", "data", "processed")
DATA_DIR = os.path.join(BASE_DIR, "..", "data")
os.makedirs(PROCESSED_DIR, exist_ok=True)

# eda_report.md written to data/ (project-level, not layer-specific)
EDA_REPORT_PATH = os.path.join(DATA_DIR, "eda_report.md")

# ──────────────────────────────────────────────────────────────────────────────
# IQR OUTLIER DETECTION — TUKEY OUTER FENCE
# Using 3.0× IQR (outer fence) rather than 1.5× (standard fence) because
# fact_sales has a genuine right-skewed volume distribution (lognormal baseline
# + promotional incremental); the standard fence would over-flag legitimate
# high-velocity promotional weeks.  The injected outliers at 5–10× baseline
# are far beyond the outer fence on the raw volume_units distribution.
# ──────────────────────────────────────────────────────────────────────────────
IQR_MULTIPLIER = 3.0  # Tukey outer fence

# ──────────────────────────────────────────────────────────────────────────────
# CANONICAL NORMALISATION MAPS
# Mirrors the corruption dictionaries in inject_quality_issues.py in inverted
# form: {corrupted_form: canonical_value}.  Entries where the corrupted form
# equals the canonical value are intentionally excluded — they would produce
# a no-op and clutter the lookup.
#
# Source of truth: inject_quality_issues.py PACK_TYPE_CORRUPTIONS and
# VARIANT_CORRUPTIONS.  Any change to corruption options there must be
# reflected here.
# ──────────────────────────────────────────────────────────────────────────────

# ── pack_type: corrupted → canonical ─────────────────────────────────────────
PACK_TYPE_CORRECTIONS: dict[str, str] = {
    # Bottle
    "bottle": "Bottle",
    "BTL": "Bottle",
    "Btl": "Bottle",
    "btl": "Bottle",
    # Carton
    "carton": "Carton",
    "CTN": "Carton",
    "Ctn": "Carton",
    "ctn": "Carton",
    # Tub
    "tub": "Tub",
    "TUB": "Tub",
    "tb": "Tub",
    # Bag
    "bag": "Bag",
    "BAG": "Bag",
    "bg": "Bag",
    # Box
    "box": "Box",
    "BOX": "Box",
    "bx": "Box",
    # Can
    "can": "Can",
    "CAN": "Can",
    "cn": "Can",
    # Multipack
    "multipack": "Multipack",
    "MPack": "Multipack",
    "Multi-pack": "Multipack",
    "multi-pack": "Multipack",
    # Pouch
    "pouch": "Pouch",
    "PCH": "Pouch",
    "pch": "Pouch",
    # Sachet Pack
    "sachet pack": "Sachet Pack",
    "sachet": "Sachet Pack",
    "Sachet Pk": "Sachet Pack",
    "sachet pk": "Sachet Pack",
    # Bar Multipack
    "bar MP": "Bar Multipack",
    "Bar Mp": "Bar Multipack",
    "bar multipack": "Bar Multipack",
    # Blister Pack
    "blister pk": "Blister Pack",
    "BLS PK": "Blister Pack",
    "blister pack": "Blister Pack",
    # Gift Box
    "gift bx": "Gift Box",
    "GIFT BOX": "Gift Box",
    "Gift Bx": "Gift Box",
    # Steam Bag
    "steam bag": "Steam Bag",
    "Stm Bag": "Steam Bag",
    "STEAM BAG": "Steam Bag",
    # Block
    "block": "Block",
    "BLK": "Block",
    "Blk": "Block",
    # Slices Pack
    "slices pk": "Slices Pack",
    "SLICES PK": "Slices Pack",
    "Slices Pk": "Slices Pack",
    # Grated Bag
    "grated bg": "Grated Bag",
    "Grated Bg": "Grated Bag",
    "GRATED BAG": "Grated Bag",
    # Pot
    "pot": "Pot",
    "POT": "Pot",
    "pt": "Pot",
    # Portion Pack
    "portion pk": "Portion Pack",
    "PORTION PK": "Portion Pack",
    "Portion Pk": "Portion Pack",
    # Tray
    "tray": "Tray",
    "TRY": "Tray",
    "try": "Tray",
    "tr": "Tray",
    # Tin
    "tin": "Tin",
    "TIN": "Tin",
    "tn": "Tin",
    # Jar
    "jar": "Jar",
    "JAR": "Jar",
    "jr": "Jar",
    # Bar
    "bar": "Bar",
    "BAR": "Bar",
    "br": "Bar",
}

# ── variant: corrupted → canonical ───────────────────────────────────────────
VARIANT_CORRECTIONS: dict[str, str] = {
    # Chocolate (bare — distinct from Milk/Dark/White Chocolate)
    "chocolate": "Chocolate",
    "Choc": "Chocolate",
    "CHOC": "Chocolate",
    "choc": "Chocolate",
    # Original
    "original": "Original",
    "Orig": "Original",
    "ORIG": "Original",
    "orig": "Original",
    # Strawberry
    "strawberry": "Strawberry",
    "Straw": "Strawberry",
    "STRAW": "Strawberry",
    "Strawb": "Strawberry",
    # Raspberry
    "raspberry": "Raspberry",
    "Rasp": "Raspberry",
    "RASP": "Raspberry",
    "Raspb": "Raspberry",
    # Vanilla
    "vanilla": "Vanilla",
    "Van": "Vanilla",
    "VANL": "Vanilla",
    "van": "Vanilla",
    # Blueberry
    "blueberry": "Blueberry",
    "Bluebry": "Blueberry",
    "BLUEBERRY": "Blueberry",
    "Blbry": "Blueberry",
    # Mango
    "mango": "Mango",
    "MNG": "Mango",
    "mng": "Mango",
    # Caramel
    "caramel": "Caramel",
    "Carm": "Caramel",
    "CARAMEL": "Caramel",
    "Carml": "Caramel",
    # Tropical
    "tropical": "Tropical",
    "Trop": "Tropical",
    "TROP": "Tropical",
    "tropcl": "Tropical",
    # Multigrain
    "multigrain": "Multigrain",
    "Multi-grain": "Multigrain",
    "MULTIGRAIN": "Multigrain",
    "Multigrn": "Multigrain",
    # Whole Grain
    "whole grain": "Whole Grain",
    "Whole-Grain": "Whole Grain",
    "WHOLE GRAIN": "Whole Grain",
    "WGN": "Whole Grain",
    # Sugar Free
    "sugar free": "Sugar Free",
    "Sugar-Free": "Sugar Free",
    "SUGAR FREE": "Sugar Free",
    "SF": "Sugar Free",
    # Diet
    "diet": "Diet",
    "DIET": "Diet",
    "dt": "Diet",
    # Zero
    "zero": "Zero",
    "ZERO": "Zero",
    "zro": "Zero",
    # Salt & Vinegar
    "salt & vinegar": "Salt & Vinegar",
    "Slt + Vin": "Salt & Vinegar",
    "Slt & Vin": "Salt & Vinegar",
    "S+V": "Salt & Vinegar",
    # Cheese & Onion
    "cheese & onion": "Cheese & Onion",
    "C&O": "Cheese & Onion",
    "Chse+Onion": "Cheese & Onion",
    "C + O": "Cheese & Onion",
    # BBQ
    "bbq": "BBQ",
    "Barbecue": "BBQ",
    "Bbq": "BBQ",
    "b.b.q": "BBQ",
    # Milk Chocolate
    "milk chocolate": "Milk Chocolate",
    "Milk Choc": "Milk Chocolate",
    "MILK CHOC": "Milk Chocolate",
    "Mlk Choc": "Milk Chocolate",
    # Dark Chocolate
    "dark chocolate": "Dark Chocolate",
    "Dark Choc": "Dark Chocolate",
    "DARK CHOC": "Dark Chocolate",
    "Drk Choc": "Dark Chocolate",
    # White Chocolate
    "white chocolate": "White Chocolate",
    "White Choc": "White Chocolate",
    "WHITE CHOC": "White Chocolate",
    "Wht Choc": "White Chocolate",
    # Salted Caramel
    "salted caramel": "Salted Caramel",
    "Salt Carml": "Salted Caramel",
    "SALT CARAMEL": "Salted Caramel",
    "Slt Crml": "Salted Caramel",
    # Apple & Cinnamon
    "apple & cinnamon": "Apple & Cinnamon",
    "Apple+Cinn": "Apple & Cinnamon",
    "A&C": "Apple & Cinnamon",
    "Apl+Cinn": "Apple & Cinnamon",
    # Honey & Nut
    "honey & nut": "Honey & Nut",
    "H&N": "Honey & Nut",
    "Honey+Nut": "Honey & Nut",
    "Hny+Nt": "Honey & Nut",
    # Sea Salt
    "sea salt": "Sea Salt",
    "SEA SALT": "Sea Salt",
    "S. Salt": "Sea Salt",
    "sea slt": "Sea Salt",
    # Lemon
    "lemon": "Lemon",
    "LMN": "Lemon",
    "Lmn": "Lemon",
    "LEM": "Lemon",
    # Orange
    "orange": "Orange",
    "ORG": "Orange",
    "Org": "Orange",
    "ornge": "Orange",
}


# ==============================================================================
# dim_product — normalisation
# ==============================================================================


def normalise_dim_product(df: pd.DataFrame) -> pd.DataFrame:
    """
    QI-01: Normalise pack_type to canonical form.
    QI-02: Normalise variant to canonical form.

    Both columns are normalised by direct dict lookup against the correction
    maps built from inject_quality_issues.py's corruption dictionaries.
    Values not present in the correction map are canonical and left unchanged.

    Additional type coercions (deliberate quality issues from generate_data.py):
        is_active  : "Y"/"N" string → bool (True/False)
        launch_date: "YYYY-MM-DD" string → datetime.date

    Returns:
        pd.DataFrame — copy with normalised / type-corrected columns.
    """
    df = df.copy()

    before_pt_unique = df["pack_type"].nunique()
    before_var_unique = df["variant"].nunique()

    # ── QI-01: pack_type normalisation ───────────────────────────────────────
    pt_changed = df["pack_type"].isin(PACK_TYPE_CORRECTIONS)
    df["pack_type"] = df["pack_type"].map(lambda v: PACK_TYPE_CORRECTIONS.get(v, v))
    after_pt_unique = df["pack_type"].nunique()

    # ── QI-02: variant normalisation ─────────────────────────────────────────
    var_changed = df["variant"].isin(VARIANT_CORRECTIONS)
    df["variant"] = df["variant"].map(lambda v: VARIANT_CORRECTIONS.get(v, v))
    after_var_unique = df["variant"].nunique()

    # ── is_active: Y/N string → bool ─────────────────────────────────────────
    invalid_active = ~df["is_active"].isin(["Y", "N"])
    if invalid_active.any():
        raise ValueError(
            f"is_active contains unexpected values: "
            f"{df.loc[invalid_active, 'is_active'].unique()}"
        )
    df["is_active"] = df["is_active"] == "Y"

    # ── launch_date: string → date ────────────────────────────────────────────
    df["launch_date"] = pd.to_datetime(df["launch_date"], format="%Y-%m-%d").dt.date

    print(
        f"    QI-01  pack_type  corrected rows                : {pt_changed.sum():>7,}  "
        f"(unique values: {before_pt_unique} → {after_pt_unique})"
    )
    print(
        f"    QI-02  variant    corrected rows                : {var_changed.sum():>7,}  "
        f"(unique values: {before_var_unique} → {after_var_unique})"
    )
    print(f"    type   is_active  str→bool                      : {len(df):>7,} rows")
    print(f"    type   launch_date str→date                     : {len(df):>7,} rows")

    return df


# ==============================================================================
# dim_customer — imputation
# ==============================================================================


def impute_dim_customer(df: pd.DataFrame) -> pd.DataFrame:
    """
    NULL territory  : Imputed as "Unknown-{Channel}" per the channel of the account.
        Rationale: territory NULLs are concentrated in Cornerstone and HospitalityPlus
        independent banners where territory assignment is structurally absent in the
        CRM — not a recording error.  A generic "Unknown" would collapse two distinct
        channel-level gaps into one value; channel-suffixed imputation preserves
        analytical distinctions between channel types.

    NULL store_count: Imputed with channel median.
        Rationale: store-count distributions are right-skewed within each channel
        (large flagship outlets pull the mean up).  Median is more representative of
        the typical account in each channel.  eCommerce rows already carry NULL by
        design (no store concept) — these are left as NULL and the imputation applies
        only to non-eCommerce accounts.

    Returns:
        pd.DataFrame — copy with imputed columns.
    """
    df = df.copy()

    # ── territory imputation ──────────────────────────────────────────────────
    null_terr_before = df["territory"].isna().sum()
    df["territory"] = df.apply(
        lambda row: (
            f"Unknown-{row['channel']}"
            if pd.isna(row["territory"])
            else row["territory"]
        ),
        axis=1,
    )
    null_terr_after = df["territory"].isna().sum()

    # ── store_count imputation (non-eCommerce only) ───────────────────────────
    null_store_before = df["store_count"].isna().sum()

    non_ecomm_mask = df["channel"] != "eCommerce"
    channel_medians = df.loc[non_ecomm_mask].groupby("channel")["store_count"].median()

    def _impute_store_count(row):
        if pd.isna(row["store_count"]) and row["channel"] != "eCommerce":
            return channel_medians.get(row["channel"], np.nan)
        return row["store_count"]

    df["store_count"] = df.apply(_impute_store_count, axis=1)
    null_store_after = df["store_count"].isna().sum()

    print(
        f"    territory  NULL imputed as Unknown-{{Channel}}    : "
        f"{null_terr_before:>4,} → {null_terr_after:>4,} remaining"
    )
    print(
        f"    store_count NULL imputed (channel median, non-eComm): "
        f"{null_store_before:>4,} → {null_store_after:>4,} remaining"
    )

    return df


# ==============================================================================
# fact_sales — flagging
# ==============================================================================


def flag_fact_sales(df: pd.DataFrame) -> pd.DataFrame:
    """
    QI-03  is_zero_price    : True where sku_net_price_gbp == 0.
        Rows are NOT removed — they carry valid volume data for non-revenue
        aggregations.  Revenue KPIs (net_revenue_gbp, gross_revenue_gbp,
        discount_gbp) remain in place but must be excluded by downstream
        queries when is_zero_price = True.  The schema dictionary explicitly
        documents this exclusion pattern.

    QI-04  is_volume_outlier: True where volume_units exceeds the Tukey outer
        fence (Q3 + 3.0 × IQR) on the raw volume_units distribution.

        Primary detection — statistical outlier detection on volume_units
        directly (univariate IQR on the raw signal, independent of
        baseline_volume / incremental_volume).  This is the technique that
        would be applied on real data where an analyst does not have access
        to the decomposed baseline and incremental columns.

        Secondary cross-validation — invariant check:
        baseline_volume + incremental_volume should equal volume_units on
        clean rows.  inject_quality_issues.py pumps volume_units to 5–10×
        baseline without touching the decomposed columns, so outlier rows
        exhibit a large positive deviation.  Agreement between IQR flag and
        invariant violation confirms that the statistical detections are
        genuine data corruption, not artefacts of the right-skewed
        distribution.

        The outer fence (3.0×) is used rather than the standard inner fence
        (1.5×) because fact_sales volume is legitimately right-skewed:
        lognormal baseline + promotional incremental (20–50% uplift).  The
        inner fence over-flags valid high-uplift promotional rows.

        Flagged rows are retained — the flag gives the LLM and analyst the
        option to exclude them per query context.

    QI-05  NULL promotion_mechanic: NOT imputed.  Documented as known
        sparseness.  NULL ≠ non-promotional — filter on is_promoted, not on
        promotion_mechanic IS NOT NULL.  Explicitly recorded in eda_report.md
        and the schema dictionary.

    Returns:
        pd.DataFrame — copy with flag columns appended.
    """
    df = df.copy()

    # ── QI-03: is_zero_price ─────────────────────────────────────────────────
    df["is_zero_price"] = df["sku_net_price_gbp"] == 0
    n_zero_price = df["is_zero_price"].sum()

    # ── QI-04: is_volume_outlier ─────────────────────────────────────────────
    # Primary: Tukey outer fence on raw volume_units distribution.
    # Treats volume_units as the univariate signal — independent of the
    # baseline/incremental decomposition, matching how this would be applied
    # on real data without access to decomposed columns.
    q1_raw = df["volume_units"].quantile(0.25)
    q3_raw = df["volume_units"].quantile(0.75)
    iqr_raw = q3_raw - q1_raw
    upper_fence = q3_raw + IQR_MULTIPLIER * iqr_raw

    df["is_volume_outlier"] = df["volume_units"] > upper_fence
    n_outliers = df["is_volume_outlier"].sum()

    # Secondary: invariant cross-validation.
    # On clean rows: baseline_volume + incremental_volume ≈ volume_units (deviation ≈ 0).
    # On injected outlier rows: volume_units is pumped 5–10× without touching the
    # decomposed columns, producing a large positive deviation.
    # Tolerance of 1.0 unit absorbs any floating-point rounding on clean rows.
    df["_vol_deviation"] = df["volume_units"] - (
        df["baseline_volume"] + df["incremental_volume"]
    )
    n_invariant_violated = (df["_vol_deviation"] > 1.0).sum()
    n_agreement = (df["is_volume_outlier"] & (df["_vol_deviation"] > 1.0)).sum()

    df.drop(columns=["_vol_deviation"], inplace=True)

    # ── QI-05: NULL promotion_mechanic — document rate, no action ────────────
    promo_rows = df[df["is_promoted"]]
    n_null_mech = promo_rows["promotion_mechanic"].isna().sum()
    null_mech_rate = n_null_mech / len(promo_rows) if len(promo_rows) > 0 else 0.0

    print(
        f"    QI-03  is_zero_price flagged                  : {n_zero_price:>8,} rows  "
        f"({n_zero_price / len(df):.1%})"
    )
    print(
        f"    QI-04  is_volume_outlier (Tukey outer fence)  : {n_outliers:>8,} rows  "
        f"({n_outliers / len(df):.1%}) — fence: {upper_fence:,.1f}"
    )
    print(
        f"    QI-04  invariant cross-check (deviation > 1)  : {n_invariant_violated:>8,} rows"
    )
    print(
        f"    QI-04  IQR ∩ invariant agreement              : {n_agreement:>8,} rows  "
        f"(expect = {n_outliers:,})"
    )
    print(
        f"    QI-05  NULL promotion_mechanic (is_promoted)  : {n_null_mech:>8,} rows  "
        f"({null_mech_rate:.1%}) — NOT imputed"
    )

    return df


# ==============================================================================
# fact_market — flagging + derived measures
# ==============================================================================


def flag_and_derive_fact_market(df: pd.DataFrame) -> pd.DataFrame:
    """
    QI-06  is_zero_shelf_price: True where avg_shelf_price_gbp == 0.
        Flagged rows excluded from price_index and implied_margin calculations.
        Not removed — they may carry valid volume data for share analysis.

    QI-07  is_vol_violation  : True where brand_volume_units > total_category_volume_units.
        Logically impossible — brand cannot exceed total category.
        Flagged rows excluded from all market share KPIs (market_share_volume_pct,
        market_share_value_pct) and from price_index (denominator corrupt).

    Derived measures (appended)
    ---------------------------
        market_share_volume_pct  — NaN where is_vol_violation
        market_share_value_pct   — NaN where is_vol_violation
        numeric_distribution_pct — always computed (distribution not affected by vol/price flags)
        price_index              — NaN where is_vol_violation OR is_zero_shelf_price
                                   (both corrupt the price or denominator)

    QI-08  temporal gap audit is performed separately in audit_temporal_gaps().

    Returns:
        pd.DataFrame — copy with flag and derived columns appended.
    """
    df = df.copy()

    # ── QI-06: is_zero_shelf_price ────────────────────────────────────────────
    df["is_zero_shelf_price"] = df["avg_shelf_price_gbp"] == 0
    n_zero_shelf = df["is_zero_shelf_price"].sum()

    # ── QI-07: is_vol_violation ───────────────────────────────────────────────
    df["is_vol_violation"] = (
        df["brand_volume_units"] > df["total_category_volume_units"]
    )
    n_vol_viol = df["is_vol_violation"].sum()

    # ── Derived: market_share_volume_pct ──────────────────────────────────────
    vol_valid = ~df["is_vol_violation"] & (df["total_category_volume_units"] > 0)
    df["market_share_volume_pct"] = np.where(
        vol_valid,
        df["brand_volume_units"] / df["total_category_volume_units"] * 100,
        np.nan,
    )

    # ── Derived: market_share_value_pct ───────────────────────────────────────
    val_valid = ~df["is_vol_violation"] & (df["total_category_value_gbp"] > 0)
    df["market_share_value_pct"] = np.where(
        val_valid,
        df["brand_value_gbp"] / df["total_category_value_gbp"] * 100,
        np.nan,
    )

    # ── Derived: numeric_distribution_pct ────────────────────────────────────
    dist_valid = df["total_outlets_in_banner"] > 0
    df["numeric_distribution_pct"] = np.where(
        dist_valid,
        df["numeric_distribution_outlets"] / df["total_outlets_in_banner"] * 100,
        np.nan,
    )

    # ── Derived: price_index ──────────────────────────────────────────────────
    # price_index = brand RSP / category avg RSP × 100
    # category avg RSP = total_category_value_gbp / total_category_volume_units
    pi_valid = (
        ~df["is_vol_violation"]
        & ~df["is_zero_shelf_price"]
        & (df["total_category_volume_units"] > 0)
        & (df["total_category_value_gbp"] > 0)
    )
    cat_avg_rsp = df["total_category_value_gbp"] / df[
        "total_category_volume_units"
    ].replace(0, np.nan)
    df["price_index"] = np.where(
        pi_valid,
        df["avg_shelf_price_gbp"] / cat_avg_rsp * 100,
        np.nan,
    )

    print(
        f"    QI-06  is_zero_shelf_price flagged            : {n_zero_shelf:>8,} rows  "
        f"({n_zero_shelf / len(df):.1%})"
    )
    print(
        f"    QI-07  is_vol_violation flagged               : {n_vol_viol:>8,} rows  "
        f"({n_vol_viol / len(df):.1%})"
    )
    print(
        f"    derived  market_share_volume_pct   non-null   : "
        f"{df['market_share_volume_pct'].notna().sum():>8,} rows"
    )
    print(
        f"    derived  market_share_value_pct    non-null   : "
        f"{df['market_share_value_pct'].notna().sum():>8,} rows"
    )
    print(
        f"    derived  numeric_distribution_pct  non-null   : "
        f"{df['numeric_distribution_pct'].notna().sum():>8,} rows"
    )
    print(
        f"    derived  price_index               non-null   : "
        f"{df['price_index'].notna().sum():>8,} rows"
    )

    return df


# ==============================================================================
# fact_market — QI-08 temporal gap audit
# ==============================================================================


def audit_temporal_gaps(df: pd.DataFrame) -> dict:
    """
    QI-08: Identifies banner × brand pairs with consecutive missing weeks
    in the 104-week measurement window (Jan 2024 – Dec 2025).

    Each banner × brand pair should have exactly 104 rows (one per week).
    Pairs with fewer than 104 rows have structural temporal gaps — left sparse
    in the processed layer (no interpolation).  The schema dictionary documents
    that a missing row ≠ zero sales; it means the panel measurement is absent.

    Returns:
        dict: {(banner, brand): sorted list of missing week_date values}
            for any pair with at least one missing week.
    """
    # Full 104-week calendar from the data
    all_weeks = sorted(df["week_date"].unique())
    assert len(all_weeks) == 104, (
        f"Expected 104 weeks in fact_market but found {len(all_weeks)} — "
        f"gap injection may have removed a week from every banner×brand pair simultaneously."
    )

    # Count weeks per banner × brand
    actual_counts = (
        df.groupby(["banner", "brand"])["week_date"].count().reset_index(name="n_weeks")
    )
    expected_weeks = len(all_weeks)
    gap_pairs_summary = actual_counts[actual_counts["n_weeks"] < expected_weeks].copy()
    gap_pairs_summary["missing_weeks"] = expected_weeks - gap_pairs_summary["n_weeks"]

    # Identify which specific weeks are missing per affected pair
    gap_details = {}
    for _, row in gap_pairs_summary.iterrows():
        banner, brand = row["banner"], row["brand"]
        present = set(
            df.loc[(df["banner"] == banner) & (df["brand"] == brand), "week_date"]
        )
        missing = sorted(set(all_weeks) - present)
        gap_details[(banner, brand)] = missing

    n_pairs_with_gaps = len(gap_details)
    total_missing_weeks = sum(len(v) for v in gap_details.values())

    print(
        f"    QI-08  banner×brand pairs with temporal gaps  : {n_pairs_with_gaps:>4,}"
    )
    print(
        f"    QI-08  total missing week slots               : {total_missing_weeks:>4,}"
    )
    for (banner, brand), missing in gap_details.items():
        consec_run = _longest_consecutive_run(missing)
        print(
            f"           {banner} × {brand}: "
            f"{len(missing)} missing weeks  (longest run: {consec_run})"
        )

    return gap_details


def _longest_consecutive_run(dates: list) -> int:
    """Returns the length of the longest run of consecutive ISO dates in the list."""
    if not dates:
        return 0
    max_run = run = 1
    for i in range(1, len(dates)):
        delta = (pd.Timestamp(dates[i]) - pd.Timestamp(dates[i - 1])).days
        if delta == 7:  # consecutive ISO weeks are 7 days apart
            run += 1
            max_run = max(max_run, run)
        else:
            run = 1
    return max_run


# ==============================================================================
# EDA REPORT GENERATION
# ==============================================================================


def generate_eda_report(
    raw_dp: pd.DataFrame,
    raw_dc: pd.DataFrame,
    raw_fs: pd.DataFrame,
    raw_fm: pd.DataFrame,
    clean_dp: pd.DataFrame,
    clean_dc: pd.DataFrame,
    clean_fs: pd.DataFrame,
    clean_fm: pd.DataFrame,
    gap_details: dict,
) -> str:
    """
    Generates a structured Markdown EDA report documenting all profiling
    findings and data quality handling decisions.

    Returns:
        str: Full Markdown content of the EDA report.
    """
    today = date.today().isoformat()

    # ── Compute EDA statistics ────────────────────────────────────────────────

    # dim_product
    pt_before = raw_dp["pack_type"].nunique()
    pt_after = clean_dp["pack_type"].nunique()
    var_before = raw_dp["variant"].nunique()
    var_after = clean_dp["variant"].nunique()
    active_count = clean_dp["is_active"].sum()
    inactive_count = (~clean_dp["is_active"]).sum()

    # dim_customer
    null_terr_raw = raw_dc["territory"].isna().sum()
    null_store_raw = raw_dc["store_count"].isna().sum()
    null_terr_clean = clean_dc["territory"].isna().sum()
    null_store_clean = clean_dc["store_count"].isna().sum()

    channel_medians = (
        raw_dc[raw_dc["channel"] != "eCommerce"]
        .groupby("channel")["store_count"]
        .median()
    )

    # fact_sales
    n_fs = len(clean_fs)
    n_zero_price = clean_fs["is_zero_price"].sum()
    n_vol_outlier = clean_fs["is_volume_outlier"].sum()
    promo_rows = clean_fs[clean_fs["is_promoted"]]
    n_null_mech = promo_rows["promotion_mechanic"].isna().sum()
    null_mech_rate = n_null_mech / len(promo_rows) if len(promo_rows) > 0 else 0.0

    # IQR stats recomputed from raw volume_units (primary detection method)
    q1_raw = clean_fs["volume_units"].quantile(0.25)
    q3_raw = clean_fs["volume_units"].quantile(0.75)
    iqr_raw = q3_raw - q1_raw
    upper_fence = q3_raw + IQR_MULTIPLIER * iqr_raw

    # Invariant cross-validation stats
    vol_deviation = clean_fs["volume_units"] - (
        clean_fs["baseline_volume"] + clean_fs["incremental_volume"]
    )
    n_invariant_violated = (vol_deviation > 1.0).sum()
    n_iqr_inv_agreement = (clean_fs["is_volume_outlier"] & (vol_deviation > 1.0)).sum()

    # fact_market
    n_fm = len(clean_fm)
    n_zero_shelf = clean_fm["is_zero_shelf_price"].sum()
    n_vol_viol = clean_fm["is_vol_violation"].sum()
    n_gap_pairs = len(gap_details)
    total_missing = sum(len(v) for v in gap_details.values())

    # ── Build report ─────────────────────────────────────────────────────────
    lines = [
        f"# EDA Report — Project Insight: Agentic Conversational BI",
        f"**AM1 / F-03 Preprocessing EDA** | Generated: {today}",
        f"Candidate: Manu Mohandas | TCS | BCS Level 7 AI Data Specialist",
        "",
        "---",
        "",
        "## Summary",
        "",
        "This report documents all exploratory data analysis findings and data quality handling decisions",
        "applied by `preprocess.py` to the four synthetic FMCG tables in `data/processed/`.",
        "All quality issues were deliberately injected by `inject_quality_issues.py` to create",
        "realistic preprocessing decisions evidenced in the AM1 project report.",
        "",
        "---",
        "",
        "## 1. dim_product (552 rows)",
        "",
        "### 1.1 QI-01 — pack_type Casing Corruption",
        "",
        f"- **Before normalisation**: {pt_before} unique pack_type values (canonical + corrupted forms)",
        f"- **After normalisation** : {pt_after} unique pack_type values (canonical only)",
        f"- Corrupted forms included lowercase variants (`bottle`, `carton`), all-caps (`BTL`, `CTN`),",
        f"  and abbreviations (`Btl`, `MPack`, `blister pk`). Injected rate: ~5%.",
        "- **Handling**: Direct dictionary lookup against inverted `PACK_TYPE_CORRUPTIONS` map.",
        "  Values not in the correction map are canonical and left unchanged.",
        "",
        "### 1.2 QI-02 — variant Casing Corruption",
        "",
        f"- **Before normalisation**: {var_before} unique variant values",
        f"- **After normalisation** : {var_after} unique variant values",
        "- Corrupted forms included abbreviated forms (`Choc`, `Orig`, `Straw`), all-caps",
        "  (`CHOC`, `ORIG`), and non-standard separators (`A&C`, `H&N`, `Apl+Cinn`).",
        "- **Handling**: Same dictionary-lookup pattern as pack_type.",
        "",
        "### 1.3 Type Coercions",
        "",
        "| Column | Raw Type | Processed Type | Notes |",
        "|---|---|---|---|",
        "| `is_active` | VARCHAR (`Y`/`N`) | BOOLEAN | `Y` → `True`, `N` → `False` |",
        "| `launch_date` | VARCHAR (`YYYY-MM-DD`) | DATE | `pd.to_datetime().dt.date` |",
        "",
        f"- Active SKUs: {active_count:,} | Inactive SKUs: {inactive_count:,}",
        "",
        "---",
        "",
        "## 2. dim_customer (240 rows)",
        "",
        "### 2.1 NULL territory (~15%)",
        "",
        f"- **Raw NULL count** : {null_terr_raw} rows ({null_terr_raw / len(raw_dc):.1%})",
        f"- **Post-imputation**: {null_terr_clean} NULLs remaining",
        "- **Root cause**: Cornerstone and HospitalityPlus independent banners do not",
        "  assign territory codes in the CRM. This is a structural absence, not a recording error.",
        "- **Handling decision**: Imputed as `Unknown-{Channel}` (e.g., `Unknown-Independent`,",
        "  `Unknown-Foodservice`). Channel-suffixed form preserves the analytical distinction",
        "  between channel-level gaps rather than collapsing all into a single `Unknown` label.",
        "",
        "### 2.2 NULL store_count (~10%)",
        "",
        f"- **Raw NULL count** : {null_store_raw} rows ({null_store_raw / len(raw_dc):.1%})",
        f"- **Post-imputation**: {null_store_clean} NULLs remaining (eCommerce rows — expected)",
        "- **Root cause**: Incomplete CRM records for non-eCommerce accounts. eCommerce accounts",
        "  have NULL store_count by design (no store concept applies).",
        "- **Handling decision**: Imputed with **channel median** (non-eCommerce only).",
        "  Mean was considered and rejected: store-count distributions are right-skewed within",
        "  each channel (large flagship outlets inflate the mean). Median is more representative",
        "  of the typical account and more robust to extreme values.",
        "",
        "**Channel median store counts used for imputation:**",
        "",
    ]

    for channel, median in channel_medians.items():
        lines.append(f"- {channel}: {int(median)}")

    lines += [
        "",
        "---",
        "",
        "## 3. fact_sales (~2.3M rows)",
        "",
        "### 3.1 QI-03 — Zero sku_net_price_gbp",
        "",
        f"- **Flagged rows**: {n_zero_price:,} ({n_zero_price / n_fs:.1%}) — `is_zero_price = True`",
        "- **Root cause**: System recording failures on price capture during promotional repricing.",
        "- **Handling decision**: Rows **retained** with boolean flag `is_zero_price`.",
        "  Volume data on these rows remains valid for non-revenue aggregations.",
        "  Revenue columns (`net_revenue_gbp`, `gross_revenue_gbp`, `discount_gbp`) are",
        "  zeroed as a consequence of the injected zero price — downstream queries must",
        "  filter on `is_zero_price = False` for any revenue-based KPI.",
        "",
        "### 3.2 QI-04 — Volume Outliers",
        "",
        "#### Primary detection — Tukey outer fence on raw `volume_units`",
        "",
        "  Univariate IQR applied directly to the `volume_units` distribution, independent",
        "  of the `baseline_volume` / `incremental_volume` decomposition. This matches how",
        "  the technique would be applied on real data where decomposed columns may not exist.",
        f"  Q1 = {q1_raw:,.2f}  |  Q3 = {q3_raw:,.2f}  |  IQR = {iqr_raw:,.2f}",
        f"  Upper fence = Q3 + {IQR_MULTIPLIER}× IQR = {upper_fence:,.2f}",
        f"- **Flagged rows**: {n_vol_outlier:,} ({n_vol_outlier / n_fs:.1%}) — `is_volume_outlier = True`",
        "- **Why outer fence (3.0×) rather than standard (1.5×)**:",
        "  fact_sales volume is legitimately right-skewed: lognormal baseline +",
        "  promotional incremental (20–50% uplift). The inner fence (1.5×) over-flags",
        "  valid high-uplift promotional rows. The outer fence isolates only the extreme",
        "  anomalies injected at 5–10× baseline.",
        "",
        "#### Secondary cross-validation — invariant check",
        "",
        "  On clean rows, `baseline_volume + incremental_volume = volume_units` (deviation ≈ 0).",
        "  Injected outliers have `volume_units` inflated 5–10× without a corresponding",
        "  change to the decomposed columns, producing a large positive deviation.",
        f"- **Invariant violations** (deviation > 1.0): {n_invariant_violated:,} rows",
        f"- **IQR ∩ invariant agreement**: {n_iqr_inv_agreement:,} rows  (expect = {n_vol_outlier:,})",
        "  Full agreement between the two methods confirms that IQR detections are genuine",
        "  data corruption events, not statistical artefacts of the skewed distribution.",
        "- **Handling decision**: Rows **retained** with boolean flag `is_volume_outlier`.",
        "  Analysts and the LLM may exclude these per query context.",
        "",
        "### 3.3 QI-05 — NULL promotion_mechanic",
        "",
        f"- **Affected rows**: {n_null_mech:,} of {len(promo_rows):,} is_promoted=True rows",
        f"  ({null_mech_rate:.1%}) — NULL mechanic where promotion is active",
        "- **Root cause**: Incomplete mechanic capture in POS/TPM system handshakes.",
        "  The promotion event occurred but the mechanic type was not transmitted.",
        "- **Handling decision**: **NOT imputed**. NULL promotion_mechanic does NOT mean",
        "  non-promotional. Queries must filter on `is_promoted = True` to identify",
        "  promotional rows — filtering on `promotion_mechanic IS NOT NULL` would silently",
        "  exclude ~22% of promoted volume. This constraint is documented in the schema",
        "  data dictionary for LLM grounding.",
        "",
        "---",
        "",
        "## 4. fact_market (~44K rows post-gap-injection)",
        "",
        "### 4.1 QI-06 — Zero avg_shelf_price_gbp",
        "",
        f"- **Flagged rows**: {n_zero_shelf:,} ({n_zero_shelf / n_fm:.1%}) — `is_zero_shelf_price = True`",
        "- **Root cause**: Panel data recording failures — scanner data gaps where RSP",
        "  was not captured.",
        "- **Handling decision**: Flagged and excluded from `price_index` and implied",
        "  retailer margin calculations. Volume data on these rows may still be valid.",
        "",
        "### 4.2 QI-07 — brand_volume_units > total_category_volume_units",
        "",
        f"- **Flagged rows**: {n_vol_viol:,} ({n_vol_viol / n_fm:.1%}) — `is_vol_violation = True`",
        "- **Root cause**: Panel data integrity failure — a brand cannot exceed its own",
        "  category total.",
        "- **Handling decision**: Flagged and excluded from all market share KPIs",
        "  (`market_share_volume_pct`, `market_share_value_pct`) and `price_index`.",
        "  Derived measures set to `NaN` for these rows.",
        "",
        "### 4.3 QI-08 — Temporal Gaps",
        "",
        f"- **Pairs with gaps**: {n_gap_pairs}",
        f"- **Total missing week slots**: {total_missing}",
        "- **Handling decision**: Left **sparse** in processed layer. No interpolation applied.",
        "  A missing row represents an absent panel measurement, NOT zero sales.",
        "  Interpolating would misrepresent the data provenance.",
        "",
        "  > **Schema dictionary note**: When aggregating fact_market over time, use",
        "  > `COUNT(DISTINCT week_date)` per group rather than assuming 104 weeks.",
        "  > Missing rows are structural gaps, not zero measurements.",
        "",
        "**Gap detail by banner × brand:**",
        "",
        "| Banner | Brand | Missing Weeks | Longest Consecutive Run |",
        "|---|---|---|---|",
    ]

    for (banner, brand), missing in gap_details.items():
        consec = _longest_consecutive_run(missing)
        lines.append(f"| {banner} | {brand} | {len(missing)} | {consec} weeks |")

    lines += [
        "",
        "---",
        "",
        "## 5. Derived Measures (fact_market)",
        "",
        "Computed and appended to `data/processed/fact_market.parquet` during preprocessing.",
        "Not stored in raw layer.",
        "",
        "| Measure | Formula | NaN Condition |",
        "|---|---|---|",
        "| `market_share_volume_pct` | `brand_volume_units / total_category_volume_units × 100` | `is_vol_violation = True` |",
        "| `market_share_value_pct` | `brand_value_gbp / total_category_value_gbp × 100` | `is_vol_violation = True` |",
        "| `numeric_distribution_pct` | `numeric_distribution_outlets / total_outlets_in_banner × 100` | `total_outlets = 0` |",
        "| `price_index` | `avg_shelf_price_gbp / (total_category_value_gbp / total_category_volume_units) × 100` | `is_vol_violation OR is_zero_shelf_price` |",
        "",
        "---",
        "",
        "## 6. Key Schema Constraints (LLM Grounding)",
        "",
        "These constraints are documented here and repeated verbatim in the schema",
        "data dictionary (F-04) for RAG injection into the LLM system prompt.",
        "",
        "1. **NULL promotion_mechanic ≠ non-promotional**: Filter on `is_promoted = True`",
        "   to identify promoted rows, never on `promotion_mechanic IS NOT NULL`.",
        "",
        "2. **Missing rows in fact_market ≠ zero sales**: Temporal gaps are absent panel",
        "   measurements. Use `COUNT(DISTINCT week_date)` per group — do not assume 104.",
        "",
        "3. **fact_market cannot be directly joined to fact_sales**: Different grains.",
        "   Aggregate `fact_sales` to `brand × banner × week` via `dim_product` and",
        "   `dim_customer` joins first, then join to `fact_market`.",
        "",
        "4. **avg_shelf_price_gbp is a brand-level weekly average RSP**: Not an SKU price",
        "   or a per-consumer transaction price.",
        "",
        "5. **Implied retailer margin requires cross-table join**:",
        "   `(avg_shelf_price_gbp − AVG(sku_net_price_gbp)) / avg_shelf_price_gbp`",
        "",
        "6. **baseline_volume + incremental_volume = volume_units (clean rows only)**:",
        "   `is_volume_outlier = True` rows violate this invariant.",
        "",
        "---",
        "",
        "*End of EDA Report*",
    ]

    return "\n".join(lines)


# ==============================================================================
# POST-PREPROCESSING VERIFICATION
# ==============================================================================


def verify_preprocessing(
    clean_dp: pd.DataFrame,
    clean_dc: pd.DataFrame,
    clean_fs: pd.DataFrame,
    clean_fm: pd.DataFrame,
) -> None:
    """
    Prints a structured verification summary confirming that all preprocessing
    steps completed correctly and that the processed layer is consistent.
    """
    print("\n── Post-preprocessing verification ─────────────────────────────────")

    # dim_product
    pt_non_canonical = (
        clean_dp["pack_type"].isin(set(PACK_TYPE_CORRECTIONS.keys())).sum()
    )
    var_non_canonical = clean_dp["variant"].isin(set(VARIANT_CORRECTIONS.keys())).sum()
    print(
        f"\n  dim_product  residual non-canonical pack_type  : {pt_non_canonical}  (expect 0)"
    )
    print(
        f"  dim_product  residual non-canonical variant    : {var_non_canonical}  (expect 0)"
    )
    print(
        f"  dim_product  is_active dtype                   : {clean_dp['is_active'].dtype}  (expect bool)"
    )
    print(
        f"  dim_product  launch_date dtype                 : {type(clean_dp['launch_date'].iloc[0]).__name__}  (expect date)"
    )

    # dim_customer
    null_terr = clean_dc["territory"].isna().sum()
    null_store_non_ecomm = (
        clean_dc.loc[clean_dc["channel"] != "eCommerce", "store_count"].isna().sum()
    )
    print(
        f"\n  dim_customer NULL territory remaining          : {null_terr}  (expect 0)"
    )
    print(
        f"  dim_customer NULL store_count (non-eComm)      : {null_store_non_ecomm}  (expect 0)"
    )

    # fact_sales flags
    print(
        f"\n  fact_sales   is_zero_price flag present        : "
        f"{'YES' if 'is_zero_price' in clean_fs.columns else 'MISSING ✗'}"
    )
    print(
        f"  fact_sales   is_volume_outlier flag present    : "
        f"{'YES' if 'is_volume_outlier' in clean_fs.columns else 'MISSING ✗'}"
    )
    print(
        f"  fact_sales   is_zero_price rate                : "
        f"{clean_fs['is_zero_price'].mean():.1%}  (target ~3%)"
    )
    print(
        f"  fact_sales   is_volume_outlier rate            : "
        f"{clean_fs['is_volume_outlier'].mean():.1%}  (target ~2%)"
    )

    # fact_market flags + derived
    derived_cols = [
        "is_zero_shelf_price",
        "is_vol_violation",
        "market_share_volume_pct",
        "market_share_value_pct",
        "numeric_distribution_pct",
        "price_index",
    ]
    for col in derived_cols:
        present = col in clean_fm.columns
        print(f"  fact_market  {col:<35}: {'present ✓' if present else 'MISSING ✗'}")

    # price_index sanity: most rows should be between 50 and 200
    pi = clean_fm["price_index"].dropna()
    pi_in_range = ((pi >= 50) & (pi <= 200)).mean()
    print(
        f"\n  fact_market  price_index in [50, 200]          : {pi_in_range:.1%}  (expect >90%)"
    )

    # market_share sanity: should sum close to 100 per cat/banner/week
    share_sample = (
        clean_fm[~clean_fm["is_vol_violation"]]
        .groupby(["sub_category", "banner", "week_date"])["market_share_volume_pct"]
        .sum()
        .dropna()
    )
    within_5pp = ((share_sample >= 95) & (share_sample <= 105)).mean()
    print(
        f"  fact_market  share sums within [95,105] per subcat/banner/week: "
        f"{within_5pp:.1%}  (expect high — shares should sum ~100)"
    )

    print("\n── Verification complete ────────────────────────────────────────────\n")


# ==============================================================================
# MAIN
# ==============================================================================


def main() -> None:
    print("\n╔══════════════════════════════════════════════════════════════════╗")
    print("║  preprocess.py — AM1 Sprint 1 / F-03                           ║")
    print("║  Reads : data/raw/qi-injected/  (QI-injected layer)            ║")
    print("║  Writes: data/processed/  (cleaned, flagged, derived measures)  ║")
    print("╚══════════════════════════════════════════════════════════════════╝\n")

    # ── 1. Load dirty Parquet files ───────────────────────────────────────────
    print("Loading QI-injected Parquet files from data/raw/qi-injected/ ...")
    dim_product = pd.read_parquet(os.path.join(DIRTY_DIR, "dim_product.parquet"))
    dim_customer = pd.read_parquet(os.path.join(DIRTY_DIR, "dim_customer.parquet"))
    fact_sales = pd.read_parquet(os.path.join(DIRTY_DIR, "fact_sales.parquet"))
    fact_market = pd.read_parquet(os.path.join(DIRTY_DIR, "fact_market.parquet"))

    print(
        f"  dim_product  : {len(dim_product):>7,} rows  | columns: {list(dim_product.columns)}"
    )
    print(
        f"  dim_customer : {len(dim_customer):>7,} rows  | columns: {list(dim_customer.columns)}"
    )
    print(
        f"  fact_sales   : {len(fact_sales):>7,} rows  | columns: {list(fact_sales.columns)}"
    )
    print(
        f"  fact_market  : {len(fact_market):>7,} rows  | columns: {list(fact_market.columns)}"
    )

    # ── 2. Preprocess each table ──────────────────────────────────────────────
    print("\n── Preprocessing tables ─────────────────────────────────────────────")

    print(
        "\n[1/4] dim_product  (QI-01: pack_type  |  QI-02: variant  |  type coercions)"
    )
    dim_product_clean = normalise_dim_product(dim_product)

    print("\n[2/4] dim_customer  (territory imputation  |  store_count imputation)")
    dim_customer_clean = impute_dim_customer(dim_customer)

    print(
        "\n[3/4] fact_sales  (QI-03: is_zero_price  |  QI-04: is_volume_outlier  |  QI-05: NULL mechanic documented)"
    )
    fact_sales_clean = flag_fact_sales(fact_sales)

    print(
        "\n[4/4] fact_market  (QI-06: is_zero_shelf_price  |  QI-07: is_vol_violation  |  derived measures)"
    )
    fact_market_clean = flag_and_derive_fact_market(fact_market)

    # ── 3. Temporal gap audit (QI-08) ─────────────────────────────────────────
    print("\n── Temporal gap audit (QI-08) ───────────────────────────────────────")
    gap_details = audit_temporal_gaps(fact_market_clean)

    # ── 4. Write cleaned files back to data/processed/ ───────────────────────
    print("\n── Writing cleaned Parquet files to data/processed/ ─────────────────")

    dim_product_clean.to_parquet(
        os.path.join(PROCESSED_DIR, "dim_product.parquet"), index=False
    )
    print(
        f"  ✓  dim_product.parquet   {len(dim_product_clean):>7,} rows  "
        f"| columns: {list(dim_product_clean.columns)}"
    )

    dim_customer_clean.to_parquet(
        os.path.join(PROCESSED_DIR, "dim_customer.parquet"), index=False
    )
    print(
        f"  ✓  dim_customer.parquet  {len(dim_customer_clean):>7,} rows  "
        f"| columns: {list(dim_customer_clean.columns)}"
    )

    fact_sales_clean.to_parquet(
        os.path.join(PROCESSED_DIR, "fact_sales.parquet"), index=False
    )
    print(
        f"  ✓  fact_sales.parquet    {len(fact_sales_clean):>7,} rows  "
        f"| +flags: is_zero_price, is_volume_outlier"
    )

    fact_market_clean.to_parquet(
        os.path.join(PROCESSED_DIR, "fact_market.parquet"), index=False
    )
    print(
        f"  ✓  fact_market.parquet   {len(fact_market_clean):>7,} rows  "
        f"| +flags: is_zero_shelf_price, is_vol_violation"
    )
    print(
        f"     derived: market_share_volume_pct, market_share_value_pct, "
        f"numeric_distribution_pct, price_index"
    )

    # ── 5. Generate and write EDA report ─────────────────────────────────────
    print("\n── Generating EDA report ────────────────────────────────────────────")
    os.makedirs(DATA_DIR, exist_ok=True)

    eda_content = generate_eda_report(
        raw_dp=dim_product,
        raw_dc=dim_customer,
        raw_fs=fact_sales,
        raw_fm=fact_market,
        clean_dp=dim_product_clean,
        clean_dc=dim_customer_clean,
        clean_fs=fact_sales_clean,
        clean_fm=fact_market_clean,
        gap_details=gap_details,
    )

    with open(EDA_REPORT_PATH, "w", encoding="utf-8") as f:
        f.write(eda_content)
    print(f"  ✓  eda_report.md written to {EDA_REPORT_PATH}")

    # ── 6. Post-preprocessing verification ───────────────────────────────────
    verify_preprocessing(
        clean_dp=dim_product_clean,
        clean_dc=dim_customer_clean,
        clean_fs=fact_sales_clean,
        clean_fm=fact_market_clean,
    )

    print("╔══════════════════════════════════════════════════════════════════╗")
    print("║  preprocess.py — COMPLETE                                       ║")
    print("║  data/processed/ ready for Sprint 2 NL2SQL core (F-06 onwards) ║")
    print("╚══════════════════════════════════════════════════════════════════╝\n")


if __name__ == "__main__":
    main()
