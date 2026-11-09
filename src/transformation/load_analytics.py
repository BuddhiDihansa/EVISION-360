"""Load the analysis outputs (segments, forecasts, readiness index) into the PostgreSQL warehouse.

These CSV files are produced by the analysis notebooks, not by the pipeline scripts:
    notebooks/06_machine_learning.ipynb     -> data/processed/country_segments_2024.csv
    notebooks/07_forecasting.ipynb          -> data/processed/ev_share_forecasts_2026_2028.csv
    notebooks/07b_ev_readiness_index.ipynb  -> data/processed/ev_readiness_index_2024.csv
A missing CSV is skipped with a message (run the notebook first). Run after load_warehouse.py:
    python src/transformation/load_analytics.py

The load runs in ONE transaction and rebuilds the analytics tables and their views each time.
"""
import re
import sys
from pathlib import Path

import pandas as pd
from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src/ingestion"))
from db import get_engine  # noqa: E402

PROCESSED = ROOT / "data/processed"
SCHEMA = "evision"
DEFAULT_SEGMENT_YEAR = 2024            # used only when an older segments CSV has no year column
SOURCES = {
    "fact_country_segment": ("country_segments_2024.csv", "06_machine_learning"),
    "fact_ev_share_forecast": ("ev_share_forecasts_2026_2028.csv", "07_forecasting"),
    "fact_readiness_index": ("ev_readiness_index_2024.csv", "07b_ev_readiness_index"),
}


def _require(df: pd.DataFrame, columns: list[str], name: str) -> None:
    missing = [c for c in columns if c not in df.columns]
    if missing:
        raise ValueError(f"{name}: missing columns {missing}. Re-run the notebook that writes this file.")


def _attach_geo_key(df: pd.DataFrame, geo_keys: dict, name: str) -> pd.DataFrame:
    out = df.assign(geo_key=df["geo_code"].map(geo_keys))
    unknown = sorted(out.loc[out["geo_key"].isna(), "geo_code"].unique())
    if unknown:
        raise ValueError(f"{name}: geo_code values not in dim_geography: {unknown}")
    out["geo_key"] = out["geo_key"].astype(int)
    return out


def parse_segment(label: str) -> tuple[int, str]:
    """'2: Middle adoption' -> (2, 'Middle adoption')."""
    m = re.match(r"^\s*(\d+)\s*:\s*(.+?)\s*$", str(label))
    if not m:
        raise ValueError(f"Unexpected segment label: {label!r}")
    return int(m.group(1)), m.group(2)


def prepare_segments(df: pd.DataFrame, geo_keys: dict) -> pd.DataFrame:
    _require(df, ["geo_code", "segment", "share", "change_pp", "gdp_per_capita_usd", "urban_pop_pct"], "segments")
    out = _attach_geo_key(df, geo_keys, "segments")
    if "year" not in out:
        out["year"] = DEFAULT_SEGMENT_YEAR
    parsed = out["segment"].map(parse_segment)
    out["segment_number"] = [p[0] for p in parsed]
    out["segment_label"] = [p[1] for p in parsed]
    out = out.rename(columns={"share": "ev_share_pct", "change_pp": "share_change_pp_3y"})
    return out[["geo_key", "year", "segment_number", "segment_label", "ev_share_pct", "share_change_pp_3y",
                "gdp_per_capita_usd", "urban_pop_pct"]]


def prepare_forecasts(df: pd.DataFrame, geo_keys: dict) -> pd.DataFrame:
    _require(df, ["geo_code", "year", "horizon", "last_share", "forecast", "persistence", "typical_error_p80",
                  "range_low", "range_high", "near_saturation"], "forecasts")
    out = _attach_geo_key(df, geo_keys, "forecasts")
    out["target_year"] = out["year"].astype(int)
    out["origin_year"] = out["origin_year"].astype(int) if "origin_year" in out else out["target_year"] - out["horizon"]
    if "method" not in out:
        out["method"] = "unspecified"
    out = out.rename(columns={"last_share": "last_share_pct", "forecast": "forecast_pct", "persistence": "persistence_pct",
                              "typical_error_p80": "typical_error_p80_pp", "range_low": "range_low_pct", "range_high": "range_high_pct"})
    out["near_saturation"] = out["near_saturation"].astype(bool)
    return out[["geo_key", "origin_year", "target_year", "horizon", "method", "last_share_pct", "forecast_pct",
                "persistence_pct", "typical_error_p80_pp", "range_low_pct", "range_high_pct", "near_saturation"]]


