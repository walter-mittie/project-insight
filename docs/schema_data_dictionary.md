---
feature: F-04
version: 1.2
last_updated: 2026-05-10
source_layer: data/processed/
tables: dim_product · dim_customer · fact_sales · fact_market
---

# Schema & Semantic Data Dictionary
## FMCG Analytics — Processed Layer

All tables are DuckDB-queryable Parquet files in `data/processed/`.
This is the **only** layer the application queries. Raw and QI-injected
layers are never accessed at query time.

---

## 1. dim_product

Grain: one row per SKU. 552 rows (497 `is_active = TRUE`).

| Column | Type | Definition |
|---|---|---|
| product_id | VARCHAR PK | Surrogate key. Format: `SKU-NNNN` |
| sku_name | VARCHAR | Display name: "Brand Variant PackSize PackType" |
| brand | VARCHAR | Parent brand. Joins to `fact_market.brand` |
| sub_brand | VARCHAR | Sub-line within brand; may equal brand for simple SKUs |
| category | VARCHAR | 6 values: Dairy, Cereals, Beverages, Snacks, Confectionery, Frozen Food |
| sub_category | VARCHAR | 22 values. Aligns with `fact_market.sub_category` |
| price_tier | VARCHAR | Brand-level attribute: Premium / Mainstream / Value. Not SKU-level |
| pack_size | INTEGER | Numeric quantity (no unit — see pack_size_uom) |
| pack_size_uom | VARCHAR | Unit of measure: ml / g / units |
| pack_type | VARCHAR | Packaging format normalised to title case (e.g. Can, Pot, Bag) |
| variant | VARCHAR | Flavour/recipe descriptor normalised to title case |
| list_price_gbp | FLOAT | Manufacturer list price. Basis for gross_revenue in fact_sales |
| cost_price_gbp | FLOAT | Manufacturer cost. Use for gross margin only; not in fact_market |
| launch_date | DATE | SKU launch date |
| is_active | BOOLEAN | TRUE = currently ranging. Filter active SKUs: `WHERE is_active = TRUE` |

---

## 2. dim_customer

Grain: one row per customer account. 240 rows across 5 channels, 15 banners.

| Column | Type | Definition |
|---|---|---|
| customer_id | VARCHAR PK | Surrogate key. Format: `CUST-NNN` |
| customer_name | VARCHAR | Account display name |
| channel | VARCHAR | 5 values: Grocery, Discounter, Convenience, eCommerce, Foodservice |
| banner | VARCHAR | 15 values. Joins to `fact_market.banner` and `fact_sales` via customer_id |
| region | VARCHAR | Geographic region. **Structurally NULL for eCommerce** (operates nationally) |
| territory | VARCHAR | Sub-region within region. NULL imputed to `"Unknown-{Channel}"` where missing |
| account_type | VARCHAR | Key Account / Regional Multiple / Independent |
| store_count | INTEGER | Physical outlet count. NULLs imputed with channel median in processed layer |

---

## 3. fact_sales

Grain: one row per transaction (SKU × customer account × week). ~2.3M rows.
Date range: 104 ISO weeks, 2024-01-01 – 2025-12-29.

| Column | Type | Definition |
|---|---|---|
| transaction_id | BIGINT PK | Surrogate key |
| week_date | DATE | Monday of ISO week |
| year | INTEGER | 2024 or 2025 |
| quarter | INTEGER | 1–4 |
| month | INTEGER | 1–12 |
| week_number | INTEGER | ISO week number (1–53) |
| product_id | VARCHAR FK | → dim_product.product_id |
| customer_id | VARCHAR FK | → dim_customer.customer_id |
| volume_units | INTEGER | Total units sold: `baseline_volume + incremental_volume` on clean rows only. See flag: `is_volume_outlier` |
| gross_revenue_gbp | FLOAT | `volume_units × list_price_gbp`. Revenue before trade investment |
| trade_discount_gbp | FLOAT | Total promotional + contractual discount |
| net_revenue_gbp | FLOAT | `gross_revenue_gbp − trade_discount_gbp`. Exclude rows where `is_zero_price = TRUE` |
| sku_net_price_gbp | FLOAT | Manufacturer's net realised price per unit post-discount. `trade_discount per unit = list_price_gbp − sku_net_price_gbp`. Exclude rows where `is_zero_price = TRUE` |
| is_promoted | BOOLEAN | TRUE = row is part of a promotional event. Authoritative promotional flag |
| promotion_mechanic | VARCHAR | Mechanic type (e.g. Price Reduction, Multibuy). **Nullable — see constraint C1** |
| baseline_volume | INTEGER | Modelled baseline (non-promo underlying demand) |
| incremental_volume | INTEGER | Promo-driven uplift above baseline. Zero for non-promoted rows |
| is_zero_price | BOOLEAN | **QI-03 flag.** TRUE where `sku_net_price_gbp = 0`. Exclude from all revenue KPIs |
| is_volume_outlier | BOOLEAN | **QI-04 flag.** TRUE where `volume_units` exceeds Tukey outer fence (Q3 + 3×IQR). Exclude from volume aggregations requiring clean decomposition, baseline/incremental invariant checks, and all revenue KPIs (gross_revenue_gbp, net_revenue_gbp) — revenue is derived from `volume_units × list_price_gbp` and is inflated on outlier-flagged rows |

