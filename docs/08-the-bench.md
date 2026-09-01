# The bench — what is connected, and how a measurement is made

**Rewritten 2026-09-01.** This document used to be "Phase 2 — hardware in the
loop": a proposed order of connection (P1–P6) and a list of risks loopback
could not reach (U1–U12), written when nothing was plugged in. That framing did
its job and is retired — see the appendix. What follows describes the bench as
it actually is and how it is actually driven.

For what to do next, `09-whats-next.md`. For every measured number,
`05-results.md`.

---

## 1. What is on the bench

```
  TSL-775 --> AOM (1550AOM-1) --> 90/10 --> 50/50 --> PDA05CF2 --> IN1
     |              ^
     |              | 80 MHz AM at f1
     |        ZHL-1-2W+ <-- OUT1
     |
     +-- trigger BNC ------------------------------------------> IN2
```

| | State |
|---|---|
| Red Pitaya SIGNALlab 250-12 | working; SCPI on port 5000, deep capture via `rp_fastread.py` in `/dev/shm` |
| TSL-775 sweeping laser | working **over LAN only**. USB is a hardware fault inside the instrument |
| ZHL-1-2W+ #1 | connected, driven by OUT1 |
| 1550AOM-1 #1 | connected |
| PDA05CF2 (InGaAs, 800–1700 nm) | connected to IN1 |
| ZHL-1-2W+ #2, AOM #2 | exist, **not wired**. Needed for SFG |
| PDA100A2 (Si, 320–1100 nm) | **on the bench, not installed.** For the SHG product near 775 nm |
| TSL-770 stepping laser | **never contacted.** Parked at Kevin's request |
| Nonlinear crystal | **not yet acquired** |

---

## 2. Making a measurement

Everything below is `scripts/bench.py`. Panels are independent on purpose: each
one does one thing, and a sweep is those things in order.

1. **Board** — Connect, then Configure. This sets the front end.
2. **Drive (OUT1)** — set carrier 80 MHz and the modulation, then `OUT1 ON`. A
   dialog names the frequencies and amplitude before anything is enabled.
3. **Sweep** — set start, stop, speed and trigger step, then **Configure**.
   **Then wait.** See the traps below.
4. **Acquire** — set the decimation and duration, then arm with trigger
   `CH2_PE`. The bench tells you it is armed and waiting.
5. **Sweep > Start.** The capture fires on the laser's first trigger pulse.
6. **Demodulate** — press the **f1** button rather than typing a frequency,
   then Demodulate capture.
7. **Sweep > Read log**, then **Map**. The wavelength axis is built from the
   measured trigger edges.
8. **Export** — CSV plus the raw `.npz`.

The `Sequences` panel runs exactly these operations in order, through the same
functions the buttons call. There is no second implementation.

### Reading the result

- **`trace`** — amplitude against wavelength. The deliverable.
- **`lock-in R`** — magnitude. Cannot go negative, ignores the reference phase.
- **`lock-in phase`** — unwrapped, so a frequency offset reads as a straight
  line with a slope.

---

## 3. The traps, in the order they will bite you

**1. Front-end settings are per channel and both matter.** IN1 is AC-coupled on
LV — the detector is 0–10 V unipolar into Hi-Z, so DC coupling parks the input
on the rail. IN2 is DC on HV — the 3.3 V trigger clips to a flat line on LV,
which reads as "the laser is not triggering". `ops.front_end` sets both.

**2. Wait between Sweep > Configure and Sweep > Start.** The laser has to get
back to its start wavelength on its own. Start it early and it sweeps a shorter
range at exactly the right speed and step, so the trace looks entirely normal —
measured, 80.96 nm of a requested 100. Driving it there by hand with `:WAV` is
**not** a fix: it leaves the instrument in a state where the sweep emits no
trigger train at all (Q32).

**3. One laser connection, held for the whole session.** A connection attempt
is a consumable — two connect-and-close cycles took a port from accepting to
silently dropping SYNs, and only a power cycle recovered it. Never retry a
failed connect; power cycle with the PC quiet (Q33). Do not run two benches.

