# Sprint 3 Validation Report — Agentic Loop + Conversation History

**Candidate:** Manu Mohandas | **Employer:** TCS  
**Run timestamp:** 2026-05-13 11:21:33  
**Model:** gemini-2.5-flash | **MAX_RETRIES:** 2  


---

## Section 1 — F-10: Retry Loop Wiring Check

The retry loop is exhaustively tested via mocks in `tests/test_agent.py` (hard cap, correction signal content, generate_sql call count per retry). This section confirms the live pipeline correctly surfaces `retry_count` and `turn_index` in the response dict, and that a normal query completes with `retry_count = 0`.

### F-10 Wiring Query

**Question:** How many distinct SKUs were sold in Q1 2025?

**Status:** ✅ SUCCESS  
**Turn index:** 0  
**Retry count:** 0  
**Exec time:** 42.9ms  
**Rows returned:** 1  

**Generated SQL:**
```sql
SELECT
    COUNT(DISTINCT product_id) AS distinct_skus_sold_q1_2025
FROM fact_sales
WHERE week_date >= '2025-01-01'
  AND week_date <= '2025-03-31';
```

**Result preview:**

|   distinct_skus_sold_q1_2025 |
|-----------------------------:|
|                          497 |

**Narrative:**
> In Q1 2025, our records show that 497 distinct SKUs were sold.


**F-10 Acceptance Criteria — Wiring Check:**

- ✅ **AC3 (hard cap)**: MAX_RETRIES constant = 2 (3 total attempts)
- ✅ **AC4 (retry_count exposed)**: retry_count present in live response
- ✅ **AC4 (turn_index exposed)**: turn_index present in live response
- ✅ **AC4 (clean query = 0 retries)**: retry_count = 0 on successful first attempt

_Full retry loop unit tests (error signal content, call count per retry, hard cap enforcement) are in `tests/test_agent.py::TestRetryLoop`._


---

## Section 2 — F-11: Multi-Turn Contextual Test (AC2)

Five sequential questions where each follow-up is contextually dependent on the prior answer.  The model must not re-explain context it has already seen.  Evidence of context retention: Turn 2 and beyond refer to brands/figures from Turn 1 without re-asking the underlying question.

### T1

**Question:** What were the top 3 brands by net revenue in 2025?

**Status:** ✅ SUCCESS  
**Turn index:** 0  
**Retry count:** 0  
**Exec time:** 66.0ms  
**Rows returned:** 3  

**Generated SQL:**
```sql
SELECT
    dp.brand,
    SUM(fs.net_revenue_gbp) AS total_net_revenue_gbp
FROM fact_sales AS fs
JOIN dim_product AS dp
    ON fs.product_id = dp.product_id
WHERE
    fs.year = 2025
    AND fs.is_zero_price = FALSE
    AND fs.is_volume_outlier = FALSE
GROUP BY
    dp.brand
ORDER BY
    total_net_revenue_gbp DESC
LIMIT 3;
```

**Result preview:**

| brand        |   total_net_revenue_gbp |
|:-------------|------------------------:|
| CocoaEthos   |             2.77581e+07 |
| BerryBliss   |             2.52547e+07 |
| Velvet Dairy |             2.00502e+07 |

**Narrative:**
> In 2025, the top 3 brands by net revenue were CocoaEthos, BerryBliss, and Velvet Dairy. CocoaEthos generated the highest net revenue at £27,758,131.82. Following closely, BerryBliss achieved £25,254,714.76, while Velvet Dairy secured the third position with £20,050,175.08 in net revenue.


### T2

**Question:** How did those same 3 brands perform in 2024?

**Status:** ✅ SUCCESS  
**Turn index:** 1  
**Retry count:** 0  
**Exec time:** 38.4ms  
**Rows returned:** 3  

**Generated SQL:**
```sql
SELECT
    dp.brand,
    SUM(fs.net_revenue_gbp) AS total_net_revenue_gbp
FROM fact_sales AS fs
JOIN dim_product AS dp
    ON fs.product_id = dp.product_id
WHERE
    fs.year = 2024
    AND dp.brand IN ('CocoaEthos', 'BerryBliss', 'Velvet Dairy')
    AND fs.is_zero_price = FALSE
    AND fs.is_volume_outlier = FALSE
GROUP BY
    dp.brand
ORDER BY
    total_net_revenue_gbp DESC;
```

**Result preview:**

| brand        |   total_net_revenue_gbp |
|:-------------|------------------------:|
| CocoaEthos   |             2.8324e+07  |
| BerryBliss   |             2.59048e+07 |
| Velvet Dairy |             2.03117e+07 |

