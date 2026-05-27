**Project Insight: Agentic Conversational BI — LLM-Driven Ad-Hoc Data Exploration**  
Sprint 1 reference document — last updated: 14 January 2026

---

## 1. Architecture Overview

### Four-table synthetic FMCG dataset

| Table | Type | Rows (validated) | File |
|---|---|---|---|
| dim_product | Dimension | 552 raw / 497 active | data/raw/dim_product.parquet |
| dim_customer | Dimension | 240 | data/raw/dim_customer.parquet |
| fact_sales | Fact (transactions) | ~2.3M | data/raw/fact_sales.parquet |
| fact_market | Fact (market measurements) | ~44K | data/raw/fact_market.parquet |

### Three-layer data architecture

```
scripts/generate_data.py         →  data/raw/               (clean generated — never modified)
scripts/inject_quality_issues.py →  data/raw/qi-injected/   (QI-injected — EDA viz reads here)
scripts/preprocess.py            →  data/processed/         (clean, flagged, derived measures)
                                 →  data/eda_report.md      (EDA profiling + handling decisions)                        
scripts/eda_viz.py               →  data/eda_plots/         (EDA plots — reads qi-injected)
```

- `data/raw/` — immutable. Generated once by `generate_data.py`, never overwritten. The clean baseline.
- `data/raw/qi-injected/` — quality-issue-injected layer. Derived from raw, never modified after injection.
  `eda_viz.py` reads from here so visualisations always reflect the dirty state regardless of pipeline order.
- `data/processed/` — the operational analytics layer. DuckDB queries only this layer. Produced by preprocess.py 
    from qi-injected/. Also produces data/eda_report.md — EDA findings and all QI handling decisions. 
    Application has no knowledge of upstream layers.
- `data/eda_plots/` — PNG outputs from `eda_viz.py`. Cited in the AM1 project report.

### Generation order (strict — respect FK dependencies)

```
1. dim_product    → write to data/raw/
2. dim_customer   → write to data/raw/
3. fact_sales     → reads dim_product + dim_customer PKs
4. fact_market    → reads dim_product brands/subcategories + dim_customer banners
```

### Seeding (ALL scripts)

```python
import numpy as np
import random
from faker import Faker

np.random.seed(42)
random.seed(42)
fake = Faker('en_GB')
Faker.seed(42)
```

---

## 2. dim_product

### Schema

| Column | Type | Notes |
|---|---|---|
| product_id | VARCHAR PK | e.g. SKU-0001 |
| sku_name | VARCHAR | Faker-generated: "Brand Variant PackSize PackType" |
| brand | VARCHAR | From subcat_to_brand mapping |
| sub_brand | VARCHAR | Optional sub-line (can be same as brand for simple cases) |
| category | VARCHAR | 6 categories |
| sub_category | VARCHAR | 22 subcategories |
| price_tier | VARCHAR | Premium / Mainstream / Value — brand-level attribute |
| pack_size | FLOAT | Numeric quantity |
| pack_size_uom | VARCHAR | ml, g, units |
| pack_type | VARCHAR | Category-appropriate (Pot, Tub, Can, Bag, Box etc.) |
| variant | VARCHAR | Flavour/recipe/range descriptor |
| list_price_gbp | FLOAT | Within tier-category range |
| cost_price_gbp | FLOAT | Generated as fraction of list price |
| launch_date | VARCHAR | **STRING in raw** — deliberate quality issue |
| is_active | VARCHAR | **"Y"/"N" string in raw** — deliberate quality issue |

### Category hierarchy

```python
subcategories = {
    "Dairy":         ["Milk & Cream", "Yogurts", "Cheese", "Butter & Spreads"],
    "Cereals":       ["Ready-to-Eat (RTE)", "Porridge & Oats", "Granola & Muesli"],
    "Beverages":     ["Soft Drinks", "Fruit Juices", "Tea & Coffee", "Functional/Energy"],
    "Snacks":        ["Crisps & Popcorn", "Savoury Biscuits", "Nut & Seed Mixes"],
    "Confectionery": ["Chocolate Bars", "Bags & Boxes", "Sugar Sweets", "Mints & Gum"],
    "Frozen Food":   ["Ice Cream", "Ready Meals", "Frozen Veg", "Pizza & Snacks"]
}
```

### Brand-subcategory mapping

