"""
generate_data.py
----------------
Synthetic FMCG dataset generator for Project Insight: Agentic Conversational BI — LLM-Driven Ad-Hoc Data Exploration.

Generation order to address FK dependencies:
    1. dim_product    → data/raw/dim_product.parquet
    2. dim_customer   → data/raw/dim_customer.parquet
    3. fact_sales     → data/raw/fact_sales.parquet
    4. fact_market    → data/raw/fact_market.parquet

inject_quality.py will be run separately to introduce quality issues, after data generation is validated.
"""

import os
import math
import random
from datetime import date, timedelta

import numpy as np
import pandas as pd
from faker import Faker

# ──────────────────────────────────────────────────────────────────────────────
# GLOBAL SEEDS
# ──────────────────────────────────────────────────────────────────────────────
SEED = 42
np.random.seed(SEED)
random.seed(SEED)
fake = Faker("en_GB")
Faker.seed(SEED)

# ──────────────────────────────────────────────────────────────────────────────
# OUTPUT PATHS
# ──────────────────────────────────────────────────────────────────────────────
RAW_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "raw")
os.makedirs(RAW_DIR, exist_ok=True)


# ==============================================================================
# TABLE 1: dim_product
# ==============================================================================

# ── 1a. Category hierarchy ────────────────────────────────────────────────────
SUBCATEGORIES = {
    "Dairy":         ["Milk & Cream", "Yogurts", "Cheese", "Butter & Spreads"],
    "Cereals":       ["Ready-to-Eat (RTE)", "Porridge & Oats", "Granola & Muesli"],
    "Beverages":     ["Soft Drinks", "Fruit Juices", "Tea & Coffee", "Functional/Energy"],
    "Snacks":        ["Crisps & Popcorn", "Savoury Biscuits", "Nut & Seed Mixes"],
    "Confectionery": ["Chocolate Bars", "Bags & Boxes", "Sugar Sweets", "Mints & Gum"],
    "Frozen Food":   ["Ice Cream", "Ready Meals", "Frozen Veg", "Pizza & Snacks"],
}

# Reverse lookup: subcategory → category
SUBCAT_TO_CATEGORY = {
    subcat: cat
    for cat, subcats in SUBCATEGORIES.items()
    for subcat in subcats
}

# ── 1b. Brand–subcategory mapping ─────────────────────────────────────────────
# Cross-subcategory brands are deliberate (enables cross-category queries):
#   CocoaEthos: Chocolate Bars + Bags & Boxes
#   BerryBliss:  Sugar Sweets  + Ice Cream
#   Velvet Dairy: Cheese       + Ice Cream
#   BoldBites:   Savoury Biscuits + Nut & Seed Mixes
SUBCAT_TO_BRAND = {
    # DAIRY
    "Milk & Cream":       ["LactoPure", "Alpine Creamery"],
    "Yogurts":            ["BioBloom", "Cultured Co."],
    "Cheese":             ["SkyrNorth", "Velvet Dairy"],
    "Butter & Spreads":   ["MorningMist", "FarmFresh"],
    # CEREALS
    "Ready-to-Eat (RTE)": ["NutriFlake", "GoldenClusters", "ToastMaster"],
    "Porridge & Oats":    ["ArtisanOats", "MorningMilled"],
    "Granola & Muesli":   ["GrainGlow", "SeededHearth"],
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
    "Pizza & Snacks":     ["PizzaFrost", "FrostPeak"],
}

# ── 1c. Price tiers (brand positioning) ─────────────────────────────────
PREMIUM_BRANDS = {
    "LactoPure", "BioBloom", "SkyrNorth", "ArtisanOats",
    "GrainGlow", "SeededHearth", "PurePulse", "BrewCraft",
    "NitroBoost", "Salt & Stone", "RootCrunch", "CocoaEthos",
    "BerryBliss",
}
MAINSTREAM_BRANDS = {
    "Alpine Creamery", "Cultured Co.", "Velvet Dairy", "MorningMist",
    "MorningMilled", "ToastMaster", "HydraVibe", "GlowWater",
    "LeafRitual", "Vitaline", "CrispCrave", "BoldBites",
    "UmamiWave", "SweetSync", "MintMarvel", "TableCraft",
    "PizzaFrost", "FrostPeak",
}
# All remaining brands are Value
VALUE_BRANDS = {
    "FarmFresh", "NutriFlake", "GoldenClusters", "ElectroFlow", "KernelPop",
    "ToffeeTide", "FruitFuse", "GlazeGlory", "ArcticBite",
    "CoolHarvest", "PolarPantry",
}

def get_price_tier(brand: str) -> str:
    """
    Gets price tier (brand-positioning) of a brand
    """
    if brand in PREMIUM_BRANDS:
        return "Premium"
    elif brand in MAINSTREAM_BRANDS:
        return "Mainstream"
    else:
        return "Value"


# ── 1d. Price ranges: (min_gbp, max_gbp) by (tier, category) ─────────────────
PRICE_RANGES = {
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

# price_endings = snaps the pence value of the price to a tier-appropriate ending
PRICE_ENDINGS = {
    "Premium":    [0.00, 0.25, 0.49, 0.50, 0.75, 0.99],
    "Mainstream": [0.49, 0.50, 0.79, 0.95, 0.99],
    "Value":      [0.49, 0.59, 0.69, 0.79, 0.89, 0.99],
}

# cost_price_gbp = list_price * Uniform(lo, hi) — thinner margins for Value
COST_FRACTION_RANGES = {
    "Premium":    (0.42, 0.58),
    "Mainstream": (0.48, 0.62),
    "Value":      (0.52, 0.68),
}


# ── 1e. Variant descriptors by category ───────────────────────────────────────
# Custom word lists preferred over Faker.word() — more reliable for FMCG context
VARIANT_DESCRIPTORS = {
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
                      "Country Style", "Farmhouse", "Signature"],
}


# ── 1f. Valid pack combinations by subcategory ────────────────────────────────
# Each tuple: (pack_size, pack_size_uom, pack_type)
# SKU differentiation comes from variants, not pack proliferation
VALID_COMBINATIONS = {
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
                           (6,"units","Multipack")],
}


# ── 1g. SKU generation helpers ────────────────────────────────────────────────

def generate_skus_for_brand_subcat(brand: str, subcategory: str,
                                   category: str, n: int = 12) -> list[dict]:
    """
    Generate n unique SKUs for a given brand–subcategory combination.
    Uniqueness enforced on (variant, pack_size, pack_size_uom, pack_type).
    Cycles through combos and variants independently to maximise variety.
    """
    combos   = VALID_COMBINATIONS[subcategory][:]   # copy — shuffle is in-place
    variants = VARIANT_DESCRIPTORS[category][:]

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
            pack_display = (f"{int(pack_size)}pk" if uom == "units"
                            else f"{pack_size}{uom}")
            sku_name = f"{brand} {variant} {pack_display} {pack_type}"
            skus.append({
                "sku_name":      sku_name,
                "brand":         brand,
                "sub_brand":     brand,          # same as brand (simple case)
                "category":      category,
                "sub_category":  subcategory,
                "pack_size":     pack_size,
                "pack_size_uom": uom,
                "pack_type":     pack_type,
                "variant":       variant,
            })

        combo_cycle   += 1
        variant_cycle += 1

    return skus


def snap_to_realistic_price(raw: float, tier: str) -> float:
    """
    Replaces the pence portion of a raw price with a
    tier-appropriate retail ending. Whole pounds are preserved
    so the result stays within the intended price range.
    """
    whole = math.floor(raw)
    pence = random.choice(PRICE_ENDINGS[tier])
    return round(whole + pence, 2)


