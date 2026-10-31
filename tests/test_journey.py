"""
The patient-journey routes, with model bundles fitted to made-up data.

The bundles in tests/fixtures/journey/ come from ``python -m acuity_ml.testbundle``
(acuity-models): they have the structure of a real bundle but hold no hospital
data and predict nothing meaningful.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from app import config

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "journey"
BUNDLES = sorted(FIXTURES.glob("journey-*.json"))

RECORD = {
    "ga_weeks": 29.5, "bw_g": 1250.0, "dol": 12.0, "weight_g": 1380.0, "shifts_in_unit": 24,
    "shift": "AM", "day_of_week": "Wednesday", "acuity_ratio": "1:2", "resp_status": "CPAP",
    "feeds": "OG/NG-advancing", "iv_lines": ["PICC"], "spells": "self_resolved", "care_area": "icu",
}
HISTORY = [{"shifts_ago": 1, "acuity_ratio": "1:2", "resp_status": "CPAP"},
           {"shifts_ago": 2, "acuity_ratio": "1:2-3", "weight_g": 1350.0}]


@pytest.fixture()
def installed(tmp_path, monkeypatch):
    """Install a bundle as the server's model file; returns a function taking a fixture path."""
    target = tmp_path / "models" / "neostay-journey.json"
    target.parent.mkdir()
    monkeypatch.setattr(config, "MODEL_FILE", target)

    def install(source: Path) -> dict:
        shutil.copy(source, target)
        return json.loads(target.read_text())

    return install


def test_without_a_model_the_routes_answer_503(client, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "MODEL_FILE", tmp_path / "missing.json")
    assert client.get("/api/journey/model").status_code == 503
    r = client.post("/api/journey", json={"record": RECORD})
    assert r.status_code == 503
    assert "No journey model" in r.json()["detail"]


@pytest.mark.parametrize("bundle_path", BUNDLES, ids=[p.stem for p in BUNDLES])
def test_journey_of_one_baby(client, installed, bundle_path):
    bundle = installed(bundle_path)
    r = client.post("/api/journey", json={"record": RECORD, "history": HISTORY})
    assert r.status_code == 200, r.text
    out = r.json()
    survival = out["remaining_stay"]["survival"]
    assert len(survival) == bundle["models"]["remaining_stay"]["horizon"]
    assert all(0 <= s <= 1 for s in survival)
    assert all(b <= a + 1e-12 for a, b in zip(survival, survival[1:]))
    for step in out["acuity_journey"]:
        assert sum(step["ratio_if_in_unit"].values()) == pytest.approx(1.0)
        assert sum(step["ratio"].values()) == pytest.approx(step["p_in_unit"])
        assert step["expected_nurses"]["min"] <= step["expected_nurses"]["max"] + 1e-12
    assert out["model_version"] == bundle["version"]


def test_model_card_leaves_out_parameters(client, installed):
    installed(BUNDLES[0])
    card = client.get("/api/journey/model").json()
    assert "models" not in card and "checks" not in card
    assert card["model_types"]["remaining_stay"]
    assert "acuity_ratios" in card["inputs"]


@pytest.mark.parametrize("change", [
    {"acuity_ratio": "1:5"}, {"resp_status": "oxygen"}, {"ga_weeks": 15.0}, {"shift": "night"},
    {"shifts_in_unit": -2}, {"iv_lines": "PICC"}, {"unknown_field": 1},
])
def test_unreadable_input_is_422(client, installed, change):
    installed(BUNDLES[0])
    r = client.post("/api/journey", json={"record": {**RECORD, **change}})
    assert r.status_code == 422


def test_history_longer_than_the_window_is_refused(client, installed):
    installed(BUNDLES[0])
    history = [{"shifts_ago": k} for k in range(1, 16)]
    assert client.post("/api/journey", json={"record": RECORD, "history": history}).status_code == 422


def test_unit_sums_the_babies(client, installed):
    installed(BUNDLES[0])
    one = client.post("/api/journey", json={"record": RECORD, "history": HISTORY}).json()
    other = {**RECORD, "acuity_ratio": "1:3-4", "resp_status": "RA", "shifts_in_unit": 3}
    two = client.post("/api/journey", json={"record": other}).json()
    unit = client.post("/api/journey/unit", json={"babies": [{"record": RECORD, "history": HISTORY},
                                                             {"record": other}]}).json()
    assert unit["babies"] == 2
    first = unit["shifts"][0]
    assert first["expected_census"] == pytest.approx(one["acuity_journey"][0]["p_in_unit"]
                                                     + two["acuity_journey"][0]["p_in_unit"])
    assert first["expected_nurses"]["max"] == pytest.approx(one["acuity_journey"][0]["expected_nurses"]["max"]
                                                            + two["acuity_journey"][0]["expected_nurses"]["max"])


def test_a_bundle_that_fails_its_checks_is_refused(client, installed, tmp_path):
    bundle = json.loads(BUNDLES[0].read_text())
    bundle["checks"][0]["expected"]["remaining_stay"]["survival"][0] += 0.01
    broken = tmp_path / "broken.json"
    broken.write_text(json.dumps(bundle))
    installed(broken)
    r = client.get("/api/journey/model")
    assert r.status_code == 503
    assert "refused" in r.json()["detail"]
    # Replacing the file with a good bundle takes effect without a restart.
    installed(BUNDLES[0])
    assert client.get("/api/journey/model").status_code == 200


def test_journey_routes_need_sign_in(tmp_path, monkeypatch):
    """With sign-in on, the journey API is closed to anonymous callers like the rest."""
    from fastapi.testclient import TestClient

    from app import main

    monkeypatch.setattr(config, "AUTH_MODE", "password")
    monkeypatch.setattr(config, "MODEL_FILE", tmp_path / "missing.json")
    with TestClient(main.create_app()) as anonymous:
        assert anonymous.post("/api/journey", json={"record": RECORD}).status_code == 401
        assert anonymous.get("/api/journey/bundle").status_code == 401
