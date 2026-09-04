# 03 — Frequency plan

**Read this before choosing any frequency. Never hand-roll one.**

This document has been **wrong twice, in opposite directions**, and both times
the error was an untested assumption about how the generator works. What
follows is the model that has been measured on the board. The two wrong models
are kept at the end, because knowing which mistakes were already made is the
only thing that stops them being made again.

---

## 1. How the generator actually works

```
output frequency = cycles written into the table x play rate
```

The DAC runs at a fixed **250 MS/s** and the 16384-entry table is **decimated
on the fly**. `SOUR<n>:FREQ:FIX` sets the **play rate** — how many times per
second the table is traversed — and the index advances by

```
step = 16384 x play_rate / 250e6     entries per DAC clock
```

so each traversal emits `250e6 / play_rate` distinct samples.

Measured 2026-08-28, OUT2 looped to IN2:

| cycles in table | played at | expected | measured | |
|---:|---:|---:|---:|---|
| 20 | 1 MHz | 20 MHz | 20.004 MHz | |
| 80 | 1 MHz | 80 MHz | 80.002 MHz | |
| 200 | 1 MHz | 200 MHz | **50.003 MHz** | folded: 250 − 200 |
| 260 | 1 MHz | 260 MHz | **9.995 MHz** | folded: 260 − 250 |

**The folds land exactly where a 250 MS/s sampler puts them. That is the
proof:** the generator is a DDS, and the play rate sets how fast it walks the
table, not how fast the converter runs.

| play rate | step per clock | samples per period | |
|---:|---:|---:|---|
| 15258.789 Hz | **1.000** | 16384 | every entry used |
| 76 250 Hz | 5.0 | 3279 | |
| 1 MHz | 65.5 | 250 | most entries skipped |

**That is all `fs/16384` ever was** — the one rate at which the step is exactly
one entry per clock. It was never a limit, just the point where nothing is
skipped.

### The constraints that are real

**Cycle counts must be integers.** Both the carrier and the modulation need a
whole number of cycles in the table, or it wraps discontinuously. A
discontinuity repeating at the table rate sprays a spur comb across the
baseband — precisely where the demodulated sweep trace lives, where it looks
like structure in the DUT response. *This part was always true, and it is the
only part of the original plan that was.*

**The play rate is quantised to 1 Hz.** Measured: 1000000.5 reads back
1000000, and 15151.5152 reads back 15151. So a **modulation must be a whole
number of hertz** to have an exact table. That is the entire remaining grid,
and it is fine enough that nothing you would actually ask for is excluded.

**The carrier lands on the nearest multiple of the same play rate.** Its error
is at most half a play rate — a few hundred kHz at worst — which the
1550AOM-1's megahertz-wide acoustic passband cannot tell apart. Requiring the
carrier exactly would rule out most modulations for no benefit.

**The output must stay under 125 MHz**, or it folds, as the 200- and 260-cycle
rows show. The play rate itself clamps at 100 MHz — asked for 130 or 200, the
board reports 100.

**At least 8 table entries per carrier cycle.** Nyquist alone is not enough:
8000 carrier cycles in 16384 entries satisfies it at 2.05 entries per cycle and
reconstructs to pure alias. The configuration measured working had 204.8.

### Two things that are not free

**Spurs.** Driving at a high play rate raised lines at 36.0 and 54.0 MHz to
~6% and ~4.6% of the carrier, against ~0.2% on the old default grid. They sit
far from the modulation and an AOM will not diffract them efficiently, but they
are real and **unexplained**.

**Nothing is gained by a finer table at a high play rate.** With 80 carrier
cycles played at 1 MHz the DAC emits 250 samples per modulation period, so the
carrier gets 250/80 = 3.125 samples per cycle — exactly what the default grid
gives it too. The DAC's 250 MS/s is the limit either way.

---

## 2. Prefer the FEWEST modulation cycles

`plan_exact_am()` searches for a table and, since 2026-09-01, **prefers the
fewest modulation cycles the carrier tolerance allows** (`carrier_tol=0.5e6`).
This is not cosmetic.

The output is `mod_cycles × play_rate`, so **a play-rate error is multiplied by
the cycle count** and lands on the modulation — the frequency the lock-in must
match.

| Plan | mod_cycles | play rate | observed lock-in offset |
|---|---:|---:|---:|
| 915 kHz, old planner | 12 | 76 250 Hz | **~0.69 Hz** |
| 915 kHz, new planner | 1 | 915 000 Hz | none visible |
| 1 MHz | 1 | 1 000 000 Hz | none visible |

A 0.69 Hz offset does not look like an error. It looked like **a smooth arch
from −76 mV through zero to +134 mV across the sweep** — because `amplitude()`
projects onto one phase, and a phase winding 0.69 turns over a 1 s record gives
`A·cos(phase)` with R flat at 134 mV throughout.

