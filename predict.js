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
    renderStaffingChart(s);

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
        (p) => `<div class="level-phase-row">
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

  /* ---------------- chart 2: staffing across the stay ---------------- */
  function renderStaffingChart(s) {
    if (!window.Chart) return;
    const pts = s.timeline;
    const total = pts.length ? pts[pts.length - 1].day : 0;
    document.getElementById("staffChartSub").textContent =
      `Nursing requirement day by day across the expected ${fmt(total, 0)}-day stay, ` +
      `shaded by care phase and annotated with the competency level each phase needs.`;

    if (staffChart) staffChart.destroy();
    staffChart = new Chart(document.getElementById("chartStaffing"), {
      type: "line",
      data: {
        labels: pts.map((p) => p.day),
        datasets: [
          {
            label: "Nurses required for this infant",
            data: pts.map((p) => p.nurses_required),
            segment: {
              borderColor: (ctx) =>
                PHASE_COLOR[pts[ctx.p0DataIndex].phase] || "#74909c",
            },
            borderColor: "#0e8a8f",
            backgroundColor: "rgba(14,138,143,0.10)",
            fill: true, stepped: true, pointRadius: 0, borderWidth: 3,
          },
        ],
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              title: (t) => `Day ${Number(t[0].label).toFixed(0)} of stay`,
              label: (t) => {
                const p = pts[t.dataIndex];
                const lvl = NeoEngine.levelInfo(p.required_level);
                return [
                  `${p.phase} care · ${p.nurses_required.toFixed(2)} nurses`,
                  `Needs level ${lvl.level} (${lvl.short}) or above`,
                ];
              },
            },
          },
        },
        scales: {
          x: {
            grid: { color: GRID },
            title: { display: true, text: "Day of stay" },
            ticks: { maxTicksLimit: 12, callback: (v, i) => Math.round(pts[i].day) },
          },
          y: {
            grid: { color: GRID }, min: 0, max: 1.15,
            title: { display: true, text: "Nurses per baby" },
            ticks: { stepSize: 0.25 },
          },
        },
      },
    });
  }
});
