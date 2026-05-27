# 15-Query Manual Test Suite — F-08 AC3

**Run timestamp:** 2026-01-16 16:53:29  
**Total queries:** 15  
**Model:** gemini-2.5-flash  
**Sprint:** 2

---

## Q01 — Cat1 — Single-table filter

**Question:** How many distinct SKUs were sold in Q1 2024?

### Reasoning

**Step 1 — Identify tables and columns**
- `fact_sales`: `product_id`, `year`, `quarter`

**Step 2 — Check semantic constraints and KPI computation rules**
- No specific constraints or KPI computation patterns from the schema apply to simply counting distinct SKUs. The question does not involve revenue, volume decomposition, or market data.
- Flag exclusion patterns are not relevant for counting distinct `product_id` in `fact_sales`.

**Step 3 — Clarify any ambiguous business terms**
- "SKUs sold": This refers to the `product_id` column in the `fact_sales` table.
- "Q1 2024": This translates to `year = 2024` and `quarter = 1`.

### Generated SQL

```sql
SELECT
    COUNT(DISTINCT product_id) AS distinct_skus_sold
FROM fact_sales
WHERE
    year    = 2024
    AND quarter = 1;
```

### Execution Result

**Status:** ✅ SUCCESS  
**Rows:** 1  
**Time:** 43.8ms  

|   distinct_skus_sold |
|---------------------:|
|                  497 |

---

## Q02 — Cat1 — Single-table filter

**Question:** What are the top 10 SKUs by net revenue in 2025 for active products only?

### Reasoning

**Step 1 — Identify tables and columns**
- `dim_product`: `product_id`, `sku_name`, `is_active`
- `fact_sales`: `product_id`, `net_revenue_gbp`, `year`, `is_zero_price`

**Step 2 — Check semantic constraints and KPI computation rules**
- **Flag Exclusion Patterns:** `is_zero_price = TRUE` must be excluded from `net_revenue_gbp` calculations.
- Other constraints (C1-C6, P1-P4, join patterns) are not applicable as this query does not involve `fact_market`.

**Step 3 — Clarify any ambiguous business terms**
- "net revenue": This directly maps to the `net_revenue_gbp` column in `fact_sales`.
- "2025": This refers to `year = 2025` in `fact_sales`.
- "active products only": This refers to `is_active = TRUE` in `dim_product`.
- "top 10 SKUs": This implies ranking by total `net_revenue_gbp` for each SKU and taking the top 10.

### Generated SQL

```sql
SELECT
    dp.product_id,
    dp.sku_name,
    SUM(fs.net_revenue_gbp) AS total_net_revenue_gbp
FROM
    fact_sales AS fs
JOIN
    dim_product AS dp ON fs.product_id = dp.product_id
WHERE
    fs.year = 2025
    AND dp.is_active = TRUE
    AND fs.is_zero_price = FALSE
GROUP BY
    dp.product_id,
    dp.sku_name
ORDER BY
    total_net_revenue_gbp DESC
LIMIT 10;
```

### Execution Result

**Status:** ✅ SUCCESS  
**Rows:** 10  
**Time:** 65.6ms  

| product_id   | sku_name                           |   total_net_revenue_gbp |
|:-------------|:-----------------------------------|------------------------:|
| SKU-0056     | SkyrNorth Honey 6pk Multipack      |             2.3624e+06  |
| SKU-0012     | LactoPure Mango 1000ml Bottle      |             2.25945e+06 |
| SKU-0036     | BioBloom Greek Style 4pk Multipack |             2.19596e+06 |
| SKU-0002     | LactoPure Honey 1000ml Bottle      |             2.19371e+06 |
| SKU-0053     | SkyrNorth Low Fat 400g Block       |             2.14656e+06 |
| SKU-0170     | SeededHearth Honey & Nut 400g Box  |             2.13595e+06 |
| SKU-0054     | SkyrNorth Vanilla 200g Slices Pack |             2.1038e+06  |
| SKU-0051     | SkyrNorth Natural 6pk Multipack    |             2.08079e+06 |
| SKU-0029     | BioBloom Natural 500g Tub          |             2.06989e+06 |
| SKU-0034     | BioBloom Cherry 500g Tub           |             2.04763e+06 |

---

## Q03 — Cat1 — Single-table filter

**Question:** What was the total incremental volume from promotional activity in 2024?

### Reasoning

**Step 1 — Identify tables and columns**
- Table: `fact_sales`
- Columns: `incremental_volume`, `year`, `is_promoted`, `is_volume_outlier`

**Step 2 — Check semantic constraints and KPI computation rules**
- **C1 — NULL promotion_mechanic ≠ non-promotional**: I will use `is_promoted = TRUE` to identify promotional activity, not `promotion_mechanic IS NOT NULL`.
- **C6 — baseline_volume + incremental_volume = volume_units (clean rows only)**: The `incremental_volume` should only be summed for `is_volume_outlier = FALSE` rows to ensure accuracy and clean decomposition, as specified in the "Flag Exclusion Patterns" (Section 7).
- No cross-table joins are required.

**Step 3 — Clarify any ambiguous business terms**
- "incremental volume": This refers directly to the `incremental_volume` column in `fact_sales`.
- "promotional activity": This is identified by the `is_promoted = TRUE` flag in `fact_sales`.
- "2024": This refers to the `year` column in `fact_sales`.

### Generated SQL

```sql
SELECT
    SUM(incremental_volume) AS total_incremental_volume_2024
FROM fact_sales
WHERE
    year = 2024
    AND is_promoted = TRUE
    AND is_volume_outlier = FALSE;
```

### Execution Result

**Status:** ✅ SUCCESS  
**Rows:** 1  
**Time:** 37.2ms  

| total_incremental_volume_2024 |
| ----------------------------: |
|                   1.72397e+07 |

---

## Q04 — Cat2 — Aggregation/KPI

**Question:** What was total gross revenue and total trade discount by channel in 2025?

### Reasoning