**The magnitude is still unexplained (Q31).** A 32-bit DDS accumulator at
250 MS/s realises 76 250 Hz to within 0.0015 Hz, which is 0.018 Hz after ×12 —
nearly 40× short of what was observed. Worked around, not understood. Two cheap
board-only checks would settle it: read `SOUR1:FREQ:FIX?` back, and measure the
phase slope of a long loopback capture.

Moving 915 kHz from 12 cycles to 1 cycle moves the carrier to 79.605 MHz,
costing about **0.06 dB** of AOM efficiency — estimated from the 50 ns rise
time, i.e. a ~6.4 MHz acceptance. Free, in practice.

---

## 3. Choosing a modulation frequency

Now that every whole hertz is reachable, **the round numbers are the dangerous
ones.** The board's switching supply puts ~32 µV — nine times the noise floor —
at **504.868 kHz** and its multiples, and a lock-in cannot tell a steady tone
from the supply apart from a steady tone from the DUT.

| Candidate | Gap to the nearest harmonic | Supply drift needed to land on it |
|---|---:|---:|
| 500 kHz | 4.9 kHz | 0.96% |
| 1.000 MHz | 9.7 kHz | 0.96% |
| 1.5 MHz | 14.6 kHz | 0.96% |
| **915 kHz** | **94.7 kHz** | **9.4%** |

**915 kHz is the bench default for that reason.** The Drive panel warns
whenever the chosen frequency comes within 20 kHz of the family. Full
measurement in `06-results.md`.

### For SFG, FOUR frequencies must clear the supply, not two

Sum-frequency generation needs both beams modulated, and its signature is the
**product**: light out goes as I1 × I2, so a χ⁽²⁾ mixer puts components at
**f1 + f2** and **|f1 − f2|** that neither beam alone can produce. f1 and f2
themselves are linear — light at either reaches the detector whether anything
mixes or not — so they are the **controls**, not the measurement.

Picking f1 and f2 clear of the supply and stopping there is the easy mistake: a
*product* landing on a harmonic reads as a strong, clean, steady optical signal
in exactly the place the real signal is expected.

The bench defaults, and why:

| | Frequency | Gap to nearest 504.868 kHz harmonic |
|---|---:|---:|
| f1 | 915 kHz | 94.7 kHz |
| f2 | **1225 kHz** | 215.3 kHz |
| f1 + f2 | 2140 kHz | 120.5 kHz |
| \|f1 − f2\| | 310 kHz | 194.9 kHz |

A round 1000 kHz was the obvious second tone and is the wrong one — it sits
9.7 kHz from the second harmonic. 1225 kHz is the nearest round-ish number that
keeps all four clear with margin.

Both tables are exact and both carriers land close to 80 MHz:

| | mod cycles | carrier cycles | play rate | carrier |
|---|---:|---:|---:|---:|
| f1 | 12 | 1049 | 76 250 Hz | 79.9862 MHz |
| f2 | 10 | 653 | 122 500 Hz | 79.9925 MHz |

The two channels do **not** share a table, a play rate or a carrier, and they
do not need to: SFG detects an amplitude *product*, so the relative phase of
the two 80 MHz acoustic drives is irrelevant. (The old two-tone plan shared a
buffer for exactly this reason — there the difference-frequency phase was the
measurement. It is not, here.)

**Always use the bench's f1 / 2×f1 / f2 / f1+f2 / |f1−f2| buttons.** They build
f_ref from what the ASG will actually **generate**. The sum of two requests is
not the sum of two outputs, and the error comes back as a beat across the trace
rather than as an error.

### Two degenerate settings

| | |
|---|---|
| **modulation = 0** | An unmodulated carrier at constant amplitude — CW. **Not** a DC level: the AOM needs its 80 MHz and the amplifier is AC-coupled, so DC would do nothing. Costs about 3 dB more average RF power than depth-1 AM. There is no f1 for a lock-in to sit on |
| **carrier = 0** | A **plain sine at the modulation frequency**, one spectral line, exact to the hertz (one cycle in the table played at the frequency itself). Both `carrier` and `modulation` on the returned table name the tone, so the f1 button lands on it |

Both zero is refused, because that is no output at all.

---

## 4. The lock-in and point-count constraints

**Lock-in validity (R4).** The integrator must see enough cycles of the
reference to average the carrier away; below roughly 5–10 cycles per
integration time the output carries residual 1f and 2f ripple.

```
cycles per tau = tau x f_ref
```

**Point count (R5).** 5000 points across a 1 s sweep means a 5000 Sa/s output,
so 200 µs per point. A 5000 Sa/s output has a 2500 Hz Nyquist, and the widest
bandwidth that does not fold noise back onto the trace is 0.9 × 2500 =
**2250 Hz**, giving

```
tau = 1 / (2 pi x 2250) = 71 us
```

Combining the two, the minimum usable difference frequency is about
10 / 71 µs ≈ **141 kHz**. Anything above that satisfies R4. At 915 kHz there
are 65 cycles per integration time — about six times the minimum.

