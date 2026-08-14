# Phase 2 — hardware in the loop

**Status: Phase 1 is complete. Phase 2 has not started, and starting it is
gated.** Nothing gets physically connected until the planning session has
happened.

This document is the **input** to that session: what is missing, what has to be
decided, the risks Phase 1 could not reach, and a proposed set of steps. The
session's **output** goes in `09-phase2-plan.md`, which does not exist yet.

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

## 4. What loopback could not test — U1 to U12

**This list is the reason Phase 2 exists.** Each item is a place where a
loopback pass does **not** imply the real system works. The P-steps below are
ordered to close them.

| # | Item | Why loopback cannot reach it | Risk if wrong |
|---|---|---|---|
| U1 | Absolute 80 MHz drive amplitude at the AOM | Round trip is attenuated twice; no calibrated reference | Under- or over-driving the AOM |
| U2 | Amplifier chain linearity and saturation | Not in the loop | Intermodulation generated by the amplifiers, not the DUT — a false signal indistinguishable from the real one |
| U3 | DUT mixing behaviour | Emulated, by construction | The entire measurement premise |
| U4 | Photodetector bandwidth at 1 MHz | Not connected | Response rolled off or absent |
| U5 | Photodetector output level and input range choice | Unknown until measured | Clipping, or burying the signal in ADC quantisation |
| U6 | Real noise environment | Loopback is quiet | SNR far worse than predicted |
| U7 | Santec trigger output: level, polarity, width, and whether it fires once per sweep or per step (Q18) | Emulated | Capture not triggered, or a pulse train appears where one edge was expected |
| U8 | Actual sweep repeatability of the laser | Not in the loop | Wavelength calibration drift |
| U9 | Ground loops and pickup with everything connected | Single-box loopback | 80 MHz leakage into the detector path |
| U10 | The Santec serial link — command set, timing, and whether its reported wavelength is trustworthy | Laser not connected; no driver written yet | **The wavelength axis is now entirely dependent on this.** A wrong or mis-aligned report mislabels every point, and nothing in the trace would look wrong |
| U11 | Clock relationship between the laser and the Red Pitaya (Q19) | Two instruments, one not present | Wavelength assignment drifts across the sweep even with the origin correctly aligned. **Mitigated:** the time-stepped trigger train measures this directly per sweep — see Q19 |
| U12 | That both sides agree on which edge is "the first trigger" (Q21) | Needs the real laser and a real sweep | **Every wavelength offset by one time step, with a trace that looks perfectly normal.** The most dangerous item on this list, because it is silent |

**Note where the risk moved.** Taking the wavelength axis from the laser removes a hard problem (recovering thousands of edge intervals without losing one) and replaces it with a different one: trusting a second instrument's report and aligning two clocks. That is a good trade — the laser knows its own wavelength far better than we can infer it — but it is a trade, not a free win, and U10 and U11 are where it now lives. Both are invisible in loopback.

U2 deserves particular attention. Amplifier intermodulation would appear at
exactly |f2 − f1| — the same frequency as the real signal — and would look
entirely legitimate. Worth designing a control measurement for it: for example,
driving one tone only and confirming nothing appears at the difference
frequency. That is **P5.1** below, and it must run before P5.2.

**U11 and U12 already have mitigations built and tested** — `wavelength.py`
measures the clock ratio from the trigger train on every sweep, and
`check_alignment` catches a late arm by comparing the pulse count against the
laser's table. Both are free and should be wired into the driver from the start,
not added after a confusing result.

---

---

## 5. Proposed steps — P1 to P6

**This is a PROPOSAL, not a plan.** I do not know the damage thresholds, so the
ordering is reasoned from "if this goes wrong, what breaks" rather than from the
equipment's actual limits. Correct it in the session; the agreed version goes in
`09-phase2-plan.md`.

The principle throughout: **every step should be one where, if it fails, the
thing that breaks is cheap.** Optics come last, and the laser goes into the beam
path only after the electrical chain is understood.

