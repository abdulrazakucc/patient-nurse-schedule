# NeoStay Generated Datasets

This folder contains **synthetic (made up but realistic) data** for the neonatal unit.
It was created by the script [`datagen/generate.py`](../datagen/generate.py).

Please read this first. It explains, in plain language, what each file is, where the
numbers come from, and how an expert can later swap this synthetic data for the real
thing.

> **Important:** No real babies or nurses are in these files. Every row is generated
> by a computer program. However, the program was carefully tuned so the data looks
> and behaves like real hospital data, so it is useful for designing reports, testing
> the software, and agreeing on what real data we should start collecting.

---

## Why this data exists

The real data we received (in the [`losdata/`](../losdata) folder) is **summarised**.
It tells us things like "for babies weighing 701 to 800 grams, the middle length of
stay was about 100 days." It does **not** contain a row for each individual baby, and
it says nothing about nurses.

To build and demonstrate:

1. individual baby journeys hour by hour, and
2. how many nurses are needed at each hour of the day,

we need patient-level and nurse-level data. Since that does not exist yet, we
**generate** it in a way that stays faithful to the real summary numbers. Later, when
the experts pull genuine records from the hospital systems, those records can replace
these files with no change to the software, because they use the same columns.

---

## How the synthetic data stays true to the real data

Think of the real summary as a recipe, and this generator as a cook following it:

| Real summary tells us... | ...and the generator does this |
|---|---|
| How many babies were in each weight band (the "N" counts) | Creates exactly that many babies in each band |
| The typical (median) and spread (Q1 to Q3) of length of stay | Draws each baby's stay from a bell-shaped curve with that same middle and spread |
| What fraction went Home, were Transferred, or Died | Assigns each baby an outcome using those same proportions |
| (from clinical guidelines) how many nurses a baby needs by acuity | Assigns nurse workload per hour using standard 1:1, 1:2, 1:3 ratios |

So if you add up the generated babies, you get back the real counts. If you look at
the middle length of stay per band, it matches the real median. The synthetic data is
"anchored" to reality.

---

## The files, one by one

### 1. `infants.csv` - one row per baby

Each row is a single (synthetic) baby admitted to the unit.

| Column | Plain-language meaning |
|---|---|
| `infant_id` | A made-up ID for the baby, like a hospital number (e.g. INF-0187) |
| `center` | Which hospital center |
| `birth_weight_g` | Birth weight in grams |
| `gestational_age_weeks` | How many weeks pregnant the mother was at birth (lower = more premature) |
| `birth_weight_band` | The weight group this baby falls into (matches the real data bands) |
| `admission_datetime` | When the baby arrived in the unit |
| `discharge_datetime` | When the baby left the unit |
| `length_of_stay_days` | How many days the baby stayed |
| `disposition` | What happened at the end: Home, Transfer, or Died |
| `admission_condition` | How sick the baby was on arrival: stable, guarded, serious, or critical |
| `respiratory_support` | Breathing help needed: room air, nasal cannula, CPAP, or ventilator |
| `acuity_severity` | A 0-to-1 sickness score (higher = sicker), used to plan nursing |

### 2. `nurses.csv` - one row per nurse

The staff who could be rostered onto shifts.

| Column | Plain-language meaning |
|---|---|
| `nurse_id` | A made-up staff ID (e.g. RN-014) |
| `full_name` | The nurse's name |
| `credential` | Their qualification (RN, BSN, NNP, etc.) |
| `specialty` | The kind of care they focus on |
| `years_experience` | How many years they have worked |
| `hire_date` | When they joined |
| `employment` | Full-time or part-time |

### 3. `infant_hourly_acuity.csv` - each baby's journey through time

This is the "time series" for babies. It records, at regular points during each
baby's stay, how much nursing care they needed. To keep the file a sensible size we
record a point every 6 hours (still fine detail for a stay measured in weeks).

| Column | Plain-language meaning |
|---|---|
| `infant_id` | Which baby this row belongs to |
| `timestamp` | The exact date and time of this reading |
| `hour_of_stay` | How many hours since the baby was admitted |
| `day_of_stay` | The same thing expressed in days |
| `care_phase` | The stage of care: intensive, intermediate, or convalescent |
| `nurses_required` | How much of a nurse this baby needs right now (1.0 = a whole nurse, 0.5 = shares a nurse with one other baby, 0.33 = one nurse for three babies) |

Babies typically start in the **intensive** phase (needing a whole nurse each), then
move to **intermediate**, and finally **convalescent** (feeding and growing) before
going home. Sicker and smaller babies spend longer in the intensive phase.

### 4. `unit_hourly_staffing.csv` - the whole unit, hour by hour

This is the "time series" for the ward as a whole. For every hour that the unit had at
least one baby, it records how busy the unit was and how many nurses were on duty.

| Column | Plain-language meaning |
|---|---|
| `timestamp` | The date and hour |
| `hour` | Hour of the day (0 to 23) |
| `shift` | Which nursing shift this hour falls in (Day 07-19 or Night 19-07) |
| `census` | How many babies were in the unit that hour |
| `nurse_demand` | The total nurse requirement, adding up every baby's need |
| `bedside_nurses_scheduled` | Bedside nurses needed (the demand rounded up) |
| `charge_nurses_scheduled` | The supervising nurse (always 1 when the unit is open) |
| `nurses_on_duty` | Total nurses on duty (bedside + charge) |

### 5. `nurse_shift_roster.csv` - who worked which shift

This is the staffing schedule: named nurses assigned to day and night shifts.

| Column | Plain-language meaning |
|---|---|
| `shift_id` | A made-up ID for the shift |
| `date` | The calendar day |
| `shift` | Day (07-19) or Night (19-07) |
| `nurse_id` | Which nurse |
| `nurse_name` | The nurse's name |
| `role` | Charge Nurse (the shift leader) or Bedside Nurse |

---

## How the files connect

```
infants.csv ────< infant_hourly_acuity.csv      (a baby has many hourly readings)
     │
     └── all babies present in an hour add up to ──> unit_hourly_staffing.csv
                                                              │
nurses.csv ────< nurse_shift_roster.csv <── staffing need per shift comes from ─┘
```

`infant_id` links the babies to their hourly readings. `nurse_id` links nurses to the
shift roster. The unit staffing file is the bridge: it is the sum of all babies'
needs, and it drives how many nurses the roster must supply.

---

## For the experts: collecting the real version

When you are ready to replace this synthetic data with genuine records, aim to collect
the same columns. In practice these come from systems you already have:

* **`infants.csv`** - from the admission / discharge (ADT) system and the badgernet /
  neonatal record: weight, gestational age, admit and discharge times, outcome.
* **`infant_hourly_acuity.csv`** - from the nursing acuity tool or the electronic
  observation chart, which already records care level at each shift.
* **`nurses.csv`** and **`nurse_shift_roster.csv`** - from the workforce / e-rostering
  system (for example allocate, healthroster).
* **`unit_hourly_staffing.csv`** - this one you do not need to collect by hand. It can
  be calculated automatically from the other four.

If the real files use these column names, NeoStay will read them directly.

---

## Regenerating

To rebuild every file from scratch (the result is identical each time because the
random seed is fixed):

```bash
source .venv/bin/activate
python datagen/generate.py
```