def random_launch_date() -> str:
    """
    Returns a launch date string 'YYYY-MM-DD' distributed 2018–2025.
    Stored as string in raw layer — deliberate quality issue.
    Parsed to date type in preprocess.py.
    """
    start = date(2018, 1, 1)
    end   = date(2025, 12, 31)
    delta = (end - start).days
    return str(start + timedelta(days=random.randint(0, delta)))


def assign_is_active(launch_date_str: str, brand: str) -> str:
    """
    Inactive SKUs cluster around older launches and value brands.
    Stored as 'Y'/'N' string in raw layer — deliberate quality issue.
    Encoded to boolean in preprocess.py.
    """
    launch_year = int(launch_date_str[:4])
    rand = random.random()
    if launch_year < 2020 and rand < 0.35:
        return "N"   # older SKUs more likely discontinued
    if brand in VALUE_BRANDS and rand < 0.12:
        return "N"   # value brand portfolio rationalisation
    return "Y"


# ── 1h. Main dim_product generator ───────────────────────────────────────────

def generate_dim_product() -> pd.DataFrame:
    """
    Generates the dim_product dimension table.

    Approach:
        - Enumerate all brand–subcategory combos from SUBCAT_TO_BRAND
        - Generate 12 SKUs per combo (~540–552 rows total)
        - Assign price tier, list price, cost price, launch date, is_active
        - Write to data/raw/dim_product.parquet

    Returns:
        pd.DataFrame with all dim_product columns (pre-quality-issue-injection).
    """
    all_skus = []

    for subcategory, brands in SUBCAT_TO_BRAND.items():
        category = SUBCAT_TO_CATEGORY[subcategory]
        for brand in brands:
            skus = generate_skus_for_brand_subcat(brand, subcategory, category)
            all_skus.extend(skus)

    df = pd.DataFrame(all_skus)

    # ── Price tier (brand-level) ──────────────────────────────────────────────
    df["price_tier"] = df["brand"].map(get_price_tier)

    # ── List price — drawn from tier × category ranges with pence snapping ────
    df["list_price_gbp"] = df.apply(
        lambda row: snap_to_realistic_price(
            np.random.uniform(*PRICE_RANGES[(row["price_tier"], row["category"])]), row["price_tier"]
        ),
        axis=1,
    )

    # ── Cost price — fraction of list price, tighter margin at Value ──────────
    df["cost_price_gbp"] = df.apply(
        lambda row: round(
            row["list_price_gbp"]
            * np.random.uniform(*COST_FRACTION_RANGES[row["price_tier"]]),
            2
        ),
        axis=1,
    )

    # ── Launch date (string — deliberate quality issue) ───────────────────────
    df["launch_date"] = [random_launch_date() for _ in range(len(df))]

    # ── is_active ("Y"/"N" string — deliberate quality issue) ────────────────
    df["is_active"] = df.apply(
    lambda row: assign_is_active(row["launch_date"], row["brand"]),
    axis=1,
    )

    # ── product_id — sequential surrogate key "SKU-0001" ─────────────────────
    df.insert(0, "product_id",
              [f"SKU-{i+1:04d}" for i in range(len(df))])

    # ── Column order matches schema spec ─────────────────────────────────────
    col_order = [
        "product_id", "sku_name", "brand", "sub_brand",
        "category", "sub_category", "price_tier",
        "pack_size", "pack_size_uom", "pack_type", "variant",
        "list_price_gbp", "cost_price_gbp", "launch_date", "is_active",
    ]
    df = df[col_order].reset_index(drop=True)

    return df


# ==============================================================================
# TABLE 2: dim_customer
# ==============================================================================

# ── 2a. Channel–banner–account structure ──────────────────────────────────────
# Values = number of accounts per banner
# Total: 240 accounts across 5 channels, 15 banners

CUSTOMER_HIERARCHY = {
    "Grocery": {
        "Ashton Retail":         28,   # Key Account
        "Meridian Supermarkets": 22,   # Key Account
        "Hartfield's":           18,   # Key Account
        "ValuMart":              20,   # Key Account
    },
    "Discounter": {
        "PoundSave":             15,   # Key Account
        "Dealz Direct":          12,   # Key Account
    },
    "Convenience": {
        "CityStop":              30,   # Regional Multiple
        "Cornerstone":           20,   # Independent
        "QuickShop Express":     15,   # Regional Multiple
    },
    "eCommerce": {
        "Ashton Online":          8,   # Key Account
        "FreshDoor":              6,   # Key Account
        "PantryBox":              5,   # Key Account
    },
    "Foodservice": {
        "CaterPro":              18,   # Regional Multiple
        "Campus & Co":           12,   # Regional Multiple
        "HospitalityPlus":       11,   # Independent
    },
}
 
# ── 2b. Account type by banner ────────────────────────────────────────────────

BANNER_ACCOUNT_TYPE = {
    "Ashton Retail":         "Key Account",
    "Meridian Supermarkets": "Key Account",
    "Hartfield's":           "Key Account",
    "ValuMart":              "Key Account",
    "PoundSave":             "Key Account",
    "Dealz Direct":          "Key Account",
    "CityStop":              "Regional Multiple",
    "Cornerstone":           "Independent",
    "QuickShop Express":     "Regional Multiple",
    "Ashton Online":         "Key Account",
    "FreshDoor":             "Key Account",
    "PantryBox":             "Key Account",
    "CaterPro":              "Regional Multiple",
    "Campus & Co":           "Regional Multiple",
    "HospitalityPlus":       "Independent",
}
 
# ── 2c. Store count ranges by channel ─────────────────────────────────────────

STORE_COUNT_RANGES = {
    "Grocery":     (150, 600),
    "Discounter":  (80,  300),
    "Convenience": (10,  80),
    "eCommerce":   (1,   1),    # no physical stores — always 1
    "Foodservice": (1,   5),    # depot count
}
 
# ── 2d. Regions and sub-regional territories ──────────────────────────────────
REGIONS = ["North", "Midlands", "South", "Scotland", "Wales"]
 
TERRITORIES = {
    "North":    ["North West", "North East", "Yorkshire & Humber"],
    "Midlands": ["East Midlands", "West Midlands"],
    "South":    ["South East", "South West", "London & Home Counties"],
    "Scotland": ["Central Scotland", "Scottish Highlands"],
    "Wales":    ["North Wales", "South Wales"],
}
 
# Banners where ~15% of accounts have NULL territory (purposeful quality issue)
# Mirrors real independent trade — smaller operators with incomplete CRM coverage
NULL_TERRITORY_BANNERS = {"Cornerstone", "HospitalityPlus"}
NULL_TERRITORY_RATE    = 0.15
 
