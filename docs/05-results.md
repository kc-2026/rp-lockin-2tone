# Measured results

**What this is:** every number this project has actually measured, in one place.
Anything here was measured against the board, not calculated or assumed.

**How the instrument behaves** is in `04-hardware-reference.md`. **How each
number was obtained**, step by step, is in `07-phase1-loopback.md`.

**One recorded explanation here has been withdrawn.** H6.2 attributed the
125 MB read's 6.7–11.2 s to "~125 round trips at ~50 ms each". Reading the code
on 2026-08-25 showed there are no such round trips — the client issues at most
FOUR GETs per capture and the board helper streams the whole reply over one
connection. **The cause of the shortfall against the 87 MB/s single-read figure
is unknown.** Per-GET timing was added to the helper to settle it; the board has
not yet run the new helper, so the question is still open. The measured times
above stand; only the explanation was wrong.

---

## The headline numbers

| Quantity | Value | Where |
|---|---|---|
| **Noise floor, σ per trace point** | **3.57 µV** (loopback cable fitted) | below |
| **Signal needed for SNR 10** | **≥36 µV** at the ADC | below |
| Board's own floor, 50 Ω terminated | 2.39 µV (24 µV for SNR 10) | below |
| Amplitude linearity | 0.3% spread above 20 mV, over 2.4 decades | H3.1 |
| Phase stability within a capture | 0.002° over 28 ms | H3.2 |
| Noise vs bandwidth | √ENBW to 1.5% | H3.4 |
| Off-frequency rejection | matches the designed filter to **0.0 dB** | H3.5 |
| Trigger edge recovery | 0 of 732 intervals wrong | H4.1 |
| IN1/IN2 alignment | 0.0005 samples | H4.3 |
| `Trig:Pos` offset from the true crossing | +1.14 samples (9.1 ns), fixed | H4.4 |
| Deep-capture read, 125 MB two-channel | **6.7–11.2 s** (11–19 MB/s) over the FAST socket | H6.2 |
| Same bytes over SCPI, for comparison | 5.7 MB/s — a path nothing takes for bulk reads | H1 |
| Sweep-to-sweep amplitude repeatability | **0.0029% rms** over 20 sweeps | H7.1 |
| Sweep-to-sweep trigger repeatability | 6 ns rms | H7.1 |
| Trace point count and spacing | exactly 5000 at exactly 200.000 µs | H6.3 |

**The two that matter most for deciding whether the experiment works:** the
noise floor, and the fact that the demodulator's noise gain is **not** the
nominal bandwidth. Both are below.

## AC coupling — measured 2026-08-14, and it is free at the operating point

The photodetector's 0–10 V unipolar output has to be AC coupled to reach the
±1 V range. Two things were unverified: where the coupling rolls off, and whether
the noise floor changes. **Both now measured. Neither is a problem.**

**The high-pass corner is 17.0 Hz**, single-pole. Measured as the AC/DC amplitude
ratio at a driven tone, so the counts-to-volts calibration cancels and Q23 cannot
affect it. Three points fit one pole to 2%:

| Frequency | AC/DC | Implied corner |
|---:|---:|---:|
| 3 Hz | 0.1724 | 17.14 Hz |
| 10 Hz | 0.5057 | 17.06 Hz |
| 30 Hz | 0.8728 | 16.78 Hz |
| ≥300 Hz | 0.998–1.002 | flat |

**At 991.821 kHz the attenuation is 1.3 × 10⁻⁹ dB** — sixty thousand times above
the corner. AC coupling costs nothing at the operating point, and does not
measurably start costing anything until below ~78 Hz (0.1 dB).

**The noise floor is unchanged.** Demodulated σ came out 0.00601 counts DC
coupled against 0.00586 AC — a 2.5% difference on 392 output points, whose own
uncertainty is ~3.6%. **So every figure in this document carries over to AC
coupling unchanged.**

One measurement artefact worth recording so nobody re-derives it: the 100 Hz
point reads AC/DC = 1.37, which is not a real response. The DC-coupled record
carries a ~27 count offset, and at that decimation the record holds 13.42
cycles, so DC leaks across bins into the signal bin and *depresses* the DC-coupled
reading. The AC-coupled record has no offset to leak. Points at ≥300 Hz sit near
whole cycle counts and are unaffected. It is an artefact of a single-bin DFT, not
of the instrument.

## Predicted noise floor with the photodetector connected

