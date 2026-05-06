# Decision Log — Project Insight: Agentic Conversational BI
**AM1 | BCS Level 7 AI Data Specialist | Manu Mohandas | TCS**
Last updated: 2026-05-04

---

## How to use this document

Each entry follows a fixed structure:
- **Context** — what situation prompted the decision
- **Decision** — what was chosen
- **Rationale** — why, including the analytical or technical reasoning
- **Alternatives considered**ADR-023 — what was rejected and why
- **KSB mapping** — which KSBs this decision evidences
- **Implementation** — where in the codebase the decision lives
- **EDA / report evidence** — plots or report sections that cite this decision

When an assessor asks "why did you choose X?" — the ADR is the answer.
When writing the report — the Rationale field is the paragraph.

---

## Data Architecture Decisions

---

### ADR-001 — Three-layer data architecture (raw / qi-injected / processed)

**Context**
Sprint 1 originally used a two-layer architecture: `data/raw/` (clean generated)
and `data/processed/` (inject_quality_issues.py output, later overwritten by
preprocess.py). This created a sequencing dependency: `eda_viz.py` had to run
before `preprocess.py` or it would read already-cleaned data, undermining the
EDA narrative of "discovering" quality issues.

**Decision**
Introduce a three-layer architecture:
- `data/raw/` — immutable clean baseline from generate_data.py; never modified
- `data/raw/qi-injected/` — QI-injected layer from inject_quality_issues.py
- `data/processed/` — clean analytics layer from preprocess.py

**Rationale**
The three layers map cleanly to a data pipeline diagram citable in the report.
`eda_viz.py` reads from `qi-injected/` and has no execution-order dependency
on `preprocess.py`. `raw/` is permanently preserved as the clean ground truth —
a critical audit trail for a controlled synthetic data experiment.

**Alternatives considered**
- Two-layer (raw / processed): rejected — creates sequencing dependency for EDA
  visualisation and conflates dirty and clean states in the same directory
- Reading eda_viz.py from raw/: rejected — raw/ doesn't contain injected quality
  issues so the EDA wouldn't show the problems being analysed

**KSB mapping** K8, K9, S7, K26
**Implementation**
- `inject_quality_issues.py` → `DIRTY_DIR = data/raw/qi-injected/`
- `preprocess.py` → reads `DIRTY_DIR`, writes `PROCESSED_DIR`
- `eda_viz.py` → reads `RAW_DIR` and `DIRTY_DIR`

---

### ADR-002 — Single module for all four data generators (no splitting)

**Context**
During Sprint 1 dim_product build, question arose whether to split generators
into separate files (one per table) for modularity.

**Decision**
Keep all four generator functions in a single `generate_data.py` module.

**Rationale**
All four tables share global constants (SEED, PRICE_RANGES, SUBCAT_TO_BRAND,
performance signal parameters) and are tightly coupled by FK dependencies —
fact_sales and fact_market both require dim_product and dim_customer PKs as
inputs. Splitting into separate files would require either duplicating shared
constants or introducing an import chain that makes FK validation harder to
enforce. The `main()` function already enforces the correct generation order.

**Alternatives considered**
- Separate modules per table: rejected — FK coupling and shared constants make
  this more complex than a single well-organised module
- Shared constants module + separate generators: rejected — over-engineering for
  a four-table synthetic dataset; adds import complexity for no analytical gain

**KSB mapping** S7, K8
**Implementation** `scripts/generate_data.py`

---

### ADR-003 — scripts/ at root for pipeline code; src/ for application code

**Context**
Initial Feature Register (F-05) did not include a `scripts/` directory. All
batch pipeline files would have sat in `src/` alongside application code.

**Decision**
Add `scripts/` at the project root for all batch/pipeline files
(`generate_data.py`, `inject_quality_issues.py`, `preprocess.py`,
`eda_viz.py`). Reserve `src/` exclusively for the Streamlit application and
NL2SQL modules.

**Rationale**
Batch pipeline files are run once to produce data artefacts; application code
runs continuously at query time. Mixing them in `src/` would make the
application boundary ambiguous and complicate any future packaging or
deployment. The separation also makes it immediately clear in the repo structure
which files are infrastructure and which are the assessed system.

**Alternatives considered**
- Everything in `src/`: rejected — no separation between pipeline and app code
- Everything in `scripts/`: rejected — application modules in `scripts/` is
  semantically incorrect and would make imports harder to manage