# ~10% NULL store_count across non-eCommerce accounts (quality issue)
# Simulates incomplete customer master file — outlet count not captured
# at onboarding. Impacts weighted distribution calculation in fact_market.
# Imputed with channel median in preprocess.py.
NULL_STORE_COUNT_RATE  = 0.10
 
 
def generate_dim_customer() -> pd.DataFrame:
    """
    Generates the dim_customer dimension table.
 
    Approach:
        - Enumerate all channel–banner combos from CUSTOMER_HIERARCHY
        - Generate the specified number of accounts per banner
        - region/territory: NULL for eCommerce (structural);
          ~15% NULL territory for Independent banners (purposeful quality issue)
        - store_count: drawn from channel range;
          ~10% NULL for non-eCommerce accounts (quality issue)
        - customer_name: Faker-generated UK company name
        - Write to data/raw/dim_customer.parquet
 
    Returns:
        pd.DataFrame with all dim_customer columns (pre-quality-issue-injection).
    """
    rows = []
 
    for channel, banners in CUSTOMER_HIERARCHY.items():
        for banner, n_accounts in banners.items():
            account_type = BANNER_ACCOUNT_TYPE[banner]
            store_lo, store_hi = STORE_COUNT_RANGES[channel]
 
            for _ in range(n_accounts):
 
                # ── Region & territory ────────────────────────────────────────
                if channel == "eCommerce":
                    region    = None   # structural — operates nationally
                    territory = None
                else:
                    region = random.choice(REGIONS)
                    territory = random.choice(TERRITORIES[region])
 
                # ── Store count ───────────────────────────────────────────────
                if store_lo == store_hi:
                    store_count = store_lo   # eCommerce: fixed at 1
                else:
                    store_count = random.randint(store_lo, store_hi)
 
                rows.append({
                    "customer_name": fake.company(),
                    "channel":       channel,
                    "banner":        banner,
                    "account_type":  account_type,
                    "region":        region,
                    "territory":     territory,
                    "store_count":   store_count,
                })
 
    df = pd.DataFrame(rows)
 
    # ── Apply ~10% NULL store_count (quality issue — non-eCommerce only) ──────
    # eCommerce store_count = 1 is a meaningful fixed value; NULLing it
    # would conflate a structural constant with a data quality problem.

    non_ecomm_idx = df[df["channel"] != "eCommerce"].index

    null_mask = np.random.random(len(non_ecomm_idx)) < NULL_STORE_COUNT_RATE

    df.loc[non_ecomm_idx[null_mask], "store_count"] = None

    # Note: pandas converts store_count to float64 once NULLs are introduced
    # (standard int cannot hold NaN). preprocess.py casts to nullable Int64.

    # Deterministic NULL territory for Independent banners
    for banner in NULL_TERRITORY_BANNERS:
        banner_idx = df[df["banner"] == banner].index
        n_nulls = max(1, round(len(banner_idx) * NULL_TERRITORY_RATE))
        null_idx = np.random.choice(banner_idx, size=n_nulls, replace=False)
        df.loc[null_idx, "territory"] = None
 
    # ── customer_id — sequential surrogate key "CUST-001" ────────────────────

    df.insert(0, "customer_id",
              [f"CUST-{i+1:03d}" for i in range(len(df))])
 
    # ── Column order matches schema spec ──────────────────────────────────────

    col_order = [
        "customer_id", "customer_name", "channel", "banner",
        "region", "territory", "account_type", "store_count",
    ]

    df = df[col_order].reset_index(drop=True)
 
    return df


# ==============================================================================
# SHARED CONSTANTS — performance signals + fact-table generation parameters
# ==============================================================================

# ── Performance signals (built into generation — NOT injected by inject_quality.py) ──

# 1. Brand-year volume multiplier: NitroBoost 18% YoY growth (health/energy trend)
BRAND_YEAR_MULTIPLIER = {
    ("NitroBoost", 2024): 1.00,
    ("NitroBoost", 2025): 1.18,
}

# 2. Subcategory Q3 seasonal dip: Porridge & Oats summer slump
SEASONAL_DIP_SUBCAT_1 = "Porridge & Oats"
SEASONAL_DIP_WEEKS_1 = frozenset(range(26, 40))   # ISO weeks 26–39, both years
SEASONAL_DIP_FACTOR_1 = 0.65                     # 35% volume decline in Q3

# 3. Subcategory Q4 seasonal dip: Ice Cream winter slump
SEASONAL_DIP_SUBCAT_2 = "Ice Cream"
SEASONAL_DIP_WEEKS_2 = frozenset(range(40, 53))   # ISO weeks 40-52, both years
SEASONAL_DIP_FACTOR_2 = 0.60                     # 40% volume decline in Q4

# 4. ValuMart banner deterioration across 2025: linear 1.00 → 0.82
DETERIORATING_BANNER  = "ValuMart"
VALMART_DECLINE_START = 1.00
VALMART_DECLINE_END   = 0.82

# ── Channel listing exclusions (structurally never listed) ────────────────────
CHANNEL_CATEGORY_UNLISTED = frozenset([
    ("Frozen Food", "Convenience"),   # no freezer logistics in small-format retail
    ("Frozen Food", "eCommerce"),     # consumer last-mile frozen not viable
    ("Snacks",      "eCommerce"),     # low value density, uneconomic per-unit delivery
])

# ── fact_sales generation parameters ─────────────────────────────────────────
# LISTING_PROBABILITY: fraction of valid channel-category (SKU, account) pairs
# that are actually ranging-listed. Reflects FMCG reality — not every SKU
# appears in every account. Tuned so that:
#   ~99K valid pairs × 0.50 listing × 104 weeks × 0.40 fill ≈ 2.07M rows.
LISTING_PROBABILITY = 0.50
WEEK_FILL_RATE      = 0.40    # fraction of weeks with a sale within a listed pair

PROMO_RATE         = 0.30     # probability of a transaction being on promotion
PROMO_MECHANICS    = ["Price Reduction", "BOGOF",  "Multi-buy"]
PROMO_MECH_WEIGHTS = [0.60,              0.25,     0.15]

# Channel volume scaling (multiplier on lognormal base)
# Grocery Key Accounts have far higher per-account throughput than Convenience.
CHANNEL_VOLUME_SCALE = {
    "Grocery":     4.0,
    "Discounter":  2.0,
    "Convenience": 0.5,
    "eCommerce":   3.0,
    "Foodservice": 2.0,
}

# Base volume distribution: lognormal(mu, sigma) before channel scaling
# exp(4.0) ≈ 55 units/week per account at base scale — realistic Convenience floor
VOLUME_MU    = 4.0
VOLUME_SIGMA = 0.6

# Realised selling price as fraction of list_price_gbp
PRICE_REALISATION_RANGE = {
    "non_promo": (0.95, 1.02),
    "promo":     (0.75, 0.90),
}

# ── fact_market generation parameters ────────────────────────────────────────
# 46 brand-subcat combos × 15 banners × 0.60 listing × 104 weeks ≈ 43K rows
MARKET_BRAND_BANNER_LISTING = 0.60

# Total category volume: lognormal for stable weekly market totals
CATEGORY_VOLUME_MU    = 8.5
CATEGORY_VOLUME_SIGMA = 0.5

# Brand market share as fraction of total category — realistic FMCG single-brand range
BRAND_MARKET_SHARE_RANGE = (0.10, 0.38)

# Avg selling price: noise multiplier around brand's mean list price
MARKET_PRICE_NOISE_RANGE = (0.90, 1.10)

# Retailer markup over manufacturer avg selling price → consumer shelf price (RSP).
# RSP is what Nielsen/Kantar measure when they record value sales.
# Convenience carries the highest markup (impulse, low basket size);
# Discounters the lowest (EDLP model, thin margins on branded goods).
RETAILER_MARKUP = {
    "Grocery":     1.30,   # standard grocery margin ~23% on RSP
    "Discounter":  1.20,   # EDLP model — lower branded margin
    "Convenience": 1.40,   # impulse premium, small basket
    "eCommerce":   1.25,   # online — competitive pricing, lower impulse
    "Foodservice": 1.35,   # catering margin on branded ingredients
}


# ==============================================================================
# SHARED HELPER — ISO week spine
# ==============================================================================

