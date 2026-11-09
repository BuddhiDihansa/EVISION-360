"""Load the cleaned parquet tables into the PostgreSQL warehouse (schema "evision").

Prerequisites (run from the repo root):
    python src/transformation/build_country_mapping.py
    python src/cleaning/clean_ember.py
    python src/cleaning/clean_iea.py
    python src/cleaning/clean_worldbank.py
Then:
    python src/transformation/load_warehouse.py

The whole load runs in ONE transaction: either everything loads or nothing changes.
Re-running wipes and rebuilds the schema (database/schema.sql drops it first).
"""
import sys
from pathlib import Path

import pandas as pd
from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src/cleaning"))
sys.path.insert(0, str(ROOT / "src/ingestion"))
from clean_ember import DRIVETRAINS  # noqa: E402
from clean_iea import CHARGING, MARKET  # noqa: E402
from db import get_engine  # noqa: E402

INTERIM = ROOT / "data/interim"
SQL_FILES = ["schema.sql", "dimensions.sql", "fact_tables.sql", "views.sql"]
SCHEMA = "evision"

# Codes shared across sources so World / EU are one row in dim_geography.
EMBER_REGION_CODES = {"World": "WLD", "EU": "EUU"}
IEA_AGG_CODE_OVERRIDES = {"world": "WLD", "european_union": "EUU"}
SCENARIO_ROWS = [
    ("Historical", "Historical (observed)", False, "Observed data"),
    ("STEPS", "Stated Policies Scenario", True, "IEA projection scenario"),
    ("CPS", "Current Policies Scenario", True, "IEA projection scenario"),
]


# ---------- pure helpers (unit tested) ----------
def ember_region_code(area: str) -> str:
    if area not in EMBER_REGION_CODES:
        raise KeyError(f"Unknown Ember region: {area!r}")
    return EMBER_REGION_CODES[area]


def iea_aggregate_code(region_code: str) -> str:
    return IEA_AGG_CODE_OVERRIDES.get(region_code, f"IEA_{region_code.upper()}")


def assign_keys(df: pd.DataFrame, sort_cols: list[str], key_name: str) -> pd.DataFrame:
    """Deterministic surrogate keys 1..n in sorted order."""
    out = df.sort_values(sort_cols).reset_index(drop=True)
    out.insert(0, key_name, range(1, len(out) + 1))
    return out


# ---------- read ----------
def read_interim() -> dict[str, pd.DataFrame]:
    names = ["ember_monthly", "ember_quarterly", "ember_regions", "iea_market", "iea_charging",
             "iea_other", "iea_prices", "iea_aggregates", "wb_economic", "wb_aggregates"]
    missing = [n for n in names if not (INTERIM / f"{n}.parquet").exists()]
    if missing:
        raise FileNotFoundError(f"Missing {missing} in data/interim/. Run the cleaning scripts first (see docstring).")
    t = {n: pd.read_parquet(INTERIM / f"{n}.parquet") for n in names}
    t["mapping"] = pd.read_csv(ROOT / "data/reference/country_mapping.csv")
    return t


