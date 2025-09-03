import pytest
from time_utils import normalise_time, normalise_time_for_bio_entry

def test_exact_date_normalisation():
    raw = {"label_type": "date", "date_value": "2020-05-10", "confidence": 100}
    out = normalise_time(raw)
    assert out["kind"] == "date"
    assert out["start_iso"] == "2020-05-10"
    assert out["end_iso"] == "2020-05-10"
    assert out["precision"] == "exact"

def test_life_stage_approx_with_dob():
    raw = {"label_type": "life_stage", "subvalue": "teens", "confidence": 80}
    out = normalise_time(raw, dob_iso="2000-01-01")
    assert out["kind"] == "life_stage"
    assert out["precision"] in {"approx", "estimated"}
    assert out["start_iso"] and out["end_iso"]

def test_decade_bucket_no_dob():
    raw = {"label_type": "decade", "subvalue": "1990s", "confidence": 70}
    out = normalise_time(raw)
    assert out["kind"] == "decade"
    assert out["start_iso"] == "1990-01-01"
    assert out["end_iso"] == "1999-12-31"

def test_unknown_falls_back_gracefully():
    raw = {"label_type": "something_new", "confidence": 20}
    out = normalise_time(raw)
    assert "start_iso" in out and "end_iso" in out  # shape is stable

def test_bio_entry_helper_uses_bio_dates():
    bio = {"dob": "1980-02-02"}
    raw = {"label_type": "life_stage", "subvalue": "twenties", "confidence": 90}
    out = normalise_time_for_bio_entry(raw, biography=bio)
    assert out["start_iso"] and out["end_iso"]