# 06 — Measured results

**What this is:** every number this project has actually measured, in one place.
Anything here was measured against the board, not calculated or assumed.

**How the instrument behaves** is in `04-board-reference.md`. **How each
number was obtained**, step by step, is in `12-test-campaigns.md`.

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

## AC coupling — measured 2026-08-17, and it is free at the operating point

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

**Q23 is now settled for these figures, and they stand as written.** They
convert counts to volts using 1817.7 counts/V, confirmed to 0.04% by H3.5.
Loopback alone could not say whether the 0.882 factor sat in the generator or
the ADC, which would have made every absolute figure here 12.7% too high. **A
scope on OUT1 on 2026-09-03 put it on the OUTPUT side** — see "Q23, mostly
settled" below. Ratios and dB figures were never affected either way.

---

## Measured noise floor and the on-board spur family — 2026-08-13 (H3.3)

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

**The absolute scale is confirmed (Q23).** These convert counts to volts using
1817.7 counts/V, independently confirmed to 0.04% by H3.5. Loopback measures
generator × cable × ADC as one number and could not say where the 0.882 factor
lived; a scope on OUT1 on 2026-09-03 put it on the **output** side, so the
input scaling is right and **the figures above stand.** See "Q23, mostly
settled" below.

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


---

## Measured 2026-09-01

### The generator's frequency error scales with `mod_cycles`

The output is `mod_cycles x play_rate`, so a play-rate error is multiplied by
the cycle count and lands on the modulation — the frequency the lock-in must
match.

| Plan | mod_cycles | play rate | observed lock-in offset |
|---|---:|---:|---:|
| 915 kHz, old planner | 12 | 76 250 Hz | **~0.69 Hz** |
| 915 kHz, new planner | 1 | 915 000 Hz | none visible |
| 1 MHz | 1 | 1 000 000 Hz | none visible |

The 0.69 Hz was recovered from the trace shape: a constant R of 134 mV with the
phase winding 0.69 turns over a 1 s record reproduces the observed projected
amplitude of -79.9 to +134.0 mV against the measured -76.3 to +133.8 mV.

**The magnitude is not explained.** A 32-bit DDS accumulator at 250 MS/s
realises 76 250 Hz to within 0.0015 Hz, which is 0.018 Hz after x12 — nearly
40x short. See Q31.

### Trigger train, a clean 1 s sweep

| | |
|---|---|
| Pulses | 5001, against 5001 logged rows |
| Step | 199.9962 us measured, 200.0000 us nominal |
| Clock ratio, laser against board | 0.999980937 — **-19.06 ppm** |
| Edges off a uniform grid | 46.2 us rms — the error the measured-edge axis removes |
| Points carrying a wavelength | 5000 of 5097; the other 97 are pre-roll (68) and tail (29) |
| Wavelength span recovered | 1500.0038 to 1599.9884 nm |

### A sweep started before the laser reached its start

| | |
|---|---|
| Pulses | 4048 against 5001 expected |
| Interval | **200.00 us — exactly correct** |
| Span | 0.8094 s against 1.0000 s |
| Wavelength actually covered | 80.96 nm of the 100 nm requested, i.e. 1519.04 -> 1600 nm |

Both ratios are 0.8094 and the interval is untouched, which is what separates a
short RANGE from a fast SWEEP. A fast sweep compresses the interval and keeps
the count.

### A sweep left in step mode

Configured for 100 nm/s, the instrument covered 28 nm in roughly ten minutes —
about 2000x slow, consistent with dwelling at each of 5001 points.

### SFG frequency plan

Sum-frequency generation goes as I1 x I2, so four frequencies must clear the
504.868 kHz switching-supply family, not the two being driven.

| | Frequency | Gap to nearest harmonic |
|---|---:|---:|
| f1 | 915 kHz | 94.7 kHz |
| f2 | 1225 kHz | 215.3 kHz |
| f1 + f2 | 2140 kHz | 120.5 kHz |
| \|f1 - f2\| | 310 kHz | 194.9 kHz |

A round 1000 kHz second tone fails: 9.7 kHz from the second harmonic.

### PDA100A2 gain against bandwidth (datasheet, Hi-Z)

For the SHG product near 775 nm. Bandwidth collapses as gain rises, so the
detection frequency and the gain setting must be chosen together. The last
column folds the detector's NEP (scaled to ~0.5 A/W at 775 nm) with the board's
own 3.57 uV over the 4763 Hz noise gain.

