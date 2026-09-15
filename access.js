"use strict";
/*
 * The sign-in gate every page loads first.
 *
 * Pages hold no data. This script finds out whether someone is signed in -- by
 * asking the NeoStay server, or by opening the sealed copy on GitHub Pages --
 * and shows the landing page with its sign-in form if nobody is. Only once the
 * data is available does it load the engine and the page's own scripts, listed
 * in data-app, in order. See access-config.js for the modes.
 */
(function () {
  const gate = document.currentScript;
  const APP_SCRIPTS = (gate.getAttribute("data-app") || "").split(/\s+/).filter(Boolean);
  const MODE = (window.NEOSTAY_ACCESS && window.NEOSTAY_ACCESS.mode) || "server";
  const DATA_SCRIPTS = ["data/neostay-data.js", "data/neostay-acuity.js", "data/neostay-timeseries.js"];
  const SEALED_GLOBALS = ["NEOSTAY_DATA", "NEOSTAY_ACUITY", "NEOSTAY_TS"];
  const STORE = "neostay-sealed-session";
  const WRONG = "Email or password is incorrect.";

  // Page scripts start through this; unlike DOMContentLoaded it also works for
  // a script loaded after the page has finished parsing.
  window.neoReady = (fn) => {
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", fn);
    else fn();
  };

  class GateError extends Error {
    constructor(message, kind) {
      super(message);
      this.kind = kind;
    }
  }

  function loadScript(src) {
    return new Promise((resolve, reject) => {
      const el = document.createElement("script");
      el.src = src;
      el.async = false;
      el.onload = resolve;
      el.onerror = () => reject(new GateError(`Could not load ${src}`, "load"));
      document.body.appendChild(el);
    });
  }

  function forget() {
    try {
      sessionStorage.removeItem(STORE);
    } catch {
      /* storage unavailable */
    }
  }

  /* ---------------- a NeoStay server checks the password ---------------- */

  const server = {
    async session() {
      let response;
      try {
        response = await fetch("api/auth/session", {
          credentials: "same-origin",
          cache: "no-store",
          headers: { Accept: "application/json" },
        });
      } catch {
        throw new GateError("The NeoStay server could not be reached. Check your connection and try again.", "load");
      }
      if (!response.ok) {
        throw new GateError("NeoStay's sign-in service is not available at this address. Contact your NeoStay administrator.", "load");
      }
      return response.json();
    },

    async login(email, password) {
      let response;
      try {
        response = await fetch("api/auth/login", {
          method: "POST",
          credentials: "same-origin",
          headers: { "Content-Type": "application/json", Accept: "application/json" },
          body: JSON.stringify({ email, password }),
        });
      } catch {
        throw new GateError("The NeoStay server could not be reached. Check your connection and try again.", "load");
      }
      let body = {};
      try {
        body = await response.json();
      } catch {
        /* no body */
      }
      const detail = typeof body.detail === "string" ? body.detail : "";
      if (response.status === 401 || response.status === 429) throw new GateError(detail || WRONG, "auth");
      if (!response.ok) throw new GateError(detail || "Sign-in is unavailable right now.", "load");
      // A browser refuses a secure cookie over plain http, which would look
      // like a sign-in that does nothing. Check, and say what to do instead.
      const session = await server.session();
      if (!session.authenticated) {
        throw new GateError(
          "Your password was accepted, but this browser did not keep the sign-in. Open NeoStay with an https:// address and allow cookies for this site.",
          "auth"
        );
      }
      return session;
    },

    async loadData() {
      for (const src of DATA_SCRIPTS) await loadScript(src);
    },

    async logout() {
      await fetch("api/auth/logout", { method: "POST", credentials: "same-origin" }).catch(() => {});
    },
  };

  /* ---------------- the sealed GitHub Pages copy ---------------- */

  const sealed = {
    bundle: null,

    async session() {
      if (!window.NeoSealed) throw new GateError("NeoStay did not load completely. Reload the page.", "load");
      let saved = null;
      try {
        saved = JSON.parse(sessionStorage.getItem(STORE) || "null");
      } catch {
        saved = null;
      }
      if (!saved) return { authenticated: false, mode: "sealed" };
      try {
        this.bundle = await NeoSealed.openBundle(NeoSealed.fromB64(saved.key));
        return { authenticated: true, mode: "sealed", email: saved.email };
      } catch (error) {
        forget();
        if (error.kind === "load") throw error;
        return { authenticated: false, mode: "sealed", notice: error.message };
      }
    },

    async login(email, password) {
      if (!window.NeoSealed) throw new GateError("NeoStay did not load completely. Reload the page.", "load");
      const key = await NeoSealed.unlock(email, password);
      this.bundle = await NeoSealed.openBundle(key);
      const record = { email: email.trim().toLowerCase(), key: NeoSealed.toB64(key) };
      try {
        // This tab only: closing it signs the reader out.
        sessionStorage.setItem(STORE, JSON.stringify(record));
      } catch {
        /* private mode: signed in until the page is left */
      }
      return { authenticated: true, mode: "sealed", email: record.email };
    },

    async loadData() {
      const globals = (this.bundle && this.bundle.globals) || {};
      for (const name of SEALED_GLOBALS) {
        if (!(name in globals)) throw new GateError("NeoStay's protected data is incomplete.", "load");
        window[name] = globals[name];
      }
      this.bundle = null;
    },

    async logout() {
      forget();
    },
  };

  const source = MODE === "sealed" ? sealed : server;

  /* ---------------- the landing page ----------------
     What a visitor sees before signing in: what NeoStay does, beside the
     sign-in form, in the same design as the pages inside. It holds no data. */

  // The same drawings as components.js, which only loads after sign-in.
  const DRAW = {
    logo: '<path d="M12 21s-6.5-4.35-9-8.5C1 9 2.5 5.5 6 5.5c2 0 3.2 1.1 4 2.3.8-1.2 2-2.3 4-2.3 3.5 0 5 3.5 3 7-2.5 4.15-9 8.5-9 8.5z"/>',
    medic: '<path d="M6 3v5a4 4 0 0 0 8 0V3"/><path d="M10 12v3.5a4.5 4.5 0 0 0 9 0V13"/><circle cx="19" cy="10.5" r="2"/>',
    shield: '<path d="M12 3l7.5 3v5.5c0 4.7-3.2 8-7.5 9.5-4.3-1.5-7.5-4.8-7.5-9.5V6z"/><path d="M9 12l2.2 2.2L15.5 9.9"/>',
    flask: '<path d="M9.5 3h5M10.5 3v5.2L4.8 18a2 2 0 0 0 1.8 3h10.8a2 2 0 0 0 1.8-3l-5.7-9.8V3"/><path d="M7.5 14.5h9"/>',
    calendar: '<rect x="3.5" y="5" width="17" height="15.5" rx="2.5"/><path d="M8 3v4M16 3v4M3.5 10h17"/><path d="M8 14h2.5M13.5 14H16M8 17h2.5"/>',
    pulse: '<path d="M3 12h4l2.5-6 4 12 2.5-6h5"/>',
    nurse: '<circle cx="12" cy="8" r="3.5"/><path d="M5 20c0-3.6 3.1-6 7-6s7 2.4 7 6"/><path d="M12 6.2v3.6M10.2 8h3.6"/>',
    clock: '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/>',
    chart: '<path d="M4 20V8M10 20V4M16 20v-9M21 20H3"/>',
    baby: '<circle cx="12" cy="12" r="8.5"/><path d="M12 3.5c1.8 0 2.6 1.2 2.4 2.6"/><circle cx="9.3" cy="11" r="0.4" fill="currentColor"/><circle cx="14.7" cy="11" r="0.4" fill="currentColor"/><path d="M9.8 14.5c1.3 1 3.1 1 4.4 0"/>',
    lock: '<rect x="5" y="11" width="14" height="9.5" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/>',
    check: '<path d="M5 12.5l4.2 4.2L19 7"/>',
  };
  const icon = (name, size = 17) =>
    `<svg viewBox="0 0 24 24" width="${size}" height="${size}" fill="none" stroke="currentColor" stroke-width="${name === "check" ? 2.6 : 1.9}" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${DRAW[name]}</svg>`;

  const POINTS = [
    "Length of stay, discharge outcome and survival, matched by birth weight and gestational age to a decade of center outcomes",
    "Nurse:patient ratios and the minimum nurse competency for each infant, from Dr. Altaf's acuity tool",
    "Shift-by-shift rosters built from the nurses your unit actually has",
  ];

  const FEATURES = [
    ["flask", "ic-teal", "Outcome &amp; staffing forecast",
      "Enter birth weight, gestational age, condition on admission and breathing support to see the expected length of stay with its realistic range, the chance of going home, transfer or death, and the nursing the stay will need."],
    ["calendar", "ic-gold", "Unit nurse scheduling",
      "Build the unit's census and get nurses per shift, the recommended skill mix and a 24-hour roster that flags any infant left without a qualified nurse."],
    ["pulse", "ic-rose", "Acuity tool &amp; levels of care",
      "Dr. Waseem Altaf's neonatal acuity tool and nursing levels of care set each infant's nurse:patient ratio and the minimum competency of the nurse assigned."],
    ["nurse", "ic-slate", "Nurse competency",
      "Nurses are grouped by Benner's novice-to-expert stages, so every plan checks not only how many nurses are on shift, but whether they are experienced enough."],
    ["clock", "ic-teal", "Hourly timeline",
      "Follow individual infant journeys and whole-unit nursing demand hour by hour across a simulated year of care."],
    ["chart", "ic-gold", "Population analytics",
      "Interactive charts of length of stay and discharge outcomes across every birth-weight band and gestational week."],
  ];

  const STEPS = [
    ["Sign in", "Use the account your NeoStay administrator created for you. Every page and all data stay locked until you do."],
    ["Describe the infant", "Birth weight, gestational age, condition on admission and breathing support — or the findings from the acuity tool."],
    ["Read the forecast", "Expected stay and its range, likely discharge outcome and survival, each with a confidence signal based on how many similar infants stand behind it."],
    ["Plan the nursing", "Ratios, nurse-hours, skill mix and a 24-hour roster for the whole unit, recalculated the moment anything changes."],
  ];

  const PRINCIPLES = [
    ["shield", "Registered users only",
      "Every page opens here. Accounts are created by a NeoStay administrator, and signing out locks the application again."],
    ["baby", "Aggregated data, no patient records",
      "NeoStay is built on aggregated center outcome statistics. No patient-level data is loaded, entered or stored, and what you type into the tools stays in your browser."],
    ["medic", "Decision support, not a medical device",
      "NeoStay informs planning and discussion. It does not replace clinical judgment, and final assignments rest with the charge nurse."],
  ];

  function landing(panel) {
    removeScreen();
    document.title = "NeoStay · Infant NICU Outcome & Staffing Intelligence";
    const wrap = document.createElement("div");
    wrap.className = "landing";
    wrap.id = "neoGateScreen";
    wrap.innerHTML = `
      <div class="aurora"></div>
      <div class="credit-strip">${icon("medic", 15)}<span>Project and Clinical Lead — <b>Waseem Altaf,&nbsp;MD</b>, Neonatologist</span></div>
      <header class="topbar">
        <a class="brand" href="index.html" aria-label="NeoStay home">
          <div class="brand-mark">${icon("logo", 24)}</div>
          <div class="brand-text"><h1>NeoStay</h1><span>Infant NICU Outcome &amp; Staffing Intelligence</span></div>
        </a>
        <span class="landing-chip">${icon("lock", 14)}<span>Registered users only</span></span>
      </header>
      <main class="landing-main">
        <section class="landing-hero">
          <div class="hero-copy landing-intro">
            <div class="eyebrow">Neonatal decision support</div>
            <h2>Forecast the NICU stay. <em>Staff it safely.</em></h2>
            <p>NeoStay helps neonatal teams anticipate the course of care for very low birth
            weight infants — how long they are likely to stay and how that stay is likely to
            end — and turns that picture into safe, acuity-based nurse staffing for the whole unit.</p>
            <ul class="landing-points">
              ${POINTS.map((point) => `<li>${icon("check", 13)}<span>${point}</span></li>`).join("")}
            </ul>
          </div>
          <div class="card landing-panel" id="neoPanel">${panel}</div>
        </section>

        <section class="panel" aria-labelledby="landingTools">
          <div class="panel-head">
            <h3 id="landingTools">What you can do in NeoStay</h3>
            <p>Six connected tools, from one infant's forecast to the whole unit's staffing plan.</p>
          </div>
          <div class="feature-grid">
            ${FEATURES.map(([name, tone, title, text]) => `
              <div class="card feature">
                <div class="feature-ic ${tone}">${icon(name, 26)}</div>
                <h4>${title}</h4>
                <p>${text}</p>
              </div>`).join("")}
          </div>
        </section>

        <section class="panel" aria-labelledby="landingSteps">
          <div class="panel-head">
            <h3 id="landingSteps">From admission to a staffing plan</h3>
            <p>Four steps, every figure traceable to the underlying outcome statistics.</p>
          </div>
          <div class="flow">
            ${STEPS.map(([title, text]) => `<div class="card flow-step"><h5>${title}</h5><p>${text}</p></div>`).join("")}
          </div>
        </section>

        <section class="panel" aria-labelledby="landingPrinciples">
          <div class="panel-head">
            <h3 id="landingPrinciples">Responsible by design</h3>
            <p>Built for neonatal teams, with its limits stated plainly.</p>
          </div>
          <div class="about-grid">
            ${PRINCIPLES.map(([name, title, text]) => `
              <div class="card about-card">
                <div class="about-ic">${icon(name, 22)}</div>
                <h4>${title}</h4>
                <p>${text}</p>
              </div>`).join("")}
          </div>
        </section>
      </main>
      <footer class="footer">
        <div class="footer-inner">
          <div class="footer-brand">
            <div class="brand-mark">${icon("logo", 20)}</div>
            <div><b>NeoStay</b><span>Neonatal outcome &amp; staffing intelligence</span></div>
          </div>
          <div class="footer-links"><a href="#neoPanel">Sign in</a></div>
        </div>
        <div class="footer-note">
          <span>Built on aggregated, de-identified outcome statistics (2016–2026). All calculations run
          in your browser — no data is sent to any server.</span>
          <span class="badge-warn">${icon("shield", 14)} Decision support only — not for clinical use</span>
        </div>
        <div class="footer-credit">
          <span>© 2026 Waseem Altaf, MD — Neonatologist. All rights reserved.</span>
          <span>Technical Lead, Lead Developer and Applied AI/Data Science Lead — Abdul Razak, PhD</span>
        </div>
      </footer>`;
    document.body.appendChild(wrap);
    return wrap;
  }

  function removeScreen() {
    const existing = document.getElementById("neoGateScreen");
    if (existing) existing.remove();
  }

  function panelHead(iconName, label, title, text) {
    return `
      <div class="landing-panel-head">
        <span class="section-label">${icon(iconName, 14)} ${label}</span>
        <h3>${title}</h3>
        <p data-message>${text}</p>
      </div>`;
  }

  function showProblem(message) {
    const wrap = landing(`
      ${panelHead("pulse", "Service status", "NeoStay is unavailable", "")}
      <button type="button" class="btn-primary neo-login-submit"><span>Try again</span></button>`);
    wrap.querySelector("[data-message]").textContent = message;
    wrap.querySelector(".neo-login-submit").addEventListener("click", () => location.reload());
  }

  function showClosed() {
    landing(`
      ${panelHead("lock", "Access", "Access is not open yet",
        "This copy of NeoStay is for registered users only, and sign-in has not been set up for it yet.")}
      <p class="neo-login-help">If you should have access, contact your NeoStay administrator.</p>`);
  }

  function showLogin(notice) {
    const note =
      MODE === "sealed"
        ? "The data is decrypted on this device. Your password never leaves the browser."
        : "Your password is checked by this NeoStay server and is never stored in the browser.";
    const wrap = landing(`
      ${panelHead("lock", "Secure sign-in", "Sign in to NeoStay",
        "Use the email address and password your NeoStay administrator gave you.")}
      <form class="neo-login-form" novalidate>
        <div class="field">
          <label for="neoEmail">Email</label>
          <input id="neoEmail" type="email" name="email" autocomplete="username" inputmode="email" required />
        </div>
        <div class="field">
          <label for="neoPassword">Password</label>
          <div class="neo-password">
            <input id="neoPassword" type="password" name="password" autocomplete="current-password" required />
            <button type="button" class="neo-reveal" aria-controls="neoPassword" aria-pressed="false">Show</button>
          </div>
        </div>
        <p class="neo-login-error" role="alert" hidden></p>
        <button type="submit" class="btn-primary neo-login-submit"><span>Sign in</span></button>
      </form>
      <p class="neo-login-note">${icon("shield", 15)}<span data-note></span></p>
      <p class="neo-login-help">Need access, or forgotten your password? Contact your NeoStay administrator.</p>`);

    const form = wrap.querySelector("form");
    const email = wrap.querySelector("#neoEmail");
    const password = wrap.querySelector("#neoPassword");
    const reveal = wrap.querySelector(".neo-reveal");
    const error = wrap.querySelector(".neo-login-error");
    const submit = wrap.querySelector(".neo-login-submit");
    const label = submit.querySelector("span");
    wrap.querySelector("[data-note]").textContent = note;

    const fail = (message) => {
      error.textContent = message;
      error.hidden = false;
    };
    if (notice) fail(notice);

    reveal.addEventListener("click", () => {
      const show = password.type === "password";
      password.type = show ? "text" : "password";
      reveal.textContent = show ? "Hide" : "Show";
      reveal.setAttribute("aria-pressed", String(show));
      password.focus();
    });

    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      error.hidden = true;
      if (!email.value.trim() || !password.value) {
        fail("Enter your email address and password.");
        return;
      }
      submit.disabled = true;
      label.textContent = MODE === "sealed" ? "Unlocking NeoStay…" : "Signing in…";
      try {
        const session = await source.login(email.value, password.value);
        password.value = "";
        await openApp(session);
      } catch (failure) {
        fail(failure.message || "Sign-in failed. Try again.");
        password.select();
      } finally {
        submit.disabled = false;
        label.textContent = "Sign in";
      }
    });

    // On a large screen the form sits beside the introduction, so start there.
    // On a phone, let the reader see the introduction first.
    if (window.matchMedia("(min-width: 901px)").matches) email.focus({ preventScroll: true });
  }

  async function signOut() {
    await source.logout();
    forget();
    location.reload();
  }

  async function openApp(session) {
    try {
      await source.loadData();
    } catch (error) {
      if (MODE === "sealed" && error.kind === "load") {
        showProblem(error.message);
        return;
      }
      await source.logout();
      showLogin("Your session has ended. Please sign in again.");
      return;
    }
    window.NeoAccess = {
      mode: session.mode,
      email: session.email || null,
      name: session.name || null,
      canSignOut: session.mode === "password" || session.mode === "sealed",
      signOut,
    };
    removeScreen();
    document.title = gate.getAttribute("data-title") || document.title;
    document.body.classList.add("neo-unlocked");
    window.scrollTo(0, 0);
    try {
      for (const src of APP_SCRIPTS) await loadScript(src);
    } catch {
      showProblem("NeoStay could not finish loading. Reload the page to try again.");
    }
  }

  async function start() {
    if (MODE === "closed") {
      showClosed();
      return;
    }
    let session;
    try {
      session = await source.session();
    } catch (error) {
      showProblem(error.message);
      return;
    }
    if (session.authenticated) await openApp(session);
    else showLogin(session.notice || "");
  }

  gate.setAttribute("data-title", document.title);
  window.neoReady(start);
})();