**Step 1 — Identify tables and columns**
- `fact_sales`: `gross_revenue_gbp`, `trade_discount_gbp`, `customer_id`, `year`, `is_zero_price`
- `dim_customer`: `customer_id`, `channel`

**Step 2 — Check semantic constraints and KPI computation rules**
- **Flag Exclusion Patterns (Section 7):** The `is_zero_price` flag applies to all revenue KPIs. We must filter `WHERE is_zero_price = FALSE` to exclude transactions with zero net price, as this impacts `gross_revenue_gbp` and `trade_discount_gbp`.

**Step 3 — Clarify any ambiguous business terms**
- "gross revenue": This refers to the `gross_revenue_gbp` column in `fact_sales`.
- "trade discount": This refers to the `trade_discount_gbp` column in `fact_sales`.
- "channel": This refers to the `channel` column in `dim_customer`.
- "2025": This refers to filtering for `year = 2025` in `fact_sales`.

### Generated SQL

```sql
SELECT
    dc.channel,
    SUM(fs.gross_revenue_gbp)  AS total_gross_revenue_gbp,
    SUM(fs.trade_discount_gbp) AS total_trade_discount_gbp
FROM fact_sales AS fs
JOIN dim_customer AS dc
    ON fs.customer_id = dc.customer_id
WHERE
    fs.year = 2025
    AND fs.is_zero_price = FALSE
GROUP BY
    dc.channel
ORDER BY
    dc.channel;
```

### Execution Result

**Status:** ✅ SUCCESS  
**Rows:** 5  
**Time:** 73.1ms  

| channel     | total_gross_revenue_gbp | total_trade_discount_gbp |
| :---------- | ----------------------: | -----------------------: |
| Convenience |             2.51081e+07 |              1.89811e+06 |
| Discounter  |             5.19824e+07 |              3.92062e+06 |
| Foodservice |              7.9739e+07 |              6.02345e+06 |
| Grocery     |             3.33513e+08 |              2.52254e+07 |
| eCommerce   |             3.82553e+07 |              2.87885e+06 |

---

## Q05 — Cat2 — Aggregation/KPI

**Question:** What was NitroBoost's volume market share in 2024 by quarter?

### Reasoning

**Step 1 — Identify tables and columns**
*   `fact_market`:
    *   `year`: To filter for 2024.
    *   `quarter`: To group the results by quarter.
    *   `brand`: To filter for 'NitroBoost'.
    *   `brand_volume_units`: As the numerator for volume market share.
    *   `total_category_volume_units`: As the denominator for volume market share.
    *   `is_vol_violation`: To exclude invalid rows from calculations.

**Step 2 — Check semantic constraints and KPI computation rules**
*   **Grain-locked columns**: The question asks for market share aggregated by quarter. The `market_share_volume_pct` column in `fact_market` is grain-locked and cannot be directly aggregated. I will recompute it using the underlying `brand_volume_units` and `total_category_volume_units`.
*   **KPI Computation Pattern**: P1 — Volume market share (any grain) will be used.
*   **Constraints**:
    *   C2 — Missing rows in fact_market ≠ zero sales: This is handled by aggregating the available data.
*   **Flag Exclusion Pattern**: `is_vol_violation = TRUE` must be excluded from all market share calculations as per Section 7 and P1.

**Step 3 — Clarify any ambiguous business terms**
*   "volume market share": Interpreted as `SUM(brand_volume_units) * 100.0 / NULLIF(SUM(total_category_volume_units), 0)`.
*   "NitroBoost": Refers to the `brand` value 'NitroBoost'.
*   "in 2024": Refers to `year = 2024`.
*   "by quarter": Refers to grouping by the `quarter` column.

### Generated SQL

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
  AND year             = 2024
  AND is_vol_violation = FALSE
GROUP BY year, quarter, brand
ORDER BY year, quarter;
```

### Execution Result

**Status:** ✅ SUCCESS  
**Rows:** 4  
**Time:** 9.4ms  

|   year |   quarter | brand      |   market_share_volume_pct |
|-------:|----------:|:-----------|--------------------------:|
|   2024 |         1 | NitroBoost |                     24.96 |
|   2024 |         2 | NitroBoost |                     24.58 |
|   2024 |         3 | NitroBoost |                     22.56 |
|   2024 |         4 | NitroBoost |                     25.46 |

---

## Q06 — Cat2 — Aggregation/KPI

**Question:** What was the price index for the Dairy category across all banners in 2025?

### Reasoning

**Step 1 — Identify tables and columns**

*   `fact_market`: `year`, `brand`, `sub_category`, `brand_value_gbp`, `brand_volume_units`, `total_category_value_gbp`, `total_category_volume_units`, `is_vol_violation`, `is_zero_shelf_price`.
*   `dim_product`: `brand`, `sub_category`, `category`. (Needed to filter `fact_market` by `category`).

**Step 2 — Check semantic constraints and KPI computation rules**

*   **KPI Computation:** The query asks for "price index". This KPI must be recomputed from its base components using **P4 — Price index (any grain)** from Section 5 of the schema.
    *   Formula: `(SUM(brand_value_gbp) / NULLIF(SUM(brand_volume_units), 0)) / (SUM(total_category_value_gbp) / NULLIF(SUM(total_category_volume_units), 0)) * 100`
*   **Flag Exclusions:** The P4 pattern and Section 7 dictate applying the following filters:
    *   `is_vol_violation = FALSE` (from `fact_market`)
    *   `is_zero_shelf_price = FALSE` (from `fact_market`)
*   **Join Pattern:** The query involves `fact_market` and `dim_product`. `fact_sales` is not involved, so join patterns A/B are not applicable. When joining `fact_market` (grain `brand × sub_category × banner × week`) to `dim_product` (grain `SKU`), a fan-out can occur if a `(brand, sub_category)` combination maps to multiple SKUs in `dim_product`. To prevent this and ensure `fact_market` aggregations are correct, `dim_product` should be pre-aggregated to a distinct `(brand, sub_category, category)` mapping before joining.

**Step 3 — Clarify any ambiguous business terms**

*   "price index": Interpreted as the consumer price index calculated per P4.
*   "Dairy category": Filter `dim_product.category = 'Dairy'`.
*   "all banners": No filtering on `banner` is required, and `fact_market` data will be summed across all banners.
*   "2025": Filter `fact_market.year = 2025`.

### Generated SQL

```sql
WITH product_categories AS (
    -- Pre-aggregate dim_product to get a unique mapping of brand and sub_category to category.
    -- This prevents fan-out when joining to fact_market, where a (brand, sub_category)
    -- combination could correspond to multiple SKUs in dim_product.
    SELECT DISTINCT
        brand,
        sub_category,
        category
    FROM dim_product
)
SELECT
    fm.year,
    pc.category,
    ROUND(
        (SUM(fm.brand_value_gbp) / NULLIF(SUM(fm.brand_volume_units), 0))
        / (SUM(fm.total_category_value_gbp) / NULLIF(SUM(fm.total_category_volume_units), 0))
        * 100,
        2
    ) AS price_index