**Narrative:**
> In 2024, CocoaEthos generated the highest net revenue among the three brands, achieving £28,323,977.71. BerryBliss followed with a total net revenue of £25,904,770.76, and Velvet Dairy recorded £20,311,651.40.


### T3

**Question:** Which of those 3 brands had the strongest revenue growth from 2024 to 2025?

**Status:** ✅ SUCCESS  
**Turn index:** 2  
**Retry count:** 0  
**Exec time:** 72.1ms  
**Rows returned:** 3  

**Generated SQL:**
```sql
WITH brand_revenue AS (
    SELECT
        dp.brand,
        fs.year,
        SUM(fs.net_revenue_gbp) AS total_net_revenue_gbp
    FROM fact_sales AS fs
    JOIN dim_product AS dp
        ON fs.product_id = dp.product_id
    WHERE
        dp.brand IN ('CocoaEthos', 'BerryBliss', 'Velvet Dairy')
        AND fs.year IN (2024, 2025)
        AND fs.is_zero_price = FALSE
        AND fs.is_volume_outlier = FALSE
    GROUP BY
        dp.brand,
        fs.year
)
SELECT
    br_2025.brand,
    br_2024.total_net_revenue_gbp AS revenue_2024_gbp,
    br_2025.total_net_revenue_gbp AS revenue_2025_gbp,
    ROUND(
        (br_2025.total_net_revenue_gbp - br_2024.total_net_revenue_gbp) * 100.0
        / br_2024.total_net_revenue_gbp,
        2
    ) AS revenue_growth_pct
FROM brand_revenue AS br_2024
JOIN brand_revenue AS br_2025
    ON br_2024.brand = br_2025.brand
WHERE
    br_2024.year = 2024
    AND br_2025.year = 2025
ORDER BY
    revenue_growth_pct DESC;
```

**Result preview:**

| brand        |   revenue_2024_gbp |   revenue_2025_gbp |   revenue_growth_pct |
|:-------------|-------------------:|-------------------:|---------------------:|
| Velvet Dairy |        2.03117e+07 |        2.00502e+07 |                -1.29 |
| CocoaEthos   |        2.8324e+07  |        2.77581e+07 |                -2    |
| BerryBliss   |        2.59048e+07 |        2.52547e+07 |                -2.51 |

**Narrative:**
> Velvet Dairy exhibited the strongest revenue growth from 2024 to 2025 among the three brands, experiencing a -1.29% change as revenue shifted from £20,311,651.40 to £20,050,175.08. In comparison, CocoaEthos saw a more significant decline of -2.00%, and BerryBliss had the steepest decrease at -2.51%.


### T4

**Question:** Break that top-growth brand's 2025 revenue down by channel.

**Status:** ✅ SUCCESS  
**Turn index:** 3  
**Retry count:** 0  
**Exec time:** 48.2ms  
**Rows returned:** 5  

**Generated SQL:**
```sql
SELECT
    dc.channel,
    SUM(fs.net_revenue_gbp) AS total_net_revenue_gbp
FROM fact_sales AS fs
JOIN dim_product AS dp
    ON fs.product_id = dp.product_id
JOIN dim_customer AS dc
    ON fs.customer_id = dc.customer_id
WHERE
    fs.year = 2025
    AND dp.brand = 'Velvet Dairy'
    AND fs.is_zero_price = FALSE
    AND fs.is_volume_outlier = FALSE
GROUP BY
    dc.channel
ORDER BY
    total_net_revenue_gbp DESC;
```

**Result preview:**

| channel     |   total_net_revenue_gbp |
|:------------|------------------------:|
| Grocery     |             1.26404e+07 |
| Foodservice |             3.40302e+06 |
| Discounter  |             2.29662e+06 |
| eCommerce   |             1.03125e+06 |
| Convenience |        678903           |

**Narrative:**
> For 2025, the top-growth brand's revenue is predominantly from the Grocery channel, generating £12,640,385.85. Foodservice contributed £3,403,017.04, while Discounter sales amounted to £2,296,622.37. eCommerce brought in £1,031,246.44, and the Convenience channel accounted for £678,903.38.


### T5

**Question:** Now show the weekly volume trend for that brand in H2 2025.

**Status:** ✅ SUCCESS  
**Turn index:** 4  
**Retry count:** 0  
**Exec time:** 47.0ms  
**Rows returned:** 26  

