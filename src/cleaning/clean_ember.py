"""Clean the raw Ember monthly EV sales file and write tidy parquet tables.

Run from the repo root (after build_country_mapping.py):
    python src/cleaning/clean_ember.py

Outputs (data/interim/):
    ember_monthly.parquet    country-level monthly rows (the main fact source)
    ember_quarterly.parquet  countries reported quarterly only (Canada, South Africa)
    ember_regions.parquet    region aggregates (EU, World), kept apart from countries
"""
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
RAW_PATH = ROOT / "data/raw/ember/monthly_ev_sales.csv"
MAPPING_PATH = ROOT / "data/reference/country_mapping.csv"
OUT_DIR = ROOT / "data/interim"

# A month counts as "complete" when at least this share of countries have reported it.
COMPLETE_MONTH_THRESHOLD = 0.90

COLUMN_MAP = {
    "Area": "area_raw",
    "ISO 3 code": "iso3",
    "Area type": "area_type",
    "Date": "date",
    "Data frequency": "frequency",
    "Drivetrain": "drivetrain_raw",
    "Is aggregate drivetrain": "is_aggregate_drivetrain",
    "Registrations": "registrations",
    "Registrations YoY change": "yoy_change",
    "Registrations YoY change (%)": "yoy_change_pct",
    "Share of registrations (%)": "share_pct",
    "Year-to-date registrations": "ytd_registrations",
    "Year-to-date share of registrations (%)": "ytd_share_pct",
    "Rolling 3-month registrations": "roll3m_registrations",
    "Rolling 3-month share of registrations (%)": "roll3m_share_pct",
    "Rolling 12-month registrations": "roll12m_registrations",
    "Rolling 12-month share of registrations (%)": "roll12m_share_pct",
    "Continent": "continent",
    "Ember region": "ember_region",
    "EU member": "is_eu",
    "OECD member": "is_oecd",
    "G20 member": "is_g20",
    "G7 member": "is_g7",
    "ASEAN member": "is_asean",
}

# raw drivetrain name -> (code, group)
DRIVETRAINS = {
    "Battery electric": ("BEV", "EV"),
    "Plug-in hybrid": ("PHEV", "EV"),
    "Hybrid": ("HEV", "Hybrid"),
    "Petrol": ("PETROL", "ICE"),
    "Diesel": ("DIESEL", "ICE"),
    "Ethanol/petrol blend": ("ETHANOL_BLEND", "ICE"),
    "Combustion (unspecified)": ("ICE_OTHER", "ICE"),
    "Other": ("OTHER", "Other"),
    "Electric vehicle (BEV+PHEV)": ("EV_TOTAL", "Aggregate"),
    "All drivetrains": ("ALL", "Aggregate"),
}

BOOL_COLS = ["is_eu", "is_oecd", "is_g20", "is_g7", "is_asean"]
KEY = ["iso3", "date", "drivetrain"]


def _standardise(raw: pd.DataFrame) -> pd.DataFrame:
    df = raw.rename(columns=COLUMN_MAP)
    unknown = set(df["drivetrain_raw"]) - set(DRIVETRAINS)
    if unknown:
        raise ValueError(f"Unmapped drivetrain values: {sorted(unknown)}")

    df["date"] = pd.to_datetime(df["date"], format="%Y-%m-%d")
    df["year"] = df["date"].dt.year.astype("int16")
    df["month"] = df["date"].dt.month.astype("int8")
    df["drivetrain"] = df["drivetrain_raw"].map(lambda v: DRIVETRAINS[v][0])
    df["drivetrain_group"] = df["drivetrain_raw"].map(lambda v: DRIVETRAINS[v][1])
    for col in ("registrations", "ytd_registrations", "roll3m_registrations", "roll12m_registrations"):
        df[col] = pd.to_numeric(df[col], errors="coerce").round().astype("Int64")
    for col in BOOL_COLS:
        df[col] = df[col].astype("boolean")
    # Year is partial when it is the latest year in the file (2026 stops before December).
    df["is_partial_year"] = df["year"] == df["year"].max()
    return df


def clean_ember(raw: pd.DataFrame, mapping: pd.DataFrame | None = None) -> dict[str, pd.DataFrame]:
    """Split raw Ember data into monthly / quarterly / region tables."""
    df = _standardise(raw)

    regions = df[df["area_type"] == "Region"].copy()
    countries = df[df["area_type"] != "Region"].copy()
    quarterly = countries[countries["frequency"] == "Quarterly"].copy()
    monthly = countries[countries["frequency"] == "Monthly"].copy()

    if mapping is not None:
        names = mapping[["iso3", "country_name"]]
        monthly = monthly.merge(names, on="iso3", how="left")
        quarterly = quarterly.merge(names, on="iso3", how="left")
        missing = monthly.loc[monthly["country_name"].isna(), "iso3"].unique()
        if len(missing):
            raise ValueError(f"ISO3 codes missing from country_mapping.csv: {list(missing)}")

    # A month is complete when enough countries have reported it (latest months lag behind).
    n_countries = monthly["iso3"].nunique()
    coverage = monthly.groupby("date")["iso3"].nunique() / n_countries
    last_complete = coverage[coverage >= COMPLETE_MONTH_THRESHOLD].index.max()
    monthly["is_complete_period"] = monthly["date"] <= last_complete

    return {
        "monthly": monthly.reset_index(drop=True),
        "quarterly": quarterly.reset_index(drop=True),
        "regions": regions.reset_index(drop=True),
    }


def validate_monthly(monthly: pd.DataFrame) -> dict:
    """Hard checks raise; soft checks are returned as metrics for the QA report."""
    if monthly.duplicated(KEY).any():
        raise ValueError("Duplicate (iso3, date, drivetrain) keys in monthly table")
    if (monthly["registrations"].dropna() < 0).any():
        raise ValueError("Negative registrations found")
    if monthly["share_pct"].dropna().gt(100.01).any():
        raise ValueError("Share above 100% found")

    wide = monthly.pivot_table(index=["iso3", "date"], columns="drivetrain", values="registrations", aggfunc="sum")
    ev = wide[["BEV", "PHEV", "EV_TOTAL"]].dropna()
    ev_mismatch = int(((ev["EV_TOTAL"] - ev["BEV"] - ev["PHEV"]).abs() > 0.5).sum())
    return {
        "rows": len(monthly),
        "countries": monthly["iso3"].nunique(),
        "date_min": monthly["date"].min().date().isoformat(),
        "date_max": monthly["date"].max().date().isoformat(),
        "last_complete_month": monthly.loc[monthly["is_complete_period"], "date"].max().date().isoformat(),
        "ev_total_vs_bev_plus_phev_mismatches": ev_mismatch,
        "rows_missing_registrations": int(monthly["registrations"].isna().sum()),
    }


def main():
    raw = pd.read_csv(RAW_PATH)
    mapping = pd.read_csv(MAPPING_PATH)
    tables = clean_ember(raw, mapping)
    report = validate_monthly(tables["monthly"])

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, table in tables.items():
        path = OUT_DIR / f"ember_{name}.parquet"
        table.to_parquet(path, index=False)
        print(f"{name:<10} {len(table):>6} rows -> {path.relative_to(ROOT)}")
    print("\nQA report:")
    for k, v in report.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()