**KSB mapping** K8, S7
**Implementation** F-05 in AM1_Feature_Register.md

---

### ADR-004 — SEED=42 for generation; INJECT_SEED=99 for injection (independent seeds)

**Context**
Both generate_data.py and inject_quality_issues.py use numpy random draws.
Question: use the same seed or independent seeds?

**Decision**
Use independent seeds: `SEED=42` in generate_data.py; `INJECT_SEED=99` in
inject_quality_issues.py.

**Rationale**
Independent seeds guarantee that injection draws are not correlated with
generation draws. If the same seed were used, the sequence of random numbers
consumed by the generator would shift the injection draws in a correlated way —
for example, the rows selected for zero-price injection might systematically
overlap with the rows that received the highest promotional uplift, creating
a spurious pattern not present in real data. Separate seeds ensure the quality
issue distribution is independent of the underlying data generation structure.
Full reproducibility is maintained: running both scripts with their respective
seeds always produces identical output.

**Alternatives considered**
- Single shared seed: rejected — correlated draws could create unintended
  patterns between quality issues and performance signals
- No seed (non-reproducible): rejected — reproducibility is a hard requirement
  for an assessed project where EDA findings must be consistently verifiable

**KSB mapping** K26, S11
**Implementation**
- `generate_data.py` → `SEED = 42`
- `inject_quality_issues.py` → `INJECT_SEED = 99`

---

## Data Generation Decisions

---

### ADR-005 — is_active stored as Y/N string; launch_date stored as string in raw

**Context**
Schema design decision: whether to store boolean and date columns in their
natural types in the raw layer, or as strings requiring type coercion.

**Decision**
Store `is_active` as `"Y"/"N"` VARCHAR and `launch_date` as `"YYYY-MM-DD"`
VARCHAR in `data/raw/`. Parse both to correct types in `preprocess.py`.

**Rationale**
These are deliberate quality issues baked into the raw layer to create a
realistic EDA scenario. Real FMCG source systems (SAP, Oracle) commonly export
boolean flags as Y/N strings and dates as VARCHAR in CSV/Parquet exports. This
gives `preprocess.py` a genuine type coercion task to demonstrate and document,
rather than only handling NULL imputation and casing normalisation.

**Alternatives considered**
- Boolean and date types in raw: rejected — removes a realistic preprocessing
  step and reduces the EDA evidence base

**KSB mapping** S22, K3
**Implementation**
- `generate_data.py` → `assign_is_active()` returns `"Y"/"N"` string
- `preprocess.py` → `normalise_dim_product()` coerces both columns

---

### ADR-006 — get_price_tier uses if/elif/else (not sequential if statements)

**Context**
Initial implementation used two sequential `if` statements for price tier
assignment. Identified as a bug during code review in Sprint 1.

**Decision**
Use `if/elif/else` branching for `get_price_tier()`.

**Rationale**
The three price tiers (Premium, Mainstream, Value) are mutually exclusive and
exhaustive — a brand belongs to exactly one tier. Sequential `if` statements
evaluate all conditions regardless of whether an earlier one matched, which is
semantically incorrect for mutually exclusive categories and would be a runtime
error if any logic overlap existed. `if/elif/else` correctly short-circuits at
the first match and guarantees exactly one branch executes.

**Alternatives considered**
- Dictionary lookup: considered — would be cleaner for a larger tier set, but
  `if/elif/else` is more readable for three tiers with string conditions
- Sequential `if` statements: rejected — semantically wrong for mutually
  exclusive categories; bug confirmed in code review

**KSB mapping** K3
**Implementation** `generate_data.py` → `get_price_tier()`

---

### ADR-007 — assign_is_active uses independent if statements (not if/elif/else)

**Context**
Follow-on from ADR-006. Question: should `assign_is_active()` also use
`if/elif/else`?

**Decision**
Keep independent `if` statements in `assign_is_active()`.

**Rationale**
The two inactivation conditions (old launch year AND value brand) are
*independent* business rules, not mutually exclusive branches. A SKU can
simultaneously be old (launch_year < 2020) AND be a value brand — both
conditions may apply to the same row. Using `if/elif/else` would prevent the
second condition from being evaluated when the first matches, understating
inactivation rates for old value brand SKUs. Sequential `if` statements
correctly allow both conditions to be evaluated independently.