| Gain | Bandwidth | Transimpedance | Detectable optical amplitude |
|---:|---:|---:|---:|
| 0 dB | 11 MHz | 1.51e3 V/A | 8.6 nW |
| 10 dB | 1.4 MHz | 4.75e3 | 1.6 nW |
| 20 dB | 800 kHz | 1.5e4 | 0.58 nW |
| **30 dB** | **260 kHz** | **4.75e4** | **0.32 nW** |
| 40 dB | 90 kHz | 1.51e5 | 0.27 nW |
| 50-70 dB | 28 / 9 / 3 kHz | — | worse |

30 dB is the knee: the first setting where the detector's own noise dominates
the board's, so more gain buys almost nothing while costing 3x the bandwidth.

At 30 dB the Red Pitaya's LV range clips at 42 uW of optical power on the
detector and the detector itself saturates at 421 uW — so ambient light on a
75.4 mm^2 window is a real hazard.

### The laser's LAN connection slots leak

Two connect-and-close cycles on port 10001 took it from accepting to silently
dropping SYNs, with nothing else on the network talking to the instrument.
Every closed port on the same host kept answering RST normally throughout, so
this is not a firewall. Port 5000 was already in that state. A front-panel LAN
reset did not recover it; a power cycle with the control PC quiet did. See Q33.

### The two amplitude estimators, against the measured noise floor

sigma = 3.57 uV per trace point. `R` is biased high and the bias does not
average away; the projection is unbiased and can go negative.

| true signal | SNR | mean R | error | mean amplitude() |
|---:|---:|---:|---:|---:|
| 0 uV | 0 | 4.48 uV | +1.25 sigma | 0.00 uV |
| 3.57 uV | 1 | 5.53 uV | +0.55 sigma | 3.58 uV |
| 10.7 uV | 3 | 11.32 uV | +0.17 sigma | 10.71 uV |
| 17.9 uV | 5 | 18.21 uV | +0.10 sigma | 17.85 uV |
| 107 uV | 30 | 107.16 uV | +0.02 sigma | 107.10 uV |


---

## Measured 2026-09-03

### SHG — the first nonlinear signal

| | |
|---|---|
| Crystal | an SHG crystal, in the beam path |
| Detector | the **APD on IN1** |
| Demodulated at | **2 x f1** |
| Result | **a clear peak at ~1559 nm**, the expected phase-matching wavelength |

**The quantitative detail is not recorded.** Peak amplitude, off-peak level,
peak width, laser power and detector gain all still need to come off the bench
log or a saved CSV and be written in here. Until they are, this is the only
line in this document without numbers, and it is the most important one.

**Why the peak is the convincing part, and what it does not yet prove.** The
known confound is the AOM's own second harmonic (Q30) — 13.3%, -17.5 dB, and
**the same wavelength shape as f1**, because it is linear optics riding the
same light through the same fibre. Its wavelength dependence is therefore the
broad transmission envelope of the path, and **it cannot produce a narrow peak
at a predicted phase-matching wavelength.** That is a far stronger
discriminator than "clear 13.3%".

What would finish it is the **power-scaling slope at the peak** — the artefact
goes as P^1 and SHG as P^2, the laser's -5 to +13 dBm range is an 18 dB lever
arm, and it works with the crystal left in. Not yet measured.

### The output lowpass is very nearly a brickwall -- measured 2026-09-04

Raised by Kevin: the traditional lock-in rule is that the output must be
sampled about **5x more coarsely than the filter** -- a sample no more often
than every 5*tau, so each reading is settled and independent. At 2250 Hz the
RC-equivalent tau is 70.7 us, 5*tau is 354 us, and we sample every **200 us**.
By the letter of the rule we are 1.8x too fast.

**The rule does not apply, and this is why.** It is written for a single-pole
RC output filter. Measured on the real chain by amplitude-modulating the
carrier and asking how much of the modulation survives to the output:

| Modulation | Response, 2250 Hz setting |
|---:|---:|
| 200 Hz | +0.4 dB |
| 1400 Hz | +0.4 dB |
| 1800 Hz | +0.1 dB |
| 2000 Hz | -0.9 dB |
| 2200 Hz | -6.4 dB |
| **2400 Hz** | **-82 dB** |
| **2500 Hz (output Nyquist)** | **-140 dB** |

**-3 dB at 2077 Hz**, consistent with the 2059 Hz recorded above. Flat to
1400 Hz and then gone: it falls 81 dB in the 400 Hz between 2000 and 2400.

**A single-pole RC at the same corner would be only -3.5 dB down at the output
Nyquist.** That is the entire reason for the 5x rule -- an RC has enormous
out-of-band tails, so you must sample slowly enough that what folds is small.
This filter has no tails to fold. Pinned by
`test_the_output_filter_is_dead_before_its_own_nyquist`, which requires at
least 60 dB and measures 140.

So the correct sampling criterion here is Nyquist on a band-limited signal:
**>= 2 x bandwidth = 4500 Sa/s. We take 5000.** Correct, with 11% margin.

