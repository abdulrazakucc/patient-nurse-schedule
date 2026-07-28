# NeoStay - Infant NICU Outcome & Staffing Intelligence

An internal, **local-only** decision-support web application for Very Low Birth Weight
(VLBW) infants. Enter a newborn's **birth weight** and **gestational age** and NeoStay
forecasts:

- **Expected length of stay** (median + interquartile range)
- **Disposition likelihood** - Home / Transfer / Died
- **Survival probability**
- **Nurse-staffing demand** - NHPPD, peak nurse:infant ratio, nurse-hours, 12h shifts

Admission **health condition** (stable → critical) and **respiratory support** (room air →
ventilator) refine the acuity. A dedicated **Unit Scheduling** page aggregates a live
census of infants into acuity-based nurses-per-shift and daily staffing demand.

The app is **multi-page** with a shared clickable navigation bar:

| Page | File | Purpose |
|------|------|---------|
| Home | `index.html` | Overview + headline stats + navigation cards |
| Predict | `predict.html` | Per-infant outcome & staffing forecast |
| Scheduling | `schedule.html` | Unit census → nurses per shift |
| Analytics | `analytics.html` | Population charts |
| About | `about.html` | Methodology |

> ⚠️ Decision-support prototype only. Not a substitute for clinical judgment. All data
> stays on the local machine - nothing is pushed anywhere.

---

## Data

Source files live in [`losdata/`](losdata/) and are **aggregated statistics** (N, Median,
Q1, Q3) - not patient-level records:

| File | Contents |
|------|----------|
| `...by-Birth Wgt 10 Levels-survival.csv` | LOS by disposition (Home/Transfer/Died/All), predicted & total LOS, per birth-weight bin |
| `...Total Length Of Stay_...by-Birth Wgt 10 Levels.csv` | Total & predicted LOS per birth-weight bin |
| `...Total Length Of Stay_...by-GA Week.csv` | Total LOS per gestational-age week |

Matching PNG/PDF renderings are included for reference.

## How predictions are produced

Because the data is aggregated, the engine:

1. Locates the birth-weight bin (10 levels) and GA-week bin for the input.
2. **Linearly interpolates** the median/IQR between neighbouring bin mid-points so each
   gram and week matters.
3. **Blends** the weight-based and GA-based LOS estimates.
4. Derives **disposition & survival** probabilities from the empirical case counts (N)
   in the survival dataset, and attaches a **confidence** signal based on sample size.

Nurse staffing follows **AAP / AWHONN** acuity-based nurse:patient ratios, modelling the
stay as intensive (1:1), intermediate (1:2) and convalescent (1:3) phases.

## Project structure

```
patient-nurse-schedule/
├── backend/
│   ├── app/
│   │   ├── data_loader.py   # CSV parsing + bin definitions
│   │   ├── predictor.py     # LOS / disposition / survival engine
│   │   ├── nursing.py       # acuity-based staffing estimator
│   │   └── main.py          # FastAPI app + static hosting
│   └── requirements.txt
├── frontend/                # multi-page UI (HTML/CSS + per-page JS + Chart.js)
│   ├── components.js        # shared nav/footer, active-link highlighting
│   ├── index.html · predict.html · schedule.html · analytics.html · about.html
│   └── styles.css
├── losdata/                 # source datasets (local only)
└── run.sh
```

## Run it

```bash
./run.sh
```

Then open <http://127.0.0.1:8000>.

Manual alternative:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
cd backend
uvicorn app.main:app --reload
```

## API

| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `/api/health` | Service status |
| GET | `/api/meta` | Centers + weight/GA bins |
| GET | `/api/analytics` | Aggregated distributions for charts |
| POST | `/api/predict` | Per-infant forecast (`{weight_g, ga_weeks, center, condition, resp_support, notes}`) |
| POST | `/api/schedule` | Unit staffing from a census (`{infants:[...], shifts_per_day}`) |

Interactive docs at <http://127.0.0.1:8000/docs>.

## Roadmap (planned)

- Nurse **shift rostering** (assigning named nurses to shifts, not just counts).
- Persisting the census and admission notes to a datastore.
- Multi-center comparison (Center 1 vs Center 267) once per-center data is available.
