"use strict";
/*
 * The sign-in gate every page loads first.
 *
 * Pages hold no data. This script finds out whether someone is signed in -- by
 * asking the NeoStay server, or by opening the sealed copy on GitHub Pages --
 * and shows the sign-in screen if nobody is. Only once the data is available
 * does it load the engine and the page's own scripts, listed in data-app, in
 * order. See access-config.js for the two modes.
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

  /* ---------------- screens ---------------- */

  const ICON = {
    logo: '<svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 21s-6.5-4.35-9-8.5C1 9 2.5 5.5 6 5.5c2 0 3.2 1.1 4 2.3.8-1.2 2-2.3 4-2.3 3.5 0 5 3.5 3 7-2.5 4.15-9 8.5-9 8.5z"/></svg>',
    lock: '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="5" y="11" width="14" height="9.5" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/></svg>',
    shield: '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3l7.5 3v5.5c0 4.7-3.2 8-7.5 9.5-4.3-1.5-7.5-4.8-7.5-9.5V6z"/><path d="M9 12l2.2 2.2L15.5 9.9"/></svg>',
  };

  const FOOT = `
    <div class="neo-login-foot">
      <span class="badge-warn">${ICON.shield} Decision support only — not for clinical use</span>
      <span>Project and Clinical Lead — Waseem Altaf, MD, Neonatologist</span>
      <span>Technical Lead, Lead Developer and Applied AI/Data Science Lead — Abdul Razak, PhD</span>
    </div>`;

  function screen(inner) {
    removeScreen();
    const wrap = document.createElement("div");
    wrap.className = "neo-login";
    wrap.id = "neoGateScreen";
    wrap.innerHTML = `
      <div class="aurora"></div>
      <div class="neo-login-card" role="main">
        <div class="neo-login-brand">
          <div class="brand-mark">${ICON.logo}</div>
          <div><strong>NeoStay</strong><span>Infant NICU Outcome &amp; Staffing Intelligence</span></div>
        </div>
        ${inner}
        ${FOOT}
      </div>`;
    document.body.appendChild(wrap);
    return wrap;
  }

  function removeScreen() {
    const existing = document.getElementById("neoGateScreen");
    if (existing) existing.remove();
  }

  function showProblem(message) {
    document.title = "NeoStay is unavailable";
    const wrap = screen(`
      <h1>NeoStay is unavailable</h1>
      <p class="neo-login-lead" data-message></p>
      <button type="button" class="btn-primary neo-login-submit"><span>Try again</span></button>`);
    wrap.querySelector("[data-message]").textContent = message;
    wrap.querySelector("button").addEventListener("click", () => location.reload());
  }

  function showLogin(notice) {
    document.title = "Sign in · NeoStay";
    const note =
      MODE === "sealed"
        ? "The data is decrypted on this device. Your password never leaves the browser."
        : "Your password is checked by this NeoStay server and is never stored in the browser.";
    const wrap = screen(`
      <span class="neo-login-badge">${ICON.lock} Registered users only</span>
      <h1>Sign in</h1>
      <p class="neo-login-lead">Use the email address and password your NeoStay administrator gave you.</p>
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
      <p class="neo-login-note">${ICON.shield}<span data-note></span></p>
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

    email.focus();
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
    try {
      for (const src of APP_SCRIPTS) await loadScript(src);
    } catch {
      showProblem("NeoStay could not finish loading. Reload the page to try again.");
    }
  }

  async function start() {
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
