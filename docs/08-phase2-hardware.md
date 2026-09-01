# Phase 2 — hardware in the loop

**Rewritten 2026-09-01.** The previous version was written on 2026-08-14 as the
*input* to a planning session, when nothing was connected and most of this was
unknown. Almost all of it has since been answered by measurement, and two of
its sections described blockers that are dead. What follows is the current
state, not a proposal.

For what was decided and why, see `09-phase2-plan.md`. For every measured
number, `05-results.md`.

---

## The short version

**The measuring instrument is finished and the optical chain works.** Light is
modulated by an AOM at f1, reaches the detector, is captured on IN1, triggered
by the laser on IN2, demodulated, and mapped onto a wavelength axis built from
the measured trigger edges. This runs end to end from `scripts/bench.py` and
has produced real optical measurements.

What is *not* done is the physics. **There is no crystal yet**, so no
second-harmonic or sum-frequency signal has ever been looked for. The second
beam path — second amplifier, second AOM — is not wired. The stepping laser has
never been contacted, so today's deliverable is a 1 x 5000 sweep rather than the
11 x 5000 map.

---

## 1. What is connected, as of 2026-09-01

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
| Red Pitaya SIGNALlab 250-12 | working; SCPI on port 5000, deep capture via `rp_fastread.py` |
| TSL-775 sweeping laser | working **over LAN only** — USB is a hardware fault inside the instrument |
| TSL-770 stepping laser | **never contacted.** Serial control parked at Kevin's request |
| ZHL-1-2W+ amplifier #1 | connected, driven by OUT1 |
| ZHL-1-2W+ amplifier #2 | exists, **not wired** |
| 1550AOM-1 #1 | connected |
| AOM #2 | **not wired** |
| PDA05CF2 (InGaAs) | connected to IN1, responds to light |
| PDA100A2 (Si) | **on the bench, not installed.** For the SHG product near 775 nm |
| Nonlinear crystal | **not yet acquired** |

**Front-end settings are per channel and both matter.** IN1 is AC-coupled on
LV — the detector is 0–10 V unipolar into Hi-Z, so DC coupling parks the input
on the rail. IN2 is DC on HV — the 3.3 V trigger clips to a flat line on LV,
which reads as "the laser is not triggering". `ops.front_end` sets both.

---

## 2. What loopback could not test — U1 to U12, current status

This list was the reason Phase 2 exists. Ten of twelve are now closed by
measurement.

| # | Item | Status |
|---|---|---|
| U1 | Absolute 80 MHz drive amplitude at the AOM | **CLOSED.** Kevin tuned it by maximising diffracted light with an unmodulated carrier. The board also loses 14 dB at 80 MHz, measured. No attenuator — see Q12, and do not reopen |
| U2 | Amplifier chain linearity and saturation | **OPEN, and the most important one left.** Amplifier intermodulation lands at exactly \|f2 − f1\|. Needs the one-tone control (P5.1) before any two-tone result is believable. Nothing two-tone has been driven yet |
| U3 | DUT mixing behaviour | **OPEN — no crystal.** The entire measurement premise, still untested |
| U4 | Photodetector bandwidth at 1 MHz | **CLOSED.** PDA05CF2 is 150 MHz; 991.821 kHz is deep in the flat region |
| U5 | Detector output level and input range | **CLOSED.** IN1 AC on LV, 289 mV swing with the beam on, no clipping across 40 captures |
| U6 | Real noise environment | **CLOSED.** The real chain measures within 0.38 dB of prediction — 8.67x against 7.94x predicted for the beam/low-power ratio |
| ~~U7~~ | Trigger electrical compatibility | **CLOSED** 2026-08-14 from the manual, confirmed on the bench 2026-08-28. 3.3 V, 25 us pulse, HV on IN2 |
| U8 | Laser sweep repeatability | **CLOSED.** 20/20 sweeps, first edge to 6 ns. The sweep speed ripples ±11% with a 0.41 nm period, which is why the axis uses measured edges — see Q29 |
| U9 | Ground loops and pickup | **CLOSED in this configuration.** The no-drive control reads nanovolts |
| U10 | The Santec link, and whether its wavelength report is trustworthy | **CLOSED.** 5001 log points against 5001 recorded pulses, spans agreeing to the microsecond |
| U11 | Laser/board clock relationship | **CLOSED.** Measured per sweep from the trigger train: −19.06 ppm |
| U12 | Both sides agreeing which edge is "the first trigger" | **CLOSED.** Count and span both match, so the first recorded edge is the laser's first trigger |

