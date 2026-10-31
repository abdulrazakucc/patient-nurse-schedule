"use strict";
/* ============================================================================
   NeoStay patient-journey engine.

   A faithful JavaScript port of backend/app/journey_runtime.py, so a journey
   can be computed in the browser from a model bundle: no patient data leaves
   the device. Every bundle carries check cases; NeoJourney.load() runs them
   and refuses a bundle whose results this engine does not reproduce.
   tests/test_journey_parity.py runs this file against the Python runtime.
   ============================================================================ */
(function () {
  const BUNDLE_FORMAT = "neostay-journey/1";
  const DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
  const SHIFTS = ["AM", "PM"];
  const STATIC_FIELDS = ["ga_weeks", "bw_g"];
  const SHIFT_FIELDS = ["acuity_ratio", "dol", "weight_g", "resp_status", "resp_flow_lpm", "resp_peep", "feeds",
    "iv_lines", "iv_fluids", "iv_saline_lock", "spells", "nas_band", "procedure", "care_area", "has_education_need"];
  const RECORD_FIELDS = STATIC_FIELDS.concat(SHIFT_FIELDS, ["shifts_in_unit", "shift", "day_of_week"]);

  class InputError extends Error {
    constructor(message) {
      super(message);
      this.kind = "input";
    }
  }

  const has = (obj, key) => Object.prototype.hasOwnProperty.call(obj, key);
  const isNum = (v) => typeof v === "number";
  const allowedHas = (allowed, v) => (Array.isArray(allowed) ? allowed.includes(v) : has(allowed, v));

  /* ---------------- input checks ---------------- */
  function number(value, name) {
    if (value === null || value === undefined) return NaN;
    if (typeof value !== "number") throw new InputError(`${name} must be a number or null`);
    if (!Number.isFinite(value) && !Number.isNaN(value)) throw new InputError(`${name} must be finite`);
    return value;
  }

  function inRange(value, name, ranges) {
    if (!Number.isNaN(value) && has(ranges, name)) {
      const [lo, hi] = ranges[name];
      if (!(lo <= value && value <= hi)) throw new InputError(`${name}=${value} is outside the valid range ${lo}-${hi}`);
    }
    return value;
  }

  function flag(value, name) {
    if (value === null || value === undefined) return false;
    if (typeof value !== "boolean") throw new InputError(`${name} must be true, false or null`);
    return value;
  }

  function choice(value, name, allowed) {
    if (value === null || value === undefined) return null;
    if (!allowedHas(allowed, value)) throw new InputError(`${name}=${JSON.stringify(value)} is not an allowed value`);
    return value;
  }

  /* ---------------- features ---------------- */
  function shiftFeatures(entry, tables) {
    for (const key of Object.keys(entry)) {
      if (!SHIFT_FIELDS.includes(key) && key !== "shifts_ago" && !RECORD_FIELDS.includes(key)) {
        throw new InputError(`unknown fields: ${key}`);
      }
    }
    const ranges = tables.valid_ranges;
    const f = {};
    const ratio = choice(entry.acuity_ratio, "acuity_ratio", tables.acuity_level);
    f.acuity_level = ratio ? tables.acuity_level[ratio] : NaN;
    f.dol = inRange(number(entry.dol, "dol"), "dol", ranges);
    f.weight_g = inRange(number(entry.weight_g, "weight_g"), "weight_g", ranges);

    const resp = choice(entry.resp_status, "resp_status", tables.resp_status);
    const r = resp ? tables.resp_status[resp] : { mode: null, tier: null, ino: false };
    f.resp_mode = r.mode;
    f.resp_tier = r.tier === null ? NaN : r.tier;
    f.resp_ino = Boolean(r.ino);
    f.resp_flow_lpm = number(entry.resp_flow_lpm, "resp_flow_lpm");
    f.resp_peep = number(entry.resp_peep, "resp_peep");

    const feeds = choice(entry.feeds, "feeds", tables.feeds);
    f.feeds = feeds;
    Object.assign(f, feeds ? tables.feeds[feeds] : tables.feeds_missing);

    const lines = entry.iv_lines || [];
    if (!Array.isArray(lines)) throw new InputError("iv_lines must be a list");
    const iv = tables.iv;
    lines.forEach((t) => choice(t, "iv_lines", iv.tokens));
    iv.tokens.forEach((t) => {
      f[`iv_${t.toLowerCase()}`] = lines.includes(t);
    });
    f.iv_fluids = flag(entry.iv_fluids, "iv_fluids");
    f.iv_saline_lock = flag(entry.iv_saline_lock, "iv_saline_lock");
    f.iv_central = iv.central.some((t) => lines.includes(t));
    f.iv_arterial = iv.arterial.some((t) => lines.includes(t));
    f.iv_line_count = new Set(lines).size;

    const spells = choice(entry.spells || "not_recorded", "spells", tables.spells);
    f.spells = spells;
    Object.assign(f, tables.spells[spells]);
    f.nas_band = choice(entry.nas_band, "nas_band", tables.nas_band);
    f.nas_scoring = f.nas_band !== null;
    f.procedure = choice(entry.procedure, "procedure", tables.procedure);
    f.care_area = choice(entry.care_area, "care_area", tables.care_area);
    f.has_education_need = flag(entry.has_education_need, "has_education_need");
    return f;
  }

  const known = (values) => values.filter((v) => !Number.isNaN(v));

  function computeFeatures(record, history, tables, historyShifts) {
    const ranges = tables.valid_ranges;
    const f = shiftFeatures(record, tables);
    f.ga_weeks = inRange(number(record.ga_weeks, "ga_weeks"), "ga_weeks", ranges);
    f.bw_g = inRange(number(record.bw_g, "bw_g"), "bw_g", ranges);
    f.cga_weeks = f.ga_weeks + f.dol / 7;

    const stay = record.shifts_in_unit;
    if (!Number.isInteger(stay) || stay < 0) throw new InputError("shifts_in_unit must be a whole number >= 0");
    f.shifts_in_unit = Math.min(stay, historyShifts);
    f.shift = choice(record.shift, "shift", SHIFTS);
    f.day_of_week = choice(record.day_of_week, "day_of_week", DAY_NAMES);
    if (f.shift === null || f.day_of_week === null) throw new InputError("shift and day_of_week are required");

    const past = new Map();
    for (const entry of history || []) {
      const k = entry.shifts_ago;
      if (!Number.isInteger(k) || k < 1 || k > historyShifts) {
        throw new InputError(`shifts_ago must be a whole number from 1 to ${historyShifts}`);
      }
      if (past.has(k)) throw new InputError(`two history entries for shifts_ago=${k}`);
      if (k > stay) throw new InputError(`history entry shifts_ago=${k} is before admission (shifts_in_unit=${stay})`);
      past.set(k, shiftFeatures(entry, tables));
    }
    const lag = (col, k) => (past.has(k) ? past.get(k)[col] : NaN);
    const pastValues = Array.from(past.values());

    const level = f.acuity_level;
    const tier = f.resp_tier;
    f.acuity_level_lag1 = lag("acuity_level", 1);
    f.acuity_level_lag2 = lag("acuity_level", 2);
    f.acuity_change_lag1 = level - f.acuity_level_lag1;
    const levels = known([level].concat(pastValues.map((p) => p.acuity_level)));
    f.acuity_level_max_window = levels.length ? Math.max(...levels) : NaN;
    f.acuity_level_min_window = levels.length ? Math.min(...levels) : NaN;
    f.acuity_level_mean_window = levels.length ? levels.reduce((a, b) => a + b, 0) / levels.length : NaN;
    let run = NaN;
    if (!Number.isNaN(level)) {
      run = 1;
      let k = 1;
      while (past.has(k) && past.get(k).acuity_level === level) {
        run += 1;
        k += 1;
      }
    }
    f.shifts_at_current_acuity = run;
    f.resp_tier_lag1 = lag("resp_tier", 1);
    f.resp_tier_lag2 = lag("resp_tier", 2);
    const tiers = known([tier].concat(pastValues.map((p) => p.resp_tier)));
    f.resp_tier_max_window = tiers.length ? Math.max(...tiers) : NaN;
    const weighed = Array.from(past.keys()).sort((a, b) => a - b).filter((k) => !Number.isNaN(past.get(k).weight_g));
    f.weight_change_g_per_day = NaN;
    if (weighed.length && !Number.isNaN(f.weight_g)) {
      const k = weighed[weighed.length - 1];
      f.weight_change_g_per_day = (f.weight_g - past.get(k).weight_g) / (k / 2);
    }
    return f;
  }

  function periodCalendar(shift, day, h) {
    const index = 2 * DAY_NAMES.indexOf(day) + SHIFTS.indexOf(shift) + h - 1;
    return [SHIFTS[index % 2], DAY_NAMES[Math.floor(index / 2) % 7]];
  }

  /* ---------------- encoding ---------------- */
  function encode(features, encoder, kind) {
    const out = [];
    for (const col of encoder.numeric) {
      let v = features[col.name];
      v = v === null || v === undefined ? NaN : Number(v);
      if (kind === "tree") {
        out.push(v);
        continue;
      }
      const missing = Number.isNaN(v);
      out.push(((missing ? col.fill : v) - col.mean) / col.scale);
      if (col.indicator) out.push(missing ? 1 : 0);
    }
    for (const name of encoder.boolean) out.push(features[name] ? 1 : 0);
    for (const col of encoder.categorical) {
      const value = features[col.name];
      for (const level of col.levels) out.push(value === level ? 1 : 0);
    }
    return out;
  }

  function periodBlock(spec, x, h, shift, day) {
    const out = [];
    if (spec.time_basis) {
      const u = Math.log(h) / Math.log(spec.time_basis.horizon);
      for (let j = 0; j < spec.time_basis.degree; j++) out.push(u ** (j + 1));
      for (const i of spec.time_basis.interact) out.push(x[i] * u);
    }
    if (spec.raw_h) out.push(h);
    if (spec.calendar) {
      const [pShift, pDay] = periodCalendar(shift, day, h);
      SHIFTS.forEach((s) => out.push(pShift === s ? 1 : 0));
      DAY_NAMES.forEach((d) => out.push(pDay === d ? 1 : 0));
    }
    return out;
  }

  /* ---------------- models ---------------- */
  const sigmoid = (z) => 1 / (1 + Math.exp(-z));
  const dot = (a, b) => {
    let s = 0;
    for (let i = 0; i < a.length; i++) s += a[i] * b[i];
    return s;
  };

  function softmax(z) {
    const m = Math.max(...z);
    const e = z.map((v) => Math.exp(v - m));
    const total = e.reduce((a, b) => a + b, 0);
    return e.map((v) => v / total);
  }

  function treeValue(trees, x) {
    let total = 0;
    for (const t of trees) {
      let node = 0;
      while (!t.leaf[node]) {
        const v = x[t.feature[node]];
        const goLeft = Number.isNaN(v) ? t.missing_left[node] : v <= t.threshold[node];
        node = goLeft ? t.left[node] : t.right[node];
      }
      total += t.value[node];
    }
    return total;
  }

  function survivalCurve(model, f) {
    const H = model.horizon;
    const kind = model.type;
    if (kind === "km") return model.survival.slice();
    if (kind === "km_by_level") {
      return (Number.isNaN(f.acuity_level) ? model.overall : model.by_level[f.acuity_level]).slice();
    }
    const x = encode(f, model.encoder, kind === "gbm_hazard" ? "tree" : "linear");
    if (kind === "cox") {
      const risk = Math.exp(dot(model.coef, x) + model.offset);
      return model.baseline_survival.map((s) => s ** risk);
    }
    const out = [];
    let s = 1;
    for (let h = 1; h <= H; h++) {
      const row = x.concat(periodBlock(model.period, x, h, f.shift, f.day_of_week));
      let hazard;
      if (kind === "logistic_hazard") hazard = sigmoid(dot(model.coef, row) + model.intercept);
      else if (kind === "gbm_hazard") hazard = sigmoid(model.baseline + treeValue(model.trees, row));
      else throw new InputError(`unknown survival model type ${kind}`);
      s *= 1 - hazard;
      out.push(s);
    }
    return out;
  }

  function acuityProbabilities(model, f) {
    const H = model.horizon;
    const n = model.n_levels;
    const kind = model.type;
    const out = [];
    for (let h = 0; h < H; h++) out.push(new Array(n).fill(0));
    if (kind === "transition") {
      for (let h = 1; h <= H; h++) {
        const table = model.table[h - 1];
        out[h - 1] = (Number.isNaN(f.acuity_level) ? table.marginal : table.by_level[f.acuity_level]).slice();
      }
      return out;
    }
    const x = encode(f, model.encoder, kind === "gbm_multiclass" ? "tree" : "linear");
    if (kind === "multinomial_per_h") {
      for (let h = 1; h <= H; h++) {
        const m = model.by_h[h - 1];
        const p = softmax(m.coef.map((row, k) => dot(row, x) + m.intercept[k]));
        m.classes.forEach((c, k) => {
          out[h - 1][c] = p[k];
        });
      }
      return out;
    }
    if (kind === "gbm_multiclass") {
      for (let h = 1; h <= H; h++) {
        const row = x.concat([h]);
        const p = softmax(model.classes.map((_, k) => model.baseline[k] + treeValue(model.trees[k], row)));
        model.classes.forEach((c, k) => {
          out[h - 1][c] = p[k];
        });
      }
      return out;
    }
    throw new InputError(`unknown acuity model type ${kind}`);
  }

  /* ---------------- the prediction ---------------- */
  function quantileShift(survival, q) {
    for (let i = 0; i < survival.length; i++) if (1 - survival[i] >= q - 1e-12) return i + 1;
    return null;
  }

  function predict(bundle, record, history) {
    if (!bundle || bundle.format !== BUNDLE_FORMAT) throw new InputError(`bundle format must be ${BUNDLE_FORMAT}`);
    for (const key of Object.keys(record)) {
      if (!RECORD_FIELDS.includes(key)) throw new InputError(`unknown fields: ${key}`);
    }
    const tables = bundle.inputs;
    const f = computeFeatures(record, history || [], tables, bundle.settings.history_shifts);
    const survival = survivalCurve(bundle.models.remaining_stay, f);
    const acuity = acuityProbabilities(bundle.models.acuity, f);
    const ratios = tables.acuity_ratios;
    const hours = bundle.settings.shift_hours;
    const days = (h) => (h === null ? null : ((h - 1) * hours) / 24);

    const median = quantileShift(survival, 0.5);
    const gone = {};
    for (const d of bundle.settings.report_days) {
      if ((d * 24) / hours <= survival.length) gone[String(d)] = 1 - survival[Math.trunc((d * 24) / hours) - 1];
    }
    const stay = {
      survival,
      p_gone_by_day: gone,
      median_days: days(median),
      quartile_days: [days(quantileShift(survival, 0.25)), days(quantileShift(survival, 0.75))],
      beyond_horizon: median === null,
      horizon_days: (survival.length * hours) / 24,
    };
    const journey = acuity.map((p, i) => {
      const present = survival[i];
      const ifIn = {};
      const joint = {};
      ratios.forEach((r, k) => {
        ifIn[r] = p[k];
        joint[r] = present * p[k];
      });
      return {
        shifts_ahead: i + 1,
        hours_ahead: (i + 1) * hours,
        p_in_unit: present,
        ratio_if_in_unit: ifIn,
        ratio: joint,
        expected_nurses: { min: present * dot(p, tables.nurse_fte_min), max: present * dot(p, tables.nurse_fte_max) },
      };
    });
    return { model_version: bundle.version, remaining_stay: stay, acuity_journey: journey };
  }

  function flatten(result) {
    const out = result.remaining_stay.survival.slice();
    result.acuity_journey.forEach((j) => Object.values(j.ratio).forEach((v) => out.push(v)));
    return out;
  }

  /* Run the bundle's check cases; throws when this engine does not reproduce them. */
  function selfCheck(bundle, tol) {
    const limit = tol === undefined ? 1e-9 : tol;
    (bundle.checks || []).forEach((c, i) => {
      const a = flatten(predict(bundle, c.record, c.history));
      const b = flatten(c.expected);
      if (a.length !== b.length || a.some((v, j) => !(Math.abs(v - b[j]) <= limit))) {
        throw new Error(`model check case ${i} does not reproduce its expected output`);
      }
    });
    return (bundle.checks || []).length;
  }

  function load(bundle) {
    selfCheck(bundle);
    return bundle;
  }

  window.NeoJourney = { predict, selfCheck, load, computeFeatures, InputError, DAY_NAMES, SHIFTS };
})();