**Temporal column note (ISO/calendar boundary):**
`year` is derived from ISO week year; `quarter` and `month` are derived from
the calendar date of `week_date`. At the ISO/calendar year boundary (typically
the last Monday of December), a row may have `year = N+1` but `quarter = 4`
and `month = 12`, because the ISO week year has advanced but the calendar date
is still in December of year N. Example: `week_date = 2024-12-30` has
`year = 2025, quarter = 4, month = 12, week_number = 1`. For precise
calendar-period queries spanning year boundaries, filter on `week_date` ranges
rather than relying on `year` + `quarter` combinations alone.

---

## 4. fact_market

Grain: one row per week × brand × sub_category × banner. ~44K rows.
Panel measurement data (Nielsen/Kantar convention). Date range aligns with fact_sales.

**This table cannot be directly joined to fact_sales — different grains. See join pattern below.**

| Column | Type | Definition |
|---|---|---|
| measurement_id | BIGINT PK | Surrogate key |
| week_date | DATE | Monday of ISO week. Aligns with fact_sales.week_date |
| year | INTEGER | 2024 or 2025 |
| quarter | INTEGER | 1–4 |
| month | INTEGER | 1–12 |
| week_number | INTEGER | ISO week number |
| brand | VARCHAR | Brand name. Joins to dim_product.brand |
| sub_category | VARCHAR | Subcategory. Joins to dim_product.sub_category |
| banner | VARCHAR | Retail banner. Joins to dim_customer.banner |
| brand_volume_units | INTEGER | Units sold for this brand in this banner × week |
| brand_value_gbp | FLOAT | Value of brand sales at RSP (consumer shelf price) |
| total_category_volume_units | INTEGER | Total market units across all brands in sub_category × banner × week |
| total_category_value_gbp | FLOAT | Total market value at RSP across all brands |
| numeric_distribution_outlets | INTEGER | Number of outlets stocking this brand |
| total_outlets_in_banner | INTEGER | Total outlets in banner (distribution denominator) |
| avg_shelf_price_gbp | FLOAT | Brand-level **weekly average RSP**. Consumer-facing price as measured at the till. Not an SKU price. Not manufacturer net price. See constraint C4 |
| is_zero_shelf_price | BOOLEAN | **QI-06 flag.** TRUE where `avg_shelf_price_gbp = 0`. Exclude from price_index and implied margin calculations |
| is_vol_violation | BOOLEAN | **QI-07 flag.** TRUE where `brand_volume_units > total_category_volume_units`. All share and index measures are NaN for these rows |

---

## 5. KPI Computation Patterns

fact_market stores pre-computed share and index columns
(`market_share_volume_pct`, `market_share_value_pct`,
`numeric_distribution_pct`, `price_index`) at grain
`brand × sub_category × banner × week`.

**These columns are grain-locked. Never SUM or AVG them across any
dimension.** Summing percentages across weeks, banners, or sub-categories
produces arithmetically incorrect results. Always compute KPIs from the
underlying numerator and denominator components at the required grain.

Example of the failure:
```
Week 1: brand_vol=150, cat_vol=1000 → share=15.0%
Week 2: brand_vol=200, cat_vol=800  → share=25.0%
AVG(market_share_volume_pct) = 20.0%          ← WRONG
Correct:  (150+200)/(1000+800)*100 = 19.4%    ← always recompute
```

