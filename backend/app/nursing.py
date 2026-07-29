"""
Nurse staffing estimator for the NICU.

Aligned with widely used neonatal staffing frameworks (AAP *Guidelines for Perinatal
Care* and AWHONN nurse-staffing standards), which assign a nurse-to-patient ratio by
acuity:

    Acuity                         Nurse : Patient    Typical infant
    -----------------------------  -----------------  -----------------------------
    Intensive / unstable           1 : 1              ventilated, ELBW, first days
    High acuity                    1 : 1              critically ill / post-op
    Intermediate (special care)    1 : 2 – 1 : 3      stable, growing, some support
    Convalescent (feeder-grower)   1 : 3 – 1 : 4      full feeds, thermoregulating

An infant's stay is modelled as a sequence of phases. Very premature / very low
birth-weight infants spend longer in the intensive phase. The estimator returns the
nurse-hours required, the peak nurses-per-shift for this infant, and an average
Nursing Hours Per Patient Day (NHPPD).
"""
from __future__ import annotations

import math

HOURS_PER_DAY = 24

# ---------------------------------------------------------------------------
# Nurse experience / competency model
# ---------------------------------------------------------------------------
# Levels follow Patricia Benner's *From Novice to Expert* (1984) skill-acquisition
# stages, which remain the standard framework for nursing competency and are the
# basis of most NICU clinical-ladder programmes.
#
# ``capacity`` is the share of a full bedside assignment a nurse at that level
# carries independently: a novice still needs preceptor support, while an expert
# absorbs more (and resolves problems faster). These coefficients are a MODELLING
# ASSUMPTION for planning discussion - they are not published, validated values.
NURSE_LEVELS = [
    {
        "level": 1,
        "name": "Novice / Advanced Beginner",
        "short": "Novice",
        "years_label": "0-1 year",
        "min_years": 0,
        "capacity": 0.75,
        "scope": "Convalescent (feeder-grower) infants; intermediate care with a preceptor.",
    },
    {
        "level": 2,
        "name": "Competent",
        "short": "Competent",
        "years_label": "1-3 years",
        "min_years": 1,
        "capacity": 0.90,
        "scope": "Intermediate / special-care infants; stable intensive with support.",
    },
    {
        "level": 3,
        "name": "Proficient",
        "short": "Proficient",
        "years_label": "3-5 years",
        "min_years": 3,
        "capacity": 1.00,
        "scope": "Intensive 1:1 assignments, including ventilated infants.",
    },
    {
        "level": 4,
        "name": "Expert",
        "short": "Expert",
        "years_label": "5+ years",
        "min_years": 5,
        "capacity": 1.10,
        "scope": "Highest-acuity / unstable infants, charge nurse, precepting.",
    },
]

LEVEL_BY_ID = {lv["level"]: lv for lv in NURSE_LEVELS}

# Share of bedside nurses on a shift that may safely be level 1, and the level a
# novice must be paired with. Unit-policy style guardrails, not published values.
MAX_NOVICE_SHARE = 0.30
PRECEPTOR_MIN_LEVEL = 3


def level_for_years(years: float) -> int:
    """Map years of NICU experience onto a Benner competency level (1-4)."""
    y = max(0.0, float(years or 0))
    if y < 1:
        return 1
    if y < 3:
        return 2
    if y < 5:
        return 3
    return 4


def required_level(severity: float, condition: str | None = None,
                   resp_support: str | None = None) -> int:
    """Minimum competency level for the nurse assigned to this infant.

    Driven by the acuity band, then escalated for invasive respiratory support
    or a critical admission condition.

    Level 4 is deliberately reserved for the genuinely unstable infant - both
    critically ill *and* ventilated. Proficient (3-5 year) nurses routinely care
    for ventilated VLBW infants, and a unit cannot roster an expert to a third
    of its cots; treating every sick infant as expert-only would make the
    requirement unmeetable rather than informative.
    """
    lvl = 1
    if severity >= 0.35:
        lvl = 2
    if severity >= 0.60:
        lvl = 3

    cond = (condition or "").lower()
    resp = (resp_support or "").lower()
    if resp == "ventilator" or cond == "critical":
        lvl = max(lvl, 3)
    if resp == "ventilator" and cond == "critical":
        lvl = 4
    return lvl


