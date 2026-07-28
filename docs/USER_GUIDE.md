# NeoStay User Guide

*A plain-language walkthrough for clinicians, students and curious readers.*

**Open the app:** https://abdulrazakucc.github.io/patient-nurse-schedule/
It works in any modern browser, on a phone or a laptop. Nothing is installed,
and nothing you type is sent anywhere — all calculations happen on your device.

---

## 1. The story in one picture

Very small babies (born under ~1,500 g) need weeks or months of hospital care.
How much care depends mostly on **two numbers known at birth**:

```mermaid
flowchart LR
    W["⚖️ Birth weight<br/>(grams)"] --> O["🏥 Outcome"]
    G["📅 Gestational age<br/>(weeks of pregnancy)"] --> O
    C["🩺 How sick on arrival<br/>+ breathing support"] --> N["👩‍⚕️ Nursing needed"]
    O --> N
    O --- L["📏 Length of stay<br/>📈 Survival chance<br/>🏠 Chance of going home"]
```

NeoStay looks up ten years of real outcomes for babies with the *same* weight
and age, and shows you what happened to them.

---

## 2. Page-by-page walkthrough

### 🏠 Home
The landing page. Headline numbers (how many infants are behind the data,
typical stay, overall survival) and a live mini-chart. Use the cards or the
top navigation to reach the tools.

### 🔮 Predict — *"What should we expect for this baby?"*

**Try this worked example:**

1. Set **Birth weight** to `720 g` (use the slider or type it).
2. Set **Gestational age** to `25 weeks`.
3. Choose condition `Serious` and support `CPAP`.
4. Press **Generate forecast**.

You will see:

| Result | Example value | How to read it |
|--------|---------------|----------------|
| Expected length of stay | ~103 days | Half of similar babies stayed between ~85 and ~125 days |
| Survival probability | ~86% | Based on 64 similar infants (high confidence) |
| Disposition rings | 69% home · 17% transfer · 14% died | How similar admissions ended |
| Nurse staffing | ~18.8 NHPPD, ~1,933 nurse-hours | The nursing effort this one baby will need over the whole stay |

The **confidence badge** tells you how many real babies stand behind the
numbers — more babies, more trust.

### 🗓️ Scheduling — *"How many nurses does the unit need tonight?"*

1. Press **Load sample unit (8 infants)** to see it work instantly, or add
   babies one at a time with the form.
2. Each baby is classified by acuity:
   - 🔴 **Intensive** — one nurse cares for one baby (1:1)
   - 🟡 **Intermediate** — one nurse for two babies (1:2)
   - 🟢 **Convalescent** — one nurse for three babies (1:3)
3. The cards at the top show **nurses needed per shift** (bedside + one charge
   nurse) and total daily nurse-shifts.

Remove any row with ✕ and the numbers update immediately.

### ⏱️ Timeline — *"How does care change hour by hour?"*

Follows a simulated (but statistically realistic) year of unit activity:

- **Single infant journey** — pick a baby and watch nursing need fall as it
  moves from intensive → intermediate → convalescent care.
- **Busiest week** — nurses on duty vs. demand vs. babies present, hourly.
- **Around the clock** — average demand by hour of day (spoiler: it never stops).

### 📊 Analytics — *"What does a decade of outcomes look like?"*

Three interactive charts. The consistent message:

> Every extra 100 g of weight and every extra week of pregnancy shortens the
> stay and improves the odds of going home.

Hover or tap any bar for exact numbers.

### ℹ️ About
The methodology in six cards, plus the "anatomy of a forecast" — read this
before quoting numbers in a discussion.

---

## 3. How the maths works (no formulas, promise)

```mermaid
flowchart TD
    A["The data: for each weight band and each week of age,<br/>we know N babies, their median stay, and the middle-50% range"]
    A --> B["Your baby rarely sits exactly on a band edge,<br/>so NeoStay slides smoothly between neighbouring bands"]
    B --> C["The weight-based answer and the age-based answer<br/>are averaged into one forecast"]
    C --> D["Survival and disposition come straight from counting<br/>what actually happened to the similar babies"]
    D --> E["Nursing need = published nurse-to-patient ratios<br/>applied to the three phases of the stay"]
```

Two important honesty rules:

1. **Nothing is invented.** If only 4 similar babies exist, NeoStay says so
   ("very low confidence") rather than pretending to know.
2. **Averages are not destinies.** A forecast describes *groups* of similar
   babies; any individual baby can do better or worse.

---

## 4. Frequently asked questions

**Is my input stored or transmitted?**
No. The site is static files; the calculation runs in your browser's memory and
vanishes when you close the tab.

**Can I use this for real clinical decisions?**
No — it is a decision-support prototype for education and research discussion.
It has not been validated as a medical device.

**Why do tiny babies sometimes show *shorter* stays?**
Sadly, because in the smallest weight bands more babies die early in the
admission. The disposition rings make this visible rather than hiding it.

**Where does the data come from?**
Aggregated center outcome tables for 2016–2026 (counts, medians, quartiles per
weight band and per gestational week) in [`losdata/`](../losdata/). No
patient-level records exist anywhere in this project.

**It says "moderate confidence" — should I trust it?**
The badge maps directly to sample size: high ≥ 50 similar babies,
moderate 20–49, low 5–19. Treat low-confidence numbers as rough sketches.

---

## 5. Sharing with colleagues

Send the link — that's it:

> **https://abdulrazakucc.github.io/patient-nurse-schedule/**

On a phone, the menu is behind the ☰ button, and every chart responds to touch.
Feedback is welcome via GitHub issues on the repository.
