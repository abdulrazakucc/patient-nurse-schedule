"""
The browser engine and the Python backend must give identical answers.

Runs frontend/engine.js in a JavaScript runtime -- Node.js, or JavaScriptCore
through osascript on macOS -- and compares its acuity classifications, unit
schedules and rosters with the Python implementation, value for value.
"""
from __future__ import annotations

import json
import random
import shutil
import subprocess
from pathlib import Path

import pytest

from app.acuity_tool import FINDINGS, classify
from app.nursing import build_roster, schedule_unit

FRONTEND = Path(__file__).resolve().parent.parent / "frontend"
RUNNER = "node" if shutil.which("node") else "osascript" if shutil.which("osascript") else None

pytestmark = pytest.mark.skipif(RUNNER is None, reason="needs Node.js or macOS osascript")

CENSUS = [
    {"weight_g": 620, "ga_weeks": 24, "condition": "critical", "resp_support": "ventilator"},
    {"weight_g": 1150, "ga_weeks": 29, "condition": "guarded", "resp_support": "nasal_cannula"},
    {"weight_g": 1300, "ga_weeks": 30, "findings": ["respiratory.intensive.0", "loc.38"]},
    {"weight_g": 900, "ga_weeks": 27, "findings": ["one-to-one"]},
    {"weight_g": 1500, "ga_weeks": 33, "findings": ["lines.continuing_low.0"]},
    {"weight_g": 1000, "ga_weeks": 28, "findings": ["bogus"]},
]
AVAILABLE = {1: 1, 2: 1, 3: 2, 4: 1}


def _cases() -> list[list[str]]:
    ids = sorted(FINDINGS)
    rng = random.Random(7)
    return (
        [[i] for i in ids]
        + [rng.sample(ids, rng.randint(2, 6)) for _ in range(400)]
        + [[], ["bogus"], ["loc.3", "bili.21"], ["bili.18"]]
    )


def _run_engine(tmp_path: Path, cases: list[list[str]]) -> dict:
    program = "var window = {};\n" + "\n".join(
        (FRONTEND / name).read_text()
        for name in ("data/neostay-data.js", "data/neostay-acuity.js", "engine.js")
    )
    program += f"""
var E = window.NeoEngine;
var s = E.scheduleUnit({json.dumps(CENSUS)}, 2);
var result = JSON.stringify({{
  classify: {json.dumps(cases)}.map(function (c) {{ return E.classifyAcuity(c); }}),
  schedule: s,
  roster: E.buildRoster(s.infants, {json.dumps(AVAILABLE)}, 2)
}});
"""
    script = tmp_path / "parity.js"
    if RUNNER == "node":
        script.write_text(program + "console.log(result);\n")
        command = ["node", str(script)]
    else:
        script.write_text(program + "result;\n")
        command = ["osascript", "-l", "JavaScript", str(script)]
    completed = subprocess.run(command, capture_output=True, text=True, timeout=120)
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def _differences(a, b, path="") -> list[tuple]:
    if isinstance(a, bool) or isinstance(b, bool):
        return [] if a is b else [(path, a, b)]
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return [] if abs(a - b) <= 1e-9 else [(path, a, b)]
    if isinstance(a, dict) and isinstance(b, dict):
        found = []
        for key in set(a) | set(b):
            if key not in a or key not in b:
                found.append((f"{path}.{key}", a.get(key, "<missing>"), b.get(key, "<missing>")))
            else:
                found += _differences(a[key], b[key], f"{path}.{key}")
        return found
    if isinstance(a, list) and isinstance(b, list):
        found = [] if len(a) == len(b) else [(path, f"len {len(a)}", f"len {len(b)}")]
        for index, (x, y) in enumerate(zip(a, b)):
            found += _differences(x, y, f"{path}[{index}]")
        return found
    return [] if a == b else [(path, a, b)]


def test_browser_and_python_engines_agree(tmp_path) -> None:
    cases = _cases()
    schedule = schedule_unit(CENSUS, 2)
    expected = json.loads(
        json.dumps(
            {
                "classify": [classify(c) for c in cases],
                "schedule": schedule,
                "roster": build_roster(schedule["infants"], AVAILABLE, 2),
            }
        )
    )
    differences = _differences(expected, _run_engine(tmp_path, cases))
    assert differences == [], differences[:10]
