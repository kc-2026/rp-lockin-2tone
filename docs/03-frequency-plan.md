# Frequency plan

> **SUPERSEDED IN PART, 2026-08-12 — read this first.**
>
> This document derives a 250-sample buffer from the assumption that the
> generator replays exactly the N samples you load. **Measured on the board,
> it does not.** The ASG always traverses a fixed 16384-entry table, and
> `SOUR:FREQ:FIX` sets the traversal rate. See "The arbitrary generator does
> not work the way waveforms.py assumes" in `04-hardware-reference.md` for the
> evidence.
>
> What survives: the *reasoning* about commensurability, the lock-in cycle
> count constraint, and the point-count constraint. All still apply.
>
> What changes: buffer length is no longer a free parameter. The period is
> fixed at 16384 samples = 65.536 µs, so every frequency must be an integer
> multiple of **fs/16384 = 15258.7890625 Hz**. Sections below that pick N are
> obsolete; the grid is now fixed and the frequencies move onto it.
>
> **Replacement operating point — decided by Kevin and implemented
> 2026-08-12.** Built by `plan_two_tone_grid()`, driven by
> `make_am_table()`, and verified on the board: all three AM lines land at
> exactly these frequencies, with sideband/carrier ratios of 0.512 and 0.488
> against 0.500 theoretical at a 20 MHz carrier where the analog path is flat.
>
> | Quantity | Grid multiple | Frequency | Was |
> |---|---:|---:|---:|
> | Carrier | 5243 | 80.0018 MHz | 80 MHz |
> | f1 | 328 | 5.004883 MHz | 5 MHz |
> | f2 | 393 | 5.996704 MHz | 6 MHz |
> | \|f2 − f1\| | 65 | **991.821 kHz** | 1 MHz |
>
> The carrier moves by 23 ppm, which is nothing to an AOM. The difference
> frequency lands at 991.821 kHz instead of 1 MHz, giving 70 cycles per 71 µs
> integration time instead of 71 — no material change against R4's 5–10. Being
> exactly on the grid matters far more than being a round number: off-grid, the
> table wraps discontinuously every 65.536 µs and sprays a 15.26 kHz spur comb
> straight across the baseband where the trace lives.

Why f1 = 5 MHz, f2 = 6 MHz, and a 250-sample buffer. This is the most
constraint-driven part of the design, and the constraints are not obvious.

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