def _build_week_spine() -> pd.DataFrame:
    """
    Returns a 104-row DataFrame of ISO weeks covering 2024-01-01 – 2025-12-31.
    Each row = the Monday of one ISO week.

    2024-01-01 is a Monday (day_of_week == 0), so W-MON starts there.
    The ISO week filter (year in {2024, 2025}) drops the stray Monday
    2025-12-29 which belongs to ISO year 2026 week 1.
    """
    mondays = pd.date_range("2024-01-01", "2025-12-31", freq="W-MON")
    df = pd.DataFrame({"week_date": mondays})
    iso = df["week_date"].dt.isocalendar()
    df["year"]        = iso.year.values.astype(int)
    df["quarter"]     = df["week_date"].dt.quarter.astype(int)
    df["month"]       = df["week_date"].dt.month.astype(int)
    df["week_number"] = iso.week.values.astype(int)
    
    # Drop the lone Monday whose ISO year bleeds into 2026
    df = df[df["year"].isin([2024, 2025])].reset_index(drop=True)
    return df # 104 rows exactly


# ==============================================================================
# TABLE 3: fact_sales
# ==============================================================================

def generate_fact_sales(dim_product: pd.DataFrame,
                        dim_customer: pd.DataFrame) -> pd.DataFrame:
    """
    Generates the fact_sales transaction table (~2.0M rows).

    Approach
    --------
    1.  Build 104-week ISO spine (2024-01-01 – 2025-12-31).
    2.  Cross-join active SKUs × all accounts; remove unlisted
        channel-category combinations; apply LISTING_PROBABILITY to
        simulate realistic SKU ranging per account.
    3.  Generate a boolean fill matrix (n_pairs × 104) at WEEK_FILL_RATE
        using numpy — avoids an explicit triple loop.
    4.  Draw baseline_volume from lognormal base scaled by channel, then
        apply the three intentional performance signals as multipliers.
        Signals are applied to baseline BEFORE promotion so that structural
        trend is not distorted by independent promo mix variation:
          – NitroBoost 2025 growth   (+18%, brand × year)
          – Porridge & Oats Q3 dip   (–35%, sub_category × ISO weeks 26-39)
          – Ice Cream Q4 dip         (–40%, sub_category × ISO weeks 40-52)
          – ValuMart 2025 decline    (linear 1.00→0.82 across 2025 weeks)
    5.  Draw incremental_volume independently for promoted rows (20–50% uplift).
        Non-promoted rows carry zero incremental by definition.
    6.  volume_units = baseline_volume + incremental_volume.
    7.  Derive all financial columns from volume_units + list_price_gbp.
    8.  FK assert before return.

    Performance signals are structural parameters — not noise, not injected
    later. inject_quality.py will separately introduce quality defects.

    Returns
    -------
    pd.DataFrame — all fact_sales columns, pre-quality-issue-injection.
    """
    # ── 1. Week spine ─────────────────────────────────────────────────────────
    weeks   = _build_week_spine()
    n_weeks = len(weeks)                                       # 104

    wk_dates    = weeks["week_date"].values
    wk_years    = weeks["year"].values
    wk_quarters = weeks["quarter"].values
    wk_months   = weeks["month"].values
    wk_wknums   = weeks["week_number"].values

    # ── 2. Active SKUs ────────────────────────────────────────────────────────
    active = (
        dim_product[dim_product["is_active"] == "Y"]
        [["product_id", "brand", "sub_category", "category",
        "price_tier", "list_price_gbp"]]
        .reset_index(drop=True)
    )

    # ── 3. Cross-join active SKUs × accounts → candidate pairs ───────────────
    customers = dim_customer[["customer_id", "channel", "banner"]]
    pairs = active.merge(customers, how="cross")

    # Remove structurally unlisted channel-category combinations
    cat_chan = list(zip(pairs["category"], pairs["channel"]))
    unlisted = np.array(
        [pair in CHANNEL_CATEGORY_UNLISTED for pair in cat_chan], dtype=bool
    )
    pairs = pairs[~unlisted].reset_index(drop=True)

    # Apply listing probability — not every active SKU is sold to every account
    listing_mask = np.random.random(len(pairs)) < LISTING_PROBABILITY
    pairs = pairs[listing_mask].reset_index(drop=True)
    n_pairs = len(pairs)

    # ── 4. Fill matrix: (n_pairs × n_weeks) Bernoulli ─────────────────────────
    # Boolean matrix: True = a transaction exists for this pair in this week.

    fill             = np.random.random((n_pairs, n_weeks)) < WEEK_FILL_RATE
    pair_idx, wk_idx = np.where(fill)
    n_rows           = len(pair_idx)

    # ── 5. Assemble base DataFrame using numpy index arrays ───────────────────
    df = pd.DataFrame({
        "product_id":     pairs["product_id"].values[pair_idx],
        "customer_id":    pairs["customer_id"].values[pair_idx],
        "brand":          pairs["brand"].values[pair_idx],
        "sub_category":   pairs["sub_category"].values[pair_idx],
        "category":       pairs["category"].values[pair_idx],
        "price_tier":     pairs["price_tier"].values[pair_idx],
        "list_price_gbp": pairs["list_price_gbp"].values[pair_idx].astype(float),
        "channel":        pairs["channel"].values[pair_idx],
        "banner":         pairs["banner"].values[pair_idx],
        "week_date":      wk_dates[wk_idx],
        "year":           wk_years[wk_idx],
        "quarter":        wk_quarters[wk_idx],
        "month":          wk_months[wk_idx],
        "week_number":    wk_wknums[wk_idx],
    })

    # ── 6. Base volume (lognormal, channel-scaled) → becomes baseline_volume ─────
    # The lognormal draw represents structural demand — the volume this SKU-account
    # pair would move WITHOUT any promotional activity. Signal multipliers are
    # applied here, before promotion, so NitroBoost growth and ValuMart decline
    # are embedded in the clean baseline rather than being diluted by promo mix.
    ch_scale    = df["channel"].map(CHANNEL_VOLUME_SCALE).values.astype(float)
    raw_vol     = np.random.lognormal(mean=VOLUME_MU, sigma=VOLUME_SIGMA, size=n_rows)
    baseline_vol = np.maximum(1, np.round(raw_vol * ch_scale)).astype(np.int64)

    # ── 7. Performance signal multipliers (applied to baseline only) ───────────
    # Applying signals to baseline — not total volume — isolates structural trend
    # from promotional distortion. Promo mix varies independently and would
    # otherwise inflate or mask YoY and intra-year signals.

    # Signal 1 — NitroBoost 2025 growth (+18%)
    nb_mask = (df["brand"].values == "NitroBoost") & (df["year"].values == 2025)
    if nb_mask.any():
        baseline_vol[nb_mask] = np.maximum(
            1,
            np.round(baseline_vol[nb_mask] * BRAND_YEAR_MULTIPLIER[("NitroBoost", 2025)])
        ).astype(np.int64)

    # Signal 2 — Porridge & Oats Q3 seasonal dip (ISO weeks 26–39)
    oats_mask = (
        (df["sub_category"].values == SEASONAL_DIP_SUBCAT_1) &
        np.isin(df["week_number"].values, list(SEASONAL_DIP_WEEKS_1))
    )
    if oats_mask.any():
        baseline_vol[oats_mask] = np.maximum(
            1,
            np.round(baseline_vol[oats_mask] * SEASONAL_DIP_FACTOR_1)
        ).astype(np.int64)

    # Signal 3 — Ice Cream Q4 seasonal dip (ISO weeks 40-52)
    ice_mask = (
        (df["sub_category"].values == SEASONAL_DIP_SUBCAT_2) &
        np.isin(df["week_number"].values, list(SEASONAL_DIP_WEEKS_2))
    )
    if ice_mask.any():
        baseline_vol[ice_mask] = np.maximum(
            1,
            np.round(baseline_vol[ice_mask] * SEASONAL_DIP_FACTOR_2)
        ).astype(np.int64)

    # Signal 4 — ValuMart 2025 linear deterioration (1.00 at wk 1 → 0.82 at wk 52)
    vm_mask = (df["banner"].values == DETERIORATING_BANNER) & (df["year"].values == 2025)
    if vm_mask.any():
        vm_wknums  = df["week_number"].values[vm_mask]
        vm_decline = (
            VALMART_DECLINE_START
            - (VALMART_DECLINE_START - VALMART_DECLINE_END)
            * (vm_wknums - 1) / 51.0
        )
        baseline_vol[vm_mask] = np.maximum(
            1,
            np.round(baseline_vol[vm_mask] * vm_decline)
        ).astype(np.int64)

    # ── 8. Promotion flags ────────────────────────────────────────────────────
    is_promo = np.random.random(n_rows) < PROMO_RATE
    df["is_promoted"] = is_promo

    mechanics       = np.full(n_rows, None, dtype=object)
    promo_positions = np.where(is_promo)[0]
    mechanics[promo_positions] = np.random.choice(
        PROMO_MECHANICS, size=len(promo_positions), p=PROMO_MECH_WEIGHTS
    )
    df["promotion_mechanic"] = mechanics

    # ── 9. Incremental volume (promo uplift on top of baseline) ───────────────
    # Promoted rows: uplift of 20–50% above baseline, drawn independently.
    # Non-promoted rows: zero incremental — no promo, no mechanistic uplift.
    incremental_vol = np.zeros(n_rows, dtype=np.int64)
    if promo_positions.size > 0:
        uplift_frac = np.random.uniform(0.20, 0.50, size=len(promo_positions))
        incremental_vol[promo_positions] = np.maximum(
            1,
            np.round(baseline_vol[promo_positions] * uplift_frac)
        ).astype(np.int64)

    # ── 10. Total volume = baseline + incremental ─────────────────────────────
    volume = baseline_vol + incremental_vol

    df["volume_units"]      = volume
    df["baseline_volume"]   = baseline_vol
    df["incremental_volume"] = incremental_vol

    # ── 11. Realised selling price ────────────────────────────────────────────
    lo = np.where(
        is_promo,
        PRICE_REALISATION_RANGE["promo"][0],
        PRICE_REALISATION_RANGE["non_promo"][0]
    )
    hi = np.where(
        is_promo,
        PRICE_REALISATION_RANGE["promo"][1],
        PRICE_REALISATION_RANGE["non_promo"][1]
    )
    realisation          = np.random.random(n_rows) * (hi - lo) + lo
    list_prices          = df["list_price_gbp"].values
    selling_price        = np.round(list_prices * realisation, 2)
    df["selling_price_gbp"] = selling_price

    # ── 12. Revenue columns ───────────────────────────────────────────────────
    df["gross_revenue_gbp"]  = np.round(volume * list_prices, 2)
    df["trade_discount_gbp"] = np.round(
        volume * np.maximum(0.0, list_prices - selling_price), 2
    )
    df["net_revenue_gbp"]    = np.round(
        df["gross_revenue_gbp"].values - df["trade_discount_gbp"].values, 2
    )

    # ── 13. Surrogate PK ──────────────────────────────────────────────────────
    df.insert(0, "transaction_id", np.arange(1, n_rows + 1, dtype=np.int64))

    # ── 14. Final column order ────────────────────────────────────────────────
    col_order = [
        "transaction_id",
        "week_date", "year", "quarter", "month", "week_number",
        "product_id", "customer_id",
        "volume_units", "gross_revenue_gbp", "trade_discount_gbp",
        "net_revenue_gbp", "selling_price_gbp",
        "is_promoted", "promotion_mechanic",
        "baseline_volume", "incremental_volume",
    ]
    df = df[col_order].reset_index(drop=True)

    # ── 14. FK assertions ─────────────────────────────────────────────────────
    valid_product_ids  = set(dim_product["product_id"])
    valid_customer_ids = set(dim_customer["customer_id"])
    assert df["product_id"].isin(valid_product_ids).all(), \
        "fact_sales FK violation: product_id not in dim_product"
    assert df["customer_id"].isin(valid_customer_ids).all(), \
        "fact_sales FK violation: customer_id not in dim_customer"

    return df


