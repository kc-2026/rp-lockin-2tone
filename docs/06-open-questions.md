# Open questions

Resolve these as they come up. When one is settled, move the answer into the
relevant doc and note it in `SESSION_LOG.md`.

## Blocking Phase 1

| # | Question | Where it gets answered |
|---|---|---|
| Q2 | Are the SCPI commands in `hardware.py` correct for that version? | H1.5 — acquisition and generator commands verified; `setup_am_generator` and the `ACQ:AXI:*` path still open |
| Q3b | Is the ASG's 16384-entry table size settable over SCPI? If so, exact 80/5/6 MHz returns and the frequency limitation in `SESSION_LOG.md` disappears. | Not yet probed |
| Q4 | Does `SOUR:TRig:INT` start both channels synchronously? | H2.4 |
| Q5 | Is Deep Memory Generation available on this OS? | **NO — answered 2026-08-14.** All nine candidate SCPI spellings return zero bytes, and sending a 32768-entry table **closes the SCPI connection outright**. The generator's unique-waveform ceiling is 16384 samples = 65.536 µs, permanently. H5.4's fallback applies. |

## Affects measurement quality

| # | Question | Notes |
|---|---|---|
| Q6 | Is the OUT1/OUT2 relative carrier phase repeatable? | **CLOSED 2026-08-14.** The offset is random at start (71–82° across restarts) but **constant within a run** — measured drift 0.0024 Hz, excursion 0.053° over 24 ms, against a 2250 Hz bandwidth. A constant offset does not affect R, and the deliverable is amplitude only (Kevin, 2026-08-12). The residual drift risk that survived that ruling is now measured and dead. Do not reopen unless phase becomes a deliverable. |
| Q7 | Are IN1 and IN2 sample-aligned? | **YES — answered 2026-08-14. Aligned to 0.004 ns = 0.0005 samples**, repeatable to 0.002 ns over 1–20 MHz. No correction needed; channel skew biases nothing. Measured properly, with OUT1 split through a BNC tee into both inputs, which is the only wiring that separates input skew from output skew and from the ASG's random start phase. See H4.3. |
| Q8 | What is the real noise floor at 1 MHz? | **Answered 2026-08-12 — see Resolved.** |
| Q9 | Does the DUT response roll off at 1 MHz? | Physics, not measurable in loopback. Lower difference frequencies are available — see `03-frequency-plan.md`. |

## Needs a human decision

| # | Question |
|---|---|
| Q11 | Photodetector output amplitude, to set input range and coupling. **H3.3 now gives the target to answer it against:** on the ±1 V range the noise floor is σ = 3.57 µV per trace point, so the intermodulation response needs ≥36 µV amplitude for SNR 10 and is invisible in a single sweep below ~4 µV. If the detector output fits in ±1 V, use that range — the ±20 V range is 14× worse in absolute volts (σ = 45 µV, needing ≥454 µV for SNR 10). |
| Q12 | Safe drive levels for the amplifier chain and AOMs — Phase 2 gate. |
| Q13 | Is averaging across repeated sweeps wanted? Changes buffer management and whether phase must stay coherent between sweeps. |
| Q18 | **ANSWERED 2026-08-14 (Kevin): the Santec triggers at set TIME steps, and only the FIRST edge is used** — to synchronise the laser and the Red Pitaya. So IN2 carries a periodic pulse train, but the alignment depends on one edge, not on recovering the train intact. **The missed-edge question is therefore closed for alignment purposes**, and with it the case for the memory move. But see Q21 — "the first edge" has to mean the same edge on both sides, and that is not automatic. |
| Q19 | **ANSWERED 2026-08-14 (Kevin): closely synchronised already, and an external timebase can be attached if needed.** Worth knowing that it need not be taken on trust: because the trigger fires at **fixed time steps** (Q18), the recorded train is a direct measurement of the two clocks' ratio — fit a line through the recorded edge times and compare the slope against the laser's nominal step. **This converts U11 from an assumption into a per-sweep measurement, using data already captured, for free.** Recommended even with an external timebase fitted, as a check that it is actually working. |
| Q20 | **ANSWERED 2026-08-14 (Kevin): the laser reports wavelength against RELATIVE TIME FROM THE FIRST TRIGGER.** That is the same origin the Red Pitaya uses, so the mapping is direct: find the first trigger edge in the record, call it t = 0, and look the wavelength up against the laser's table. No sweep-rate assumption and no step-index arithmetic. Still needed before writing the driver: the serial command set, port settings, and whether the table streams live or is dumped after the sweep. **No driver exists yet.** |
| Q22 | **What is the TSL-770/775 serial command set, and do the two models differ?** Needed before any transport code can be written. Also: port settings, and whether the wavelength table streams live during the sweep or is dumped afterwards — that decides whether the driver runs alongside the capture or after it. **Do not guess these**; a misspelled command returns zero bytes exactly like a correct one, and this is the one subsystem whose silent failure is invisible in the output. Raised 2026-08-14. |
| Q21 | **NEW, and the one that can silently ruin a sweep: is the Red Pitaya's "first trigger" the same edge as the laser's?** Both sides define t = 0 as the first trigger, but they define it independently. If the acquisition arms late and latches the *second* pulse, every wavelength is offset by exactly one time step and **nothing in the trace looks wrong** — the shape is identical, just mislabelled. Mitigations, both cheap: arm the capture before the sweep starts and use pre-roll (H6.4 proved this works), and cross-check the number of pulses in the record against the length of the laser's table. Raised 2026-08-14. |
| Q14 | Is a GUI actually wanted, and what would it show? |
| Q15 | Output file format for the traces. Currently `.npz`. |

