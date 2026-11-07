import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src/cleaning"))
from clean_iea import clean_iea  # noqa: E402

MAPPING = pd.DataFrame({
    "iso3": ["NOR", "USA"],
    "country_name": ["Norway", "United States"],
    "iea_name": ["Norway", "USA"],
})


def make_raw(rows):
    base = {"region_country": "Norway", "category": "Historical", "parameter": "EV sales", "mode": "Cars",
            "powertrain": "BEV", "year": 2023, "unit": "Vehicles", "value": 100.0, "Aggregate group": "Other"}
    return pd.DataFrame([{**base, **r} for r in rows])


def test_exact_duplicates_are_removed_and_reported():
    raw = make_raw([{}, {}, {"year": 2024}])
    tables, report = clean_iea(raw, MAPPING)
    assert report["exact_duplicates_removed"] == 1
    assert len(tables["market"]) == 2


def test_conflicting_duplicate_keys_raise():
    raw = make_raw([{"value": 1.0}, {"value": 2.0}])
    with pytest.raises(ValueError, match="Conflicting"):
        clean_iea(raw, MAPPING)


def test_aggregates_are_separated_from_countries():
    raw = make_raw([{}, {"region_country": "World", "Aggregate group": "_World"}])
    tables, _ = clean_iea(raw, MAPPING)
    assert tables["market"]["iso3"].tolist() == ["NOR"]
    assert tables["aggregates"]["region_code"].tolist() == ["world"]


def test_scenarios_and_projection_flag():
    raw = make_raw([{}, {"category": "Projection-STEPS", "year": 2035}, {"category": "Projection-CPS", "year": 2035}])
    m = clean_iea(raw, MAPPING)[0]["market"]
    assert set(m["scenario"]) == {"Historical", "STEPS", "CPS"}
    assert m.loc[m["scenario"] == "Historical", "is_projection"].eq(False).all()


def test_share_above_100_is_flagged_not_changed():
    raw = make_raw([{"parameter": "EV sales share", "unit": "percent", "value": 250.0}])
    m = clean_iea(raw, MAPPING)[0]["market"]
    assert m["is_suspect_value"].iloc[0] and m["value"].iloc[0] == 250.0


def test_prices_are_pivoted_and_missing_country_is_kept_and_flagged():
    raw = make_raw([
        {"parameter": "price_p50_2025USD", "unit": None, "mode": "City car", "value": 20000.0},
        {"parameter": "price_p25_2025USD", "unit": None, "mode": "City car", "value": 15000.0},
        {"region_country": None, "parameter": "price_p50_2025USD", "unit": None, "mode": "City car", "value": 99.0},
    ])
    p = clean_iea(raw, MAPPING)[0]["prices"]
    assert len(p) == 2
    assert {"price_p25", "price_p50"} <= set(p.columns)
    assert p["country_missing"].sum() == 1 and p.loc[p["country_missing"], "iso3"].isna().all()


def test_country_missing_from_mapping_raises():
    with pytest.raises(ValueError, match="missing from country_mapping"):
        clean_iea(make_raw([{"region_country": "Atlantis"}]), MAPPING)


def test_unknown_parameter_raises():
    with pytest.raises(ValueError, match="Unmapped IEA parameters"):
        clean_iea(make_raw([{"parameter": "Teleporters"}]), MAPPING)