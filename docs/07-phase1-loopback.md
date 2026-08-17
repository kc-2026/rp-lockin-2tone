# Phase 1 — loopback testing

**Status: COMPLETE, 2026-08-14.** Every step passed, except two that were
deliberately skipped and are marked as such (H6.1, and H5.2/H5.3).

**Loopback means coax cables from the board's outputs to its own inputs.** The
DUT, amplifiers, AOMs, photodetector and laser are not connected to anything
during Phase 1.

**Two failures are recorded here rather than hidden**, because "passed" and "we
decided it did not matter" are very different things to inherit:

- **H2.5 failed** — the OUT1/OUT2 relative phase is not repeatable. Downgraded
  by Kevin, because the deliverable is amplitude only. Its one surviving risk
  was later closed by H3.2.
- **H7.4 failed, then was fixed** — outputs used to stay on after a crash.

The numbers produced here are collected in `05-results.md`. What Phase 1 could
**not** reach is in `08-phase2-hardware.md`.

---

## How this was run

Phased, in order. Each step assumes the previous one passed — debugging H3 while
H1 is broken wastes a lot of time.

---

## The structural limit of loopback

**You cannot produce |f2 − f1| by combining two Red Pitaya outputs.**

Passive summing is linear. The difference frequency exists only because the DUT
is nonlinear — wiring OUT1 and OUT2 into a tee produces 80 MHz sidebands and
nothing at 1 MHz at all. Any test plan that assumes otherwise is broken.

So Phase 1 splits the problem:

- **Transmit** is verified by generating a drive waveform and looking at its
  spectrum on an input.
- **Receive** is verified by playing a *synthetic DUT output* — a waveform the
  board computes to be what the DUT would emit — and checking the recovered
  trace against the analytic ground truth (`rp_lockin.emulator`).

Together these cover everything except the DUT physics and the analog chain.

---

## Phase 1 — loopback

### H1 — transport validation

**Wiring:** none needed.

**This is the gate for everything else.** `src/rp_lockin/hardware.py` has never
been executed. Work through it method by method, confirming each SCPI command
against the board's actual OS version. Every method carries a `VERIFY:` note.

- [x] H1.1 Record the OS version into `docs/04-hardware-reference.md`.
      **Done 2026-08-12 — OS 2.00 build 37.**
- [x] H1.2 Connect, `*IDN?`, confirm it is a 250-12 and not a 125-14. A 125-14
      would make every frequency in this project wrong, silently.
      **Done 2026-08-12, but NOT via `*IDN?`, which carries no model name.**
      Confirmed by the board's label, by `monitor -f` → `z20_250`, and by
      measuring the sample rate. Amend this step's wording accordingly.
- [x] H1.3 Confirm the sample rate the board reports matches 250 MS/s.
      **Done 2026-08-12 by measurement.**
- [x] H1.4 Read `ACQ:AXI:START?` and `ACQ:AXI:SIZE?`. Record the region size.
      **Done — 2 MiB as shipped, enlarged to 128 MB on 2026-08-12.**
- [x] H1.5 Verify each command in `setup_generator`, `setup_am_generator`,
      `setup_acquisition`, `acquire`, `acquire_deep`, `acquire_deep_2ch`.
      Fix spellings in place; note every correction in `SESSION_LOG.md`.
      **Done. `setup_am_generator` needed rewriting, not respelling — the ASG
      model was wrong. `acquire_deep_2ch`'s SCPI read is broken and superseded
      by `acquire_deep_fast`.**
- [x] H1.6 Confirm binary block transfer (`ACQ:DATA:FORMAT BIN`) returns the
      expected sample count and a sane amplitude range.
      **Done 2026-08-12 — exactly 16384 int16 big-endian samples. The separate
      little-endian decode on the fast-read path was proven 2026-08-12.**

**Exit:** every method in `hardware.py` has been executed successfully at least
once, and its `VERIFY:` note either removed or replaced with a confirmation.

### H2 — transmit path

**Wiring:** OUT1 → IN1.