```python
subcat_to_brand = {
    # DAIRY
    "Milk & Cream":       ["LactoPure", "Alpine Creamery"],
    "Yogurts":            ["BioBloom", "Cultured Co."],
    "Cheese":             ["SkyrNorth", "Velvet Dairy"],
    "Butter & Spreads":   ["MorningMist", "FarmFresh"],
    # CEREALS
    "Ready-to-Eat (RTE)": ["NutriFlake", "GoldenClusters"],
    "Porridge & Oats":    ["ArtisanOats", "MorningMilled"],
    "Granola & Muesli":   ["GrainGlow", "SeededHearth", "ToastMaster"],
    # BEVERAGES
    "Soft Drinks":        ["HydraVibe", "ElectroFlow"],
    "Fruit Juices":       ["PurePulse", "GlowWater"],
    "Tea & Coffee":       ["BrewCraft", "LeafRitual"],
    "Functional/Energy":  ["NitroBoost", "Vitaline"],
    # SNACKS
    "Crisps & Popcorn":   ["CrispCrave", "KernelPop"],
    "Savoury Biscuits":   ["Salt & Stone", "BoldBites"],
    "Nut & Seed Mixes":   ["BoldBites", "RootCrunch", "UmamiWave"],
    # CONFECTIONERY
    "Chocolate Bars":     ["CocoaEthos", "SweetSync"],
    "Bags & Boxes":       ["CocoaEthos", "ToffeeTide"],
    "Sugar Sweets":       ["FruitFuse", "BerryBliss"],
    "Mints & Gum":        ["MintMarvel", "GlazeGlory"],
    # FROZEN FOOD
    "Ice Cream":          ["BerryBliss", "Velvet Dairy"],
    "Ready Meals":        ["TableCraft", "ArcticBite"],
    "Frozen Veg":         ["CoolHarvest", "PolarPantry"],
    "Pizza & Snacks":     ["PizzaFrost", "FrostPeak"]
}
```

Cross-subcategory brands (deliberate — enables cross-category queries):
- **CocoaEthos**: Chocolate Bars + Bags & Boxes
- **BerryBliss**: Sugar Sweets + Ice Cream
- **Velvet Dairy**: Cheese + Ice Cream
- **BoldBites**: Savoury Biscuits + Nut & Seed Mixes

### Price tiers

```python
premium_brands = [
    "LactoPure", "BioBloom", "SkyrNorth", "ArtisanOats",
    "GrainGlow", "SeededHearth", "PurePulse", "BrewCraft",
    "NitroBoost", "Salt & Stone", "RootCrunch", "CocoaEthos",
    "BerryBliss"
]

mainstream_brands = [
    "Alpine Creamery", "Cultured Co.", "Velvet Dairy", "MorningMist",
    "MorningMilled", "ToastMaster", "HydraVibe", "GlowWater",
    "LeafRitual", "Vitaline", "CrispCrave", "BoldBites",
    "UmamiWave", "SweetSync", "MintMarvel", "TableCraft",
    "PizzaFrost", "FrostPeak"
]

# Value brands (all remaining):
# FarmFresh, NutriFlake, GoldenClusters, ElectroFlow, KernelPop,
# ToffeeTide, FruitFuse, GlazeGlory, ArcticBite, CoolHarvest, PolarPantry
```

### Price ranges by tier and category

```python
# list_price_gbp ranges: (min, max)
price_ranges = {
    ("Premium",    "Dairy"):         (2.50, 5.50),
    ("Premium",    "Cereals"):       (2.80, 5.00),
    ("Premium",    "Beverages"):     (1.80, 4.20),
    ("Premium",    "Snacks"):        (1.50, 3.50),
    ("Premium",    "Confectionery"): (1.80, 4.50),
    ("Premium",    "Frozen Food"):   (3.00, 6.50),
    ("Mainstream", "Dairy"):         (1.60, 3.50),
    ("Mainstream", "Cereals"):       (1.40, 3.50),
    ("Mainstream", "Beverages"):     (1.20, 3.20),
    ("Mainstream", "Snacks"):        (0.80, 2.50),
    ("Mainstream", "Confectionery"): (1.00, 3.00),
    ("Mainstream", "Frozen Food"):   (2.00, 4.50),
    ("Value",      "Dairy"):         (0.60, 1.80),
    ("Value",      "Cereals"):       (0.80, 1.80),
    ("Value",      "Beverages"):     (0.50, 1.80),
    ("Value",      "Snacks"):        (0.45, 1.50),
    ("Value",      "Confectionery"): (0.50, 1.60),
    ("Value",      "Frozen Food"):   (1.00, 2.80),
}

# cost_price_gbp = list_price * cost_fraction (by tier)
cost_fraction_ranges = {
    "Premium":    (0.42, 0.58),  # stronger margins
    "Mainstream": (0.48, 0.62),
    "Value":      (0.52, 0.68),  # thinner margins
}
```

### SKU generation approach

**12 SKUs per brand-subcategory combination** via variant differentiation (not pack size proliferation).

Total: ~45 brand-subcategory combinations × 12 = 540 SKUs raw.
Active SKUs: ~480–500 (40–60 marked inactive via `is_active = "N"`).

