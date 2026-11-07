import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src/cleaning"))
from clean_ember import COLUMN_MAP, clean_ember, validate_monthly  # noqa: E402

INV = {v: k for k, v in COLUMN_MAP.items()}
MAPPING = pd.DataFrame({"iso3": ["NOR", "CAN"], "country_name": ["Norway", "Canada"]})


def make_raw(rows):
    base = {
        "Area": "Norway", "ISO 3 code": "NOR", "Area type": "Country or economy",
        "Date": "2025-01-01", "Data frequency": "Monthly", "Drivetrain": "Battery electric",
        "Is aggregate drivetrain": False, "Registrations": 10.0,
        "Registrations YoY change": None, "Registrations YoY change (%)": None,
        "Share of registrations (%)": 50.0, "Year-to-date registrations": 10,
        "Year-to-date share of registrations (%)": 50.0,
        "Rolling 3-month registrations": None, "Rolling 3-month share of registrations (%)": None,
        "Rolling 12-month registrations": None, "Rolling 12-month share of registrations (%)": None,
        "Continent": "Europe", "Ember region": "Europe",
        "EU member": False, "OECD member": True, "G20 member": False, "G7 member": False, "ASEAN member": False,
    }
    return pd.DataFrame([{**base, **r} for r in rows])


def test_regions_and_quarterly_are_split_from_monthly():
    raw = make_raw([
        {},
        {"Area": "World", "ISO 3 code": None, "Area type": "Region"},
        {"Area": "Canada", "ISO 3 code": "CAN", "Data frequency": "Quarterly", "Date": "2025-03-01"},
    ])
    out = clean_ember(raw, MAPPING)
    assert len(out["monthly"]) == 1 and out["monthly"]["iso3"].iloc[0] == "NOR"
    assert len(out["regions"]) == 1 and len(out["quarterly"]) == 1


def test_drivetrain_codes_groups_and_aggregate_flag():
    raw = make_raw([
        {"Drivetrain": "Battery electric"},
        {"Drivetrain": "Electric vehicle (BEV+PHEV)", "Is aggregate drivetrain": True},
        {"Drivetrain": "Petrol"},
    ])
    m = clean_ember(raw, MAPPING)["monthly"].set_index("drivetrain")
    assert m.loc["BEV", "drivetrain_group"] == "EV"
    assert m.loc["EV_TOTAL", "drivetrain_group"] == "Aggregate" and m.loc["EV_TOTAL", "is_aggregate_drivetrain"]
    assert m.loc["PETROL", "drivetrain_group"] == "ICE"


def test_unknown_drivetrain_raises():
    with pytest.raises(ValueError, match="Unmapped drivetrain"):
        clean_ember(make_raw([{"Drivetrain": "Steam"}]), MAPPING)


def test_unmapped_iso3_raises():
    with pytest.raises(ValueError, match="country_mapping"):
        clean_ember(make_raw([{"Area": "Atlantis", "ISO 3 code": "ATL"}]), MAPPING)


def test_partial_year_flag_marks_latest_year_only():
    raw = make_raw([{"Date": "2024-06-01"}, {"Date": "2025-01-01"}])
    m = clean_ember(raw, MAPPING)["monthly"].sort_values("date")
    assert m["is_partial_year"].tolist() == [False, True]


def test_duplicate_keys_fail_validation():
    raw = make_raw([{}, {}])
    monthly = clean_ember(raw, MAPPING)["monthly"]
    with pytest.raises(ValueError, match="Duplicate"):
        validate_monthly(monthly)