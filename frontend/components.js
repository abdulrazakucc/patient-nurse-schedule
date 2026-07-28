"use strict";
/* Shared layout: renders the top bar + footer on every page and highlights
   the active link. Each page sets <body data-page="predict"> etc. */

const NAV = [
  { id: "home", label: "Home", href: "index.html" },
  { id: "predict", label: "Predict", href: "predict.html" },
  { id: "schedule", label: "Scheduling", href: "schedule.html" },
  { id: "timeline", label: "Timeline", href: "timeline.html" },
  { id: "analytics", label: "Analytics", href: "analytics.html" },
  { id: "about", label: "About", href: "about.html" },
];

function renderChrome() {
  const page = document.body.dataset.page || "home";

  const header = document.createElement("header");
  header.className = "topbar";
  header.innerHTML = `
    <a class="brand" href="index.html">
      <div class="brand-mark">
        <svg viewBox="0 0 24 24" width="26" height="26" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
          <path d="M12 21s-6.5-4.35-9-8.5C1 9 2.5 5.5 6 5.5c2 0 3.2 1.1 4 2.3.8-1.2 2-2.3 4-2.3 3.5 0 5 3.5 3 7-2.5 4.15-9 8.5-9 8.5z"/>
        </svg>
      </div>
      <div class="brand-text">
        <h1>NeoStay</h1>
        <span>Infant NICU Outcome &amp; Staffing Intelligence</span>
      </div>
    </a>
    <nav class="nav">
      ${NAV.map(
        (n) => `<a href="${n.href}" class="${n.id === page ? "active" : ""}">${n.label}</a>`
      ).join("")}
    </nav>
    <div class="center-pill" id="centerPill">Center 267 · 2016–2026</div>
  `;

  const footer = document.createElement("footer");
  footer.className = "footer";
  footer.innerHTML =
    "NeoStay · Internal decision-support prototype · Data restricted to local use.";

  const aurora = document.createElement("div");
  aurora.className = "aurora";

  document.body.prepend(header);
  document.body.prepend(aurora);
  document.body.appendChild(footer);
  loadMeta();
}

async function getJSON(path, opts) {
  const res = await fetch(path, opts);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

const fmt = (v, d = 0) => (v === null || v === undefined ? "-" : Number(v).toFixed(d));

async function loadMeta() {
  try {
    const meta = await getJSON("/api/meta");
    const pill = document.getElementById("centerPill");
    if (pill) pill.textContent = `${meta.center} · ${meta.period}`;
    return meta;
  } catch (e) {
    return null;
  }
}

document.addEventListener("DOMContentLoaded", renderChrome);
