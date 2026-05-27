**Version 1:** Sprint 2 (15 Qs) | **Version 2:** Sprint 5 (20 Qs)
### Q01 : How many distinct SKUs were sold in Q1 2024?

```sql
select 
  count (distinct product_id) 
from
  fact_sales 
where 
  "year" = 2024 
  and "quarter" = 1
;
```

### Q02 : What are the top 10 SKUs by net revenue in 2025 for active products only?

```sql
select 
  dp.product_id,
  dp.sku_name,
  sum(fs.net_revenue_gbp) as net_revenue
from 
  fact_sales as fs
join 
  dim_product as dp on fs.product_id = dp.product_id
where 
  dp.is_active = true
  and fs.is_zero_price = false
  and fs.year = 2025
group by 
  dp.product_id, 
  dp.sku_name
order by 
  net_revenue desc
limit 10;
```

### Q03 : What was the total incremental volume from promotional activity in 2024?

```sql
select
  sum(incremental_volume) as '2024_incr_vol'
from
  fact_sales
where
  year = 2024
  and is_volume_outlier = false
;
```

### Q04 : What was total gross revenue and total trade discount by channel in 2025?

```sql
select
  dc.channel,
  printf('%,.2f', sum(fs.gross_revenue_gbp)) as '2025_gross_revenue',
  printf('%,.2f', sum(fs.trade_discount_gbp)) as '2025_trade_discount'
from 
  fact_sales as fs
join
  dim_customer as dc using (customer_id)
where
  fs.year = 2025
  and is_zero_price = false
group by channel
order by channel
;
```

### Q05 : What was NitroBoost's volume market share in 2024 by quarter?

```sql
select
  quarter,
  sum(brand_volume_units),
  sum(total_category_volume_units),
  round(100 * sum(brand_volume_units) / nullif(sum(total_category_volume_units),0),2) as vol_market_share
from
  fact_market as fm
where
  fm.year = 2024
  and fm.is_vol_violation = false
  and fm.brand = 'NitroBoost'
group by quarter
;
```

### Q06 : What was the price index for the Dairy category across all banners in 2025?

```sql
select
  sum(fm.brand_value_gbp) / nullif(sum(fm.brand_volume_units),0) as avg_brand_srp,
  sum(fm.total_category_value_gbp) / nullif(sum(fm.total_category_volume_units),0) as avg_category_srp,
  printf('%.2f',100 * avg_brand_srp / nullif(avg_category_srp,0)) as cat_price_index
from
  fact_market as fm
join
  (
  select distinct
    sub_category,
    category
  from
    dim_product
  )as dp using (sub_category)
where
  fm.year = 2025
  and fm.is_zero_shelf_price = false
  and fm.is_vol_violation = false
  and dp.category = 'Dairy'
;
```

### Q07 : What was net revenue by region and category in Q4 2025?

```sql
select
  dc.region,
  dp.category,
  '£ ' || printf('%,.2f',sum(fs.net_revenue_gbp)) as total_net_revenue
from
  fact_sales as fs
join
  dim_product as dp using (product_id)
join
  dim_customer as dc using (customer_id)
where
  fs.year = 2025
  and fs.quarter = 4
  and is_zero_price = false
group by 
  dc.region, dp.category
order by
  dc.region, dp.category
;
```

### Q08 : For the Grocery channel, what was net revenue and volume market share by brand in 2025?

```sql
with sales_agg as
(
  select 
    fs.week_date, dp.brand, dc.banner,
    sum(fs.net_revenue_gbp) as 'net_revenue'
  from fact_sales as fs
  join dim_product as dp using (product_id)
  join dim_customer as dc using (customer_id)
  where
    fs.year = 2025
    and fs.is_zero_price = false
    and dc.channel = 'Grocery'
    -- and fs.is_volume_outlier = false --> LLM used this condition - is this relevant as we are only drawing net_revenue?
    -- The 'fs.is_volume_outlier = false' is causing a difference is the net revenue figure. Need to discuss with Claude.
  group by
    fs.week_date, dp.brand, dc.banner
),

market_agg as
(
  select 
    fm.week_date, fm.brand, fm.banner,
    sum(fm.brand_volume_units) as 'brand_volume',
    sum(fm.total_category_volume_units) as 'catgeory_volume'
  from fact_market as fm
  join
  (
    select distinct
      banner, channel
    from
      dim_customer
  ) as dc using (banner) --> LLM did not use distinct, will this cause a fan out as the dim_customer has a finer grain?
  where
    fm.year = 2025
    and fm.is_vol_violation = false
    and dc.channel = 'Grocery'
  group by
    fm.week_date, fm.brand, fm.banner
)

select
brand,
'£ ' || printf('%,.2f', sum(net_revenue)) as '2025_net_reveue',
printf('%.2f%%', 100 * sum(brand_volume)/nullif(sum(catgeory_volume),0)) as '2025_volume_market_share'
from
  sales_agg as sa
join
  market_agg as ma using (week_date, brand, banner)
group by brand
order by sum(net_revenue) desc
;
```