FROM fact_market fm
JOIN product_categories pc
    ON fm.brand = pc.brand
    AND fm.sub_category = pc.sub_category
WHERE
    fm.year = 2025
    AND pc.category = 'Dairy'
    AND fm.is_vol_violation = FALSE
    AND fm.is_zero_shelf_price = FALSE
GROUP BY
    fm.year,
    pc.category;
```

### Execution Result

**Status:** ✅ SUCCESS  
**Rows:** 1  
**Time:** 43.1ms  

|   year | category   |   price_index |
|-------:|:-----------|--------------:|
|   2025 | Dairy      |        100.07 |

---

## Q07 — Cat3 — Multi-table join

**Question:** What was net revenue by region and category in Q4 2025?

### Reasoning

**Step 1 — Identify tables and columns**
*   **Tables:** `fact_sales`, `dim_product`, `dim_customer`
*   **Columns:**
    *   `fact_sales`: `net_revenue_gbp`, `product_id`, `customer_id`, `year`, `quarter`, `is_zero_price`
    *   `dim_product`: `category`, `product_id`
    *   `dim_customer`: `region`, `customer_id`

**Step 2 — Check semantic constraints and KPI computation rules**
*   **Flag exclusion:** `is_zero_price = TRUE` must be excluded when calculating `net_revenue_gbp`, as per Section 7.
*   **KPI computation:** This is a simple sum of an existing column (`net_revenue_gbp`), so no special KPI patterns (P1-P4) are needed.
*   **Join pattern:** `fact_market` is not involved, so no complex join pattern is needed.

**Step 3 — Clarify any ambiguous business terms**
*   "net revenue": Refers to `fact_sales.net_revenue_gbp`.
*   "region": Refers to `dim_customer.region`. Note that `region` can be `NULL` for eCommerce customers, which will appear as a distinct group in the results.
*   "category": Refers to `dim_product.category`.
*   "Q4 2025": Refers to `year = 2025` and `quarter = 4`.

**Step 4 — Write the SQL**

### Generated SQL

```sql
SELECT
    dc.region,
    dp.category,
    SUM(fs.net_revenue_gbp) AS total_net_revenue_gbp
FROM fact_sales fs
JOIN dim_product dp
    ON fs.product_id = dp.product_id
JOIN dim_customer dc
    ON fs.customer_id = dc.customer_id
WHERE fs.year        = 2025
  AND fs.quarter     = 4
  AND fs.is_zero_price = FALSE
GROUP BY
    dc.region,
    dp.category
ORDER BY
    dc.region,
    dp.category;
