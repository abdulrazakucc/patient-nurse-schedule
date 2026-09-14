"""
Dr. Waseem Altaf's nurse-skills classifier (``datasets/nurse-skills/``).

The source PDF is three scanned pages. Their tables were transcribed into one CSV
per page, and those CSVs are the only thing read here - the PDF itself is never
opened:

    page 1  Abrazo Arrowhead Neonatal Acuity Tool: clinical findings per body
            system, each placed in a nurse:patient ratio column.
    page 2  Nursing Levels of Care - hyperbilirubinemia criteria, N1-N4.
    page 3  Nursing Levels of Care - general criteria, N1-N4.

Handwritten annotations on pages 2-3 are deliberately ignored.

An infant is classified from the findings ticked for it: the most intensive
ratio column across every body system sets the nurse:patient ratio, and the
highest level-of-care criterion met sets the care level (N1-N4). The minimum
nurse competency level is the higher of the two.
"""
from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Iterable

SKILLS_DIR = Path(__file__).resolve().parents[2] / "datasets" / "nurse-skills"
SOURCE = "Nurse-skills-classifier-dr-waseem-altaf.pdf"
FILES = {
    "acuity": "page_1_abrazo_arrowhead_neonatal_acuity_tool.csv",
    "hyperbilirubinemia": "page_2_nursing_levels_of_care_hyperbilirubinemia.csv",
    "general": "page_3_nursing_levels_of_care.csv",
}

# Ratio columns of the acuity tool, most intensive first. Where a column gives a
# range, planning uses its more protective end. Intensive care is the exception:
# the tool's own footnote names the infants who need 1:1, so the rest are 1:2.
RATIO_COLUMNS = [
    {"key": "intensive", "csv": "nurse_ratio_1_2_or_1_1_intensive_care",
     "name": "Intensive care", "ratio": "1:2 or 1:1", "planning_ratio": "1:2",
     "band": "intensive", "nurses_per_infant": 0.5, "nurse_level": 3},
    {"key": "intermediate", "csv": "nurse_ratio_1_2_3_intermediate_care",
     "name": "Intermediate care", "ratio": "1:2–3", "planning_ratio": "1:2",
     "band": "intermediate", "nurses_per_infant": 0.5, "nurse_level": 2},
    {"key": "continuing", "csv": "nurse_ratio_1_3_continuing_care",
     "name": "Continuing care", "ratio": "1:3", "planning_ratio": "1:3",
     "band": "convalescent", "nurses_per_infant": 1 / 3, "nurse_level": 1},
    {"key": "continuing_low", "csv": "nurse_ratio_1_3_4_continuing_care",
     "name": "Continuing care", "ratio": "1:3–4", "planning_ratio": "1:3",
     "band": "convalescent", "nurses_per_infant": 1 / 3, "nurse_level": 1},
]
COLUMN_RANK = {c["key"]: i for i, c in enumerate(RATIO_COLUMNS)}

# The footnoted 1:1 infant: one nurse, and an Expert one.
ONE_TO_ONE = {"ratio": "1:1", "nurses_per_infant": 1.0, "nurse_level": 4}

# Levels of care. Each maps onto the nurse competency level of the same number
# (N1 -> Novice ... N4 -> Expert).
CARE_LEVELS = [
    {"level": 1, "code": "N1", "name": "Newborn Nursery",
     "csv": "NBN_N1_Newborn_Nursery"},
    {"level": 2, "code": "N2", "name": "Continuing / Special Care Nursery",
     "csv": "Level_2_N2_Continuing_Care_Nursery_CCN_Special_Care_Nursery"},
    {"level": 3, "code": "N3", "name": "Neonatal Intensive Care Unit 3",
     "csv": "Level_3_N3_Neonatal_Intensive_Care_Unit_3"},
    {"level": 4, "code": "N4", "name": "Neonatal Intensive Care Unit 4",
     "csv": "Level_4_N4_Neonatal_Intensive_Care_Unit_4"},
]
CARE_BY_LEVEL = {c["level"]: c for c in CARE_LEVELS}

# With no bedside findings ticked, the ratio column is inferred from care level.
CARE_LEVEL_COLUMN = {4: "intensive", 3: "intensive", 2: "intermediate", 1: "continuing"}

ONE_TO_ONE_ID = "one-to-one"