- [x] H2.1 Generate 80 MHz AM at 5 MHz. Confirm three spectral lines at 75, 80,
      85 MHz. **Done 2026-08-12 — all three lines exact, on the grid-snapped
      frequencies.**
- [x] H2.2 **Done 2026-08-12 — sideband/carrier ratios 0.512 and 0.488 against
      0.500 theoretical.** Repeat at a 20 MHz carrier. **This is the
      quantitative check** — the
      analog path is flat at 20 MHz, so sideband amplitudes and modulation
      depth are meaningful there. At 80 MHz the round trip is attenuated twice
      (output and input both roll off at 60 MHz), so only relative line
      positions are trustworthy.
- [x] H2.3 **Done 2026-08-12 — worst spur −48.5 dBc, no comb.** Confirm no
      wrap-glitch comb. Look for spurious content between
      100 kHz and 40 MHz; there should be essentially none. This is the test
      that catches an incommensurate buffer.
- [x] H2.4 Both channels generating at once, at f1 and f2. Confirm both are
      alive and that starting them is synchronous. **Done 2026-08-12 — both
      generate simultaneously, carrier magnitudes within 0.6%.**
- [x] H2.5 **DONE AND FAILED, then downgraded — not blocking.** The OUT1/OUT2
      relative carrier phase scatters over 71–82°, whether or not the
      generators are restarted, and is unexplained. **Kevin ruled on 2026-08-12
      that this does not block the project, because the deliverable is
      amplitude only and the intermodulation amplitude does not depend on the
      relative phase of the two drives.** One residual risk survives that
      ruling — a relative *drift*, as opposed to a constant offset — and the
      way to check it is recorded in `SESSION_LOG.md`. Do not reopen the phase
      scatter unless phase becomes a deliverable again.

### H3 — receive path

**Wiring:** OUT1 → IN1.

- [x] H3.1 Generate a plain tone at the lock-in frequency. Demodulate. Confirm
      recovered amplitude tracks the commanded amplitude linearly.
      **Done 2026-08-14 — linear over 2.4 decades (2 mV to 500 mV).** Above
      20 mV the recovered/commanded ratio sits in 0.9919–0.9951, a 0.3%
      spread. The full-range spread of 4.5% comes entirely from the 2 mV and
      5 mV points, and is the **generator's** amplitude resolution at small
      settings, not demodulator nonlinearity — noise cannot explain it, since
      the vector mean's noise at 2 mV is 0.3 µV against a 2036 µV signal.
      Amplitude taken as |mean(X + jY)|, not mean(R), which is biased upward.
- [x] H3.2 Confirm recovered phase is stable within a capture.
      **Done 2026-08-14 — 0.002° total excursion over 28 ms**, drift
      0.00003 Hz, R stable to 0.003% rms. That is the shared DAC/ADC clock
      behaving as `02-architecture.md` predicts.
      **Also closed the H2.5 residual risk, which needed a separate test.**
      H3.2 above measures one channel against the ADC; the risk was about the
      two channels against *each other*. Drove both at the same frequency and
      tracked OUT2−OUT1 across one capture: **drift 0.0024 Hz, excursion
      0.053° over 24 ms**, against a 2250 Hz bandwidth. The offset is a
      constant −113° that does not move. Same frequency on both channels is
      what makes this valid — a common capture-start offset then cancels
      exactly, which is the trap that made the earlier envelope-based
      measurement worthless.