**4. Use the frequency buttons, never a typed harmonic.** `f1`, `2 x f1`, `f2`,
`f1+f2`, `|f1-f2|` all build f_ref from what the ASG will actually generate.
Typing the round number leaves f_ref tens of hertz out, and a lock-in that is df
from its signal returns a df beat — a clean sine across the trace that looks
like a measurement.

**5. A negative amplitude is the estimator, not the signal.** `amplitude()`
projects onto one phase; it is unbiased where `R` reads +1.25σ on pure noise,
but it assumes the phase is steady. A sign change means the phase rotated past
90°, which no optical amplitude can do. Plot **lock-in R** — flat R under a
swinging amplitude is phase, not physics.

**6. Every laser setting is written and read back.** `configure_sweep` writes
seven and verifies seven. It used to verify one, and a sweep silently reverted
to step mode between the first run and the second — running ~2000× slow with a
nearly flat trigger channel.

**7. `mod_cycles` multiplies the generator's frequency error.** The planner now
takes the fewest cycles the carrier tolerance allows. If you ever override it,
prefer one modulation cycle (Q31).

**8. The fast-read helper lives in `/dev/shm`**, which is RAM, so it disappears
on every board reboot. `RedPitaya.fast_read_available()` says whether it is up.

---

## 4. What is proven

- **The optical chain works.** 289 mV swing on IN1 with the beam on, nanovolts
  with OUT1 disarmed, and a 9 dB laser drop giving a measured 8.67× against a
  predicted 7.94× — 0.38 dB. The signal tracks optical power while the RF drive
  is unchanged, so it is light and not pickup.
- **The trigger and the wavelength axis are trustworthy.** 5001 pulses against
  5001 logged rows, spans agreeing to the microsecond, first edge repeatable to
  6 ns over 20 sweeps, and the laser/board clock ratio measured per sweep at
  −19.06 ppm.
- **The axis uses the measured edges**, because the sweep speed ripples ±11%
  with a 0.41 nm period. That is 13.68 pm — 0.684 of a step — of error removed.

## 5. What is not

- **No crystal**, so no nonlinear signal has ever been looked for.
- **Nothing two-tone has been driven**, so amplifier intermodulation at
  \|f2 − f1\| is untested. It would look exactly like a real signal.
- **The AOM makes its own second harmonic** at −17.5 dB with the same
  wavelength shape, so any SHG measurement on the InGaAs detector must clear
  13.3% before it has said anything (Q30).
- **The stepping laser has never been contacted**, so the output is a 1 × 5000
  sweep, not the 11 × 5000 map.

---

## Appendix — the retired P/U framing

The original Phase 2 document proposed six connection steps (P1–P6) and listed
twelve risks loopback could not reach (U1–U12). It was written on 2026-08-14 to
answer "in what order do we plug things in so that if something breaks, the
thing that breaks is cheap".

That question is answered. The order was followed for the laser link and the
trigger; the drive chain went in with the AOM already connected, so P3 as
written never ran; and the bench GUI replaced the step-by-step scripts as the
working tool. **Ten of the twelve U-risks are closed by measurement** — the
detail is in `05-results.md` and the closures are dated in
`10-open-questions.md`.

**The two that remain are the two the crystal will settle:**

| | | |
|---|---|---|
| **U2** | Amplifier linearity and saturation | Intermodulation from the amplifiers lands at exactly \|f2 − f1\| and is indistinguishable from the real signal. The one-tone control must run first and come back clean |
| **U3** | DUT mixing behaviour | The measurement premise. Untested |

The P-series scripts (`scripts/p1_laser_check.py` … `p6_robustness.py`) still
exist and still hold the safety contract — outputs disarmed on every exit path,
nothing drives an output without a typed confirmation, and P5.2 refuses to run
before a clean P5.1. **That control ordering is still right and still matters**,
whether it runs from a script or from the bench. Everything else about the
framing is history.
