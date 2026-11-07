"""Build data/reference/country_mapping.csv (country name -> ISO3) from the raw sources.

Run from the repo root:
    python src/transformation/build_country_mapping.py
"""
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
EMBER_PATH = ROOT / "data/raw/ember/monthly_ev_sales.csv"
IEA_PATH = ROOT / "data/raw/iea/EV data by country 2026.xlsx"
WB_PATH = ROOT / "data/raw/worldbank/wdi_indicators_2010_2025.xlsx"
OUT_PATH = ROOT / "data/reference/country_mapping.csv"

# IEA rows in these groups are aggregates (World, EU, regions), not countries.
IEA_AGG_GROUPS = {"_World", "European Union", "Other_aggregate", "Projection_region"}

# IEA names that differ from Ember's spelling -> resolved through Ember's ISO3.
IEA_TO_EMBER_NAME = {
    "USA": "United States",
    "Korea": "South Korea",
    "Turkiye": "Türkiye",
    "Czech Republic": "Czechia",
}

# IEA-only countries (not in Ember): ISO3 assigned manually, checked against World Bank names.
IEA_ONLY_ISO3 = {
    "Argentina": "ARG",
    "Cambodia": "KHM",
    "Costa Rica": "CRI",
    "Jordan": "JOR",
    "Lao PDR": "LAO",
    "Philippines": "PHL",
    "Russia": "RUS",
    "Seychelles": "SYC",
    "United Arab Emirates": "ARE",
    "Uzbekistan": "UZB",
}


def load_sources():
    ember = pd.read_csv(EMBER_PATH)
    iea = pd.read_excel(IEA_PATH, sheet_name="GEVO_EV_2026")
    wb = pd.read_excel(WB_PATH, sheet_name="Data")
    return ember, iea, wb[wb["Country Code"].notna()]


def build_mapping():
    ember, iea, wb = load_sources()

    # 1. Ember: country rows carry an ISO3 code already.
    e = (
        ember[ember["ISO 3 code"].notna()]
        .drop_duplicates("ISO 3 code")[["ISO 3 code", "Area"]]
        .rename(columns={"ISO 3 code": "iso3", "Area": "ember_name"})
    )

    # 2. IEA countries (aggregates removed).
    names = iea.dropna(subset=["region_country"]).drop_duplicates("region_country")
    iea_countries = names.loc[~names["Aggregate group"].isin(IEA_AGG_GROUPS), "region_country"]
    ember_iso = dict(zip(e["ember_name"], e["iso3"]))

    rows = []
    for name in iea_countries:
        if name in IEA_ONLY_ISO3:
            iso3 = IEA_ONLY_ISO3[name]
        else:
            iso3 = ember_iso.get(IEA_TO_EMBER_NAME.get(name, name))
        if iso3 is None:
            raise ValueError(f"No ISO3 for IEA country: {name}")
        rows.append({"iso3": iso3, "iea_name": name})
    i = pd.DataFrame(rows)

    # 3. Combine on ISO3.
    m = e.merge(i, on="iso3", how="outer")
    m["country_name"] = m["ember_name"].fillna(m["iea_name"])
    wb_codes = set(wb["Country Code"])
    m["in_ember"] = m["ember_name"].notna()
    m["in_iea"] = m["iea_name"].notna()
    m["in_worldbank"] = m["iso3"].isin(wb_codes)
    m = m[["iso3", "country_name", "ember_name", "iea_name", "in_ember", "in_iea", "in_worldbank"]]
    return m.sort_values("iso3").reset_index(drop=True), wb


def validate(m, wb):
    assert m["iso3"].is_unique, "duplicate ISO3 codes"
    assert m["iso3"].str.fullmatch(r"[A-Z]{3}").all(), "malformed ISO3"
    # Sanity check for manually assigned codes: print the World Bank name for each.
    wb_names = dict(zip(wb["Country Code"], wb["Country Name"]))
    print("Manual ISO3 check (IEA name -> World Bank name):")
    for name, iso3 in IEA_ONLY_ISO3.items():
        print(f"  {name:<22} {iso3} -> {wb_names.get(iso3)}")
    print("\nNot in World Bank:", m.loc[~m["in_worldbank"], "country_name"].tolist())


if __name__ == "__main__":
    mapping, wb = build_mapping()
    validate(mapping, wb)
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    mapping.to_csv(OUT_PATH, index=False, encoding="utf-8")
    print(f"\nWrote {len(mapping)} countries -> {OUT_PATH.relative_to(ROOT)}")
    print(mapping[["in_ember", "in_iea", "in_worldbank"]].sum().to_string())