### Q09 : What was numeric distribution for the Snacks category by banner in 2024?

```sql
select
  fm.banner,
  printf('%.2f%%', 
  100 * sum(fm.numeric_distribution_outlets) / nullif(sum(fm.total_outlets_in_banner),0)) as num_distr_perc
from
  fact_market as fm
join
  (
  select distinct
    sub_category,
    category
  from
    dim_product
  )as dp using (sub_category)
where
  fm.year = 2024
  and dp.category = 'Snacks'
group by fm.banner
order by fm.banner
;
```

### Q10 : What was total revenue by brand in 2024?

```sql
select
  dp.brand,
  '£ ' || printf('%,.2f', sum(net_revenue_gbp)) as '2024_total_revenue'
from
  fact_sales as fs
join
  dim_product as dp using (product_id)
where
  fs.year = 2024
  and fs.is_zero_price = false
   -- and fs.is_volume_outlier = false --> LLM used this condition - is this relevant as we are only drawing net_revenue?
   -- LLM is using the rationale 'Since net_revenue_gbp is derived from volume_units, excluding these rows ensures a "clean" revenue calculation consistent with clean volume.'
   -- The 'fs.is_volume_outlier = false' is causing a difference is the net revenue figure. Need to discuss with Claude.
group by
  dp.brand
order by sum(net_revenue_gbp) desc
;
```

### Q11 : What is the market share of the top 3 brands in the Beverages category?
I am really far away from LLM on this one - may be I am wrong; Need to validate.

```sql
with top_3_bev_brands as
(
  select
  dp.sub_category,
  dp.brand,
  sum(fs.net_revenue_gbp) as brand_revenue
  from
    fact_sales as fs
  inner join  
  (
    select
      product_id,      
      brand,
      sub_category
    from
      dim_product
    where category = 'Beverages'
  ) as dp using (product_id)
  where
    fs.is_zero_price = false
  group by dp.brand,sub_category
  order by brand_revenue desc
  limit 3
)

select
 fm.brand,
 round(100 * sum(brand_volume_units)/nullif(sum(total_category_volume_units),0),2) 
   as 'volume_market_share'
from
  fact_market as fm
inner join
  top_3_bev_brands
    using (brand, sub_category)
where
  fm.is_vol_violation = false
group by fm.brand
order by 2 desc
;
```

### Q12 : What is the average price of Dairy products sold through Tesco?

```sql
select
dp.category,
round(sum(fm.brand_value_gbp)/sum(fm.brand_volume_units),2) as avg_price
from
  fact_market fm
join
  (
    select distinct 
    brand, sub_category,category 
    from dim_product 
    where category = 'Dairy'
  ) as dp using (brand, sub_category)
where
  fm.is_zero_shelf_price = false
  and fm.is_vol_violation = false
  and fm.banner = 'Tesco'
group by dp.category
;
```

### Q13 : Compare total net revenue and volume units by category between 2024 and 2025.

```sql
with category_year_vol_revenue as
(
  select
    dp.category,
    fs.year,
    sum(case when fs.is_volume_outlier = false then fs.volume_units else 0 end) as vol_per_year,
    round(sum(case when is_zero_price = false then fs.net_revenue_gbp else 0 end),2) as revenue_per_year
  from
    fact_sales as fs
  join
    dim_product as dp using (product_id)
  group by
    dp.category,
    fs.year
)

pivot
(
  select category, year, vol_per_year, revenue_per_year
  from category_year_vol_revenue
)
on year
using sum(vol_per_year) as volume, sum(revenue_per_year) as revenue
;
```

### Q14 : What was total net revenue by channel in January 2025?

```sql
select
dc.channel,
'£ ' || printf('%,.2f', sum(net_revenue_gbp)) as total_net_revenue
from fact_sales as fs
join dim_customer as dc using (customer_id)
where fs.is_zero_price = false
  and fs.year = 2025
  and fs.month = 1
group by dc.channel
order by sum(net_revenue_gbp) desc
;
```

### Q15 : What was the weekly trend of volume units for the Confectionery category in H2 2025?