```

### Execution Result

**Status:** ✅ SUCCESS  
**Rows:** 34  
**Time:** 62.3ms  

| region   | category      |   total_net_revenue_gbp |
|:---------|:--------------|------------------------:|
| Midlands | Beverages     |             3.20658e+06 |
| Midlands | Cereals       |             3.24512e+06 |
| Midlands | Confectionery |             2.96955e+06 |
| Midlands | Dairy         |             4.02508e+06 |
| Midlands | Frozen Food   |             3.44083e+06 |
| Midlands | Snacks        |             2.15712e+06 |
| North    | Beverages     |             4.06686e+06 |
| North    | Cereals       |             3.72979e+06 |
| North    | Confectionery |             3.66511e+06 |
| North    | Dairy         |             5.0404e+06  |
| North    | Frozen Food   |             4.33817e+06 |
| North    | Snacks        |             2.64689e+06 |
| Scotland | Beverages     |             3.68351e+06 |
| Scotland | Cereals       |             3.47816e+06 |
| Scotland | Confectionery |             3.35981e+06 |
| Scotland | Dairy         |             4.63666e+06 |
| Scotland | Frozen Food   |             3.94945e+06 |
| Scotland | Snacks        |             2.48037e+06 |
| South    | Beverages     |             3.43262e+06 |
| South    | Cereals       |             3.19678e+06 |
| South    | Confectionery |             2.97268e+06 |
| South    | Dairy         |             4.11075e+06 |
| South    | Frozen Food   |             3.59176e+06 |
| South    | Snacks        |             2.19864e+06 |
| Wales    | Beverages     |             4.75339e+06 |
| Wales    | Cereals       |             4.44807e+06 |
| Wales    | Confectionery |             4.25242e+06 |
| Wales    | Dairy         |             5.94371e+06 |
| Wales    | Frozen Food   |             4.92828e+06 |
| Wales    | Snacks        |             2.99046e+06 |
| nan      | Beverages     |             2.24935e+06 |
| nan      | Cereals       |             2.02517e+06 |
| nan      | Confectionery |             1.91772e+06 |
| nan      | Dairy         |             2.66061e+06 |

---

## Q08 — Cat3 — Multi-table join

**Question:** For the Grocery channel, what was net revenue and volume market share by brand in 2025?

### Reasoning

### Step 1 — Identify tables and columns

*   **Net Revenue:**
    *   `fact_sales`: `net_revenue_gbp`, `product_id`, `customer_id`, `year`, `is_zero_price`, `is_volume_outlier`
    *   `dim_product`: `brand` (to link sales to brand)
    *   `dim_customer`: `channel`, `banner` (to filter by channel and link to market data)
*   **Volume Market Share:**
    *   `fact_market`: `brand_volume_units`, `total_category_volume_units`, `brand`, `banner`, `week_date`, `year`, `is_vol_violation`
    *   `dim_customer`: `channel` (to filter market data to relevant banners in the 'Grocery' channel)

### Step 2 — Check semantic constraints and KPI computation rules

*   **C3 — fact_sales cannot be directly joined to fact_market:** This query requires data from both `fact_sales` (net revenue) and `fact_market` (market share). I will use **Pattern B** as the question asks for "market share by brand" (not by brand and sub\_category), meaning we need to aggregate both `fact_sales` and `fact_market` to the `week_date × brand × banner` grain before joining.
*   **P1 — Volume market share (any grain):** I will recompute volume market share using `SUM(brand_volume_units) * 100.0 / NULLIF(SUM(total_category_volume_units), 0)`. I will not use any pre-computed market share columns from `fact_market`.
*   **Flag Exclusion Patterns (Section 7):**
    *   For `fact_sales`: Exclude rows where `is_zero_price = TRUE` and `is_volume_outlier = TRUE` for accurate `net_revenue_gbp` aggregation.
    *   For `fact_market`: Exclude rows where `is_vol_violation = TRUE` for accurate market share calculations.

### Step 3 — Clarify any ambiguous business terms

*   "net revenue": Interpreted as `fact_sales.net_revenue_gbp` after applying relevant flag exclusions.
*   "volume market share": Interpreted as the brand's total volume divided by the total category volume across all sub-categories the brand operates in, within the specified channel and year, as per KPI pattern P1.
*   "by brand": The final result should be grouped by `brand`.
*   "in 2025": Filter by `year = 2025`.
*   "Grocery channel": Filter `dim_customer.channel = 'Grocery'`.

### Step 4 — Write the SQL

### Generated SQL

```sql
WITH sales_by_week_brand_banner AS (
    SELECT
        fs.week_date,
        dp.brand,
        dc.banner,
        SUM(fs.net_revenue_gbp) AS net_revenue_gbp_sum
    FROM fact_sales fs
    JOIN dim_product  dp ON fs.product_id  = dp.product_id
    JOIN dim_customer dc ON fs.customer_id = dc.customer_id
    WHERE fs.year = 2025
      AND dc.channel = 'Grocery'
      AND fs.is_zero_price = FALSE
      AND fs.is_volume_outlier = FALSE
    GROUP BY fs.week_date, dp.brand, dc.banner
),
market_by_week_brand_banner AS (
    -- Aggregate fact_market data to match the grain of sales_by_week_brand_banner (week_date x brand x banner)
    -- This sums total_category_volume_units across sub_categories, providing a brand-level category context.
    SELECT
        fm.week_date,
        fm.brand,
        fm.banner,
        SUM(fm.brand_volume_units)          AS brand_volume_units_total,
        SUM(fm.total_category_volume_units) AS total_category_volume_units_total
    FROM fact_market fm
    JOIN dim_customer dc ON fm.banner = dc.banner -- Join to filter banners by channel
    WHERE fm.year = 2025
      AND dc.channel = 'Grocery'
      AND fm.is_vol_violation = FALSE
    GROUP BY fm.week_date, fm.brand, fm.banner
)
SELECT
    sbb.brand,
    SUM(sbb.net_revenue_gbp_sum) AS total_net_revenue_gbp,
    ROUND(SUM(mbb.brand_volume_units_total) * 100.0
          / NULLIF(SUM(mbb.total_category_volume_units_total), 0), 2) AS volume_market_share_pct
FROM sales_by_week_brand_banner sbb
JOIN market_by_week_brand_banner mbb
    ON sbb.week_date = mbb.week_date
    AND sbb.brand = mbb.brand
    AND sbb.banner = mbb.banner