def _read(name: str) -> list[dict]:
    with (SKILLS_DIR / FILES[name]).open(newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _clean(text: str | None) -> str:
    return " ".join((text or "").split())


def _bullets(cell: str | None) -> list[str]:
    """Split a table cell into its bullet points, dropping N/A."""
    out = []
    for line in (cell or "").split("\n"):
        text = line.strip().lstrip("•").strip()
        if text and text.upper() != "N/A":
            out.append(text)
    return out


def _load_acuity() -> dict:
    title, footnote = "", ""
    systems, assessment = [], {}
    for row in _read("acuity"):
        kind = row["record_type"]
        text = row["infant_body_system"]
        if kind == "title":
            title = _clean(text)
        elif kind == "footnote":
            footnote = _clean(text).lstrip("*").strip()
        elif kind == "table_row":
            system = _clean(text)
            if system.lower() == "nursing care":
                # Not a finding: how often each column is assessed.
                assessment = {c["key"]: _clean(row[c["csv"]]) for c in RATIO_COLUMNS}
                continue
            sid = _slug(system)
            items = {}
            for c in RATIO_COLUMNS:
                items[c["key"]] = [
                    {
                        "id": f"{sid}.{c['key']}.{i}",
                        "label": label.rstrip("*").strip(),
                        # An asterisk marks a finding the footnote makes 1:1.
                        "one_to_one": label.endswith("*"),
                    }
                    for i, label in enumerate(_bullets(row[c["csv"]]))
                ]
            systems.append({"id": sid, "system": system, "items": items})

    columns = [
        {k: c[k] for k in ("key", "name", "ratio", "planning_ratio", "band",
                           "nurses_per_infant", "nurse_level")}
        | {"assessment": assessment.get(c["key"], "")}
        for c in RATIO_COLUMNS
    ]
    one_to_one = {
        "id": ONE_TO_ONE_ID,
        "label": "Hemodynamically unstable, needing nurse interventions every 15 minutes",
        "note": footnote,
    }
    return {"title": title, "columns": columns, "systems": systems, "one_to_one": one_to_one}


def _load_levels(name: str, prefix: str) -> dict:
    title, note, criteria = "", "", []
    for row in _read(name):
        kind = row["record_type"]
        text = _clean(row["criterion_or_note"])
        if kind == "title":
            title = text
        elif kind == "document_note":
            note = text
        elif kind == "criterion":
            level = next(
                (cl["level"] for cl in CARE_LEVELS if row[cl["csv"]].strip().upper() == "X"),
                None,
            )
            if level is not None:
                criteria.append({"id": f"{prefix}.{row['row_order']}", "label": text, "level": level})
        # handwritten_annotation rows are ignored by design.
    return {"title": title, "note": note, "criteria": criteria}


def _build() -> tuple[dict, dict]:
    acuity = _load_acuity()
    levels = {
        "general": _load_levels("general", "loc"),
        "hyperbilirubinemia": _load_levels("hyperbilirubinemia", "bili"),
    }
    tool = {
        "source": SOURCE,
        **acuity,
        "care_levels": [{k: c[k] for k in ("level", "code", "name")} for c in CARE_LEVELS],
        "levels_of_care": levels,
    }

    index: dict[str, dict] = {}
    for system in acuity["systems"]:
        for key, items in system["items"].items():
            for item in items:
                index[item["id"]] = {"kind": "acuity", "column": key,
                                     "system": system["system"], **item}
    index[ONE_TO_ONE_ID] = {"kind": "acuity", "column": "intensive", "system": "1:1 staffing",
                            "id": ONE_TO_ONE_ID, "label": acuity["one_to_one"]["label"],
                            "one_to_one": True}
    for group in levels.values():
        for crit in group["criteria"]:
            index[crit["id"]] = {"kind": "care_level", **crit}
    return tool, index


TOOL, FINDINGS = _build()


def classify(findings: Iterable[str] | None) -> dict | None:
    """Classify one infant from the finding ids ticked for it.

    Returns None when no recognised finding is given, so callers can fall back
    to the modelled acuity.
    """
    chosen = [FINDINGS[f] for f in (findings or []) if f in FINDINGS]
    if not chosen:
        return None

    acuity = [c for c in chosen if c["kind"] == "acuity"]
    care = [c for c in chosen if c["kind"] == "care_level"]
    care_level = max((c["level"] for c in care), default=None)

    if acuity:
        column = RATIO_COLUMNS[min(COLUMN_RANK[c["column"]] for c in acuity)]
    else:
        column = RATIO_COLUMNS[COLUMN_RANK[CARE_LEVEL_COLUMN[care_level]]]
    one_to_one = any(c["one_to_one"] for c in acuity)
    staffing = ONE_TO_ONE if one_to_one else {
        "ratio": column["planning_ratio"],
        "nurses_per_infant": column["nurses_per_infant"],
        "nurse_level": column["nurse_level"],
    }

    # The findings that actually decided the result.
    reasons = [
        c["label"] for c in chosen
        if (c["kind"] == "acuity"
            and (c["one_to_one"] if one_to_one else c["column"] == column["key"]))
        or (c["kind"] == "care_level" and c["level"] == care_level)
    ]

    return {
        "column": column["key"],
        "column_name": column["name"],
        "ratio": staffing["ratio"],
        "band": column["band"],
        "nurses_per_infant": staffing["nurses_per_infant"],
        "one_to_one": one_to_one,
        "care_level": care_level,
        "care_level_code": CARE_BY_LEVEL[care_level]["code"] if care_level else None,
        "required_level": max(staffing["nurse_level"], care_level or 1),
        "assessment": next(c["assessment"] for c in TOOL["columns"] if c["key"] == column["key"]),
        "reasons": reasons,
    }