**Generated SQL:**
```sql
SELECT
    fs.week_date,
    dp.brand,
    SUM(fs.volume_units) AS total_volume_units
FROM fact_sales AS fs
JOIN dim_product AS dp
    ON fs.product_id = dp.product_id
WHERE
    dp.brand = 'Velvet Dairy'
    AND fs.year = 2025
    AND fs.quarter IN (3, 4)
    AND fs.is_volume_outlier = FALSE
GROUP BY
    fs.week_date,
    dp.brand
ORDER BY
    fs.week_date;
```

**Result preview:**

| week_date           | brand        |   total_volume_units |
|:--------------------|:-------------|---------------------:|
| 2024-12-30 00:00:00 | Velvet Dairy |               144056 |
| 2025-07-07 00:00:00 | Velvet Dairy |               139695 |
| 2025-07-14 00:00:00 | Velvet Dairy |               144205 |
| 2025-07-21 00:00:00 | Velvet Dairy |               148127 |
| 2025-07-28 00:00:00 | Velvet Dairy |               143776 |
| 2025-08-04 00:00:00 | Velvet Dairy |               136965 |
| 2025-08-11 00:00:00 | Velvet Dairy |               144146 |
| 2025-08-18 00:00:00 | Velvet Dairy |               142215 |
| 2025-08-25 00:00:00 | Velvet Dairy |               144576 |
| 2025-09-01 00:00:00 | Velvet Dairy |               139643 |

_...26 rows total (first 10 shown)_

**Narrative:**
> Velvet Dairy's weekly volume in H2 2025 has shown fluctuations. Starting at 139,695 units in the week of July 7th, volume peaked at 148,127 units by July 21st, before dropping to 136,965 units in the week of August 4th. Subsequently, volumes for Velvet Dairy have varied, with the latest visible data showing 139,643 units in the week of September 1st.


**F-11 Acceptance Criteria:**

- ✅ **AC1 (history injected)**: Prior turns passed to generate_sql on each call
- ✅ **AC2 (5-turn test)**: All 5 sequential contextual turns completed without error
- ✅ **AC1 (history grows)**: History length after 5 turns = 5 (expect 5)
- ✅ **AC3 (truncation logic)**: MAX_HISTORY_TURNS = 5 enforced in nl2sql.py (unit tested)
- ✅ **AC4 (turn counter)**: turn_index present in all 5 response dicts

**Turn index sequence:**

- T1: turn_index = 0 ✅
- T2: turn_index = 1 ✅
- T3: turn_index = 2 ✅
- T4: turn_index = 3 ✅
- T5: turn_index = 4 ✅


---

## Section 3 — F-12: Narrative Quality Test (AC4 — 5 Query Types)

Five stand-alone queries covering the five query types specified in F-12 AC4. Each narrative is manually assessed against AC2 (specific figures cited) and AC3 (both narrative and SQL present in response dict).

**Manual assessment criteria:** AC2 PASS = narrative contains at least one specific numeric figure from the result. AC2 FAIL = narrative is generic with no result-specific numbers.

### N1 — Volume trend

### 

**Question:** What was the total volume units sold per month for the Confectionery category in 2025?

**Status:** ✅ SUCCESS  
**Turn index:** 0  
**Retry count:** 0  
**Exec time:** 43.5ms  
**Rows returned:** 12  

**Generated SQL:**
```sql
SELECT
    fs.month,
    SUM(fs.volume_units) AS total_volume_units
FROM fact_sales AS fs
JOIN dim_product AS dp
    ON fs.product_id = dp.product_id
WHERE
    dp.category = 'Confectionery'
    AND fs.year = 2025
    AND fs.is_volume_outlier = FALSE
GROUP BY
    fs.month
ORDER BY
    fs.month;
```

**Result preview:**

|   month |   total_volume_units |
|--------:|---------------------:|
|       1 |          2.82437e+06 |
|       2 |          2.80876e+06 |
|       3 |          3.48514e+06 |
|       4 |          2.79769e+06 |
|       5 |          2.78031e+06 |
|       6 |          3.49996e+06 |
|       7 |          2.821e+06   |
|       8 |          2.79128e+06 |
|       9 |          3.4294e+06  |
|      10 |          2.76351e+06 |

_...12 rows total (first 10 shown)_

**Narrative:**
> In 2025, the Confectionery category's total volume units sold varied monthly. Sales for month 1 were 2,824,366.0 units, increasing to 3,485,138.0 units by month 3 and reaching 3,499,961.0 units in month 6. Monthly volumes also included 2,797,687.0 units in month 4 and 2,763,509.0 units in month 10, showing fluctuations throughout the year.