```sql
select
fs.week_date::date as week_starting,
sum(fs.volume_units) as volume_units
from fact_sales as fs
join dim_product as dp using (product_id)
where dp.category = 'Confectionery'
  and fs.is_volume_outlier = false
  and fs.year = 2025
  and fs.quarter in (3,4)
  and fs.week_number > 1 -- There are some rows with week_date as '2024-12-30' but with year as 2025 for some reason.
group by week_starting
order by week_starting
;
```

### Q16 : Total net revenue by brand for 2025, excluding volume outlier weeks

```sql
select
  dp.brand,
  '£ ' || printf('%,.2f', sum(net_revenue_gbp)) as '2025_net_revenue'
from
  fact_sales as fs
  join dim_product as dp using (product_id)
where
  fs.is_volume_outlier = false
  and is_zero_price = false
  and fs.year = 2025
group by
  dp.brand
order by
  sum(net_revenue_gbp) desc
```

### Q17 : BerryBliss's volume market share in the Sugar Sweets sub-category, all banners combined, in H1 2025

```sql
select
  round(100 * sum(brand_volume_units) / sum(total_category_volume_units), 2) as volume_market_share_pct
from
  fact_market
where
  brand = 'BerryBliss'
  and sub_category = 'Sugar Sweets'
  and year = 2025
  and quarter in (1, 2)
  and is_vol_violation = false
```

### Q18 : CocoaEthos average weekly net revenue: Q2 2025 vs Q4 2025

```sql
SELECT
  '2025Q' || fs.quarter as quarter,
  ROUND(SUM(fs.net_revenue_gbp) / NULLIF(COUNT(DISTINCT fs.week_date), 0), 2) AS avg_weekly_net_revenue_gbp
FROM
  fact_sales AS fs
  JOIN dim_product AS dp ON fs.product_id = dp.product_id
WHERE
  dp.brand = 'CocoaEthos'
  AND fs.year = 2025
  AND fs.quarter IN (2, 4)
  AND fs.is_zero_price = FALSE
  AND fs.is_volume_outlier = FALSE
GROUP BY
  fs.quarter
```

### Q19 : Brands in Confectionery category that declined by more than 2% in net revenue from 2024 to 2025

```sql
WITH brand_rev AS (
    SELECT
        dp.brand,
        SUM(CASE WHEN fs.year = 2024 THEN fs.net_revenue_gbp ELSE 0 END) AS rev_2024,
        SUM(CASE WHEN fs.year = 2025 THEN fs.net_revenue_gbp ELSE 0 END) AS rev_2025
    FROM fact_sales AS fs
    JOIN dim_product AS dp
        ON fs.product_id = dp.product_id
    WHERE dp.category          = 'Confectionery'
      AND fs.year              IN (2024, 2025)
      AND fs.is_zero_price     = FALSE
      AND fs.is_volume_outlier = FALSE
    GROUP BY dp.brand
)
SELECT
    brand,
    ROUND(rev_2024, 2)                                            AS net_revenue_2024_gbp,
    ROUND(rev_2025, 2)                                            AS net_revenue_2025_gbp,
    ROUND((rev_2025 - rev_2024) / NULLIF(rev_2024, 0) * 100, 2)  AS growth_rate_pct
FROM brand_rev
WHERE rev_2024 > 0
  AND (rev_2025 - rev_2024) / NULLIF(rev_2024, 0) * 100 < -2
ORDER BY growth_rate_pct ASC;
```

### Q20 : Multi-turn ·  T1 - top 3 brands by net revenue Q3 2025

```sql
SELECT
    dp.brand,
    SUM(fs.net_revenue_gbp) AS total_net_revenue_gbp
FROM fact_sales AS fs
JOIN dim_product AS dp
    ON fs.product_id = dp.product_id
WHERE fs.year              = 2025
  AND fs.quarter           = 3
  AND fs.is_zero_price     = FALSE
  AND fs.is_volume_outlier = FALSE
GROUP BY dp.brand
ORDER BY total_net_revenue_gbp DESC
LIMIT 3;
```
### Q20 : Multi-turn ·  T2 - compare those 3 brands Q3 2024 vs Q3 2025

```sql
SELECT
    dp.brand,
    fs.year,
    SUM(fs.net_revenue_gbp) AS total_net_revenue_gbp
FROM fact_sales AS fs
JOIN dim_product AS dp
    ON fs.product_id = dp.product_id
WHERE dp.brand             IN ('CocoaEthos', 'BerryBliss', 'Velvet Dairy')
  AND fs.quarter           = 3
  AND fs.year              IN (2024, 2025)
  AND fs.is_zero_price     = FALSE
  AND fs.is_volume_outlier = FALSE
GROUP BY dp.brand, fs.year
ORDER BY dp.brand, fs.year;

```