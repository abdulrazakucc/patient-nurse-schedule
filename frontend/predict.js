"use strict";

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

(async function init() {
  const meta = await loadMeta();
  if (meta) {
    meta.centers.forEach((c) => {
      const o = document.createElement("option");
      o.value = c;
      o.textContent = c;
      els.center.appendChild(o);
    });
    els.center.value = meta.center;
  }
})();

els.form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const payload = {
    weight_g: Number(els.weightNum.value),
    ga_weeks: Number(els.gaNum.value),
    center: els.center.value,
    condition: document.getElementById("condition").value,
    resp_support: document.getElementById("respSupport").value,
    notes: document.getElementById("notes").value,
  };
  try {
    const r = await getJSON("/api/predict", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    render(r);
  } catch (err) {
    alert("Prediction failed: " + err.message);
  }
});

function render(r) {
  els.results.hidden = false;
  const los = r.length_of_stay.blended;
  document.getElementById("losMedian").textContent = fmt(los.median);
  document.getElementById("losIqr").textContent = `${fmt(los.q1)} – ${fmt(los.q3)} days`;
  document.getElementById("survival").textContent = fmt(r.survival_probability, 1);
  document.getElementById("sampleN").textContent = r.sample_size ?? "-";
  document.getElementById("confidence").textContent = r.confidence;

  const d = r.disposition;
  const home = d.home ?? 0, transfer = d.transfer ?? 0, died = d.died ?? 0;
  const setRing = (ringId, pctId, pct) => {
    const ring = document.getElementById(ringId);
    ring.style.setProperty("--pct", pct);
    document.getElementById(pctId).textContent = fmt(pct, 1);
  };
  setRing("ringHome", "pHome", home);
  setRing("ringTransfer", "pTransfer", transfer);
  setRing("ringDied", "pDied", died);

  const s = r.staffing;
  document.getElementById("nhppd").textContent = fmt(s.avg_nhppd, 1);
  document.getElementById("peakNurse").textContent = fmt(s.peak_nurses_per_infant, 2);
  document.getElementById("nurseHours").textContent = fmt(s.total_nurse_hours);
  document.getElementById("shifts").textContent = fmt(s.total_12h_shifts);
  document.getElementById("staffNote").textContent = s.note;

  const list = document.getElementById("phaseList");
  list.innerHTML = "";
  const maxDays = Math.max(...s.phases.map((p) => p.days), 1);
  s.phases.forEach((p) => {
    const row = document.createElement("div");
    row.className = "phase-row";
    row.innerHTML = `<span>${p.name}</span><span>${fmt(p.days, 1)} d · ${fmt(p.nurse_hours)} h</span>
      <div class="phase-track"><div class="phase-fill" style="width:${(p.days / maxDays) * 100}%"></div></div>`;
    list.appendChild(row);
  });

  els.results.scrollIntoView({ behavior: "smooth", block: "nearest" });
}
