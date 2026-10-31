"use strict";
/* Patient journey page: loads the model bundle from the NeoStay server, checks
   it (NeoJourney.load runs its check cases), and computes the journey in the
   browser from what is typed in. Nothing typed here is sent anywhere. */
neoReady(async () => {
  const $ = (id) => document.getElementById(id);
  const status = $("journeyStatus");
  const esc = (s) =>
    String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const label = (code) => String(code).replace(/_/g, " ");
  const pct = (v) => `${Math.round(v * 100)}%`;

  if (window.NEOSTAY_ACCESS && window.NEOSTAY_ACCESS.mode === "sealed") {
    status.textContent = "The journey model is available on a NeoStay server only, not in this published copy.";
    return;
  }

  let bundle;
  try {
    const response = await fetch("api/journey/bundle", {
      credentials: "same-origin", cache: "no-store", headers: { Accept: "application/json" },
    });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) {
      status.textContent = typeof body.detail === "string" ? body.detail : "The journey model could not be loaded.";
      return;
    }
    bundle = NeoJourney.load(body);
  } catch (error) {
    status.textContent = `The journey model could not be used: ${error.message}`;
    return;
  }
  const T = bundle.inputs;
  status.textContent = `Model ${bundle.version}, trained on ${bundle.training_data.boards} boards ` +
    `(${bundle.training_data.boards_from} to ${bundle.training_data.boards_to}).`;
  $("journeyGrid").hidden = false;

  /* ---------------- the form ---------------- */
  const options = (values, { empty, labels } = {}) =>
    (empty ? `<option value="">${esc(empty)}</option>` : "") +
    values.map((v) => `<option value="${esc(v)}">${esc(labels ? labels(v) : v)}</option>`).join("");
  const respKeys = Object.keys(T.resp_status).filter((k) => T.resp_status[k].tier !== null);

  $("ratio").innerHTML = options(T.acuity_ratios, { empty: "Not recorded" });
  $("ratio").value = T.acuity_ratios[1];
  $("resp").innerHTML = options(respKeys, { empty: "Not recorded" });
  $("resp").value = "RA";
  $("feeds").innerHTML = options(Object.keys(T.feeds), { empty: "Not recorded" });
  $("spells").innerHTML = options(Object.keys(T.spells), { labels: label });
  $("spells").value = "not_recorded";
  $("nas").innerHTML = options(T.nas_band, { empty: "Not scored" });
  $("area").innerHTML = options(T.care_area, { labels: label });
  $("procedure").innerHTML = options(T.procedure, { empty: "None", labels: label });
  $("lines").innerHTML = T.iv.tokens
    .map((t) => `<label><input type="checkbox" value="${esc(t)}" /> ${esc(t.replace("_", " "))}</label>`).join("");
  $("day").innerHTML = options(NeoJourney.DAY_NAMES);
  const now = new Date();
  $("day").value = NeoJourney.DAY_NAMES[(now.getDay() + 6) % 7];
  $("shift").value = now.getHours() >= 7 && now.getHours() < 19 ? "AM" : "PM";

  const EARLIER = 4;
  $("history").innerHTML =
    "<thead><tr><th scope=\"col\">Hours ago</th><th scope=\"col\">Ratio</th><th scope=\"col\">Respiratory</th>" +
    "<th scope=\"col\">Weight (g)</th></tr></thead><tbody>" +
    Array.from({ length: EARLIER }, (_, i) => `<tr data-ago="${i + 1}"><th scope="row">${(i + 1) * 12}</th>
      <td><select class="h-ratio" aria-label="Ratio ${(i + 1) * 12} hours ago">${options(T.acuity_ratios, { empty: "—" })}</select></td>
      <td><select class="h-resp" aria-label="Respiratory ${(i + 1) * 12} hours ago">${options(respKeys, { empty: "—" })}</select></td>
      <td><input type="number" class="h-weight" min="300" max="8000" step="10" aria-label="Weight ${(i + 1) * 12} hours ago" /></td></tr>`)
      .join("") + "</tbody>";

  const num = (id) => ($(id).value === "" ? null : Number($(id).value));
  const val = (id) => $(id).value || null;

  function readForm() {
    const record = {
      ga_weeks: num("ga"), bw_g: num("bw"), dol: num("dol"), weight_g: num("weight"),
      shifts_in_unit: num("shifts"), shift: val("shift"), day_of_week: val("day"),
      acuity_ratio: val("ratio"), resp_status: val("resp"), feeds: val("feeds"),
      iv_lines: Array.from($("lines").querySelectorAll("input:checked")).map((el) => el.value),
      iv_fluids: $("ivFluids").checked, iv_saline_lock: $("salineLock").checked,
      spells: val("spells"), nas_band: val("nas"), procedure: val("procedure"), care_area: val("area"),
      has_education_need: $("education").checked,
    };
    const history = [];
    $("history").querySelectorAll("tbody tr").forEach((row) => {
      const ago = Number(row.dataset.ago);
      const entry = {
        shifts_ago: ago,
        acuity_ratio: row.querySelector(".h-ratio").value || null,
        resp_status: row.querySelector(".h-resp").value || null,
        weight_g: row.querySelector(".h-weight").value === "" ? null : Number(row.querySelector(".h-weight").value),
      };
      const filled = entry.acuity_ratio || entry.resp_status || entry.weight_g !== null;
      if (filled && ago <= (record.shifts_in_unit || 0)) history.push(entry);
    });
    return { record, history };
  }

  /* ---------------- the results ---------------- */
  // Ratio levels in one hue, light (1:3-4) to dark (1:1); having left the unit in neutral grey.
  const RATIO_COLORS = ["#cfe9e8", "#93cfcc", "#4fb0ad", "#0e8a8f", "#0a5458"];
  const GONE_COLOR = "#b9c3c7";
  let stayChart;
  let ratioChart;

  function render(result) {
    const stay = result.remaining_stay;
    const horizon = stay.horizon_days;
    const days = (d) => (d === null ? `> ${horizon}` : d.toFixed(1).replace(/\.0$/, ""));
    $("medianDays").textContent = stay.beyond_horizon ? `> ${horizon}` : days(stay.median_days);
    $("iqrDays").textContent = `${days(stay.quartile_days[0])} – ${days(stay.quartile_days[1])} days`;
    $("goneBy").innerHTML = Object.entries(stay.p_gone_by_day)
      .map(([d, p]) => `<div><span>${d === "1" ? "1 day" : `${d} days`}</span><b>${pct(p)}</b></div>`).join("");

    const hours = bundle.settings.shift_hours;
    const xs = stay.survival.map((_, i) => ((i + 1) * hours) / 24);
    if (stayChart) stayChart.destroy();
    stayChart = new Chart($("chartStay"), {
      type: "line",
      data: {
        datasets: [{
          label: "Still in the unit", data: stay.survival.map((s, i) => ({ x: xs[i], y: s * 100 })),
          borderColor: "#0e8a8f", backgroundColor: "rgba(14,138,143,0.10)", fill: true,
          stepped: true, pointRadius: 0, borderWidth: 2,
        }],
      },
      options: {
        responsive: true, maintainAspectRatio: false, interaction: { mode: "index", intersect: false },
        plugins: { legend: { display: false } },
        scales: {
          x: { type: "linear", min: 0, max: horizon, title: { display: true, text: "Days from now" } },
          y: { min: 0, max: 100, title: { display: true, text: "%" } },
        },
      },
    });

    const steps = result.acuity_journey;
    const ratios = T.acuity_ratios;
    const datasets = ratios.map((r, k) => ({
      label: r, data: steps.map((s) => s.ratio[r] * 100), backgroundColor: RATIO_COLORS[k % RATIO_COLORS.length],
      borderColor: "#ffffff", borderWidth: 1, stack: "s",
    }));
    datasets.push({
      label: "Left the unit", data: steps.map((s) => (1 - s.p_in_unit) * 100),
      backgroundColor: GONE_COLOR, borderColor: "#ffffff", borderWidth: 1, stack: "s",
    });
    if (ratioChart) ratioChart.destroy();
    ratioChart = new Chart($("chartRatio"), {
      type: "bar",
      data: { labels: steps.map((s) => `${s.hours_ahead} h`), datasets },
      options: {
        responsive: true, maintainAspectRatio: false, interaction: { mode: "index", intersect: false },
        plugins: { legend: { position: "bottom" } },
        scales: { x: { stacked: true }, y: { stacked: true, min: 0, max: 100, title: { display: true, text: "%" } } },
      },
    });

    $("ratioTable").innerHTML =
      `<thead><tr><th scope="col">Hours ahead</th><th scope="col">In the unit</th>${ratios
        .map((r) => `<th scope="col">${esc(r)}</th>`).join("")}<th scope="col">Expected nurses</th></tr></thead><tbody>${steps
        .map((s) => `<tr><th scope="row">${s.hours_ahead}</th><td>${pct(s.p_in_unit)}</td>${ratios
          .map((r) => `<td>${pct(s.ratio[r])}</td>`).join("")}<td>${s.expected_nurses.min.toFixed(2)}–${s.expected_nurses.max
          .toFixed(2)}</td></tr>`).join("")}</tbody>`;

    $("journeyPlaceholder").hidden = true;
    $("journeyResults").hidden = false;
  }

  function renderCard() {
    const perf = bundle.performance || {};
    const stay = perf.remaining_stay && perf.remaining_stay.test_primary;
    const acu = perf.acuity && perf.acuity.test_primary;
    const ci = (p) => (p && p.ci ? ` (95% interval ${p.ci[0].toFixed(3)}–${p.ci[1].toFixed(3)})` : "");
    const td = bundle.training_data;
    $("modelCard").innerHTML = `
      <p><b>Version</b> ${esc(bundle.version)} · trained on ${td.landmarks.toLocaleString()} baby-shifts from
      ${td.stays} stays, ${esc(td.boards_from)} to ${esc(td.boards_to)}.</p>
      <p><b>Remaining stay</b>: ${esc(bundle.models.remaining_stay.type.replace(/_/g, " "))}.
      ${stay ? `Integrated Brier score on the held-out period ${stay.score.toFixed(3)}${ci(stay)} (lower is better).` : ""}</p>
      <p><b>Nurse ratio</b>: ${esc(bundle.models.acuity.type.replace(/_/g, " "))}.
      ${acu ? `Log loss on the held-out period ${acu.score.toFixed(3)}${ci(acu)} (lower is better).` : ""}</p>
      <p class="staff-note">${esc(bundle.intended_use || "")}</p>`;
  }

  renderCard();
  $("journeyForm").addEventListener("submit", (event) => {
    event.preventDefault();
    const { record, history } = readForm();
    try {
      render(NeoJourney.predict(bundle, record, history));
    } catch (error) {
      if (error.kind === "input") toast(error.message);
      else throw error;
    }
  });
});