```python
# Variant descriptors by category (Faker not used for variants —
# custom word lists are more reliable than Faker's random word generator)
variant_descriptors = {
    "Dairy":         ["Strawberry", "Vanilla", "Blueberry", "Mango", "Natural",
                      "Greek Style", "Low Fat", "Organic", "High Protein",
                      "Honey", "Cherry", "Peach"],
    "Cereals":       ["Original", "Honey & Nut", "Chocolate", "Berry",
                      "Apple & Cinnamon", "Raisin", "Golden", "Ancient Grain",
                      "Multigrain", "Whole Grain", "Coconut", "Maple"],
    "Beverages":     ["Original", "Sugar Free", "Diet", "Zero", "Raspberry",
                      "Lemon", "Orange", "Tropical", "Peach", "Cherry",
                      "Grapefruit", "Elderflower"],
    "Snacks":        ["Sea Salt", "Salt & Vinegar", "Cheese & Onion", "BBQ",
                      "Sour Cream", "Sweet Chilli", "Smoked Paprika",
                      "Lightly Salted", "Jalapeno", "Prawn Cocktail",
                      "Mature Cheddar", "Caramelised Onion"],
    "Confectionery": ["Milk Chocolate", "Dark Chocolate", "White Chocolate",
                      "Caramel", "Mint", "Orange", "Hazelnut", "Salted Caramel",
                      "Strawberry", "Raspberry", "Toffee", "Fudge"],
    "Frozen Food":   ["Original", "Spicy", "Tomato & Basil", "Creamy", "BBQ",
                      "Chargrilled", "Mediterranean", "Classic", "Deluxe",
                      "Country Style", "Farmhouse", "Signature"]
}
```

### Valid pack combinations by subcategory

```python
# Each tuple: (pack_size, pack_size_uom, pack_type)
# Kept intentionally tight — SKU differentiation comes from variants, not pack proliferation
valid_combinations = {
    "Milk & Cream":       [(500,"ml","Bottle"), (1000,"ml","Bottle"),
                           (1500,"ml","Bottle"), (1000,"ml","Carton"),
                           (200,"ml","Carton")],
    "Yogurts":            [(125,"g","Pot"), (150,"g","Pot"),
                           (500,"g","Tub"), (4,"units","Multipack"),
                           (6,"units","Multipack")],
    "Cheese":             [(200,"g","Block"), (400,"g","Block"),
                           (150,"g","Grated Bag"), (200,"g","Slices Pack"),
                           (6,"units","Multipack")],
    "Butter & Spreads":   [(250,"g","Block"), (500,"g","Block"),
                           (250,"g","Tub"), (500,"g","Tub"),
                           (10,"g","Portion Pack")],
    "Ready-to-Eat (RTE)": [(375,"g","Box"), (500,"g","Box"),
                           (750,"g","Box"), (1000,"g","Box"),
                           (6,"units","Multipack")],
    "Porridge & Oats":    [(500,"g","Box"), (1000,"g","Box"),
                           (8,"units","Sachet Pack"), (12,"units","Sachet Pack"),
                           (60,"g","Pot")],
    "Granola & Muesli":   [(400,"g","Bag"), (750,"g","Bag"),
                           (400,"g","Box"), (500,"g","Pouch"),
                           (6,"units","Multipack")],
    "Soft Drinks":        [(330,"ml","Can"), (500,"ml","PET Bottle"),
                           (1500,"ml","PET Bottle"), (250,"ml","Glass Bottle"),
                           (6,"units","Multipack")],
    "Fruit Juices":       [(250,"ml","Carton"), (1000,"ml","Carton"),
                           (500,"ml","Glass Bottle"), (1000,"ml","PET Bottle"),
                           (6,"units","Multipack")],
    "Tea & Coffee":       [(80,"units","Box"), (160,"units","Box"),
                           (200,"g","Jar"), (200,"g","Bag"),
                           (10,"units","Sachet Pack")],
    "Functional/Energy":  [(250,"ml","Can"), (500,"ml","Can"),
                           (500,"ml","PET Bottle"), (4,"units","Multipack"),
                           (12,"units","Multipack")],
    "Crisps & Popcorn":   [(40,"g","Bag"), (150,"g","Bag"),
                           (200,"g","Bag"), (6,"units","Multipack"),
                           (12,"units","Multipack")],
    "Savoury Biscuits":   [(150,"g","Box"), (200,"g","Box"),
                           (150,"g","Bag"), (6,"units","Multipack"),
                           (300,"g","Box")],
    "Nut & Seed Mixes":   [(30,"g","Bag"), (150,"g","Bag"),
                           (300,"g","Bag"), (4,"units","Multipack"),
                           (200,"g","Pouch")],
    "Chocolate Bars":     [(45,"g","Bar"), (100,"g","Bar"),
                           (4,"units","Multipack"), (8,"units","Multipack"),
                           (200,"g","Gift Box")],
    "Bags & Boxes":       [(150,"g","Bag"), (200,"g","Bag"),
                           (400,"g","Box"), (175,"g","Tin"),
                           (6,"units","Multipack")],
    "Sugar Sweets":       [(100,"g","Bag"), (200,"g","Bag"),
                           (400,"g","Bag"), (4,"units","Multipack"),
                           (150,"g","Pouch")],
    "Mints & Gum":        [(35,"g","Tin"), (50,"g","Tin"),
                           (10,"units","Blister Pack"), (4,"units","Multipack"),
                           (200,"g","Bag")],
    "Ice Cream":          [(500,"ml","Tub"), (1000,"ml","Tub"),
                           (4,"units","Bar Multipack"), (6,"units","Bar Multipack"),
                           (500,"g","Bag")],
    "Ready Meals":        [(300,"g","Tray"), (400,"g","Tray"),
                           (500,"g","Tray"), (450,"g","Box"),
                           (2,"units","Multipack")],
    "Frozen Veg":         [(450,"g","Bag"), (750,"g","Bag"),
                           (1000,"g","Bag"), (300,"g","Steam Bag"),
                           (4,"units","Multipack")],
    "Pizza & Snacks":     [(300,"g","Box"), (500,"g","Box"),
                           (2,"units","Multipack"), (400,"g","Bag"),
                           (6,"units","Multipack")]
}
```

