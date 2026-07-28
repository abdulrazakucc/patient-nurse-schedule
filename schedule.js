"use strict";
/* Scheduling page: census management + unit staffing via the client-side engine. */
document.addEventListener("DOMContentLoaded", () => {
  const census = [];

  const bind = (rangeId, labelId, unit) => {
    const r = document.getElementById(rangeId);
    const l = document.getElementById(labelId);
    const upd = () => (l.textContent = `${r.value} ${unit}`);
    r.addEventListener("input", upd);
    upd();
  };
  bind("sWeight", "sWeightVal", "g");
  bind("sGa", "sGaVal", "weeks");

  const CONDITION_LABEL = { stable: "Stable", guarded: "Guarded", serious: "Serious", critical: "Critical" };
  const RESP_LABEL = { room_air: "Room air", nasal_cannula: "Cannula", cpap: "CPAP", ventilator: "Ventilator" };

  const SAMPLE_UNIT = [
    { weight_g: 620, ga_weeks: 24, condition: "critical", resp_support: "ventilator" },
    { weight_g: 740, ga_weeks: 25, condition: "serious", resp_support: "ventilator" },
    { weight_g: 880, ga_weeks: 27, condition: "serious", resp_support: "cpap" },
    { weight_g: 980, ga_weeks: 28, condition: "guarded", resp_support: "cpap" },
    { weight_g: 1150, ga_weeks: 29, condition: "guarded", resp_support: "nasal_cannula" },
    { weight_g: 1300, ga_weeks: 30, condition: "stable", resp_support: "nasal_cannula" },
    { weight_g: 1420, ga_weeks: 31, condition: "stable", resp_support: "room_air" },
    { weight_g: 1650, ga_weeks: 33, condition: "stable", resp_support: "room_air" },
  ];

  document.getElementById("addForm").addEventListener("submit", (e) => {
    e.preventDefault();
    census.push({
      weight_g: Number(document.getElementById("sWeight").value),
      ga_weeks: Number(document.getElementById("sGa").value),
      condition: document.getElementById("sCondition").value,
      resp_support: document.getElementById("sResp").value,
    });
    refresh();
    toast("Infant added to census.");
  });

  document.getElementById("presetSample").addEventListener("click", () => {
    census.length = 0;
    census.push(...SAMPLE_UNIT.map((i) => ({ ...i })));
    refresh();
    toast("Sample unit loaded — 8 infants across all acuity levels.");
  });
  document.getElementById("presetClear").addEventListener("click", () => {
    census.length = 0;
    refresh();
  });

  function refresh() {
    const shifts = Number(document.getElementById("sShifts").value);
    if (census.length === 0) {
      document.getElementById("roster").hidden = true;
      document.getElementById("rosterEmpty").hidden = false;
      setMetrics({ census: 0, nurses_per_shift: 0, daily_nurse_shifts: 0, total_demand: 0 });
      document.getElementById("schedNote").textContent = "";
      return;
    }
    const r = NeoEngine.scheduleUnit(census, shifts);
    setMetrics(r);
    document.getElementById("schedNote").textContent = r.note;

    document.getElementById("rosterEmpty").hidden = true;
    const table = document.getElementById("roster");
    table.hidden = false;
    const body = document.getElementById("rosterBody");
    body.innerHTML = "";
    r.infants.forEach((inf, i) => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>${inf.index}</td>
        <td>${inf.weight_g} g</td>
        <td>${inf.ga_weeks} wk</td>
        <td>${CONDITION_LABEL[inf.condition] || inf.condition}</td>
        <td>${RESP_LABEL[inf.resp_support] || inf.resp_support}</td>
        <td><span class="pill pill-${inf.acuity}">${inf.acuity}</span></td>
        <td>${inf.nurses_required.toFixed(2)}</td>
        <td><button class="rm" data-i="${i}" title="Remove" aria-label="Remove infant ${inf.index}">✕</button></td>`;
      body.appendChild(tr);
    });
    body.querySelectorAll(".rm").forEach((b) =>
      b.addEventListener("click", () => {
        census.splice(Number(b.dataset.i), 1);
        refresh();
      })
    );
  }

  function setMetrics(r) {
    document.getElementById("mCensus").textContent = r.census ?? 0;
    document.getElementById("mNurses").textContent = r.nurses_per_shift ?? 0;
    document.getElementById("mDaily").textContent = r.daily_nurse_shifts ?? 0;
    document.getElementById("mDemand").textContent = fmt(r.total_demand ?? 0, 1);
  }

  document.getElementById("sShifts").addEventListener("change", refresh);
  refresh();
});
