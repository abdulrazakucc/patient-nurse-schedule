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

    phase_detail = []
    total_nurse_hours = 0.0
    for ph in phases:
        days = ph["fraction"] * los_days
        nurse_hours = days * HOURS_PER_DAY * ph["nurses_per_infant"]
        total_nurse_hours += nurse_hours
        phase_detail.append(
            {
                "name": ph["name"],
                "days": round(days, 1),
                "nurses_per_infant": round(ph["nurses_per_infant"], 3),
                "nurse_hours": round(nurse_hours, 1),
            }
        )

    nhppd = total_nurse_hours / los_days               # nursing hours per patient day
    peak_nurses = max(p["nurses_per_infant"] for p in phases)  # during intensive phase
    # Total nursing shifts (12h) required across the stay.
    shifts_12h = total_nurse_hours / 12

    return {
        "acuity_severity": profile["severity"],
        "peak_nurses_per_infant": round(peak_nurses, 3),
        "avg_nhppd": round(nhppd, 2),
        "total_nurse_hours": round(total_nurse_hours, 1),
        "total_12h_shifts": round(shifts_12h, 1),
        "phases": phase_detail,
        "note": (
            "Estimates follow AAP/AWHONN acuity-based nurse:patient ratios. Actual "
            "staffing must be adjusted for ventilation, surgery, and unit policy."
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
        "note": (
            "Immediate acuity-based demand using AAP/AWHONN ratios (1:1 intensive, "
            "1:2 intermediate, 1:3 convalescent) plus one charge nurse per shift."
        ),
    }