# ---------- dimensions ----------
def build_dim_geography(t: dict[str, pd.DataFrame]) -> pd.DataFrame:
    mapping, wb_e = t["mapping"], t["wb_economic"]
    flag_cols = ["is_eu", "is_oecd", "is_g20", "is_g7", "is_asean"]

    # Countries: mapping (Ember + IEA) plus World Bank economies not in the mapping (e.g. Sri Lanka).
    base = mapping[["iso3", "country_name", "in_ember", "in_iea", "in_worldbank"]]
    wb_only = (wb_e[~wb_e["iso3"].isin(mapping["iso3"])].drop_duplicates("iso3")[["iso3", "country_name"]]
               .assign(in_ember=False, in_iea=False, in_worldbank=True))
    countries = pd.concat([base, wb_only], ignore_index=True)
    ember_rows = pd.concat([t["ember_monthly"], t["ember_quarterly"]])
    attrs = ember_rows.groupby("iso3")[["continent", "ember_region"] + flag_cols].first().reset_index()
    countries = countries.merge(attrs, on="iso3", how="left")
    countries = countries.rename(columns={"country_name": "geo_name"}).assign(
        geo_code=lambda d: d["iso3"], geo_type="country")

    # Aggregates: World Bank names win, then IEA, then Ember.
    wb_agg = t["wb_aggregates"].drop_duplicates("region_code")[["region_code", "region_name"]]
    wb_agg.columns = ["geo_code", "geo_name"]
    iea_agg = t["iea_aggregates"].drop_duplicates("region_code")[["region_code", "region_country"]]
    iea_agg = pd.DataFrame({"geo_code": iea_agg["region_code"].map(iea_aggregate_code),
                            "geo_name": iea_agg["region_country"]})
    ember_agg = pd.DataFrame({"geo_code": [ember_region_code(a) for a in t["ember_regions"]["area_raw"].unique()]})
    ember_agg["geo_name"] = ember_agg["geo_code"]
    aggs = pd.concat([wb_agg, iea_agg, ember_agg]).drop_duplicates("geo_code", keep="first").reset_index(drop=True)
    aggs["geo_type"] = "aggregate"
    aggs["iso3"] = None
    aggs["in_worldbank"] = aggs["geo_code"].isin(wb_agg["geo_code"])
    aggs["in_iea"] = aggs["geo_code"].isin(iea_agg["geo_code"])
    aggs["in_ember"] = aggs["geo_code"].isin(ember_agg["geo_code"])

    geo = pd.concat([countries, aggs], ignore_index=True)
    geo["has_ev_data"] = geo["in_ember"] | geo["in_iea"]
    for col in flag_cols:
        geo[col] = geo[col].astype("boolean")
    geo["_order"] = geo["geo_type"].map({"country": 0, "aggregate": 1})
    geo = assign_keys(geo, ["_order", "geo_code"], "geo_key").drop(columns="_order")
    return geo[["geo_key", "geo_code", "geo_name", "geo_type", "iso3", "continent", "ember_region"] + flag_cols
               + ["in_ember", "in_iea", "in_worldbank", "has_ev_data"]]


def build_dim_year(t, latest_observed: int) -> pd.DataFrame:
    years = pd.concat([t["ember_monthly"]["year"], t["iea_market"]["year"], t["iea_prices"]["year"],
                       t["iea_charging"]["year"], t["iea_other"]["year"], t["iea_aggregates"]["year"],
                       t["wb_economic"]["year"]]).astype(int)
    out = pd.DataFrame({"year": range(int(years.min()), int(years.max()) + 1)})
    out["decade"] = out["year"] // 10 * 10
    out["is_partial_year"] = out["year"] == latest_observed
    out["is_projection_year"] = out["year"] > latest_observed
    return out


def build_dim_date(t) -> pd.DataFrame:
    m = t["ember_monthly"]
    last_complete = m.loc[m["is_complete_period"], "date"].max()
    start, end = m["date"].min(), pd.Timestamp(year=int(m["year"].max()), month=12, day=1)
    d = pd.DataFrame({"month_start": pd.date_range(start, end, freq="MS")})
    d["year"] = d["month_start"].dt.year
    d["quarter"] = d["month_start"].dt.quarter
    d["month"] = d["month_start"].dt.month
    d["month_name"] = d["month_start"].dt.month_name()
    d["year_month"] = d["month_start"].dt.strftime("%Y-%m")
    d["is_complete_period"] = d["month_start"] <= last_complete
    d["month_start"] = d["month_start"].dt.date
    return d


def build_dim_drivetrain() -> pd.DataFrame:
    rows = [(code, raw, group, group == "Aggregate") for raw, (code, group) in DRIVETRAINS.items()]
    d = pd.DataFrame(rows, columns=["drivetrain_code", "drivetrain_name", "drivetrain_group", "is_aggregate"])
    return assign_keys(d, ["drivetrain_code"], "drivetrain_key")