def level_info(level: int) -> dict:
    lv = LEVEL_BY_ID.get(level, LEVEL_BY_ID[1])
    return {
        "level": lv["level"],
        "name": lv["name"],
        "short": lv["short"],
        "years_label": lv["years_label"],
        "scope": lv["scope"],
    }


# Admission health-condition modifiers (added to base severity 0..1).
CONDITION_MODIFIERS = {
    "stable": 0.0,
    "guarded": 0.12,
    "serious": 0.25,
    "critical": 0.40,
}

# Respiratory support modifiers (added to base severity 0..1).
RESP_SUPPORT_MODIFIERS = {
    "room_air": 0.0,
    "nasal_cannula": 0.05,
    "cpap": 0.15,
    "ventilator": 0.30,
}


def _acuity_profile(weight_g: float, ga_weeks: float, modifier: float = 0.0) -> dict:
    """Return the fraction of the stay spent in each acuity phase and its ratio.

    Ratios are nurse:patient, expressed here as nurses-per-infant (1/ratio).
    ``modifier`` (0..~0.7) raises severity for sicker admission conditions.
    """
    # Base severity 0..1 (higher = sicker). Combine weight and GA.
    w_sev = max(0.0, min(1.0, (1400 - weight_g) / (1400 - 400)))
    g_sev = max(0.0, min(1.0, (34 - ga_weeks) / (34 - 22)))
    severity = max(0.0, min(1.0, 0.55 * w_sev + 0.45 * g_sev + modifier))

    # Phase length fractions shift toward the intensive phase as severity rises.
    intensive = 0.15 + 0.45 * severity          # 1:1
    intermediate = 0.30 + 0.10 * (1 - severity)  # 1:2
    # Remainder is convalescent (1:3).
    convalescent = max(0.0, 1.0 - intensive - intermediate)

    total = intensive + intermediate + convalescent
    return {
        "severity": round(severity, 3),
        "phases": [
            {"name": "Intensive care (1:1)", "fraction": intensive / total, "nurses_per_infant": 1.0},
            {"name": "Intermediate care (1:2)", "fraction": intermediate / total, "nurses_per_infant": 0.5},
            {"name": "Convalescent care (1:3)", "fraction": convalescent / total, "nurses_per_infant": 1 / 3},
        ],
    }


def condition_modifier(condition: str | None, resp_support: str | None) -> float:
    """Combined severity modifier from admission condition + respiratory support."""
    c = CONDITION_MODIFIERS.get((condition or "stable").lower(), 0.0)
    r = RESP_SUPPORT_MODIFIERS.get((resp_support or "room_air").lower(), 0.0)
    return c + r


PHASE_KEYS = ["intensive", "intermediate", "convalescent"]


def phase_required_level(phase_key: str, severity: float, condition: str | None,
                         resp_support: str | None) -> int:
    """Minimum competency level for a nurse during one phase of the stay.

    The intensive phase carries the infant's full acuity (and any escalation for
    ventilation / critical illness); by the convalescent phase the infant is a
    stable feeder-grower and is a suitable novice assignment.
    """
    if phase_key == "intensive":
        return required_level(max(severity, 0.60), condition, resp_support)
    if phase_key == "intermediate":
        return 2
    return 1


