# Phase 2 preparation — what the planning session needs

**Status: Phase 1 is complete. Phase 2 has not started, and starting it is
gated.** Nothing gets physically connected until the planning session has
happened.

This document is the **input** to that session: what is missing, what has to be
decided, and what can be built meanwhile. The session's **output** goes in
`07-phase2-plan.md`, which does not exist yet.

---

## The short version

Three things block Phase 2, and they are independent — none has to wait for the
others:

| | What | Blocks |
|---|---|---|
| **1** | The Santec TSL-770/775 serial command set (Q22) | The laser driver, which is the critical path |
| **2** | Photodetector output level and impedance (Q11) | Choosing the input range; getting it wrong means clipping or burying the signal |
| **3** | Safe drive levels for the amplifiers and AOMs (Q12) | **Connecting anything at all.** A hard safety gate |

Everything else on this page is either a decision that can be made in the
session, or work that can proceed regardless.

---

## 1. What I need from you — information

### The laser (blocks the driver)

- **The TSL-770/775 programming manual**, or the model's command reference. A
  PDF, a link, or the part of it covering wavelength logging is enough.
- **Which interface** the laser is connected by — USB, RS-232, GPIB or Ethernet —
  and the port settings if serial.
- **Whether the wavelength table streams during the sweep, or is read afterwards.**
  This is structural, not a detail: it decides whether the driver runs alongside
  the capture or after it.
- **Do the 770 and 775 differ** in any of the above? If so, both.

**Please do not paraphrase the commands from memory, and I will not guess them.**
On this hardware a misspelled command returns zero bytes exactly like a correct
one, and the wavelength axis is the one subsystem where a silent failure is
completely invisible in the output — a mislabelled sweep looks exactly like a
good one.

### The photodetector (blocks the input-range choice)

- **Typical and maximum output voltage** into a high-impedance input.
- **Output impedance**, and whether it expects a 50 Ω or high-Z load.
- **Bandwidth**, specifically whether it is flat at ~1 MHz. If it rolls off
  there, the whole measurement premise needs revisiting (this is U4).
- **Optical damage threshold**, for setting laser power safely.

The number to judge it against: on the ±1 V range the noise floor is
**σ = 3.57 µV per trace point**, so the response needs **≥36 µV** to be clearly
visible in a single sweep, and below ~4 µV it is not visible at all. The ±20 V
range is 14× worse in absolute terms (σ = 45 µV, needing ≥454 µV).

### The amplifier chain and AOMs (blocks connecting anything)

- **Maximum safe input** to the amplifier, and its gain.
- **Maximum RF power** into the AOMs, and their damage threshold.
- **Whether attenuators are needed** between the Red Pitaya's output and the
  amplifier input — and if so, what value. The board can output up to ±1 V into
  50 Ω, which may already be too much.
- **Amplifier linearity**, if known. This is U2 and it matters more than it
  sounds: amplifier intermodulation appears at exactly the same frequency as the
  real signal and would look completely legitimate.

---

## 2. What I need from you — decisions

These need an answer but not a measurement. They can be settled in the session.

| # | Decision | Why it matters now |
|---|---|---|
| Q17 | **Phase 2 success criteria** | Deliberately deferred until Phase 1 results were in. They are in |
| Q13 | Is averaging across repeated sweeps wanted? | Changes buffer management, and whether phase must stay coherent between sweeps |
| Q15 | Output file format for the traces | Currently `.npz`. Cheap to change now, annoying later |
| Q14 | Is a GUI wanted, and what would it show? | Phase 3, but the answer shapes what the driver exposes |
| — | **What may I command unattended, and what needs you present?** | Loopback has been safe to run alone. With a laser and amplifiers connected that is a different question, and I would rather have the boundary explicit than assume it |

---

## 3. What I need physically

- **A serial cable / adapter** for the laser, matching whatever Q22 says.
- **An order of connection that fails safe** — my draft is below, for you to
  correct.