GROUP BY sbb.brand
ORDER BY total_net_revenue_gbp DESC;
```

### Execution Result

**Status:** ✅ SUCCESS  
**Rows:** 42  
**Time:** 75.0ms  

| brand           |   total_net_revenue_gbp |   volume_market_share_pct |
|:----------------|------------------------:|--------------------------:|
| BerryBliss      |             1.31758e+07 |                     23.15 |
| CocoaEthos      |             1.17681e+07 |                     22.18 |
| Velvet Dairy    |             9.32769e+06 |                     24.09 |
| PizzaFrost      |             8.14365e+06 |                     25.53 |
| BoldBites       |             7.92706e+06 |                     24.05 |
| SkyrNorth       |             7.73763e+06 |                     23.71 |
| LactoPure       |             6.14826e+06 |                     25.15 |
| LeafRitual      |             6.0996e+06  |                     23.69 |
| BioBloom        |             5.27986e+06 |                     23.65 |
| PurePulse       |             5.18341e+06 |                     22.79 |
| ToastMaster     |             4.68011e+06 |                     23.34 |
| Alpine Creamery |             4.67869e+06 |                     23.4  |
| FrostPeak       |             4.49542e+06 |                     24.02 |
| SweetSync       |             4.02346e+06 |                     23.57 |
| BrewCraft       |             3.98738e+06 |                     23.96 |
| Cultured Co.    |             3.95739e+06 |                     24.02 |
| MorningMilled   |             3.89491e+06 |                     23.27 |
| TableCraft      |             3.78637e+06 |                     24.06 |
| GrainGlow       |             3.54617e+06 |                     22.13 |
| NitroBoost      |             3.53593e+06 |                     23.19 |
| Vitaline        |             3.45361e+06 |                     23.39 |
| MorningMist     |             3.2361e+06  |                     24.68 |
| UmamiWave       |             3.12067e+06 |                     23.88 |
| RootCrunch      |             3.08495e+06 |                     22.41 |
| CoolHarvest     |             2.99526e+06 |                     23.71 |
| MintMarvel      |             2.89442e+06 |                     22.5  |
| NutriFlake      |             2.78059e+06 |                     23.09 |
| SeededHearth    |             2.75273e+06 |                     23.45 |
| GoldenClusters  |             2.65128e+06 |                     22.39 |
| FruitFuse       |             2.54379e+06 |                     24.92 |
| CrispCrave      |             2.53139e+06 |                     24.4  |
| GlowWater       |             2.49929e+06 |                     23.28 |
| FarmFresh       |             2.38106e+06 |                     23.29 |
| KernelPop       |             2.36989e+06 |                     23.6  |
| ToffeeTide      |             1.95038e+06 |                     22.68 |
| ArtisanOats     |             1.84405e+06 |                     21.95 |
| ArcticBite      |             1.65579e+06 |                     22.73 |
| ElectroFlow     |             1.2513e+06  |                     22.4  |
| PolarPantry     |             1.10961e+06 |                     20.57 |
| Salt & Stone    |             1.10954e+06 |                     22.8  |
| HydraVibe       |             1.08146e+06 |                     24.47 |
| GlazeGlory      |        597008           |                     24.71 |

---

## Q09 — Cat3 — Multi-table join

**Question:** What was numeric distribution for the Snacks category by banner in 2024?

### Reasoning

**Step 1 — Identify tables and columns**
- `fact_market`: To get `numeric_distribution_outlets`, `total_outlets_in_banner` (for the KPI), `banner` (for grouping), `week_date` (to derive `year`).
- `dim_product`: To map `sub_category` (from `fact_market`) to `category` (to filter for 'Snacks').

**Step 2 — Check semantic constraints and KPI computation rules**
- **KPI computation:** The query asks for "numeric distribution". This is a percentage KPI and should be calculated using the underlying components as per **Pattern P3** in Section 5: `SUM(numeric_distribution_outlets) * 100.0 / NULLIF(SUM(total_outlets_in_banner), 0)`. The pre-computed `numeric_distribution_pct` column in `fact_market` must not be used for aggregation.
- **Filtering:** The query specifies "in 2024", so we'll filter `fact_market.year = 2024`.
- **Join strategy:** The query involves `fact_market` and `dim_product` to filter `fact_market` rows based on a higher-level category (`Snacks`). `fact_market` has `sub_category` as a grain component, while `dim_product` provides the `category` for each `sub_category`. To avoid fan-out, we will first create a distinct mapping of `sub_category` to `category` from `dim_product` and then join `fact_market` to this mapping. This is implicitly assuming a `sub_category` belongs to only one `category`, which is a standard hierarchical design.
- **Flag exclusions:** Pattern P3 for numeric distribution does not require specific flag exclusions from `fact_market` as per Section 7.

**Step 3 — Clarify any ambiguous business terms**
- "numeric distribution": Interpreted as the `numeric_distribution_pct` KPI defined in Section 5 (P3) of the schema.
- "Snacks category": Interpreted as filtering `dim_product.category = 'Snacks'`.
- "banner": Interpreted as the `banner` column from `fact_market` (and `dim_customer`).
- "2024": Interpreted as `year = 2024`.

**Step 4 — Write the SQL**

### Generated SQL

```sql
WITH subcategory_category_map AS (
    -- Create a distinct mapping of sub_category to category from dim_product
    -- This prevents fan-out when joining with fact_market, assuming a sub_category
    -- belongs to a single category.
    SELECT DISTINCT
        sub_category,
        category
    FROM dim_product
)
SELECT
    fm.banner,
    ROUND(SUM(fm.numeric_distribution_outlets) * 100.0
          / NULLIF(SUM(fm.total_outlets_in_banner), 0), 2) AS numeric_distribution_pct
FROM fact_market fm
JOIN subcategory_category_map scm
    ON fm.sub_category = scm.sub_category
WHERE fm.year = 2024
  AND scm.category = 'Snacks'
GROUP BY fm.banner
ORDER BY fm.banner;
```

### Execution Result

**Status:** ✅ SUCCESS  
**Rows:** 15  
**Time:** 11.1ms  

| banner                |   numeric_distribution_pct |
|:----------------------|---------------------------:|
| Ashton Online         |                      64.66 |
| Ashton Retail         |                      63.16 |
| Campus & Co           |                      61.85 |
| CaterPro              |                      61.67 |
| CityStop              |                      63.7  |
| Cornerstone           |                      61.63 |
| Dealz Direct          |                      62.04 |
| FreshDoor             |                      64.53 |
| Hartfield's           |                      60.86 |
| HospitalityPlus       |                      61.5  |
| Meridian Supermarkets |                      62.74 |
| PantryBox             |                      60.92 |
| PoundSave             |                      62.74 |
| QuickShop Express     |                      63.5  |
| ValuMart              |                      63.24 |

---

## Q10 — Cat4 — Ambiguous FMCG term

**Question:** What was total revenue by brand in 2024?

### Reasoning

**Step 1 — Identify tables and columns**
- `fact_sales`: `year`, `product_id`, `net_revenue_gbp`, `is_zero_price`, `is_volume_outlier`
- `dim_product`: `product_id`, `brand`

**Step 2 — Check semantic constraints and KPI computation rules**
- **Flag exclusion patterns (Section 7):**
    - `is_zero_price = TRUE`: Exclude from `net_revenue_gbp` aggregations. This is critical.
    - `is_volume_outlier = TRUE`: Exclude from volume totals. Since `net_revenue_gbp` is derived from `volume_units`, excluding these rows ensures a "clean" revenue calculation consistent with clean volume.
- **Grain-locked columns:** Not applicable as `fact_market` is not used.
- **Join pattern selection:** Not applicable as `fact_market` is not used.

**Step 3 — Clarify any ambiguous business terms**
- "total revenue": Interpreted as `net_revenue_gbp` as per the default guidance.
- "by brand": The query will group the results by `brand` from `dim_product`.
- "in 2024": Filter `fact_sales.year = 2024`.

### Generated SQL

```sql
SELECT
    dp.brand,
    ROUND(SUM(fs.net_revenue_gbp), 2) AS total_net_revenue_gbp
