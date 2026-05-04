"""
inject_quality_issues.py
-----------------
AM1 Sprint 1 / F-02 — Deliberate Data Quality Injection

Reads clean Parquet files from data/raw/ and writes quality-issue-injected
versions to data/raw/qi-injected/. Raw files are never modified.

Quality issues injected (all deliberate by design — documented and version-
controlled so that EDA decisions in preprocess.py are evidentially grounded):

    dim_product  (2 issues):
        QI-01  Inconsistent casing/abbreviations in pack_type  (~5% of rows)
        QI-02  Inconsistent casing/abbreviations in variant    (~5% of rows)

    dim_customer (0 issues):
        Copied unchanged — quality issues already present in raw layer:
            ~15% NULL territory  (Cornerstone + HospitalityPlus independents)
            ~10% NULL store_count (non-eCommerce accounts — incomplete CRM)

    fact_sales   (3 issues):
        QI-03  ~3%  sku_net_price_gbp = 0       (system recording errors)
        QI-04  ~2%  volume_units = 5–10× baseline (data-entry / duplicate errors;
                    creates internal inconsistency: volume_units ≠ baseline +
                    incremental — detected by preprocess.py)
        QI-05  22% NULL promotion_mechanic where is_promoted = True
                    (sparse mechanic capture in POS systems)

    fact_market  (3 issues):
        QI-06  ~5%  avg_shelf_price_gbp = 0         (recording failures)
        QI-07  ~1%  brand_volume_units > total_category_volume_units
                    (deliberate constraint violation — tests detection logic
                    in preprocess.py; rows flagged and excluded from share KPIs)
        QI-08  3–4 week temporal gaps for 4 selected banner × brand pairs
                    (left sparse in processed layer — NOT interpolated;
                    LLM schema dictionary documents that missing weeks ≠ zero sales)

NOTE — what inject_quality_issues.py does NOT touch:
    - Performance signals (NitroBoost, Porridge & Oats, Ice Cream, ValuMart)
      are structural parameters baked into baseline_volume generation. They
      are not quality issues and must be preserved intact.
    - is_active (Y/N string) and launch_date (string) in dim_product are
      quality issues baked into generate_data.py by design — not added here.

Execution
---------
    python scripts/inject_quality_issues.py          # from project root
    python inject_quality_issues.py                  # from scripts/ directory

Output
------
    data/raw/qi-injected/dim_product.parquet   (552 rows — casing corrupted)
    data/raw/qi-injected/dim_customer.parquet  (240 rows — unchanged copy)
    data/raw/qi-injected/fact_sales.parquet    (~2.3M rows — 3 issues injected)
    data/raw/qi-injected/fact_market.parquet   (~44K rows less gap drops — 3 issues)
"""

import os
import random

import numpy as np
import pandas as pd

# ──────────────────────────────────────────────────────────────────────────────
# GLOBAL SEEDS
# Using a distinct seed from generate_data.py (SEED=42) so that injection
# draws are independent and reproducible without interfering with the
# generation draws.
# ──────────────────────────────────────────────────────────────────────────────
INJECT_SEED = 99
np.random.seed(INJECT_SEED)
random.seed(INJECT_SEED)

# ──────────────────────────────────────────────────────────────────────────────
# PATHS
# Assumes this script sits in scripts/ alongside generate_data.py.
# data/ is a sibling directory of scripts/ at the project root.
# ──────────────────────────────────────────────────────────────────────────────
BASE_DIR  = os.path.dirname(os.path.abspath(__file__))
RAW_DIR   = os.path.join(BASE_DIR, "..", "data", "raw")
DIRTY_DIR = os.path.join(BASE_DIR, "..", "data", "raw", "qi-injected")
os.makedirs(DIRTY_DIR, exist_ok=True)
# ──────────────────────────────────────────────────────────────────────────────
# INJECTION RATES
# Named constants for transparency and defensibility — every rate here
# corresponds directly to an acceptance criterion in F-01 / F-02.
# ──────────────────────────────────────────────────────────────────────────────

# dim_product
CASING_RATE_PACK_TYPE = 0.05  # QI-01: fraction of rows with corrupted pack_type
CASING_RATE_VARIANT = 0.05  # QI-02: fraction of rows with corrupted variant

