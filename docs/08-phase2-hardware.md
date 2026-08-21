# Phase 2 — hardware in the loop

**Status: Phase 1 is complete. Phase 2 has not started, and starting it is
gated.** Nothing gets physically connected until the planning session has
happened.

This document is the **input** to that session: what is missing, what has to be
decided, the risks Phase 1 could not reach, and a proposed set of steps. The
session's **output** goes in `09-phase2-plan.md`, which does not exist yet.

---

## The short version

**ALL THREE original blockers are down, as of 2026-08-14.**

| | What | State |
|---|---|---|
| ~~1~~ | Santec TSL-770/775 command set (Q22) | **ANSWERED** from both manuals — `04-hardware-reference.md` |
| ~~2~~ | Photodetector level and impedance (Q11) | **ANSWERED** — PDA05CF2. **U4 closed too**: 150 MHz bandwidth, no rolloff at 991.821 kHz |
| ~~3~~ | Safe drive levels (Q12) | **ANSWERED** — ZHL-1-2W+ and 1550AOM-1 datasheets. **No attenuator needed; Kevin's CW tuning is correct** |

**What is left before hardware goes in** is the planning session itself, plus:

- an **optical damage threshold** for the detector (the manual gives saturation
  but no damage figure),
- confirmation of **whether there is a second ZHL-1-2W+** — the design needs two,
- the **unattended-operation boundary**, deferred at Kevin's request.

**Four things the answers changed, beyond unblocking:**

- **The noise budget got worse.** The detector, not the ADC, will dominate:
  ~11 µV against the board's 3.57 µV, so **SNR 10 needs ~120 µV rather than
  36 µV**. See `05-results.md`.
- **The trigger worry got better.** The real trigger is 3.3 V, 25 µs wide, at
  most 20 kHz — 780 samples per pulse at decimation 8. Every anxiety about
  missed edges came from a synthetic 20 ns pattern that looks nothing like it.
- **No attenuator, and the drive level must not be changed.** Three separate
  recommendations (20, 10 and 6 dB) were all withdrawn: the drive is depth-1 AM,
  so the AOM is switched fully on and off rather than held at a bias point, and
  Kevin's CW tuning is within 0.6% of maximising the signal at f1. Reasoning in
  `04-hardware-reference.md`, recorded because the mistake is easy to repeat.
  The measurement behind it also gives **14 dB of board rolloff at 80 MHz**,
  which answers U1, and the amplifier has **14 dB of margin** to its damage
  rating as wired.
- **A new assumption surfaced (Q26).** Neither manual says the laser logs one
  wavelength per trigger pulse, and the index-based mapping depends on it. One
  command and one capture settles it at P1.

---

## 0. THE LIVE BLOCKER — the laser does not answer

**P1 ran on 2026-08-14 and got nothing back.** Serial is present as **COM29**
(USB, via the FTDI VCP driver), the trigger BNC is fitted and the laser light is
available — but the laser replies to nothing.

**Eliminated, do not retry:** cable, driver, COM port, baud rate (6), terminator
(CR/LF/CRLF), flow control (both), and the driver interface — the device
enumerates cleanly over **both VCP and D2XX** (`desc='TSL-775'
serial='2601S967' id=0x2428:0116 flags=0`) and is silent on both. The host side
is done; `scripts/laser_comms_diag.py` reruns it all and explains each outcome.

**What is left, in order:**

1. **Line settings other than 8N1** — data bits, parity and stop bits were never
   swept. 7E1 and 8E1. **The biggest untried gap, and cheap.**
2. **Power-cycle the laser**, to clear a stuck REMOTE state (manual p54).
3. **Santec's own software**, if supplied. Connects → the laser is listening and
   our settings are wrong. Does not → the fault is not ours. **Highest
   information per minute of anything here.**
4. **LAN**, which sidesteps all of it. `SantecTSL.over_lan()` is written.

