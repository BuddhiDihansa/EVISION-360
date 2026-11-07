"""Clean the World Bank WDI extract into tidy parquet tables (one row per economy-year).

Run from the repo root (after build_country_mapping.py):
    python src/cleaning/clean_worldbank.py

Outputs (data/interim/):
    wb_economic.parquet     economies (countries/territories) x year, 5 indicators as columns
    wb_aggregates.parquet   World Bank aggregates (World, income groups, regions) in the same shape
"""
import warnings
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
RAW_PATH = ROOT / "data/raw/worldbank/wdi_indicators_2010_2025.xlsx"
MAPPING_PATH = ROOT / "data/reference/country_mapping.csv"
OUT_DIR = ROOT / "data/interim"

INDICATORS = {
    "NY.GDP.PCAP.CD": "gdp_per_capita_usd",
    "NY.GDP.MKTP.KD.ZG": "gdp_growth_pct",
    "SP.POP.TOTL": "population",
    "SP.URB.TOTL.IN.ZS": "urban_pop_pct",
    "FP.CPI.TOTL.ZG": "inflation_pct",
}
CORE = ["gdp_per_capita_usd", "population", "urban_pop_pct"]

# World Bank aggregate codes (income groups, regions, lending groups, ...). Everything else is an economy.
AGGREGATE_CODES = set(
    "AFE AFW ARB CEB CSS EAP EAR EAS ECA ECS EMU EUU FCS FCV HIC HPC IBD IBT IDA IDB IDX INX LAC LCN LDC "
    "LIC LMC LMY LTE MEA MIC MNA NAC OED OSS PRE PSS PST SAS SSA SSF SST TEA TEC TLA TMN TSA TSS UMC WLD".split()
)
# Economies that are real but not standard ISO 3166 alpha-3 codes.
NON_ISO_ECONOMIES = {"XKX", "CHI"}  # Kosovo, Channel Islands


def _check_unknown_codes(codes: set[str]) -> None:
    """Optional safety net: warn about non-ISO codes that are not aggregates (new aggregates in a newer file)."""
    try:
        import pycountry
    except ImportError:
        return
    iso = {c.alpha_3 for c in pycountry.countries}
    odd = sorted(c for c in codes if c not in iso and c not in AGGREGATE_CODES and c not in NON_ISO_ECONOMIES)
    if odd:
        warnings.warn(f"Non-ISO World Bank codes treated as economies (new aggregates?): {odd}")


def clean_worldbank(raw: pd.DataFrame, mapping: pd.DataFrame | None = None) -> tuple[dict[str, pd.DataFrame], dict]:
    df = raw[raw["Country Code"].notna()].copy()  # drops the footer/blank rows at the bottom of the extract
    unknown = set(df["Series Code"]) - set(INDICATORS)
    if unknown:
        raise ValueError(f"Unmapped World Bank series: {sorted(unknown)}")
    if df.duplicated(["Country Code", "Series Code"]).any():
        raise ValueError("Duplicate (country, series) rows in World Bank data")

    year_cols = [c for c in df.columns if "[YR" in str(c)]
    long = df.melt(id_vars=["Country Name", "Country Code", "Series Code"], value_vars=year_cols,
                   var_name="year_raw", value_name="value")
    long["year"] = long["year_raw"].str.extract(r"(\d{4})", expand=False).astype("int16")
    long["value"] = pd.to_numeric(long["value"].replace("..", pd.NA), errors="coerce")  # '..' = missing
    long["indicator"] = long["Series Code"].map(INDICATORS)

    # unstack (not pivot_table) so only real economy-year combinations are created.
    wide = (long.set_index(["Country Code", "Country Name", "year", "indicator"])["value"]
            .unstack("indicator").reset_index())
    wide.columns.name = None
    wide = wide.rename(columns={"Country Code": "iso3", "Country Name": "country_name_wb"})
    for col in INDICATORS.values():
        if col not in wide:
            wide[col] = pd.NA
    indicators = list(INDICATORS.values())

    # Hard value checks (inflation is left alone: hyperinflation values such as Zimbabwe 2020 are real).
    if (wide["population"].dropna() <= 0).any():
        raise ValueError("Non-positive population")
    if not wide["urban_pop_pct"].dropna().between(0, 100).all():
        raise ValueError("Urban population share outside 0-100")
    if (wide["gdp_per_capita_usd"].dropna() <= 0).any():
        raise ValueError("Non-positive GDP per capita")

    all_codes = set(wide["iso3"])
    n_before = len(wide)
    wide = wide.dropna(subset=indicators, how="all")  # economy-years with no data at all
    codes_without_data = sorted(all_codes - set(wide["iso3"]))
    wide["has_core_indicators"] = wide[CORE].notna().all(axis=1)

    is_agg = wide["iso3"].isin(AGGREGATE_CODES)
    aggregates = wide[is_agg].rename(columns={"iso3": "region_code", "country_name_wb": "region_name"})
    economies = wide[~is_agg].copy()

    if mapping is not None:
        names = mapping[["iso3", "country_name"]]
        economies = economies.merge(names, on="iso3", how="left")
        economies["country_name"] = economies["country_name"].fillna(economies["country_name_wb"])
        economies["is_ev_country"] = economies["iso3"].isin(set(mapping["iso3"]))
        mapped_in_aggs = set(mapping["iso3"]) & set(aggregates["region_code"])
        if mapped_in_aggs:
            raise ValueError(f"Mapped countries misclassified as aggregates: {sorted(mapped_in_aggs)}")
    _check_unknown_codes(set(economies["iso3"]))

    first = ["iso3", "country_name"] if mapping is not None else ["iso3"]
    economies = economies[first + [c for c in economies.columns if c not in first]].sort_values(["iso3", "year"])

    tables = {"economic": economies.reset_index(drop=True),
              "aggregates": aggregates.sort_values(["region_code", "year"]).reset_index(drop=True)}
    latest = int(economies["year"].max())
    report = {
        "raw_rows": len(raw),
        "footer_rows_dropped": len(raw) - len(df),
        "economies": int(economies["iso3"].nunique()),
        "aggregates": int(aggregates["region_code"].nunique()),
        "economy_year_rows": len(economies),
        "empty_economy_years_dropped": n_before - len(wide),
        "codes_without_any_data": codes_without_data,
        "years": f"{int(economies['year'].min())}-{latest}",
        "core_complete_share_2024": round(float(economies.loc[economies["year"] == 2024, "has_core_indicators"].mean()), 3),
        f"core_complete_share_{latest}": round(float(economies.loc[economies["year"] == latest, "has_core_indicators"].mean()), 3),
    }
    if mapping is not None:
        report["ev_countries_found"] = int(economies.loc[economies["is_ev_country"], "iso3"].nunique())
        report["ev_countries_missing"] = sorted(set(mapping["iso3"]) - set(economies["iso3"]))
    return tables, report


def main():
    raw = pd.read_excel(RAW_PATH, sheet_name="Data")
    mapping = pd.read_csv(MAPPING_PATH)
    tables, report = clean_worldbank(raw, mapping)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, table in tables.items():
        path = OUT_DIR / f"wb_{name}.parquet"
        table.to_parquet(path, index=False)
        print(f"{name:<11} {len(table):>6} rows -> {path.relative_to(ROOT)}")
    print("\nQA report:")
    for k, v in report.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()