# Patient-journey model

The **Journey** page and the `/api/journey` routes predict, for a baby already in the unit:

- **Remaining stay.** The chance that the baby is still on the board at each 12-hour board over the next 28 days. From that curve come the median remaining stay, its middle half, and the chance of having left within 1, 3, 7, 14 and 28 days.
- **Nurse-ratio journey.** For each of the next 14 boards (7 days): the chance of each nurse:patient ratio if the baby is still in the unit, the chance of each ratio overall, and the expected bedside nurses at both ends of the ratio ranges.

The models are trained in the separate **acuity-models** project on the unit's own anonymised acuity boards. They reach NeoStay as a single JSON file, the *bundle*. This repository contains no trained model and no hospital data. Its tests use bundles fitted to made-up data (`tests/fixtures/journey/`).

## How it fits together

| Part | File | Role |
|---|---|---|
| Runtime (Python) | `backend/app/journey_runtime.py` | Turns a board entry into features and evaluates the bundle with numpy only. Vendored unchanged from `acuity-models/src/acuity_ml/runtime.py`. |
| Loader and API | `backend/app/journey.py`, `backend/app/main.py` | Loads the bundle and runs its check cases. Serves the routes below. |
| Runtime (browser) | `frontend/journey-engine.js` | JavaScript port of the runtime, so the page computes in the browser. |
| Page | `frontend/journey.html`, `frontend/journey.js` | Form for one board entry, plus charts and a table of the journey. |
| Tests | `tests/test_journey.py`, `tests/test_journey_parity.py` | Cover the API behaviour. Check that the browser engine and the Python runtime agree value for value on every fixture bundle. |

Training and serving share one definition of the features: the training project computes every feature with the same `runtime.py`. Each bundle carries check cases (made-up inputs with their expected outputs). The server runs them when it loads the bundle, and the page runs them in the browser. A bundle whose results do not reproduce is refused.

## Installing a model

1. In acuity-models, build the data, run the study and export:

   ```bash
   python -m acuity_data.build
   python -m acuity_ml.dataset
   python -m acuity_ml.experiment
   python -m acuity_ml.export     # writes data/models/neostay-journey.json
   ```

2. Copy the bundle to the NeoStay server's instance folder:

   ```bash
   mkdir -p instance/models
   cp ../acuity-models/data/models/neostay-journey.json instance/models/
   ```

   You can also set `NEOSTAY_MODEL_FILE` to another path. `instance/` is git-ignored and server-private, so the bundle is never committed.

   In the container (docs/DEPLOYMENT.md) the instance folder is the `neostay-instance` volume:

   ```bash
   docker compose exec app mkdir -p /srv/instance/models
   docker compose cp neostay-journey.json app:/srv/instance/models/neostay-journey.json
   ```

3. There is no need to restart. The server reloads the file whenever it changes. Check with `GET /api/journey/model`.

If no model is installed, or the installed one fails its checks, the journey routes answer **503** with the reason. The rest of NeoStay is unaffected.

The published GitHub Pages copy does **not** include the model. Its Journey page says the model is available on a NeoStay server only. Putting a model fitted to hospital data on a public site, even encrypted, is a governance decision; see below.

## API

All routes need a signed-in session, like the rest of `/api/`.

| Route | Answer |
|---|---|
| `GET /api/journey/model` | Model card: version, training period and size, selection and test performance, privacy audit, intended use, and the allowed input values (`inputs`). No parameters. |
| `GET /api/journey/bundle` | The whole bundle, for the browser engine. |
| `POST /api/journey` | The journey of one baby. |
| `POST /api/journey/unit` | Summed over up to 64 babies: expected census, expected babies at each ratio, and expected nurses for each coming board. Covers today's babies only; future admissions are not included. |

### Request