**Alternatives considered**
- if/elif/else: rejected — would incorrectly prevent second condition evaluation
  for SKUs satisfying both criteria
- Combined single condition: considered but rejected — conflates two logically
  distinct business rules into one expression, reducing readability

**KSB mapping** K3
**Implementation** `generate_data.py` → `assign_is_active()`

---

### ADR-008 — Performance signals applied to baseline_volume before promotion draw

**Context**
Four structural performance signals are embedded in fact_sales:
NitroBoost +18% YoY, Porridge & Oats Q3 ×0.65, Ice Cream Q4 ×0.60,
ValuMart 2025 linear decline 1.00→0.82. Decision: apply signals to
`baseline_volume` or to total `volume_units`?

**Decision**
Apply all performance signals to `baseline_volume` before the promotional
draw, not to `volume_units` after.

**Rationale**
Performance signals represent structural demand characteristics — the volume
an SKU-account pair would move without any promotional activity. Applying them
to `baseline_volume` ensures the signals are cleanly measurable in non-promoted
periods and are not diluted or inflated by independent promotional mix variation.
If signals were applied to total volume after the promo draw, a brand on
promotion in one year but not the other would show a spurious trend that
conflates promo mix with structural performance — exactly the kind of
confounding that RGM analysis exists to separate.

**Alternatives considered**
- Apply signals to total volume_units after promo: rejected — conflates
  promotional mix variation with structural trend signal
- Apply signals as post-hoc multipliers: rejected — same problem as above

**KSB mapping** K3, S22, K26
**Implementation** `generate_data.py` → `generate_fact_sales()` steps 7–8

---

### ADR-009 — avg_shelf_price_gbp only in fact_market (no manufacturer net price)

**Context**
Schema design for fact_market: should it include both RSP (retail shelf price)
and manufacturer net price?

**Decision**
Store only `avg_shelf_price_gbp` (RSP) in fact_market. manufacturer net price
belongs exclusively in `fact_sales.sku_net_price_gbp`.

**Rationale**
Consistent with Nielsen/Kantar panel data convention. Panel providers measure
value at the till — they observe consumer-facing RSP from scanner data. They
cannot observe manufacturer trade terms (net prices, retroactive rebates,
promotional funding) as these are commercial agreements invisible to the panel.
Including a manufacturer net price in fact_market would misrepresent how panel
data is structured and would create a false join path that real panel data
does not support. The schema dictionary (F-04) explicitly documents this
constraint for LLM grounding.

**Alternatives considered**
- Both prices in fact_market: rejected — manufacturer net price is not
  observable by panel providers; would be analytically misleading
- Implied margin calculated in fact_market: rejected — requires a cross-table
  join from fact_market to fact_sales and cannot be reliably derived at the
  brand × banner × week grain without SKU-level transaction data

**KSB mapping** K3, K8, S22
**Implementation**
- `generate_data.py` → `generate_fact_market()` — no manufacturer price column
- F-04 schema dictionary — "Implied retailer margin requires cross-table join"

---

### ADR-010 — Lognormal distribution for baseline_volume generation

**Context**
Choice of statistical distribution for generating baseline transaction volumes
in fact_sales.

**Decision**
Draw `baseline_volume` from a lognormal distribution
(`np.random.lognormal(mean=VOLUME_MU, sigma=VOLUME_SIGMA)`), scaled by a
channel-level multiplier.

**Rationale**
Real FMCG transaction volumes are right-skewed — most SKU-account-week
combinations record modest volumes with a long tail of high-volume events
(promotional peaks, seasonal spikes, large-format stores). The lognormal
distribution naturally captures this shape. A normal distribution would
produce unrealistic negative volume draws and a symmetric shape inconsistent
with real scanner data. A uniform distribution would produce a flat density
inconsistent with the concentration of volume around typical trading levels.

**Alternatives considered**
- Normal distribution: rejected — negative values possible; symmetric shape
  unrealistic for volume data
- Uniform distribution: rejected — flat density; no realistic concentration
  around typical trading levels
- Poisson distribution: considered — appropriate for count data but assumes
  mean = variance which is too restrictive for weekly volume aggregates

**KSB mapping** K3, S11, K26
**Implementation** `generate_data.py` → `generate_fact_sales()` step 6

---

