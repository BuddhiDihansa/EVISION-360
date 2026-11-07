import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src/cleaning"))
from clean_worldbank import clean_worldbank  # noqa: E402

MAPPING = pd.DataFrame({"iso3": ["NOR", "TWN"], "country_name": ["Norway", "Taiwan (China)"]})
SERIES = ["NY.GDP.PCAP.CD", "NY.GDP.MKTP.KD.ZG", "SP.POP.TOTL", "SP.URB.TOTL.IN.ZS", "FP.CPI.TOTL.ZG"]


def make_raw(countries):
    """countries: {code: {series_code: (v2023, v2024)}}; missing series are filled with '..'."""
    rows = []
    for code, vals in countries.items():
        for s in SERIES:
            a, b = vals.get(s, ("..", ".."))
            rows.append({"Country Name": f"Name {code}", "Country Code": code, "Series Name": s,
                         "Series Code": s, "2023 [YR2023]": a, "2024 [YR2024]": b})
    footer = [{"Country Name": "Data from database: WDI"}, {"Country Name": "Last Updated: 10/08/2026"}]
    return pd.concat([pd.DataFrame(rows), pd.DataFrame(footer)], ignore_index=True)


FULL = {"NY.GDP.PCAP.CD": (80000, 90000), "SP.POP.TOTL": (5_400_000, 5_500_000), "SP.URB.TOTL.IN.ZS": (83.0, 83.5)}


def test_footer_rows_dropped_and_missing_markers_become_nan():
    raw = make_raw({"NOR": FULL})
    tables, report = clean_worldbank(raw, MAPPING)
    assert report["footer_rows_dropped"] == 2
    e = tables["economic"]
    assert e["inflation_pct"].isna().all()          # '..' -> NaN
    assert e.loc[e["year"] == 2024, "gdp_per_capita_usd"].iloc[0] == 90000
    assert str(e["year"].dtype) == "int16"


def test_aggregates_are_separated_from_economies():
    raw = make_raw({"NOR": FULL, "WLD": FULL, "HIC": FULL})
    tables, _ = clean_worldbank(raw, MAPPING)
    assert tables["economic"]["iso3"].unique().tolist() == ["NOR"]
    assert sorted(tables["aggregates"]["region_code"].unique()) == ["HIC", "WLD"]


def test_economy_years_without_any_data_are_dropped():
    raw = make_raw({"NOR": FULL, "INX": {}})
    tables, report = clean_worldbank(raw, MAPPING)
    assert report["codes_without_any_data"] == ["INX"]
    assert len(tables["aggregates"]) == 0


@pytest.mark.filterwarnings("ignore:Non-ISO")
def test_core_indicator_flag_and_ev_country_flag():
    partial = {"NY.GDP.PCAP.CD": (1000, "..")}
    raw = make_raw({"NOR": FULL, "XYZ": partial})
    e = clean_worldbank(raw, MAPPING)[0]["economic"]
    assert e[e["iso3"] == "NOR"]["has_core_indicators"].all()
    assert not e[e["iso3"] == "XYZ"]["has_core_indicators"].any()
    assert e.set_index("iso3").loc["NOR", "is_ev_country"].all()
    assert not e.set_index("iso3").loc["XYZ", "is_ev_country"].any()


def test_mapping_country_missing_from_file_is_reported():
    _, report = clean_worldbank(make_raw({"NOR": FULL}), MAPPING)
    assert report["ev_countries_missing"] == ["TWN"]


def test_urban_share_over_100_raises():
    bad = {**FULL, "SP.URB.TOTL.IN.ZS": (120.0, 83.5)}
    with pytest.raises(ValueError, match="Urban"):
        clean_worldbank(make_raw({"NOR": bad}), MAPPING)


def test_unknown_series_raises():
    raw = make_raw({"NOR": FULL})
    raw.loc[0, "Series Code"] = "XX.UNKNOWN"
    with pytest.raises(ValueError, match="Unmapped World Bank series"):
        clean_worldbank(raw, MAPPING)