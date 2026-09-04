# 01 — Project overview

## Goal

Measure a nonlinear sample's response as a function of laser wavelength, using
lock-in detection on a Red Pitaya SIGNALlab 250-12.

Light is **intensity-modulated** by an acousto-optic modulator. The sample's
nonlinearity puts a component at a frequency neither beam alone carries, a
photodetector returns it, and software demodulation turns one laser sweep into
an amplitude-against-wavelength trace.

Which frequency that is depends on which nonlinearity is being looked for:

| | Modulate | Detect at | Because |
|---|---|---|---|
| **Two-tone intermodulation** | two beams, f1 and f2 | **\|f2 − f1\|** | the mixing product; neither beam alone produces it |
| **SHG** (second harmonic) | one beam at f1 | **f1** on a silicon detector | `P_2ω ∝ P_ω²`, and silicon cannot see the 1550 nm fundamental at all |
| **SFG** (sum frequency) | two beams, f1 and f2 | **f1 + f2** or **\|f1 − f2\|** | output goes as I1·I2 |

The original plan was two-tone intermodulation at |f2 − f1|. The instrument is
built and works; the physics currently in front of it is **SHG first, then
SFG** — see `09-whats-next.md`.

## The 80 MHz belongs to the AOM, not to the sample

**The sample never sees 80 MHz at all.** It sees light varying in brightness at
f1 (and f2).

An acousto-optic modulator diffracts light only while it is driven
acoustically, and the Aerodiode 1550AOM-1 is an 80 MHz part.
Amplitude-modulating that 80 MHz — sweeping its envelope from zero to full —
gates the light, and *that* is what produces the optical modulation. If the AOM
were a different part it would be a different number.

One consequence worth recording: the generator's 1 Hz play-rate grid puts the
carrier a few hundred kHz off 80.000000 MHz at worst. **That is irrelevant to
the AOM**, whose acoustic passband is megahertz-wide (a 50 ns rise time implies
~6.4 MHz of acceptance, so 0.4 MHz costs ~0.06 dB).

## Two lasers, not one

Established 2026-08-25. Everything written before that date describes a single
sweeping laser; that was incomplete.

- **The fine sweeper (TSL-775)** covers ~100 nm in about one second, 5001
  logged points. Its trigger output goes to IN2 and its log supplies the
  wavelength axis. This is the one every older passage means by "the laser",
  and it is the one that works.
- **The stepper (TSL-770)** sits at **11 discrete wavelengths, one per sweep**.
  It never sweeps in real time, so it has no trigger train and no log to
  index — it is set, allowed to settle, and read with `:WAVelength?`. **It has
  never been contacted.** Parked at Kevin's request.

The deliverable across the eleven is an **11 × 5000 map**. `SweepSeries` in
`pipeline.py` holds the set. Today's output is **1 × 5000**.

**A naming collision that will cause a bug if it is not watched.** This
project's **f1/f2** are the AOM *modulation* frequencies, in megahertz. Kevin's
**freq1/freq2** are the *lasers*, in terahertz. Same names, nine orders of
magnitude apart.

## Where the wavelength axis comes from

**From the laser over its serial link, not from trigger-edge timing** (Kevin,
2026-08-14).

The laser logs **wavelength values with the time axis implicit**:
`:READout:DATa?` returns a bare array and `:READout:POINts?` its length, so
`wavelength[i]` belongs to logged point `i`. No time column is transmitted.

The trigger train is still digitised on IN2, but its job shrank from "encode
the wavelength axis in its interval timing" to **"say where in the record each
logged point sits"**. `reduce_sweep` places the log on the **measured edge
times**, because the sweep speed ripples ±11% with a 0.41 nm period and a
uniform grid carries up to 13.68 pm of error (Q29). Details in
`07-pipeline.md`.

**The one silent failure to design against:** both instruments define t = 0 as
"the first trigger", but independently. If the acquisition arms late and
latches the *second* pulse, every wavelength shifts by exactly one step and the
trace looks perfectly normal. Arm before the sweep, use pre-roll, and check the
pulse count against the table length. That is Q21, and
`wavelength.logged_point_times()` is built to avoid it — it locates **one**
edge and indexes from it, so a missed edge mid-record changes nothing.

## Requirements

| # | Requirement | Source |
|---|---|---|
| R1 | 80 MHz carrier on both drive outputs | **AOM** — the 1550AOM-1's acoustic drive frequency. Not a sample requirement |
| R2 | Independent amplitude modulation at f1 and f2 | measurement principle |
| R3 | Demodulate at the nonlinear product | measurement principle |
| R4 | Integration time ≥ 5–10 periods of the reference | lock-in validity |
| R5 | 4000–5000 output points per 1 s sweep | sufficient sampling of the sweep |
| R6 | Trigger the capture from the laser's trigger output | sweep alignment |
| R6b | Read the laser's wavelength log and map the trace onto it | wavelength axis (Kevin, 2026-08-14) |
| R7 | Software only; no FPGA development | scope decision, ADR-0001 |
| R8 | Runs on a control PC over the network | environment |
| R9 | **Output the trace as CSV**, raw capture as `.npz` alongside | Kevin, 2026-08-14 |
| R10 | **No averaging across sweeps** | Kevin, 2026-08-14 — each sweep is its own measurement |
| R11 | **Post-filter wavelength resolution never worse than 100 pm** | structural constraint, ADR-0004 |