## Quality Issue Injection Decisions

---

### ADR-011 — NULL_MECHANIC_RATE set to 22% (not original spec of 30%)

**Context**
Original quality issue specification set NULL promotion_mechanic rate at ~30%
of is_promoted=True rows. Revised to 22% during inject_quality_issues.py build.

**Decision**
Use `NULL_MECHANIC_RATE = 0.22` (~22% of promoted rows).

**Rationale**
30% NULL rate would mean nearly one third of all promoted transactions have
no mechanic recorded — high enough to cause an analyst to question whether
the is_promoted flag itself was reliable. 22% is analytically significant
(substantial enough to matter in mechanic-level ROI analysis) while remaining
plausible as a POS/TPM system handshake failure rate. The rate is significant
enough to demonstrate the preprocessing decision (no imputation) matters, but
not so high as to undermine the credibility of the synthetic data.

**Alternatives considered**
- 30% as originally specified: rejected — too high; undermines confidence in
  the is_promoted flag itself
- 10%: rejected — not significant enough to motivate the no-imputation decision

**KSB mapping** K26, S22
**Implementation** `inject_quality_issues.py` → `NULL_MECHANIC_RATE = 0.22`

---

### ADR-012 — QI-08 gap pairs selected as specific banner × brand combinations

**Context**
Decision on which banner × brand pairs to inject with temporal gaps (QI-08).

**Decision**
Four specific pairs selected:
- ValuMart × NitroBoost
- PoundSave × CocoaEthos
- CityStop × ArtisanOats
- FreshDoor × BerryBliss

**Rationale**
Pairs chosen to span multiple channels (Grocery, Discounter, Convenience,
eCommerce) and multiple categories, so the gap pattern is not confounded with
any single channel or category. ValuMart × NitroBoost is analytically
interesting — both have structural performance signals (ValuMart decline,
NitroBoost growth) so the temporal gap creates a realistic missing-data
challenge for the NL2SQL system. The specific pairs are documented in the
schema dictionary so the LLM can be grounded on which combinations are affected.

**Alternatives considered**
- Random selection of gap pairs: rejected — random selection might cluster gaps
  in one channel or category, creating confounded patterns
- All pairs in one banner: rejected — would look like a banner data outage
  rather than realistic sporadic measurement gaps

**KSB mapping** K26, K8
**Implementation** `inject_quality_issues.py` → `GAP_TARGET_PAIRS`

---

## Preprocessing Decisions

---

### ADR-013 — IQR outer fence (3.0×) for volume outlier detection

**Context**
QI-04 injects volume outliers at 5–10× baseline into ~2% of fact_sales rows.
Decision: which IQR multiplier to use for the Tukey fence in `preprocess.py`?

**Decision**
Use Tukey outer fence: `upper_fence = Q3 + 3.0 × IQR` on the deviation metric
`(volume_units − baseline_volume − incremental_volume)`.

**Rationale**
fact_sales volume has a legitimately right-skewed distribution: lognormal
baseline + independent promotional incremental (20–50% uplift). The standard
inner fence (Q3 + 1.5 × IQR) would flag legitimate high-uplift promotional
weeks as outliers, inflating the is_volume_outlier rate well beyond the injected
~2%. The outer fence (3.0×) is the established convention for datasets with
legitimate extreme values in the upper tail. Critically, the deviation metric
normalises for promotional uplift — clean rows have deviation = 0 by
construction (volume_units = baseline + incremental exactly). Only injected
outlier rows (where volume_units was overwritten to 5–10× baseline while
baseline and incremental were left unchanged) produce deviations large enough
to exceed the outer fence.

**Alternatives considered**
- Standard inner fence (1.5×): rejected — over-flags legitimate 50% promotional
  uplift weeks; inflates flagging rate beyond injected ~2%
- Z-score threshold (e.g. >3σ): rejected — assumes normality; volume deviation
  distribution is lognormal and right-skewed, violating the normality assumption
- Absolute threshold (e.g. deviation > 500 units): rejected — not generalisable
  across SKUs with different baseline volume scales

**KSB mapping** K3, S11, S26
**Implementation** `preprocess.py` → `flag_fact_sales()`, `IQR_MULTIPLIER = 3.0`
**EDA evidence** `03_volume_deviation_hist.png`, `04_volume_outlier_scatter.png`

---