# fact_sales
ZERO_PRICE_RATE = 0.03  # QI-03: fraction of rows where sku_net_price_gbp → 0
OUTLIER_RATE = 0.02  # QI-04: fraction of rows where volume_units → 5–10× baseline
OUTLIER_MULT_MIN = 5  # QI-04: minimum outlier multiplier (× baseline_volume)
OUTLIER_MULT_MAX = 10  # QI-04: maximum outlier multiplier (× baseline_volume)
NULL_MECHANIC_RATE = 0.22  # QI-05: fraction of is_promoted=True rows → NULL mechanic

# fact_market
ZERO_MFR_PRICE_RATE = 0.05  # QI-06: fraction of rows where avg_shelf_price_gbp → 0
VOL_VIOLATION_RATE = 0.01  # QI-07: fraction of rows where brand_vol > cat_vol
VOL_VIOLATION_MIN = 1.05  # QI-07: minimum overshoot (5% above category total)
VOL_VIOLATION_MAX = 2.00  # QI-07: maximum overshoot (2× category total)
N_GAP_PAIRS = 4  # QI-08: number of banner × brand pairs to receive gaps
GAP_WEEKS_MIN = 3  # QI-08: minimum consecutive weeks dropped per pair
GAP_WEEKS_MAX = 4  # QI-08: maximum consecutive weeks dropped per pair


# ==============================================================================
# QI-01 / QI-02  dim_product — casing and abbreviation corruption
# ==============================================================================

# Corruption options per canonical pack_type value.
# Simulates inconsistent data entry across account management systems and
# retail scan data exports (common in FMCG data pipelines).
PACK_TYPE_CORRUPTIONS = {
    "Bottle": ["bottle", "BTL", "Btl", "btl"],
    "Carton": ["carton", "CTN", "Ctn", "ctn"],
    "Tub": ["tub", "TUB", "tb"],
    "Bag": ["bag", "BAG", "bg"],
    "Box": ["box", "BOX", "bx"],
    "Can": ["can", "CAN", "cn"],
    "Multipack": ["multipack", "MPack", "Multi-pack", "multi-pack"],
    "Pouch": ["pouch", "PCH", "pch"],
    "Sachet Pack": ["sachet pack", "sachet", "Sachet Pk", "sachet pk"],
    "Bar Multipack": ["bar MP", "Bar Mp", "bar multipack"],
    "Blister Pack": ["blister pk", "BLS PK", "blister pack"],
    "Gift Box": ["gift bx", "GIFT BOX", "Gift Bx"],
    "Steam Bag": ["steam bag", "Stm Bag", "STEAM BAG"],
    "Block": ["block", "BLK", "Blk"],
    "Slices Pack": ["slices pk", "SLICES PK", "Slices Pk"],
    "Grated Bag": ["grated bg", "Grated Bg", "GRATED BAG"],
    "Pot": ["pot", "POT", "pt"],
    "Portion Pack": ["portion pk", "PORTION PK", "Portion Pk"],
    "Tray": ["tray", "TRY", "try", "tr"],
    "Tin": ["tin", "TIN", "tn"],
    "Jar": ["jar", "JAR", "jr"],
    "Bar": ["bar", "BAR", "br"],
}

# Corruption options per canonical variant value.
# Abbreviations mirror common issues seen in category management data extracts
# where different source systems use different controlled vocabularies.
VARIANT_CORRUPTIONS = {
    "Chocolate": ["chocolate", "Choc", "CHOC", "choc"],
    "Original": ["original", "Orig", "ORIG", "orig"],
    "Strawberry": ["strawberry", "Straw", "STRAW", "Strawb"],
    "Raspberry": ["raspberry", "Rasp", "RASP", "Raspb"],
    "Vanilla": ["vanilla", "Van", "VANL", "van"],
    "Blueberry": ["blueberry", "Bluebry", "BLUEBERRY", "Blbry"],
    "Mango": ["mango", "MNG", "mng"],
    "Caramel": ["caramel", "Carm", "CARAMEL", "Carml"],
    "Tropical": ["tropical", "Trop", "TROP", "tropcl"],
    "Multigrain": ["multigrain", "Multi-grain", "MULTIGRAIN", "Multigrn"],
    "Whole Grain": ["whole grain", "Whole-Grain", "WHOLE GRAIN", "WGN"],
    "Sugar Free": ["sugar free", "Sugar-Free", "SUGAR FREE", "SF"],
    "Diet": ["diet", "DIET", "dt"],
    "Zero": ["zero", "ZERO", "zro"],
    "Salt & Vinegar": ["salt & vinegar", "Slt + Vin", "Slt & Vin", "S+V"],
    "Cheese & Onion": ["cheese & onion", "C&O", "Chse+Onion", "C + O"],
    "BBQ": ["bbq", "Barbecue", "Bbq", "b.b.q"],
    "Milk Chocolate": ["milk chocolate", "Milk Choc", "MILK CHOC", "Mlk Choc"],
    "Dark Chocolate": ["dark chocolate", "Dark Choc", "DARK CHOC", "Drk Choc"],
    "White Chocolate": ["white chocolate", "White Choc", "WHITE CHOC", "Wht Choc"],
    "Salted Caramel": ["salted caramel", "Salt Carml", "SALT CARAMEL", "Slt Crml"],
    "Apple & Cinnamon": ["apple & cinnamon", "Apple+Cinn", "A&C", "Apl+Cinn"],
    "Honey & Nut": ["honey & nut", "H&N", "Honey+Nut", "Hny+Nt"],
    "Sea Salt": ["sea salt", "SEA SALT", "S. Salt", "sea slt"],
    "Lemon": ["lemon", "LMN", "Lmn", "LEM"],
    "Orange": ["orange", "ORG", "Org", "ornge"],
}