**Command set: use SCPI** (Kevin's front panel offers Legacy or SCPI, and no
delimiter option — which killed the leading hypothesis). Not cosmetic: the two
answer the same query in different units, so `wavelength_m()` now checks and
raises rather than returning nanometres as metres.

---

## 1. What I need from you — information

### ~~The laser~~ — ANSWERED 2026-08-14

Both manuals read; the command set, data formats, interfaces and delimiter are
in `04-hardware-reference.md`. **The driver is unblocked.**

**Cabled on USB, enumerating as COM29** (Kevin, 2026-08-14), with the FTDI VCP
driver bound. The command set is set to **SCPI**. **It still does not answer** —
see section 0.

### ~~The photodetector~~ — ANSWERED 2026-08-14

It is a **Thorlabs PDA05CF2**; full entry in `04-hardware-reference.md`.
**U4 is closed** — 150 MHz bandwidth, so no rolloff anywhere near 991.821 kHz.

**Two things still wanted from you**, neither blocking:

- **An optical damage threshold.** The manual gives saturation (~0.96 mW) but no
  damage figure. Needed to set a safe starting laser power at P4.
- **Confirmation that AC coupling is acceptable on your side.** It is measured
  and free on ours (Q25: 17.0 Hz corner, no noise penalty), but it does remove
  any DC information about average optical power. If that matters for
  diagnostics, say so — the laser's own `:READout:DATa:POWer?` log can supply
  it instead.

### ~~The amplifier chain and AOMs~~ — ANSWERED 2026-08-14

**ZHL-1-2W+** (32 dB gain, P1dB +33 dBm, absolute max input +10 dBm) and
**1550AOM-1** (2.5 W nominal RF at 80 MHz, 0.5 W optical handling). Full working
in `04-hardware-reference.md`.

**Decided: NO attenuator.** Kevin's CW tuning maximises the diffracted light,
and because the drive is depth-1 AM (the envelope reaches zero every cycle) that
is also within 0.6% of maximising the signal at f1. Three earlier revisions
recommending 20, 10 and 6 dB were withdrawn — see `04-hardware-reference.md`.
The amplifier has 14 dB of margin to its damage rating as wired.

**One thing still to confirm: is there a second ZHL-1-2W+?** The design drives
two AOMs, one per arm, so it needs two amplifiers. One datasheet proves the
model, not the count. (No attenuators are needed — see above.)

---

## 2. What I need from you — decisions

These need an answer but not a measurement. They can be settled in the session.

| # | Decision | Why it matters now |
|---|---|---|
| Q17 | **Phase 2 success criteria** | Deliberately deferred until Phase 1 results were in. They are in |
| ~~Q13~~ | ~~Averaging across sweeps?~~ **DECIDED: no.** Detuning 1 is swept across ~11–13 discrete settings of detuning 2, so each sweep is its own measurement and phase need not stay coherent between them |
| ~~Q15~~ | ~~Output format?~~ **DECIDED: CSV** for the transfer function, with the raw capture kept as `.npz` alongside. Implemented in `output.py` |
| Q14 | Is a GUI wanted, and what would it show? | Phase 3, but the answer shapes what the driver exposes |
| — | **What may I command unattended, and what needs you present?** | Loopback has been safe to run alone. With a laser and amplifiers connected that is a different question, and I would rather have the boundary explicit than assume it |

---

## 3. What I need physically

- ~~A serial cable for the laser~~ — **done: USB, as COM29.** But see section 0; it is connected and the laser still does not answer.
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
| ~~U7~~ | **Largely ANSWERED from the manual 2026-08-14.** TSL-775 p46: **3.3 V logic, 25 µs pulse width, 20 kHz maximum rate.** Needs **HV (±20 V) on IN2** — 3.3 V will not fit ±1 V — and `ACQ:SOUR<n>:GAIN` is per channel, so IN1 stays on LV. A 25 µs pulse is 780 samples at decimation 8, so **the missed-edge worry does not apply to the real trigger at all.** What remains untested is only that it physically fires the capture, which is P2.2 |
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

