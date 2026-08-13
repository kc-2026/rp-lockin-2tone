# Open questions

Resolve these as they come up. When one is settled, move the answer into the
relevant doc and note it in `SESSION_LOG.md`.

## Blocking Phase 1

| # | Question | Where it gets answered |
|---|---|---|
| Q2 | Are the SCPI commands in `hardware.py` correct for that version? | H1.5 — acquisition and generator commands verified; `setup_am_generator` and the `ACQ:AXI:*` path still open |
| Q3b | Is the ASG's 16384-entry table size settable over SCPI? If so, exact 80/5/6 MHz returns and the frequency limitation in `SESSION_LOG.md` disappears. | Not yet probed |
| Q4 | Does `SOUR:TRig:INT` start both channels synchronously? | H2.4 |
| Q5 | Is Deep Memory Generation available on this OS? | H5.1 |

## Affects measurement quality

| # | Question | Notes |
|---|---|---|
| Q6 | Is the OUT1/OUT2 relative carrier phase repeatable? | **No — 71–82° spread, unexplained. DOWNGRADED, not blocking.** Edwin confirmed 2026-08-10 that **the deliverable is amplitude only**, and the intermodulation amplitude does not depend on the relative phase of the two envelopes. See `SESSION_LOG.md` for the one residual risk this leaves (a relative *drift* fast enough to offset the beat frequency) and how to check it. Do not spend time explaining the phase scatter unless phase becomes a deliverable again. |
| Q7 | Are IN1 and IN2 sample-aligned? | A fixed skew between signal and trigger biases every wavelength assignment. Measure, do not assume. |
| Q8 | What is the real noise floor at 1 MHz? | **Answered 2026-08-12 — see Resolved.** |
| Q9 | Does the DUT response roll off at 1 MHz? | Physics, not measurable in loopback. Lower difference frequencies are available — see `03-frequency-plan.md`. |

## Needs a human decision

| # | Question |
|---|---|
| Q11 | Photodetector output amplitude, to set input range and coupling. **H3.3 now gives the target to answer it against:** on the ±1 V range the noise floor is σ = 2.96 µV per trace point, so the intermodulation response needs ≥30 µV amplitude for SNR 10 and is invisible in a single sweep below ~3 µV. If the detector output fits in ±1 V, use that range — the ±20 V range is 14× worse in absolute volts (σ = 45 µV, needing ≥454 µV for SNR 10). |
| Q12 | Safe drive levels for the amplifier chain and AOMs — Phase 2 gate. |
| Q13 | Is averaging across repeated sweeps wanted? Changes buffer management and whether phase must stay coherent between sweeps. |
| Q14 | Is a GUI actually wanted, and what would it show? |
| Q15 | Output file format for the traces. Currently `.npz`. |

## Resolved

| # | Question | Answer |
|---|---|---|
| Q1 | Red Pitaya OS version | **2.00, build 37** (Ubuntu 22.04.4, kernel 5.15.0-xilinx, commit `a0457d3aa`). In `/opt/redpitaya/version.txt`; `/etc/redpitaya_version` does not exist on this image. |
| Q3 | Does the generator accept a 250-sample arbitrary buffer? | **No — and the question was based on a wrong model.** The ASG always traverses a fixed 16384-entry table; `SOUR:FREQ:FIX` sets the traversal rate, not a per-sample clock. A 50-sample buffer produces no output at all. |
| Q3a | Move the frequency plan onto the 15258.789 Hz grid? | **Yes, decided by Edwin 2026-08-10 and implemented.** Carrier 80.001831 MHz, f1 5.004883 MHz, f2 5.996704 MHz, difference **991.821 kHz**. The limitation this imposes is recorded in full in `SESSION_LOG.md` at his request — in particular, **do not hardcode 1e6 as the lock-in frequency.** |
| Q8 | What is the real noise floor at the lock-in frequency? | **45.6 nV/√Hz on IN1** at 991.821 kHz, giving **σ = 2.96 µV per quadrature** at the operating bandwidth (decimation 2, DC, ±1 V range, outputs off, loopback cables fitted — Edwin accepted the cable-on configuration rather than a 50 Ω terminator on 2026-08-12, as it is the wiring Phase 1 runs in). 2.96 ppm of full scale; repeatable to 0.2%, and measured directly off a 256 ms deep capture (a second, independent density-based route agreed to 6%). **A signal of ≥30 µV amplitude at the ADC gives SNR 10 on every trace point with no sweep averaging.** On the ±20 V range, σ = 45 µV (2.3 ppm of range). Two caveats that matter: the conversion from density to σ uses a noise gain of **4232.7 Hz, which is 1.88× the nominal 2250 Hz bandwidth**, not equal to it; and a switching-supply harmonic sits 17.9 kHz off the lock-in frequency, rejected by >200 dB today but only **1.77% of switcher drift** away from landing on it — where it would read as a **32 µV steady amplitude, 11× the noise floor and indistinguishable from a healthy real signal.** Full detail and the five things this does not cover are in `SESSION_LOG.md` 2026-08-12. |
| Q10 | τ = 30 µs or 71 µs? | **71 µs at 5000 points**, decided by Edwin 2026-08-10. Forcing 30 µs at 5000 points would fold 2805 Hz of noise onto every trace for 3.7 dB worse SNR, buying resolution a 5000-point grid cannot represent. The aliasing-free way to reach ~30 µs is 12500 points (τ = 28.3 µs); considered, not taken. Recorded in `01-project-spec.md`. |

## Deferred

| # | Question |
|---|---|
| Q16 | Does anything need continuous analog output of the demodulated signal? Only this would justify revisiting FPGA — see ADR-0001. |
| Q17 | Phase 2 success criteria. Deliberately not set until Phase 1 results are in. |