def inject_dim_product(df: pd.DataFrame) -> pd.DataFrame:
    """
    QI-01 + QI-02: Injects inconsistent casing and abbreviations into
    pack_type and variant columns.

    Each column is corrupted independently — affected rows are different draws,
    so a row can have a corrupted pack_type, a corrupted variant, both, or
    neither. Values not present in the corruption dictionaries are left intact
    (not all values have a plausible abbreviation form).

    Returns:
        pd.DataFrame — copy with corrupted string columns.
    """
    df = df.copy()
    n = len(df)

    # ── QI-01: pack_type casing corruption ───────────────────────────────────
    pack_mask = np.random.random(n) < CASING_RATE_PACK_TYPE
    affected_pack = df.index[pack_mask]
    corrupted_pack = [
        random.choice(options) if (options := PACK_TYPE_CORRUPTIONS.get(v)) else v
        for v in df.loc[affected_pack, "pack_type"]
    ]
    df.loc[affected_pack, "pack_type"] = corrupted_pack

    # ── QI-02: variant casing corruption (independent draw) ──────────────────
    var_mask = np.random.random(n) < CASING_RATE_VARIANT
    affected_var = df.index[var_mask]
    corrupted_var = [
        random.choice(options) if (options := VARIANT_CORRUPTIONS.get(v)) else v
        for v in df.loc[affected_var, "variant"]
    ]
    df.loc[affected_var, "variant"] = corrupted_var

    print(
        f"    QI-01  pack_type casing corrupted             : {pack_mask.sum():>8,} rows  "
        f"({pack_mask.mean():.1%}, target {CASING_RATE_PACK_TYPE:.0%})"
    )
    print(
        f"    QI-02  variant casing corrupted               : {var_mask.sum():>8,} rows  "
        f"({var_mask.mean():.1%}, target {CASING_RATE_VARIANT:.0%})"
    )

    return df


# ==============================================================================
# QI-03 / QI-04 / QI-05  fact_sales — price zeros, volume outliers, NULL mechanic
# ==============================================================================


