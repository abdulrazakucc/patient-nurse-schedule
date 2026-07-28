"use strict";
/* Predictor page: runs the client-side engine (engine.js) — no server round-trip. */
document.addEventListener("DOMContentLoaded", () => {
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
    placeholder: document.getElementById("resultsPlaceholder"),
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

  const meta = NeoEngine.meta();
  meta.centers.forEach((c) => {
    const o = document.createElement("option");
    o.value = c;
    o.textContent = c;
    els.center.appendChild(o);
  });
  els.center.value = meta.center;

  els.form.addEventListener("submit", (e) => {
    e.preventDefault();
    const weight = Number(els.weightNum.value);
    const ga = Number(els.gaNum.value);
    if (!weight || !ga) {
      toast("Please provide both birth weight and gestational age.");
      return;
    }
    try {
      const r = NeoEngine.predict(weight, ga);
      r.staffing = NeoEngine.estimateStaffing(
        weight,
        ga,
        r.length_of_stay.blended.median || 0,
        document.getElementById("condition").value,
        document.getElementById("respSupport").value
      );
      render(r);
    } catch (err) {
      toast("Prediction failed: " + err.message);
    }
  });

  function render(r) {
    els.placeholder.hidden = true;
    els.results.hidden = false;

    const los = r.length_of_stay.blended;
    countUp(document.getElementById("losMedian"), los.median, { decimals: 0 });
    document.getElementById("losIqr").textContent = `${fmt(los.q1)} – ${fmt(los.q3)} days`;
    countUp(document.getElementById("survival"), r.survival_probability, { decimals: 1 });
    document.getElementById("sampleN").textContent = r.sample_size ?? "–";

    const conf = document.getElementById("confidence");
    conf.textContent = r.confidence + " confidence";
    conf.className = "conf-badge conf-" + String(r.confidence).replace(/\s+/g, "-");

    const d = r.disposition;
    const setRing = (ringId, pctId, pct) => {
      const ring = document.getElementById(ringId);
      const label = document.getElementById(pctId);
      const target = pct ?? 0;
      const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      if (reduced) {
        ring.style.setProperty("--pct", target);
        label.textContent = fmt(target, 1);
        return;
      }
      const start = performance.now();
      const stepFn = (now) => {
        const t = Math.min(1, (now - start) / 700);
        const eased = 1 - Math.pow(1 - t, 3);
        const v = target * eased;
        ring.style.setProperty("--pct", v);
        label.textContent = fmt(v, 1);
        if (t < 1) requestAnimationFrame(stepFn);
      };
      requestAnimationFrame(stepFn);
    };
    setRing("ringHome", "pHome", d.home);
    setRing("ringTransfer", "pTransfer", d.transfer);
    setRing("ringDied", "pDied", d.died);

    const dispLosText = (key, elId) => {
      const est = r.disposition_los[key];
      const el = document.getElementById(elId);
      el.textContent = est && est.median !== null ? `Typical stay ~${fmt(est.median)} days` : "";
    };
    dispLosText("home", "losHome");
    dispLosText("transfer", "losTransfer");
    dispLosText("died", "losDied");

    const s = r.staffing;
    countUp(document.getElementById("nhppd"), s.avg_nhppd, { decimals: 1 });
    countUp(document.getElementById("peakNurse"), s.peak_nurses_per_infant, { decimals: 2 });
    countUp(document.getElementById("nurseHours"), s.total_nurse_hours, { decimals: 0 });
    countUp(document.getElementById("shifts"), s.total_12h_shifts, { decimals: 0 });
    document.getElementById("staffNote").textContent = s.note;

    const list = document.getElementById("phaseList");
    list.innerHTML = "";
    const maxDays = Math.max(...s.phases.map((p) => p.days), 1);
    s.phases.forEach((p) => {
      const row = document.createElement("div");
      row.className = "phase-row";
      row.innerHTML = `<span>${p.name}</span><span>${fmt(p.days, 1)} d · ${fmt(p.nurse_hours)} h</span>
        <div class="phase-track"><div class="phase-fill" style="width:0%"></div></div>`;
      list.appendChild(row);
      requestAnimationFrame(() =>
        requestAnimationFrame(() => {
          row.querySelector(".phase-fill").style.width = `${(p.days / maxDays) * 100}%`;
        })
      );
    });

    els.results.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }
});
