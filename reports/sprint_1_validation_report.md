# Sprint 1 Validation Report
## Project Insight : Agentic Conversational BI
### F-01 Synthetic Dataset · F-02 Quality Injection · F-03 EDA & Preprocessing · F-04 Schema Data Dictionary · F-05 Environment & Scaffolding

**Sprint:** 1
**Run timestamp:** 2026-01-10 09:33:47  
**Methodology:** Track A — Manual validation via `validate_*` functions in `generate_data.py` and `preprocess.py`; Track B — File-system and environment checks

> **Track A approach:** `generate_data.py` exposes per-table `validate_*` functions that read each Parquet file and assert against acceptance criteria. `preprocess.py` emits an `eda_report.md` at the end of its run documenting all quality-issue handling decisions and derived measure statistics. No Gemini or DuckDB calls required for Sprint 1 validation.

---

## Section 1 — F-01: Synthetic FMCG Dataset Generation

Validation run against Parquet files in `data/raw/`. All four tables generated from `generate_data.py` with `seed=42`.

### dim_product

- ✅ **DP-01**: Row count 552 — within target range 540–552
- ✅ **DP-02**: `product_id` PK — 0 nulls, 552 unique values (= row count)
- ✅ **DP-03**: Active SKU count 497 — within target range 480–500 (`is_active = 'Y'`)
- ✅ **DP-04**: All 6 categories present (Dairy, Snacks, Beverages, Confectionery, Cereals, Ice Cream)
- ✅ **DP-05**: SKUs per brand–subcategory combination — all combos = 12 (no deviations)
- ✅ **DP-06**: Price sanity — 0 rows where `cost_price_gbp >= list_price_gbp`
- ✅ **DP-07**: `launch_date` stored as `object/string` — deliberate quality issue QI (pre-injection), dtype = object ✓
- ✅ **DP-08**: `is_active` stored as `object/string` with values `['Y', 'N']` — deliberate quality issue (pre-injection) ✓
- ✅ **DP-09**: No unintended nulls pre-injection — null check PASS

### dim_customer

- ✅ **DC-01**: Row count 240 — exact match (expect 240)
- ✅ **DC-02**: `customer_id` PK — 0 nulls, 240 unique values ✓
- ✅ **DC-03**: All 15 banners present with correct account counts — PASS (0 mismatches)
- ✅ **DC-04**: eCommerce structural NULLs — `region` NULL: 40/40 (100%); `territory` NULL: 40/40 (100%) ✓
- ✅ **DC-05**: NULL territory rate for Independent banners (Cornerstone, HospitalityPlus) — ~15% ✓
- ✅ **DC-06**: NULL `store_count` rate (non-eCommerce) — ~10% ✓
- ✅ **DC-07**: Store count ranges by channel (non-null) — within expected bounds ✓

### fact_sales

- ✅ **FS-01**: Row count ~2.3M — within expected range for 104 ISO weeks × 552 SKUs × 240 accounts (sparse)
- ✅ **FS-02**: `sales_id` PK — 0 nulls, all unique ✓
- ✅ **FS-03**: FK integrity — all `product_id` values present in `dim_product` ✓
- ✅ **FS-04**: FK integrity — all `customer_id` values present in `dim_customer` ✓
- ✅ **FS-05**: Date range — first `week_date` = 2024-01-01, last = 2025-12-29 (104 ISO weeks) ✓
- ✅ **FS-06**: `is_promoted` distribution — ~22% promoted rows (expect 20–25%) ✓
- ✅ **FS-07**: `net_revenue_gbp` > 0 for all non-zero-price rows pre-injection ✓
- ✅ **FS-08**: `baseline_volume` + `incremental_volume` consistent with `volume_units` pre-injection ✓

### fact_market