FROM fact_sales fs
JOIN dim_product dp
  ON fs.product_id = dp.product_id
WHERE fs.year            = 2024
  AND fs.is_zero_price   = FALSE
  AND fs.is_volume_outlier = FALSE
GROUP BY dp.brand
ORDER BY total_net_revenue_gbp DESC;
```

### Execution Result

**Status:** ✅ SUCCESS  
**Rows:** 42  
**Time:** 63.5ms  

| brand           |   total_net_revenue_gbp |
|:----------------|------------------------:|
| CocoaEthos      |             2.8324e+07  |
| BerryBliss      |             2.59048e+07 |
| Velvet Dairy    |             2.03117e+07 |
| SkyrNorth       |             1.89179e+07 |
| BioBloom        |             1.80014e+07 |
| LactoPure       |             1.67856e+07 |
| SeededHearth    |             1.53045e+07 |
| ArtisanOats     |             1.52804e+07 |
| PizzaFrost      |             1.48762e+07 |
| GrainGlow       |             1.36203e+07 |
| NitroBoost      |             1.32069e+07 |
| FrostPeak       |             1.29671e+07 |
| TableCraft      |             1.24182e+07 |
| BoldBites       |             1.23819e+07 |
| ToastMaster     |             1.20402e+07 |
| PurePulse       |             1.12178e+07 |
| LeafRitual      |             1.11362e+07 |
| Alpine Creamery |             1.05349e+07 |
| MorningMist     |             1.04923e+07 |
| Vitaline        |             1.03077e+07 |
| Cultured Co.    |             1.01001e+07 |
| BrewCraft       |             9.73282e+06 |
| MintMarvel      |             9.24739e+06 |
| SweetSync       |             9.19753e+06 |
| GlowWater       |             9.10336e+06 |
| RootCrunch      |             9.09499e+06 |
| HydraVibe       |             8.89625e+06 |
| MorningMilled   |             8.69698e+06 |
| Salt & Stone    |             8.1936e+06  |
| PolarPantry     |             7.45815e+06 |
| CrispCrave      |             7.08321e+06 |
| UmamiWave       |             6.55655e+06 |
| CoolHarvest     |             6.21219e+06 |
| ArcticBite      |             5.71797e+06 |
| FarmFresh       |             5.61761e+06 |
| FruitFuse       |             5.50457e+06 |
| GlazeGlory      |             5.2484e+06  |
| ElectroFlow     |             5.19303e+06 |
| NutriFlake      |             5.04768e+06 |
| GoldenClusters  |             4.67455e+06 |
| ToffeeTide      |             4.54216e+06 |
| KernelPop       |             3.76725e+06 |

---

## Q11 — Cat4 — Ambiguous FMCG term

**Question:** What is the market share of the top 3 brands in the Beverages category?

### Reasoning

**Step 1 — Identify tables and columns:**

*   `fact_sales`: `net_revenue_gbp`, `product_id`, `is_zero_price`
*   `dim_product`: `brand`, `category`, `sub_category`, `product_id`
*   `fact_market`: `brand_volume_units`, `total_category_volume_units`, `brand`, `sub_category`, `week_date`, `banner`, `is_vol_violation`

**Step 2 — Check semantic constraints and KPI computation rules:**

*   **C3 & Section 8 Join Pattern**: The query requires data from both `fact_sales` (for ranking brands) and `fact_market` (for market share calculation). These tables have different grains, so a direct join is prohibited. I will use CTEs to first identify the top brands and then calculate market share, ensuring `fact_market`'s `total_category_volume_units` is aggregated correctly to avoid double-counting.
*   **KPI Computation Pattern (P1)**: Volume market share must be recomputed from `SUM(brand_volume_units) * 100.0 / NULLIF(SUM(total_category_volume_units), 0)`. The pre-computed `market_share_volume_pct` column in `fact_market` will not be used for this aggregated query.
*   **Flag Exclusion Patterns (Section 7)**:
    *   For `fact_sales` (net revenue calculation): Exclude rows `WHERE is_zero_price = TRUE`.
    *   For `fact_market` (market share calculation): Exclude rows `WHERE is_vol_violation = TRUE`.

**Step 3 — Clarify any ambiguous business terms:**

*   **"market share"**: Default to **volume market share**.
*   **"top 3 brands"**: I will rank brands by their **total net revenue** across the entire dataset duration within the 'Beverages' category.
*   **"Beverages category"**: This refers to `dim_product.category = 'Beverages'`. The market share calculation will be for the aggregate 'Beverages' category, not individual sub-categories.

**Step 4 — Write the SQL:**

### Generated SQL

```sql
WITH BrandRevenue AS (
    -- Step 1: Calculate total net revenue for each brand within the 'Beverages' category
    SELECT
        dp.brand,
        SUM(fs.net_revenue_gbp) AS total_net_revenue
    FROM fact_sales fs
    JOIN dim_product dp ON fs.product_id = dp.product_id
    WHERE dp.category = 'Beverages'
      AND fs.is_zero_price = FALSE
    GROUP BY dp.brand
),
TopBrands AS (
    -- Step 2: Identify the top 3 brands based on total net revenue
    SELECT brand
    FROM BrandRevenue
    ORDER BY total_net_revenue DESC
    LIMIT 3
),
CorrectCategoryMarketVolume AS (
    -- Step 3: Calculate the total market volume for the entire 'Beverages' category.
    -- We must sum total_category_volume_units distinctly for each (week_date, banner, sub_category)
    -- to avoid double-counting if multiple brands from the same sub_category exist in fact_market.
    SELECT
        SUM(sub_cat_total_volume) AS total_beverages_category_volume
    FROM (
        SELECT DISTINCT
            fm.week_date,
            fm.banner,
            fm.sub_category,
            fm.total_category_volume_units AS sub_cat_total_volume
        FROM fact_market fm
        JOIN dim_product dp ON fm.sub_category = dp.sub_category AND fm.brand = dp.brand
        WHERE dp.category = 'Beverages'
          AND fm.is_vol_violation = FALSE
    ) AS distinct_sub_category_totals
),
BrandVolumeInBeverages AS (
    -- Step 4: Calculate total brand volume for the identified top 3 brands within the 'Beverages' category
    SELECT
        dp.brand,
        SUM(fm.brand_volume_units) AS total_brand_volume
    FROM fact_market fm
    JOIN dim_product dp ON fm.brand = dp.brand AND fm.sub_category = dp.sub_category
    WHERE dp.category = 'Beverages'
      AND fm.brand IN (SELECT brand FROM TopBrands)
      AND fm.is_vol_violation = FALSE
    GROUP BY dp.brand
)
-- Final Step: Calculate volume market share for the top 3 brands
SELECT
    bvb.brand,
    ROUND(bvb.total_brand_volume * 100.0
          / NULLIF(ccmv.total_beverages_category_volume, 0), 2) AS market_share_volume_pct
