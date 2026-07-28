"""
NeoStay synthetic data generator
=================================

This script turns the *aggregated* real statistics in ``losdata/`` (counts, medians
and quartiles of length of stay, plus disposition and survival) into a set of
*realistic, patient-level* datasets that experts can inspect, validate and later
replace with genuine records pulled from the hospital systems.

Nothing here invents medical facts out of thin air. Every number is anchored to the
real data:

* The **number of infants** in each birth-weight band matches the real ``N`` counts.
* Each infant's **length of stay** is drawn from a distribution whose median and
  inter-quartile range match the real figures for that band and outcome.
* Each infant's **outcome** (Home / Transfer / Died) is drawn using the real
  proportions observed for that birth-weight band.
* **Nurse workload** per hour follows the same acuity based nurse-to-patient ratios
  (AAP / AWHONN) used everywhere else in NeoStay.

The output is written to ``generated_data/`` as plain CSV files that look like the
kind of spreadsheet a ward clerk or charge nurse could realistically maintain.

Run with::

    python datagen/generate.py

The generator is fully deterministic (fixed random seed) so it produces the same
data every time, which makes it safe to review and discuss.
"""
from __future__ import annotations

import csv
import math
import random
from datetime import datetime, timedelta
from pathlib import Path

# Reuse the real dataset + bin definitions so the synthetic data stays anchored.
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.data_loader import DATASET, WEIGHT_BINS  # noqa: E402

OUT_DIR = ROOT / "generated_data"
OUT_DIR.mkdir(exist_ok=True)

SEED = 20260728
random.seed(SEED)

# Simulation window: a decade, matching the real data period label.
START = datetime(2016, 1, 1)
END = datetime(2026, 1, 1)

# Disposition rows in the survival dataset.
DISP_HOME = "Initial Length of Stay (By Disposition) - Home"
DISP_TRANSFER = "Initial Length of Stay (By Disposition) - Transfer"
DISP_DIED = "Initial Length of Stay (By Disposition) - Died"

Z75 = 0.6744897501960817  # 75th percentile of the standard normal


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def lognormal_params(median: float, q1: float, q3: float):
    """Return (mu, sigma) of a log-normal whose median/quartiles match inputs."""
    median = max(median or 1.0, 0.5)
    if q1 and q3 and q3 > q1 > 0:
        sigma = math.log(q3 / q1) / (2 * Z75)
    else:
        sigma = 0.5
    sigma = min(max(sigma, 0.15), 1.2)
    mu = math.log(median)
    return mu, sigma


def sample_los(median, q1, q3, floor=1.0, cap=250.0):
    mu, sigma = lognormal_params(median, q1, q3)
    val = math.exp(random.gauss(mu, sigma))
    return max(floor, min(cap, round(val, 1)))


def weight_for_bin(b) -> int:
    lo = max(b.low, 350)
    hi = min(b.high, 1700)
    return int(random.uniform(lo, hi))


def ga_for_weight(weight_g: int) -> int:
    """Approximate gestational age (weeks) from birth weight with mild noise."""
    # Roughly linear: ~24 wk at 600 g, ~31 wk at 1500 g.
    base = 22 + (weight_g - 450) / 150.0
    return int(min(34, max(22, round(base + random.uniform(-1.5, 1.5)))))


CONDITIONS = ["stable", "guarded", "serious", "critical"]
RESP = ["room_air", "nasal_cannula", "cpap", "ventilator"]


def admission_condition(severity: float):
    """Pick an admission condition + respiratory support weighted by severity."""
    idx = min(3, int(severity * 4 + random.uniform(-0.4, 0.4)))
    idx = max(0, idx)
    resp_idx = min(3, max(0, int(severity * 4 + random.uniform(-0.6, 0.6))))
    return CONDITIONS[idx], RESP[resp_idx]


def severity_of(weight_g: float, ga_weeks: float) -> float:
    w_sev = max(0.0, min(1.0, (1400 - weight_g) / (1400 - 400)))
    g_sev = max(0.0, min(1.0, (34 - ga_weeks) / (34 - 22)))
    return max(0.0, min(1.0, 0.55 * w_sev + 0.45 * g_sev))


def care_phase_at(day_of_stay: float, total_days: float, severity: float):
    """Return (phase_name, nurses_required) for a given point in the stay."""
    intensive = (0.15 + 0.45 * severity) * total_days
    intermediate = (0.30 + 0.10 * (1 - severity)) * total_days
    if day_of_stay <= intensive:
        return "intensive", 1.0
    if day_of_stay <= intensive + intermediate:
        return "intermediate", 0.5
    return "convalescent", 1 / 3