def build_iea_long(t) -> pd.DataFrame:
    """All IEA annual rows (countries + aggregates) with a geo_code and an indicator category."""
    cols = ["scenario", "parameter", "mode", "powertrain", "unit", "year", "value", "is_suspect_value"]
    countries = pd.concat([t["iea_market"], t["iea_charging"], t["iea_other"]])
    countries = countries.assign(geo_code=countries["iso3"])[["geo_code"] + cols]
    agg = t["iea_aggregates"]
    agg = agg.assign(geo_code=agg["region_code"].map(iea_aggregate_code))[["geo_code"] + cols]
    long = pd.concat([countries, agg], ignore_index=True)
    for c in ("mode", "powertrain", "unit"):
        long[c] = long[c].fillna("n/a")
    long["category"] = long["parameter"].map(
        lambda p: "market" if p in MARKET else "charging" if p in CHARGING else "energy")
    return long


def build_dim_indicator(long: pd.DataFrame) -> pd.DataFrame:
    d = long[["category", "parameter", "mode", "powertrain", "unit"]].drop_duplicates()
    d.columns = ["indicator_category", "parameter_code", "vehicle_mode", "powertrain", "unit"]
    return assign_keys(d, ["indicator_category", "parameter_code", "vehicle_mode", "powertrain", "unit"], "indicator_key")


# ---------- facts ----------
def build_fact_sales_monthly(t, geo_keys, dr_keys) -> pd.DataFrame:
    m, r = t["ember_monthly"], t["ember_regions"].copy()
    if not (r["frequency"] == "Monthly").all():
        raise ValueError("Ember region rows are not all monthly")
    last_complete = m.loc[m["is_complete_period"], "date"].max()
    r["iso3"] = r["area_raw"].map(ember_region_code)          # region 'iso3' = shared geo_code
    r["is_complete_period"] = r["date"] <= last_complete
    f = pd.concat([m, r], ignore_index=True)
    f["geo_key"] = f["iso3"].map(geo_keys)
    f["drivetrain_key"] = f["drivetrain"].map(dr_keys)
    f["month_start"] = f["date"].dt.date
    cols = ["geo_key", "month_start", "drivetrain_key", "registrations", "share_pct", "yoy_change", "yoy_change_pct",
            "ytd_registrations", "ytd_share_pct", "roll3m_registrations", "roll3m_share_pct",
            "roll12m_registrations", "roll12m_share_pct", "is_partial_year", "is_complete_period"]
    return f[cols]


def build_fact_sales_quarterly(t, geo_keys, dr_keys) -> pd.DataFrame:
    q = t["ember_quarterly"]
    f = q.assign(geo_key=q["iso3"].map(geo_keys), drivetrain_key=q["drivetrain"].map(dr_keys),
                 period_date=q["date"].dt.date)
    cols = ["geo_key", "period_date", "drivetrain_key", "registrations", "share_pct", "yoy_change", "yoy_change_pct",
            "ytd_registrations", "ytd_share_pct", "roll12m_registrations", "roll12m_share_pct", "is_partial_year"]
    return f[cols]


def build_fact_iea(long, category, geo_keys, scen_keys, ind_keys) -> pd.DataFrame:
    f = long[long["category"] == category].copy()
    f["geo_key"] = f["geo_code"].map(geo_keys)
    f["scenario_key"] = f["scenario"].map(scen_keys)
    idx = f[["category", "parameter", "mode", "powertrain", "unit"]].apply(tuple, axis=1)
    f["indicator_key"] = idx.map(ind_keys)
    return f[["geo_key", "year", "scenario_key", "indicator_key", "value", "is_suspect_value"]]


def build_fact_prices(t, geo_keys) -> pd.DataFrame:
    p = t["iea_prices"]
    f = p.assign(geo_key=p["iso3"].map(geo_keys), vehicle_mode=p["mode"], year=p["year"].astype(int))
    f = f.sort_values(["vehicle_mode", "powertrain", "year", "geo_key"]).reset_index(drop=True)
    f.insert(0, "price_key", range(1, len(f) + 1))
    return f[["price_key", "geo_key", "country_missing", "vehicle_mode", "powertrain", "year", "price_p0", "price_p25",
              "price_p50", "price_p75", "price_p95", "price_p100", "price_mean", "currency"]]