### SKU name generation function

```python
def generate_skus_for_brand_subcat(brand, subcategory, category, n=12):
    combos   = valid_combinations[subcategory][:]
    variants = variant_descriptors[category][:]

    random.shuffle(combos)
    random.shuffle(variants)

    skus = []
    used = set()
    combo_cycle   = 0
    variant_cycle = 0

    while len(skus) < n:
        combo   = combos[combo_cycle % len(combos)]
        variant = variants[variant_cycle % len(variants)]
        pack_size, uom, pack_type = combo

        key = (variant, pack_size, uom, pack_type)
        if key not in used:
            used.add(key)
            pack_display = (f"{pack_size}pk" if uom == "units"
                            else f"{pack_size}{uom}")
            sku_name = f"{brand} {variant} {pack_display} {pack_type}"
            skus.append({
                "sku_name":      sku_name,
                "brand":         brand,
                "sub_category":  subcategory,
                "pack_size":     pack_size,
                "pack_size_uom": uom,
                "pack_type":     pack_type,
                "variant":       variant
            })

        combo_cycle   += 1
        variant_cycle += 1

    return skus
```

### is_active logic (purposeful, not random)

```python
# Applied after launch_date generation
# Inactive SKUs cluster around older launches and value brands
def assign_is_active(launch_date_str, brand, value_brands):
    launch_year = int(launch_date_str[:4])
    rand = random.random()
    if launch_year < 2020 and rand < 0.35:
        return "N"   # older SKUs more likely discontinued
    if brand in value_brands and rand < 0.12:
        return "N"   # value brand rationalisation
    return "Y"
```

### launch_date distribution

```python
# Distributed across 2018–2025 so some SKUs predate the data window
# Stored as string "YYYY-MM-DD" — deliberate quality issue
# Parsed to date type in preprocess.py
import random
from datetime import date, timedelta

def random_launch_date():
    start = date(2018, 1, 1)
    end   = date(2025, 12, 31)
    delta = (end - start).days
    return str(start + timedelta(days=random.randint(0, delta)))
```

---

## 3. dim_customer

### Schema

| Column | Type | Notes |
|---|---|---|
| customer_id | VARCHAR PK | e.g. CUST-001 |
| customer_name | VARCHAR | Faker-generated account name |
| channel | VARCHAR | 5 channels |
| banner | VARCHAR | 15 banners |
| region | VARCHAR | North, Midlands, South, Scotland, Wales — NULL for eCommerce |
| territory | VARCHAR | Sub-regional — NULL for eCommerce + ~15% Convenience/Foodservice |
| account_type | VARCHAR | Key Account, Regional Multiple, Independent |
| store_count | INTEGER | Channel-realistic ranges — ~10% NULL (quality issue) |

### Channel-banner-account structure

```python
customer_hierarchy = {
    "Grocery": {
        "Ashton Retail":          28,   # Key Account
        "Meridian Supermarkets":  22,   # Key Account
        "Hartfield's":            18,   # Key Account
        "ValuMart":               20,   # Key Account
    },
    "Discounter": {
        "PoundSave":              15,   # Key Account
        "Dealz Direct":           12,   # Key Account
    },
    "Convenience": {
        "CityStop":               30,   # Regional Multiple
        "Cornerstone":            20,   # Independent
        "QuickShop Express":      15,   # Regional Multiple
    },
    "eCommerce": {
        "Ashton Online":           8,   # Key Account
        "FreshDoor":               6,   # Key Account
        "PantryBox":               5,   # Key Account
    },
    "Foodservice": {
        "CaterPro":               18,   # Regional Multiple
        "Campus & Co":            12,   # Regional Multiple
        "HospitalityPlus":        11,   # Independent
    }
}
# Total: 240 accounts across 5 channels, 15 banners
```

### store_count ranges by channel