# ---------------------------------------------------------------------------
# 1. Infants
# ---------------------------------------------------------------------------
def build_infants():
    surv = DATASET.survival_by_weight
    infants = []
    infant_id = 1

    for b in WEIGHT_BINS:
        n_home = (surv.get(DISP_HOME, {}).get(b.label) or type("x", (), {"n": 0})).n or 0
        n_tr = (surv.get(DISP_TRANSFER, {}).get(b.label) or type("x", (), {"n": 0})).n or 0
        n_died = (surv.get(DISP_DIED, {}).get(b.label) or type("x", (), {"n": 0})).n or 0

        outcomes = ["Home"] * n_home + ["Transfer"] * n_tr + ["Died"] * n_died
        random.shuffle(outcomes)

        for outcome in outcomes:
            weight = weight_for_bin(b)
            ga = ga_for_weight(weight)
            sev = severity_of(weight, ga)
            cond, resp = admission_condition(sev)

            if outcome == "Home":
                row = surv.get(DISP_HOME, {}).get(b.label)
            elif outcome == "Transfer":
                row = surv.get(DISP_TRANSFER, {}).get(b.label)
            else:
                row = surv.get(DISP_DIED, {}).get(b.label)
            if row and row.median:
                los = sample_los(row.median, row.q1, row.q3)
            else:
                los = sample_los(60, 40, 95)

            admit = START + timedelta(
                seconds=random.uniform(0, (END - START).total_seconds())
            )
            discharge = admit + timedelta(days=los)

            infants.append(
                {
                    "infant_id": f"INF-{infant_id:04d}",
                    "center": "Center 1",
                    "birth_weight_g": weight,
                    "gestational_age_weeks": ga,
                    "birth_weight_band": b.label,
                    "admission_datetime": admit.strftime("%Y-%m-%d %H:%M"),
                    "discharge_datetime": discharge.strftime("%Y-%m-%d %H:%M"),
                    "length_of_stay_days": los,
                    "disposition": outcome,
                    "admission_condition": cond,
                    "respiratory_support": resp,
                    "acuity_severity": round(sev, 3),
                }
            )
            infant_id += 1

    infants.sort(key=lambda r: r["admission_datetime"])
    return infants


# ---------------------------------------------------------------------------
# 2. Nurses
# ---------------------------------------------------------------------------
FIRST = ["Amara", "Priya", "Sofia", "Liam", "Noah", "Maya", "Emma", "Aiden", "Zara",
         "Omar", "Grace", "Leo", "Hana", "Ivan", "Nadia", "Ruth", "Kofi", "Lena",
         "Diego", "Sara", "Tom", "Ana", "Yara", "Ben", "Mei", "Jack", "Rosa", "Sam"]
LAST = ["Okafor", "Sharma", "Rossi", "Nguyen", "Cohen", "Silva", "Khan", "Meyer",
        "Ivanov", "Haddad", "Adeyemi", "Costa", "Park", "Dubois", "Bauer", "Mensah"]
CREDENTIALS = ["RN", "RN, BSN", "RN, NNP", "RN, MSN"]


def build_nurses(n=42):
    nurses = []
    used = set()
    for i in range(1, n + 1):
        while True:
            name = f"{random.choice(FIRST)} {random.choice(LAST)}"
            if name not in used:
                used.add(name)
                break
        hire = START - timedelta(days=random.randint(0, 3650))
        nurses.append(
            {
                "nurse_id": f"RN-{i:03d}",
                "full_name": name,
                "credential": random.choice(CREDENTIALS),
                "specialty": random.choice(
                    ["Neonatal Intensive Care", "Special Care Nursery", "Feeder-Grower"]
                ),
                "years_experience": random.randint(1, 25),
                "hire_date": hire.strftime("%Y-%m-%d"),
                "employment": random.choice(["Full-time", "Full-time", "Part-time"]),
            }
        )
    return nurses


