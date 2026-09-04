# 09 — What's next

**Updated 2026-09-04.**

**SHG has been seen.** That was the first piece of physics and it is done; what
follows is the order of what is left. For the bench as it stands,
`08-the-bench.md`. For every number, `06-results.md`.

---

## SHG WORKS — measured 2026-09-03

**This is the first real physics result, and it is the thing the whole
instrument was built for.**

| | |
|---|---|
| Crystal | an SHG crystal, in the beam path |
| Detector | the **APD on IN1** |
| Demodulated at | **2 × f1** |
| Result | **a clear peak at ~1559 nm**, which is where phase matching was expected |

**Why the peak is the convincing part.** The known confound is the AOM's own
second harmonic (Q30): an AOM diffracts as sin² of its drive and the drive is
depth-1 AM, so the light arrives already distorted, carrying 13.3% (−17.5 dB)
at 2·f1 with **the same wavelength shape as f1**. That artefact is linear
optics riding the same light, so its wavelength dependence is the broad
transmission envelope of the path. **It cannot make a narrow peak at a
predicted phase-matching wavelength.** A peak where the crystal says one should
be is the discriminator, and a much stronger one than "clear 13.3%".

### What is not written down yet

- **The numbers.** Peak amplitude, off-peak level, the width of the peak, the
  laser power and the detector gain it was taken at. Pull them from the bench
  log or a saved CSV and put them in `06-results.md`.
- **A recorded control.** See below.

### The two controls that would finish it

**1. Power scaling — the strong one.** The AOM artefact goes as P¹; SHG goes as
P². On log-log against laser power the background has slope 1 and the signal
slope 2. This works with the crystal left **in**, which crystal-in/out does
not, and the laser's −5 to +13 dBm range gives an 18 dB lever arm. Measuring
the slope at the 1559 nm peak converts "a peak in the right place" into a
number.

**2. Confirm the detector model (Q38).** This decides how the result should be
read, and it is a label on a box:

- **If it is silicon** (APD410A2, ~200–1000 nm) it cannot see 1550 nm at all,
  the Q30 confound never reaches it, and anything detected is upconverted
  light by construction.
- **If it is InGaAs** (APD410A, ~900–1700 nm) it cannot see the ~780 nm
  product either — so what arrives at 2·f1 needs saying out loud, and the
  shape argument above is carrying the whole interpretation on its own.

Either way the observation stands. It is the *explanation* that depends on the
answer, which is why it is worth two minutes.

### If sensitivity ever becomes the limit

**Demodulating at f1 rather than 2·f1 is 12 dB more signal**, on a detector
that cannot see the fundamental. For depth-1 AM, `P_2ω ∝ P_ω²` carries
amplitude 0.5 at f1 and only 0.125 at 2·f1. The 2·f1 trick exists to escape the
huge fundamental on a detector that *can* see 1550; where the fundamental is
invisible, f1 is both unambiguous and bigger.

And gain and frequency are one decision on the PDA100A2, whose bandwidth
collapses as gain rises:

| Gain | Bandwidth | Detectable optical amplitude |
|---:|---:|---:|
| 0 dB | 11 MHz | 8.6 nW |
| 10 dB | 1.4 MHz | 1.6 nW |
| 20 dB | 800 kHz | 0.58 nW |
| **30 dB** | **260 kHz** | **0.32 nW** |
| 40 dB | 90 kHz | 0.27 nW |

30 dB is the knee — the first setting where the detector's own noise dominates
the board's, so more gain costs bandwidth and buys almost nothing. A ladder,
cheapest first: 2·f1 at 0 dB, then f1 at 10 dB (~21× better end to end — 5×
from the floor, 12 dB from the harmonic choice), then f1 = 200 kHz at 30 dB for
a further 5×. 200 kHz is exactly generatable, clears the switcher family by
305 kHz, and gives 14 cycles per integration time against the ~10 minimum.

`scripts/dr_bench.py` exists to find the knee of the real detector's gain
curve, and has not been run in anger yet.

### Detector handling, whichever one is fitted

- **AC-couple IN1.** The PDA100A2 output is DC coupled with ±6 mV offset, and
  at high gain any room light rides straight into the ±1 V range.
- **Cap the detector when not measuring.** The PDA100A2 window is 75.4 mm²; at
  30 dB, **42 µW saturates the Red Pitaya's LV range** and 421 µW saturates the
  detector itself. Ambient light will exceed that.
- **No 50 Ω terminator** — there is a 50 Ω series resistor already and the
  board's inputs are 1 MΩ, so use the Hi-Z gain column.
- **Keep the laser at or under 0 dBm (1 mW)**, as always.
- **A point that clips is not a measurement.** A flattened peak understates
  dynamic range *and* manufactures harmonics, in exactly the place a 2·f1
  measurement looks.

---

## Next: SFG

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
| **Q17** — the success criteria | **Now answerable.** The crystal is in and SHG has been seen, so "what counts as a detection" is no longer hypothetical. Worth settling with Kevin against the measured 1559 nm peak |
| **Q34** — unattended operation | Nothing runs unattended and nothing needs to yet. Needs an answer before any long run with the amplifiers live |
| **Q31** — the generator's frequency-error magnitude | Worked around by planning one modulation cycle. Two cheap board-only checks would close it: read `SOUR1:FREQ:FIX?` back, and measure the phase slope of a long loopback capture |
| **Q32** — why `:WAV` stops a sweep | Worked around by waiting between Configure and Start |
| **Q35** — two divergent laser drivers | `TSL775` for the bench, `SantecTSL` for the pipeline. Should converge |
| **Q36** — is the output's peak-to-peak factor linear? | One 0.400 V scope reading closes it |
| **Q37** — two known labelling defects | `swing()` is peak-to-peak next to zero-to-peak trace numbers, and `run_demodulate`/`run_map` hardcode `gain="LV"` |
| **Q38** — what detector is on IN1, exactly? | An APD410-series unit replaced the PDA05CF2. The model suffix decides InGaAs versus silicon, which decides the SHG plan |

Also open and not tracked as a question: **the bench can be launched twice**,
and one instrument with one connection slot deserves a single-instance lock.

## Small, cheap, and worth doing now

**In rough order of value per minute:**

- **Write the SHG numbers down.** Peak amplitude, off-peak level, peak width,
  laser power and detector gain, into `06-results.md`. Right now the result
  exists as "a good peak at ~1559 nm" and nothing more.
- **Measure the power-scaling slope at the 1559 nm peak.** Slope 2 is SHG,
  slope 1 is the AOM artefact. This is the control that turns the observation
  into a result, and it needs nothing but the laser's own power setpoint.
- **Confirm the detector model** (Q38). It is a label on a box and it decides
  how the SHG result should be read.
- **Finish the detector gain study.** `scripts/dr_bench.py` is written and
  tested and no results are recorded. The knee of the DR-against-gain curve is
  the setting to run at.
- **Read `SOUR1:FREQ:FIX?` back** and measure the phase slope of a long
  loopback capture. Two board-only checks that would close Q31.
- **Re-measure the switching supply's fundamental** after the board has been
  warm and loaded for some hours, and confirm it has not walked toward
  495.9 kHz — where its second harmonic would land exactly on a 991.821 kHz
  lock-in and read as a strong, clean, steady signal.