- ✅ **FM-01**: Row count ~44K — within expected range for 104 weeks × brands × sub_categories × banners ✓
- ✅ **FM-02**: PK composite (`week_date`, `brand`, `sub_category`, `banner`) — 0 duplicates ✓
- ✅ **FM-03**: `brand_volume_units <= total_category_volume_units` for all rows pre-injection ✓
- ✅ **FM-04**: `avg_shelf_price_gbp` > 0 for all rows pre-injection ✓
- ✅ **FM-05**: `numeric_distribution_outlets <= total_outlets_in_banner` for all rows ✓
- ✅ **FM-06**: Date range — 2024-01-01 to 2025-12-29, consistent with `fact_sales` ✓
- ✅ **FM-07**: No `manufacturer_net_price_gbp` column present in `fact_market` — deliberate design decision (panel data convention) ✓

**Section 1 result: 27/27 checks passed**

---

## Section 2 — F-02: Deliberate Quality Issue Injection

Validation run against Parquet files in `data/raw/qi-injected/`. `inject_quality_issues.py` verified to have produced all 8 quality issues without modifying `data/raw/` originals.

### dim_product (QI-01, QI-02)

- ✅ **QI-01**: `pack_type` casing/abbreviation corruption injected in ~5% of rows — cardinality increased from canonical to inflated count ✓
- ✅ **QI-02**: `variant` casing/abbreviation corruption injected in ~5% of rows — cardinality increased ✓
- ✅ **QI-IMP-01**: Raw `dim_product.parquet` in `data/raw/` unchanged — immutability preserved ✓

### dim_customer (pass-through)

- ✅ **QI-DC-01**: `dim_customer` copied unchanged — structural NULLs from `generate_data.py` preserved (~15% `territory`, ~10% `store_count`) ✓

### fact_sales (QI-03, QI-04, QI-05)

- ✅ **QI-03**: `sku_net_price_gbp = 0` injected in ~3% of rows (system recording error simulation) ✓
- ✅ **QI-04**: `volume_units` inflated 5–10× baseline in ~2% of rows — creates `volume_units ≠ baseline_volume + incremental_volume` internal inconsistency ✓
- ✅ **QI-05**: `promotion_mechanic = NULL` where `is_promoted = True` in ~22% of promoted rows (sparse POS mechanic capture) ✓
- ✅ **QI-IMP-02**: Raw `fact_sales.parquet` in `data/raw/` unchanged ✓

### fact_market (QI-06, QI-07, QI-08)

- ✅ **QI-06**: `avg_shelf_price_gbp = 0` injected in ~5% of rows (recording failure simulation) ✓
- ✅ **QI-07**: `brand_volume_units > total_category_volume_units` in ~1% of rows (constraint violation) ✓
- ✅ **QI-08**: 3–4 week temporal gaps injected for 4 selected banner × brand pairs — confirmed sparse in injected layer ✓
- ✅ **QI-IMP-03**: Raw `fact_market.parquet` in `data/raw/` unchanged ✓
- ✅ **QI-PERF-01**: Performance signals (NitroBoost growth, ValuMart decline, seasonal dip) intact — not modified by injection ✓

**Section 2 result: 13/13 checks passed**

---

## Section 3 — F-03: EDA and Preprocessing Pipeline

Validation run against Parquet files in `data/processed/`. `preprocess.py` run on `data/raw/qi-injected/` input. `eda_report.md` generated and reviewed.

### dim_product preprocessing

- ✅ **PP-01**: QI-01 `pack_type` casing normalised — cardinality reduced to canonical count using mapping table ✓
- ✅ **PP-02**: QI-02 `variant` casing normalised — cardinality reduced to canonical count ✓
- ✅ **PP-03**: `is_active` dtype converted from string `'Y'/'N'` → boolean ✓
- ✅ **PP-04**: `launch_date` dtype converted from string → `date` ✓

### dim_customer preprocessing

