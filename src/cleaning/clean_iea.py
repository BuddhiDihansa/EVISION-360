"""Clean the IEA Global EV Outlook data (sheet GEVO_EV_2026) into tidy parquet tables.

Run from the repo root (after build_country_mapping.py):
    python src/cleaning/clean_iea.py

Outputs (data/interim/):
    iea_market.parquet      country rows: EV sales, EV stock, sales share, stock share
    iea_charging.parquet    country rows: charging points, EVs per charging point, capacity per EVSE
    iea_other.parquet       country rows: electricity demand, battery deployment, oil displacement, capacity per EV
    iea_prices.parquet      vehicle price percentiles (wide), 20 countries + rows with no country label
    iea_aggregates.parquet  aggregate regions (World, EU, Europe, ...) for every non-price parameter
"""
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
RAW_PATH = ROOT / "data/raw/iea/EV data by country 2026.xlsx"
MAPPING_PATH = ROOT / "data/reference/country_mapping.csv"
OUT_DIR = ROOT / "data/interim"

# Rows in these groups are aggregates (World, EU, regions), not countries.
AGG_GROUPS = {"_World", "European Union", "Other_aggregate", "Projection_region"}

PARAMETER_CODES = {
    "EV sales": "ev_sales",
    "EV stock": "ev_stock",
    "EV sales share": "ev_sales_share",
    "EV stock share": "ev_stock_share",
    "EV charging points": "charging_points",
    "Electric LDVs per charging point": "ev_per_charging_point",
    "Average capacity per EVSE": "avg_capacity_per_evse",
    "Average capacity per EV": "avg_capacity_per_ev",
    "Electricity demand": "electricity_demand",
    "Battery deployment": "battery_deployment",
    "Oil displacement Mlge": "oil_displacement_mlge",
    "Oil displacement, Mbd": "oil_displacement_mbd",
    "price_p0_2025USD": "price_p0",
    "price_p25_2025USD": "price_p25",
    "price_p50_2025USD": "price_p50",
    "price_p75_2025USD": "price_p75",
    "price_p95_2025USD": "price_p95",
    "price_p100_2025USD": "price_p100",
    "price_mean_2025USD": "price_mean",
}
MARKET = {"ev_sales", "ev_stock", "ev_sales_share", "ev_stock_share"}
CHARGING = {"charging_points", "ev_per_charging_point", "avg_capacity_per_evse"}
SCENARIOS = {"Historical": "Historical", "Projection-STEPS": "STEPS", "Projection-CPS": "CPS"}
KEY = ["region_country", "scenario", "parameter", "mode", "powertrain", "year"]
UNASSIGNED = "UNASSIGNED"


def _slug(name: str) -> str:
    return name.lower().replace(" excl. ", "_excl_").replace(" ", "_").replace(".", "")


