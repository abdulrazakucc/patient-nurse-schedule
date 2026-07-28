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
from app.nursing import (  # noqa: E402
    LEVEL_BY_ID,
    level_for_years,
    required_level,
)

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
                    "required_nurse_level": required_level(sev, cond, resp),
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

# Target shape of the nursing workforce by Benner competency level. Real NICUs
# run a pyramid: a modest novice intake, a large competent/proficient core, and
# a senior expert group who precept and take charge. Shares are a planning
# assumption, chosen to be realistic rather than drawn from a published census.
LEVEL_SHARES = [
    (1, 0.19),  # Novice / Advanced Beginner  (0-1 yr)
    (2, 0.29),  # Competent                   (1-3 yr)
    (3, 0.26),  # Proficient                  (3-5 yr)
    (4, 0.26),  # Expert                      (5+ yr)
]

# Years of experience sampled inside each level's band.
LEVEL_YEARS_RANGE = {1: (0.2, 0.9), 2: (1.0, 2.9), 3: (3.0, 4.9), 4: (5.0, 24.0)}

# Higher levels carry the specialist credentials and the sickest assignments.
LEVEL_CREDENTIALS = {
    1: ["RN", "RN, BSN"],
    2: ["RN", "RN, BSN", "RN, BSN"],
    3: ["RN, BSN", "RN, MSN"],
    4: ["RN, BSN", "RN, MSN", "RN, NNP"],
}
LEVEL_SPECIALTY = {
    1: ["Feeder-Grower", "Special Care Nursery"],
    2: ["Special Care Nursery", "Neonatal Intensive Care"],
    3: ["Neonatal Intensive Care", "Special Care Nursery"],
    4: ["Neonatal Intensive Care"],
}


def build_nurses(n=42):
    """Build a workforce with a realistic competency pyramid (Benner levels 1-4)."""
    # Resolve the target headcount per level, giving any rounding remainder to L2.
    counts = {lv: int(round(n * share)) for lv, share in LEVEL_SHARES}
    counts[2] += n - sum(counts.values())

    roster_levels = []
    for lv, c in counts.items():
        roster_levels.extend([lv] * max(0, c))
    random.shuffle(roster_levels)

    nurses = []
    used = set()
    for i, level in enumerate(roster_levels, start=1):
        while True:
            name = f"{random.choice(FIRST)} {random.choice(LAST)}"
            if name not in used:
                used.add(name)
                break

        lo, hi = LEVEL_YEARS_RANGE[level]
        years = round(random.uniform(lo, hi), 1)
        # Hire date follows from experience, so the two never contradict.
        hire = START - timedelta(days=int(years * 365.25))
        info = LEVEL_BY_ID[level]

        nurses.append(
            {
                "nurse_id": f"RN-{i:03d}",
                "full_name": name,
                "credential": random.choice(LEVEL_CREDENTIALS[level]),
                "specialty": random.choice(LEVEL_SPECIALTY[level]),
                "years_experience": years,
                "experience_level": level,
                "competency_stage": info["name"],
                "level_band": info["years_label"],
                "care_capacity": info["capacity"],
                "can_precept": "yes" if level >= 3 else "no",
                "charge_eligible": "yes" if level == 4 else "no",
                "hire_date": hire.strftime("%Y-%m-%d"),
                "employment": random.choice(["Full-time", "Full-time", "Part-time"]),
            }
        )
    nurses.sort(key=lambda r: (-r["experience_level"], r["full_name"]))
    for i, nurse in enumerate(nurses, start=1):
        nurse["nurse_id"] = f"RN-{i:03d}"
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
                    "required_nurse_level": (
                        inf["required_nurse_level"] if phase == "intensive"
                        else (2 if phase == "intermediate" else 1)
                    ),
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
    """Assign named nurses to day/night shifts on days the unit was staffed.

    Rostering respects the competency model rather than picking at random:

    * the charge nurse is always an expert (level 4);
    * every shift keeps at least one further expert or proficient nurse free to
      precept, and novices are capped at ~30% of the bedside team;
    * each novice on shift is paired with a named preceptor (level 3+).
    """
    by_level = {lv: [n for n in nurses if n["experience_level"] == lv] for lv in (1, 2, 3, 4)}

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
            bedside_need = max(0, need - 1)  # one slot is the charge nurse

            # Charge nurse: expert, falling back to proficient only if unavoidable.
            charge_pool = by_level[4] or by_level[3]
            charge = random.choice(charge_pool)

            # Compose the bedside team: cap novices, then fill with the senior core.
            max_novice = int(bedside_need * 0.30)
            n_novice = min(max_novice, len(by_level[1]), random.randint(0, max(0, max_novice)))
            remaining = bedside_need - n_novice
            senior_pool = [n for n in by_level[3] + by_level[4] if n["nurse_id"] != charge["nurse_id"]]
            # At least one senior stays on the floor to precept the novices.
            n_senior = min(len(senior_pool), max(n_novice, remaining // 2))
            n_competent = max(0, remaining - n_senior)

            team = []
            team += random.sample(by_level[1], min(n_novice, len(by_level[1])))
            team += random.sample(senior_pool, min(n_senior, len(senior_pool)))
            comp_pool = by_level[2]
            team += random.sample(comp_pool, min(n_competent, len(comp_pool)))

            # Top up from anyone left if the pools ran short.
            if len(team) < bedside_need:
                ids = {n["nurse_id"] for n in team} | {charge["nurse_id"]}
                spare = [n for n in nurses if n["nurse_id"] not in ids]
                team += random.sample(spare, min(bedside_need - len(team), len(spare)))

            preceptors = [n for n in team if n["experience_level"] >= 3]
            preceptor_cycle = 0

            for nurse in [charge] + team:
                is_charge = nurse["nurse_id"] == charge["nurse_id"] and nurse is charge
                assigned_preceptor = ""
                if not is_charge and nurse["experience_level"] == 1 and preceptors:
                    assigned_preceptor = preceptors[preceptor_cycle % len(preceptors)]["full_name"]
                    preceptor_cycle += 1
                shift_rows.append(
                    {
                        "shift_id": f"SH-{shift_id:06d}",
                        "date": date,
                        "shift": shift_name,
                        "nurse_id": nurse["nurse_id"],
                        "nurse_name": nurse["full_name"],
                        "experience_level": nurse["experience_level"],
                        "competency_stage": nurse["competency_stage"],
                        "years_experience": nurse["years_experience"],
                        "role": "Charge Nurse" if is_charge else "Bedside Nurse",
                        "precepted_by": assigned_preceptor,
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
