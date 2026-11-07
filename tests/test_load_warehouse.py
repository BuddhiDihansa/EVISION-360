import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src/transformation"))
sys.path.insert(0, str(ROOT / "src/cleaning"))
sys.path.insert(0, str(ROOT / "src/ingestion"))
import load_warehouse as lw  # noqa: E402


def test_shared_aggregate_codes():
    assert lw.ember_region_code("World") == "WLD" and lw.ember_region_code("EU") == "EUU"
    assert lw.iea_aggregate_code("world") == "WLD"
    assert lw.iea_aggregate_code("european_union") == "EUU"
    assert lw.iea_aggregate_code("asia_pacific") == "IEA_ASIA_PACIFIC"
    with pytest.raises(KeyError):
        lw.ember_region_code("Mars")


def test_assign_keys_is_deterministic_and_starts_at_one():
    df = pd.DataFrame({"code": ["b", "a", "c"]})
    out = lw.assign_keys(df, ["code"], "k")
    assert out["k"].tolist() == [1, 2, 3] and out["code"].tolist() == ["a", "b", "c"]


def _tables():
    ember_cols = {"iso3": ["NOR"], "continent": ["Europe"], "ember_region": ["Europe"], "is_eu": [False],
                  "is_oecd": [True], "is_g20": [False], "is_g7": [False], "is_asean": [False]}
    return {
        "mapping": pd.DataFrame({"iso3": ["NOR"], "country_name": ["Norway"], "in_ember": [True],
                                 "in_iea": [True], "in_worldbank": [True]}),
        "wb_economic": pd.DataFrame({"iso3": ["NOR", "LKA"], "country_name": ["Norway", "Sri Lanka"]}),
        "ember_monthly": pd.DataFrame(ember_cols),
        "ember_quarterly": pd.DataFrame(ember_cols).iloc[0:0],
        "ember_regions": pd.DataFrame({"area_raw": ["World", "EU"]}),
        "wb_aggregates": pd.DataFrame({"region_code": ["WLD", "HIC"], "region_name": ["World", "High income"]}),
        "iea_aggregates": pd.DataFrame({"region_code": ["world", "europe"], "region_country": ["World", "Europe"]}),
    }


def test_dim_geography_merges_sources_and_flags_ev_data():
    geo = lw.build_dim_geography(_tables()).set_index("geo_code")
    assert geo["geo_key"].is_unique
    assert geo.loc["LKA", "geo_type"] == "country" and not geo.loc["LKA", "has_ev_data"]   # World Bank only
    assert geo.loc["NOR", "has_ev_data"]
    # World appears once although all three sources list it, with the World Bank name and all three flags.
    assert (geo.index == "WLD").sum() == 1
    assert geo.loc["WLD", ["in_ember", "in_iea", "in_worldbank"]].all()
    assert geo.loc["EUU", "geo_type"] == "aggregate" and geo.loc["IEA_EUROPE", "in_iea"]
    assert geo.loc["HIC", "in_worldbank"] and not geo.loc["HIC", "in_iea"]


def test_insert_rejects_unresolved_foreign_keys():
    df = pd.DataFrame({"geo_key": [1, None], "value": [1.0, 2.0]})
    with pytest.raises(ValueError, match="unresolved foreign key"):
        lw.insert(None, "fact_test", df)