- [x] H3.3 Measure the noise floor with the output off and the input
      terminated. Convert to an equivalent input noise density. Record it —
      this is the number that predicts whether the real measurement will work.
      **Done 2026-08-12, then revised TWICE. Use these numbers:
      51.7 nV/√Hz on IN1 at 991.821 kHz → σ = 3.57 µV per quadrature; ≥36 µV of
      signal gives SNR 10 per trace point.**

      | Configuration | Density | σ per quadrature | For SNR 10 |
      |---|---:|---:|---:|
      | 50 Ω terminated — board's own floor | 34.6 nV/√Hz | 2.39 µV | 24 µV |
      | **Loopback cable, output off — plan with this** | **51.7** | **3.57** | **36 µV** |

      **The cable adds ~50%**, and that is pickup, not artefact. The real input
      is a longer cable from a photodetector in a noisier place, so 34.6 is a
      floor the real system will never see and 24 µV is an unreachable best
      case. **Hand 36 µV to whoever answers Q11.**

      Two supersessions, both worth knowing about:
      **(1)** the original 45.6 nV/√Hz → 2.96 µV was **~15% optimistic** — an
      independent re-measurement from a fresh capture, by two routes agreeing
      with each other to 6%, gave 51.7 → 3.57. The gap is real, not statistical
      (σ from 392 output points carries only ~4% uncertainty); cause unresolved,
      candidates being record length, the inherited 1817.7 counts/V calibration,
      or conditions on the day. **Use the pessimistic figure.**
      **(2)** the input carried the loopback cable with the output commanded
      off, not a terminator — Kevin accepted that on 2026-08-12 as the wiring
      Phase 1 runs in, and the terminated measurement above later quantified
      what that choice costs.

      **The noise gain is NOT the nominal bandwidth** — 4763 Hz measured against
      2250 Hz nominal. Predicting σ from the −3 dB bandwidth gives 2.45 µV
      against 3.57 measured, 46% low, in the dangerous direction.

      Also found a switching-supply spur family at 504.868 kHz, ~32 µV per line,
      harmless at its present frequency but a real hazard if it drifts, and
      **partly conducted** so cabling alone cannot remove it — see
      `04-hardware-reference.md`.
- [x] H3.4 Confirm the √bandwidth law holds on real data, not just synthetic:
      halving the bandwidth should drop the noise by √2. **Done 2026-08-12 —
      holds to 2–4% across a factor of 8 in bandwidth, on one real capture.**
      σ tracks √ENBW to ~1.5%, better than it tracks √(nominal bandwidth),
      because the ENBW/bandwidth ratio drifts slightly with bandwidth. Scale by
      √ENBW if you need the noise at some other setting.
- [x] **H3.5 PASSES 2026-08-14, both halves.** On the board: drove OUT1 at
      f_lockin + delta and demodulated at f_lockin. **Over the seven
      offsets above the noise floor, the worst disagreement with the
      designed filter response is 0.0 dB** — including −12.1 dB measured
      against −12.0 dB predicted at the 2250 Hz nominal bandwidth.
      Offsets past 2500 Hz are **lower bounds, not measurements**: a 0.5 V
      drive against the 3.57 µV floor gives 102 dB of range, and the
      residual 6.7–11 µV is what complex-Gaussian noise produces.
      Turned up a calibration discrepancy — see **Q23**.
- [x] H3.5 (original wording) Deliberately offset the demodulation frequency by a few kHz and
      confirm the response falls off as the filter predicts. **Offline half done
      2026-08-12** (rejection table in `SESSION_LOG.md`: −12 dB at the nominal
      2250 Hz bandwidth, −124 dB by 3 kHz, −204 dB at 19 kHz). Still to do on
      the board.

### H4 — trigger digitisation

**Wiring:** OUT2 → IN2 (H4.3 additionally needs OUT1 through a BNC tee).

**All four steps PASS.** Read the scope note first — it changes which of them
still matters.

#### Scope reduced 2026-08-14 (Kevin)

The wavelength axis now comes from the Santec laser's own serial report of
wavelength against time, not from the intervals between trigger edges. The
trigger output's only job is to **align the sweep with the capture**.

What that changes:

- **H4.4 is now the load-bearing test**, and it passes. Triggering the
  acquisition from IN2 and knowing where the trigger sits in the record is
  exactly and only what the new scheme needs.
- **H4.1 and H4.2 are no longer critical.** Recovering a long train of intervals
  to sub-nanosecond precision was in service of a calibration that no longer
  exists. The results stand and are kept — they are good evidence the input path
  and edge finder work — but nothing is gated on them.
