"use strict";
/* Shared layout: renders the top bar + footer on every page, highlights the
   active link, and provides small shared helpers (icons, toast, formatting).
   Each page sets <body data-page="predict"> etc. */

const NAV = [
  { id: "home", label: "Home", href: "index.html" },
  { id: "predict", label: "Predict", href: "predict.html" },
  { id: "schedule", label: "Scheduling", href: "schedule.html" },
  { id: "timeline", label: "Timeline", href: "timeline.html" },
  { id: "analytics", label: "Analytics", href: "analytics.html" },
  { id: "about", label: "About", href: "about.html" },
];

/* Small inline SVG icon set (stroke inherits currentColor). */
const ICONS = {
  logo: '<svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 21s-6.5-4.35-9-8.5C1 9 2.5 5.5 6 5.5c2 0 3.2 1.1 4 2.3.8-1.2 2-2.3 4-2.3 3.5 0 5 3.5 3 7-2.5 4.15-9 8.5-9 8.5z"/></svg>',
  menu: '<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M4 7h16M4 12h16M4 17h16"/></svg>',
  close: '<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M6 6l12 12M18 6L6 18"/></svg>',
  pulse: '<svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12h4l2.5-6 4 12 2.5-6h5"/></svg>',
  nurse: '<svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="8" r="3.5"/><path d="M5 20c0-3.6 3.1-6 7-6s7 2.4 7 6"/><path d="M12 6.2v3.6M10.2 8h3.6"/></svg>',
  chart: '<svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M4 20V8M10 20V4M16 20v-9M21 20H3"/></svg>',
  home: '<svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M3.5 10.5 12 3.5l8.5 7"/><path d="M6 9v11h12V9"/><path d="M10 20v-5h4v5"/></svg>',
  transfer: '<svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M3 16V8a1 1 0 0 1 1-1h9v9"/><path d="M13 10h4l3 3v3h-2.2"/><circle cx="7.5" cy="17" r="1.8"/><circle cx="16.5" cy="17" r="1.8"/><path d="M9.3 16.8h5"/></svg>',
  dove: '<svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M20.5 5.5c-5 0-8 2.5-9.5 5C9.5 8 7 7 4 7c1 2.5 2 4 4.5 5.5C6 13 4.5 13 3 12.5 5 16.5 9 18.5 13 17.5s7.5-5 7.5-12z"/></svg>',
  baby: '<svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="8.5"/><path d="M12 3.5c1.8 0 2.6 1.2 2.4 2.6"/><circle cx="9.3" cy="11" r="0.4" fill="currentColor"/><circle cx="14.7" cy="11" r="0.4" fill="currentColor"/><path d="M9.8 14.5c1.3 1 3.1 1 4.4 0"/></svg>',
  calendar: '<svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><rect x="3.5" y="5" width="17" height="15.5" rx="2.5"/><path d="M8 3v4M16 3v4M3.5 10h17"/><path d="M8 14h2.5M13.5 14H16M8 17h2.5"/></svg>',
  flask: '<svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M9.5 3h5M10.5 3v5.2L4.8 18a2 2 0 0 0 1.8 3h10.8a2 2 0 0 0 1.8-3l-5.7-9.8V3"/><path d="M7.5 14.5h9"/></svg>',
  shield: '<svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3l7.5 3v5.5c0 4.7-3.2 8-7.5 9.5-4.3-1.5-7.5-4.8-7.5-9.5V6z"/><path d="M9 12l2.2 2.2L15.5 9.9"/></svg>',
  clock: '<svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/></svg>',
  sparkle: '<svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M12 4l1.8 4.6L18.5 10l-4.7 1.4L12 16l-1.8-4.6L5.5 10l4.7-1.4z"/><path d="M18.5 15.5l.9 2.1 2.1.9-2.1.9-.9 2.1-.9-2.1-2.1-.9 2.1-.9z"/></svg>',
};

function icon(name, size) {
  let svg = ICONS[name] || "";
  if (size) svg = svg.replace(/width="\d+" height="\d+"/, `width="${size}" height="${size}"`);
  return svg;
}