### 5000 samples per second are about 3800 independent values

The other half of the traditional rule is real and worth stating: **N samples
are not N measurements.** Measured on pure noise at the operating point, by
two independent routes that agree:

| | |
|---|---|
| Autocorrelation, lags 1-5 | **+0.21, -0.15, +0.10, -0.06, +0.04** |
| Integrated autocorrelation time, all lags | **1.32 samples** |
| Same, from the variance of block means | 1.26-1.34 |
| **Independent values per second** | **~3800** of the 5000 taken |
| 2 x nominal bandwidth | 4500 |
| 2 x measured ENBW (2087 Hz) | 4174 |

**~0.84 x 2B, and the same ratio at 1000 Hz** (1691 against 2000), so the
trace carries close to the information-theoretic maximum for its bandwidth.
The right way to describe a sweep is therefore **"5000 points, ~3800 degrees
of freedom"**, not 5000 independent measurements.

Note the autocorrelation **alternates in sign** -- that is the sinc structure
of a sharp filter. Summing only the positive terms gives tau_int = 1.75 and
"3080 independent points", which is wrong; see `11-mistakes.md`.

### The original 5600-point specification does not hold together

Worth recording, because it is where the 5000 came from. The original brief
assumed **tau = 30 us over a 0.8 s sweep**, sampled at 5*tau, giving ~5300
points. Checked:

| | |
|---|---:|
| tau = 30 us | RC corner **5305 Hz** |
| 5*tau spacing | 6667 Sa/s, Nyquist **3333 Hz** |
| corner / Nyquist | **1.59** |

**The corner sits above the Nyquist frequency, so the recipe aliases** -- and
an RC is still only 1.5 dB down at 3333 Hz, so a lot folds. The traditional
recipe tolerates that because an RC lock-in output is usually read by eye or
by a slow meter, where nobody looks at the folded noise.

**What the current design changed, and what it cost.** Same point count, no
aliasing, 3.7 dB less noise (Q10, 2026-08-12) -- and **coarser time
resolution**: the 30 us intent implies ~94 us features, against **255 us
measured** here. In wavelength at 100 nm/s that is ~9 pm intended against
**25.5 pm delivered**.

To actually get the original resolution: bandwidth ~5300 Hz, output rate
>= 11.8 kSa/s (the 0.9 clamp), ~11800 points per second, and **+4.0 dB of
noise** since sigma scales as sqrt(ENBW). That is the 12500-point option Q10
considered and Kevin declined. Both boxes are on the bench, so it is a
two-field experiment whenever the trade is worth revisiting.

### The output lowpass, characterised

The bench now exposes the lock-in's output filter directly (bandwidth, or the
equivalent time constant). Measured against the real filter chain at the
default 5000 Sa/s / 2250 Hz operating point:

| | |
|---|---|
| −3 dB point | **2059 Hz** against 2250 nominal |
| Equivalent noise bandwidth | **2087 Hz** |
| **Noise gain** | **4184–4763 Hz — about 1.9x the nominal** |
| Settling | **113 output points**, 22.6 ms |

**The noise gain is the number to scale sigma by**, not the nominal bandwidth
and not the −3 dB point. Using 2250 Hz puts sigma **46% low**.

**Settling is NOT monotonic in bandwidth.** Measured across the range it runs
113 → 48 → 70 → 98 output points, because the transition width is floored at
0.10 × output Nyquist. A test that assumed monotonicity was wrong and was
rewritten to assert the readout reports the real number.

The decimation to 5000 Sa/s from 31.25 MS/s is a factor of **6250**, done as
`[5, 5, 5, 5, 5, 2]` — six cheap wide-transition stages, then one sharp 79-tap
filter at the output rate. That factorisation is what makes a 2 kHz corner at
31 MS/s affordable at all; a single FIR would need ~2.4 M taps.

### Wavelength resolution after the filter

```
resolution_nm = speed_nm_s / (2 x bandwidth)
```

| Bandwidth | Speed | Predicted | Measured impulse FWHM |
|---:|---:|---:|---:|
| 2250 Hz | 100 nm/s | 22 pm | **20 pm**, and 25.5 pm re-measured 2026-09-04 |
| 1000 Hz | 100 nm/s | 50 pm | **60 pm**, and 48 pm re-measured |

Good to about 20%, which is what the 100 pm structural limit is written
against (ADR-0004).

**Measure this with the OUTPUT OVERSAMPLED, or you will measure your own
grid.** At 2250 Hz the impulse is ~255 us wide and the output steps every
200 us, so a FWHM read off the trace itself is quantised to about half its own
value: doing that gives **450 us**, twice the truth, and reads as the formula
being 2x optimistic. Hold the bandwidth and raise the output rate to 50 kSa/s
-- same filter, finer ruler -- and it converges to 255 us. See
`11-mistakes.md`.