def prepare_readiness(df: pd.DataFrame, geo_keys: dict) -> pd.DataFrame:
    _require(df, ["year", "geo_code", "E", "U", "core_index", "core_percentile", "core_rank", "rank_p05_any", "rank_p95_any",
                  "rank_p05_near", "rank_p95_near", "chargers_per_100k", "C", "ext_index", "ev_share", "gap", "freq_top10_gap"], "readiness")
    out = _attach_geo_key(df, geo_keys, "readiness")
    out = out.rename(columns={"E": "e_percentile", "U": "u_percentile", "C": "c_percentile", "rank_p05_any": "rank_p05_any_weights",
                              "rank_p95_any": "rank_p95_any_weights", "rank_p05_near": "rank_p05_near_equal",
                              "rank_p95_near": "rank_p95_near_equal", "ev_share": "ev_share_pct", "gap": "adoption_gap"})
    out["core_rank"] = out["core_rank"].astype("Int64")
    return out[["geo_key", "year", "e_percentile", "u_percentile", "core_index", "core_percentile", "core_rank",
                "rank_p05_any_weights", "rank_p95_any_weights", "rank_p05_near_equal", "rank_p95_near_equal",
                "chargers_per_100k", "c_percentile", "ext_index", "ev_share_pct", "adoption_gap", "freq_top10_gap"]]


PREPARE = {"fact_country_segment": prepare_segments, "fact_ev_share_forecast": prepare_forecasts,
           "fact_readiness_index": prepare_readiness}


def main() -> None:
    engine = get_engine()
    with engine.connect() as conn:
        geo_keys = dict(conn.execute(text(f"SELECT geo_code, geo_key FROM {SCHEMA}.dim_geography")).fetchall())
    if not geo_keys:
        sys.exit("dim_geography is empty. Run load_warehouse.py first.")

    tables, skipped = {}, []
    for table, (csv, notebook) in SOURCES.items():
        path = PROCESSED / csv
        if not path.exists():
            skipped.append(f"{table}: {csv} not found (run notebooks/{notebook}.ipynb)")
            continue
        tables[table] = PREPARE[table](pd.read_csv(path), geo_keys)

    with engine.begin() as conn:                                  # single transaction
        conn.exec_driver_sql((ROOT / "database/analytics_tables.sql").read_text(encoding="utf-8"))
        conn.exec_driver_sql(f"SET search_path TO {SCHEMA}")
        print("Analytics tables:")
        for table, df in tables.items():
            df.to_sql(table, conn, schema=SCHEMA, if_exists="append", index=False, chunksize=1000, method="multi")
            print(f"  {table:<26} {len(df):>5} rows")
        if len(tables) == len(SOURCES):
            conn.exec_driver_sql((ROOT / "database/analytics_views.sql").read_text(encoding="utf-8"))
            print("  views: v_ev_share_forecast, v_country_analytics")
        else:
            print("  analytics views NOT created (they need all three tables)")

    for line in skipped:
        print("SKIPPED", line)
    with engine.connect() as conn:
        print("\nVerification (rows in PostgreSQL vs loaded):")
        ok = True
        for table, df in tables.items():
            n = conn.execute(text(f"SELECT COUNT(*) FROM {SCHEMA}.{table}")).scalar()
            ok &= n == len(df)
            print(f"  {table:<26} {n:>5}  {'OK' if n == len(df) else 'MISMATCH'}")
    if not ok:
        sys.exit("ROW COUNT MISMATCH")
    print("\nAll counts match." if tables else "\nNothing loaded.")


if __name__ == "__main__":
    main()
