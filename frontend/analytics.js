"use strict";
/* Analytics page: charts computed from the bundled dataset via the engine. */
document.addEventListener("DOMContentLoaded", () => {
  const MUTED = "#74909c", GRID = "rgba(14,43,54,0.07)";
  Chart.defaults.color = MUTED;
  Chart.defaults.font.family = "Inter";

  const a = NeoEngine.analytics();
  makeIqrChart("chartLosWeight", a.los_by_weight, "#0e8a8f");
  makeIqrChart("chartLosGa", a.los_by_ga, "#c9a24b");
  makeDispositionChart("chartDisposition", a.disposition_by_weight);

  function baseOpts(unit) {
    return {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { labels: { color: MUTED, usePointStyle: true } } },
      scales: {
        x: { grid: { color: GRID }, ticks: { maxRotation: 60, minRotation: 40 } },
        y: { grid: { color: GRID }, title: { display: true, text: unit } },
      },
    };
  }

  function makeIqrChart(id, series, color) {
    new Chart(document.getElementById(id), {
      type: "bar",
      data: {
        labels: series.map((s) => s.label),
        datasets: [
          {
            label: "IQR (Q1–Q3)",
            data: series.map((s) => [s.q1, s.q3]),
            backgroundColor: color + "40",
            borderColor: color,
            borderWidth: 1,
            borderRadius: 6,
          },
          {
            label: "Median",
            type: "line",
            data: series.map((s) => s.median),
            borderColor: "#122b36",
            backgroundColor: "#122b36",
            pointRadius: 4,
            pointHoverRadius: 6,
            tension: 0.3,
          },
        ],
      },
      options: baseOpts("days"),
    });
  }

  function makeDispositionChart(id, disp) {
    const pct = (arr) =>
      arr.map((s, i) => {
        const total = disp.all[i].n || 0;
        return total ? ((s.n || 0) / total) * 100 : 0;
      });
    new Chart(document.getElementById(id), {
      type: "bar",
      data: {
        labels: disp.all.map((s) => s.label),
        datasets: [
          { label: "Home", data: pct(disp.home), backgroundColor: "#10998a" },
          { label: "Transfer", data: pct(disp.transfer), backgroundColor: "#de9327" },
          { label: "Died", data: pct(disp.died), backgroundColor: "#d5637a" },
        ],
      },
      options: {
        ...baseOpts("%"),
        scales: {
          x: { stacked: true, grid: { color: GRID } },
          y: { stacked: true, grid: { color: GRID }, max: 100, title: { display: true, text: "% of infants" } },
        },
      },
    });
  }
});