```python
store_count_ranges = {
    "Grocery":     (150, 600),
    "Discounter":  (80,  300),
    "Convenience": (10,  80),
    "eCommerce":   (1,   1),    # no physical stores
    "Foodservice": (1,   5),    # depot count
}
```

### territory and region logic

```python
regions = ["North", "Midlands", "South", "Scotland", "Wales"]

# eCommerce: region = NULL, territory = NULL (structural — operates nationally)
# Convenience Independents + smaller Foodservice: ~15% NULL territory (quality issue)
# All others: region assigned, territory = sub-region within region
```

---

## 4. fact_sales

### Schema

| Column | Type | Notes |
|---|---|---|
| transaction_id | BIGINT PK | Surrogate key |
| week_date | DATE | Monday of ISO week |
| year | INTEGER | 2024 or 2025 |
| quarter | INTEGER | 1–4 |
| month | INTEGER | 1–12 |
| week_number | INTEGER | ISO week number |
| product_id | VARCHAR FK | → dim_product |
| customer_id | VARCHAR FK | → dim_customer |
| volume_units | INTEGER | baseline_volume + incremental_volume |
| gross_revenue_gbp | FLOAT | Revenue before trade investment |
| trade_discount_gbp | FLOAT | Promotional + contractual discounts |
| net_revenue_gbp | FLOAT | gross - discount |
| sku_net_price_gbp | FLOAT | Manufacturer's net realised price per unit (post-discount). trade_discount per unit = list_price_gbp − sku_net_price_gbp. Source: fact_sales only — not visible to panel providers |
| is_promoted | BOOLEAN | Promotion flag |
| promotion_mechanic | VARCHAR | Price Reduction, BOGOF, Multi-buy, NULL |
| baseline_volume | INTEGER | Structural demand — lognormal base with performance signals applied. Zero promo contribution by definition |
| incremental_volume | INTEGER | Promo uplift only (20–50% of baseline for promoted rows). Zero for non-promoted rows |

### Time window

**1 Jan 2024 – 31 Dec 2025** (104 ISO weeks, 2 complete calendar years)

Rationale: enables full-year 2024 vs 2025 YoY comparisons, 4 complete quarters per year, 2 full seasonal cycles.

### Row count target

~2.3M rows: 497 active SKUs × 240 accounts × 104 weeks × 50% listing probability × 40% weekly fill rate within listed pairs.

### Channel-category listing rules

Three structural exclusions — not modelled as low probability, but as impossible combinations:

```python
CHANNEL_CATEGORY_UNLISTED = frozenset([
    ("Frozen Food", "Convenience"),   # no freezer logistics in small-format retail
    ("Frozen Food", "eCommerce"),     # consumer last-mile frozen not viable
    ("Snacks",      "eCommerce"),     # low value density, uneconomic per-unit delivery
])
```

Full matrix (✗ = structurally unlisted):

| Category | Grocery | Discounter | Convenience | eCommerce | Foodservice |
|---|---|---|---|---|---|
| Dairy | ✓ | ✓ | ✓ | ✓ | ✓ |
| Cereals | ✓ | ✓ | ✓ | ✓ | ✓ |
| Beverages | ✓ | ✓ | ✓ | ✓ | ✓ |
| Snacks | ✓ | ✓ | ✓ | ✗ | ✓ |
| Confectionery | ✓ | ✓ | ✓ | ✓ | ✓ |
| Frozen Food | ✓ | ✓ | ✗ | ✗ | ✓ |

Key rationale: Foodservice retains Frozen (commercial kitchens use frozen goods), Dairy (core catering ingredient — milk, cream, butter), and Confectionery (hotels, canteens, corporate catering). Dairy eCommerce retained — Ocado/FreshDoor-type operators handle chilled last-mile.

### Intentional performance signals

Built into `baseline_volume` generation — **NOT injected by inject_quality_issues.py, and NOT applied to total volume**. Signals are applied to baseline before the promotion draw, so structural trends are isolated from promo mix variation.

Generation order:
```
lognormal base volume (channel-scaled)
    → apply signal multipliers → baseline_volume
    → draw is_promoted independently (30% rate)
    → incremental_volume = 20–50% uplift for promoted rows only, 0 otherwise
    → volume_units = baseline_volume + incremental_volume
```