def staffing_timeline(weight_g: float, ga_weeks: float, los_days: float,
                      condition: str | None = None, resp_support: str | None = None,
                      max_points: int = 120) -> list[dict]:
    """Day-by-day nursing requirement across the expected stay (for plotting)."""
    if not los_days or los_days <= 0:
        los_days = 1.0
    modifier = condition_modifier(condition, resp_support)
    profile = _acuity_profile(weight_g, ga_weeks, modifier)
    sev = profile["severity"]
    fractions = [p["fraction"] for p in profile["phases"]]
    intensive_days = fractions[0] * los_days
    intermediate_days = fractions[1] * los_days

    step = max(1.0, los_days / max_points)
    points = []
    day = 0.0
    while day <= los_days + 1e-9:
        if day <= intensive_days:
            key, npi = "intensive", 1.0
        elif day <= intensive_days + intermediate_days:
            key, npi = "intermediate", 0.5
        else:
            key, npi = "convalescent", 1 / 3
        points.append(
            {
                "day": round(day, 2),
                "phase": key,
                "nurses_required": round(npi, 3),
                "required_level": phase_required_level(key, sev, condition, resp_support),
            }
        )
        day += step
    return points


def estimate_staffing(
    weight_g: float,
    ga_weeks: float,
    los_days: float,
    condition: str | None = None,
    resp_support: str | None = None,
) -> dict:
    """Estimate nursing workload for one infant over the expected stay."""
    if not los_days or los_days <= 0:
        los_days = 1.0

    modifier = condition_modifier(condition, resp_support)
    profile = _acuity_profile(weight_g, ga_weeks, modifier)
    phases = profile["phases"]
    severity = profile["severity"]

    phase_detail = []
    total_nurse_hours = 0.0
    for idx, ph in enumerate(phases):
        days = ph["fraction"] * los_days
        nurse_hours = days * HOURS_PER_DAY * ph["nurses_per_infant"]
        total_nurse_hours += nurse_hours
        key = PHASE_KEYS[idx]
        lvl = phase_required_level(key, severity, condition, resp_support)
        phase_detail.append(
            {
                "name": ph["name"],
                "phase": key,
                "days": round(days, 1),
                "nurses_per_infant": round(ph["nurses_per_infant"], 3),
                "nurse_hours": round(nurse_hours, 1),
                "required_level": lvl,
                "required_level_name": LEVEL_BY_ID[lvl]["short"],
            }
        )

    nhppd = total_nurse_hours / los_days               # nursing hours per patient day
    peak_nurses = max(p["nurses_per_infant"] for p in phases)  # during intensive phase
    # Total nursing shifts (12h) required across the stay.
    shifts_12h = total_nurse_hours / 12

    admission_level = required_level(severity, condition, resp_support)

    return {
        "acuity_severity": severity,
        "peak_nurses_per_infant": round(peak_nurses, 3),
        "avg_nhppd": round(nhppd, 2),
        "total_nurse_hours": round(total_nurse_hours, 1),
        "total_12h_shifts": round(shifts_12h, 1),
        "phases": phase_detail,
        "admission_required_level": admission_level,
        "admission_level_info": level_info(admission_level),
        "timeline": staffing_timeline(
            weight_g, ga_weeks, los_days, condition, resp_support
        ),
        "note": (
            "Estimates follow AAP/AWHONN acuity-based nurse:patient ratios. Actual "
            "staffing must be adjusted for ventilation, surgery, and unit policy."
        ),
        "competency_note": (
            "Competency levels follow Benner's novice-to-expert stages. The minimum "
            "level shown is a planning guide - final assignment rests with the charge "
            "nurse, who also weighs continuity of care and precepting needs."
        ),
    }