---

### P1 — Santec serial link *(nothing connected to the Red Pitaya)*

The largest piece of untested software, and it can be fully validated with no RF,
no optics, and the Red Pitaya switched off.

| Step | What it establishes |
|---|---|
| P1.1 | Open the port and identify the laser. Confirm the 770 and 775 answer the same commands, or record how they differ |
| P1.2 | Run a sweep and read back a wavelength table |
| P1.3 | Confirm the table's shape: units, row count, and that time really is relative to the first trigger |
| P1.4 | Confirm whether the table streams during the sweep or is dumped after it |
| P1.5 | Run the same sweep twice and compare the tables — sweep repeatability (**U8**) |

**Needs:** the serial cable/adapter and the laser powered. **The manuals are read
and the command set is recorded** in `04-hardware-reference.md` — Q22 answered
2026-08-14 — so P1 is unblocked.

**Settle Q24 here.** Set `:TRIGger:OUTPut:SETTing` and read it back: the two
manuals document it with inverted encodings, and the wrong value still produces a
trigger train, just periodic in the wrong variable. Also decide `:TRIGger:OUTPut`
deliberately — 3 (Step) gives the train the index pairing needs; 2 (Start) gives
one pulse and no way to index the log — and record which the laser was actually
in rather than inheriting it.
**Pass:** a wavelength table read reliably, with its format confirmed rather than
assumed.
**Closes:** Q22, U8, most of U10.

---

### P2 — Laser trigger into IN2 *(still no RF, no optics)*

| Step | What it establishes |
|---|---|
| P2.1 | Measure the trigger electrically: amplitude, polarity, rise time, pulse width (**U7**) |
| P2.2 | Confirm it fires the acquisition, and find the right `ACQ:TRig:LEV` |
| P2.3 | Confirm the recorded pulse count matches the table's row count — the off-by-one-trigger guard (**U12**) |
| P2.4 | Measure the laser/board clock ratio across a full sweep (**U11**) |
| P2.5 | **Confirm the decimation choice against the REAL trigger.** Loopback showed zero lost edges at decimation 8, but with a 20 ns synthetic edge. If the real edges are much faster, this is where that shows |

**Needs:** a BNC from the laser's trigger out to IN2, the laser able to sweep,
and P1 done so there is a table to compare against.
**Pass:** the capture triggers reliably, pulse count matches the table, and the
clock ratio is stable.
**Closes:** U7, U11, U12. Confirms or overturns the decimation choice.

**Note:** the code for P2.3 and P2.4 is already written and tested —
`wavelength.check_alignment` and `analyse_trigger_train`. This step is where they
first meet a real instrument.

---

### P3 — Drive chain, AOMs disconnected *(no optics)*

Everything electrical, into a load or a scope, before anything optical exists.

| Step | What it establishes |
|---|---|
| P3.1 | Red Pitaya output level at the amplifier input, with attenuators if needed — confirm it is inside the amplifier's safe input |
| P3.2 | Amplifier output level — confirm it is inside the AOMs' rating **before** they are connected |
| P3.3 | Absolute 80 MHz drive amplitude at what will be the AOM input (**U1**) |
| P3.4 | Spectrum of each amplifier output on its own — catches gross nonlinearity early |
| P3.5 | Both channels running: check for crosstalk between them, which is the mechanism that could produce a false difference-frequency signal |

**Needs:** **Q12** (safe input, gain, AOM rating), attenuators if required, a 50 Ω
load, and a way to measure RF at 80 MHz — a scope or power meter. **This is the
first step that can damage something, and the first that needs you present.**
**Pass:** levels confirmed inside every rating, with margin, and no gross
nonlinearity.
**Closes:** U1, part of U2.

---

### P4 — Optics connected, laser at low power