## Resolved

| # | Question | Answer |
|---|---|---|
| Q1 | Red Pitaya OS version | **2.00, build 37** (Ubuntu 22.04.4, kernel 5.15.0-xilinx, commit `a0457d3aa`). In `/opt/redpitaya/version.txt`; `/etc/redpitaya_version` does not exist on this image. |
| Q3 | Does the generator accept a 250-sample arbitrary buffer? | **No — and the question was based on a wrong model.** The ASG always traverses a fixed 16384-entry table; `SOUR:FREQ:FIX` sets the traversal rate, not a per-sample clock. A 50-sample buffer produces no output at all. |
| Q3a | Move the frequency plan onto the 15258.789 Hz grid? | **Yes, decided by Kevin 2026-08-12 and implemented.** Carrier 80.001831 MHz, f1 5.004883 MHz, f2 5.996704 MHz, difference **991.821 kHz**. The limitation this imposes is recorded in full in `SESSION_LOG.md` at his request — in particular, **do not hardcode 1e6 as the lock-in frequency.** |
| Q8 | What is the real noise floor at the lock-in frequency? | **51.7 nV/√Hz on IN1** at 991.821 kHz, giving **σ = 3.57 µV per quadrature** at the operating bandwidth (decimation 2, DC, ±1 V range, outputs off, loopback cables fitted — Kevin accepted the cable-on configuration rather than a 50 Ω terminator on 2026-08-12, as it is the wiring Phase 1 runs in). 3.57 ppm of full scale. **Revised twice from an original 2.96 µV, which was ~15% optimistic** — re-measured independently by two mutually agreeing routes, and separately with 50 Ω terminators, which showed the loopback **cable adds ~50%** to the floor (terminated: 34.6 nV/√Hz, 2.39 µV). **A signal of ≥36 µV amplitude at the ADC gives SNR 10 on every trace point with no sweep averaging**; 24 µV is the unreachable terminated best case, and the real cable from a photodetector will be worse than ours, not better. On the ±20 V range, σ = 45 µV (2.3 ppm of range). Two caveats that matter: the conversion from density to σ uses a noise gain of **4232.7 Hz, which is 1.88× the nominal 2250 Hz bandwidth**, not equal to it; and a switching-supply harmonic sits 17.9 kHz off the lock-in frequency, rejected by >200 dB today but only **1.77% of switcher drift** away from landing on it — where it would read as a **32 µV steady amplitude, 11× the noise floor and indistinguishable from a healthy real signal.** Full detail and the five things this does not cover are in `SESSION_LOG.md` 2026-08-12. |
| Q10 | τ = 30 µs or 71 µs? | **71 µs at 5000 points**, decided by Kevin 2026-08-12. Forcing 30 µs at 5000 points would fold 2805 Hz of noise onto every trace for 3.7 dB worse SNR, buying resolution a 5000-point grid cannot represent. The aliasing-free way to reach ~30 µs is 12500 points (τ = 28.3 µs); considered, not taken. Recorded in `01-project-spec.md`. |

## Deferred

| # | Question |
|---|---|
| Q16 | Does anything need continuous analog output of the demodulated signal? Only this would justify revisiting FPGA — see ADR-0001. |
| Q17 | Phase 2 success criteria. Deliberately not set until Phase 1 results are in. |