**The bandwidth is derived from the output rate, not chosen freely.**
`demodulate(output_rate=...)` clamps to 0.9 × output Nyquist, so asking for a
wider bandwidth alongside a fixed point count is silently ignored. That clamp
is deliberate — see ADR-0003 in `02-architecture.md`. The bench exposes the
bandwidth explicitly and shows the resulting τ, the noise gain and the settling
cost.

**And there is a hard floor on wavelength resolution.** A feature of width
`d` nm passes the detector in `d / speed` seconds, so

```
resolution_nm = speed_nm_s / (2 x bandwidth)
```

**`run_map` refuses anything coarser than 100 pm** (`RESOLUTION_LIMIT_NM`).
That is a refusal rather than a warning because the failure is invisible: an
over-filtered trace is smooth, plausible, correctly mapped onto wavelength, and
simply is not resolving what it claims to — and narrowing the bandwidth is
otherwise a free win, so nothing else pushes back on it.

---

## 5. History — the two wrong models

Kept because both were believed, both were written into the code, and both
produced confident wrong answers.

### Wrong model 1 — "the ASG replays exactly the N samples you load"

The original plan assumed `SOUR:FREQ:FIX = fs/N` replays an N-sample buffer one
entry per DAC clock, and derived a **250-sample buffer** from it: 80 cycles of
carrier, 5 of f1, 6 of f2, 1 of the difference. Elegant, and wrong.

Two things from that era are still worth keeping:

**The naive buffer rule N = fs/f_mod is wrong.** It works for f1 = 5 MHz
(250/5 = 50) and fails for f2 = 6 MHz, where 250/6 = 41.67 — yet a buffer for
6 MHz does exist: N = 125 gives 6 whole modulation cycles and 40 carrier
cycles. The correct rule is the smallest N making `N·f/fs` whole for *every*
frequency simultaneously. The first implementation rejected 6 MHz as impossible
when it is perfectly realisable.

**Each output carries three lines.** At 100% depth OUT1 has 75/80/85 MHz and
OUT2 has 74/80/86 MHz, all above the board's 60 MHz output specification and
all attenuated. Understood and accepted — the amplifier chain compensates, and
the attenuation was measured. The carrier component sits at half the peak
amplitude of the normalised waveform, which matters for power budgeting.

### Wrong model 2 — "everything must sit on a 15258.789 Hz grid"

Measured 2026-08-12: a 50-sample buffer at 5 MHz produced **no output at all**
(min −2, max 4 counts), while loading the full 16384-entry table and playing it
at `fs/16384` reproduced the intended spectrum exactly. The conclusion drawn
was that the ASG *always* traverses a fixed 16384-entry table at a rate that
must be `fs/16384`, and therefore that every frequency must be an integer
multiple of **15258.7890625 Hz**.

That was the plan the code used from 2026-08-12 to 2026-08-28. It gave:

| Quantity | Nominal | Grid value | Offset |
|---|---:|---:|---:|
| Carrier | 80 MHz | **80.001831 MHz** | +1831 Hz (+23 ppm) |
| f1 | 5 MHz | **5.004883 MHz** | +4883 Hz (+977 ppm) |
| f2 | 6 MHz | **5.996704 MHz** | −3296 Hz (−549 ppm) |
| \|f2 − f1\| | 1 MHz | **991.821 kHz** | −8179 Hz (−0.82%) |

**Re-measured 2026-08-28, the ceiling does not exist.** A short buffer is not
ignored — the board treats what you write as the whole table, so the frequency
scales as 16384/N (measured 65.54 = 16384/250 for a 250-entry write). And
`SOUR:FREQ:FIX` accepts 1 MHz and 5 MHz perfectly well. The decisive test: a
16384-entry table holding **one** modulation cycle and **80** carrier cycles,
played at **1 000 000 Hz**, gave a carrier at 80.0018 MHz with sidebands at
78.995 and 80.978 MHz, at 132 counts against the grid path's 124 — exactly
80 MHz amplitude-modulated at exactly 1 MHz, with no loss of amplitude.

**What survives.** `plan_two_tone_grid()` — carrier 80.001831 MHz, difference
**991.821 kHz** — is still what the two-tone code uses, and those frequencies
do work: they were verified on the board and every Phase 1 result rests on
them. They are now needlessly constrained rather than wrong.

**One warning from that era is unchanged and still load-bearing: do not
hardcode `1e6` as the lock-in frequency.** Typing the round number into a
demodulator produces a flat trace and no error, because the real signal falls
outside the 2250 Hz output filter. Use `plan_two_tone_grid().difference`, or
better, the bench's frequency buttons.

**And one consequence that is simply gone.** ADR-0001 noted that 1 MHz is
exactly fs/250, which would make an FPGA demodulator a fixed 250-entry table.
Under the grid plan that stopped being true. Under the current model an exact
1 MHz is reachable again — so if FPGA work is ever revisited, that convenience
is back.