**Ready to run: python scripts/p1_laser_check.py <laser-ip>.** Read-only by default; the only write is behind --set-trigger-step.

**Needs:** the laser on the LAN and its IP address (front panel: Other -> Communication -> LAN). **The manuals are read
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
| P2.1 | Confirm the trigger against the manual: **expect 3.3 V, 25 µs wide, ≥50 µs apart** (TSL-775 p46). Use **HV on IN2**. Measure the rise time, which the manual does not give (**U7**) |
| P2.2 | Confirm it fires the acquisition, and find the right `ACQ:TRig:LEV` |
| P2.3 | Compare the recorded pulse count against `:READout:POINts?`. This is both the off-by-one-trigger guard (**U12**) and the test of whether logging is one-per-pulse at all (**Q26**), which no manual states |
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
| P3.1 | Red Pitaya output level at the amplifier input — confirm it is inside the amplifier's safe input. Expect ~−4 dBm against a +10 dBm rating |
| P3.2 | Amplifier output level — confirm it is inside the AOMs' rating **before** they are connected |
| P3.3 | Absolute 80 MHz drive amplitude at what will be the AOM input (**U1**) |
| P3.4 | Spectrum of each amplifier output on its own — catches gross nonlinearity early |
| P3.5 | Both channels running: check for crosstalk between them, which is the mechanism that could produce a false difference-frequency signal |

**Needs:** a 50 Ω load and a way to measure RF at 80 MHz. **No attenuators** — see
`04-hardware-reference.md`; the drive level Kevin already tuned is correct.
**This is the first step that can damage something, and the first that needs you
present.**

**Do not add attenuators and do not retune the drive.** The amplifier sees about
−4 dBm against a +10 dBm rating — 14 dB of margin — and the board's 14 dB rolloff
at 80 MHz means it cannot get closer. See `04-hardware-reference.md`.

**Connect the AOM before applying RF.** The amplifier datasheet warns that an open
load can damage it, and derates the maximum input by 20 dB with no load.

**P3.1 confirms on a 50 Ω load what was measured on a 1 MΩ scope.** The board
showed 800 mVpp open-circuit at 80 MHz; into the amplifier's 50 Ω that halves,
giving −4 dBm. Worth confirming directly, since the whole drive-level argument
rests on it and an RF voltage without its impedance is not a measurement.
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

**Needs:** optics aligned, and agreement on a safe starting laser power. The
detector is a **PDA05CF2** and its datasheet figures are in
`04-hardware-reference.md`; **U4 is already closed** — 150 MHz bandwidth, so no
rolloff anywhere near 991.821 kHz. Saturation is around **0.96 mW** optical; an
explicit damage threshold is not in the manual, so confirm before exceeding it.

**Expect ~11 µV of detector noise against the board's 3.57 µV**, so P4.4 should
land near **11–12 µV** and SNR 10 should need **~120 µV**. If it comes back near
3.6 µV, suspect the detector is not actually in the path; above ~25 µV, something
is wrong beyond the datasheet. **AC-couple IN1** — the 0–10 V pedestal will not
fit the ±1 V range otherwise, and the ±20 V range would put the ADC back in
charge at 45 µV. **Q25 measured this on 2026-08-14 and it is free**: the corner is
17.0 Hz, so attenuation at 991.821 kHz is 10⁻⁹ dB, and the noise floor is
unchanged AC coupled.
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

- **Index the wavelengths, do not count them.** With the trigger periodic in
  TIME, the laser's i-th logged wavelength sits at `first_edge + i × step`, so
  **only the first edge is ever located** and a missed edge in the middle changes
  nothing. Taking `step` from a line fit through the recorded train, rather than
  from the laser's nominal setting, also measures the two clocks against each
  other — closing U11 by measurement instead of trust.
  `wavelength.logged_point_times()` does this and is tested against both failure
  modes. **Keep Step mode rather than Start:** Start emits a single pulse, and
  then there is no train to fit a step from and no count to check against.
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