- **H4.3 still matters**, though less. A skew between IN1 and IN2 would offset
  the signal against the trigger instant, and so shift the whole trace in time
  relative to the sweep. It is 0.0005 samples, so this is settled either way.
- **The decimation-8 missed-edge problem largely dissolves.** Detecting one
  sweep-start edge is not the same task as recovering thousands of intervals
  without losing any. See the decimation note in `04-hardware-reference.md`.

**Confirmed 2026-08-14 (Kevin):** the Santec triggers at set **time** steps, so
IN2 does carry a periodic pulse train — but **only the first edge is used**, to
synchronise the laser and the board. Alignment depends on one edge, not on
recovering the train intact, so the paragraphs above hold and the missed-edge
question is closed for alignment purposes.

**Do not discard the rest of the train.** It is recorded anyway, and because the
pulses are evenly spaced in time it is a direct measurement of how the laser's
clock compares to the board's: fit a line through the recorded edge times and
compare the slope against the laser's nominal step. That turns U11 from an
assumption into a per-sweep check, for free, from data already captured. A few
missing edges do not disturb a slope fit through hundreds of them, and a missed
edge is visible as a double-length gap.

**The one way this still fails silently — see Q21.** The laser reports wavelength
against time *from its own first trigger*, and the board defines t = 0 from *its*
first trigger. If the acquisition arms late and latches the second pulse instead
of the first, every wavelength is off by exactly one time step and **the trace
looks entirely normal** — same shape, wrong labels. Arm before the sweep starts
and use pre-roll, then cross-check the pulse count in the record against the
length of the laser's table.

#### The steps, and what each found

- [x] **H4.1 — play a known edge pattern via `make_trigger_sequence`, recover it
      with `find_trigger_edges`, and confirm intervals to within a sample or
      two. PASSES, comfortably.** Played a six-edge pattern from the ASG table
      and recovered it on IN2. 733 edges over 122.1 table repeats (expected
      732). All six designed intervals recovered, **zero of 732 intervals failed
      to match a designed value**. Worst mean error 0.1 ns = **0.007 samples**,
      far inside the "sample or two" this step asks for.
- [x] **H4.2 — establish the timing resolution at the intended decimation and
      confirm it is adequate for the wavelength calibration. Result: 0.01 ns rms
      (0.002 samples)** at decimation 2, where the sample period is 8 ns. Over a
      1 s sweep that is 0.01 ppb.
      **Do not read this as the resolution the real system will achieve.**
      Everything here shares one clock — the ASG steps one table entry per DAC
      tick and the ADC samples at exactly half that — so edges land at
      perfectly reproducible positions. The real laser trigger is asynchronous
      to the board and will bring its own jitter and slower, noisier edges.
      This measures the *instrument's* contribution, which is negligible. The
      real limit is U7 on the untestable list.
- [x] **H4.3 — confirm IN1 and IN2 are sample-aligned**, since a fixed skew
      between the signal and trigger channels would bias every wavelength
      assignment. **PASSES — the inputs are aligned to 0.004 ns = 0.0005
      samples**, 2000× finer than one sample, repeatable to 0.002 ns across five
      frequencies (1–20 MHz) and three captures each. **Q7 answered: no
      correction needed, and channel skew biases nothing.**
      Measured with OUT1 → BNC tee → two matched cables → IN1 and IN2, so both
      inputs saw literally the same signal. Several frequencies on purpose: a
      fixed time skew gives phase proportional to frequency, a constant offset
      does not, so the slope separates them. Slope gives −0.0042 ns with a
      −0.046° intercept and 0.04° residual rms.
      Secondary observation, not a timing issue: **the two inputs have slightly
      different frequency responses.** At 20 MHz IN2 reads 200 counts against
      IN1's 237, a 16% difference, versus ~1% at 1 MHz — IN2 rolls off sooner.
      Irrelevant at the 991.8 kHz operating point, and it does not affect edge
      timing, which threshold interpolation handles. Worth knowing if anyone
      ever compares absolute amplitudes between the two channels.