# ==============================================================================
# TABLE 4: fact_market
# ==============================================================================

def generate_fact_market(dim_product: pd.DataFrame,
                         dim_customer: pd.DataFrame) -> pd.DataFrame:
    """
    Generates the fact_market panel measurement table (~40K rows).

    Grain: week × brand × sub_category × banner.

    Approach
    --------
    1.  Determine listed (brand, sub_category, banner) triplets at
        MARKET_BRAND_BANNER_LISTING probability.
    2.  Cross-join listed triplets × 104-week spine.
    3.  Generate total_category_volume_units FIRST (market denominator).
        Derive brand_volume_units as brand_share × total — this guarantees
        the critical constraint brand_vol ≤ category_vol for all raw rows.
    4.  Apply ValuMart 2025 deterioration by reducing brand_share for
        ValuMart rows linearly across 2025 ISO weeks (1.00 → 0.82).
    5.  Derive manufacturer_net_price_gbp then apply channel-appropriate
        RETAILER_MARKUP to produce consumer_shelf_price_gbp (RSP). Value columns use RSP — consistent with how Nielsen/Kantar measure value sales at the till.
    6.  Derive distribution columns.
    7.  FK + constraint assertions before return.

    The total_category_volume_units represents the full market (all brands
    including non-portfolio competitors), so brand_share < 1.0 always.

    Returns
    -------
    pd.DataFrame — all fact_market columns, pre-quality-issue-injection.
    """
    # ── 1. Week spine ─────────────────────────────────────────────────────────
    weeks = _build_week_spine()

    # ── 2. Unique brand–subcategory combinations ──────────────────────────────
    brand_subcat = (
        dim_product[["brand", "sub_category"]]
        .drop_duplicates()
        .reset_index(drop=True)
    )

    # ── 3. All banners ────────────────────────────────────────────────────────
    banners = (
        dim_customer[["banner"]]
        .drop_duplicates()
        .reset_index(drop=True)
    )

    # ── 4. Cross-join → all possible (brand, sub_category, banner) triplets ───
    triplets = brand_subcat.merge(banners, how="cross")

    # Apply listing probability — not every brand is measured in every banner
    listed_mask = np.random.random(len(triplets)) < MARKET_BRAND_BANNER_LISTING
    triplets    = triplets[listed_mask].reset_index(drop=True)

    # ── 5. Cross-join listed triplets × week spine ────────────────────────────
    grid = (
        triplets.merge(weeks, how="cross")
        .reset_index(drop=True)
    )
    n_rows = len(grid)

    # ── 6. Total category volume (generated FIRST — market denominator) ────────
    # lognormal(8.5, 0.5): median ≈ 4,900 units, mean ≈ 5,500 — realistic
    # weekly category volumes at a grocery banner.
    total_cat_vol = np.maximum(
        100,
        np.random.lognormal(
            mean=CATEGORY_VOLUME_MU, sigma=CATEGORY_VOLUME_SIGMA, size=n_rows
        ).astype(np.int64)
    )

    # ── 7. Brand market share → brand volume ──────────────────────────────────
    lo_s, hi_s  = BRAND_MARKET_SHARE_RANGE
    brand_share = np.random.uniform(lo_s, hi_s, size=n_rows)

    # Signal: ValuMart 2025 linear deterioration — reduce brand_share
    # (total_category_volume_units is untouched; only our brand's portion shrinks)
    vm_mask = (
        (grid["banner"].values == DETERIORATING_BANNER) &
        (grid["year"].values == 2025)
    )
    if vm_mask.any():
        vm_wknums   = grid["week_number"].values[vm_mask]
        vm_mult     = (
            VALMART_DECLINE_START
            - (VALMART_DECLINE_START - VALMART_DECLINE_END)
            * (vm_wknums - 1) / 51.0
        )
        brand_share[vm_mask] = np.clip(brand_share[vm_mask] * vm_mult, 0.01, 1.0)

    # brand_volume derived from total — constraint brand_vol ≤ category_vol guaranteed
    brand_vol = np.maximum(
        1,
        np.floor(total_cat_vol * brand_share).astype(np.int64)
    )

    grid["brand_volume_units"]          = brand_vol
    grid["total_category_volume_units"] = total_cat_vol

    # ── 8. Average selling price per brand + consumer shelf price ────────────
    # manufacturer_net_price_gbp: manufacturer's net realised price (trade net).
    #   Derived from brand mean list price ± week-to-week noise (±10%).
    # consumer_shelf_price_gbp: retailer shelf price (RSP).
    #   = manufacturer_net_price_gbp × channel markup.
    #   This is the price Nielsen/Kantar record when measuring value sales —
    #   so value columns below use RSP, not the manufacturer net price.
    brand_avg_price = (
        dim_product.groupby("brand")["list_price_gbp"]
        .mean()
        .reset_index()
        .rename(columns={"list_price_gbp": "_brand_base_price"})
    )
    grid = grid.merge(brand_avg_price, on="brand", how="left")

    price_noise = np.random.uniform(
        MARKET_PRICE_NOISE_RANGE[0], MARKET_PRICE_NOISE_RANGE[1], size=n_rows
    )
    grid["manufacturer_net_price_gbp"] = np.round(
        grid["_brand_base_price"].values * price_noise, 2
    )

    # Banner → channel lookup to apply the right markup per row
    banner_channel = (
        dim_customer[["banner", "channel"]]
        .drop_duplicates("banner")
        .set_index("banner")["channel"]
    )
    grid["_channel"] = grid["banner"].map(banner_channel)
    markup = grid["_channel"].map(RETAILER_MARKUP).values.astype(float)

    grid["consumer_shelf_price_gbp"] = np.round(
        grid["manufacturer_net_price_gbp"] * markup, 2
    )

    # ── 9. Value columns (at RSP — consistent with panel measurement) ─────────
    # Nielsen/Kantar value = volume × consumer shelf price, not manufacturer net.
    grid["brand_value_gbp"] = np.round(
        grid["brand_volume_units"] * grid["consumer_shelf_price_gbp"], 2
    )

    cat_price_mult = np.random.uniform(0.92, 1.08, size=n_rows)
    grid["total_category_value_gbp"] = np.round(
        grid["total_category_volume_units"]
        * grid["consumer_shelf_price_gbp"]
        * cat_price_mult, 2
    )

    # ── 10. Distribution columns ──────────────────────────────────────────────
    # total_outlets_in_banner: sum store_count across all accounts for that banner.
    # ~10% NULL store_count in dim_customer — dropna excludes those accounts.
    banner_outlets = (
        dim_customer.dropna(subset=["store_count"])
        .groupby("banner")["store_count"]
        .sum()
        .reset_index()
        .rename(columns={"store_count": "total_outlets_in_banner"})
    )
    grid = grid.merge(banner_outlets, on="banner", how="left")

    # Numeric distribution: brands with higher market share have higher distribution.
    # Add small random noise; clip to [0.10, 1.00] fraction of total outlets.
    dist_frac = np.clip(
        brand_share * 2.5 + np.random.uniform(-0.05, 0.10, size=n_rows),
        0.10, 1.00
    )
    tot_outlets = grid["total_outlets_in_banner"].values.astype(float)
    grid["numeric_distribution_outlets"] = np.minimum(
        np.maximum(1, np.round(tot_outlets * dist_frac).astype(np.int64)),
        grid["total_outlets_in_banner"].values.astype(np.int64)
    )

    # ── 11. Surrogate PK ──────────────────────────────────────────────────────
    grid.insert(0, "measurement_id", np.arange(1, n_rows + 1, dtype=np.int64))

    # ── 12. Final column order (drops _brand_base_price and _channel) ───────────
    col_order = [
        "measurement_id",
        "week_date", "year", "quarter", "month", "week_number",
        "brand", "sub_category", "banner",
        "brand_volume_units", "brand_value_gbp",
        "total_category_volume_units", "total_category_value_gbp",
        "numeric_distribution_outlets", "total_outlets_in_banner",
        "manufacturer_net_price_gbp", "consumer_shelf_price_gbp",
    ]
    grid = grid[col_order].reset_index(drop=True)

    # ── 13. FK + critical constraint assertions ────────────────────────────────
    valid_brands  = set(dim_product["brand"])
    valid_banners = set(dim_customer["banner"])
    valid_subcats = set(dim_product["sub_category"])
    assert grid["brand"].isin(valid_brands).all(), \
        "fact_market FK violation: brand not in dim_product"
    assert grid["banner"].isin(valid_banners).all(), \
        "fact_market FK violation: banner not in dim_customer"
    assert grid["sub_category"].isin(valid_subcats).all(), \
        "fact_market FK violation: sub_category not in dim_product"
    assert (grid["brand_volume_units"] <= grid["total_category_volume_units"]).all(), \
        "fact_market CONSTRAINT violation: brand_volume_units > total_category_volume_units"
    assert (grid["consumer_shelf_price_gbp"] > grid["manufacturer_net_price_gbp"]).all(), \
        "fact_market CONSTRAINT violation: consumer_shelf_price_gbp ≤ manufacturer_net_price_gbp"

    return grid