function renderChrome() {
  const page = document.body.dataset.page || "home";

  const header = document.createElement("header");
  header.className = "topbar";
  header.innerHTML = `
    <a class="brand" href="index.html" aria-label="NeoStay home">
      <div class="brand-mark">${icon("logo")}</div>
      <div class="brand-text">
        <h1>NeoStay</h1>
        <span>Infant NICU Outcome &amp; Staffing Intelligence</span>
      </div>
    </a>
    <button class="nav-toggle" id="navToggle" aria-label="Open menu" aria-expanded="false">${icon("menu")}</button>
    <nav class="nav" id="navMenu" aria-label="Main navigation">
      ${NAV.map(
        (n) => `<a href="${n.href}" class="${n.id === page ? "active" : ""}" ${n.id === page ? 'aria-current="page"' : ""}>${n.label}</a>`
      ).join("")}
    </nav>
    <div class="center-pill" id="centerPill">Center 267 · 2016–2026</div>
  `;

  const footer = document.createElement("footer");
  footer.className = "footer";
  footer.innerHTML = `
    <div class="footer-inner">
      <div class="footer-brand">
        <div class="brand-mark">${icon("logo", 20)}</div>
        <div><b>NeoStay</b><span>Neonatal outcome &amp; staffing intelligence</span></div>
      </div>
      <div class="footer-links">
        ${NAV.map((n) => `<a href="${n.href}">${n.label}</a>`).join("")}
        <a href="https://github.com/abdulrazakucc/patient-nurse-schedule" rel="noopener" target="_blank">Source code</a>
      </div>
    </div>
    <div class="footer-note">
      <span>Built on aggregated, de-identified outcome statistics (2016–2026). All calculations run
      in your browser — no data is sent to any server.</span>
      <span class="badge-warn">${icon("shield", 14)} Decision support only — not for clinical use</span>
    </div>
    <div class="footer-credit">Prepared by Abdul Razak, PhD</div>
  `;

  const aurora = document.createElement("div");
  aurora.className = "aurora";

  document.body.prepend(header);
  document.body.prepend(aurora);
  document.body.appendChild(footer);

  // Mobile menu
  const toggle = document.getElementById("navToggle");
  const menu = document.getElementById("navMenu");
  toggle.addEventListener("click", () => {
    const open = menu.classList.toggle("open");
    toggle.innerHTML = icon(open ? "close" : "menu");
    toggle.setAttribute("aria-expanded", String(open));
    toggle.setAttribute("aria-label", open ? "Close menu" : "Open menu");
  });

  // Center pill from bundled dataset
  if (window.NeoEngine) {
    const meta = NeoEngine.meta();
    const pill = document.getElementById("centerPill");
    if (pill) pill.textContent = `${meta.center} · ${meta.period}`;
  }

  // Inject section-label icons declared as data-icon attributes
  document.querySelectorAll("[data-icon]").forEach((el) => {
    el.insertAdjacentHTML("afterbegin", icon(el.dataset.icon, el.dataset.iconSize));
  });
}

const fmt = (v, d = 0) => (v === null || v === undefined ? "–" : Number(v).toFixed(d));

/* Animated numeric count-up (used for stats and rings). */
function countUp(el, target, { decimals = 0, duration = 700, suffix = "" } = {}) {
  if (target === null || target === undefined || isNaN(target)) {
    el.textContent = "–";
    return;
  }
  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (reduced) {
    el.textContent = Number(target).toFixed(decimals) + suffix;
    return;
  }
  const start = performance.now();
  const from = 0;
  const step = (now) => {
    const t = Math.min(1, (now - start) / duration);
    const eased = 1 - Math.pow(1 - t, 3);
    el.textContent = (from + (target - from) * eased).toFixed(decimals) + suffix;
    if (t < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}

/* Toast notification (replaces alert()). */
let toastTimer;
function toast(message) {
  let el = document.querySelector(".toast");
  if (!el) {
    el = document.createElement("div");
    el.className = "toast";
    el.setAttribute("role", "status");
    document.body.appendChild(el);
  }
  el.textContent = message;
  requestAnimationFrame(() => el.classList.add("show"));
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove("show"), 3200);
}

document.addEventListener("DOMContentLoaded", renderChrome);