### N2 — Market share

### 

**Question:** What was NitroBoost's volume market share by quarter in 2025?

**Status:** ✅ SUCCESS  
**Turn index:** 0  
**Retry count:** 0  
**Exec time:** 10.4ms  
**Rows returned:** 4  

**Generated SQL:**
```sql
SELECT
    year,
    quarter,
    brand,
    ROUND(SUM(brand_volume_units) * 100.0
          / NULLIF(SUM(total_category_volume_units), 0), 2) AS market_share_volume_pct
FROM fact_market
WHERE brand            = 'NitroBoost'
  AND year             = 2025
  AND is_vol_violation = FALSE
GROUP BY
    year,
    quarter,
    brand
ORDER BY
    year,
    quarter;
```

**Result preview:**

|   year |   quarter | brand      |   market_share_volume_pct |
|-------:|----------:|:-----------|--------------------------:|
|   2025 |         1 | NitroBoost |                     23.83 |
|   2025 |         2 | NitroBoost |                     22.81 |
|   2025 |         3 | NitroBoost |                     24.61 |
|   2025 |         4 | NitroBoost |                     25.03 |

**Narrative:**
> NitroBoost's volume market share in 2025 started at 23.83% in Quarter 1 before slightly decreasing to 22.81% in Quarter 2. The brand then saw an increase to 24.61% in Quarter 3, concluding the year with its highest share of 25.03% in Quarter 4.


### N3 — Promotional uplift

### 

**Question:** What was the average volume uplift for promoted SKUs compared to non-promoted SKUs in 2024?

**Status:** ✅ SUCCESS  
**Turn index:** 0  
**Retry count:** 0  
**Exec time:** 46.7ms  
**Rows returned:** 1  

**Generated SQL:**
```sql
SELECT
    AVG(incremental_volume) AS average_promoted_volume_uplift_2024
FROM
    fact_sales
WHERE
    year = 2024
    AND is_promoted = TRUE
    AND is_zero_price = FALSE
    AND is_volume_outlier = FALSE;
```

**Result preview:**

|   average_promoted_volume_uplift_2024 |
|--------------------------------------:|
|                               51.3824 |

**Narrative:**
> In 2024, promoted SKUs achieved an average volume uplift of 51.38% compared to non-promoted SKUs. This indicates that promotional activities significantly increased sales volume during this period.


### N4 — Price analysis

### 

**Question:** What was the average shelf price by sub-category in Q4 2025?

**Status:** ✅ SUCCESS  
**Turn index:** 0  
**Retry count:** 0  
**Exec time:** 11.7ms  
**Rows returned:** 22  

**Generated SQL:**
```sql
SELECT
    sub_category,
    ROUND(SUM(brand_value_gbp) / NULLIF(SUM(brand_volume_units), 0), 2) AS avg_shelf_price_gbp
FROM
    fact_market
WHERE
        year                 = 2025
    AND quarter              = 4
    AND is_vol_violation     = FALSE
    AND is_zero_shelf_price  = FALSE
GROUP BY
    sub_category
ORDER BY
    sub_category;
```

**Result preview:**

| sub_category      |   avg_shelf_price_gbp |
|:------------------|----------------------:|
| Bags & Boxes      |                  2.77 |
| Butter & Spreads  |                  2.62 |
| Cheese            |                  4.92 |
| Chocolate Bars    |                  3.32 |
| Crisps & Popcorn  |                  1.81 |
| Frozen Veg        |                  3.05 |
| Fruit Juices      |                  3.32 |
| Functional/Energy |                  3.83 |
| Granola & Muesli  |                  5.04 |
| Ice Cream         |                  4.6  |

_...22 rows total (first 10 shown)_

**Narrative:**
> In Q4 2025, sub-category average shelf prices varied, with Granola & Muesli recording the highest average at £5.04, closely followed by Cheese at £4.92. Conversely, Crisps & Popcorn had the lowest average shelf price at £1.81. Other sub-categories like Chocolate Bars and Fruit Juices both averaged £3.32, while Bags & Boxes had an average shelf price of £2.77.


### N5 — Multi-brand comparison

### 

**Question:** Compare the top 5 brands by net revenue in 2025, showing each brand's total and percentage share of category revenue.

**Status:** ✅ SUCCESS  
**Turn index:** 0  
**Retry count:** 0  
**Exec time:** 78.5ms  
**Rows returned:** 5  