```python
# Signal 1 — NitroBoost YoY baseline growth
BRAND_YEAR_MULTIPLIER = {
    ("NitroBoost", 2024): 1.00,
    ("NitroBoost", 2025): 1.18,   # +18% — health/energy category trend
}

# Signal 2 — Porridge & Oats Q3 seasonal dip (ISO weeks 26–39, both years)
# Rationale: cold-weather breakfast staple; well-documented summer slump in UK grocery
SEASONAL_DIP_SUBCAT_1 = "Porridge & Oats"
SEASONAL_DIP_WEEKS_1  = frozenset(range(26, 40))   # ISO weeks 26–39
SEASONAL_DIP_FACTOR_1 = 0.65   # 35% baseline decline in Q3

# Signal 3 — Ice Cream Q4 seasonal dip (ISO weeks 40–52, both years)
# Rationale: summer impulse category; peaks Q2/Q3, drops sharply in winter
SEASONAL_DIP_SUBCAT_2 = "Ice Cream"
SEASONAL_DIP_WEEKS_2  = frozenset(range(40, 53))   # ISO weeks 40–52
SEASONAL_DIP_FACTOR_2 = 0.60   # 40% baseline decline in Q4

# Signal 4 — ValuMart 2025 linear baseline deterioration
# Rationale: structural market share loss independent of promotion activity
DETERIORATING_BANNER  = "ValuMart"
VALMART_DECLINE_START = 1.00   # week 1 multiplier
VALMART_DECLINE_END   = 0.82   # week 52 multiplier (linear interpolation)
```

The two seasonal signals are counter-cyclical by design — Porridge & Oats dips in summer while Ice Cream dips in winter. This enables the NL2SQL agent to surface genuinely contrasting seasonal patterns when queried.

**Verification:** Performance signals are confirmed via `baseline_volume` summary queries only. Checking `volume_units` would conflate structural trend with promo uplift variation.

### Quality issues (inject_quality_issues.py)

- ~3% of `sku_net_price_gbp` set to zero (system recording errors on promoted lines)
- ~2% of `volume_units` as outliers — 5–10× baseline (data entry / duplicates)
- `promotion_mechanic` NULL for ~22% of rows where `is_promoted = True`

---

## 5. fact_market

### Schema (RAW layer — no pre-calculated KPIs)

| Column | Type | Notes |
|---|---|---|
| measurement_id | BIGINT PK | Surrogate key |
| week_date | DATE | Aligns with fact_sales |
| year | INTEGER | 2024 or 2025 |
| quarter | INTEGER | 1–4 |
| month | INTEGER | 1–12 |
| week_number | INTEGER | ISO week |
| brand | VARCHAR | Aligns with dim_product.brand |
| sub_category | VARCHAR | Aligns with dim_product.sub_category |
| banner | VARCHAR | Aligns with dim_customer.banner |
| brand_volume_units | INTEGER | Units sold for this brand |
| brand_value_gbp | FLOAT | Value of those sales |
| total_category_volume_units | INTEGER | Total market units (all brands) |
| total_category_value_gbp | FLOAT | Total market value (all brands) |
| numeric_distribution_outlets | INTEGER | Outlets stocking the brand |
| total_outlets_in_banner | INTEGER | Total outlets (distribution denominator) |
| avg_shelf_price_gbp | FLOAT | Brand-level weekly average consumer shelf price (RSP). Derived as brand mean list price × channel RETAILER_MARKUP × weekly noise (±10%). This is the price Nielsen/Kantar record at the till — not an SKU-level price and not the manufacturer's net price |

### CRITICAL generation constraint

Generate `total_category_volume_units` FIRST as market size.
Derive `brand_volume_units` as a share of that.
**Never the reverse** — brand volume must always be ≤ category volume.

### Retailer markup (list price → avg_shelf_price_gbp)

```python
# Applied per row via banner → channel lookup.
# avg_shelf_price_gbp = brand_mean_list_price × RETAILER_MARKUP × noise(0.90, 1.10)
# Value columns use avg_shelf_price_gbp — consistent with Nielsen/Kantar which
# measure value at the till, not at manufacturer invoice.
RETAILER_MARKUP = {
    "Grocery":     1.30,   # standard grocery margin ~23% on RSP
    "Discounter":  1.20,   # EDLP model — lower branded margin (~17%)
    "Convenience": 1.40,   # impulse premium, small basket (~28%)
    "eCommerce":   1.25,   # competitive online pricing (~20%)
    "Foodservice": 1.35,   # catering margin on branded ingredients (~26%)
}
```

`manufacturer_net_price_gbp` is NOT stored in `fact_market` — panel providers have no
visibility of bilateral trade terms. The manufacturer's net price lives in
`fact_sales.sku_net_price_gbp`. Implied retailer margin is derivable by joining both tables:

```sql
(fm.avg_shelf_price_gbp - AVG(fs.sku_net_price_gbp)) / fm.avg_shelf_price_gbp
```

### Derived measures (computed in preprocess.py, NOT stored raw)

```python
# Computed and appended to data/processed/fact_market.parquet
df["market_share_volume_pct"]   = df.brand_volume_units / df.total_category_volume_units * 100
df["market_share_value_pct"]    = df.brand_value_gbp / df.total_category_value_gbp * 100
df["numeric_distribution_pct"]  = df.numeric_distribution_outlets / df.total_outlets_in_banner * 100
df["price_index"]               = (df.avg_shelf_price_gbp /
                                   (df.total_category_value_gbp / df.total_category_volume_units) * 100)
# weighted_distribution_pct requires store_count join from dim_customer
```

### Join pattern to fact_sales (MUST be documented in schema dictionary)

