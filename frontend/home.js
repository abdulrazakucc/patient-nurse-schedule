"use strict";
/* Home page: hero stats + "unit at a glance" showcase, all from the bundled dataset. */
document.addEventListener("DOMContentLoaded", () => {
  const a = NeoEngine.analytics();
  const meta = NeoEngine.meta();

  const heroN = a.los_by_weight.reduce((s, x) => s + (x.n || 0), 0);
  const diedTotal = a.disposition_by_weight.died.reduce((s, x) => s + (x.n || 0), 0);
  const allTotal = a.disposition_by_weight.all.reduce((s, x) => s + (x.n || 0), 0);
  const survival = allTotal ? (1 - diedTotal / allTotal) * 100 : null;
  const medians = a.los_by_weight.map((x) => x.median).filter((v) => v != null).sort((p, q) => p - q);
  const medianLos = medians.length ? medians[Math.floor(medians.length / 2)] : null;

  const stat = (k) => document.querySelector(`[data-k="${k}"]`);
  countUp(stat("infants"), heroN, { duration: 900 });
  countUp(stat("los"), medianLos, { duration: 900 });
  countUp(stat("survival"), survival, { decimals: 1, suffix: "%", duration: 900 });

  /* Glance card: median LOS by birth weight sparkline */
  const ctx = document.getElementById("glanceChart");
  if (ctx && window.Chart) {
    Chart.defaults.font.family = "Inter";
    new Chart(ctx, {
      type: "line",
      data: {
        labels: a.los_by_weight.map((s) => s.label),
        datasets: [
          {
            label: "Median LOS",
            data: a.los_by_weight.map((s) => s.median),
            borderColor: "#0e8a8f",
            backgroundColor: "rgba(14,138,143,0.12)",
            fill: true,
            tension: 0.4,
            pointRadius: 0,
            borderWidth: 2.5,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: { label: (t) => ` ${t.formattedValue} days median stay` },
          },
        },
        scales: {
          x: { display: false },
          y: { display: false },
        },
      },
    });
  }

  const rows = document.getElementById("glanceRows");
  if (rows) {
    const homeTotal = a.disposition_by_weight.home.reduce((s, x) => s + (x.n || 0), 0);
    const items = [
      ["Data window", meta.period],
      ["Birth-weight bands", `${meta.weight_bins.length}`],
      ["Discharged home", allTotal ? `${((homeTotal / allTotal) * 100).toFixed(1)}%` : "–"],
      ["Longest median stay", `${Math.max(...a.los_by_weight.map((s) => s.median || 0))} days`],
    ];
    rows.innerHTML = items
      .map(([l, v]) => `<div class="glance-row"><span>${l}</span><b>${v}</b></div>`)
      .join("");
  }
});