- ✅ **PP-05**: NULL `territory` imputed to `"Unknown-{Channel}"` string — 0 NULLs remaining ✓
- ✅ **PP-06**: NULL `store_count` imputed with channel median (not mean — right-skewed distribution documented in `eda_report.md`) ✓

### fact_sales preprocessing

- ✅ **PP-07**: `is_zero_price` boolean flag added — TRUE for all rows where `sku_net_price_gbp = 0` (~3%) ✓
- ✅ **PP-08**: `is_volume_outlier` boolean flag added — Tukey outer fence (IQR × 3.0) as primary detection; invariant cross-validation (`volume_units ≠ baseline_volume + incremental_volume`) as secondary confirmation ✓
- ✅ **PP-09**: `is_volume_outlier` flag rate ~2% — consistent with QI-04 injection rate ✓
- ✅ **PP-10**: QI-05 NULL `promotion_mechanic` — NOT imputed; documented as known sparseness in `eda_report.md` ✓

### fact_market preprocessing

- ✅ **PP-11**: `is_zero_shelf_price` boolean flag added — TRUE for rows where `avg_shelf_price_gbp = 0` (~5%) ✓
- ✅ **PP-12**: `is_vol_violation` boolean flag added — TRUE for rows where `brand_volume_units > total_category_volume_units` (~1%) ✓
- ✅ **PP-13**: QI-08 temporal gaps — NOT interpolated; documented in `eda_report.md` as true missing data ✓

### Derived fact_market measures

- ✅ **PP-14**: `market_share_volume_pct` = `brand_volume_units / total_category_volume_units × 100` — NaN where `is_vol_violation = True` ✓
- ✅ **PP-15**: `market_share_value_pct` = `brand_value_gbp / total_category_value_gbp × 100` — NaN where `is_vol_violation = True` or `is_zero_shelf_price = True` ✓
- ✅ **PP-16**: `numeric_distribution_pct` = `numeric_distribution_outlets / total_outlets_in_banner × 100` ✓
- ✅ **PP-17**: `price_index` = `avg_shelf_price_gbp / (total_category_value_gbp / total_category_volume_units) × 100` — NaN where `is_zero_shelf_price = True` or `is_vol_violation = True` ✓

### EDA visualisation output

- ✅ **EDA-01**: 8 Plotly Express plots generated to `data/eda_plots/`: `01_casing_cardinality.png` through `08_price_index_by_tier.png` ✓
- ✅ **EDA-02**: `eda_report.md` generated with all quality issue handling decisions and EDA statistics documented ✓
- ✅ **EDA-03**: IQR multiplier in `eda_viz.py` (3.0) matches `preprocess.py` — outer fence annotation consistent with flagging logic ✓

**Section 3 result: 20/20 checks passed**

---

## Section 4 — F-04: Schema Data Dictionary

Validation of `docs/schema_data_dictionary.md` against acceptance criteria.

- ✅ **SD-01**: All 4 clean-layer tables covered — column names, data types, FK relationships, and semantic definitions present for every field ✓
- ✅ **SD-02**: Derived measure definitions explicit — `market_share_volume_pct`, `market_share_value_pct`, `numeric_distribution_pct`, and `price_index` defined with formulas. Model instruction: do not treat these as stored raw columns ✓
- ✅ **SD-03**: Sparseness patterns documented — NULL `promotion_mechanic` means unknown mechanic (not non-promotional); QI-08 temporal gaps documented as true missing data (not zero sales) ✓
- ✅ **SD-04**: Explicit join guidance present — to compare `fact_sales` with `fact_market`, aggregate `fact_sales` to banner level via `dim_customer` first, then join on `week_date`, `brand`, `banner` ✓
- ✅ **SD-05**: Document injectable as plain text — token count verified within Gemini 2.5 Flash context window ✓
- ✅ **SD-06**: `manufacturer_net_price_gbp` absence in `fact_market` documented with business rationale (panel data licence convention — panel providers cannot observe bilateral trade terms) ✓

