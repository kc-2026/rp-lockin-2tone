# 13 — The output filter, and why 5000 points is not too many

**A self-contained handoff.** Written 2026-09-04 to answer one question. It
stands alone; you do not need to open anything else to follow it.

**Reproduce every number in it with:**

```bash
.venv\Scripts\python.exe scripts\filter_study.py
```

That script is offline, touches no hardware, takes about two minutes, and is
the source of every figure below. Re-run it after any change to `dsp.py`.

---

## 1. The question

Kevin, 2026-09-04:

> Traditionally, the output of a lock-in amplifier must be sampled ~5× more
> coarsely than the filter. The ~5000 points given in an initial prompt here is
> coming from the assumption of a 30 µs time constant and a 0.8 s sweep, which
> gives 5600 points. Is the current approach compatible with this? Something
> seems off since a sub-second sweep can be rendered into 5000 points despite
> having a 2250 Hz bandwidth.

And, on being told the rule is written for an RC:

> The SR865A does not use a simple RC filter, but rather a Gaussian FIR filter.

And, on being told a Gaussian would need ~20 kSa/s of output:

> Why is 19851 Sa/s a problem for the Gaussian? The ADC sample rate is much
> faster.

**Both follow-ups were corrections to my answer, and both were right.** They
are recorded in `11-mistakes.md` §2.11 and §2.12.

## 2. The answer in five lines

1. **Yes, compatible.** The 5× rule manages a *gently-rolling* filter's tails
   past the output Nyquist. Ours is sharp — **−140 dB at Nyquist** — so plain
   Nyquist applies: ≥ 2 × bandwidth = 4500 Sa/s, and we take 5000.
2. **The rule's other half is real**: 5000 samples/s carry **~3800 independent
   values**, not 5000.
3. **The original 5600-point spec is the thing that does not hold together** —
   τ = 30 µs with 5τ spacing *aliases*, by a factor 1.59.
4. **What we pay for the sharpness is ringing**: **+5.5% step overshoot**. A
   Gaussian has none. That is a real open choice — **Q40**.
5. **A Gaussian is available**, and the output rate is not what stops it.

---

## 3. What the filter actually is

| | |
|---|---|
| Final stage | **Kaiser-windowed FIR, 79 taps at the output rate**, 60 dB stopband design |
| Cutoff | `min(bandwidth, 0.9 × output Nyquist)` = 2250 Hz |
| Transition width | **237.5 Hz** at the operating point |
| Preceded by | six lax Kaiser decimation stages, `[5,5,5,5,5,2]` = 6250, 90 dB |
| Measured −3 dB | **2223 Hz** |
| Settling | 113 output samples, 22.6 ms |

**It is not what its own design comment says.** `_design_filter_chain` computes

```
transition = min(max(0.8 × cutoff, 0.10 × Nyquist), 0.95 × (Nyquist − cutoff))
```

and the comment above it says the transition is *"deliberately comparable to
the cutoff … a lock-in output filter gains nothing from a brick wall … close to
the settling of a 2-pole analog filter of the same corner"*. The intended value
is **1800 Hz**. At the default operating point the third term binds at
**237.5 Hz**, because the bandwidth is pinned at 0.9 × Nyquist and only 250 Hz
of room is left.

**We get a brickwall by accident, and only at the default.** At bandwidth
1000 Hz the intent wins and the transition is 800 Hz.

## 4. The transfer function

Measured by amplitude-modulating the carrier and recovering the modulation —
i.e. the way the filter is actually used. Compared against a Gaussian and a
1-pole RC **matched at the same −3 dB point (2223 Hz)**:

| f | measured (full chain) | final stage alone | Gaussian | 1-pole RC |
|---:|---:|---:|---:|---:|
| 1000 Hz | −0.0 | −0.0 | −0.6 | −0.8 |
| 2000 Hz | −1.3 | 0.0 | −2.4 | −2.6 |
| 2200 Hz | −6.8 | −1.4 | −2.9 | −3.0 |
| 2400 Hz | **−82.8** | −67.4 | −3.5 | −3.4 |
| **2500 Hz (output Nyquist)** | **−140.2** | −75.6 | **−3.8** | **−3.6** |

*(The full chain beats the final stage alone because the six decimation stages
ahead of it add their own rejection.)*

**A Gaussian and an RC are indistinguishable at the output Nyquist** — −3.8 and
−3.6 dB. A Gaussian is deliberately the *gentlest* possible rolloff; that is
its whole point. **So the 5× rule applies to a Gaussian instrument exactly as
it does to an RC one**, and my first answer named the wrong exemplar while
getting the magnitude right.

Pinned by `test_the_output_filter_is_dead_before_its_own_nyquist`, which
requires ≥ 60 dB and measures 140.

## 5. What the sharpness costs — ringing

Measured on the full chain by stepping the carrier amplitude:

| Bandwidth | Step overshoot |
|---:|---:|
| **2250 Hz (operating point)** | **+5.5%** |
| 2000 Hz | +7.3% |
| 1500 Hz | +7.8% |
| 1000 Hz | +6.5% |
| 500 Hz | +7.8% |

First output samples after a step: 0.888, **1.055**, 0.961, 1.027, 0.982,
1.011, 0.995, 1.001 — a damped oscillation settling under 0.5% after ~7 output
samples (1.4 ms).

**A Gaussian has no overshoot and no sidelobes, by construction.** That is what
an instrument buys by choosing one, and it is Gibbs ringing from a windowed
sinc — a property of the Kaiser design, not of the accidental brickwall, since
it does not improve at the gentler settings.