def schedule_unit(infants: list[dict], shifts_per_day: int = 2) -> dict:
    """Compute unit-wide nurse staffing from a live census of infants.

    Each infant dict may contain: weight_g, ga_weeks, condition, resp_support.
    Returns the immediate nurses-required (current acuity) plus a charge nurse and
    a per-shift roster recommendation.
    """
    rows = []
    total_current_demand = 0.0
    acuity_counts = {"intensive": 0, "intermediate": 0, "convalescent": 0}
    demand_by_level: dict[int, float] = {1: 0.0, 2: 0.0, 3: 0.0, 4: 0.0}

    for i, inf in enumerate(infants):
        w = float(inf.get("weight_g", 1000))
        g = float(inf.get("ga_weeks", 30))
        modifier = condition_modifier(inf.get("condition"), inf.get("resp_support"))
        profile = _acuity_profile(w, g, modifier)
        sev = profile["severity"]

        # Current acuity band -> immediate nurse:infant requirement.
        if sev >= 0.6:
            band, npi = "intensive", 1.0
            acuity_counts["intensive"] += 1
        elif sev >= 0.35:
            band, npi = "intermediate", 0.5
            acuity_counts["intermediate"] += 1
        else:
            band, npi = "convalescent", 1 / 3
            acuity_counts["convalescent"] += 1

        total_current_demand += npi
        req = required_level(sev, inf.get("condition"), inf.get("resp_support"))
        demand_by_level[req] = demand_by_level.get(req, 0.0) + npi
        rows.append(
            {
                "index": i + 1,
                "weight_g": w,
                "ga_weeks": g,
                "condition": inf.get("condition") or "stable",
                "resp_support": inf.get("resp_support") or "room_air",
                "severity": round(sev, 3),
                "acuity": band,
                "nurses_required": round(npi, 3),
                "required_level": req,
                "required_level_name": LEVEL_BY_ID[req]["short"],
            }
        )

    bedside_nurses = math.ceil(total_current_demand) if total_current_demand > 0 else 0
    # A charge nurse is standard for any staffed unit.
    charge_nurse = 1 if infants else 0
    nurses_per_shift = bedside_nurses + charge_nurse
    daily_nurse_shifts = nurses_per_shift * shifts_per_day

    return {
        "census": len(infants),
        "acuity_counts": acuity_counts,
        "total_demand": round(total_current_demand, 2),
        "bedside_nurses_per_shift": bedside_nurses,
        "charge_nurses_per_shift": charge_nurse,
        "nurses_per_shift": nurses_per_shift,
        "shifts_per_day": shifts_per_day,
        "daily_nurse_shifts": daily_nurse_shifts,
        "infants": rows,
        "skill_mix": skill_mix(demand_by_level, bedside_nurses, bool(infants)),
        "note": (
            "Immediate acuity-based demand using AAP/AWHONN ratios (1:1 intensive, "
            "1:2 intermediate, 1:3 convalescent) plus one charge nurse per shift."
        ),
    }


def distribute_nurses(available_by_level: dict[int, int], shifts_per_day: int) -> list[list[int]]:
    """Spread the available workforce across the day's shifts.

    Nurses work one shift per day, so the pool has to be divided. Seniors are
    dealt out first and rotated round-robin, which keeps every shift's skill mix
    comparable instead of stacking all the experts onto days.
    """
    shifts: list[list[int]] = [[] for _ in range(max(1, shifts_per_day))]
    seq = 0
    for lv in (4, 3, 2, 1):
        for _ in range(int(available_by_level.get(lv, 0) or 0)):
            shifts[seq % len(shifts)].append(lv)
            seq += 1
    return shifts