def clean_iea(raw: pd.DataFrame, mapping: pd.DataFrame) -> tuple[dict[str, pd.DataFrame], dict]:
    n_raw = len(raw)
    df = raw.drop_duplicates().copy()  # exact duplicate rows only (15 in the 2026 file)
    n_dupes = n_raw - len(df)

    unknown = set(df["parameter"]) - set(PARAMETER_CODES)
    if unknown:
        raise ValueError(f"Unmapped IEA parameters: {sorted(unknown)}")
    unknown_cat = set(df["category"]) - set(SCENARIOS)
    if unknown_cat:
        raise ValueError(f"Unmapped IEA categories: {sorted(unknown_cat)}")

    df["parameter"] = df["parameter"].map(PARAMETER_CODES)
    df["scenario"] = df["category"].map(SCENARIOS)
    df["is_projection"] = df["scenario"] != "Historical"
    df["year"] = df["year"].astype("int16")
    df = df.rename(columns={"Aggregate group": "aggregate_group"}).drop(columns="category")

    if df.duplicated(KEY).any():
        raise ValueError("Conflicting duplicate keys in IEA data (same key, different value)")
    if (df["value"] < 0).any():
        raise ValueError("Negative values found in IEA data")

    is_price = df["parameter"].str.startswith("price_")
    is_agg = df["aggregate_group"].isin(AGG_GROUPS)
    if (df.loc[~is_price, "region_country"].isna()).any():
        raise ValueError("Non-price IEA rows without a region/country label")

    # Values above 100% in a share column are impossible -> flag (kept, not edited).
    df["is_suspect_value"] = (df["unit"] == "percent") & (df["value"] > 100)

    # Country identity via the reference mapping (IEA name -> ISO3).
    iea_map = mapping.dropna(subset=["iea_name"])[["iea_name", "iso3", "country_name"]]
    df = df.merge(iea_map, left_on="region_country", right_on="iea_name", how="left").drop(columns="iea_name")
    countries_named = df["region_country"].notna() & ~is_agg.values
    missing = df.loc[countries_named & df["iso3"].isna(), "region_country"].unique()
    if len(missing):
        raise ValueError(f"IEA countries missing from country_mapping.csv: {list(missing)}")
    df["region_code"] = df["region_country"].where(is_agg.values).map(lambda v: _slug(v) if isinstance(v, str) else None)
    is_price = df["parameter"].str.startswith("price_")
    is_agg = df["aggregate_group"].isin(AGG_GROUPS)

    cols = ["iso3", "country_name", "region_code", "region_country", "aggregate_group", "scenario",
            "is_projection", "parameter", "mode", "powertrain", "unit", "year", "value", "is_suspect_value"]

    aggregates = df[is_agg & ~is_price][cols]
    countries = df[~is_agg & ~is_price & df["iso3"].notna()]
    market = countries[countries["parameter"].isin(MARKET)][cols]
    charging = countries[countries["parameter"].isin(CHARGING)][cols]
    other = countries[~countries["parameter"].isin(MARKET | CHARGING)][cols]

    # Prices: wide format (one column per percentile). Rows with no country label are kept and flagged.
    p = df[is_price].copy()
    p["country_missing"] = p["iso3"].isna()
    p["iso3"] = p["iso3"].fillna(UNASSIGNED)
    p["country_name"] = p["country_name"].fillna(UNASSIGNED)
    prices = (
        p.pivot_table(index=["iso3", "country_name", "country_missing", "mode", "powertrain", "year"],
                      columns="parameter", values="value", aggfunc="first")
        .reset_index()
    )
    prices.columns.name = None
    prices.loc[prices["country_missing"], ["iso3", "country_name"]] = None
    prices["currency"] = "USD (2025 prices)"

    tables = {"market": market, "charging": charging, "other": other, "prices": prices, "aggregates": aggregates}
    tables = {k: v.reset_index(drop=True) for k, v in tables.items()}
    n_price_rows = int(is_price.sum())
    report = {
        "raw_rows": n_raw,
        "exact_duplicates_removed": n_dupes,
        "rows_after_dedupe": len(df),
        "price_rows_long": n_price_rows,
        "price_rows_without_country": int(p["country_missing"].sum()),
        "countries_in_market": int(market["iso3"].nunique()),
        "aggregates": int(aggregates["region_code"].nunique()),
        "suspect_share_rows": int(df["is_suspect_value"].sum()),
        "non_price_rows_accounted": len(market) + len(charging) + len(other) + len(aggregates),
        "non_price_rows_expected": int((~is_price).sum()),
    }
    if report["non_price_rows_accounted"] != report["non_price_rows_expected"]:
        raise ValueError(f"Row accounting mismatch: {report}")
    return tables, report


def main():
    raw = pd.read_excel(RAW_PATH, sheet_name="GEVO_EV_2026")
    mapping = pd.read_csv(MAPPING_PATH)
    tables, report = clean_iea(raw, mapping)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, table in tables.items():
        path = OUT_DIR / f"iea_{name}.parquet"
        table.to_parquet(path, index=False)
        print(f"{name:<11} {len(table):>6} rows -> {path.relative_to(ROOT)}")
    print("\nQA report:")
    for k, v in report.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()