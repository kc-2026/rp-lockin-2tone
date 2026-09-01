# What's next

**Updated 2026-09-01.** This replaces "Phase 2 plan", which recorded the output
of a planning gate that closed on 2026-08-28. The gate is history; what matters
now is the order of the remaining work.

For the bench as it stands, `08-the-bench.md`. For every number,
`05-results.md`.

---

## Next: SHG

**The instrument is finished; this is the first piece of actual physics.**

### What SHG needs that the bench does not yet have

| | |
|---|---|
| A nonlinear crystal | **not yet acquired.** Everything below is ready for it |
| The PDA100A2 silicon detector | on the bench, not installed |
| A filter blocking 1550, passing ~775 | needed on the Si detector |

### Why silicon, and not the InGaAs detector already fitted

**The AOM makes its own second harmonic.** Measured with no crystal in the
path: demodulating at 2·f1 gives 24 mV against 180 mV at f1 — 13.3%, −17.5 dB,
**and the same wavelength shape**. An AOM diffracts as sin² of its drive and
the drive is depth-1 AM, so the light is already distorted before it reaches
anything. On the InGaAs detector, any SHG measurement has to clear 13.3% before
it has said anything (Q30).

Silicon does not see 1550 nm at all. So **anything the PDA100A2 detects near
775 nm is genuinely upconverted light**, and the confound never arrives.

### Demodulate at f1, not 2·f1

This is the part that is easy to get wrong. The 2·f1 trick existed only to
escape the huge fundamental on the InGaAs channel. On silicon the fundamental
is invisible, so f1 is unambiguous there — and it is the **bigger** signal:
for depth-1 AM, `P_2ω ∝ P_ω²` carries amplitude 0.5 at f1 and only 0.125 at
2·f1, so **f1 has 12 dB more signal**.

### Choosing the gain and the frequency together

The PDA100A2's bandwidth collapses as gain rises, so these are one decision.

| Gain | Bandwidth | Detectable optical amplitude |
|---:|---:|---:|
| 0 dB | 11 MHz | 8.6 nW |
| 10 dB | 1.4 MHz | 1.6 nW |
| 20 dB | 800 kHz | 0.58 nW |
| **30 dB** | **260 kHz** | **0.32 nW** |
| 40 dB | 90 kHz | 0.27 nW |

30 dB is the knee — the first setting where the detector's own noise dominates
the board's, so more gain costs bandwidth and buys almost nothing.

**A ladder, cheapest first.** Take first light at the top and only move down if
you see nothing:

| Detect at | f1 | Gain | Floor |
|---|---:|---:|---:|
| 2·f1 = 1.83 MHz | 915 kHz | 0 dB | 8.6 nW |
| **f1 = 915 kHz** | **915 kHz** | **10 dB** | **1.6 nW** |
| f1 = 200 kHz | 200 kHz | 30 dB | 0.32 nW |

Moving from the first row to the second is **~21×** end to end — 5× from the
noise floor and 12 dB from demodulating at f1 rather than 2·f1 — and costs
nothing but a knob and a button. The third row buys a further 5× but needs a
frequency change; 200 kHz is exactly generatable, clears the switcher family by
305 kHz, and gives 14 cycles per integration time against the ~10 minimum.

**If you see nothing at 0 dB, do not conclude there is no SHG.** At 8.6 nW you
cannot separate "no signal" from "not enough sensitivity", and CW SHG from a
bulk crystal at sub-mW pump can plausibly sit well under a nanowatt.

### Setting it up

- **AC-couple IN1.** The PDA100A2 output is DC coupled with ±6 mV offset, and
  at 30 dB any room light rides straight into the ±1 V range.
- **Cap the detector when not measuring.** The window is 75.4 mm². At 30 dB,
  **42 µW saturates the Red Pitaya's LV range** and 421 µW saturates the
  detector itself. Ambient light will exceed that.
- **No 50 Ω terminator** — it has a 50 Ω series resistor already, and the
  board's inputs are 1 MΩ, so use the Hi-Z gain column.
- **Keep the laser under 1 mW**, as always.

### The control that makes it a result

**Power scaling.** The AOM artefact is linear optics and goes as P¹; SHG goes
as P². On log-log against laser power the background has slope 1 and SHG
slope 2. This works with the crystal left **in**, which crystal-in/out does
not, and the laser's −5 to +13 dBm range gives an 18 dB lever arm. Worth
measuring the slope-1 baseline before the crystal arrives.

---

## After that: SFG

Needs the **second amplifier and second AOM wired** — they exist and are not
connected. The bench already drives OUT2 and can demodulate the products.

**Take the difference, not the sum.** SFG goes as I1·I2, so the nonlinearity
appears at f1+f2 and \|f1−f2\|; f1 and f2 alone are linear and are the
controls. On a wavelength-selective detector the difference is the better
choice — \|f1−f2\| = 310 kHz allows 20 dB of detector gain, where f1+f2 =
2140 kHz forces 0 dB.

| | Frequency | Gap to the switcher family |
|---|---:|---:|
| f1 | 915 kHz | 94.7 kHz |
| f2 | 1225 kHz | 215.3 kHz |
| f1 + f2 | 2140 kHz | 120.5 kHz |
| \|f1 − f2\| | 310 kHz | 194.9 kHz |

**Four** frequencies must clear 504.868 kHz and its harmonics, not the two
being driven. A round 1000 kHz second tone fails: 9.7 kHz from the second
harmonic.

**Run the one-tone control first and get it clean.** Amplifier intermodulation
lands at exactly \|f1−f2\| and is indistinguishable from a real signal. This is
U2, the last electrical unknown, and `p5_first_measurement.py` enforces the
ordering.

---

## Then: the second axis

The deliverable is an **11 × 5000 map** — eleven wavelengths of the stepping
laser, one sweep each. **The TSL-770 has never been contacted**, so today's
output is 1 × 5000. `SweepSeries` / `write_series` in `pipeline.py` already
handle the set.

The TSL-775's LAN recipe should transfer, but nothing is proven. Parked at
Kevin's request.

---

## Decisions already taken — do not reopen

| | |
|---|---|
| **No attenuator** on the drive | Kevin tuned it by maximising diffracted light with an unmodulated carrier, which is correct because the drive is depth-1 AM. Three attenuator recommendations were made and all three withdrawn (Q12) |
| **Laser under 1 mW** | Below the PDA05CF2's ~0.96 mW saturation, and so well below damage |
| **Amplitude only**, not phase | Q6. A constant phase offset does not affect the deliverable |
| **No sweep averaging** | Q13. Each sweep is its own measurement |
| **No FPGA work** | ADR-0001 |

## Still open

| | |
|---|---|
| **Q17** — the success criteria | Waits on the crystal: what counts as a detection depends on what the DUT gives |
| **Q34** — unattended operation | Nothing runs unattended and nothing needs to yet. Needs an answer before any long run with the amplifiers live |
| **Q31** — the generator's frequency-error magnitude | Worked around by planning one modulation cycle. Two cheap board-only checks would close it: read `SOUR1:FREQ:FIX?` back, and measure the phase slope of a long loopback capture |
| **Q32** — why `:WAV` stops a sweep | Worked around by waiting between Configure and Start |
| **Q35** — two divergent laser drivers | `TSL775` for the bench, `SantecTSL` for the pipeline. Should converge |

Also open and not tracked as a question: **the bench can be launched twice**,
and one instrument with one connection slot deserves a single-instance lock.