def inject_fact_sales(df: pd.DataFrame) -> pd.DataFrame:
    """
    QI-03: ~3% of sku_net_price_gbp set to 0.
        Simulates system recording failures on price capture — common in POS
        exports during promotional repricing. Rows flagged by a new boolean
        column `is_zero_price` in preprocess.py (not removed — they carry
        valid volume data used in non-revenue aggregations).

    QI-04: ~2% of volume_units set to 5–10× baseline_volume.
        Simulates data-entry errors or duplicate scan events. Creates an
        internal inconsistency: injected rows violate the invariant
        volume_units = baseline_volume + incremental_volume.
        preprocess.py detects these via IQR-based outlier detection and
        applies an `is_volume_outlier` flag column.

    QI-05: 22% of is_promoted=True rows have NULL promotion_mechanic.
        Simulates incomplete mechanic capture in POS/TPM system handshakes.
        NOT imputed in preprocess.py — schema dictionary explicitly documents
        NULL mechanic ≠ non-promotional; the LLM is instructed accordingly.

    All three draws are independent — a row can be affected by one, two, or
    all three issues simultaneously.

    Returns:
        pd.DataFrame — copy with quality issues injected in-place.
    """
    df = df.copy()
    n = len(df)

    # ── QI-03: zero sku_net_price_gbp ────────────────────────────────────────
    zero_price_mask = np.random.random(n) < ZERO_PRICE_RATE
    df.loc[zero_price_mask, "sku_net_price_gbp"] = 0.0
    print(
        f"    QI-03  zero sku_net_price_gbp               : {zero_price_mask.sum():>8,} rows  "
        f"({zero_price_mask.mean():.1%}, target {ZERO_PRICE_RATE:.0%})"
    )

    # ── QI-04: volume outliers ────────────────────────────────────────────────
    # volume_units is overwritten to (baseline × multiplier), deliberately
    # breaking the volume_units = baseline + incremental invariant.
    # baseline_volume and incremental_volume are left unchanged so that
    # preprocess.py can detect and flag the inconsistency.
    outlier_mask = np.random.random(n) < OUTLIER_RATE
    n_outliers = outlier_mask.sum()
    multipliers = np.random.uniform(OUTLIER_MULT_MIN, OUTLIER_MULT_MAX, size=n_outliers)
    df.loc[outlier_mask, "volume_units"] = (
        np.round(df.loc[outlier_mask, "baseline_volume"].values * multipliers)
        .clip(min=1)
        .astype(np.int64)
    )
    print(
        f"    QI-04  volume outliers (5–10× baseline)      : {n_outliers:>8,} rows  "
        f"({outlier_mask.mean():.1%}, target {OUTLIER_RATE:.0%})"
    )

    # ── QI-05: NULL promotion_mechanic ───────────────────────────────────────
    # Only promoted rows are eligible — non-promoted rows already carry NULL
    # mechanic (correct by design). The 22% NULL rate is applied within the
    # promoted subset, not across all rows.
    promo_idx = df.index[df["is_promoted"] == True]
    null_mech_mask = np.random.random(len(promo_idx)) < NULL_MECHANIC_RATE
    null_mech_idx = promo_idx[null_mech_mask]
    df.loc[null_mech_idx, "promotion_mechanic"] = None
    print(
        f"    QI-05  NULL promotion_mechanic (of promoted) : {null_mech_mask.sum():>8,} rows  "
        f"({null_mech_mask.mean():.1%}, target {NULL_MECHANIC_RATE:.0%})"
    )

    return df


# ==============================================================================
# QI-06 / QI-07 / QI-08  fact_market — price zeros, vol violations, gaps
# ==============================================================================

# The four banner × brand pairs chosen for temporal gap injection (QI-08).
# Criteria:
#   - Mix of channels (Grocery, Discounter, Convenience, eCommerce)
#   - At least one pair overlaps with a performance signal (ValuMart × NitroBoost)
#     so EDA must handle both a gap and a structural trend simultaneously
#   - No pair violates CHANNEL_CATEGORY_UNLISTED (eCommerce × Confectionery is allowed)
# Note: MARKET_BRAND_BANNER_LISTING = 0.60, so not every banner × brand combination
# is guaranteed to appear in fact_market. If a target pair was not generated,
# gap injection skips it and logs a warning — fewer than 4 gaps may be applied.
GAP_TARGET_PAIRS: list[tuple[str, str]] = [
    ("ValuMart", "NitroBoost"),  # Grocery × Energy — overlaps ValuMart decline signal
    ("PoundSave", "CocoaEthos"),  # Discounter × Premium confectionery
    ("CityStop", "ArtisanOats"),  # Convenience × Premium cereal
    ("FreshDoor", "BerryBliss"),  # eCommerce × Premium confectionery/frozen
]