def build_fact_economic(t, geo_keys) -> pd.DataFrame:
    e = t["wb_economic"].assign(geo_code=lambda d: d["iso3"])
    a = t["wb_aggregates"].assign(geo_code=lambda d: d["region_code"])
    f = pd.concat([e, a], ignore_index=True)
    f["geo_key"] = f["geo_code"].map(geo_keys)
    f["population"] = f["population"].round().astype("Int64")
    f["year"] = f["year"].astype(int)
    return f[["geo_key", "year", "gdp_per_capita_usd", "gdp_growth_pct", "population", "urban_pop_pct",
              "inflation_pct", "has_core_indicators"]]


# ---------- load ----------
def insert(conn, name: str, df: pd.DataFrame) -> None:
    """Insert a DataFrame; every *_key column must be resolved (only vehicle prices may lack a geo_key)."""
    for key in [c for c in df.columns if c.endswith("_key")]:
        if name == "fact_vehicle_prices" and key == "geo_key":
            continue  # rows the IEA file gives no country for
        if df[key].isna().any():
            raise ValueError(f"{name}: unresolved foreign key in column {key}")
    df.to_sql(name, conn, schema=SCHEMA, if_exists="append", index=False, chunksize=2000, method="multi")
    print(f"  {name:<30} {len(df):>7} rows")


def main():
    t = read_interim()
    latest_observed = int(t["ember_monthly"]["year"].max())

    geo = build_dim_geography(t)
    dim_year = build_dim_year(t, latest_observed)
    dim_date = build_dim_date(t)
    dim_dr = build_dim_drivetrain()
    scen = pd.DataFrame(SCENARIO_ROWS, columns=["scenario_code", "scenario_name", "is_projection", "description"])
    scen.insert(0, "scenario_key", range(1, len(scen) + 1))
    iea_long = build_iea_long(t)
    dim_ind = build_dim_indicator(iea_long)

    geo_keys = dict(zip(geo["geo_code"], geo["geo_key"]))
    dr_keys = dict(zip(dim_dr["drivetrain_code"], dim_dr["drivetrain_key"]))
    scen_keys = dict(zip(scen["scenario_code"], scen["scenario_key"]))
    ind_keys = {(r.indicator_category, r.parameter_code, r.vehicle_mode, r.powertrain, r.unit): r.indicator_key
                for r in dim_ind.itertuples()}

    facts = {
        "fact_ev_sales_monthly": build_fact_sales_monthly(t, geo_keys, dr_keys),
        "fact_ev_sales_quarterly": build_fact_sales_quarterly(t, geo_keys, dr_keys),
        "fact_ev_market_annual": build_fact_iea(iea_long, "market", geo_keys, scen_keys, ind_keys),
        "fact_charging_infrastructure": build_fact_iea(iea_long, "charging", geo_keys, scen_keys, ind_keys),
        "fact_ev_energy_annual": build_fact_iea(iea_long, "energy", geo_keys, scen_keys, ind_keys),
        "fact_vehicle_prices": build_fact_prices(t, geo_keys),
        "fact_economic_indicators": build_fact_economic(t, geo_keys),
    }
    dims = {"dim_year": dim_year, "dim_date": dim_date, "dim_scenario": scen, "dim_drivetrain": dim_dr,
            "dim_indicator": dim_ind, "dim_geography": geo}

    engine = get_engine()
    with engine.begin() as conn:  # single transaction
        for f in SQL_FILES:
            conn.exec_driver_sql((ROOT / "database" / f).read_text(encoding="utf-8"))
        conn.exec_driver_sql(f"SET search_path TO {SCHEMA}")
        print("Dimensions:")
        for name, df in dims.items():
            insert(conn, name, df)
        print("Facts:")
        for name, df in facts.items():
            insert(conn, name, df)

    verify(engine, {**dims, **facts})


def verify(engine, tables: dict[str, pd.DataFrame]) -> None:
    """Compare row counts in PostgreSQL with what was loaded."""
    print("\nVerification (rows in PostgreSQL vs loaded):")
    ok = True
    with engine.connect() as conn:
        for name, df in tables.items():
            n = conn.execute(text(f"SELECT COUNT(*) FROM {SCHEMA}.{name}")).scalar()
            flag = "OK" if n == len(df) else "MISMATCH"
            ok &= n == len(df)
            print(f"  {name:<30} {n:>7}  {flag}")
    print("\nAll counts match." if ok else "\nROW COUNT MISMATCH - investigate before using the warehouse.")
    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
