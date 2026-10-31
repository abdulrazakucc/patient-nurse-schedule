"""
The browser journey engine and the Python runtime must give the same answers.

Runs frontend/journey-engine.js in a JavaScript runtime -- Node.js, or
JavaScriptCore through osascript on macOS -- on every bundle in
tests/fixtures/journey/ (fitted to made-up data), and compares each prediction
with backend/app/journey_runtime.py, value for value. The engine must also pass
each bundle's own check cases, and refuse the input the runtime refuses.
"""
from __future__ import annotations

import json
import random
import shutil
import subprocess
from pathlib import Path

import pytest

from app import journey_runtime as runtime

FRONTEND = Path(__file__).resolve().parent.parent / "frontend"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "journey"
BUNDLES = sorted(FIXTURES.glob("journey-*.json"))
RUNNER = "node" if shutil.which("node") else "osascript" if shutil.which("osascript") else None

pytestmark = pytest.mark.skipif(RUNNER is None, reason="needs Node.js or macOS osascript")


def _cases(bundle: dict, n: int = 60) -> list[dict]:
    """Inputs built from the bundle's own value lists, with a few that must be refused."""
    t = bundle["inputs"]
    rng = random.Random(3)
    resp = [k for k, v in t["resp_status"].items() if v["tier"] is not None]

    def entry():
        return {
            "acuity_ratio": rng.choice(t["acuity_ratios"] + [None]),
            "dol": float(rng.randint(0, 90)),
            "weight_g": rng.choice([None, float(rng.randint(700, 4000))]),
            "resp_status": rng.choice(resp + [None]),
            "resp_flow_lpm": rng.choice([None, float(rng.randint(1, 8))]),
            "feeds": rng.choice(list(t["feeds"]) + [None]),
            "iv_lines": sorted(set(rng.sample(t["iv"]["tokens"], rng.randint(0, 2)))),
            "iv_fluids": rng.random() < 0.3,
            "spells": rng.choice(list(t["spells"])),
            "nas_band": rng.choice(t["nas_band"] + [None]),
            "procedure": rng.choice(t["procedure"] + [None]),
            "care_area": rng.choice(t["care_area"]),
            "has_education_need": rng.random() < 0.2,
        }

    out = []
    for _ in range(n):
        stay = rng.randint(0, 40)
        record = entry() | {"ga_weeks": float(rng.randint(23, 41)), "bw_g": float(rng.randint(500, 4200)),
                            "shifts_in_unit": stay, "shift": rng.choice(["AM", "PM"]),
                            "day_of_week": rng.choice(list(runtime.DAY_NAMES))}
        ago = sorted(rng.sample(range(1, 15), rng.randint(0, 8)))
        out.append({"record": record, "history": [entry() | {"shifts_ago": k} for k in ago if k <= stay]})
    good = out[0]["record"]
    out += [
        {"record": good | {"acuity_ratio": "1:9"}, "history": []},
        {"record": good | {"weight_g": 20.0}, "history": []},
        {"record": good | {"shifts_in_unit": 1}, "history": [{"shifts_ago": 2}]},
        {"record": good | {"iv_lines": ["NOPE"]}, "history": []},
    ]
    return out


def _python(bundle: dict, cases: list[dict]) -> list:
    out = []
    for c in cases:
        try:
            out.append(runtime.predict(bundle, c["record"], c["history"]))
        except runtime.InputError:
            out.append("input-error")
    return out


def _engine(tmp_path: Path, bundle: dict, cases: list[dict]) -> dict:
    program = "var window = {};\n" + (FRONTEND / "journey-engine.js").read_text()
    program += f"""
var J = window.NeoJourney;
var bundle = {json.dumps(bundle)};
var checks = J.selfCheck(bundle);
var results = {json.dumps(cases)}.map(function (c) {{
  try {{ return J.predict(bundle, c.record, c.history); }}
  catch (e) {{ if (e.kind === "input") return "input-error"; throw e; }}
}});
var result = JSON.stringify({{checks: checks, results: results}});
"""
    script = tmp_path / "journey.js"
    if RUNNER == "node":
        script.write_text(program + "console.log(result);\n")
        command = ["node", str(script)]
    else:
        script.write_text(program + "result;\n")
        command = ["osascript", "-l", "JavaScript", str(script)]
    completed = subprocess.run(command, capture_output=True, text=True, timeout=300)
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def _differences(a, b, path="") -> list[tuple]:
    if a is None or b is None or isinstance(a, (str, bool)) or isinstance(b, (str, bool)):
        return [] if a == b else [(path, a, b)]
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return [] if abs(a - b) <= 1e-9 else [(path, a, b)]
    if isinstance(a, dict) and isinstance(b, dict):
        if set(a) != set(b):
            return [(path, sorted(a), sorted(b))]
        return [d for k in a for d in _differences(a[k], b[k], f"{path}.{k}")]
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return [(path, len(a), len(b))]
        return [d for i, (x, y) in enumerate(zip(a, b)) for d in _differences(x, y, f"{path}[{i}]")]
    return [(path, a, b)]


@pytest.mark.parametrize("bundle_path", BUNDLES, ids=[p.stem for p in BUNDLES])
def test_engine_matches_runtime(tmp_path, bundle_path):
    bundle = json.loads(bundle_path.read_text())
    cases = _cases(bundle)
    js = _engine(tmp_path, bundle, cases)
    assert js["checks"] == len(bundle["checks"]) > 0
    py = _python(bundle, cases)
    assert py.count("input-error") == 4, "the last four cases are invalid"
    differences = _differences(py, js["results"])
    assert not differences, differences[:5]