**Amplitude only, not amplitude and phase** (Kevin, 2026-08-10). Phase is still
computed and returned by `demodulate()`, and is still useful *within* a sweep,
but it is not a deliverable and nothing should be gated on it. This is what
downgraded Q6 — the OUT1/OUT2 relative carrier phase is not repeatable across
restarts — from a blocker to a noted limitation.

One consequence worth acting on, and it is implemented: `R = sqrt(X² + Y²)` is
the obvious amplitude estimator and it is **biased upward in noise** (+1.25σ on
pure noise). Because the phase is steady *within* a sweep, rotating X + jY to a
common angle and taking the real part is unbiased and quieter. That is
`LockinResult.amplitude()`.

## Operating point

| Parameter | Value | Why |
|---|---|---|
| Carrier | ~80 MHz | AOM requirement |
| **Bench default f1** | **915 kHz** | 94.7 kHz clear of the 504.868 kHz switching-supply family |
| **Bench default f2** | **1225 kHz** | keeps f2, f1+f2 and \|f1−f2\| clear too |
| Acquisition | 31.25 MS/s (decimation 8) | fits a 1 s two-channel capture in the 128 MiB region, for 1.1 dB |
| Output rate | 5000 Sa/s | R5 |
| Bandwidth | 2250 Hz (default) | 0.9 × output Nyquist, the widest honest value |
| Equivalent τ | 71 µs | follows from the bandwidth |
| Wavelength resolution | 22 pm at 100 nm/s | speed / (2 × bandwidth) |

The **original two-tone plan** — carrier 80.001831 MHz, f1 5.004883 MHz, f2
5.996704 MHz, difference **991.821 kHz** — is what `plan_two_tone_grid()` still
returns, and every Phase 1 result rests on it. It is now needlessly constrained
rather than wrong. **Never hardcode 1e6 as the lock-in frequency.** See
`03-frequency-plan.md`.

**Note on τ.** The original spec suggested 30 µs. At a 5000 Sa/s output that is
5.3 kHz of bandwidth, above the 2.5 kHz output Nyquist — noise between 2.5 and
5.3 kHz would fold into the trace. 71 µs keeps the same 5000 points, removes
the folding and gains about 3.7 dB. **Decided 2026-08-12 (Q10, Kevin): keep
τ = 71 µs at 5000 points.** The alternative that also avoids aliasing is 12500
points at τ = 28.3 µs, which would honour the original convention but exceed
R5's point count; considered and not taken.

## Channel allocation

The board has two inputs and two outputs. All four are committed.

| Port | Use |
|---|---|
| OUT1 | 80 MHz AOM drive, AM at f1 — gates beam 1 |
| OUT2 | 80 MHz AOM drive, AM at f2 — gates beam 2. **Not yet wired to an amplifier** |
| IN1 | Photodetector. **LV / AC** — the detector is unipolar with a DC pedestal |
| IN2 | Sweeping laser's trigger train. **Must be HV** — the trigger is 3.3 V, and the ±1 V range clips it to a flat line that reads as "the laser is not triggering" |

Gain and coupling are **per channel** — see `setup_channel()`.

The **stepping** laser needs no channel at all: it is read over serial, not
digitised. There is no spare channel, and a reference pickoff of the drive is
not available — but is also not needed, since both tones are generated by this
board and are clock-coherent with the ADC.

## Out of scope

- FPGA development (ADR-0001).
- Real-time analog output of the demodulated signal. The deliverable is a
  captured trace per sweep, not a continuous voltage.
- Closed-loop feedback.

## How the project was sequenced

**Phase 0 — offline.** Signal processing, waveform construction, capture
planning, DUT emulator, test suite. No hardware. **Complete.**

**Phase 1 — loopback.** SCPI transport, transmit path, receive path, trigger
digitisation, long captures, using only cables from the board to itself.
**Complete, 2026-08-14.**

**Phase 2 — hardware in the loop.** Real drive levels through the amplifier
chain, the AOM, the sample, the photodetector, the laser trigger. **Under
way** — the instrument runs end to end and real optical sweeps exist.

**Phase 3 — usability.** Delivered ahead of schedule as `scripts/bench.py`.

Both campaigns are recorded in full in `12-test-campaigns.md`. **The phase
framing is history**; what the bench is today is `08-the-bench.md`, and what is
left is `09-whats-next.md`.

**Phase 2 success criteria are still not set** (Q17). They now wait on the
crystal, since what counts as a detection depends on what the sample gives. The
single most useful number to set them against: the noise floor is **σ = 3.57 µV
per trace point** at the ADC, so a response of **≥36 µV** is clearly visible in
a single sweep and anything below ~4 µV is not visible at all. With the
photodetector's own noise included, expect nearer **~11 µV** and **~120 µV**.