# ==============================================================================
# MAIN — generation pipeline (strict FK order)
# ==============================================================================

def main():
    print("=" * 60)
    print("Project Insight — Synthetic FMCG Dataset Generator")
    print("=" * 60)

    # 1. dim_product
    print("\n[1/4] Generating dim_product...")
    dim_product = generate_dim_product()
    out_path = os.path.join(RAW_DIR, "dim_product.parquet")
    dim_product.to_parquet(out_path, index=False)
    print(f"      Written: {out_path}")
    print(f"      Rows: {len(dim_product):,}  |  "
          f"Active: {(dim_product['is_active']=='Y').sum()}  |  "
          f"Inactive: {(dim_product['is_active']=='N').sum()}")

    # 2. dim_customer
    print("\n[2/4] Generating dim_customer...")
    dim_customer = generate_dim_customer()
    out_path = os.path.join(RAW_DIR, "dim_customer.parquet")
    dim_customer.to_parquet(out_path, index=False)
    print(f"      Written: {out_path}")
    print(f"      Rows: {len(dim_customer):,}  |  "
          f"Channels: {dim_customer['channel'].nunique()}  |  "
          f"Banners: {dim_customer['banner'].nunique()}")

    # 3. fact_sales  (reads dim_product + dim_customer PKs)
    print("\n[3/4] Generating fact_sales...")
    fact_sales = generate_fact_sales(dim_product, dim_customer)
    out_path = os.path.join(RAW_DIR, "fact_sales.parquet")
    fact_sales.to_parquet(out_path, index=False)
    print(f"      Written: {out_path}")
    print(f"      Rows: {len(fact_sales):,}  |  "
          f"Promoted: {fact_sales['is_promoted'].sum():,}  "
          f"({fact_sales['is_promoted'].mean():.1%})")

    # 4. fact_market  (reads dim_product brands/subcats + dim_customer banners)
    print("\n[4/4] Generating fact_market...")
    fact_market = generate_fact_market(dim_product, dim_customer)
    out_path = os.path.join(RAW_DIR, "fact_market.parquet")
    fact_market.to_parquet(out_path, index=False)
    print(f"      Written: {out_path}")
    print(f"      Rows: {len(fact_market):,}  |  "
          f"Brands: {fact_market['brand'].nunique()}  |  "
          f"Banners: {fact_market['banner'].nunique()}")

    print("\n" + "=" * 60)
    print("Generation complete. Run validate_* functions to verify.")
    print("=" * 60)
 
 
