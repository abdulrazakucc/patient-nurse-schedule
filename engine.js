"use strict";
/* ============================================================================
   NeoStay client-side prediction & staffing engine.

   A faithful JavaScript port of backend/app/predictor.py and nursing.py so the
   whole application runs in the browser: no server, no data leaves the device.
   Reads the aggregated statistics bundled in data/neostay-data.js.
   ============================================================================ */
(function () {
  const D = window.NEOSTAY_DATA;

  const DISP_HOME = "Initial Length of Stay (By Disposition) - Home";
  const DISP_TRANSFER = "Initial Length of Stay (By Disposition) - Transfer";
  const DISP_DIED = "Initial Length of Stay (By Disposition) - Died";
  const DISP_ALL = "Initial Length of Stay (By Disposition) - All";
  const TOTAL_LOS = "Total Length Of Stay";

  const HOURS_PER_DAY = 24;
  const CONDITION_MODIFIERS = { stable: 0.0, guarded: 0.12, serious: 0.25, critical: 0.4 };
  const RESP_SUPPORT_MODIFIERS = { room_air: 0.0, nasal_cannula: 0.05, cpap: 0.15, ventilator: 0.3 };

  /* Match Python's round(): correct decimal rounding of the exact binary value,
     with ties going to the even digit. Works on the exact decimal expansion via
     toFixed so no scaling error creeps in. */
  const round = (v, nd = 1) => {
    if (v === null || v === undefined) return null;
    if (!isFinite(v)) return v;
    const neg = v < 0;
    const ext = Math.abs(v).toFixed(Math.min(100, nd + 18));
    const dot = ext.indexOf(".");
    const digits = (ext.slice(0, dot) + ext.slice(dot + 1, dot + 1 + nd)).replace(/^0+(?=\d)/, "");
    const rem = ext.slice(dot + 1 + nd);
    const tie = "5" + "0".repeat(rem.length - 1);
    let n = Number(digits);
    if (rem > tie) n += 1;
    else if (rem === tie && n % 2 === 1) n += 1;
    const r = n / 10 ** nd;
    return neg ? -r : r;
  };

  /* ---------------- prediction ---------------- */

  function findBin(value, bins, inclusiveHigh) {
    for (let i = 0; i < bins.length; i++) {
      if (inclusiveHigh ? value <= bins[i].high : value < bins[i].high) return i;
    }
    return bins.length - 1;
  }

  function interpStat(value, bins, perBin, attr) {
    const points = [];
    for (const b of bins) {
      const stat = perBin[b.label];
      if (stat && stat[attr] !== null && stat[attr] !== undefined) {
        points.push([b.midpoint, stat[attr]]);
      }
    }
    if (!points.length) return null;
    points.sort((a, b) => a[0] - b[0]);
    if (value <= points[0][0]) return points[0][1];
    if (value >= points[points.length - 1][0]) return points[points.length - 1][1];
    for (let i = 0; i < points.length - 1; i++) {
      const [x0, y0] = points[i];
      const [x1, y1] = points[i + 1];
      if (x0 <= value && value <= x1) {
        if (x1 === x0) return y0;
        return y0 + ((value - x0) / (x1 - x0)) * (y1 - y0);
      }
    }
    return points[points.length - 1][1];
  }

  function losEstimate(bins, perBin, value) {
    return {
      median: interpStat(value, bins, perBin, "median"),
      q1: interpStat(value, bins, perBin, "q1"),
      q3: interpStat(value, bins, perBin, "q3"),
    };
  }

  function confidence(n) {
    if (n === null || n === undefined) return "unknown";
    if (n >= 50) return "high";
    if (n >= 20) return "moderate";
    if (n >= 5) return "low";
    return "very low";
  }

  function predict(weightG, gaWeeks) {
    const wBins = D.weight_bins;
    const gBins = D.ga_bins;
    const weightBin = wBins[findBin(weightG, wBins, true)];
    const gaBin = gBins[findBin(gaWeeks, gBins, false)];

    const losW = losEstimate(wBins, D.los_by_weight[TOTAL_LOS] || {}, weightG);
    const losG = losEstimate(gBins, D.los_by_ga[TOTAL_LOS] || {}, gaWeeks);

    const blend = (a, b) => {
      const vals = [a, b].filter((v) => v !== null && v !== undefined);
      return vals.length ? vals.reduce((s, v) => s + v, 0) / vals.length : null;
    };
    const losBlended = {
      median: round(blend(losW.median, losG.median)),
      q1: round(blend(losW.q1, losG.q1)),
      q3: round(blend(losW.q3, losG.q3)),
    };

    const surv = D.survival_by_weight;
    const nOf = (row) => {
      const stat = (surv[row] || {})[weightBin.label];
      return stat && stat.n ? stat.n : 0;
    };
    const nHome = nOf(DISP_HOME);
    const nTransfer = nOf(DISP_TRANSFER);
    const nDied = nOf(DISP_DIED);
    const nAll = nOf(DISP_ALL) || nHome + nTransfer + nDied;

    let pHome = null, pTransfer = null, pDied = null;
    if (nAll > 0) {
      pHome = nHome / nAll;
      pTransfer = nTransfer / nAll;
      pDied = nDied / nAll;
    }
    const survivalProb = pDied !== null ? 1 - pDied : null;

    const dispLos = {};
    for (const [key, row] of [["home", DISP_HOME], ["transfer", DISP_TRANSFER], ["died", DISP_DIED]]) {
      const est = losEstimate(wBins, surv[row] || {}, weightG);
      dispLos[key] = { median: round(est.median), q1: round(est.q1), q3: round(est.q3) };
    }

    return {
      input: { weight_g: weightG, ga_weeks: gaWeeks },
      weight_bin: weightBin.label,
      ga_bin: gaBin.label,
      length_of_stay: {
        blended: losBlended,
        by_weight: { median: round(losW.median), q1: round(losW.q1), q3: round(losW.q3) },
        by_ga: { median: round(losG.median), q1: round(losG.q1), q3: round(losG.q3) },
        unit: "days",
      },
      disposition: {
        home: pHome !== null ? round(pHome * 100, 1) : null,
        transfer: pTransfer !== null ? round(pTransfer * 100, 1) : null,
        died: pDied !== null ? round(pDied * 100, 1) : null,
        unit: "percent",
      },
      survival_probability: survivalProb !== null ? round(survivalProb * 100, 1) : null,
      disposition_los: dispLos,
      sample_size: nAll,
      confidence: confidence(nAll),
    };
  }

  /* ---------------- nurse staffing ---------------- */

  function conditionModifier(condition, respSupport) {
    const c = CONDITION_MODIFIERS[(condition || "stable").toLowerCase()] ?? 0.0;
    const r = RESP_SUPPORT_MODIFIERS[(respSupport || "room_air").toLowerCase()] ?? 0.0;
    return c + r;
  }

  function acuityProfile(weightG, gaWeeks, modifier = 0.0) {
    const clamp01 = (v) => Math.max(0, Math.min(1, v));
    const wSev = clamp01((1400 - weightG) / (1400 - 400));
    const gSev = clamp01((34 - gaWeeks) / (34 - 22));
    const severity = clamp01(0.55 * wSev + 0.45 * gSev + modifier);

    const intensive = 0.15 + 0.45 * severity;
    const intermediate = 0.3 + 0.1 * (1 - severity);
    const convalescent = Math.max(0, 1 - intensive - intermediate);
    const total = intensive + intermediate + convalescent;

    return {
      severity: round(severity, 3),
      phases: [
        { name: "Intensive care (1:1)", fraction: intensive / total, nurses_per_infant: 1.0 },
        { name: "Intermediate care (1:2)", fraction: intermediate / total, nurses_per_infant: 0.5 },
        { name: "Convalescent care (1:3)", fraction: convalescent / total, nurses_per_infant: 1 / 3 },
      ],
    };
  }

  function estimateStaffing(weightG, gaWeeks, losDays, condition, respSupport) {
    if (!losDays || losDays <= 0) losDays = 1.0;
    const modifier = conditionModifier(condition, respSupport);
    const profile = acuityProfile(weightG, gaWeeks, modifier);

    const phaseDetail = [];
    let totalNurseHours = 0;
    for (const ph of profile.phases) {
      const days = ph.fraction * losDays;
      const nurseHours = days * HOURS_PER_DAY * ph.nurses_per_infant;
      totalNurseHours += nurseHours;
      phaseDetail.push({
        name: ph.name,
        days: round(days, 1),
        nurses_per_infant: round(ph.nurses_per_infant, 3),
        nurse_hours: round(nurseHours, 1),
      });
    }

    const nhppd = totalNurseHours / losDays;
    const peakNurses = Math.max(...profile.phases.map((p) => p.nurses_per_infant));

    return {
      acuity_severity: profile.severity,
      peak_nurses_per_infant: round(peakNurses, 3),
      avg_nhppd: round(nhppd, 2),
      total_nurse_hours: round(totalNurseHours, 1),
      total_12h_shifts: round(totalNurseHours / 12, 1),
      phases: phaseDetail,
      note:
        "Estimates follow AAP/AWHONN acuity-based nurse:patient ratios. Actual " +
        "staffing must be adjusted for ventilation, surgery, and unit policy.",
    };
  }

  function scheduleUnit(infants, shiftsPerDay = 2) {
    const rows = [];
    let totalDemand = 0;
    const acuityCounts = { intensive: 0, intermediate: 0, convalescent: 0 };

    infants.forEach((inf, i) => {
      const w = Number(inf.weight_g ?? 1000);
      const g = Number(inf.ga_weeks ?? 30);
      const modifier = conditionModifier(inf.condition, inf.resp_support);
      const sev = acuityProfile(w, g, modifier).severity;

      let band, npi;
      if (sev >= 0.6) {
        band = "intensive"; npi = 1.0;
      } else if (sev >= 0.35) {
        band = "intermediate"; npi = 0.5;
      } else {
        band = "convalescent"; npi = 1 / 3;
      }
      acuityCounts[band] += 1;
      totalDemand += npi;
      rows.push({
        index: i + 1,
        weight_g: w,
        ga_weeks: g,
        condition: inf.condition || "stable",
        resp_support: inf.resp_support || "room_air",
        severity: round(sev, 3),
        acuity: band,
        nurses_required: round(npi, 3),
      });
    });

    const bedsideNurses = totalDemand > 0 ? Math.ceil(totalDemand) : 0;
    const chargeNurse = infants.length ? 1 : 0;
    const nursesPerShift = bedsideNurses + chargeNurse;

    return {
      census: infants.length,
      acuity_counts: acuityCounts,
      total_demand: round(totalDemand, 2),
      bedside_nurses_per_shift: bedsideNurses,
      charge_nurses_per_shift: chargeNurse,
      nurses_per_shift: nursesPerShift,
      shifts_per_day: shiftsPerDay,
      daily_nurse_shifts: nursesPerShift * shiftsPerDay,
      infants: rows,
      note:
        "Immediate acuity-based demand using AAP/AWHONN ratios (1:1 intensive, " +
        "1:2 intermediate, 1:3 convalescent) plus one charge nurse per shift.",
    };
  }

  /* ---------------- analytics helpers ---------------- */

  function seriesFor(bins, perBin) {
    const out = [];
    for (const b of bins) {
      const stat = perBin[b.label];
      if (stat) out.push({ label: b.label, n: stat.n, median: stat.median, q1: stat.q1, q3: stat.q3 });
    }
    return out;
  }

  function analytics() {
    const surv = D.survival_by_weight;
    return {
      los_by_weight: seriesFor(D.weight_bins, D.los_by_weight[TOTAL_LOS] || {}),
      los_by_ga: seriesFor(D.ga_bins, D.los_by_ga[TOTAL_LOS] || {}),
      disposition_by_weight: {
        home: seriesFor(D.weight_bins, surv[DISP_HOME] || {}),
        transfer: seriesFor(D.weight_bins, surv[DISP_TRANSFER] || {}),
        died: seriesFor(D.weight_bins, surv[DISP_DIED] || {}),
        all: seriesFor(D.weight_bins, surv[DISP_ALL] || {}),
      },
    };
  }

  window.NeoEngine = {
    meta: () => ({
      center: D.center,
      period: D.period,
      centers: D.centers,
      weight_bins: D.weight_bins,
      ga_bins: D.ga_bins,
    }),
    predict,
    estimateStaffing,
    scheduleUnit,
    analytics,
  };
})();