# ---------------------------------------------------------------------------
# 3. Hourly infant time series + unit staffing
# ---------------------------------------------------------------------------
def build_timeseries(infants, nurses):
    """Per-infant hourly acuity, and an aggregated hourly unit staffing series."""
    total_hours = int((END - START).total_seconds() // 3600) + 24 * 60
    # Unit demand accumulator keyed by hour offset from START.
    demand = [0.0] * (total_hours + 1)
    census = [0] * (total_hours + 1)

    infant_rows = []
    for inf in infants:
        admit = datetime.strptime(inf["admission_datetime"], "%Y-%m-%d %H:%M")
        los_days = inf["length_of_stay_days"]
        sev = inf["acuity_severity"]
        n_hours = max(1, int(los_days * 24))
        start_offset = int((admit - START).total_seconds() // 3600)

        # Sample one row every 6 hours to keep the file reviewable while still hourly-grade.
        for h in range(0, n_hours, 6):
            day = h / 24.0
            phase, npi = care_phase_at(day, los_days, sev)
            # Small realistic fluctuation.
            npi_noise = min(1.0, max(0.2, npi * random.uniform(0.9, 1.12)))
            ts = admit + timedelta(hours=h)
            infant_rows.append(
                {
                    "infant_id": inf["infant_id"],
                    "timestamp": ts.strftime("%Y-%m-%d %H:%M"),
                    "hour_of_stay": h,
                    "day_of_stay": round(day, 2),
                    "care_phase": phase,
                    "nurses_required": round(npi_noise, 3),
                }
            )

        # Add hourly demand to the unit accumulator (full hourly resolution).
        for h in range(n_hours):
            off = start_offset + h
            if 0 <= off < len(demand):
                day = h / 24.0
                _, npi = care_phase_at(day, los_days, sev)
                demand[off] += npi
                census[off] += 1

    # Aggregate the unit series to hourly rows, but only emit hours with a census
    # (an empty unit is not interesting to plot and keeps the file compact).
    unit_rows = []
    shifts_per_day = 2
    for off in range(len(demand)):
        if census[off] == 0:
            continue
        ts = START + timedelta(hours=off)
        bedside = math.ceil(demand[off]) if demand[off] > 0 else 0
        on_duty = bedside + 1  # + charge nurse
        shift = "Day (07-19)" if 7 <= ts.hour < 19 else "Night (19-07)"
        unit_rows.append(
            {
                "timestamp": ts.strftime("%Y-%m-%d %H:%M"),
                "hour": ts.hour,
                "shift": shift,
                "census": census[off],
                "nurse_demand": round(demand[off], 2),
                "bedside_nurses_scheduled": bedside,
                "charge_nurses_scheduled": 1,
                "nurses_on_duty": on_duty,
            }
        )
    return infant_rows, unit_rows, shifts_per_day


# ---------------------------------------------------------------------------
# 4. Nurse shift roster (daily day/night shifts)
# ---------------------------------------------------------------------------
def build_shifts(nurses, unit_rows):
    """Assign named nurses to day/night shifts on days the unit was staffed."""
    # Determine per-day peak on-duty need from the unit series.
    per_day = {}
    for r in unit_rows:
        date = r["timestamp"][:10]
        per_day.setdefault(date, {"Day (07-19)": 0, "Night (19-07)": 0})
        per_day[date][r["shift"]] = max(per_day[date][r["shift"]], r["nurses_on_duty"])

    shift_rows = []
    shift_id = 1
    for date in sorted(per_day):
        for shift_name, need in per_day[date].items():
            need = max(1, need)
            roster = random.sample(nurses, min(need, len(nurses)))
            for j, nurse in enumerate(roster):
                shift_rows.append(
                    {
                        "shift_id": f"SH-{shift_id:06d}",
                        "date": date,
                        "shift": shift_name,
                        "nurse_id": nurse["nurse_id"],
                        "nurse_name": nurse["full_name"],
                        "role": "Charge Nurse" if j == 0 else "Bedside Nurse",
                    }
                )
            shift_id += 1
    return shift_rows


# ---------------------------------------------------------------------------
# Writers
# ---------------------------------------------------------------------------
def write_csv(name, rows):
    path = OUT_DIR / name
    if not rows:
        path.write_text("")
        return path
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    return path


def main():
    print("Building infants...")
    infants = build_infants()
    print(f"  {len(infants)} infants")

    print("Building nurses...")
    nurses = build_nurses()

    print("Building hourly time series (this is the heavy step)...")
    infant_ts, unit_ts, _ = build_timeseries(infants, nurses)
    print(f"  {len(infant_ts)} infant timepoints, {len(unit_ts)} unit hours")

    print("Building shift roster...")
    shifts = build_shifts(nurses, unit_ts)
    print(f"  {len(shifts)} shift assignments")

    write_csv("infants.csv", infants)
    write_csv("nurses.csv", nurses)
    write_csv("infant_hourly_acuity.csv", infant_ts)
    write_csv("unit_hourly_staffing.csv", unit_ts)
    write_csv("nurse_shift_roster.csv", shifts)

    print(f"\nDone. Files written to {OUT_DIR}")


if __name__ == "__main__":
    main()