```sql
-- CORRECT: aggregate fact_sales to banner level FIRST, then join
SELECT
    fm.week_date, fm.banner, fm.brand,
    fm.market_share_volume_pct,
    agg.sellout_volume
FROM fact_market fm
JOIN (
    SELECT fs.week_date, dp.brand, dc.banner,
           SUM(fs.volume_units) AS sellout_volume
    FROM fact_sales fs
    JOIN dim_product  dp ON fs.product_id  = dp.product_id
    JOIN dim_customer dc ON fs.customer_id = dc.customer_id
    GROUP BY fs.week_date, dp.brand, dc.banner
) agg ON fm.week_date = agg.week_date
     AND fm.brand     = agg.brand
     AND fm.banner    = agg.banner

-- WRONG: direct join without aggregation is INVALID
-- fact_market has no FK to fact_sales customer_id

-- Implied retailer margin (requires cross-table join — richer NL2SQL query)
SELECT
    fm.brand, fm.banner, fm.week_date,
    fm.avg_shelf_price_gbp,
    agg.avg_net_price,
    (fm.avg_shelf_price_gbp - agg.avg_net_price) / fm.avg_shelf_price_gbp AS implied_margin
FROM fact_market fm
JOIN (
    SELECT dp.brand, dc.banner, fs.week_date,
           AVG(fs.sku_net_price_gbp) AS avg_net_price
    FROM fact_sales fs
    JOIN dim_product  dp ON fs.product_id  = dp.product_id
    JOIN dim_customer dc ON fs.customer_id = dc.customer_id
    GROUP BY dp.brand, dc.banner, fs.week_date
) agg ON fm.brand     = agg.brand
     AND fm.banner    = agg.banner
     AND fm.week_date = agg.week_date
```

### Quality issues (inject_quality_issues.py)

- ~5% of `avg_shelf_price_gbp` set to zero (system recording failures)
- ~1% of rows where `brand_volume_units` > `total_category_volume_units` (deliberately violating the pre-injection generation constraint — tests that preprocess.py detects and flags these)
- 3–4 week temporal gaps for select banner × brand combinations (left sparse in processed layer — not interpolated)

---

## 6. Key design decisions (for report narrative)

