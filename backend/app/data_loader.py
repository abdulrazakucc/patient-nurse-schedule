"""
Data loader for Center VLBW (Very Low Birth Weight) infant length-of-stay datasets.

The source CSV files are aggregated statistics (not patient-level records). Each file
is organised as a wide table:

    Row 0 : group headers (birth-weight bins OR gestational-age week bins) each
            spanning 4 columns.
    Row 1 : the 4 sub-columns for every group -> N, Median, Q1, Q3
    Row 2+: one metric per row (e.g. "Total Length Of Stay", disposition rows...)

This module parses those files into a tidy, queryable structure and exposes the
empirical distributions used by the prediction and staffing engines.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
DATA_DIR = Path(__file__).resolve().parents[2] / "losdata"

FILES = {
    "survival_by_weight": "Center-1_2016-to-2026__All VLBW Infants_by-Birth Wgt 10 Levels-survival.csv",
    "los_by_weight": "Center-1_2016-to-2026__Total Length Of Stay_All VLBW Infants_by-Birth Wgt 10 Levels.csv",
    "los_by_ga": "Center-1_2016-to-2026__Total Length Of Stay_All VLBW Infants_by-GA Week.csv",
}


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------
@dataclass
class Stat:
    """A single N / Median / Q1 / Q3 cell group for one metric & one bin."""

    n: Optional[int] = None
    median: Optional[float] = None
    q1: Optional[float] = None
    q3: Optional[float] = None

    def as_dict(self) -> dict:
        return {"n": self.n, "median": self.median, "q1": self.q1, "q3": self.q3}


@dataclass
class Bin:
    """An ordered categorical bin (weight range or GA week) with a numeric key."""

    label: str
    # representative numeric midpoint used for interpolation (grams or weeks)
    midpoint: float
    low: float
    high: float


# ---------------------------------------------------------------------------
# Bin definitions (mid-points chosen for interpolation)
# ---------------------------------------------------------------------------
WEIGHT_BINS = [
    Bin("< 501 g", 450, 0, 500),
    Bin("501-600 g", 550, 501, 600),
    Bin("601-700 g", 650, 601, 700),
    Bin("701-800 g", 750, 701, 800),
    Bin("801-900 g", 850, 801, 900),
    Bin("901-1000 g", 950, 901, 1000),
    Bin("1001-1100 g", 1050, 1001, 1100),
    Bin("1101-1200 g", 1150, 1101, 1200),
    Bin("1201-1300 g", 1250, 1201, 1300),
    Bin("1301-1400 g", 1350, 1301, 1400),
    Bin("> 1400 g", 1500, 1401, 2500),
]

GA_BINS = [
    Bin("< 22 Weeks", 21, 0, 22),
    Bin("22 Weeks", 22, 22, 23),
    Bin("23 Weeks", 23, 23, 24),
    Bin("24 Weeks", 24, 24, 25),
    Bin("25 Weeks", 25, 25, 26),
    Bin("26 Weeks", 26, 26, 27),
    Bin("27 Weeks", 27, 27, 28),
    Bin("28 Weeks", 28, 28, 29),
    Bin("29 Weeks", 29, 29, 30),
    Bin("30 Weeks", 30, 30, 31),
    Bin("31 Weeks", 31, 31, 32),
    Bin("32 Weeks", 32, 32, 33),
    Bin("33 Weeks", 33, 33, 34),
    Bin("34 Weeks", 34, 34, 35),
    Bin("35 Weeks", 35, 35, 36),
    Bin("36 Weeks", 36, 36, 37),
    Bin("37 Weeks", 37, 37, 38),
    Bin("> 37 Weeks", 38, 38, 42),
]


def _to_float(value: str) -> Optional[float]:
    value = (value or "").strip()
    if value == "":
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _to_int(value: str) -> Optional[int]:
    f = _to_float(value)
    return int(f) if f is not None else None


def _parse_file(path: Path) -> dict[str, dict[str, Stat]]:
    """Parse one wide CSV into {metric_label: {bin_label: Stat}}."""
    with path.open(newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.reader(fh))

    header = rows[0]
    # Each group spans 4 data columns (N, Median, Q1, Q3) beginning at column 1.
    # The group label is written into the 2nd cell of that block (columns 2, 6, 10...).
    group_labels: list[str] = []
    col = 2
    while col < len(header):
        label = header[col].strip()
        group_labels.append(label)
        col += 4

    metrics: dict[str, dict[str, Stat]] = {}
    for row in rows[2:]:
        if not row or not row[0].strip():
            continue
        metric = row[0].strip()
        per_bin: dict[str, Stat] = {}
        for gi, glabel in enumerate(group_labels):
            base = 1 + gi * 4
            if base + 3 >= len(row):
                break
            per_bin[glabel] = Stat(
                n=_to_int(row[base]),
                median=_to_float(row[base + 1]),
                q1=_to_float(row[base + 2]),
                q3=_to_float(row[base + 3]),
            )
        metrics[metric] = per_bin
    return metrics


@dataclass
class Dataset:
    center: str = "Center 1"
    period: str = "2016–2026"
    survival_by_weight: dict[str, dict[str, Stat]] = field(default_factory=dict)
    los_by_weight: dict[str, dict[str, Stat]] = field(default_factory=dict)
    los_by_ga: dict[str, dict[str, Stat]] = field(default_factory=dict)

    def weight_bin_labels(self) -> list[str]:
        return [b.label for b in WEIGHT_BINS]

    def ga_bin_labels(self) -> list[str]:
        return [b.label for b in GA_BINS]


def load_dataset() -> Dataset:
    ds = Dataset()
    ds.survival_by_weight = _parse_file(DATA_DIR / FILES["survival_by_weight"])
    ds.los_by_weight = _parse_file(DATA_DIR / FILES["los_by_weight"])
    ds.los_by_ga = _parse_file(DATA_DIR / FILES["los_by_ga"])
    return ds


# Singleton, loaded once at import time.
DATASET = load_dataset()