- [x] **H4.4 — confirm triggering the acquisition from IN2 works, and determine
      where the trigger lands in the record. DONE.** `ACQ:TRig CH2_PE` with
      `ACQ:TRig:LEV 0.1` triggers the acquisition from IN2. With the level set
      to 2.0 V, above the 0.5 V signal, it correctly does **not** fire and
      `wait_until` raises cleanly instead of hanging — which also covers
      **H7.2**'s failure mode.
      **Where the trigger lands is now known.**
      `ACQ:AXI:SOUR<n>:Trig:Pos?` returns the trigger's sample index. It reads
      0x7F800000 only when no trigger has occurred, which is why an earlier
      pass — taken idle and after `ACQ:TRig NOW` — wrongly concluded it was
      broken. Validated by reading a known distance before it: across four
      captures with different positions, the rising edge appeared at exactly
      the expected offset each time. It sits a fixed **1.14 samples (9.1 ns)
      after** the true threshold crossing, reproducible to 0.00 samples;
      subtract it only if the absolute instant matters.
      Note the DMA ring is already running when the trigger fires, so **buffer
      offset 0 is not the trigger instant** — it is wherever the write pointer
      happened to be. Reads must be referenced to `Trig:Pos`, which
      `acquire_deep_fast` now does.
      **H6.4 is unblocked.** `acquire_deep_fast(trigger="CH2_PE",
      preroll_samples=...)` delivers pre-trigger data, verified at 5k, 25k and
      100k samples of pre-roll: the rising edge lands at the requested offset
      each time and the pre-roll region carries the same rms as the rest of the
      record, so it is real signal rather than leftovers. The 22 ms of filter
      settling H6.4 needs is 2.75 M samples at decimation 2, comfortably
      within the region.

### H5 — long waveform generation

The emulated-DUT test at full sweep length needs a waveform longer than the
16384-sample arbitrary buffer, which means Deep Memory Generation.

- [x] **H5.1 ANSWERED 2026-08-14: DMG is NOT available.** All nine candidate
      spellings (`SOUR<n>:AXI:*`, `SOUR:AXI:*`, `SOUR<n>:DMG?`,
      `SOUR<n>:TRAC:DATA:AXI?`, `SOUR<n>:TRAC:DATA:LEN?`) return zero bytes.
      Confirmed behaviourally as well: loading a 32768-entry table **closes the
      SCPI connection** — the server does not reject an oversized write, it
      drops the socket. **Do not send more than 16384 points.** The unique
      waveform ceiling is 65.536 µs and is permanent.
      Outputs were verified off after the crash; the reconnect found 0/0.
- [ ] H5.2 Play a 60 ms emulated DUT response and recover it. Compare against
      ground truth; expect agreement to a few percent.
- [ ] H5.3 Scale up as memory allows. Record the maximum achievable.
- [ ] H5.4 If DMG proves unavailable, fall back to short emulated sweeps and
      record the limitation. The physics validation still holds; only the
      duration is reduced.

### H6 — full-length capture

**Wiring:** OUT1 → IN1, OUT2 → IN2.

- [ ] H6.1 Enlarge the reserved DMA region to 512 MB, **based at `0x20000000`,
      not at `0x1000000`** (`docs/04-hardware-reference.md`). The board has 1 GB but
      Linux is capped to the lower half by `mem=512M`; basing the region in the
      upper half costs the OS nothing, whereas the original instruction ran a
      512 MB region from the 16 MB mark straight through Linux's own memory.
      Back up `dtraw.dts` first. Reboot. Confirm `ACQ:AXI:SIZE?`.
- [x] **H6.2 PASSES 2026-08-14**, at decimation 8 rather than 2 — see the
      decimation note in `04-hardware-reference.md`; decimation 2 does not fit
      the 128 MiB region and the move to buy it was rejected.
      32,812,500 samples on each channel, exactly as requested, both
      carrying signal. 125.2 MB, **97.8% of the region.**
      **Transfer is far slower than the single-channel figure suggests:**
      6.7–11.2 s for 125 MB including arming and the 1 s capture, so
      11–19 MB/s against the 87 MB/s measured on a 64 MB single-channel
      read. The 1 MB chunking added to `rp_fastread.py` after it was
      killed by a 50 MB request means ~125 round trips, and at ~50 ms each
      that is most of the difference. A robustness-for-speed trade that
      was worth making; larger chunks would recover most of it if a sweep
      ever needs to be faster.