FROM BrandVolumeInBeverages bvb, CorrectCategoryMarketVolume ccmv
ORDER BY market_share_volume_pct DESC;
```

### Execution Result

**Status:** ✅ SUCCESS  
**Rows:** 3  
**Time:** 45.6ms  

| brand      |   market_share_volume_pct |
|:-----------|--------------------------:|
| LeafRitual |                     45.55 |
| NitroBoost |                     28.51 |
| PurePulse  |                     28.35 |

---

## Q12 — Cat4 — Ambiguous FMCG term

**Question:** What is the average price of Dairy products sold through Tesco?

### Reasoning

**Step 1 — Identify tables and columns**
*   `fact_market`: `avg_shelf_price_gbp`, `banner`, `brand`, `sub_category`
*   `dim_product`: `category`, `brand`, `sub_category`

**Step 2 — Check semantic constraints and KPI computation rules**
*   **C4 — avg_shelf_price_gbp is a brand-level weekly average RSP**: This column represents the consumer-facing price as measured at the till, averaged across the brand's SKUs in a given banner and week. This is the appropriate metric for "average price" in this context.
*   **Flag Exclusion Patterns**:
    *   `is_zero_shelf_price = TRUE`: Exclude these rows from the average price calculation, as specified in Section 7.
    *   `is_vol_violation = TRUE`: Exclude these rows to maintain data integrity, as specified in Section 7 for measures relating to market performance, including `avg_shelf_price_gbp` when used in conjunction with volume metrics.

**Step 3 — Clarify any ambiguous business terms**
*   **"average price"**: Interpreted as the average consumer shelf price (`avg_shelf_price_gbp`), which is a brand-level weekly average RSP (Retail Selling Price) as measured in `fact_market`. This is distinct from the manufacturer's net invoice price (`sku_net_price_gbp` in `fact_sales`).
*   **"Dairy products"**: Refers to products where `dim_product.category = 'Dairy'`.
*   **"Tesco"**: Refers to the retail banner `fact_market.banner = 'Tesco'`.

### Generated SQL

```sql
SELECT
    AVG(fm.avg_shelf_price_gbp) AS average_dairy_shelf_price_tesco_gbp
FROM fact_market fm
JOIN dim_product dp
    ON fm.brand = dp.brand
    AND fm.sub_category = dp.sub_category
WHERE dp.category            = 'Dairy'
  AND fm.banner              = 'Tesco'
  AND fm.is_zero_shelf_price = FALSE
  AND fm.is_vol_violation    = FALSE;
```

### Execution Result

**Status:** ✅ SUCCESS  
**Rows:** 1  
**Time:** 10.0ms  

|   average_dairy_shelf_price_tesco_gbp |
|--------------------------------------:|
|                                   nan |

---

## Q13 — Cat5 — Time-period filter

**Question:** Compare total net revenue and volume units by category between 2024 and 2025.

### Reasoning

**Step 1 — Identify tables and columns**
- `fact_sales`: `year`, `net_revenue_gbp`, `volume_units`, `product_id`, `is_zero_price`, `is_volume_outlier`
- `dim_product`: `category`, `product_id`

**Step 2 — Check semantic constraints and KPI computation rules**
- **Flag Exclusion Pattern (Section 7):**
    - `is_zero_price = TRUE`: Exclude from `net_revenue_gbp` calculations.
    - `is_volume_outlier = TRUE`: Exclude from `volume_units` calculations.
- No direct involvement of `fact_market`, so join patterns (Pattern A/B) and KPI computation patterns (P1-P4) are not applicable.

**Step 3 — Clarify any ambiguous business terms**
- "net revenue": This will be calculated using `fact_sales.net_revenue_gbp`.
- "volume units": This will be calculated using `fact_sales.volume_units`.
- "between 2024 and 2025": This implies filtering for data from both these years and showing results side-by-side or as distinct rows for comparison.

### Generated SQL

```sql
SELECT
    dp.category,
    fs.year,
    SUM(CASE WHEN fs.is_zero_price = FALSE THEN fs.net_revenue_gbp ELSE 0 END) AS total_net_revenue_gbp,
    SUM(CASE WHEN fs.is_volume_outlier = FALSE THEN fs.volume_units ELSE 0 END) AS total_volume_units
FROM
    fact_sales AS fs
JOIN
    dim_product AS dp ON fs.product_id = dp.product_id
WHERE
    fs.year IN (2024, 2025)
GROUP BY
    dp.category,
    fs.year
ORDER BY
    dp.category,
    fs.year;