```json
{
  "record": {
    "ga_weeks": 29.5, "bw_g": 1250, "dol": 12, "weight_g": 1380,
    "shifts_in_unit": 24, "shift": "AM", "day_of_week": "Wednesday",
    "acuity_ratio": "1:2", "resp_status": "CPAP", "feeds": "OG/NG-advancing",
    "iv_lines": ["PICC"], "iv_fluids": false, "iv_saline_lock": false,
    "spells": "self_resolved", "nas_band": null, "procedure": null,
    "care_area": "icu", "has_education_need": false
  },
  "history": [
    {"shifts_ago": 1, "acuity_ratio": "1:2", "resp_status": "CPAP"},
    {"shifts_ago": 2, "acuity_ratio": "1:2-3", "weight_g": 1350}
  ]
}
```

- `record` is the current board entry. `ga_weeks`, `bw_g`, `shifts_in_unit`, `shift` and `day_of_week` are required. Any other field may be null when it is not recorded.
- `shifts_in_unit` counts 12-hour shifts since admission: 0 on the admission shift.
- `history` lists earlier entries of the same stay, 1 to 14 shifts ago. Leave out shifts that were not recorded. Each entry takes the per-shift fields of `record`.
- The allowed labels (ratios, respiratory, feeds, spells, NAS bands, procedures, care areas, line types) are listed under `inputs` in `GET /api/journey/model`. They match the labels on the acuity board.
- Input the runtime cannot read is refused with **422** and the reason: an unknown label, a value out of range, a history entry dated before admission, or an unknown field.

### Response (abridged)

```json
{
  "model_version": "2026-10-29-1a2b3c4d5e",
  "remaining_stay": {
    "survival": [0.98, 0.96, "... 56 values, one per board ahead"],
    "p_gone_by_day": {"1": 0.04, "3": 0.12, "7": 0.31, "14": 0.55, "28": 0.81},
    "median_days": 11.5, "quartile_days": [4.0, 24.5],
    "beyond_horizon": false, "horizon_days": 28.0
  },
  "acuity_journey": [
    {"shifts_ahead": 1, "hours_ahead": 12, "p_in_unit": 0.98,
     "ratio_if_in_unit": {"1:3-4": 0.01, "1:3": 0.05, "1:2-3": 0.12, "1:2": 0.80, "1:1": 0.02},
     "ratio": {"1:3-4": 0.0098, "...": "..."},
     "expected_nurses": {"min": 0.46, "max": 0.49}}
  ]
}
```

- **Remaining stay** counts the further boards the baby appears on, in days. 0 means gone before the next board. When the median lies beyond 28 days, `median_days` is null and `beyond_horizon` is true.
- **`expected_nurses`** applies the unit's ratio ranges at both ends: 1:2-3 is 1/3 to 1/2 of a nurse. The charge nurse is not included.

## Other apps (mobile, desktop, web)

- **Through the server.** Call `POST /api/journey` from any app that can reach a NeoStay server. This is the simplest route: the app sends JSON and reads JSON.
- **On the device.** Load the bundle (`GET /api/journey/bundle`) and evaluate it with `frontend/journey-engine.js` (any JavaScript runtime) or `journey_runtime.py` (any Python with numpy). Run the bundle's check cases first (`NeoJourney.load` / `journey_runtime.self_check`). The bundle then stays on the device; whoever holds it holds the model.

## Governance before clinical use

The training project produces the evidence. These steps are the unit's to take:

1. **Model card sign-off.** The clinical lead reviews the study notebooks (05 and 06 in acuity-models) and the card served at `/api/journey/model`, and signs off.
2. **Silent run.** Run the model prospectively without showing it, record its predictions, and compare them with what happens before anyone sees the predictions in practice.
3. **Data governance.** The bundle holds no identifiers, dates of stays or patient rows. Its privacy audit lists the smallest number of stays behind any number in it. It is still fitted to hospital data: decide where it may be stored and who may download it before installing it on any shared server or publishing it anywhere.
4. **Retraining.** When new boards are added, rerun the four commands above. The data build validates the new boards, the study reruns its cross-validation and test, and the export refuses a bundle that the runtime does not reproduce. Install a new bundle only after the same review.

The model supports planning. It is not a basis for any decision about an individual baby's care.