Use the pre-computed columns only for exact point lookups at the
native grain (e.g. "NitroBoost share in Tesco in week 12 2024").
For all other queries, use the patterns below.

---

### P1 — Volume market share (any grain)
```sql
SUM(brand_volume_units) * 100.0
    / NULLIF(SUM(total_category_volume_units), 0)
    AS market_share_volume_pct
-- Always filter: WHERE is_vol_violation = FALSE
```

### P2 — Value market share (any grain)
```sql
SUM(brand_value_gbp) * 100.0
    / NULLIF(SUM(total_category_value_gbp), 0)
    AS market_share_value_pct
-- Always filter: WHERE is_vol_violation = FALSE
```

### P3 — Numeric distribution (any grain)
```sql
SUM(numeric_distribution_outlets) * 100.0
    / NULLIF(SUM(total_outlets_in_banner), 0)
    AS numeric_distribution_pct
-- Note: aggregating across banners produces a blended rate.
-- Meaningful for within-banner or total-portfolio queries only.
```

### P4 — Price index (any grain)
```sql
(SUM(brand_value_gbp) / NULLIF(SUM(brand_volume_units), 0))
    / (SUM(total_category_value_gbp)
       / NULLIF(SUM(total_category_volume_units), 0))
    * 100
    AS price_index
-- Always filter: WHERE is_vol_violation = FALSE
--            AND is_zero_shelf_price = FALSE
```

### P1 example — NitroBoost quarterly share, all banners
```sql
SELECT
    year,
    quarter,
    brand,
    ROUND(SUM(brand_volume_units) * 100.0
          / NULLIF(SUM(total_category_volume_units), 0), 2)
                                    AS market_share_volume_pct
FROM fact_market
WHERE brand            = 'NitroBoost'
  AND is_vol_violation = FALSE
GROUP BY year, quarter, brand
ORDER BY year, quarter;
```

---

## 6. Critical Semantic Constraints

**C1 — NULL promotion_mechanic ≠ non-promotional**
Filter on `is_promoted = TRUE` to identify promoted rows. Never filter on
`promotion_mechanic IS NOT NULL` — this silently excludes ~22% of promoted
volume where the mechanic was not captured by the POS/TPM system.

**C2 — Missing rows in fact_market ≠ zero sales**
Temporal gaps are absent panel measurements, not zero sales events.
Always use `COUNT(DISTINCT week_date)` per group — never assume 104 weeks.
Missing rows represent structural gaps in panel reporting coverage.

**C3 — fact_sales cannot be directly joined to fact_market**
Different grains: fact_sales is SKU × account × week; fact_market is
brand × sub_category × banner × week. Direct join produces a fan-out.
Aggregate fact_sales to brand × banner × week first, then join. See Section 8.

**C4 — avg_shelf_price_gbp is a brand-level weekly average RSP**
This is the consumer shelf price as measured at the till (Nielsen/Kantar
convention), averaged across the brand's SKUs in that banner × week.
It is not an SKU-level price and not the manufacturer's net invoice price.
Manufacturer net price lives in `fact_sales.sku_net_price_gbp`.

**C5 — Implied retailer margin requires a cross-table join**
`(avg_shelf_price_gbp − AVG(sku_net_price_gbp)) / avg_shelf_price_gbp`
This requires aggregating `fact_sales` to brand × banner × week first (C3).
Cannot be computed from `fact_market` alone.

**C6 — baseline_volume + incremental_volume = volume_units (clean rows only)**
This invariant holds only where `is_volume_outlier = FALSE`. On outlier-flagged
rows, `volume_units` was inflated without adjusting the decomposed columns.
Do not use this invariant as a filter criterion — use `is_volume_outlier` instead.

---

## 7. Flag Exclusion Patterns

| Flag | Value | Exclude From |
|---|---|---|
| is_zero_price | TRUE | All revenue KPIs: net_revenue_gbp, gross_revenue_gbp, sku_net_price_gbp aggregations |
| is_volume_outlier | TRUE | Volume totals requiring clean decomposition; baseline/incremental invariant checks; all revenue KPIs (net_revenue_gbp, gross_revenue_gbp) — revenue is derived from volume_units × list_price_gbp and is inflated on outlier-flagged rows |
| is_zero_shelf_price | TRUE | price_index; implied retailer margin calculations |
| is_vol_violation | TRUE | All KPI computations using brand_volume_units, brand_value_gbp, total_category_volume_units, total_category_value_gbp as components; also excludes the grain-locked pre-computed columns |

