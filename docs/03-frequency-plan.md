# Frequency plan

> **CORRECTED 2026-08-28. Read this before anything below.**
>
> This document has been wrong twice, in opposite directions, and both times
> the error was an untested assumption about the generator.
>
> **The original version** assumed the ASG replays exactly the N samples you
> load, and derived a 250-sample buffer from it.
>
> **The 2026-08-12 correction** measured that a short buffer "produces no
> output at all", concluded the ASG always traverses a fixed 16384-entry table
> at `fs/16384`, and fixed every frequency onto a **15258.7890625 Hz grid**.
> That is the plan the code has used since.
>
> **Measured on the board 2026-08-28, with OUT2 looped to IN2, both of those
> are wrong.** The rule is simply:
>
> ```
> output frequency = cycles in the table x play rate
> ```
>
> and the play rate is a free setting. Evidence:
>
> | buffer written | output / play rate |
> |---:|---:|
> | 16384 | 1.00 |
> | 4096 | 4.00 |
> | 1024 | 16.00 |
> | 250 | 65.54  (= 16384/250) |
>
> A short buffer is neither ignored nor silent: the board treats what you write
> as the whole table, so the frequency scales as `16384/N`. And
> `SOUR:FREQ:FIX` accepts 1 MHz and 5 MHz — **there is no 15258 Hz ceiling.**
> That number is only the rate at which the table advances one entry per DAC
> clock, and nothing enforces it.
>
> **The decisive test.** A 16384-entry table holding **one** modulation cycle
> and **80** carrier cycles, played at **1 000 000 Hz**, gave a carrier at
> 80.0018 MHz with sidebands at 78.995 and 80.978 MHz, at 132 counts against
> the grid path's 124. Exactly 80 MHz amplitude-modulated at exactly 1 MHz,
> with no loss of amplitude.

## What the generator is actually doing

The obvious objection: if the table is 16384 entries and you play it at 1 MHz,
that is 16.384 GS/s, which no converter on this board can do. So what happens?

**The DAC runs at a fixed 250 MS/s and the table is DECIMATED on the fly.**
Measured 2026-08-28:

| cycles in table | played at | expected | measured | |
|---:|---:|---:|---:|---|
| 20 | 1 MHz | 20 MHz | 20.004 MHz | |
| 80 | 1 MHz | 80 MHz | 80.002 MHz | |
| 200 | 1 MHz | 200 MHz | **50.003 MHz** | folded: 250 − 200 |
| 260 | 1 MHz | 260 MHz | **9.995 MHz** | folded: 260 − 250 |

The folds land exactly where a 250 MS/s sampler puts them. That is the proof:
the generator is a DDS, and the play rate sets how fast it walks the table, not
how fast the converter runs.

Per DAC clock the table index advances by

```
step = 16384 x play_rate / 250e6   entries
```

so each traversal emits `250e6 / play_rate` distinct samples:

| play rate | step per clock | samples per period | |
|---:|---:|---:|---|
| 15258.789 Hz | **1.000** | 16384 | every entry used |
| 76 250 Hz | 5.0 | 3279 | |
| 1 MHz | 65.5 | 250 | most entries skipped |

**That is all fs/16384 ever was** — the one rate at which the step is exactly
one entry per clock. It was never a limit, just the point where nothing is
skipped.

Two consequences worth holding on to:

* **Nothing is gained by a finer table at a high play rate.** With 80 carrier
  cycles played at 1 MHz the DAC emits 250 samples per modulation period, so
  the carrier gets 250/80 = 3.125 samples per cycle — exactly what the default
  grid gives it too. The DAC's 250 MS/s is the limit either way.
* **The output must stay under 125 MHz.** `carrier_cycles x play_rate` above
  that folds, as the 200- and 260-cycle rows show. The 80 MHz carrier sits at
  3.125 samples per cycle, which is above Nyquist but not by much.

**The play rate itself clamps at 100 MHz** — asked for 130 MHz or 200 MHz, the
board reports back 100 MHz. Not a limit anything here approaches, but it is
there.

Amplitude falls off steeply with frequency, which is the analog path rather
than the generator: 1793 counts at 1 MHz, 844 at 60 MHz, 135 at 80 MHz, 27 at
100 MHz. The 60 MHz analog bandwidth is a specification, and 80 MHz is
deliberately beyond it — see `04-hardware-reference.md`.