**U2 and U3 are what Phase 2 has left**, and both need hardware that is not yet
on the bench.

---

## 3. P1 to P6 — where each step stands

| Step | State |
|---|---|
| **P1** laser link | **DONE** — LAN, one held connection |
| **P2** trigger into IN2 | **DONE** — 5001 pulses, 24.997 us wide, 199.997 us apart, none lost at decimation 8 |
| **P3** drive chain, AOMs disconnected | **SUPERSEDED.** The drive chain went in with the AOM already connected and works. The step as written never ran |
| **P4** optics, low power | **DONE in substance** — the full chain runs from `bench.py`, including a low-power control |
| **P5** full system, first real measurement | **PART DONE.** A real optical sweep exists: amplitude against wavelength, 5000 points, 1500–1600 nm. **P5.1 (one-tone control) and P5.2 (two-tone) have not run** — there is no second tone and no crystal |
| **P6** robustness and delivery | **NOT DONE** |

The P-series scripts (`scripts/p1_laser_check.py` ... `p6_robustness.py`) still
exist and still hold the safety contract, but **`scripts/bench.py` has become
the working tool** and is where the real runs happen. Both go through
`scripts/_bench_ops.py`, so there is no second implementation to drift.

---

## 4. What remains, in the order worth doing it

1. **Get the crystal.** Everything else is instrumentation; this is the
   experiment. Until it exists, U2 and U3 stay open and the deliverable is a
   transmission measurement.
2. **Wire the second amplifier and AOM.** Needed for SFG. The bench already
   drives OUT2 at f2 = 1225 kHz and can demodulate f2, f1+f2 and \|f1−f2\|; see
   `03-frequency-plan.md` for why those four frequencies and not round numbers.
3. **Run P5.1 before P5.2.** An amplifier-generated product sits at exactly the
   frequency P5.2 looks at, so a signal there proves nothing until the one-tone
   control is clean. `p5_first_measurement.py` enforces the ordering.
4. **Install the PDA100A2 for the SHG product.** Silicon is blind at 1550, so
   anything it sees near 775 nm is genuinely upconverted — that is what closes
   Q30. Its bandwidth collapses as gain rises, so the detection frequency and
   the gain setting have to be chosen together; the working is in
   `04-hardware-reference.md`.
5. **Contact the TSL-770.** It supplies the second axis, so half the
   deliverable. The TSL-775's LAN recipe should transfer, but nothing is
   proven. Parked at Kevin's request.
6. **P6 — robustness and delivery.**

Items 1, 2, 4 and 5 are independent of each other.

---

## 5. Still undecided

**Unattended operation.** Nothing runs unattended, and that is the working
assumption until Kevin says otherwise. It costs nothing while he is at the
bench, and it needs a real answer before any long run with the amplifiers live.

**Q17, the Phase 2 success criteria.** Still unset. It decides when to stop,
not how to begin. The numbers to set it against: sigma = 3.57 uV per trace
point at the ADC, with the PDA05CF2's own ~11 uV dominating that, so roughly
120 uV of signal for SNR 10 in a single sweep.

---

## 6. Explicitly not in scope

FPGA work (ADR-0001), phase as a deliverable (Q6 — amplitude only), and sweep
averaging (Q13 — each sweep is its own measurement).