| Step | What it establishes |
|---|---|
| P4.1 | Photodetector output level and DC offset, laser on, no RF — sets the input range and coupling (**Q11, U5**) |
| P4.2 | Photodetector response near 1 MHz (**U4**). Modulate one AOM and sweep the modulation frequency. **If it rolls off here, the measurement premise needs revisiting** |
| P4.3 | Confirm nothing clips across the full wavelength sweep |
| P4.4 | **Noise floor with everything connected and no drive (U6)** — the real SNR number, against loopback's 3.57 µV |

**Needs:** optics aligned, photodetector damage threshold, agreement on a safe
starting laser power.
**Pass:** detector output sits comfortably inside a range, is flat at ~1 MHz, and
the real noise floor is known.
**Closes:** Q11, U4, U5, U6.

**P4.4 is the step that decides whether the project works.** Loopback says a
signal needs ≥36 µV to be clearly visible. That figure was measured in a quiet
box with 30 cm of cable, and it can only get worse from here. This is where you
find out by how much.

---

### P5 — Full system, first real measurement

| Step | What it establishes |
|---|---|
| P5.1 | **The U2 control measurement: drive ONE tone only and look at the difference frequency. Nothing should be there.** If something is, it is the amplifiers or crosstalk, not the DUT |
| P5.2 | Both tones. Is there an intermodulation response at all (**U3** — the entire premise) |
| P5.3 | A full 1 s swept trace, mapped to wavelength end to end |
| P5.4 | Ground loops and 80 MHz leakage into the detector path (**U9**) |

**Needs:** everything above passed, and agreement on what I may run unattended
from here.
**Pass:** the control measurement is clean, and a real response appears above the
P4.4 noise floor.
**Closes:** U2, U3, U9.

**P5.1 before P5.2, always.** An amplifier-generated signal appears at exactly
the frequency we are looking for and looks entirely legitimate. Running P5.2
first and finding a signal proves nothing.

---

### P6 — Robustness and delivery

| Step | What it establishes |
|---|---|
| P6.1 | Repeat the full sweep 20 times — real sweep-to-sweep repeatability, against loopback's 0.003% |
| P6.2 | Output file format, once decided (**Q15**) |
| P6.3 | Averaging across sweeps, if wanted (**Q13**) |
| P6.4 | Failure behaviour with the real system: laser not sweeping, trigger absent, serial link dropped |

**Needs:** **Q13**, **Q15**, and **Q17** — the success criteria that say when this
is finished.

---

### What this ordering deliberately avoids

- **No optics until P4**, so every electrical unknown is settled while the only
  thing at risk is a cable.
- **The AOMs are not connected until their drive level has been measured**, not
  calculated.
- **P5.1 comes before P5.2**, so a false positive cannot be mistaken for success.
- **P2 validates the wavelength path before any RF exists**, so if the trigger or
  the serial link misbehaves it is found in the cheapest possible configuration.

---

## 6. The session's minimum agenda

Do not begin connecting hardware without this. At minimum the session must
settle:

- Safe drive levels for the amplifier chain and AOMs, from Kevin
- Photodetector damage thresholds
- An order of connection that fails safe — P1 to P6 below are a proposal
- A control measurement for U2
- Agreement on what the agent may command unattended versus what needs a human
  present

**Write the outcome into a new `docs/09-phase2-plan.md`.** This document is the
input to that session; that one is its output.

## 7. What I can do without any of the above

None of this is blocked, and none of it touches hardware:

- **The unbiased amplitude estimator.** `01-overview.md` notes that `R =
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

## 8. What is deliberately NOT in scope here

- **H6.1, the 512 MB memory move.** Rejected on its merits, and the reason it was
  wanted has since evaporated. Do not revive it without a new argument. Note
  though that a 1 s two-channel capture already fills **98.9%** of the current
  region — lengthening the sweep or adding a channel brings it straight back.
- **H5.2 / H5.3.** Superseded; Deep Memory Generation does not exist on this OS.
- **Phase 3 (a GUI).** Deferred pending Q14.