**Everything above was measured with loopback cables. The real input is a
Thorlabs PDA05CF2, and it is noisier than the board.** Calculated 2026-08-14 from
its datasheet — *predicted, not measured*, and the first real test is P4.4.

| Route | Detector density | σ_detector | With the board | **SNR 10 needs** |
|---|---:|---:|---:|---:|
| Board alone (measured, loopback) | — | — | 3.57 µV | 35.7 µV |
| Optimistic — from NEP, 50 Ω gain | 65.5 nV/√Hz | 4.52 µV | 5.76 µV | 57.6 µV |
| **Pessimistic — from the 2 mV rms figure** | **163 nV/√Hz** | **11.27 µV** | **11.82 µV** | **118 µV** |

The two routes are independent — one from the quoted 2 mV rms output noise over
the 150 MHz bandwidth, one from the 1.26 × 10⁻¹¹ W/√Hz NEP through the gain — and
they disagree by 2.5×. That is not a reason to average them: the discrepancy
probably means the noise is not flat across 150 MHz, or the rms figure includes
amplifier contributions the NEP does not. **Plan against the pessimistic number
until P4.4 measures it.**

**So expect the real floor to be roughly 3× worse than loopback, and a signal of
~120 µV to be needed rather than ~36 µV.** The detector, not the ADC, will
dominate — which is the right way round: it means the instrument is not the
limitation, and it is why the sensitive ±1 V range plus AC coupling is worth
keeping rather than retreating to ±20 V.

Not included, and both can only make it worse: the real noise environment (U6)
and any pickup on a longer detector cable. Loopback added 50% just from a 30 cm
lead.

**One caveat on every absolute voltage here (Q23).** These convert counts to
volts using 1817.7 counts/V, confirmed to 0.04% by H3.5. But loopback measures
generator × cable × ADC as a single number and cannot say whether the 0.882
factor sits in the generator or the ADC. The photodetector drives the input
directly, with no generator involved, so **if the factor is in the generator,
every absolute figure here is 12.7% too high.** Ratios and dB figures are
unaffected.

---

## Measured noise floor and the on-board spur family — 2026-08-12 (H3.3)

Outputs off, loopback cables fitted, DC coupled, decimation 2.

**USE THESE NUMBERS.** They supersede an earlier 45.6 nV/√Hz → 2.96 µV → 30 µV
that appeared here and in three other documents; that set was revised twice and
was ~21% optimistic. The history is in `SESSION_LOG.md`.

| Configuration, IN1 at ±1 V | Density @ 991.821 kHz | σ per quadrature | For SNR 10 |
|---|---:|---:|---:|
| 50 Ω terminated — the board's own floor | 34.6 nV/√Hz | 2.39 µV | 24 µV |
| **Loopback cable, output off — plan with this** | **51.7 nV/√Hz** | **3.57 µV** | **36 µV** |

**The cable adds ~50%, and that is pickup, not an artefact.** The real input is a
longer cable from a photodetector in a noisier place, so 34.6 nV/√Hz is a floor
the real system will never see and 24 µV is an unreachable best case.

| Other ranges (density route only, likely ~6% high) | IN1 | IN2 |
|---|---:|---:|
| Density @ 991.821 kHz, ±20 V range | 697 nV/√Hz | 624 nV/√Hz |
| σ per quadrature, ±20 V range | 45.4 µV | 40.6 µV |

IN2 was not re-measured: it carries the trigger train, where a few percent of
amplitude noise is irrelevant.

Repeatable to 0.2%. Raw record σ is 0.68 counts against 0.289 counts for ideal
12-bit quantisation, so the floor is analog, not quantisation — though
quantisation is ~18% of the variance and not negligible.

**The noise gain is NOT the nominal bandwidth** — 4763 Hz measured against
2250 Hz nominal. Predicting σ from the −3 dB bandwidth gives 2.45 µV against
3.57 measured, **46% low, in the dangerous direction.**

**One caveat on the absolute scale (Q23).** These convert counts to volts using
1817.7 counts/V, independently confirmed to 0.04% by H3.5. But loopback measures
generator × cable × ADC as one number and cannot say whether the 0.882 factor
sits in the generator or the ADC. In the real experiment the photodetector drives
the input directly, with no generator involved, so **if the factor is in the
generator then every figure above is 12.7% too high.** Settling it needs a
calibrated source or meter, which is not a loopback measurement.

**σ scales as √ENBW to ~1.5%**, confirmed on real data across a factor of 8 in
bandwidth (H3.4). Scale by √ENBW, not √(nominal bandwidth), which is only good
to 4% because the ENBW/bandwidth ratio drifts with bandwidth.