- [x] **H6.3 PASSES 2026-08-14 — exactly 5000 points**, spanning +0.1 ms to
      999.9 ms about the trigger, at **exactly 200.000 µs spacing with zero
      measurable jitter**, first point 100 µs after the trigger.
      **It failed the first time, at 4943 points, and the reason is a real
      constraint that was not written down anywhere.** A 1 s sweep with
      45 ms of pre-roll, stopping at exactly trigger + 1 s, comes up 57
      points short — with no error, and a trace that looks perfectly
      healthy and merely ends early. `LockinResult.t` compensates the
      filter's GROUP DELAY as well as trimming its settling, so the valid
      window is **shifted**, not just shortened, and the usable span runs
      out about half the settling length before the record does. 57 points
      against 113 trimmed.
      **The record must bracket the sweep on both sides:** settling before
      it, and about half the settling after it. `planning.recommended_tail()`
      now returns that, alongside `recommended_preroll()`. Re-running with
      30 ms of pre-roll and a 20 ms tail gave exactly 5000.
      **Watch the memory.** The recommended pre-roll (45.2 ms) plus tail
      (16.9 ms) plus a 1 s sweep at decimation 8 is **98.9% of the
      128 MiB region**. It fits, with essentially nothing to spare.
- [x] **H6.4 PASSES 2026-08-14.** Compared two captures of the same constant
      signal, triggered from IN2:

      | | Trace starts | Result |
      |---|---|---|
      | no pre-roll | 10.8 ms **after** the trigger | 1.1% of the sweep lost |
      | 43.2 ms pre-roll | 32.4 ms **before** the trigger | fully covered |

      The pre-roll region reads as real signal (1.0 × steady, versus ~0 for
      unwritten memory), so it is genuine pre-trigger data.

      **Correction to the wording above: without pre-roll the start of the
      sweep is ABSENT, not garbage.** `demodulate()` trims the settling
      transient internally, so it never reaches the output — the trace simply
      does not begin until the filter is valid. Nothing looks wrong; the trace
      is just short at the front, and only the time axis reveals it. Arguably
      easier to miss than corruption would be.

      Two defects in `acquire_deep_fast` were found and fixed getting here:
      **(1)** the DMA must be given time to accumulate history before the
      trigger is armed — a trigger firing immediately after `ACQ:START` leaves
      nothing behind it, and the "pre-roll" reads back as near-silence, which
      looks like a dead input rather than a sequencing error;
      **(2)** reads must be referenced to `Trig:Pos` whenever there is a real
      trigger, not only when pre-roll is requested — reading from offset 0
      after a real trigger returns an arbitrary point in the ring, which looks
      entirely plausible and silently misplaces every event in the record.
- [x] **H6.5 PASSES 2026-08-14 — the Phase 1 exit criterion is met.**
      Both channels captured together for a full second at decimation 8,
      triggered from the trigger train on IN2, with 45.2 ms of pre-roll.

      | Result | |
      |---|---|
      | Amplitude, 7 levels over a 7.5× range | all within 1%, spread **0.34%** |
      | Relative timing of transitions | **0.2%** error |
      | Trace coverage | −33.9 to +943.3 ms about the trigger — covers the sweep from t=0 |
      | Channel alignment | `Trig:Pos` identical on both (4706/4706) |

      The consistent 0.8% under-read matches H3.1's independent figure.

      The DUT response is emulated by stepping the generator's amplitude during
      the capture rather than by a synthesised waveform, because DMG does not
      exist (H5.1). Eight levels rather than 5000 smooth points — coarser than
      intended, but it exercises the full chain end to end.

      **CAVEAT, and it matters for Phase 2: trigger edge recovery degrades at
      decimation 8.** 1.17% of intervals failed to match, rms 3.24 µs, against
      0.01 ns at decimation 2 (H4.2). At decimation 8 the sample period is
      32 ns and the test edges rise in 20 ns, so an edge often has no sample on
      its ramp and the interpolation has nothing to work with. Missed edges
      corrupt the mapping rather than blurring it.
      The signal path and the trigger path want opposite decimations, and
      `ACQ:AXI:DEC` is global — one setting serves both. **Establish the laser
      trigger's real edge rate (U7) before committing to a decimation.**
      Counter-intuitively a *slower* trigger edge is easier to time here, since
      it puts more samples on the ramp.