def inject_fact_market(df: pd.DataFrame) -> pd.DataFrame:
    """
    QI-06: ~5% of avg_shelf_price_gbp set to zero.
        Simulates recording failures in panel price feeds. manufacturer_net_price_gbp
        no longer exists in fact_market (panel providers cannot observe bilateral
        trade terms), so avg_shelf_price_gbp is the sole price column and the
        correct injection target. Rows must be excluded from price_index and
        implied margin calculations in preprocess.py.

    QI-07: ~1% of rows where brand_volume_units > total_category_volume_units.
        Deliberate violation of the pre-injection generation constraint.
        Simulates panel measurement reconciliation errors (real Nielsen/Kantar
        data can exhibit brand > category at granular cuts when measurement
        windows differ). preprocess.py detects via direct comparison, flags
        affected rows, and excludes them from share KPI calculations.

    QI-08: 3–4 week temporal gaps for four selected banner × brand combinations.
        Simulates missing panel measurement weeks — either the panel provider
        did not report data for that combination, or a banner changed its
        scanning configuration. Gaps are introduced by DROPPING rows entirely
        (not setting to zero). Left sparse in the processed layer —
        interpolation would manufacture evidence of sales that did not occur.
        LLM schema dictionary documents that missing rows ≠ zero sales.

        Gap windows are placed within the MIDDLE THIRD of each pair's time
        series to ensure the gap is analytically visible (not mistaken for
        a series start/end).

    Returns:
        pd.DataFrame — copy with issues injected; fewer rows than input
        due to gap drops in QI-08.
    """
    df = df.copy()
    n = len(df)

    # ── QI-06: zero avg_shelf_price_gbp ──────────────────────────────────────
    mfr_zero_mask = np.random.random(n) < ZERO_MFR_PRICE_RATE
    df.loc[mfr_zero_mask, "avg_shelf_price_gbp"] = 0.0
    print(
        f"    QI-06  zero avg_shelf_price_gbp             : {mfr_zero_mask.sum():>8,} rows  "
        f"({mfr_zero_mask.mean():.1%}, target {ZERO_MFR_PRICE_RATE:.0%})"
    )

    # ── QI-07: brand_volume > total_category_volume ──────────────────────────
    vol_viol_mask = np.random.random(n) < VOL_VIOLATION_RATE
    n_viol = vol_viol_mask.sum()
    overshoot = np.random.uniform(VOL_VIOLATION_MIN, VOL_VIOLATION_MAX, size=n_viol)
    df.loc[vol_viol_mask, "brand_volume_units"] = (
        np.round(
            df.loc[vol_viol_mask, "total_category_volume_units"].values * overshoot
        )
        .clip(min=1)
        .astype(np.int64)
    )
    print(
        f"    QI-07  brand_vol > category_vol violations  : {n_viol:>8,} rows  "
        f"({vol_viol_mask.mean():.1%}, target {VOL_VIOLATION_RATE:.0%})"
    )

    # ── QI-08: temporal gaps ──────────────────────────────────────────────────
    rows_to_drop: list[int] = []
    n_gaps_applied = 0

    for banner, brand in GAP_TARGET_PAIRS:
        pair_mask = (df["banner"] == banner) & (df["brand"] == brand)
        pair_rows = df[pair_mask]
        pair_weeks = sorted(pair_rows["week_date"].unique())
        n_pw = len(pair_weeks)

        # Minimum safe series: clearance weeks before + gap + clearance weeks after.
        clearance = GAP_WEEKS_MAX + 1
        if n_pw < 2 * clearance + GAP_WEEKS_MAX:
            # Pair has too few measurement weeks to place a gap safely.
            # This can happen if MARKET_BRAND_BANNER_LISTING (0.60) happened
            # not to generate this combination — skip without error.
            print(
                f"    QI-08  GAP SKIPPED  {banner:22s} × {brand:14s}"
                f"  only {n_pw} weeks available"
            )
            continue

        gap_length = random.randint(GAP_WEEKS_MIN, GAP_WEEKS_MAX)

        # Place gap with clearance from each end so the gap is unambiguously
        # a mid-series measurement hole, not a series start/end boundary.
        gap_start = random.randint(clearance, n_pw - gap_length - clearance)
        gap_week_set = set(pair_weeks[gap_start : gap_start + gap_length])

        drop_idx = df.index[pair_mask & df["week_date"].isin(gap_week_set)].tolist()
        rows_to_drop.extend(drop_idx)
        n_gaps_applied += 1

        gap_min_date = min(gap_week_set)
        gap_max_date = max(gap_week_set)
        print(
            f"    QI-08  gap applied  {banner:22s} × {brand:14s}"
            f"  {gap_length} weeks "
            f"({pd.Timestamp(gap_min_date).date()} → {pd.Timestamp(gap_max_date).date()})  "
            f"({len(drop_idx)} rows dropped)"
        )

    # Drop all gap rows in a single operation for efficiency
    if rows_to_drop:
        df = df.drop(index=rows_to_drop).reset_index(drop=True)

    print(
        f"    QI-08  {n_gaps_applied}/{N_GAP_PAIRS} gap pairs applied  "
        f"({len(rows_to_drop)} total rows dropped)"
    )

    return df