### ADR-014 — Median over mean for store_count imputation (dim_customer)

**Context**
~10% of non-eCommerce dim_customer rows have NULL store_count. Decision: impute
with channel mean or channel median?

**Decision**
Impute NULL store_count values with the channel median for non-eCommerce accounts.

**Rationale**
Store count distributions are right-skewed within each channel — large flagship
stores and major key accounts pull the mean upward. The median is more
representative of the typical account in each channel and is more robust to
extreme values. For example, in the Grocery channel, a small regional co-op
(5 stores) and a major supermarket chain (500 stores) would produce a mean
that over-estimates most accounts. The median correctly represents the central
tendency for the majority of accounts. eCommerce rows are left as NULL by
design — no store concept applies.

**Alternatives considered**
- Mean imputation: rejected — right-skewed distribution makes the mean
  unrepresentative of the typical account; large flagship stores inflate it
- Mode imputation: rejected — store count is a continuous integer variable;
  mode is not meaningful
- KNN imputation: rejected — over-engineered for a dimension table with a
  well-defined, stable channel structure; median is sufficient and transparent

**KSB mapping** K3, S11, S26, S22
**Implementation** `preprocess.py` → `impute_dim_customer()`
**EDA evidence** `02_data_quality_overview.png`

---

### ADR-015 — NULL territory imputed as Unknown-{Channel} (not generic Unknown)

**Context**
~15% of dim_customer rows have NULL territory, concentrated in Cornerstone
and HospitalityPlus independent banners.

**Decision**
Impute NULL territory as `"Unknown-{Channel}"` (e.g. `"Unknown-Independent"`,
`"Unknown-Foodservice"`), not a single `"Unknown"` label.

**Rationale**
Territory NULLs are structurally linked to channel type — Cornerstone and
HospitalityPlus independents do not assign territory codes in the CRM because
their account structure is not territory-based. Collapsing all NULLs into a
single `"Unknown"` label would conflate two distinct channel-level gaps into one
value, making it impossible to distinguish Independent accounts without
territory from Foodservice accounts without territory in any GROUP BY analysis.
Channel-suffixed imputation preserves the analytical distinction at zero cost.

**Alternatives considered**
- Single "Unknown" label: rejected — conflates structurally different NULL
  causes; loses channel-level analytical distinction
- Leave as NULL: rejected — NULLs in territory would cause GROUP BY exclusions
  in queries that don't explicitly handle them
- Territory assignment by lookup: rejected — no territory mapping exists for
  these account types; any assignment would be fabricated

**KSB mapping** K3, S22, S26
**Implementation** `preprocess.py` → `impute_dim_customer()`

---

### ADR-016 — No imputation for NULL promotion_mechanic (QI-05)

**Context**
22% of is_promoted=True rows have NULL promotion_mechanic. Decision: impute
(e.g. with mode) or leave sparse?

**Decision**
Leave NULL. Document in schema dictionary and eda_report.md. Do not impute.

**Rationale**
NULL promotion_mechanic does NOT mean non-promotional. The promotion event
occurred — is_promoted=True is reliable — but the mechanic type was not
transmitted from the POS/TPM system. Imputing with the mode mechanic
(e.g. "Price Reduction") would systematically misattribute promoted volume
to the most common mechanic, distorting any mechanic-level ROI or contribution
analysis. The missing value is not missing at random — it is structurally
linked to specific POS system handshake failures. The correct handling is to
filter on `is_promoted = True` for promotional volume analysis, not on
`promotion_mechanic IS NOT NULL`. This constraint is explicitly documented in
the F-04 schema dictionary for LLM grounding.

**Alternatives considered**
- Mode imputation: rejected — systematically misattributes volume to the most
  common mechanic; distorts mechanic ROI analysis
- "Unknown" mechanic category: rejected — creates a spurious mechanic value that
  would appear in all mechanic GROUP BY outputs as the largest single category
- Multiple imputation: rejected — over-engineered; the missing mechanism is
  structural, not random

**KSB mapping** K3, S11, S22, S26
**Implementation** `preprocess.py` → `flag_fact_sales()` (documented, not imputed)
**EDA evidence** `05_null_mechanic.png`

---

### ADR-017 — No interpolation for temporal gaps in fact_market (QI-08)

**Context**
QI-08 introduces 3–4 week temporal gaps for 4 banner × brand pairs in
fact_market. Decision: interpolate missing weeks or leave sparse?

