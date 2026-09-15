"use strict";
/* Acuity tool page: renders Dr. Altaf's classifier straight from the bundled
   data, so what is shown here is exactly what Scheduling classifies with. */
neoReady(() => {
  const TOOL = NeoEngine.acuityTool();
  if (!TOOL) return;

  const esc = (s) =>
    String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const lvl = (n) => `<span class="lvl lvl-${n}">L${n} ${NeoEngine.levelInfo(n).short}</span>`;
  const list = (items) =>
    items.length
      ? `<ul>${items.map((it) => `<li>${esc(it.label)}${it.one_to_one
          ? '<span class="one-tag" data-tip="Footnoted criterion: staffed 1:1, by an Expert nurse.">1:1</span>'
          : ""}</li>`).join("")}</ul>`
      : '<span class="na">—</span>';

  /* ---------------- acuity tool ---------------- */
  document.getElementById("acuityTitle").textContent = TOOL.title;

  const head = TOOL.columns
    .map((c) => `<th scope="col" data-tip="Planned at ${c.planning_ratio} (1 nurse to ${c.planning_ratio.split(":")[1]} infants)${c.key === "intensive" ? ", or 1:1 with an Expert nurse for the footnoted criteria" : ""}.">
      ${esc(c.name)}<span class="ratio-tag">${esc(c.ratio)}</span>${lvl(c.nurse_level)}</th>`)
    .join("");
  const rows = TOOL.systems
    .map((s) => `<tr><th scope="row">${esc(s.system)}</th>${TOOL.columns
      .map((c) => `<td>${list(s.items[c.key])}</td>`).join("")}</tr>`)
    .join("");
  const assessment = `<tr class="assess-row"><th scope="row">Nursing care</th>${TOOL.columns
    .map((c) => `<td>${esc(c.assessment)}</td>`).join("")}</tr>`;

  document.getElementById("acuityTable").innerHTML =
    `<thead><tr><th scope="col">Body system</th>${head}</tr></thead><tbody>${rows}${assessment}</tbody>`;
  document.getElementById("acuityFootnote").textContent = `1:1 staffing — ${TOOL.one_to_one.note}`;

  /* ---------------- levels of care ---------------- */
  function renderLevels(group, gridId, noteId) {
    document.getElementById(gridId).innerHTML = TOOL.care_levels
      .map((cl) => {
        const items = group.criteria.filter((c) => c.level === cl.level);
        return `<div class="card care-col">
          <div class="care-col-head"><span class="care-tag">${cl.code}</span>${lvl(cl.level)}</div>
          <h5>${esc(cl.name)}</h5>
          ${list(items)}
        </div>`;
      })
      .join("");
    document.getElementById(noteId).textContent = group.note;
  }
  renderLevels(TOOL.levels_of_care.general, "careGeneral", "careGeneralNote");
  renderLevels(TOOL.levels_of_care.hyperbilirubinemia, "careBili", "careBiliNote");
});
