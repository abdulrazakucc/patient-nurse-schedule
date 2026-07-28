"use strict";
/* Scheduling page: census management + unit staffing via the client-side engine. */
document.addEventListener("DOMContentLoaded", () => {
  const census = [];

  // Competency colours, aligned with the .lvl-N badges.
  const LEVEL_FILL = { 1: "#8aa4b0", 2: "#0e8a8f", 3: "#c9a24b", 4: "#d5637a" };
  const GRID = "rgba(14,43,54,0.07)";
  if (window.Chart) Chart.defaults.font.family = "Inter";
  let mixChart;

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
      document.getElementById("skillMixCard").hidden = true;
      setMetrics({ census: 0, nurses_per_shift: 0, daily_nurse_shifts: 0, total_demand: 0 });
      document.getElementById("schedNote").textContent = "";
      return;
    }
    const r = NeoEngine.scheduleUnit(census, shifts);
    setMetrics(r);
    document.getElementById("schedNote").textContent = r.note;
    renderSkillMix(r.skill_mix);

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
        <td><span class="lvl lvl-${inf.required_level}">L${inf.required_level} ${inf.required_level_name}</span></td>
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

  function renderSkillMix(mix) {
    const card = document.getElementById("skillMixCard");
    card.hidden = false;

    document.getElementById("mixWarnings").innerHTML = (mix.warnings || [])
      .map((w) => `<div class="mix-warn"><span>⚠</span><span>${w}</span></div>`)
      .join("");

    document.getElementById("mixGrid").innerHTML = mix.levels
      .map(
        (l) => `<div class="mix-card${l.recommended === 0 ? " is-zero" : ""}">
          <span class="mix-n">${l.recommended}</span>
          <span class="mix-lab">L${l.level} · ${l.short}</span>
          <span class="mix-yrs">${l.years_label}</span>
        </div>`
      )
      .join("");

    const charge = mix.charge_nurse_level;
    document.getElementById("mixMeta").innerHTML = `
      <span>Bedside nurses: <b>${mix.bedside_nurses}</b></span>
      <span>Charge nurse: <b>level ${charge} (Expert)</b></span>
      <span>Effective care capacity: <b>${fmt(mix.effective_capacity, 2)}</b></span>
      <span>Preceptors needed: <b>${mix.preceptors_needed}</b></span>`;

    renderMixChart(mix);

    document.getElementById("mixNote").textContent =
      "A nurse may always cover an assignment below their level, never above it, so " +
      "requirements accumulate from the expert tier downward. Novices are capped at 30% " +
      "of the bedside team and each is paired with a proficient or expert preceptor. " +
      "Experience weightings are a planning assumption based on Benner's novice-to-expert " +
      "framework, not values from a validated dataset.";
  }

  /* Three bars, all in nurses, stacked by competency level:
       1. what the infants' acuity demands, at the level each infant requires
       2. the roster this recommends (whole nurses, novice cap applied)
       3. what that roster actually delivers once experience is weighted
     Bar 3 shorter than bar 1 means the shift is numerically staffed but
     too junior to carry the workload. */
  function renderMixChart(mix) {
    if (!window.Chart) return;

    const demand = {}, roster = {}, capacity = {};
    mix.levels.forEach((l) => {
      demand[l.level] = l.demand;
      roster[l.level] = l.recommended;
      capacity[l.level] = +(l.recommended * l.capacity).toFixed(2);
    });

    const totalDemand = mix.levels.reduce((s, l) => s + l.demand, 0);
    const totalCapacity = mix.effective_capacity;

    const datasets = [4, 3, 2, 1].map((lv) => {
      const info = mix.levels.find((l) => l.level === lv);
      return {
        label: `L${lv} ${info.short}`,
        data: [demand[lv], roster[lv], capacity[lv]],
        backgroundColor: LEVEL_FILL[lv],
        borderRadius: 3,
        borderSkipped: false,
      };
    });

    if (mixChart) mixChart.destroy();
    mixChart = new Chart(document.getElementById("chartSkillMix"), {
      type: "bar",
      data: {
        labels: ["Acuity demand", "Recommended roster", "Effective capacity"],
        datasets,
      },
      options: {
        indexAxis: "y",
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { position: "bottom", labels: { usePointStyle: true, boxWidth: 8 } },
          tooltip: {
            callbacks: {
              label: (t) => `${t.dataset.label}: ${Number(t.raw).toFixed(2)} nurses`,
              footer: (items) => {
                const total = items.reduce((s, i) => s + Number(i.raw), 0);
                return `Total: ${total.toFixed(2)} nurses`;
              },
            },
          },
        },
        scales: {
          x: {
            stacked: true, beginAtZero: true, grid: { color: GRID },
            title: { display: true, text: "Nurses" },
          },
          y: { stacked: true, grid: { display: false } },
        },
      },
    });

    // Plain-language verdict, so the comparison is not left to the eye alone.
    const gap = totalCapacity - totalDemand;
    const verdict = document.getElementById("mixVerdict");
    if (gap >= 0) {
      verdict.className = "mix-verdict ok";
      verdict.textContent =
        `Covered — this roster delivers ${fmt(totalCapacity, 2)} nurses of effective care ` +
        `against ${fmt(totalDemand, 2)} of demand (${fmt(gap, 2)} in hand).`;
    } else {
      verdict.className = "mix-verdict short";
      verdict.textContent =
        `Short by ${fmt(Math.abs(gap), 2)} nurses — the headcount meets the count, but once ` +
        `experience is weighted the team delivers ${fmt(totalCapacity, 2)} against ` +
        `${fmt(totalDemand, 2)} of demand. Consider a more senior mix.`;
    }
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
