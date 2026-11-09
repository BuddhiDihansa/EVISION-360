import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src/transformation"))
sys.path.insert(0, str(ROOT / "src/ingestion"))
import load_analytics as la  # noqa: E402

KEYS = {"NOR": 1, "LKA": 2}


def test_parse_segment():
    assert la.parse_segment("2: Middle adoption") == (2, "Middle adoption")
    with pytest.raises(ValueError):
        la.parse_segment("Middle adoption")


def test_segments_without_year_column_use_the_default_year():
    df = pd.DataFrame({"geo_code": ["NOR"], "segment": ["3: High adoption"], "share": [92.0], "change_pp": [10.0],
                       "gdp_per_capita_usd": [90000.0], "urban_pop_pct": [84.0]})
    out = la.prepare_segments(df, KEYS)
    assert out.loc[0, "year"] == la.DEFAULT_SEGMENT_YEAR and out.loc[0, "segment_number"] == 3
    assert out.loc[0, "segment_label"] == "High adoption" and out.loc[0, "geo_key"] == 1


def test_forecasts_derive_origin_year_and_default_method():
    df = pd.DataFrame({"geo_code": ["NOR"], "year": [2027], "horizon": [2], "last_share": [90.0], "forecast": [95.0],
                       "persistence": [90.0], "typical_error_p80": [5.0], "range_low": [90.0], "range_high": [100.0],
                       "near_saturation": [True]})
    out = la.prepare_forecasts(df, KEYS)
    assert out.loc[0, "origin_year"] == 2025 and out.loc[0, "method"] == "unspecified" and bool(out.loc[0, "near_saturation"])


def test_forecasts_keep_method_and_origin_when_present():
    df = pd.DataFrame({"geo_code": ["NOR"], "year": [2027], "horizon": [2], "last_share": [90.0], "forecast": [95.0],
                       "persistence": [90.0], "typical_error_p80": [5.0], "range_low": [90.0], "range_high": [100.0],
                       "near_saturation": [False], "origin_year": [2025], "method": ["drift3"]})
    out = la.prepare_forecasts(df, KEYS)
    assert out.loc[0, "method"] == "drift3" and out.loc[0, "target_year"] == 2027


def test_readiness_maps_columns_and_allows_missing_adoption():
    df = pd.DataFrame({"year": [2024], "geo_code": ["LKA"], "E": [35.0], "U": [3.0], "core_index": [19.0], "core_percentile": [18.0],
                       "core_rank": [165.0], "rank_p05_any": [135.0], "rank_p95_any": [195.0], "rank_p05_near": [153.0],
                       "rank_p95_near": [183.0], "chargers_per_100k": [None], "C": [None], "ext_index": [None],
                       "ev_share": [None], "gap": [None], "freq_top10_gap": [None]})
    out = la.prepare_readiness(df, KEYS)
    assert out.loc[0, "geo_key"] == 2 and out.loc[0, "core_rank"] == 165 and pd.isna(out.loc[0, "ev_share_pct"])
    assert {"e_percentile", "rank_p05_any_weights", "adoption_gap"} <= set(out.columns)


def test_unknown_country_and_missing_columns_raise():
    df = pd.DataFrame({"geo_code": ["XXX"], "segment": ["1: Low"], "share": [1.0], "change_pp": [0.0],
                       "gdp_per_capita_usd": [1.0], "urban_pop_pct": [1.0]})
    with pytest.raises(ValueError, match="not in dim_geography"):
        la.prepare_segments(df, KEYS)
    with pytest.raises(ValueError, match="missing columns"):
        la.prepare_segments(df.drop(columns="segment"), KEYS)