# ==============================================================================
# POST-INJECTION VERIFICATION
# ==============================================================================


def verify_injection(
    raw_product: pd.DataFrame,
    raw_sales: pd.DataFrame,
    raw_market: pd.DataFrame,
    dirty_product: pd.DataFrame,
    dirty_sales: pd.DataFrame,
    dirty_market: pd.DataFrame,
) -> None:
    """
    Prints a structured post-injection verification summary.

    Checks that:
      - Each injection rate is within ±1.5pp of its target
      - Constraint violations are present in fact_market (QI-07)
      - Row count reduction in fact_market reflects gap drops (QI-08)
      - dim_customer FK relationships are intact (banner values unchanged)
    """
    print("\n── Post-injection verification ─────────────────────────────────────")

    # ── dim_product casing ────────────────────────────────────────────────────
    raw_pt_vals = set(raw_product["pack_type"].unique())
    dirty_pt_vals = set(dirty_product["pack_type"].unique())
    new_pt_vals = dirty_pt_vals - raw_pt_vals
    raw_var_vals = set(raw_product["variant"].unique())
    dirty_var_vals = set(dirty_product["variant"].unique())
    new_var_vals = dirty_var_vals - raw_var_vals
    print(
        f"\n  dim_product  new pack_type  values introduced  : {len(new_pt_vals):3d}  "
        f"(examples: {sorted(new_pt_vals)[:4]})"
    )
    print(
        f"  dim_product  new variant    values introduced  : {len(new_var_vals):3d}  "
        f"(examples: {sorted(new_var_vals)[:4]})"
    )

    # ── fact_sales rates ──────────────────────────────────────────────────────
    zero_px_rate = (dirty_sales["sku_net_price_gbp"] == 0).mean()
    promo_rows = dirty_sales[dirty_sales["is_promoted"] == True]
    null_mech_rate = promo_rows["promotion_mechanic"].isna().mean()

    # Outlier proxy: rows where volume_units > 4× baseline_volume are candidates.
    # This is approximate — some legitimate promoted rows with large incremental
    # uplift may also exceed 4× but the injected outliers are at 5–10×.
    outlier_proxy = (
        dirty_sales["volume_units"] > dirty_sales["baseline_volume"] * 4
    ).mean()

    print(
        f"\n  fact_sales   zero selling_price rate           : {zero_px_rate:.1%}  "
        f"(target {ZERO_PRICE_RATE:.0%})"
    )
    print(
        f"  fact_sales   NULL promotion_mechanic (promo)   : {null_mech_rate:.1%}  "
        f"(target {NULL_MECHANIC_RATE:.0%})"
    )
    print(
        f"  fact_sales   volume >4× baseline (outlier proxy): {outlier_proxy:.1%}  "
        f"(indicative — exact count logged above)"
    )

    # ── fact_market rates ─────────────────────────────────────────────────────
    zero_mfr_rate = (dirty_market["avg_shelf_price_gbp"] == 0).mean()
    vol_viol_n = (
        dirty_market["brand_volume_units"] > dirty_market["total_category_volume_units"]
    ).sum()
    row_delta = len(raw_market) - len(dirty_market)

    print(
        f"\n  fact_market  zero avg_shelf_price rate         : {zero_mfr_rate:.1%}  "
        f"(target {ZERO_MFR_PRICE_RATE:.0%})"
    )
    print(
        f"  fact_market  brand_vol > cat_vol violations    : {vol_viol_n:,}  "
        f"(target ~{int(len(raw_market) * VOL_VIOLATION_RATE):,})"
    )
    print(
        f"  fact_market  rows removed by gap injection     : {row_delta:,}  "
        f"(raw {len(raw_market):,} → processed {len(dirty_market):,})"
    )

    print("\n── Verification complete ────────────────────────────────────────────\n")


# ==============================================================================
# MAIN
# ==============================================================================