---

## 8. Join Pattern: fact_sales → fact_market

**Never join these tables directly.** fact_sales grain is
`SKU × account × week`; fact_market grain is
`brand × sub_category × banner × week`. A direct join produces a fan-out.

Two valid patterns depending on whether sub_category is needed:

---

### Pattern A — brand × sub_category × banner × week (preferred)

Use when the question involves sub_category-level market data, or when
joining to a single sub_category. All four grain keys must be present.

```sql
WITH sales_agg AS (
    SELECT
        fs.week_date,
        dp.brand,
        dp.sub_category,                       -- required for clean join
        dc.banner,
        SUM(fs.net_revenue_gbp)  AS net_revenue_gbp,
        SUM(fs.volume_units)     AS volume_units
    FROM fact_sales fs
    JOIN dim_product  dp ON fs.product_id  = dp.product_id
    JOIN dim_customer dc ON fs.customer_id = dc.customer_id
    WHERE fs.is_zero_price     = FALSE
      AND fs.is_volume_outlier = FALSE
    GROUP BY fs.week_date, dp.brand, dp.sub_category, dc.banner
)
SELECT
    sa.week_date, sa.brand, sa.sub_category, sa.banner,
    sa.net_revenue_gbp, sa.volume_units,
    ROUND(SUM(fm.brand_volume_units) * 100.0
          / NULLIF(SUM(fm.total_category_volume_units), 0), 2)
                                         AS market_share_volume_pct,
    fm.avg_shelf_price_gbp
FROM sales_agg sa
JOIN fact_market fm
    ON  sa.week_date    = fm.week_date
    AND sa.brand        = fm.brand
    AND sa.sub_category = fm.sub_category  -- all four keys
    AND sa.banner       = fm.banner
WHERE fm.is_vol_violation    = FALSE
  AND fm.is_zero_shelf_price = FALSE
GROUP BY sa.week_date, sa.brand, sa.sub_category, sa.banner,
         sa.net_revenue_gbp, sa.volume_units, fm.avg_shelf_price_gbp;
```

**Join keys:** `week_date · brand · sub_category · banner`

---

### Pattern B — brand × banner × week (brand-total, no sub_category)

Use when the question is brand-level only and sub_category is not needed.
fact_market must ALSO be pre-aggregated to brand × banner × week.
Joining a three-key sales_agg directly to the four-key fact_market grain
produces a fan-out — one sales row matches multiple fact_market rows.

```sql
WITH sales_agg AS (
    SELECT
        fs.week_date,
        dp.brand,
        dc.banner,
        SUM(fs.net_revenue_gbp)  AS net_revenue_gbp,
        SUM(fs.volume_units)     AS volume_units
    FROM fact_sales fs
    JOIN dim_product  dp ON fs.product_id  = dp.product_id
    JOIN dim_customer dc ON fs.customer_id = dc.customer_id
    WHERE fs.is_zero_price     = FALSE
      AND fs.is_volume_outlier = FALSE
    GROUP BY fs.week_date, dp.brand, dc.banner
),
market_agg AS (
    -- Pre-aggregate fact_market to match sales_agg grain
    SELECT
        week_date, brand, banner,
        SUM(brand_volume_units)          AS brand_volume_units,
        SUM(brand_value_gbp)             AS brand_value_gbp,
        SUM(total_category_volume_units) AS total_category_volume_units,
        SUM(total_category_value_gbp)    AS total_category_value_gbp
    FROM fact_market
    WHERE is_vol_violation = FALSE
    GROUP BY week_date, brand, banner
)
SELECT
    sa.week_date, sa.brand, sa.banner,
    sa.net_revenue_gbp, sa.volume_units,
    ROUND(ma.brand_volume_units * 100.0
          / NULLIF(ma.total_category_volume_units, 0), 2)
                                         AS market_share_volume_pct
FROM sales_agg sa
JOIN market_agg ma
    ON  sa.week_date = ma.week_date
    AND sa.brand     = ma.brand
    AND sa.banner    = ma.banner;
```

**Join keys:** `week_date · brand · banner`
**Requirement:** fact_market pre-aggregated via market_agg CTE —
never join sales_agg (3-key grain) directly to fact_market (4-key grain).