**Decision**
Leave sparse. No interpolation. Document in schema dictionary and eda_report.md.

**Rationale**
A missing row in fact_market represents an absent panel measurement — the
scanner data for that banner × brand × week was simply not captured.
Interpolating would fabricate brand volume, category volume, and RSP data points
that the panel never measured, creating false confidence in data coverage.
This is categorically different from a structural zero (a brand genuinely not
selling in a week) — the measurement is absent, not the sales. The F-04 schema
dictionary explicitly documents: "a missing row ≠ zero sales; it means the
panel measurement is absent." All time-series aggregations must use
`COUNT(DISTINCT week_date)` rather than assuming 104 weeks.

**Alternatives considered**
- Linear interpolation: rejected — fabricates measurements that never existed;
  misrepresents data provenance
- Forward-fill: rejected — same problem; propagates last known value as if
  it were a genuine measurement
- Zero-fill: rejected — implies zero sales when sales may have been normal;
  understates brand performance in affected weeks

**KSB mapping** K3, S22, K8
**Implementation** `preprocess.py` → `audit_temporal_gaps()` (documents, does not fill)
**EDA evidence** `06_temporal_gap_heatmap.png`

---

### ADR-018 — Flag-and-retain strategy for QI-03, QI-06, QI-07 (not remove or impute)

**Context**
Three quality issues produce provably wrong values: zero sku_net_price_gbp
(QI-03), zero avg_shelf_price_gbp (QI-06), brand_vol > cat_vol (QI-07).
Decision: remove affected rows, impute, or flag and retain?

**Decision**
Flag all three with boolean columns (`is_zero_price`, `is_zero_shelf_price`,
`is_vol_violation`) and retain rows in the processed layer. Exclude flagged
rows from specific KPI calculations via WHERE clause in downstream queries.

**Rationale**
Rows with corrupted values still carry valid data in other columns. A zero-price
row in fact_sales still has valid volume data — removing it would understate
total units shipped. Imputation is not possible without ground truth: a zero
net price could represent any promotional depth; we cannot recover the true
value from available data. Flag-and-retain preserves analytical optionality —
volume-based KPIs can include these rows; revenue-based KPIs exclude them.
For the NL2SQL use case specifically, a flagged row the LLM can reason about
and selectively exclude is more valuable than a silently imputed row the LLM
cannot distinguish from clean data.

**Alternatives considered**
- Row removal: rejected — destroys valid volume data on rows with only a price
  corruption; understates units
- Imputation: rejected — ground truth is unrecoverable; any imputed value would
  be fabricated (zero price could be any promotional depth)
- No flagging (leave corrupted values): rejected — downstream KPIs would be
  silently wrong; LLM would receive misleading revenue figures

**KSB mapping** K3, S22, S26, K8
**Implementation**
- `preprocess.py` → `flag_fact_sales()` (QI-03, QI-04)
- `preprocess.py` → `flag_and_derive_fact_market()` (QI-06, QI-07)

---

### ADR-019 — Normalisation via inverted dictionary map (not fuzzy matching) for QI-01/02

**Context**
QI-01/02 inject inconsistent casing and abbreviations into `pack_type` and
`variant`. Decision: how to normalise back to canonical form in preprocess.py?

**Decision**
Build inverted correction maps (`PACK_TYPE_CORRECTIONS`, `VARIANT_CORRECTIONS`)
from the known corruption dictionaries in inject_quality_issues.py.
Apply via vectorised `.map(lambda v: dict.get(v, v))`.

**Rationale**
The corruption patterns are deterministic and enumerable — inject_quality_issues.py
defines exactly which corrupted forms are introduced. An inverted lookup is
100% precise, computationally trivial on 552 rows, and fully transparent: every
mapping is explicit and auditable. Fuzzy string matching (e.g. Levenshtein
distance, RapidFuzz) would introduce probabilistic corrections — acceptable for
genuinely unknown corruption patterns but unnecessary and less defensible when
the corruption catalogue is known exactly.

**Alternatives considered**
- Fuzzy string matching (RapidFuzz, difflib): rejected — probabilistic and
  opaque when exact correction catalogue is known; risk of incorrect matches
  on short abbreviations (e.g. "br" could match "Bar" or "Bag")