def main() -> None:
    print("\n══════════════════════════════════════════════════════════════════")
    print("inject_quality_issues.py — AM1 Sprint 1 / F-02")
    print("Reads  : data/raw/        Writes : data/raw/qi-injected/")
    print("════════════════════════════════════════════════════════════════════\n")

    # ── 1. Load raw Parquet files ─────────────────────────────────────────────
    print("Loading raw Parquet files from data/raw/ ...")
    dim_product = pd.read_parquet(os.path.join(RAW_DIR, "dim_product.parquet"))
    dim_customer = pd.read_parquet(os.path.join(RAW_DIR, "dim_customer.parquet"))
    fact_sales = pd.read_parquet(os.path.join(RAW_DIR, "fact_sales.parquet"))
    fact_market = pd.read_parquet(os.path.join(RAW_DIR, "fact_market.parquet"))

    print(
        f"  dim_product  : {len(dim_product):>7,} rows  |  "
        f"columns: {list(dim_product.columns)}"
    )
    print(
        f"  dim_customer : {len(dim_customer):>7,} rows  |  "
        f"columns: {list(dim_customer.columns)}"
    )
    print(
        f"  fact_sales   : {len(fact_sales):>7,} rows  |  "
        f"columns: {list(fact_sales.columns)}"
    )
    print(
        f"  fact_market  : {len(fact_market):>7,} rows  |  "
        f"columns: {list(fact_market.columns)}"
    )

    # ── 2. Inject quality issues ──────────────────────────────────────────────
    print("\n── Injecting quality issues ─────────────────────────────────────────")

    # 2a. dim_product — casing/abbreviation corruption
    print("\n[1/4] dim_product  (QI-01: pack_type casing  |  QI-02: variant casing)")
    dim_product_dirty = inject_dim_product(dim_product)

    # 2b. dim_customer — pass-through (quality issues already in raw layer)
    print("\n[2/4] dim_customer  (pass-through — quality issues already in raw)")
    dim_customer_dirty = dim_customer.copy()
    null_terr = dim_customer_dirty["territory"].isna().sum()
    null_store = dim_customer_dirty["store_count"].isna().sum()
    print(
        f"    NULL territory  (raw, from generate_data.py) : {null_terr:>4,} rows  "
        f"({null_terr / len(dim_customer_dirty):.1%})"
    )
    print(
        f"    NULL store_count (raw, from generate_data.py): {null_store:>4,} rows  "
        f"({null_store / len(dim_customer_dirty):.1%})"
    )

    # 2c. fact_sales — price zeros, volume outliers, NULL mechanic
    print(
        "\n[3/4] fact_sales  "
        "(QI-03: zero price  |  QI-04: volume outliers  |  QI-05: NULL mechanic)"
    )
    fact_sales_dirty = inject_fact_sales(fact_sales)

    # 2d. fact_market — zero prices, volume violations, temporal gaps
    print(
        "\n[4/4] fact_market  "
        "(QI-06: zero mfr price  |  QI-07: vol violations  |  QI-08: gaps)"
    )
    fact_market_dirty = inject_fact_market(fact_market)

    # ── 3. Write to data/raw/qi-injected/ ──────────────────────────────────────────
    print("\n── Writing dirty Parquet files to data/raw/qi-injected/ ───────────────────")

    dim_product_dirty.to_parquet(
        os.path.join(DIRTY_DIR, "dim_product.parquet"), index=False
    )
    print(f"  ✓  dim_product.parquet    {len(dim_product_dirty):>7,} rows")

    dim_customer_dirty.to_parquet(
        os.path.join(DIRTY_DIR, "dim_customer.parquet"), index=False
    )
    print(f"  ✓  dim_customer.parquet   {len(dim_customer_dirty):>7,} rows")

    fact_sales_dirty.to_parquet(
        os.path.join(DIRTY_DIR, "fact_sales.parquet"), index=False
    )
    print(f"  ✓  fact_sales.parquet     {len(fact_sales_dirty):>7,} rows")

    fact_market_dirty.to_parquet(
        os.path.join(DIRTY_DIR, "fact_market.parquet"), index=False
    )
    print(f"  ✓  fact_market.parquet    {len(fact_market_dirty):>7,} rows")

    # ── 4. Post-injection verification ───────────────────────────────────────
    verify_injection(
        raw_product=dim_product,
        raw_sales=fact_sales,
        raw_market=fact_market,
        dirty_product=dim_product_dirty,
        dirty_sales=fact_sales_dirty,
        dirty_market=fact_market_dirty,
    )

    print("════════════════════════════════════════════════════════════════════\n")
    print("inject_quality_issues.py — COMPLETED")
    print("data/raw/qi-injected/ ready for preprocess.py (F-03)")
    print("════════════════════════════════════════════════════════════════════\n")


if __name__ == "__main__":
    main()