# ==============================================================================
# VALIDATION — F-01 acceptance criteria checks for dim_product
# ==============================================================================
 
def validate_dim_product():
    """
    Sprint 1 / F-01 acceptance criteria validation for dim_product.
    Run after generate_dim_product() has written the Parquet file.
    """
    path = os.path.join(RAW_DIR, "dim_product.parquet")
    df = pd.read_parquet(path)
 
    print("\n── dim_product validation ──────────────────────────────────────")
 
    # Row count
    print(f"\nRow count : {len(df):,}  (expect ~540–552)")
 
    # PK non-null and unique
    pk_nulls  = df["product_id"].isnull().sum()
    pk_unique = df["product_id"].nunique()
    print(f"PK nulls  : {pk_nulls}   (expect 0)")
    print(f"PK unique : {pk_unique}  (expect = row count)")
 
    # is_active distribution
    print(f"\nis_active distribution:")
    print(df["is_active"].value_counts().to_string())
    print(f"  → Active SKUs: {(df['is_active']=='Y').sum()}  (expect ~480–500)")
 
    # Price tier distribution
    print(f"\nPrice tier distribution:")
    print(df["price_tier"].value_counts().to_string())
 
    # SKUs per brand–subcategory (expect 12 per combo)
    combo_counts = df.groupby(["sub_category", "brand"]).size()
    print(f"\nSKUs per brand–subcategory:")
    print(f"  Min: {combo_counts.min()}  Max: {combo_counts.max()}  "
          f"(expect all = 12)")
    if (combo_counts != 12).any():
        print("  WARNING: Some combos deviate from 12:")
        print(combo_counts[combo_counts != 12])
 
    # launch_date stored as string (deliberate quality issue)
    print(f"\nlaunch_date dtype: {df['launch_date'].dtype}  (expect object/string)")
    print(f"launch_date sample: {df['launch_date'].head(3).tolist()}")
 
    # is_active stored as string (deliberate quality issue)
    print(f"\nis_active dtype: {df['is_active'].dtype}  (expect object/string)")
    print(f"Unique values  : {df['is_active'].unique().tolist()}  (expect ['Y','N'])")
 
    # Null check — no unintended nulls expected pre-injection
    null_counts = df.isnull().sum()
    unexpected_nulls = null_counts[null_counts > 0]
    if unexpected_nulls.empty:
        print("\nNull check: PASS — no nulls pre-injection ✓")
    else:
        print("\nNull check: UNEXPECTED NULLS FOUND:")
        print(unexpected_nulls)
 
    # Price sanity: cost < list
    price_violations = (df["cost_price_gbp"] >= df["list_price_gbp"]).sum()
    print(f"\nPrice sanity (cost < list): "
          f"{'PASS ✓' if price_violations == 0 else f'FAIL — {price_violations} violations'}")
 
    # Category coverage — all 6 categories present
    categories_present = set(df["category"].unique())
    expected_categories = set(SUBCATEGORIES.keys())
    if categories_present == expected_categories:
        print(f"Category coverage: PASS ✓ — all 6 categories present")
    else:
        print(f"Category coverage: FAIL — missing {expected_categories - categories_present}")
 
    print("\n── Validation complete ─────────────────────────────────────────\n")
 
 
# ==============================================================================
# VALIDATION — F-01 acceptance criteria checks for dim_customer
# ==============================================================================
 
def validate_dim_customer():
    """
    Sprint 1 / F-01 acceptance criteria validation for dim_customer.
    Run after generate_dim_customer() has written the Parquet file.
    """
    path = os.path.join(RAW_DIR, "dim_customer.parquet")
    df = pd.read_parquet(path)
 
    print("\n── dim_customer validation ─────────────────────────────────────")
 
    # Row count
    print(f"\nRow count : {len(df):,}  (expect 240)")
 
    # PK non-null and unique
    print(f"PK nulls  : {df['customer_id'].isnull().sum()}  (expect 0)")
    print(f"PK unique : {df['customer_id'].nunique()}  (expect 240)")
 
    # Channel distribution
    print(f"\nChannel distribution:")
    print(df["channel"].value_counts().to_string())
 
    # Accounts per banner vs spec
    expected_counts = {
        banner: count
        for banners in CUSTOMER_HIERARCHY.values()
        for banner, count in banners.items()
    }
    banner_counts = df.groupby("banner").size()
    mismatches = {
        b: (banner_counts.get(b, 0), expected_counts[b])
        for b in expected_counts
        if banner_counts.get(b, 0) != expected_counts[b]
    }
    if mismatches:
        print(f"\nBanner count mismatches (got vs expected):")
        for banner, (got, exp) in mismatches.items():
            print(f"  {banner}: {got} (expected {exp})")
    else:
        print(f"\nBanner counts: PASS ✓ — all 15 banners match spec")
 
    # eCommerce structural NULLs
    ecomm = df[df["channel"] == "eCommerce"]
    ecomm_region_nulls    = ecomm["region"].isnull().sum()
    ecomm_territory_nulls = ecomm["territory"].isnull().sum()
    print(f"\neCommerce NULL region   : {ecomm_region_nulls}/{len(ecomm)}  "
          f"{'PASS ✓' if ecomm_region_nulls == len(ecomm) else 'FAIL'}")
    print(f"eCommerce NULL territory: {ecomm_territory_nulls}/{len(ecomm)}  "
          f"{'PASS ✓' if ecomm_territory_nulls == len(ecomm) else 'FAIL'}")
 
    # NULL territory rate for Independent banners (~15%)
    ind = df[df["banner"].isin(["Cornerstone", "HospitalityPlus"])]
    null_terr_rate = ind["territory"].isnull().mean()
    print(f"\nNULL territory (Independent banners): {null_terr_rate:.1%}  (expect ~15%)")
 
    # NULL store_count rate (non-eCommerce, ~10%)
    non_ecomm = df[df["channel"] != "eCommerce"]
    null_store_rate = non_ecomm["store_count"].isnull().mean()
    print(f"NULL store_count (non-eCommerce)    : {null_store_rate:.1%}  (expect ~10%)")
 
    # Store count ranges by channel (non-null values)
    print(f"\nStore count by channel (non-null):")
    store_summary = (
        df.dropna(subset=["store_count"])
        .groupby("channel")["store_count"]
        .agg(["min", "max", "mean"])
        .round(0)
        .astype(int)
    )
    print(store_summary.to_string())
 
    print("\n── Validation complete ─────────────────────────────────────────\n")
 
# ==============================================================================
# VALIDATION — fact_sales acceptance criteria
# ==============================================================================