**Why it matters here specifically:** this project's entire hazard class is
artefacts that look like signal. **~5% of peak height sitting 200 µs from a
sharp phase-matching peak is exactly that**, and it is not obviously wrong when
you look at it. Pinned in both directions by
`test_the_output_filter_overshoots_a_step_by_a_known_amount`.

## 6. Resolution — and how to measure it without fooling yourself

```
resolution = speed / (2 × bandwidth)
```

| Bandwidth | Measured FWHM | 1/(2B) | ratio | at 100 nm/s |
|---:|---:|---:|---:|---:|
| **2250 Hz** | **255 µs** | 222 µs | 1.15 | **25.5 pm** |
| 2000 Hz | 283 µs | 250 µs | 1.13 | 28.3 pm |
| 1500 Hz | 361 µs | 333 µs | 1.08 | 36.1 pm |
| 1000 Hz | 482 µs | 500 µs | 0.96 | 48.2 pm |

Good to ~15%, which is what the 100 pm structural limit (ADR-0004) is written
against.

**Measure this with the output OVERSAMPLED.** At 2250 Hz the impulse is ~255 µs
and the output steps every 200 µs, so a FWHM read off the trace itself
quantises to about half its own value: **the same measurement on the 5000 Sa/s
grid reads 461 µs**, twice the truth, and looks exactly like the formula being
2× optimistic. Hold the bandwidth, raise the output rate to 50 kSa/s — same
filter, finer ruler.

## 7. Degrees of freedom

| | |
|---|---|
| Autocorrelation, lags 1–5 | **+0.200, −0.145, +0.108, −0.068, +0.033** |
| τ_int, all lags | **1.32** |
| τ_int from block-mean variance | 1.25–1.29 |
| **Independent values per second** | **~3790** of the 5000 taken |
| 2 × nominal bandwidth | 4500 |

**Describe a sweep as "5000 points, ~3800 degrees of freedom."** That is the
honest content of the traditional rule, and it is close to the
information-theoretic maximum for this bandwidth.

**Sum all the lags.** This chain's autocorrelation alternates in sign; keeping
only the positive terms gives τ_int = 1.83 and "2700 independent points",
which is wrong.

## 8. The original specification, checked

| | |
|---|---:|
| τ = 30 µs | RC corner **5305 Hz** |
| 5τ spacing | 6667 Sa/s = 5333 points in 0.8 s |
| Nyquist there | **3333 Hz** |
| **corner / Nyquist** | **1.59 — it aliases** |

The corner sits *above* the Nyquist frequency, and an RC is still only 1.5 dB
down at 3333 Hz, so a lot folds. The traditional recipe tolerates that because
an RC lock-in output is normally read by eye or by a slow meter.

**Q10 took the other trade on 2026-08-12:** same point count, no folding, 3.7 dB
quieter. **The cost is time resolution** — 255 µs delivered against the ~94 µs
the 30 µs intent implies, i.e. 25.5 pm rather than ~9 pm at 100 nm/s.

## 9. The open choice — Q40

**Gaussian response, full bandwidth, 5000 rows — pick two:**

| | Bandwidth | Rows per 1 s sweep | Step overshoot |
|---|---:|---:|---:|
| **What we do now** | 2223 Hz | **5000** | **+5.5%** |
| Gaussian, same bandwidth | 2223 Hz | **25000** | 0% |
| Gaussian, same row count | **560 Hz** | 5000 | 0% |

**The output rate is not the obstacle.** A Gaussian at our bandwidth needs
~19.9 kSa/s for 60 dB at its own Nyquist. `max_output_rate` allows **31250 Sa/s**
at f1 = 915 kHz — the binding limit there is reference cycles per integration
time, not the converter — and **25000 Sa/s divides 31.25 MS/s exactly**. At
25 kSa/s the bandwidth is not clamped, so **noise, bandwidth and resolution are
all unchanged**; the only cost is 25000 rows instead of 5000.

**The 5000 is R5 — a line in the original brief — not a hardware limit.**

One thing that does *not* work: filtering with a Gaussian at 25 kSa/s and then
decimating to 5000 rows. That decimation needs its own anti-alias filter at
2500 Hz, which is precisely the sharp filter whose ringing you were avoiding.

**Nothing is broken today.** Every result this project has was taken with the
current filter, the overshoot is small and now measured, and both boxes
(`bandwidth`, `output rate`) are on the bench. This is a deliberate choice to
make, not a defect to fix.

---

## 10. If you are picking this up

- **Numbers**: `06-results.md` is the canonical home; this document repeats the
  ones relevant to the question.
- **Design rationale**: ADR-0003 and ADR-0004 in `02-architecture.md`.
- **The two errors made answering this**: `11-mistakes.md` §2.9–§2.12.
- **The open choice**: Q40 in `10-open-questions.md`.
- **Reproduce**: `scripts/filter_study.py`.
- **Tests that pin this**: in `tests/test_dsp.py` —
  `test_the_output_filter_is_dead_before_its_own_nyquist`,
  `test_the_output_filter_overshoots_a_step_by_a_known_amount`,
  `test_the_output_carries_about_two_bandwidths_of_independent_values`.

**The single most useful thing a next session could do here** is decide Q40
with Kevin: whether a 25000-row sweep with a Gaussian output filter is worth
having, given the SHG lineshape is the deliverable and a 5% shoulder beside a
phase-matching peak is the kind of artefact this project exists to avoid.