| Decision | Rationale | Alternative Considered |
|---|---|---|
| Synthetic data with injected quality issues | Real EDA decisions required; clean generated data trivialises preprocessing and undermines evidential value | Real client data — rejected: GDPR and data governance constraints |
| Two-layer architecture (raw / processed) | Reproducibility and data governance — raw always preserved; preprocessing is auditable and repeatable | Single layer — rejected: no audit trail of data quality decisions |
| `fact_market` at brand × sub_category × banner × week grain | Matches real Nielsen/Kantar panel data licence grain. SKU-level market data would imply retailer EPOS — a different source | SKU-banner grain — rejected: misrepresents the data source and measurement methodology |
| `fact_market` grain distinct from `fact_sales` grain | Architecturally correct — internal sell-out (SKU × account × week) and panel measurement (brand × banner × week) are different data products | Same grain — rejected: would require aggregating fact_sales before any market comparison anyway |
| Jan 2024 – Dec 2025 window (104 ISO weeks) | Two complete calendar years for clean YoY, quarterly, and two full seasonal cycles | Single year — rejected: no YoY comparison possible; shorter seasonal evidence |
| numpy + pandas (not SDV) | No source dataset to learn from; generation parameters define distributions directly — transparent and reproducible | SDV (Synthetic Data Vault) — rejected: requires a real dataset as input |
| Lognormal distribution for base volume | Always positive; right-skewed matching real FMCG velocity data; median ≈ 55 units at Convenience scale | Normal distribution — rejected: allows negatives, symmetric, unrealistic |
| Channel volume scaling as multiplier on lognormal base | Preserves consistent within-channel variance shape; only the level shifts. Grocery ×4.0, eCommerce ×3.0, Discounter ×2.0, Foodservice ×2.0, Convenience ×0.5 | Separate lognormal per channel — rejected: redundant parameterisation, harder to maintain consistently |
| Performance signals applied to `baseline_volume` before promotion draw | Isolates structural trend from promo mix distortion. NitroBoost growth and ValuMart decline are structural — promo mix varies independently and would otherwise dilute or inflate signals | Signals on total volume — rejected: independent promo draw would unpredictably mask or amplify trends |
| `incremental_volume` drawn independently (20–50% uplift, promoted rows only); non-promo rows carry zero incremental | Keeps baseline analytically clean as a pure structural demand signal | Back-calculating baseline as fraction of total — rejected: circular; contaminates baseline with noise |
| Two seasonal signals (Porridge & Oats Q3, Ice Cream Q4) — counter-cyclical by design | Different seasonal shapes enable richer NL2SQL queries: *"compare seasonal patterns across sub-categories"* or *"which categories are counter-cyclical?"* return genuinely contrasting results | Single seasonal signal — rejected: limits analytical surface of the prototype |
| `CHANNEL_CATEGORY_UNLISTED` final set: Frozen/Convenience, Frozen/eCommerce, Snacks/eCommerce | Frozen/Convenience: no freezer logistics in small-format. Frozen/eCommerce: consumer last-mile not viable. Snacks/eCommerce: low value density, uneconomic. Foodservice retains all three (commercial kitchens). Dairy eCommerce retained (Ocado/FreshDoor model) | Earlier set also excluded Dairy/eCommerce and Confectionery/Foodservice — reversed after real-world rationale review |
| `how="cross"` for all cross-joins; `_k` dummy column pattern removed | Native pandas cross-join is explicit, readable, and does not mutate source DataFrames. `_k` pattern required defensive `.copy()` calls and left junk columns | `_k` merge pattern — replaced as code quality improvement |
| `selling_price_gbp` renamed to `sku_net_price_gbp` in `fact_sales` | Unambiguous industry term — "net price" means post-discount manufacturer realised price in all FMCG commercial finance contexts. `selling_price` is ambiguous between shelf price and invoice price | `sku_sales_price` — rejected: ambiguous; could refer to consumer or manufacturer side |
| `avg_shelf_price_gbp` in `fact_market` — single price column (no `manufacturer_net_price_gbp`) | Panel providers have no visibility of bilateral trade terms. `manufacturer_net_price_gbp` in `fact_market` implied Nielsen knows manufacturer-retailer trade terms — factually wrong. RSP is the only price Nielsen/Kantar can measure. Retailer margin is derivable via cross-table join to `fact_sales.sku_net_price_gbp` | Storing both prices in `fact_market` — rejected: manufacturer net does not belong in panel measurement data |
| `avg_shelf_price_gbp` naming (not `consumer_shelf_price_gbp`) | Explicitly communicates it is a brand-level weekly average, not an individual SKU or individual consumer price. Prevents misinterpretation as a transactional price | `consumer_shelf_price_gbp` — rejected: implies per-consumer or per-SKU granularity |
| `snap_to_realistic_price()` NOT applied to `sku_net_price_gbp` or `fact_market` price columns | `sku_net_price_gbp` is manufacturer trade net — calculated as % discount off list, lands at arbitrary pence. Pence snapping applies only to consumer-facing list prices in `dim_product` | Apply pence endings to selling price — rejected: wrong data layer, wrong semantics; also prohibitively slow on 2M rows via scalar function |
| Retailer margin not modelled in `fact_sales` | Requires off-invoice rates and bill-back accruals — neither is modelled. Any computation would produce manufacturer discount, not retailer margin | Add retailer margin to `fact_sales` — deferred: requires separate trade terms table, out of scope |
| Faker (en_GB) for string fields | Realistic UK-sounding names improve demo readability; seeded for reproducibility | Generic IDs only — rejected: reduces demo authenticity |
| Variant-based SKU differentiation (12 per brand-subcat) | FMCG SKU proliferation comes from variants, not pack size combinations | Pack size proliferation — rejected: produces unrealistic range depth |
| `price_tier` at brand level | Tier is brand equity positioning, not a per-SKU price calculation | Per-SKU tier — rejected: same brand cannot straddle tiers |

---

## 7. Validation checks after each table

```python
import pandas as pd

# dim_product
df = pd.read_parquet('data/raw/dim_product.parquet')
print(df.shape)                                      # expect 552 rows
print(df.isnull().sum())                             # no nulls pre-injection
print(df['price_tier'].value_counts())
print(df['is_active'].value_counts())                # Y=497, N=55
print(df.groupby(['sub_category','brand']).size())   # expect 12 per combo

# dim_customer
df = pd.read_parquet('data/raw/dim_customer.parquet')
print(df.shape)                                      # expect 240 rows
print(df.groupby(['channel','banner']).size())

# fact_sales
df = pd.read_parquet('data/raw/fact_sales.parquet')
print(df.shape)                                      # expect ~2.3M rows
print(df['year'].value_counts())                     # ~50/50 split 2024/2025
print(df['is_promoted'].value_counts())              # ~30% promoted
# Signal verification on baseline_volume (not volume_units)
nb_ids = pd.read_parquet('data/raw/dim_product.parquet')
nb_ids = nb_ids[nb_ids['brand']=='NitroBoost']['product_id']
nb = df[df['product_id'].isin(nb_ids)].groupby('year')['baseline_volume'].sum()
print(nb[2025]/nb[2024])                             # expect ~1.18

# fact_market
df = pd.read_parquet('data/raw/fact_market.parquet')
print(df.shape)                                      # expect ~44K rows
# Pre-injection constraint: brand_volume ≤ category_volume
assert (df.brand_volume_units <= df.total_category_volume_units).all()
# Shelf price positive and above brand mean list (markup applied)
assert (df.avg_shelf_price_gbp > 0).all()
```

---