def validate_fact_sales():
    """
    Sprint 1 / F-01 acceptance criteria validation for fact_sales.
    Run after generate_fact_sales() has written the Parquet file.
    """
    path = os.path.join(RAW_DIR, "fact_sales.parquet")
    df   = pd.read_parquet(path)
    dp   = pd.read_parquet(os.path.join(RAW_DIR, "dim_product.parquet"))
    dc   = pd.read_parquet(os.path.join(RAW_DIR, "dim_customer.parquet"))

    print("\n── fact_sales validation ────────────────────────────────────────")

    # Row count
    print(f"\nRow count : {len(df):,}  (expect ~2.0M)")

    # Year split
    print(f"\nYear split:")
    print(df["year"].value_counts().sort_index().to_string())

    # Week count
    print(f"\nUnique weeks : {df['week_date'].nunique()}  (expect 104)")

    # FK checks
    pk_miss   = (~df["product_id"].isin(dp["product_id"])).sum()
    cust_miss = (~df["customer_id"].isin(dc["customer_id"])).sum()
    print(f"\nFK product_id  : {pk_miss} orphans    (expect 0)")
    print(f"FK customer_id : {cust_miss} orphans    (expect 0)")

    # Promotion distribution
    print(f"\nis_promoted distribution:")
    print(df["is_promoted"].value_counts().to_string())
    print(f"  → Promo rate: {df['is_promoted'].mean():.1%}  (expect ~30%)")

    # Revenue sanity: net = gross - discount, all ≥ 0
    rev_check = (df["net_revenue_gbp"] < 0).sum()
    print(f"\nNegative net_revenue_gbp : {rev_check}  (expect 0)")

    # ── Performance signal verification (on baseline_volume — not total) ─────
    # Signals are embedded in baseline. Checking total would conflate promo mix.

    # Signal 1: NitroBoost YoY baseline growth
    nb_ids = dp[dp["brand"] == "NitroBoost"]["product_id"]
    nb     = df[df["product_id"].isin(nb_ids)]
    print(f"\nNitroBoost baseline_volume by year:")
    print(nb.groupby("year")["baseline_volume"].sum().to_string())
    print(f"  → Expect 2025 > 2024 by ~18%")

    # Signal 2: Porridge & Oats Q3 baseline dip
    po_ids = dp[dp["sub_category"] == "Porridge & Oats"]["product_id"]
    po     = df[df["product_id"].isin(po_ids)].copy()
    po["in_q3"] = po["week_number"].isin(range(26, 40))
    q3_avg    = po[po["in_q3"]]["baseline_volume"].mean()
    nonq3_avg = po[~po["in_q3"]]["baseline_volume"].mean()
    print(f"\nPorridge & Oats avg weekly baseline_volume:")
    print(f"  Q3 (wks 26–39): {q3_avg:,.0f}  |  Non-Q3: {nonq3_avg:,.0f}")
    print(f"  → Expect Q3 ≈ 65% of non-Q3")

    # Signal 3: Ice Cream Q4 baseline dip
    ic_ids = dp[dp["sub_category"] == "Ice Cream"]["product_id"]
    ic     = df[df["product_id"].isin(ic_ids)].copy()
    ic["in_q4"] = ic["week_number"].isin(range(40, 53))
    q4_avg    = ic[ic["in_q4"]]["baseline_volume"].mean()
    nonq4_avg = ic[~ic["in_q4"]]["baseline_volume"].mean()
    print(f"\nIce Cream avg weekly baseline_volume:")
    print(f"  Q4 (wks 40–52): {q4_avg:,.0f}  |  Non-Q4: {nonq4_avg:,.0f}")
    print(f"  → Expect Q4 ≈ 60% of non-Q4")

    # Signal 4: ValuMart 2025 baseline deterioration
    vm_ids = dc[dc["banner"] == "ValuMart"]["customer_id"]
    vm     = df[df["customer_id"].isin(vm_ids) & (df["year"] == 2025)]
    print(f"\nValuMart 2025 baseline_volume by quarter:")
    print(vm.groupby("quarter")["baseline_volume"].sum().to_string())
    print(f"  → Expect Q4 < Q1 (linear decline)")

    print("\n── Validation complete ──────────────────────────────────────────\n")


# ==============================================================================
# VALIDATION — fact_market acceptance criteria
# ==============================================================================

def validate_fact_market():
    """
    Sprint 1 / F-01 acceptance criteria validation for fact_market.
    Run after generate_fact_market() has written the Parquet file.
    """
    path = os.path.join(RAW_DIR, "fact_market.parquet")
    df   = pd.read_parquet(path)
    dp   = pd.read_parquet(os.path.join(RAW_DIR, "dim_product.parquet"))
    dc   = pd.read_parquet(os.path.join(RAW_DIR, "dim_customer.parquet"))

    print("\n── fact_market validation ───────────────────────────────────────")

    # Row count
    print(f"\nRow count : {len(df):,}  (expect ~40K)")

    # Year split
    print(f"\nYear split:")
    print(df["year"].value_counts().sort_index().to_string())

    # FK checks
    brand_miss  = (~df["brand"].isin(dp["brand"])).sum()
    banner_miss = (~df["banner"].isin(dc["banner"])).sum()
    subcat_miss = (~df["sub_category"].isin(dp["sub_category"])).sum()
    print(f"\nFK brand       : {brand_miss} orphans   (expect 0)")
    print(f"FK banner      : {banner_miss} orphans   (expect 0)")
    print(f"FK sub_category: {subcat_miss} orphans   (expect 0)")

    # Critical constraint: brand_volume ≤ category_volume (pre-injection)
    violations = (df["brand_volume_units"] > df["total_category_volume_units"]).sum()
    print(f"\nbrand_vol ≤ category_vol : "
          f"{'PASS ✓' if violations == 0 else f'FAIL — {violations} violations'}")

    # Shelf price > manufacturer net (retailer margin check)
    margin_violations = (
        df["consumer_shelf_price_gbp"] <= df["manufacturer_net_price_gbp"]
    ).sum()
    print(f"shelf_price > mfr_net    : "
          f"{'PASS ✓' if margin_violations == 0 else f'FAIL — {margin_violations} violations'}")

    # Implied retailer margin by banner
    df["_implied_margin"] = (
        (df["consumer_shelf_price_gbp"] - df["manufacturer_net_price_gbp"])
        / df["consumer_shelf_price_gbp"]
    )
    print(f"\nImplied retailer margin by banner (sample):")
    margin_by_banner = (
        df.merge(
            pd.read_parquet(os.path.join(RAW_DIR, "dim_customer.parquet"))
            [["banner", "channel"]].drop_duplicates("banner"),
            on="banner", how="left"
        )
        .groupby("channel")["_implied_margin"]
        .mean()
        .mul(100)
        .round(1)
    )
    print(margin_by_banner.to_string())
    print(f"  → Expect Convenience highest (~28%), Discounter lowest (~17%)")

    # Distribution outlets ≤ total outlets
    dist_violations = (
        df["numeric_distribution_outlets"] > df["total_outlets_in_banner"]
    ).sum()
    print(f"dist_outlets ≤ total_outlets : "
          f"{'PASS ✓' if dist_violations == 0 else f'FAIL — {dist_violations} violations'}")

    # Brand and banner coverage
    print(f"\nUnique brands  : {df['brand'].nunique()}  "
          f"(expect ≤ {dp['brand'].nunique()})")
    print(f"Unique banners : {df['banner'].nunique()}  (expect 15)")
    print(f"Unique weeks   : {df['week_date'].nunique()}  (expect 104)")

    # ── Performance signal verification ──────────────────────────────────────

    # Signal: ValuMart 2025 brand volume deterioration
    vm = df[df["banner"] == "ValuMart"]
    if not vm.empty:
        vm25 = vm[vm["year"] == 2025]
        print(f"\nValuMart 2025 mean brand_volume_units by quarter:")
        print(vm25.groupby("quarter")["brand_volume_units"].mean().round(0).to_string())
        print(f"  → Expect Q4 < Q1 (declining market share)")

    print("\n── Validation complete ──────────────────────────────────────────\n")


if __name__ == "__main__":
    main()
    validate_dim_product()
    validate_dim_customer()
    validate_fact_sales()
    validate_fact_market()