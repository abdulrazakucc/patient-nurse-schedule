"use strict";
/* Scheduling page: census management + unit staffing via the client-side engine. */
document.addEventListener("DOMContentLoaded", () => {
  const census = [];

  // Competency colours, aligned with the .lvl-N badges.
  const LEVEL_FILL = { 1: "#8aa4b0", 2: "#0e8a8f", 3: "#c9a24b", 4: "#d5637a" };
  const GRID = "rgba(14,43,54,0.07)";
  if (window.Chart) Chart.defaults.font.family = "Inter";
  let mixChart, rosterChart;

  // Nurses in hand. Defaults describe a mid-sized unit; the user edits freely.
  const DEFAULT_AVAILABLE = { 1: 4, 2: 6, 3: 6, 4: 4 };
  const available = { ...DEFAULT_AVAILABLE };
  const LEVELS = NeoEngine.nurseLevels();

  /* ---------------- availability panel ---------------- */
  function buildAvailability() {
    document.getElementById("availGrid").innerHTML = LEVELS.map(
      (l) => `
      <div class="avail-item">
        <span class="lvl lvl-${l.level}">L${l.level} ${l.short}</span>
        <div class="avail-stepper">
          <button type="button" data-step="-1" data-lv="${l.level}" aria-label="One fewer ${l.short} nurse">−</button>
          <input type="number" min="0" max="99" step="1" id="avail-${l.level}"
                 value="${available[l.level]}" aria-label="${l.short} nurses available" />
          <button type="button" data-step="1" data-lv="${l.level}" aria-label="One more ${l.short} nurse">+</button>
        </div>
        <span class="avail-yrs">${l.years_label}</span>
      </div>`
    ).join("");

    document.getElementById("availGrid").addEventListener("click", (e) => {
      const btn = e.target.closest("button[data-step]");
      if (!btn) return;
      const lv = Number(btn.dataset.lv);
      available[lv] = Math.max(0, available[lv] + Number(btn.dataset.step));
      document.getElementById(`avail-${lv}`).value = available[lv];
      refresh();
    });
    document.getElementById("availGrid").addEventListener("input", (e) => {
      if (e.target.tagName !== "INPUT") return;
      const lv = Number(e.target.id.split("-")[1]);
      available[lv] = Math.max(0, Number(e.target.value) || 0);
      refresh();
    });

    document.getElementById("availReset").addEventListener("click", () => {
      Object.assign(available, DEFAULT_AVAILABLE);
      syncAvailInputs();
      refresh();
    });
    document.getElementById("availAuto").addEventListener("click", autoFill);
  }

  function syncAvailInputs() {
    LEVELS.forEach((l) => {
      const el = document.getElementById(`avail-${l.level}`);
      if (el) el.value = available[l.level];
    });
  }

  /* Raise staffing until every infant can be covered on every shift. */
  function autoFill() {
    if (census.length === 0) {
      toast("Add infants to the census first.");
      return;
    }
    const shifts = Number(document.getElementById("sShifts").value);
    for (let guard = 0; guard < 60; guard++) {
      const rows = NeoEngine.scheduleUnit(census, shifts).infants;
      const roster = NeoEngine.buildRoster(rows, available, shifts);
      if (roster.covered) break;
      // Add the shortfall, once per shift, at the level each gap requires.
      const need = roster.additional_nurses_needed;
      const levels = Object.keys(need).map(Number).sort((a, b) => b - a);
      if (!levels.length) break;
      available[levels[0]] += shifts;
    }
    syncAvailInputs();
    refresh();
    toast("Staffing raised until every infant is covered.");
  }

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
    updateAvailTotal();

    if (census.length === 0) {
      document.getElementById("roster").hidden = true;
      document.getElementById("rosterEmpty").hidden = false;
      document.getElementById("skillMixCard").hidden = true;
      document.getElementById("rosterCard").hidden = true;
      document.getElementById("statusBanner").hidden = true;
      setMetrics({ census: 0, nurses_per_shift: 0, daily_nurse_shifts: 0, total_demand: 0 });
      document.getElementById("schedNote").textContent = "";
      return;
    }
    const r = NeoEngine.scheduleUnit(census, shifts);
    setMetrics(r);
    document.getElementById("schedNote").textContent = r.note;
    renderSkillMix(r.skill_mix);

    const roster = NeoEngine.buildRoster(r.infants, available, shifts);
    renderStatus(roster, r);
    renderRosterChart(roster, r);

    document.getElementById("rosterEmpty").hidden = true;
    const table = document.getElementById("roster");
    table.hidden = false;
    const body = document.getElementById("rosterBody");
    body.innerHTML = "";
    // An infant nobody could be assigned to, on any shift.
    const uncovered = new Set();
    roster.shifts.forEach((s) => s.unassigned.forEach((i) => uncovered.add(i)));

    r.infants.forEach((inf, i) => {
      const tr = document.createElement("tr");
      if (uncovered.has(inf.index)) tr.className = "row-uncovered";
      tr.innerHTML = `
        <td>${inf.index}</td>
        <td>${inf.weight_g} g</td>
        <td>${inf.ga_weeks} wk</td>
        <td>${CONDITION_LABEL[inf.condition] || inf.condition}</td>
        <td>${RESP_LABEL[inf.resp_support] || inf.resp_support}</td>
        <td><span class="pill pill-${inf.acuity}">${inf.acuity}</span></td>
        <td>${inf.nurses_required.toFixed(2)}${uncovered.has(inf.index) ? '<span class="tag-uncovered">uncovered</span>' : ""}</td>
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

  function updateAvailTotal() {
    const total = LEVELS.reduce((s, l) => s + available[l.level], 0);
    const shifts = Number(document.getElementById("sShifts").value);
    document.getElementById("availTotal").innerHTML =
      `<b>${total}</b> nurses in hand · about <b>${Math.floor(total / shifts)}</b> per shift`;
  }

  /* ---------------- headline status ---------------- */
  function renderStatus(roster, sched) {
    const el = document.getElementById("statusBanner");
    el.hidden = false;

    if (!roster.covered) {
      const need = roster.additional_nurses_needed;
      const shifts = roster.shifts_per_day;
      const parts = Object.keys(need)
        .map(Number)
        .sort((a, b) => b - a)
        .map((lv) => {
          const info = NeoEngine.levelInfo(lv);
          const n = need[lv] * shifts;
          return `<span class="lvl lvl-${lv}">+${n} × L${lv} ${info.short}</span>`;
        })
        .join(" ");
      const worst = Math.max(...roster.shifts.map((s) => s.unassigned.length));
      el.className = "status-banner short";
      el.innerHTML = `
        <span class="sb-ic">!</span>
        <div>
          <b>Demand exceeds the nurses available</b>
          ${worst} infant${worst === 1 ? "" : "s"} cannot be given a qualified nurse on the
          worst-affected shift. Those cots are highlighted in the census below and shown in red
          on the 24-hour roster.
          <div class="sb-actions">To close the gap across all ${shifts} shifts, add: ${parts}</div>
        </div>`;
      return;
    }

    // Covered only because the charge nurse took a cot - flag it.
    if (roster.charge_carrying_bedside) {
      el.className = "status-banner tight";
      el.innerHTML = `
        <span class="sb-ic">!</span>
        <div>
          <b>Covered, but the charge nurse is at a cot</b>
          Every infant has a qualified nurse only because the charge nurse took a bedside
          assignment. That leaves nobody free to coordinate the unit, take admissions or
          respond to a deterioration. One more senior nurse would restore the charge role.
        </div>`;
      return;
    }

    // Covered - but is there any slack left for an admission?
    const tightest = Math.max(...roster.shifts.map((s) => s.mean_load));
    const spare = roster.shifts.map(
      (s) => s.capacity_hours - s.committed_hours
    );
    const minSpare = Math.min(...spare);
    if (tightest >= 0.95) {
      el.className = "status-banner tight";
      el.innerHTML = `
        <span class="sb-ic">!</span>
        <div>
          <b>Covered, but running at capacity</b>
          Every infant has a qualified nurse, yet bedside nurses are at
          ${fmt(tightest * 100, 0)}% of their assignment limit on the busiest shift.
          A single admission or deterioration would leave you short.
        </div>`;
    } else {
      el.className = "status-banner ok";
      el.innerHTML = `
        <span class="sb-ic">✓</span>
        <div>
          <b>Fully covered</b>
          All ${sched.census} infant${sched.census === 1 ? "" : "s"} have a qualified nurse on every
          shift, with ${fmt(minSpare, 0)} spare nurse-hours on the tightest shift.
        </div>`;
    }
  }

  /* ---------------- 24-hour roster ----------------
     One row per nurse. The nursing day starts at 07:00, so shift blocks sit
     side by side on a 24-hour axis with no wrap around midnight. Each block
     splits into hours committed to infants and spare capacity, and any infant
     nobody could take gets its own red row. */
  function renderRosterChart(roster, sched) {
    const card = document.getElementById("rosterCard");
    card.hidden = false;
    if (!window.Chart) return;

    const rows = [];
    roster.shifts.forEach((s) => {
      const clock = s.label.split("-")[0];
      s.nurses.forEach((n) => {
        rows.push({
          label: `${clock} · ${n.id.replace(/^S\d+-/, "")} · L${n.level}${n.is_charge ? " charge" : ""}`,
          shift: s.label,
          nurse: n,
        });
      });
    });

    const uncoveredRows = [];
    roster.shifts.forEach((s) => {
      s.unassigned.forEach((idx) => {
        uncoveredRows.push({ shift: s.label, infant: idx, start: s.start_hour, end: s.end_hour });
      });
    });

    const labels = rows.map((r) => r.label);
    uncoveredRows.forEach((u) => labels.push(`Infant #${u.infant} · unassigned`));

    // Floating bars: [startHour, endHour] on a 0-24 axis beginning at 07:00.
    const committed = rows.map((r) => [
      r.nurse.shift_start,
      r.nurse.shift_start + r.nurse.allocated_hours,
    ]);
    const spare = rows.map((r) => [
      r.nurse.shift_start + r.nurse.allocated_hours,
      r.nurse.shift_end,
    ]);
    uncoveredRows.forEach(() => { committed.push(null); spare.push(null); });
    const gap = rows.map(() => null).concat(uncoveredRows.map((u) => [u.start, u.end]));

    const box = document.getElementById("rosterChartBox");
    box.style.height = `${Math.max(260, labels.length * 24 + 90)}px`;

    // Divider + name for each shift block, so the day/night split is obvious.
    const shiftBands = {
      id: "neoShiftBands",
      beforeDatasetsDraw(chart) {
        const { ctx, chartArea, scales } = chart;
        ctx.save();
        roster.shifts.forEach((s, i) => {
          const xa = scales.x.getPixelForValue(s.start_hour);
          const xb = scales.x.getPixelForValue(s.end_hour);
          if (i % 2 === 1) {
            ctx.fillStyle = "rgba(14,43,54,0.025)";
            ctx.fillRect(xa, chartArea.top, xb - xa, chartArea.bottom - chartArea.top);
          }
          if (i > 0) {
            ctx.strokeStyle = "rgba(14,43,54,0.18)";
            ctx.setLineDash([4, 4]);
            ctx.beginPath();
            ctx.moveTo(xa, chartArea.top);
            ctx.lineTo(xa, chartArea.bottom);
            ctx.stroke();
            ctx.setLineDash([]);
          }
          ctx.fillStyle = "#74909c";
          ctx.font = "700 10px Inter, sans-serif";
          ctx.textAlign = "center";
          ctx.fillText(s.label, (xa + xb) / 2, chartArea.top - 5);
        });
        ctx.restore();
      },
    };

    if (rosterChart) rosterChart.destroy();
    rosterChart = new Chart(document.getElementById("chartRoster"), {
      type: "bar",
      plugins: [shiftBands],
      data: {
        labels,
        datasets: [
          {
            label: "Committed to infants",
            data: committed,
            backgroundColor: rows.map((r) => LEVEL_FILL[r.nurse.level]),
            borderRadius: 3, borderSkipped: false, barPercentage: 0.78,
          },
          {
            label: "On duty, spare capacity",
            data: spare,
            backgroundColor: "#dbe7ec",
            borderRadius: 3, borderSkipped: false, barPercentage: 0.78,
          },
          {
            label: "Uncovered",
            data: gap,
            backgroundColor: "#d5637a",
            borderRadius: 3, borderSkipped: false, barPercentage: 0.78,
          },
        ],
      },
      options: {
        indexAxis: "y",
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              title: (t) => labels[t[0].dataIndex],
              label: (t) => {
                const r = rows[t.dataIndex];
                if (!r) {
                  const u = uncoveredRows[t.dataIndex - rows.length];
                  return u ? `No qualified nurse free on ${u.shift}` : "";
                }
                const n = r.nurse;
                if (t.datasetIndex === 0) {
                  const who = n.infants.length
                    ? `infants #${n.infants.join(", #")}`
                    : (n.is_charge ? "charge nurse — no bedside assignment" : "no assignment");
                  return [
                    `${r.shift} · ${n.level_name}`,
                    `${who}`,
                    `${fmt(n.allocated_hours, 1)} h committed = ${fmt(n.day_percent, 1)}% of the day`,
                  ];
                }
                if (t.datasetIndex === 1) {
                  return `${fmt(n.spare_hours, 1)} h spare (${fmt(100 - n.load * 100, 0)}% of the shift)`;
                }
                return "";
              },
            },
          },
        },
        layout: { padding: { top: 16 } },
        scales: {
          // The category axis is stacked so all three series share one row per
          // nurse; the value axis is not, so floating bars keep absolute hours.
          x: {
            stacked: false, min: 0, max: 24, grid: { color: GRID },
            title: { display: true, text: "Hour of the nursing day (starts 07:00)" },
            ticks: {
              stepSize: 3,
              callback: (v) => `${String((7 + v) % 24).padStart(2, "0")}:00`,
            },
          },
          y: {
            stacked: true, grid: { display: false },
            ticks: { autoSkip: false, font: { size: 10 } },
          },
        },
      },
    });

    const totalCommitted = roster.shifts.reduce((s, x) => s + x.committed_hours, 0);
    const totalCapacity = roster.shifts.reduce((s, x) => s + x.capacity_hours, 0);
    document.getElementById("rosterSub").textContent =
      `${roster.total_available} nurses split across ${roster.shifts_per_day} shifts. ` +
      `Each bar is one nurse's shift: the solid part is time committed to infants, ` +
      `the pale part is spare capacity. Unit-wide, ${fmt(totalCommitted, 0)} of ` +
      `${fmt(totalCapacity, 0)} rostered nurse-hours are committed ` +
      `(${fmt((totalCommitted / Math.max(1, totalCapacity)) * 100, 0)}%).`;

    document.getElementById("rosterNote").textContent = roster.note;
  }

  function setMetrics(r) {
    document.getElementById("mCensus").textContent = r.census ?? 0;
    document.getElementById("mNurses").textContent = r.nurses_per_shift ?? 0;
    document.getElementById("mDaily").textContent = r.daily_nurse_shifts ?? 0;
    document.getElementById("mDemand").textContent = fmt(r.total_demand ?? 0, 1);
  }

  document.getElementById("sShifts").addEventListener("change", refresh);
  buildAvailability();
  refresh();
});