- **Optional but valuable: a calibrated reference** — either a known source into
  IN1, or a meter on OUT1. This settles Q23, which loopback cannot: a commanded
  0.5 V reads back as 902.8 counts, implying 1816.9 counts/V, but loopback
  measures generator × cable × ADC as a single number and cannot say where the
  0.882 factor lives. **If it sits in the generator rather than the ADC, every
  absolute noise figure is 12.7% too high.** Not urgent, but it is the last
  unresolved doubt about the numbers above.

---

## 4. The risks loopback could not test

Carried from `04-test-plan.md`. These are what the session exists to plan
around — each is somewhere a passing loopback test does **not** imply the real
system works.

| # | Item | Risk if wrong |
|---|---|---|
| U1 | Absolute 80 MHz drive amplitude at the AOM | Under- or over-driving |
| **U2** | **Amplifier chain linearity** | **Intermodulation from the amplifiers, not the DUT — a false signal indistinguishable from the real one** |
| U3 | DUT mixing behaviour | The entire measurement premise |
| U4 | Photodetector bandwidth at ~1 MHz | Response rolled off or absent |
| U5 | Photodetector level vs input range | Clipping, or burying the signal in quantisation |
| U6 | Real noise environment | SNR far worse than the 3.57 µV loopback figure |
| U7 | Laser trigger electrical characteristics | Capture not triggered |
| U8 | Laser sweep repeatability | Wavelength calibration drift |
| U9 | Ground loops and pickup | 80 MHz leakage into the detector path |
| U10 | **The Santec serial link** | **The wavelength axis depends entirely on it, and a wrong report mislabels every point with nothing looking wrong** |
| U11 | Laser/board clock relationship | Wavelength assignment drifts across the sweep |
| U12 | **Both sides agreeing which edge is "the first trigger"** | **Every wavelength offset by one time step, with a trace that looks perfectly normal** |

**U2 deserves a dedicated control measurement**, and it is cheap: drive one tone
only and confirm nothing appears at the difference frequency. If something does,
it is the amplifiers, not the DUT. Worth doing before trusting any real result.

**U11 and U12 already have mitigations built and tested** — `wavelength.py`
measures the clock ratio from the trigger train on every sweep, and
`check_alignment` catches a late arm by comparing the pulse count against the
laser's table. Both are free and should be wired into the driver from the start,
not added after a confusing result.

---

## 5. Draft order of connection — please correct this

Written to fail safe, and offered as a starting point rather than a
recommendation, since I do not know the damage thresholds.

1. **Laser serial only.** No RF, no optics. Confirm the driver reads a
   wavelength table and that the timing lines up. This is the largest piece of
   untested software and it can be validated with nothing connected to the Red
   Pitaya at all.
2. **Laser trigger into IN2**, still no RF. Confirms U7 — that the real trigger
   actually fires the capture, at real levels — while nothing can be damaged.
3. **Drive chain with the AOMs disconnected**, into a load or a scope. Confirms
   U1 and U2 at real levels without touching the optics. The U2 control
   measurement belongs here.
4. **Optics connected, laser at low power.** Confirms U3, U4, U5.
5. **Full system.** Confirms U6, U8, U9.

The principle: every step should be one where, if it goes wrong, the thing that
breaks is cheap.

---

## 6. What I can do without any of the above

None of this is blocked, and none of it touches hardware:

- **The unbiased amplitude estimator.** `01-project-spec.md` notes that `R =
  sqrt(X² + Y²)` is biased upward in noise, and that rotating `X + jY` to a
  common angle and taking the real part is unbiased and quieter. **Still not
  implemented.** It matters most exactly where the measurement is hardest — at
  low SNR, near the 4 µV floor.
- **Output file format** (Q15), once decided.
- **The U2 control measurement**, as a script ready to run.
- **The Santec driver itself**, the moment Q22 is answered — everything that does
  not depend on the command set is already written and tested in
  `wavelength.py`.

---

## What is deliberately NOT in scope here

- **H6.1, the 512 MB memory move.** Rejected on its merits, and the reason it was
  wanted has since evaporated. Do not revive it without a new argument. Note
  though that a 1 s two-channel capture already fills **98.9%** of the current
  region — lengthening the sweep or adding a channel brings it straight back.
- **H5.2 / H5.3.** Superseded; Deep Memory Generation does not exist on this OS.
- **Phase 3 (a GUI).** Deferred pending Q14.