### H7 — robustness

- [x] **H7.1 PASSES 2026-08-14.** Twenty full-second two-channel captures
      at decimation 8, triggered with 45 ms pre-roll. **20/20 succeeded.**
      **Amplitude reproduces to 0.0029% rms**; the first trigger edge lands
      at the same point in the record to **6 ns rms** (range 19 ns, well
      inside one 32 ns sample). Drive held constant rather than stepped as
      H6.5 did, to separate sweep-to-sweep variation from within-sweep
      structure. Phase is not a deliverable (see `01-overview.md`) so
      it is not quantified here; H3.2 covers phase stability.
      `Trig:Pos` scatters by 2.6 ms and that is expected — the trigger fires
      wherever the DMA ring pointer sits, which is why reads reference it
      rather than the region base.
      **Edge count was 122071 on every run, zero variance, zero missing —
      2.4 M edges at decimation 8 with no losses.** That sits badly with
      H6.5's 1.17% and is discussed under H6.5 and in `SESSION_LOG.md`.
- [x] **H7.2 PASSES 2026-08-14.** Armed on CH2_PE at 2.0 V with outputs
      off. Raised `TimeoutError` after 8.7 s against an 8 s budget, naming
      the trigger source. **It does not hang.**
      **The first attempt left the board unusable, which was a real defect
      and is now fixed.** `acquire_deep_fast`'s cleanup only wrapped the
      read, so a trigger that never arrived raised from above it and left
      `ACQ:START` active with both channels enabled. **A board left armed
      that way stops answering SCPI entirely** — TCP still accepts, so it
      looks like a dead cable or a hung PC, and recovery needs the SCPI
      server restarted by hand. Cleanup now spans arming through reading.
- [x] **H7.3 PASSES 2026-08-14, all three stages**, run last and staged from
      harmless to risky so earlier results were banked first.
      **A — SCPI socket gone:** raises `OSError` in 0.000 s, no hang.
      **B — fast-read helper absent:** raises `ConnectionError` naming the
      cause, before anything is armed.
      **C — helper killed MID-TRANSFER**, 0.8 s into a 57 MB read: raises
      `ConnectionError` after 17.7 s. Slow, but it fails rather than hangs.
      **The board was healthy after every stage, outputs off.** That is the
      part that matters, and it is the widened cleanup from H7.2 doing its
      job — before that fix, stage C would very likely have left the
      capture armed and the SCPI server wedged.
      Not covered: physically unplugging the Ethernet, which needs a human.
      Its software-visible behaviour is stage A.
- [x] **H7.4 FAILED 2026-08-14, then was fixed and passes.**
      `close()` only shut the socket, so **an unhandled exception anywhere
      in a measurement script left the generator driving indefinitely.**
      Confirmed on hardware: `OUTPUT1:STATE?` still read `1` after a
      simulated crash inside a `with` block.
      `tests/hardware/conftest.py` disarms outputs for the hardware suite,
      which is exactly why this survived — the gap only showed in ad-hoc
      scripts, which is where most measuring here actually happens.
      `close()` now disarms both outputs first, best-effort and never
      raising, since it usually runs while an exception is already
      propagating. `close(disable_outputs=False)` opts out. Five offline
      tests in `tests/test_hardware_safety.py` pin it.

---