def assign_shift(infants: list[dict], nurse_levels: list[int], shift_index: int) -> dict:
    """Assign this shift's infants to the nurses rostered on it.

    Rules, in order of priority:
      * a nurse may only take an infant at or below their competency level;
      * a nurse carries at most one full assignment (1.0 = one intensive infant,
        or two intermediate, or three convalescent);
      * the sickest infants are placed first, into the *least* senior qualified
        nurse available, so experts stay free for the infants who need them;
      * one senior nurse is held back as charge (not given a bedside load)
        whenever the shift has two or more nurses.
    """
    nurses = [
        {
            "id": f"S{shift_index + 1}-N{i + 1}",
            "level": lv,
            "load": 0.0,
            "infants": [],
            "is_charge": False,
        }
        for i, lv in enumerate(nurse_levels)
    ]
    nurses.sort(key=lambda n: (-n["level"], n["id"]))

    charge = None
    if len(nurses) >= 2:
        nurses[0]["is_charge"] = True
        charge = nurses[0]
    bedside = [n for n in nurses if not n["is_charge"]]

    queue = sorted(
        infants,
        key=lambda i: (-i["required_level"], -i["nurses_required"], i["index"]),
    )

    unassigned = []
    for inf in queue:
        eligible = [
            n for n in bedside
            if n["level"] >= inf["required_level"]
            and n["load"] + inf["nurses_required"] <= 1.0 + 1e-9
        ]
        if not eligible:
            unassigned.append(inf)
            continue
        # Least senior qualified nurse, then the tightest fit.
        eligible.sort(key=lambda n: (n["level"], -n["load"], n["id"]))
        pick = eligible[0]
        pick["load"] = round(pick["load"] + inf["nurses_required"], 6)
        pick["infants"].append(inf["index"])

    # Last resort: rather than leave an infant with nobody, the charge nurse
    # picks up an assignment. Real units do this when cover is thin - but it
    # leaves no one free to coordinate, so it is reported as a warning.
    charge_carrying = False
    if unassigned and charge is not None:
        still_unassigned = []
        for inf in unassigned:
            if (charge["level"] >= inf["required_level"]
                    and charge["load"] + inf["nurses_required"] <= 1.0 + 1e-9):
                charge["load"] = round(charge["load"] + inf["nurses_required"], 6)
                charge["infants"].append(inf["index"])
                charge_carrying = True
            else:
                still_unassigned.append(inf)
        unassigned = still_unassigned

    return {
        "nurses": nurses,
        "unassigned": unassigned,
        "charge_carrying_bedside": charge_carrying,
    }


def build_roster(infants: list[dict], available_by_level: dict[int, int],
                 shifts_per_day: int = 2) -> dict:
    """Roster the available nurses against the census, shift by shift.

    Returns per-shift assignments with each nurse's committed hours over the
    24-hour cycle, plus an explicit account of any infant left uncovered.
    """
    shifts_per_day = max(1, int(shifts_per_day or 2))
    shift_hours = 24.0 / shifts_per_day
    pools = distribute_nurses(available_by_level, shifts_per_day)

    shifts = []
    total_unassigned = 0
    worst_gap: dict[int, float] = {}

    for idx, pool in enumerate(pools):
        result = assign_shift(infants, pool, idx)
        rows = []
        for n in result["nurses"]:
            allocated = round(n["load"] * shift_hours, 2)
            rows.append(
                {
                    "id": n["id"],
                    "level": n["level"],
                    "level_name": LEVEL_BY_ID[n["level"]]["short"],
                    "is_charge": n["is_charge"],
                    "infants": n["infants"],
                    "load": round(n["load"], 3),
                    "shift_start": round(idx * shift_hours, 2),
                    "shift_end": round((idx + 1) * shift_hours, 2),
                    "allocated_hours": allocated,
                    "spare_hours": round(shift_hours - allocated, 2),
                    "day_percent": round(allocated / 24.0 * 100, 1),
                }
            )

        # What would it take to cover the infants nobody could accept?
        gap: dict[int, float] = {}
        for inf in result["unassigned"]:
            lv = inf["required_level"]
            gap[lv] = gap.get(lv, 0.0) + inf["nurses_required"]
        for lv, dem in gap.items():
            worst_gap[lv] = max(worst_gap.get(lv, 0.0), dem)

        total_unassigned += len(result["unassigned"])
        shifts.append(
            {
                "index": idx,
                "label": _shift_label(idx, shifts_per_day),
                "start_hour": round(idx * shift_hours, 2),
                "end_hour": round((idx + 1) * shift_hours, 2),
                "nurses": rows,
                "nurse_count": len(rows),
                "bedside_count": sum(1 for r in rows if not r["is_charge"]),
                "has_charge": any(r["is_charge"] for r in rows),
                "unassigned": [i["index"] for i in result["unassigned"]],
                "charge_carrying_bedside": result["charge_carrying_bedside"],
                "committed_hours": round(sum(r["allocated_hours"] for r in rows), 2),
                "capacity_hours": round(len(rows) * shift_hours, 2),
                "mean_load": round(
                    sum(r["load"] for r in rows if not r["is_charge"])
                    / max(1, sum(1 for r in rows if not r["is_charge"])), 3
                ),
            }
        )

    needed = {lv: math.ceil(d - 1e-9) for lv, d in worst_gap.items() if d > 0}
    total_available = sum(int(available_by_level.get(lv, 0) or 0) for lv in (1, 2, 3, 4))

    return {
        "shifts_per_day": shifts_per_day,
        "shift_hours": shift_hours,
        "shifts": shifts,
        "total_available": total_available,
        "unassigned_total": total_unassigned,
        "covered": total_unassigned == 0,
        "charge_carrying_bedside": any(s["charge_carrying_bedside"] for s in shifts),
        "additional_nurses_needed": needed,
        "note": (
            "Each nurse works one shift per day and carries at most one full "
            "assignment. Charge nurses are held free of a bedside load."
        ),
    }


