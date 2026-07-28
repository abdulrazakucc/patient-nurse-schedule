"use strict";
// Home page: populate hero stats from analytics.
(async function () {
  const a = await getJSON("/api/analytics").catch(() => null);
  if (!a) return;
  const heroN = a.los_by_weight.reduce((s, x) => s + (x.n || 0), 0);
  const diedTotal = a.disposition_by_weight.died.reduce((s, x) => s + (x.n || 0), 0);
  const allTotal = a.disposition_by_weight.all.reduce((s, x) => s + (x.n || 0), 0);
  const survival = allTotal ? (1 - diedTotal / allTotal) * 100 : null;
  const medians = a.los_by_weight.map((x) => x.median).filter((v) => v != null).sort((p, q) => p - q);

  const set = (k, v) => {
    const el = document.querySelector(`[data-k="${k}"]`);
    if (el) el.textContent = v;
  };
  set("infants", heroN.toLocaleString());
  set("los", medians.length ? medians[Math.floor(medians.length / 2)] : "-");
  set("survival", survival != null ? survival.toFixed(1) + "%" : "-");
})();