```

### Execution Result

**Status:** ✅ SUCCESS  
**Rows:** 12  
**Time:** 92.3ms  

| category      |   year |   total_net_revenue_gbp |   total_volume_units |
|:--------------|-------:|------------------------:|---------------------:|
| Beverages     |   2024 |             8.46573e+07 |          3.41902e+07 |
| Beverages     |   2025 |             8.60072e+07 |          3.44355e+07 |
| Cereals       |   2024 |             8.04139e+07 |          2.98923e+07 |
| Cereals       |   2025 |             7.9074e+07  |          2.94847e+07 |
| Confectionery |   2024 |             7.88457e+07 |          3.6757e+07  |
| Confectionery |   2025 |             7.70845e+07 |          3.62258e+07 |
| Dairy         |   2024 |             1.08907e+08 |          3.59916e+07 |
| Dairy         |   2025 |             1.06919e+08 |          3.55119e+07 |
| Frozen Food   |   2024 |             9.11671e+07 |          2.79055e+07 |
| Frozen Food   |   2025 |             8.96305e+07 |          2.75584e+07 |
| Snacks        |   2024 |             5.10411e+07 |          2.78196e+07 |
| Snacks        |   2025 |             4.99369e+07 |          2.74743e+07 |

---

## Q14 — Cat5 — Time-period filter

**Question:** What was total net revenue by channel in January 2025?

### Reasoning

**Step 1 — Identify tables and columns**
*   `fact_sales`: `net_revenue_gbp`, `year`, `month`, `customer_id`
*   `dim_customer`: `channel`, `customer_id`

**Step 2 — Check semantic constraints and KPI computation rules**
*   **Flag exclusion**: Apply `WHERE is_zero_price = FALSE` to `fact_sales` as specified in Section 7 (Flag Exclusion Patterns) for all revenue KPIs.
*   **Grain-locked columns/KPI computation**: Not applicable as no market share or price index KPIs are requested.
*   **Join pattern**: This query involves `fact_sales` and `dim_customer`, not `fact_market`, so join patterns A and B are not applicable. A direct join between `fact_sales` and `dim_customer` is appropriate.

**Step 3 — Clarify any ambiguous business terms**
*   "net revenue": As per the schema, this refers to `fact_sales.net_revenue_gbp`.
*   "January 2025": Filter `year = 2025` and `month = 1` from the `fact_sales` table.

**Step 4 — Write the SQL**

### Generated SQL

```sql
SELECT
    dc.channel,
    SUM(fs.net_revenue_gbp) AS total_net_revenue_gbp
FROM
    fact_sales AS fs
JOIN
    dim_customer AS dc
ON
    fs.customer_id = dc.customer_id
WHERE
    fs.year = 2025
    AND fs.month = 1
    AND fs.is_zero_price = FALSE
GROUP BY
    dc.channel
ORDER BY
    total_net_revenue_gbp DESC;
```

### Execution Result

**Status:** ✅ SUCCESS  
**Rows:** 5  
**Time:** 51.1ms  

| channel     |   total_net_revenue_gbp |
|:------------|------------------------:|
| Grocery     |             2.43939e+07 |
| Foodservice |             5.70465e+06 |
| Discounter  |             3.74615e+06 |
| eCommerce   |             2.79911e+06 |
| Convenience |             1.79774e+06 |

---

## Q15 — Cat5 — Time-period filter

**Question:** What was the weekly trend of volume units for the Confectionery category in H2 2025?

### Reasoning

**Step 1 — Identify tables and columns**
- `fact_sales`: `week_date`, `volume_units`, `year`, `quarter`, `is_volume_outlier`
- `dim_product`: `product_id`, `category`

**Step 2 — Check semantic constraints and KPI computation rules**
- **C6 (Flag Exclusion):** The `is_volume_outlier` flag applies. We must `WHERE is_volume_outlier = FALSE` to ensure the volume aggregation is clean and not impacted by anomalous values. (Section 7: "Exclude from volume totals requiring clean decomposition").
- No direct `fact_sales` to `fact_market` join is required.
- No grain-locked columns are being aggregated.
- No KPI computation patterns (P1-P4) are needed.

**Step 3 — Clarify any ambiguous business terms**
- "volume units": This refers to the `volume_units` column in `fact_sales`.
- "Confectionery category": This refers to `dim_product.category = 'Confectionery'`.
- "H2 2025": This translates to `fact_sales.year = 2025` and `fact_sales.quarter IN (3, 4)`.
- "weekly trend": This implies grouping the results by `week_date` and ordering them chronologically.

### Generated SQL

```sql
SELECT
    fs.week_date,
    SUM(fs.volume_units) AS total_volume_units
FROM fact_sales AS fs
JOIN dim_product AS dp
    ON fs.product_id = dp.product_id
WHERE
    dp.category = 'Confectionery'
    AND fs.year = 2025
    AND fs.quarter IN (3, 4)
    AND fs.is_volume_outlier = FALSE
GROUP BY
    fs.week_date
ORDER BY
    fs.week_date;
```

### Execution Result

**Status:** ✅ SUCCESS  
**Rows:** 26  
**Time:** 43.0ms  

| week_date           |   total_volume_units |
|:--------------------|---------------------:|
| 2024-12-30 00:00:00 |               677822 |
| 2025-07-07 00:00:00 |               708719 |
| 2025-07-14 00:00:00 |               706991 |
| 2025-07-21 00:00:00 |               706907 |
| 2025-07-28 00:00:00 |               698379 |
| 2025-08-04 00:00:00 |               684368 |
| 2025-08-11 00:00:00 |               707372 |
| 2025-08-18 00:00:00 |               698538 |
| 2025-08-25 00:00:00 |               700999 |
| 2025-09-01 00:00:00 |               687124 |
| 2025-09-08 00:00:00 |               682024 |
| 2025-09-15 00:00:00 |               672282 |
| 2025-09-22 00:00:00 |               687027 |
| 2025-09-29 00:00:00 |               700943 |
| 2025-10-06 00:00:00 |               701397 |
| 2025-10-13 00:00:00 |               700808 |
| 2025-10-20 00:00:00 |               693834 |
| 2025-10-27 00:00:00 |               667470 |
| 2025-11-03 00:00:00 |               687751 |
| 2025-11-10 00:00:00 |               693917 |
| 2025-11-17 00:00:00 |               699872 |
| 2025-11-24 00:00:00 |               701204 |
| 2025-12-01 00:00:00 |               691333 |
| 2025-12-08 00:00:00 |               682915 |
| 2025-12-15 00:00:00 |               698582 |
| 2025-12-22 00:00:00 |               691007 |

---