def _shift_label(idx: int, shifts_per_day: int) -> str:
    """Clock label for a shift, with the nursing day starting at 07:00."""
    hours = 24 // max(1, shifts_per_day)
    start = (7 + idx * hours) % 24
    end = (start + hours) % 24
    return f"{start:02d}:00-{end:02d}:00"


def skill_mix(demand_by_level: dict[int, float], bedside_nurses: int,
              staffed: bool = True) -> dict:
    """Recommend how the bedside nurses on a shift should be distributed by level.

    A nurse may always cover an assignment that requires a *lower* level than
    their own, never a higher one - so requirements accumulate downward from the
    expert tier.
    """
    if not staffed or bedside_nurses <= 0:
        return {
            "bedside_nurses": 0,
            "charge_nurse_level": 4,
            "levels": [
                {**level_info(lv["level"]), "recommended": 0, "min_required": 0,
                 "demand": 0.0, "capacity": lv["capacity"]}
                for lv in NURSE_LEVELS
            ],
            "effective_capacity": 0.0,
            "novice_share": 0.0,
            "preceptors_needed": 0,
            "warnings": [],
        }

    # Cumulative demand that can only be met at this level or above.
    cum = {}
    running = 0.0
    for lv in (4, 3, 2, 1):
        running += demand_by_level.get(lv, 0.0)
        cum[lv] = running

    min_at_or_above = {lv: math.ceil(cum[lv] - 1e-9) for lv in (4, 3, 2, 1)}

    # Turn the cumulative minimums into a concrete headcount per level.
    n4 = min_at_or_above[4]
    n3 = max(0, min_at_or_above[3] - n4)
    n2 = max(0, min_at_or_above[2] - n4 - n3)
    n1 = max(0, bedside_nurses - n4 - n3 - n2)
    counts = {4: n4, 3: n3, 2: n2, 1: n1}

    # Cap novices at the policy share, promoting the surplus to competent.
    max_novices = int(bedside_nurses * MAX_NOVICE_SHARE)
    if counts[1] > max_novices:
        counts[2] += counts[1] - max_novices
        counts[1] = max_novices

    effective = sum(counts[lv] * LEVEL_BY_ID[lv]["capacity"] for lv in counts)
    novice_share = counts[1] / bedside_nurses if bedside_nurses else 0.0
    preceptors = counts[1]  # one preceptor (level 3+) per novice on shift
    seniors = counts[3] + counts[4]

    warnings = []
    if counts[1] and seniors < preceptors:
        warnings.append(
            f"{counts[1]} novice nurse(s) rostered but only {seniors} proficient/expert "
            "nurse(s) available to precept."
        )
    if counts[4] == 0 and cum[4] > 0:
        warnings.append("High-acuity infants present - at least one expert nurse is required.")

    return {
        "bedside_nurses": bedside_nurses,
        "charge_nurse_level": 4,
        "levels": [
            {
                **level_info(lv["level"]),
                "recommended": counts[lv["level"]],
                "min_required": min_at_or_above[lv["level"]],
                "demand": round(demand_by_level.get(lv["level"], 0.0), 2),
                "capacity": lv["capacity"],
            }
            for lv in NURSE_LEVELS
        ],
        "effective_capacity": round(effective, 2),
        "novice_share": round(novice_share, 3),
        "preceptors_needed": preceptors,
        "warnings": warnings,
    }