## How frequencies are chosen now

Put a whole number of cycles of **both** the carrier and the modulation in the
table, and play it at a rate that makes them come out right:

```
modulation = mod_cycles     x play_rate
carrier    = carrier_cycles x play_rate
```

The cycle counts must be integers so the table wraps without a discontinuity —
that part was always real, and it is the only thing that was. The play rate
they multiply is free.

So for 80 MHz with 1 MHz modulation: **1 modulation cycle, 80 carrier cycles,
played at 1 MHz.** For a modulation that does not divide the carrier, a few
cycles and a lower rate bring the carrier closer — 915 kHz uses 12 and 1049
cycles at 76 250 Hz.

`plan_exact_am()` does this search; `make_am_table_exact()` builds the table.

### The only grid left

**The play rate is quantised to 1 Hz** (measured: 1000000.5 reads back
1000000, 15151.5152 reads back 15151). So a modulation must be a **whole number
of hertz** to have an exact table. That is the entire remaining constraint, and
it is fine enough that nothing you would actually ask for is excluded.

The **carrier** lands on the nearest multiple of the same play rate. Its error
is at most half a play rate — a few hundred kHz at worst — which the
1550AOM-1's megahertz-wide acoustic passband cannot tell apart. Requiring the
carrier exactly would rule out most modulations for no benefit.

### Two things that are not free

**Spurs.** Driving at a high play rate raised lines at 36.0 and 54.0 MHz to
~6% and ~4.6% of the carrier, against ~0.2% on the default grid. They sit far
from the modulation and an AOM will not diffract them efficiently, but they are
real and unexplained.

**Table resolution.** At least 8 table entries per carrier cycle. Nyquist alone
is not enough: 8000 carrier cycles in 16384 entries satisfies it with 2.05
entries per cycle and reconstructs to pure alias. The configuration that was
measured working had 204.8.

### Choosing a modulation frequency

Now that every whole hertz is reachable, **the round numbers are the dangerous
ones.** The board's switching supply puts ~32 µV — nine times the noise floor —
at 504.868 kHz and its multiples, and a lock-in cannot tell a steady tone from
the supply apart from a steady tone from the DUT.

| Candidate | Gap to the nearest harmonic | Drift needed to land on it |
|---|---:|---:|
| 500 kHz | 4.9 kHz | 0.96% |
| 1.000 MHz | 9.7 kHz | 0.96% |
| 1.5 MHz | 14.6 kHz | 0.96% |
| **915 kHz** | **94.7 kHz** | **9.4%** |

915 kHz is the bench default for that reason. The Drive panel warns whenever
the chosen frequency comes within 20 kHz of the family.

### What still stands from the 2026-08-12 plan

`plan_two_tone_grid()` — carrier 80.001831 MHz, f1 5.004883 MHz, f2
5.996704 MHz, difference **991.821 kHz** — is still what the two-tone code
uses, and those frequencies do work: they were verified on the board and every
Phase 1 result rests on them. They are now needlessly constrained rather than
wrong. **Do not hardcode 1e6 as the lock-in frequency**; that warning is
unchanged.

Everything below this line predates the correction. The reasoning about
commensurability, the lock-in cycle count and the point count all still apply.
Only the claim that frequencies must sit on a fixed 15258.789 Hz grid does not.

---

## The commensurability constraint

The stock generator replays a fixed buffer in a loop. For the output to be a
clean spectral line, the buffer must contain a **whole number of cycles of
every frequency in it** — both the 80 MHz carrier and the modulation.

If it does not, the waveform jumps discontinuously at each wrap. A
discontinuity repeating at rate fs/N produces a comb of spurs at multiples of
fs/N. For a 16384-sample buffer that comb starts at 15.26 kHz and extends
across the whole baseband — precisely where the demodulated sweep trace lives.
The result looks like structure in the DUT response. It is not.

Formally, buffer length N works for frequency f only if

    N · f / fs   is an integer

For the 80 MHz carrier at fs = 250 MS/s: N · 80/250 = 0.32·N must be an
integer, so **N must be a multiple of 25**. The modulation frequencies must
then land on the resulting fs/N grid.

