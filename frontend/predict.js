"use strict";
/* Predictor page: runs the client-side engine (engine.js) — no server round-trip. */
document.addEventListener("DOMContentLoaded", () => {
  const MUTED = "#74909c", GRID = "rgba(14,43,54,0.07)";
  const PHASE_COLOR = { intensive: "#0e8a8f", intermediate: "#c9a24b", convalescent: "#10998a" };
  if (window.Chart) {
    Chart.defaults.color = MUTED;
    Chart.defaults.font.family = "Inter";
  }
  let losChart, staffChart;

  const els = {
    center: document.getElementById("center"),
    weight: document.getElementById("weight"),
    weightNum: document.getElementById("weightNum"),
    weightVal: document.getElementById("weightVal"),
    ga: document.getElementById("ga"),
    gaNum: document.getElementById("gaNum"),
    gaVal: document.getElementById("gaVal"),
    form: document.getElementById("predictForm"),
    results: document.getElementById("results"),
    placeholder: document.getElementById("resultsPlaceholder"),
  };

  function sync(rangeEl, numEl, labelEl, unit) {
    const update = (source) => {
      const v = source.value;
      if (source === rangeEl) numEl.value = v;
      else rangeEl.value = v;
      labelEl.textContent = `${v} ${unit}`;
    };
    rangeEl.addEventListener("input", () => update(rangeEl));
    numEl.addEventListener("input", () => update(numEl));
  }
  sync(els.weight, els.weightNum, els.weightVal, "g");
  sync(els.ga, els.gaNum, els.gaVal, "weeks");

  const meta = NeoEngine.meta();
  meta.centers.forEach((c) => {
    const o = document.createElement("option");
    o.value = c;
    o.textContent = c;
    els.center.appendChild(o);
  });
  els.center.value = meta.center;

  els.form.addEventListener("submit", (e) => {
    e.preventDefault();
    const weight = Number(els.weightNum.value);
    const ga = Number(els.gaNum.value);
    if (!weight || !ga) {
      toast("Please provide both birth weight and gestational age.");
      return;
    }
    try {
      const r = NeoEngine.predict(weight, ga);
      r.staffing = NeoEngine.estimateStaffing(
        weight,
        ga,
        r.length_of_stay.blended.median || 0,
        document.getElementById("condition").value,
        document.getElementById("respSupport").value
      );
      render(r);
    } catch (err) {
      toast("Prediction failed: " + err.message);
    }
  });

  function render(r) {
    els.placeholder.hidden = true;
    els.results.hidden = false;

    const los = r.length_of_stay.blended;
    countUp(document.getElementById("losMedian"), los.median, { decimals: 0 });
    document.getElementById("losIqr").textContent = `${fmt(los.q1)} – ${fmt(los.q3)} days`;
    countUp(document.getElementById("survival"), r.survival_probability, { decimals: 1 });
    document.getElementById("sampleN").textContent = r.sample_size ?? "–";

    const conf = document.getElementById("confidence");
    conf.textContent = r.confidence + " confidence";
    conf.setAttribute("data-tip",
      `Based on ${r.sample_size} similar infants. 50 or more gives high confidence, ` +
      `20-49 moderate, 5-19 low. Treat low-confidence figures as rough sketches.`);
    conf.className = "conf-badge conf-" + String(r.confidence).replace(/\s+/g, "-");

    const d = r.disposition;
    const setRing = (ringId, pctId, pct) => {
      const ring = document.getElementById(ringId);
      const label = document.getElementById(pctId);
      const target = pct ?? 0;
      const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      if (reduced) {
        ring.style.setProperty("--pct", target);
        label.textContent = fmt(target, 1);
        return;
      }
      const start = performance.now();
      const stepFn = (now) => {
        const t = Math.min(1, (now - start) / 700);
        const eased = 1 - Math.pow(1 - t, 3);
        const v = target * eased;
        ring.style.setProperty("--pct", v);
        label.textContent = fmt(v, 1);
        if (t < 1) requestAnimationFrame(stepFn);
      };
      requestAnimationFrame(stepFn);
    };
    setRing("ringHome", "pHome", d.home);
    setRing("ringTransfer", "pTransfer", d.transfer);
    setRing("ringDied", "pDied", d.died);

    const dispLosText = (key, elId) => {
      const est = r.disposition_los[key];
      const el = document.getElementById(elId);
      el.textContent = est && est.median !== null ? `Typical stay ~${fmt(est.median)} days` : "";
    };
    dispLosText("home", "losHome");
    dispLosText("transfer", "losTransfer");
    dispLosText("died", "losDied");

    const s = r.staffing;
    countUp(document.getElementById("nhppd"), s.avg_nhppd, { decimals: 1 });
    countUp(document.getElementById("peakNurse"), s.peak_nurses_per_infant, { decimals: 2 });
    countUp(document.getElementById("nurseHours"), s.total_nurse_hours, { decimals: 0 });
    countUp(document.getElementById("shifts"), s.total_12h_shifts, { decimals: 0 });
    document.getElementById("staffNote").textContent = s.note;

    const list = document.getElementById("phaseList");
    list.innerHTML = "";
    const maxDays = Math.max(...s.phases.map((p) => p.days), 1);
    s.phases.forEach((p) => {
      const row = document.createElement("div");
      row.className = "phase-row";
      row.innerHTML = `<span>${p.name}</span><span>${fmt(p.days, 1)} d · ${fmt(p.nurse_hours)} h</span>
        <div class="phase-track"><div class="phase-fill" style="width:0%"></div></div>`;
      list.appendChild(row);
      requestAnimationFrame(() =>
        requestAnimationFrame(() => {
          row.querySelector(".phase-fill").style.width = `${(p.days / maxDays) * 100}%`;
        })
      );
    });

    renderCompetency(r, s);
    renderLosChart(r);
    renderStaffingChart(r, s);

    els.results.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  /* ---------------- nurse competency panel ---------------- */
  function renderCompetency(r, s) {
    const lv = s.admission_level_info;
    document.getElementById("levelCallout").innerHTML = `
      <span class="lvl lvl-${lv.level}">Level ${lv.level} · ${lv.short}</span>
      <div>
        <b>${lv.name} <span style="font-weight:500;color:var(--muted)">(${lv.years_label} experience)</span></b>
        <span>${lv.scope}</span>
      </div>`;

    document.getElementById("levelPhases").innerHTML = s.phases
      .map(
        (p) => `<div class="level-phase-row" data-tip="${p.name.replace(/"/g, "&quot;")} lasts about ${fmt(p.days, 1)} days and consumes ${fmt(p.nurse_hours, 0)} nurse-hours. It needs a level ${p.required_level} (${p.required_level_name}) nurse or above.">
          <span>${p.name} · <b style="color:var(--ink)">${fmt(p.days, 1)} days</b></span>
          <span class="lvl lvl-${p.required_level}">L${p.required_level} ${p.required_level_name}</span>
        </div>`
      )
      .join("");

    document.getElementById("competencyNote").textContent = s.competency_note;
  }

  /* ---------------- chart 1: LOS in context ---------------- */
  function renderLosChart(r) {
    if (!window.Chart) return;
    const a = NeoEngine.analytics().los_by_weight;
    const labels = a.map((x) => x.label);
    const thisWeight = r.input.weight_g;
    const idx = labels.indexOf(r.weight_bin);
    const median = r.length_of_stay.blended.median;

    // Highlight this infant's position on the birth-weight axis.
    const marker = labels.map((_, i) => (i === idx ? median : null));

    if (losChart) losChart.destroy();
    losChart = new Chart(document.getElementById("chartLosContext"), {
      type: "line",
      data: {
        labels,
        datasets: [
          {
            label: "Upper quartile (Q3)",
            data: a.map((x) => x.q3),
            borderColor: "rgba(14,138,143,0.25)",
            backgroundColor: "rgba(14,138,143,0.12)",
            fill: "+1", pointRadius: 0, borderWidth: 1, tension: 0.35,
          },
          {
            label: "Lower quartile (Q1)",
            data: a.map((x) => x.q1),
            borderColor: "rgba(14,138,143,0.25)",
            fill: false, pointRadius: 0, borderWidth: 1, tension: 0.35,
          },
          {
            label: "Median stay",
            data: a.map((x) => x.median),
            borderColor: "#0e8a8f",
            backgroundColor: "#0e8a8f",
            pointRadius: 0, borderWidth: 2.5, tension: 0.35,
          },
          {
            label: `This infant (${thisWeight} g)`,
            data: marker,
            borderColor: "#b5445f",
            backgroundColor: "#b5445f",
            pointRadius: 7, pointHoverRadius: 9, pointStyle: "circle",
            showLine: false,
          },
        ],
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        plugins: {
          legend: { labels: { usePointStyle: true, filter: (l) => !l.text.includes("quartile") } },
          tooltip: {
            callbacks: {
              label: (t) => t.raw == null ? null : `${t.dataset.label}: ${Number(t.raw).toFixed(1)} days`,
            },
          },
        },
        scales: {
          x: { grid: { color: GRID }, ticks: { maxRotation: 60, minRotation: 40 },
               title: { display: true, text: "Birth weight band" } },
          y: { grid: { color: GRID }, beginAtZero: true,
               title: { display: true, text: "Length of stay (days)" } },
        },
      },
    });
  }

  /* ---------------- chart 2: staffing across the stay ----------------
     Uses a linear day axis so the discharge window and phase-transition
     markers can be positioned by day rather than by data index. */

  // Competency level colours, matching the .lvl-N badges in the stylesheet.
  const LEVEL_COLOR = {
    1: { fill: "#e8eef2", ink: "#40606f" },
    2: { fill: "#e3f4f4", ink: "#0a6d72" },
    3: { fill: "#f7efdd", ink: "#a76f1e" },
    4: { fill: "#fbe7ec", ink: "#b5445f" },
  };

  // Headroom above the 1:1 line, reserved for the competency ribbon and labels.
  const Y_MAX = 1.7;
  const RIBBON_LO = 1.36;
  const RIBBON_HI = 1.62;

  // Nurse:patient ratio labels - how staffing is actually discussed on the unit.
  const RATIO_TICKS = [
    { value: 1, label: "1 : 1" },
    { value: 0.5, label: "1 : 2" },
    { value: 1 / 3, label: "1 : 3" },
    { value: 0, label: "0" },
  ];

  function ratioLabel(v) {
    const hit = RATIO_TICKS.find((t) => Math.abs(t.value - v) < 0.02);
    return hit ? hit.label : "";
  }

  function renderStaffingChart(r, s) {
    if (!window.Chart) return;
    const pts = s.timeline;
    const los = r.length_of_stay.blended;
    const median = los.median || (pts.length ? pts[pts.length - 1].day : 1);
    const q1 = los.q1, q3 = los.q3;
    const hasWindow = q1 != null && q3 != null && q3 > q1;
    const xMax = hasWindow ? Math.max(q3, median) : median;

    // Phase spans (for the competency ribbon) and boundaries (for the markers).
    const spans = [];
    const boundaries = [];
    let run = 0;
    s.phases.forEach((p, i) => {
      spans.push({
        start: run, end: run + p.days,
        level: p.required_level, levelName: p.required_level_name,
      });
      run += p.days;
      if (i < s.phases.length - 1) {
        boundaries.push({ day: run, next: s.phases[i + 1] });
      }
    });

    document.getElementById("staffChartSub").textContent =
      `Nursing requirement day by day. The solid line is the expected ${fmt(median, 0)}-day stay; ` +
      (hasWindow
        ? `the shaded band shows the likely discharge window (${fmt(q1, 0)}–${fmt(q3, 0)} days), ` +
          "because the length of stay is a forecast, not a fixed date. "
        : "") +
      "Dashed markers show where care steps down to a lower ratio.";

    /* Custom plugin: discharge window, expected-discharge line, phase markers. */
    const annotations = {
      id: "neoStaffAnnotations",
      afterDatasetsDraw(chart) {
        const { ctx, chartArea, scales } = chart;
        const x = scales.x, yS = scales.y;
        const top = chartArea.top, bottom = chartArea.bottom;
        ctx.save();

        // 0. Competency ribbon - which level of nurse each phase needs, drawn in
        //    the headroom above the ratio line so it is readable without tapping.
        const ribTop = yS.getPixelForValue(RIBBON_HI);
        const ribBot = yS.getPixelForValue(RIBBON_LO);
        spans.forEach((sp) => {
          const xa = x.getPixelForValue(sp.start);
          const xb = x.getPixelForValue(Math.min(sp.end, xMax));
          if (xb <= xa) return;
          const col = LEVEL_COLOR[sp.level] || LEVEL_COLOR[1];
          ctx.fillStyle = col.fill;
          ctx.fillRect(xa, ribTop, xb - xa, ribBot - ribTop);
          ctx.strokeStyle = col.ink;
          ctx.globalAlpha = 0.35;
          ctx.lineWidth = 1;
          ctx.strokeRect(xa + 0.5, ribTop + 0.5, xb - xa - 1, ribBot - ribTop - 1);
          ctx.globalAlpha = 1;

          ctx.fillStyle = col.ink;
          ctx.font = "700 10px Inter, sans-serif";
          ctx.textAlign = "center";
          ctx.textBaseline = "middle";
          const full = `L${sp.level} ${sp.levelName}`;
          const short = `L${sp.level}`;
          const w = xb - xa;
          const label = ctx.measureText(full).width + 10 < w
            ? full
            : (ctx.measureText(short).width + 6 < w ? short : "");
          if (label) ctx.fillText(label, (xa + xb) / 2, (ribTop + ribBot) / 2);
        });
        ctx.textBaseline = "alphabetic";

        // Caption for the ribbon, in the left margin when there is room.
        ctx.fillStyle = "#74909c";
        ctx.font = "600 9px Inter, sans-serif";
        ctx.textAlign = "left";
        if (ribBot - ribTop > 10) {
          ctx.fillText("nurse level needed", chartArea.left + 3, ribTop - 4);
        }

        // 1. Likely discharge window (uncertainty).
        if (hasWindow) {
          const xa = x.getPixelForValue(q1), xb = x.getPixelForValue(q3);
          ctx.fillStyle = "rgba(181, 68, 95, 0.09)";
          ctx.fillRect(xa, top, xb - xa, bottom - top);
          ctx.strokeStyle = "rgba(181, 68, 95, 0.35)";
          ctx.setLineDash([3, 3]);
          ctx.lineWidth = 1;
          [xa, xb].forEach((px) => {
            ctx.beginPath(); ctx.moveTo(px, top); ctx.lineTo(px, bottom); ctx.stroke();
          });
          ctx.setLineDash([]);
          ctx.fillStyle = "#b5445f";
          ctx.font = "600 10px Inter, sans-serif";
          ctx.textAlign = "center";
          const mid = (xa + xb) / 2;
          if (xb - xa > 90) ctx.fillText("likely discharge window", mid, bottom - 6);
        }

        // 2. Expected discharge (the median).
        const xm = x.getPixelForValue(median);
        ctx.strokeStyle = "#b5445f";
        ctx.lineWidth = 1.5;
        ctx.beginPath(); ctx.moveTo(xm, top); ctx.lineTo(xm, bottom); ctx.stroke();
        ctx.fillStyle = "#b5445f";
        ctx.font = "700 10px Inter, sans-serif";
        // Flip the label to the left of the line when it would overflow the plot.
        const dischargeText = `expected discharge · day ${Math.round(median)}`;
        const flip = xm + 5 + ctx.measureText(dischargeText).width > chartArea.right;
        ctx.textAlign = flip ? "right" : "left";
        // Sits low in the plot, clear of the phase labels below the ribbon.
        ctx.fillText(dischargeText, xm + (flip ? -5 : 5), bottom - 20);

        // 3. Phase step-downs.
        ctx.font = "600 10px Inter, sans-serif";
        boundaries.forEach((b, i) => {
          const px = x.getPixelForValue(b.day);
          ctx.strokeStyle = "rgba(14,43,54,0.35)";
          ctx.setLineDash([4, 4]);
          ctx.lineWidth = 1;
          ctx.beginPath(); ctx.moveTo(px, top); ctx.lineTo(px, bottom); ctx.stroke();
          ctx.setLineDash([]);
          const ratio = b.next.nurses_per_infant >= 0.5 ? "1 : 2" : "1 : 3";
          const text = `day ${Math.round(b.day)} → ${ratio}`;
          ctx.fillStyle = "#3d5763";
          const flipPhase = px + 5 + ctx.measureText(text).width > chartArea.right;
          ctx.textAlign = flipPhase ? "right" : "left";
          ctx.fillText(text, px + (flipPhase ? -5 : 5), ribBot + 13 + i * 13);
        });
        ctx.restore();
      },
    };

    if (staffChart) staffChart.destroy();
    staffChart = new Chart(document.getElementById("chartStaffing"), {
      type: "line",
      data: {
        datasets: [
          {
            label: "Nurses required for this infant",
            data: pts.map((p) => ({ x: p.day, y: p.nurses_required })),
            segment: {
              borderColor: (ctx) => PHASE_COLOR[pts[ctx.p0DataIndex].phase] || "#74909c",
            },
            borderColor: "#0e8a8f",
            backgroundColor: "rgba(14,138,143,0.10)",
            fill: true, stepped: true, pointRadius: 0, borderWidth: 3,
          },
          // If the stay runs long, convalescent care simply continues.
          {
            label: "If the stay runs longer",
            data: hasWindow && q3 > median
              ? [{ x: median, y: 1 / 3 }, { x: q3, y: 1 / 3 }]
              : [],
            borderColor: "rgba(16,153,138,0.75)",
            borderDash: [5, 4], borderWidth: 2, pointRadius: 0, fill: false,
          },
        ],
      },
      plugins: [annotations],
      options: {
        responsive: true, maintainAspectRatio: false,
        layout: { padding: { top: 4 } },
        interaction: { mode: "nearest", axis: "x", intersect: false },
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              title: (t) => `Day ${Math.round(t[0].parsed.x)} of stay`,
              label: (t) => {
                if (t.datasetIndex === 1) return "Care continues at 1 : 3 if discharge is later";
                const p = pts[t.dataIndex];
                if (!p) return "";
                const lvl = NeoEngine.levelInfo(p.required_level);
                const ratio = ratioLabel(p.nurses_required) || p.nurses_required.toFixed(2);
                return [
                  `${p.phase} care · ${ratio} nurse to babies`,
                  `Needs level ${lvl.level} (${lvl.short}) or above`,
                ];
              },
            },
          },
        },
        scales: {
          x: {
            type: "linear", min: 0, max: xMax,
            grid: { color: GRID },
            title: { display: true, text: "Day of stay" },
            ticks: { maxTicksLimit: 10, callback: (v) => Math.round(v) },
          },
          y: {
            min: 0, max: Y_MAX,
            grid: { color: GRID },
            title: { display: true, text: "Nurse-to-baby ratio" },
            afterBuildTicks: (axis) => {
              axis.ticks = RATIO_TICKS.map((t) => ({ value: t.value }));
            },
            ticks: { callback: (v) => ratioLabel(v), autoSkip: false },
          },
        },
      },
    });
  }
});