### The switching-supply spur family — the one real hazard H3.3 found

Present on both inputs **with the outputs off**. Measured at 59.6 Hz resolution,
with the amplitude estimator validated against an injected tone of known size
(recovered to 0.2%):

| | Centre | FWHM | Amplitude | vs σ | Offset from f_lockin |
|---|---:|---:|---:|---:|---:|
| Fundamental | **504 867.6 Hz** | 335 Hz | **33.7 µV** | 11.4× | −486.95 kHz |
| 2nd harmonic | **1 009 737.7 Hz** | 451 Hz | **32.2 µV** | 10.9× | **+17.92 kHz** |
| 3rd harmonic | 1 514 602.7 Hz | 750 Hz | 18.0 µV | 6.1× | +522.78 kHz |

**Nothing reaches the trace today** — the demodulator rejects a component
17.9 kHz off frequency by more than 200 dB, and at 59.6 Hz resolution there is
no line at all inside the ±2250 Hz measurement band (worst in-band bin 1.44× the
local floor, which is just what the maximum of 75 noise bins looks like).

**But the margin is a frequency margin, not a rejection margin, and the stakes
are higher than they look.** A **−1.77% drift** of the fundamental (504.868 →
495.911 kHz) puts the second harmonic exactly on 991.821 kHz, where there is no
rejection at all. It would then read as a **32 µV steady amplitude — 11× the
noise floor, and squarely inside the 30 µV range we would call a healthy real
signal.** It would not look like interference; it would look like a strong,
clean, steady DUT response. So:

- **504.868 kHz and its multiples are a forbidden zone for any future choice of
  difference frequency**, with several kHz of margin (relevant to Q9, which
  contemplates lower values). The present 991.821 kHz is safe by luck, not by
  design.
- Short-term the line is stable: it held to within one 476 Hz bin across all
  eight sub-segments of a 256 ms record, and its 335 Hz width implies only
  ~0.07% jitter — 25× less than the 1.77% needed. **But 256 ms says nothing
  about hours, load, or temperature**, and a switcher moving a few percent over
  its full range is ordinary. **Re-measure the fundamental after the board has
  been warm and loaded for some hours** and confirm it has not walked toward
  495.9 kHz.

An earlier coarse-resolution pass put this family at 505.447 kHz with a ~4 µV
amplitude. Both were wrong: a 450 Hz-wide line smeared across a 7.6 kHz bin
reads about 8× too low, and the frequencies were bin centres rather than
measurements. **Do not size a narrow line from a coarse spectrum.**

### Use a median, not a mean, for a noise floor

A mean density over a window around the lock-in frequency silently absorbs any
spur in that window. The first pass of H3.3 averaged over ±38 kHz, swallowed the
1010.895 kHz harmonic, and reported 6.2 µV instead of 3.16 µV — wrong by 2×,
with nothing looking wrong. A median ignores lines. The mean/median ratio is
itself the useful diagnostic: it ran 2.1–2.4 at decimation 2, which is the tell
that a line is present.

### Do not read broadband noise at high decimation

Measured at the same input on the same afternoon, the floor near 991.8 kHz
"improved" on IN1 from 52 to 17 nV/√Hz going from decimation 2 to 64, while on
IN2 it "worsened" from 54 to 134. At decimation 2 the two channels agree within
5%; at decimation 64 they disagree by 60×. Both trends are artefacts — folding
of 2–60 MHz into the reduced band, plus whatever averaging the FPGA applies at
high decimation. **This settles the "unverified" caveat on the decimation 4
fallback above: do not use a high-decimation noise measurement to justify it.**

High decimation *is* good for one thing: locating discrete lines. A 16384-sample
buffer at decimation 64 covers 4.19 ms and so resolves 238 Hz, and a real line
holds its frequency as fs changes whereas a folded one moves. That is how the
505.447 kHz family above was pinned without any deep capture.

### Decimation costs far less noise than ADR-0002 assumes — MEASURED

ADR-0002 rejects decimation beyond 2 on the grounds that everything above the
new Nyquist folds into the record. That is true in principle but the penalty is
small, because **the board applies its own anti-alias filter when decimating.**
Measured 2026-08-14, outputs off, loopback cables attached:

| Decimation | Rate | σ per output point | Cost vs dec 2 | Signal for SNR 10 | 1 s, 2 ch |
|---:|---:|---:|---:|---:|---:|
| 2 | 125 MS/s | 3.29 µV | — | 36.0 µV | 477 MB |
| 4 | 62.5 MS/s | 3.65 µV | +0.9 dB | 39.8 µV | 238 MB |
| **8** | **31.2 MS/s** | **3.75 µV** | **+1.1 dB** | **40.9 µV** | **119.2 MiB** |
| 16 | 15.6 MS/s | 4.58 µV | +2.9 dB | 50.1 µV | 60 MB |

**Decimation 8 is the practical operating point on a 128 MB region.** It runs a
full 1 s two-channel capture for a 14% sensitivity cost, and avoids needing the
DMA region moved into the upper half of RAM — an edit that changes a node name,
an alias, and places the region outside the kernel's memory map, with a
non-booting board as the failure mode.

**Settled 2026-08-14: the main objection to decimation 8 has gone away.** That
objection was that 1.17% of trigger intervals fail to match at decimation 8, which
mattered while the wavelength axis was derived from edge intervals. It no longer
is — the Santec laser reports its own wavelength over serial, and the trigger only
has to align the sweep with the capture. Detecting one sweep-start edge is a far
easier task than recovering thousands of intervals without losing any.

**Confirmed with Kevin 2026-08-14:** the Santec triggers at fixed *time* steps, so
the train is periodic — but **only its first edge is used**, to give both
instruments a common t = 0. Alignment never depended on recovering the train
intact, so **the memory move is not needed.**

One caveat remains, and it is about honesty rather than risk: the missed-edge
mechanism was never explained — the recorded cause is off by a factor of a
hundred (see the log). The memory question is closed because the requirement
vanished, not because the fault was understood. If some future design needs the
whole train recovered intact, that fault is still there and still unexplained.

Note the margin is thin, and **every figure here is MiB** — 1024², the unit
`ACQ:AXI:SIZE?` and the device tree use. Exactly 1.000 s at decimation 8 is
**119.2 MiB**, 93.1% of the 128 MiB region; 43 ms of pre-roll adds ~5 MiB,
giving ~124 MiB, 97%. **H6.2's "125.2 MB" is the same unit and is larger only
because that capture ran 1.050 s** including pre-roll — 97.8% full. Both numbers
are right; they describe different captures, and neither is decimal MB. Decimation 16 leaves comfortable headroom
(63 MB) for +2.9 dB if that becomes awkward.

**Why the folding penalty is small here.** Nothing in this measurement has
high-frequency content to fold: the photodetector returns only the ~1 MHz
intermodulation response, so only *noise* folds, not signal. The naive estimate
(~6 dB at decimation 8, from counting alias bands) is wrong because it ignores
the decimation filter.

Decimation 2 remains the best operating point if the memory is ever available,
and decimation 1 does not fit at any region size.

**Decimation 2 is right for the real measurement but wrong for loopback
testing, and this is not a contradiction.** At decimation 2 the Nyquist limit
is 62.5 MHz, so an 80 MHz carrier aliases down to 45 MHz. In the real
experiment that never arises: the photodetector returns only the ~1 MHz
intermodulation response, and the 80 MHz never reaches an input. In loopback we
wire an output carrying 80 MHz straight into an input, so it does.

**Use decimation 1 for any loopback test that looks at the carrier.** A
measurement of the 80 MHz carrier at decimation 2 is measuring a 45 MHz alias,
and it will look entirely plausible — that is how the first drift measurement
produced a confident fictitious answer. Do not "fix" the operating point in
response; the plan is correct.

### Decimation 4 as a fallback

Not needed, but worth keeping in mind if the region cannot be enlarged for some
reason. ADR-0002 rejects it because 31–60 MHz folds in, but for *this*
measurement the fold may be tolerable: content at `f` lands at `62.5 − f` MHz,
so the energy reaching our 1 MHz lock-in frequency comes from 61.5 and
63.5 MHz, both above the 60 MHz analog rolloff. Caveats: 60 MHz is a −3 dB
point rather than a wall, and if `ACQ:AVG` applies to the AXI path its boxcar
nulls fall near 62.5 MHz, which would suppress the fold further. Both are
unverified — measure in H3.3/H3.4 before relying on any of it.

**Overtaken by events, 2026-08-14.** Decimation 4 was never needed: the noise
cost of decimation was measured directly (see below) and **decimation 8** was
adopted, which fits a full 1 s two-channel capture in the existing 128 MiB
region for 1.1 dB. H6.2–H6.5 and H7.1 all ran that way. The speculation above
about the 62.5 MHz fold is therefore moot, and was never tested.