## The naive rule is wrong

It is tempting to write N = fs / f_mod. That works for f1 = 5 MHz
(250/5 = 50 samples) and produces a beautifully small buffer. It fails for
f2 = 6 MHz, where 250/6 = 41.67.

But a buffer for 6 MHz does exist: N = 125 gives 6 whole cycles of the
modulation and 40 of the carrier. The correct rule is the smallest N making
N·f/fs whole for *every* frequency simultaneously. `_minimal_buffer()`
implements this; `make_am_waveform()` uses it.

This was a real bug — the first implementation rejected f2 = 6 MHz as
impossible when it is perfectly realisable.

## The lock-in constraint

Lock-in detection needs the integrator to see enough cycles of the reference to
average the carrier away. Below roughly 5–10 cycles per integration time, the
output carries residual 1f and 2f ripple.

    cycles per τ = τ · |f2 − f1|

## The point-count constraint

5000 points across a 1 s sweep means a 5000 Sa/s output, so 200 µs per point.
The integration time must be short enough that points are reasonably
independent, which in turn bounds the bandwidth from below.

Working backwards: a 5000 Sa/s output has a 2500 Hz Nyquist. The widest
bandwidth that does not fold noise is 0.9 × 2500 = 2250 Hz, giving

    τ = 1 / (2π · 2250) = 71 µs

Combining with the lock-in constraint, the minimum usable difference frequency
is about 10/71 µs ≈ 141 kHz. Anything above that satisfies R4.

## Putting it together

| N | buffer period | frequency grid | f1 = 5 MHz exact? |
|---:|---:|---:|:---:|
| 250 | 1.0 µs | 1 MHz | yes |
| 500 | 2.0 µs | 500 kHz | yes |
| 1000 | 4.0 µs | 250 kHz | yes |
| 2500 | 10.0 µs | 100 kHz | yes |
| 12500 | 50.0 µs | 20 kHz | yes |
| 16375 | 65.5 µs | 15.27 kHz | **no** |

The chosen point, N = 250:

| Frequency | Cycles in 250 samples |
|---|---:|
| Carrier 80 MHz | 80 |
| f1 = 5 MHz | 5 |
| f2 = 6 MHz | 6 |
| \|f2 − f1\| = 1 MHz | 1 |

All integers. The buffer is 250 samples — 1 µs — and holds exactly one cycle
of the difference frequency, which is a pleasing (if incidental) property.

1 MHz gives **71 cycles per integration time**, roughly seven times the minimum
R4 asks for. That headroom is deliberate: it leaves room to shorten τ later
without revisiting the frequency plan.

## If the DUT response rolls off

1 MHz was chosen for margin, not because the DUT demands it. If the DUT's
response at the difference frequency turns out to be weak at 1 MHz, lower
options on the grid are available and all remain valid under R4:

| \|f2 − f1\| | f2 | Buffer | Cycles per 71 µs τ |
|---:|---:|---:|---:|
| 1 MHz | 6 MHz | 250 | 71 |
| 500 kHz | 5.5 MHz | 500 | 36 |
| 250 kHz | 5.25 MHz | 1000 | 18 |
| 200 kHz | 5.2 MHz | 1250 | 14 |

Below about 141 kHz the lock-in constraint starts to bind. `plan_two_tone()`
will construct any of these; `TwoTonePlan.periods_per_tau()` checks the margin.

## Sidebands

Each output carries three lines. With 100% modulation depth:

- OUT1: 75, 80, 85 MHz
- OUT2: 74, 80, 86 MHz

All are above the board's 60 MHz analog output specification and will be
attenuated. This is understood and accepted — the downstream amplifier chain
compensates, and the attenuation has been measured. Note the carrier component
sits at half the peak amplitude of the normalised waveform, which matters for
power budgeting.

## Rules for changing frequencies

1. Use `plan_two_tone()`. Do not hand-pick frequencies.
2. If it raises, the frequencies are off-grid — move them, do not force it.
3. Check `periods_per_tau()` against the τ you intend to use.
4. Both channels must use the *same* buffer length, or their carriers drift
   apart in phase and the difference-frequency phase becomes meaningless.
   `TwoTonePlan.buffer_samples` is that shared length.
