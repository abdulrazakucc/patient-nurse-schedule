"use strict";
/* Timeline page: renders the precomputed bundle in data/neostay-timeseries.js. */
document.addEventListener("DOMContentLoaded", () => {
  const MUTED = "#74909c", GRID = "rgba(14,43,54,0.07)";
  Chart.defaults.color = MUTED;
  Chart.defaults.font.family = "Inter";

  const PHASE_COLOR = { intensive: "#0e8a8f", intermediate: "#c9a24b", convalescent: "#10998a" };
  const CONDITION_LABEL = { stable: "Stable", guarded: "Guarded", serious: "Serious", critical: "Critical" };
  const RESP_LABEL = { room_air: "Room air", nasal_cannula: "Nasal cannula", cpap: "CPAP", ventilator: "Ventilator" };

  const TS = window.NEOSTAY_TS;
  if (!TS) {
    document.querySelector("main").innerHTML =
      '<section class="panel"><div class="card" style="padding:40px;text-align:center">' +
      "Timeline bundle not found. Run <code>python3 scripts/build_frontend_data.py</code> and reload." +
      "</div></section>";
    return;
  }

  let infantChart, weekChart, hourlyChart, phaseChart;

  renderMetrics(TS.summary);
  renderHourly(TS.summary.hourly_demand_profile);
  renderPhase(TS.summary.care_phase_mix);

  const sel = document.getElementById("infantSelect");
  TS.infants.forEach((i) => {
    const o = document.createElement("option");
    o.value = i.infant_id;
    o.textContent = `${i.infant_id} · ${i.birth_weight_g} g · ${i.gestational_age_weeks} wk · ${i.disposition} · ${i.length_of_stay_days} d`;
    sel.appendChild(o);
  });
  sel.addEventListener("change", () => loadInfant(sel.value));
  if (TS.infants.length) loadInfant(TS.infants[0].infant_id);

  loadWeek();

  function renderMetrics(s) {
    const box = document.getElementById("tsMetrics");
    const items = [
      { v: s.total_infants.toLocaleString(), l: "Infants" },
      { v: s.total_nurses, l: "Nurses on file" },
      { v: s.avg_census, l: "Average census" },
      { v: s.peak_census, l: "Peak census" },
      { v: s.avg_nurses_on_duty, l: "Avg nurses on duty" },
    ];
    box.innerHTML = items
      .map((i) => `<div class="ts-metric"><span>${i.v}</span><label>${i.l}</label></div>`)
      .join("");
  }

  function loadInfant(id) {
    const data = TS.series[id];
    if (!data) return;
    const m = data.infant;
    document.getElementById("infantMeta").innerHTML = `
      <span class="chip">${m.birth_weight_g} g</span>
      <span class="chip">${m.gestational_age_weeks} weeks</span>
      <span class="chip">${m.birth_weight_band}</span>
      <span class="chip chip-${m.disposition.toLowerCase()}">${m.disposition}</span>
      <span class="chip">${CONDITION_LABEL[m.admission_condition] || m.admission_condition} on arrival</span>
      <span class="chip">${RESP_LABEL[m.respiratory_support] || m.respiratory_support}</span>
      <span class="chip">${m.length_of_stay_days} day stay</span>`;

    // Compact points: [hour_of_stay, phase_index, nurses_required]
    const pts = data.pts.map(([h, p, n]) => ({
      day: h / 24,
      phase: TS.phases[p] || "unknown",
      nurses: n,
    }));
    const labels = pts.map((p) => p.day.toFixed(1));
    const values = pts.map((p) => p.nurses);
    const colors = pts.map((p) => PHASE_COLOR[p.phase] || "#74909c");

    if (infantChart) infantChart.destroy();
    infantChart = new Chart(document.getElementById("chartInfant"), {
      type: "bar",
      data: {
        labels,
        datasets: [
          {
            label: "Nurses required",
            data: values,
            backgroundColor: colors,
            borderRadius: 2,
            barPercentage: 1.0,
            categoryPercentage: 1.0,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              title: (t) => `Day ${t[0].label} of stay`,
              label: (t) => {
                const p = pts[t.dataIndex];
                return `${p.phase} care · ${p.nurses.toFixed(2)} nurses`;
              },
            },
          },
        },
        scales: {
          x: {
            grid: { color: GRID },
            title: { display: true, text: "Day of stay" },
            ticks: { maxTicksLimit: 14, callback: (v, i) => Math.round(pts[i].day) },
          },
          y: {
            grid: { color: GRID },
            title: { display: true, text: "Nurses per baby" },
            min: 0, max: 1.15,
          },
        },
      },
    });
  }

  function loadWeek() {
    const w = TS.week;
    document.getElementById("weekLabel").textContent =
      `Seven day window starting ${w.start} (the busiest week in the record)`;
    const labels = w.points.map((p) => p.timestamp.slice(5, 16));
    if (weekChart) weekChart.destroy();
    weekChart = new Chart(document.getElementById("chartWeek"), {
      type: "line",
      data: {
        labels,
        datasets: [
          {
            label: "Nurses on duty",
            data: w.points.map((p) => p.nurses_on_duty),
            borderColor: "#0e8a8f",
            backgroundColor: "rgba(14,138,143,0.12)",
            fill: true, stepped: true, pointRadius: 0, borderWidth: 2,
          },
          {
            label: "Nurse demand",
            data: w.points.map((p) => p.nurse_demand),
            borderColor: "#c9a24b",
            backgroundColor: "transparent",
            pointRadius: 0, borderWidth: 2, tension: 0.25,
          },
          {
            label: "Babies in unit (census)",
            data: w.points.map((p) => p.census),
            borderColor: "#d5637a",
            backgroundColor: "transparent",
            pointRadius: 0, borderWidth: 1.5, borderDash: [4, 3], tension: 0.25,
          },
        ],
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        plugins: { legend: { labels: { usePointStyle: true } } },
        scales: {
          x: { grid: { color: GRID }, ticks: { maxTicksLimit: 14 }, title: { display: true, text: "Date and hour" } },
          y: { grid: { color: GRID }, title: { display: true, text: "Count of nurses / babies" }, beginAtZero: true },
        },
      },
    });
  }

  function renderHourly(profile) {
    if (hourlyChart) hourlyChart.destroy();
    hourlyChart = new Chart(document.getElementById("chartHourly"), {
      type: "line",
      data: {
        labels: profile.map((p) => p.hour + ":00"),
        datasets: [
          {
            label: "Avg nurse demand",
            data: profile.map((p) => p.avg_nurse_demand),
            borderColor: "#0e8a8f",
            backgroundColor: "rgba(14,138,143,0.14)",
            fill: true, pointRadius: 0, borderWidth: 2, tension: 0.35,
          },
        ],
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: {
          x: { grid: { color: GRID }, ticks: { maxTicksLimit: 8 } },
          y: { grid: { color: GRID }, beginAtZero: true, title: { display: true, text: "Nurses" } },
        },
      },
    });
  }

  function renderPhase(mix) {
    const labels = Object.keys(mix);
    if (phaseChart) phaseChart.destroy();
    phaseChart = new Chart(document.getElementById("chartPhase"), {
      type: "doughnut",
      data: {
        labels: labels.map((l) => l[0].toUpperCase() + l.slice(1)),
        datasets: [
          {
            data: labels.map((l) => mix[l]),
            backgroundColor: labels.map((l) => PHASE_COLOR[l] || "#74909c"),
            borderWidth: 2, borderColor: "#fff",
          },
        ],
      },
      options: {
        responsive: true, maintainAspectRatio: false, cutout: "62%",
        plugins: {
          legend: { position: "bottom", labels: { usePointStyle: true } },
          tooltip: { callbacks: { label: (t) => `${t.label}: ${t.raw}%` } },
        },
      },
    });
  }
});