### Q23, mostly settled: the counts-per-volt constant is right

**Measured with a scope on OUT1.** A commanded **0.200 V** read **70 mV RMS**
on the scope, which is **99 mV amplitude**. The bench's lock-in trace read
**100 mV** on the same signal — **1% agreement**.

Two things follow.

**1. `ADC_COUNTS_PER_V_LV = 1817.7` is correct, and the 0.882 factor lives on
the OUTPUT side.** That is the half of Q23 that mattered: the photodetector
drives the input directly with no generator involved, so the absolute noise
figures above stand as written rather than being 12.7% high.

**2. `SOUR<n>:VOLT X` commands X volts PEAK-TO-PEAK.** A commanded 0.2 V is a
0.1 V amplitude. **Drive levels have therefore been 6 dB more conservative than
the arithmetic in the attenuator discussion assumed**, which only widens an
already comfortable margin.

**Still outstanding:** a **0.400 V** scope reading, to confirm the factor is a
constant 0.5 and linear rather than something more interesting. Until that
exists, treat the peak-to-peak finding as measured at one point.

### What the lock-in graphs display

**Zero-to-peak amplitude, in volts at IN1, of the component at f_ref.** Not
RMS, not peak-to-peak.

Confirmed three ways: the normalisation in `dsp.py`
(`z = 2.0 * (block - dc) * exp(...)`); a pure-software test putting 10, 134 and
400 mV in and getting 10.000, 134.000 and 400.000 mV out; and the loopback
agreement against the scope above.

**One label is still wrong and known to be:** the capture log line reports
`swing()`, which is peak-to-peak, alongside trace numbers that are zero-to-peak,
with no units named. And `run_demodulate` / `run_map` both hardcode `gain="LV"`
rather than reading the front end that is actually set.

### Dynamic range is 20 log10, and it is unit-free

`_bench_ops.trace_dynamic_range` reports

```python
20.0 * np.log10(peak / floor)
```

**20, not 10** — correct for a *voltage* ratio, and equal to 10·log10 of the
corresponding power ratio.

Because `peak` and `floor` are in the same units — zero-to-peak amplitude volts
— **the ratio is dimensionless and every convention question above cancels out
of it.** A factor of 2 in both changes nothing. Every dynamic-range number
reported so far stands regardless.

**The floor is the scatter of one wavelength ACROSS repeats**, not the off-peak
rms:

```python
per_point   = np.nanstd(stack, axis=0, ddof=1)     # M sweeps x N wavelengths
floor       = sqrt(mean(per_point ** 2))
```

That needs no idea where the signal is and no assumption that it ever stops,
which matters because **a sinc's tails never do**. Verified against known
truth in the offline suite: **3.55 µV recovered from a true 3.57**.

`tail_ratio` comes along free — off-peak rms divided by the across-sweep
floor. Near 1 the trace really is empty away from the peak; well above 1 there
is real structure in the skirts, which for a sinc is the answer rather than a
problem.

### Dynamic range against the commercial lock-in

Measured with the **laser output at +10 dBm** and the **APD on gain notch 2**:

| | Dynamic range |
|---|---:|
| **This instrument (the board + software lock-in)** | **~55 dB** |
| The commercial lock-in, same conditions | ~60 dB |

**About 5 dB short of the bench reference**, not orders of magnitude. The gap
has not been chased.

Two things to hold on to when reading this. **Dynamic range is a ratio of two
voltages in the same units**, `20 log10(peak / floor)`, so it is unaffected by
every peak-to-peak-versus-amplitude question elsewhere in this document. And
**+10 dBm is well above the 0 dBm ceiling written throughout these documents**
-- that ceiling is the PDA05CF2's 0.96 mW saturation and nothing more, and the
detector has changed. See Q39.

### The detector on IN1 is now an APD

`scripts/dr_bench.py` was written to characterise its gain knob: N sweeps per
gain setting, averaged, reduced to peak / floor / dynamic range, with a
waterfall, a DR-against-gain curve and a peak-and-floor curve. **No results are
recorded here yet.**

Two things it reports that are not optional:

- **`clip`** — raw ADC samples at the rail, summed over the sweeps. Anything
  but 0 and the point is **not a measurement**: a flattened peak understates DR
  *and* invents harmonics, in exactly the place an SHG measurement looks.
- A point whose **peak stopped rising while the gain went up** is already
  compressing, even if nothing railed.

The laser power is set at every point by default, because constant optical
power is what makes the gain comparison mean anything. If the laser drifts
between points the peak moves for reasons that have nothing to do with the
detector.