- Manual regex patterns: rejected — more brittle than a dictionary; harder
  to maintain as corruption catalogue grows
- Lowercasing + title-casing: rejected — doesn't handle abbreviations
  (BTL → Bottle) or multi-word forms (Sachet Pack)

**KSB mapping** K3, S22, S26
**Implementation**
- `preprocess.py` → `PACK_TYPE_CORRECTIONS`, `VARIANT_CORRECTIONS`, `normalise_dim_product()`
**EDA evidence** `01_casing_cardinality.png`

---

## EDA Visualisation Decisions

---

### ADR-020 — Fence-first approach for outlier scatter sampling

**Context**
Initial `plot_volume_outlier_scatter()` used a proxy threshold
(`volume_units > baseline * 3`) to pre-split outlier and normal rows, then
applied the IQR fence. This caused ~46K outlier rows to be included while
normal rows were capped at 30K — red dots outnumbered blue dots, making
outliers appear ~60% of the chart rather than their true ~2%.

**Decision**
Compute IQR fence on full dataset first. Apply flag to all rows. Then sample
each group independently: 2,000 outlier rows + 30,000 normal rows.

**Rationale**
The fence computation is the single source of truth — it should be computed
once and used consistently, matching preprocess.py exactly. The proxy threshold
(`> baseline * 3`) was a different criterion that happened to overlap with the
fence criterion for most injected outliers but was not identical. Controlled
group sampling ensures the visual ratio of red to blue dots reflects the true
~2% injection rate, making the plot analytically honest. The caption reports
`n_total_outliers` from the full dataset so the assessor sees the real figure
even though the scatter shows a sampled subset.

**Alternatives considered**
- All outliers + 30K normals: rejected — original bug; outliers outnumber
  normals visually; misleading representation of ~2% rate
- Pure random sample: rejected — at 2% injection rate, a 30K random sample
  would contain only ~600 outlier points, making the cluster nearly invisible

**KSB mapping** S9, S22
**Implementation** `eda_viz.py` → `plot_volume_outlier_scatter()`
**EDA evidence** `04_volume_outlier_scatter.png`

---

### ADR-021 — Weekly volume trends over market share box plot (plot 07)

**Context**
Original plot 07 was a box plot of `market_share_volume_pct` by sub-category.
All medians clustered between 20–25% with no meaningful differentiation.

**Decision**
Replace with a three-panel line chart of weekly brand_volume_units showing
the four embedded performance signals: NitroBoost growth (Panel A), Porridge &
Oats seasonal dip (Panel B), ValuMart decline (Panel C), with CocoaEthos as
a stable reference baseline in Panel A.

**Rationale**
The market share clustering was caused by a structural limitation in the
synthetic data: brand shares were drawn independently from `uniform(0.05, 0.40)`
without competitive sum-to-one constraints, producing identical median shares
(~22.5% = mean of the uniform) across all sub-categories. This is a known
synthetic data characteristic acknowledged in the EDA report. The performance
signals (NitroBoost, ValuMart, seasonal dips), by contrast, are genuinely and
distinctly embedded in baseline_volume and produce clearly visible trend breaks.
The weekly volume plot directly evidences the structural data design and
validates that the signals survived the quality injection pipeline intact.

**Alternatives considered**
- Fixing generate_data.py to use Dirichlet draws: rejected — Sprint 1 scope
  expansion with FK and validation knock-on effects; out of scope
- Keeping the market share plot with a disclaimer: rejected — a plot that shows
  nothing analytically interesting is weaker evidence than a replacement that
  shows genuine signals
- Market share filtered to sub-categories with highest variance: rejected —
  cosmetic fix that doesn't address the root cause

**KSB mapping** S9, S22, K26
**Implementation** `eda_viz.py` → `plot_weekly_volume_trends()`
**EDA evidence** `07_weekly_volume_trends.png`

---

### ADR-022 — avg_shelf_price_gbp used for tier analysis; price_index excluded (plot 08)

**Context**
Original plot 08 showed `price_index` by price tier. All three tiers showed
identical distributions (~92–109 range) with no tier stratification.

**Decision**
Replace `price_index` on y-axis with `avg_shelf_price_gbp`. Acknowledge
price_index circular denominator as a known synthetic data limitation in the
EDA report and plot subtitle.

