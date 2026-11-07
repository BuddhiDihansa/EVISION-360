from pathlib import Path

import pandas as pd
import pytest

MAPPING = Path(__file__).resolve().parents[1] / "data/reference/country_mapping.csv"


@pytest.fixture(scope="module")
def mapping():
    return pd.read_csv(MAPPING)


def test_iso3_unique_and_well_formed(mapping):
    assert mapping["iso3"].is_unique
    assert mapping["iso3"].str.fullmatch(r"[A-Z]{3}").all()


def test_expected_source_coverage(mapping):
    assert mapping["in_ember"].sum() == 59
    assert mapping["in_iea"].sum() == 62


@pytest.mark.parametrize(
    "iso3, iea_name",
    [("USA", "USA"), ("KOR", "Korea"), ("TUR", "Turkiye"), ("CZE", "Czech Republic"), ("RUS", "Russia")],
)
def test_iea_name_variants_resolve(mapping, iso3, iea_name):
    row = mapping[mapping["iso3"] == iso3].iloc[0]
    assert row["iea_name"] == iea_name


def test_known_gaps(mapping):
    assert mapping.loc[~mapping["in_worldbank"], "iso3"].tolist() == ["TWN"]
    assert "LKA" not in set(mapping["iso3"])  # Sri Lanka has no EV data in Ember/IEA