**Section 4 result: 6/6 checks passed**

---

## Section 5 — F-05: Project Environment & Scaffolding

- ✅ **ENV-01**: Folder structure established: `data/`, `src/`, `scripts/`, `logs/`, `tests/`, `docs/` all present ✓
- ✅ **ENV-02**: `requirements.txt` present with pinned package versions ✓
- ✅ **ENV-03**: Virtual environment documented in `README.md` ✓
- ✅ **ENV-04**: `.env.example` created; `.env` excluded from Git via `.gitignore` ✓
- ✅ **ENV-05**: Git repository initialised; `README.md` with setup and run instructions written ✓
- ✅ **ENV-06**: Gemini API key loaded from `.env` via `python-dotenv`; first test call verified ✓
- ✅ **ENV-07**: Key not hardcoded anywhere in codebase — `grep -r "AIza" .` returns empty ✓

**Section 5 result: 7/7 checks passed**

---

## Sprint 1 Closure Summary

**Total: 73/73 checks passed (0 failures)**

| Feature | Section | Checks | Result | Sprint status |
|---|---|---|---|---|
| **F-01** Synthetic dataset | §1 | 27 | ✅ 27/27 | ✅ Validated |
| **F-02** Quality injection | §2 | 13 | ✅ 13/13 | ✅ Validated |
| **F-03** EDA & preprocessing | §3 | 20 | ✅ 20/20 | ✅ Validated |
| **F-04** Schema data dictionary | §4 | 6 | ✅ 6/6 | ✅ Validated |
| **F-05** Environment & scaffolding | §5 | 7 | ✅ 7/7 | ✅ Validated |

### Key design decisions documented in Sprint 1

| Decision | Rationale | ADR |
|---|---|---|
| Three-layer pipeline (`raw/` → `qi-injected/` → `processed/`) | Prevents EDA from reading already-clean data; preserves immutable raw baseline | ADR-001 |
| `fact_market` at brand × sub_category × banner × week grain | Mirrors Nielsen/Kantar panel data licence grain; `manufacturer_net_price_gbp` excluded deliberately | Data Design |
| QI-05 NULL `promotion_mechanic` not imputed | Imputation would fabricate mechanic types not captured at POS; documented as true sparseness | `eda_report.md` |
| QI-08 temporal gaps not interpolated | Missing weeks represent true data absence (panel provider not reporting), not zero sales | `eda_report.md` |
| Channel median for `store_count` imputation (not mean) | Right-skewed store-count distributions — median more robust to large flagship stores | `eda_report.md` |
| Tukey outer fence IQR × 3.0 for volume outlier detection | Outer fence (vs inner × 1.5) reduces false positives on genuine promotional spikes | `preprocess.py` |

### Sprint 2 readiness

All Sprint 1 outputs are in place. Sprint 2 (NL2SQL Core) can begin:

- `data/processed/` — 4 clean Parquet files ready for DuckDB query engine
- `docs/schema_data_dictionary.md` — ready for RAG injection (F-07)
- `data/eda_plots/` — 8 EDA visualisations available for report appendix
- `docs/eda_report.md` — all preprocessing decisions documented
- `.env` — Gemini API key verified working

**Evidence artefacts produced this sprint:**
- `scripts/generate_data.py` — reproducible dataset generator (seed=42)
- `scripts/inject_quality_issues.py` — 8 deliberate quality issues
- `scripts/preprocess.py` — EDA + cleaning pipeline with `eda_report.md` output
- `scripts/eda_viz.py` — 8 Plotly Express EDA plots
- `docs/schema_data_dictionary.md` — treatment schema v1.0 (baseline for F-07)
- `data/eda_plots/*.png` — 8 report-quality visualisations
- `docs/eda_report.md` — auto-generated EDA decisions document

---

*Sprint 1 validated: 09 January 2026 · Project Insight · AM1 · Manu Mohandas *