**Generated SQL:**
```sql
WITH sales_2025 AS (
    -- Filter and join base sales data for 2025, excluding flagged rows
    SELECT
        dp.brand,
        dp.category,
        fs.net_revenue_gbp
    FROM fact_sales fs
    JOIN dim_product dp ON fs.product_id = dp.product_id
    WHERE fs.year = 2025
      AND fs.is_zero_price = FALSE
      AND fs.is_volume_outlier = FALSE
),
brand_total_revenue_overall AS (
    -- Calculate total net revenue for each brand across all categories in 2025
    SELECT
        brand,
        SUM(net_revenue_gbp) AS brand_total_net_revenue_2025
    FROM sales_2025
    GROUP BY brand
),
top_5_brands AS (
    -- Identify the top 5 brands by their total net revenue
    SELECT
        brand,
        brand_total_net_revenue_2025
    FROM brand_total_revenue_overall
    ORDER BY brand_total_net_revenue_2025 DESC
    LIMIT 5
),
brand_categories AS (
    -- Get all unique categories that each of the top 5 brands sells in
    SELECT DISTINCT
        t5.brand,
        s.category
    FROM top_5_brands t5
    JOIN sales_2025 s ON t5.brand = s.brand
),
relevant_category_revenue AS (
    -- Calculate the total net revenue for all categories that each of the top 5 brands operates in.
    -- This forms the denominator for the "share of category revenue" metric.
    SELECT
        bc.brand,
        SUM(s.net_revenue_gbp) AS total_relevant_category_revenue
    FROM brand_categories bc
    JOIN sales_2025 s ON bc.category = s.category -- Sum sales from ALL brands within these relevant categories
    GROUP BY bc.brand
)
-- Final selection: combine brand totals, and calculate share of relevant category revenue
SELECT
    t5.brand,
    t5.brand_total_net_revenue_2025,
    ROUND(
        (t5.brand_total_net_revenue_2025 * 100.0)
        / NULLIF(rcr.total_relevant_category_revenue, 0),
        2
    ) AS percentage_share_of_category_revenue_2025
FROM top_5_brands t5
JOIN relevant_category_revenue rcr ON t5.brand = rcr.brand
ORDER BY t5.brand_total_net_revenue_2025 DESC;
```

**Result preview:**

| brand        |   brand_total_net_revenue_2025 |   percentage_share_of_category_revenue_2025 |
|:-------------|-------------------------------:|--------------------------------------------:|
| CocoaEthos   |                    2.77581e+07 |                                       38.61 |
| BerryBliss   |                    2.52547e+07 |                                       16.29 |
| Velvet Dairy |                    2.00502e+07 |                                       10.98 |
| SkyrNorth    |                    1.85175e+07 |                                       18.63 |
| BioBloom     |                    1.75391e+07 |                                       17.65 |

**Narrative:**
> In 2025, CocoaEthos was the top brand by net revenue, achieving £27,758,131.82 and representing 38.61% of the category's total revenue. BerryBliss followed with £25,254,714.76 (16.29% share), then Velvet Dairy at £20,050,175.08 (10.98% share). The remaining top five brands were SkyrNorth, which generated £18,517,487.04 (18.63% share), and BioBloom with £17,539,072.59 (17.65% share).


**F-12 Acceptance Criteria:**

- ✅ **AC1 (second Gemini call)**: narrative key present in all 5 responses
- **AC2 (specific figures):** ⚠️  **Manual assessment required.** Review each narrative above — PASS if specific numbers/brand names cited, FAIL if generic text only.
- ✅ **AC3 (narrative + SQL in response)**: Both keys present in all 5 response dicts
- ✅ **AC4 (5 query types)**: 5/5 queries returned non-empty narrative

---

## Sprint 3 Closure Summary

| Feature | Unit Tests | Live Validation | Status |
|---|---|---|---|
| F-10 Self-Correction Retry Loop | `tests/test_agent.py::TestRetryLoop` | Wiring check: ✅ | ✅ Validated |
| F-11 Conversation History | `tests/test_agent.py::TestConversationHistory` | 5-turn test: ✅ | ✅ Validated |
| F-12 Narrative Generation | `tests/test_narrative.py` | 5-type test: ✅ | ✅ Validated (pending AC2 manual check) |


_AC2 (narrative cites specific figures) requires manual review of the narrative outputs in Section 3 above.  Mark F-12 Validated only after confirming at least 4/5 narratives contain result-specific numbers._


**Next step:** Update F-10, F-11, F-12 status to `Validated` in `AM1_Feature_Register.md` after manual AC2 review.