**Rationale**
`total_category_value_gbp` was derived in generate_data.py as
`brand_volume_units × avg_shelf_price_gbp × cat_price_mult (0.92–1.08)`.
This makes the category average RSP (the price_index denominator)
approximately equal to the brand's own RSP for every brand, collapsing
price_index to `100 / uniform(0.92, 1.08) ≈ 92–108` regardless of tier.
`avg_shelf_price_gbp` inherits genuine tier stratification from list_price_gbp
× RETAILER_MARKUP, which was drawn from tier × category-specific PRICE_RANGES
in generate_data.py. Premium RSP > Mainstream RSP > Value RSP is genuine and
visually clear in the violin plot.

**Alternatives considered**
- Fix total_category_value_gbp in generate_data.py to use multi-brand weighted
  average RSP: considered — correct long-term fix, deferred to post-Sprint 1
- Keep price_index plot with disclaimer: rejected — a flat violin adds nothing;
  avg_shelf_price_gbp is analytically correct and more defensible

**KSB mapping** S9, S22, K3
**Implementation** `eda_viz.py` → `plot_price_index_by_tier()`
**EDA evidence** `08_price_index_by_tier.png`

---

### ADR-023 — QI-04 volume outlier detection: IQR on raw volume_units (primary) + invariant cross-validation (secondary)

**Context**
The initial implementation of QI-04 outlier detection in `flag_fact_sales()`
computed a deviation series — `volume_units − (baseline_volume + incremental_volume)`
— and applied the Tukey outer fence to that residual. This is logically sound
but structurally circular: the deviation is derived from the same invariant that
inject_quality_issues.py violated when creating the outliers. An assessor could
reasonably challenge this as a tautological detection — identifying rows by
checking the property that was deliberately broken, rather than by statistical
analysis of the observable data.

**Decision**
Apply the Tukey outer fence (3.0× IQR) directly to the raw `volume_units`
distribution as the primary detection method. Retain the invariant check
(`volume_units − (baseline_volume + incremental_volume) > 1.0`) as a secondary
cross-validation only — not as the detection criterion.

**Rationale**
Univariate IQR on `volume_units` is the technique an analyst would apply on
real FMCG data, where decomposed `baseline_volume` and `incremental_volume`
columns do not exist. The method is fully independent of the injection
mechanism and produces genuine statistical evidence: outlier rows lie beyond
the outer fence of the observable volume distribution. The secondary invariant
check then confirms that the statistically flagged rows are also logically
inconsistent — full agreement between both methods (expect n_IQR ∩ n_invariant
= n_outliers) validates the detection is not an artefact of distributional
skew. This two-method framing is defensible under assessor probing and
constitutes stronger KSB evidence for S22 (exploratory analysis technique)
and S9 (statistical technique selection) than the original single-method
invariant-based detection.

**Alternatives considered**
- IQR on deviation residual only (original): rejected — structurally circular;
  the deviation is derived from the injected invariant, making it an identity
  check dressed as statistical analysis
- Invariant check only (no IQR): rejected — not a statistical technique; cannot
  be applied to real data without access to decomposed columns; not defensible
  as EDA
- Z-score on volume_units: considered — appropriate for normally distributed
  data but volume_units is lognormal + right-skewed (promotional incremental);
  IQR is the correct non-parametric alternative for skewed distributions

**KSB mapping** S22, S9, K3, S26
**Implementation**
- `preprocess.py` → `flag_fact_sales()` (primary IQR block + secondary
  invariant block)
- `preprocess.py` → `generate_eda_report()` (QI-04 section documents both
  methods with live computed stats)
**EDA evidence** `eda_report.md` §3.2 | `04_volume_outlier_scatter.png`

---

## Pending Decisions (Sprint 2 onwards)

The following will be added as ADRs once decisions are made in Sprint 2:

- ADR-024 — Gemini 2.5 Flash vs Gemini 1.5 Flash model selection (F-06)
- ADR-025 — RAG schema injection strategy: full schema vs chunked retrieval (F-07)
- ADR-026 — Self-correction retry loop: 2 retries vs unlimited (F-09)
- ADR-027 — Streamlit session state management approach (Sprint 4)
- ADR-028 — JSONL logging schema design (Sprint 4)
- ADR-029 — Hypothesis test selection for Sprint 5 evaluation

---

*End of decision log. Maintained incrementally — one ADR per decision, at point of decision.*
