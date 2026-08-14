# Test plan

Phased. Run in order. Each phase assumes the previous one passed — debugging
H3 while H1 is broken wastes a lot of time.

Loopback means **coax cables from the board's outputs to its own inputs**. The
DUT, amplifiers, AOMs, photodetector and laser are not connected to anything
during Phase 1.

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

## Phase 0 — offline (COMPLETE)

`pytest` — 62 tests, no hardware. Must stay green.

Covers: demodulation accuracy, noise scaling, filter settling, streaming block
equality, time-axis correctness, waveform commensurability, capture planning,
emulator round-trip against ground truth, trigger edge recovery.

---

## Phase 1 — loopback

### H1 — transport validation

**Wiring:** none needed.

**This is the gate for everything else.** `src/rp_lockin/hardware.py` has never
been executed. Work through it method by method, confirming each SCPI command
against the board's actual OS version. Every method carries a `VERIFY:` note.

- [x] H1.1 Record the OS version into `docs/05-hardware-notes.md`.
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
      **Done 2026-08-12: 45.6 nV/√Hz on IN1 at 991.821 kHz → σ = 2.96 µV per
      quadrature at the operating bandwidth; ≥30 µV of signal gives SNR 10 per
      trace point.** Measured directly off a 256 ms deep capture, and
      independently via a density route that agreed to 6%. One departure from
      the wording above: the input carried the **loopback cable with the output
      commanded off**, not a 50 Ω terminator — **Kevin accepted this as the
      operative configuration on 2026-08-12**, on the grounds that it is the
      wiring the rest of Phase 1 runs in. Also found a switching-supply spur
      family at 504.868 kHz, ~32 µV per line, harmless at its present frequency
      but a real hazard if it drifts — see `05-hardware-notes.md`.
- [x] H3.4 Confirm the √bandwidth law holds on real data, not just synthetic:
      halving the bandwidth should drop the noise by √2. **Done 2026-08-12 —
      holds to 2–4% across a factor of 8 in bandwidth, on one real capture.**
      σ tracks √ENBW to ~1.5%, better than it tracks √(nominal bandwidth),
      because the ENBW/bandwidth ratio drifts slightly with bandwidth. Scale by
      √ENBW if you need the noise at some other setting.
- [~] H3.5 Deliberately offset the demodulation frequency by a few kHz and
      confirm the response falls off as the filter predicts. **Offline half done
      2026-08-12** (rejection table in `SESSION_LOG.md`: −12 dB at the nominal
      2250 Hz bandwidth, −124 dB by 3 kHz, −204 dB at 19 kHz). Still to do on
      the board.

### H4 — trigger digitisation — H4.1, H4.2, H4.4 done 2026-08-14

- [x] **H4.1 PASSES, comfortably.** Played a six-edge pattern from the ASG
      table and recovered it on IN2. 733 edges over 122.1 table repeats
      (expected 732). All six designed intervals recovered, **zero of 732
      intervals failed to match a designed value**. Worst mean error 0.1 ns =
      **0.007 samples**, far inside the "sample or two" this step asks for.
- [x] **H4.2 timing resolution: 0.01 ns rms (0.002 samples)** at decimation 2,
      where the sample period is 8 ns. Over a 1 s sweep that is 0.01 ppb.
      **Do not read this as the resolution the real system will achieve.**
      Everything here shares one clock — the ASG steps one table entry per DAC
      tick and the ADC samples at exactly half that — so edges land at
      perfectly reproducible positions. The real laser trigger is asynchronous
      to the board and will bring its own jitter and slower, noisier edges.
      This measures the *instrument's* contribution, which is negligible. The
      real limit is U7 on the untestable list.
- [ ] **H4.3 NOT DONE — needs hardware we do not have.** Confirming IN1 and
      IN2 are sample-aligned requires ONE source split to BOTH inputs, i.e. a
      BNC tee. Driving OUT1→IN1 and OUT2→IN2 cannot separate input skew from
      output skew or from the ASG's random start phase — they are degenerate.
      **Ask Kevin for a BNC tee and a short matched pair of cables.**
- [x] **H4.4 PARTIAL.** `ACQ:TRig CH2_PE` with `ACQ:TRig:LEV 0.1` does trigger
      the acquisition from IN2 — confirmed. And with the level set to 2.0 V,
      above the 0.5 V signal, it correctly does **not** fire and `wait_until`
      raises cleanly instead of hanging (which also covers H7.2's failure
      mode).
      **But where the trigger lands in the record is UNRESOLVED, and this
      blocks H6.4.** The first edge in the record was 9.71 µs in and falling;
      its interval signature identifies it as the pattern's 41 µs edge, so the
      record starts at table-time 31.3 µs while the rising edge that fired the
      trigger was at 25 µs. In other words the DMA ring was already running and
      **buffer offset 0 is not the trigger instant** — it is wherever the write
      pointer happened to be. `ACQ:AXI:SOUR<n>:Trig:Pos?` exists to resolve
      this and returns 0x7F800000, the float bit pattern for infinity.
      Two ways forward, in preference order: find a working spelling or method
      for the trigger position, or locate everything from the IN2 edge pattern
      itself — the wavelength calibration already derives from recorded edges
      rather than from the acquisition trigger, so this may be sufficient. The
      ring wrap still has to be unwrapped either way, which needs the write
      pointer.

### H4 — trigger digitisation (original wording)

**Wiring:** OUT2 → IN2.

- [ ] H4.1 Play a known edge pattern via `make_trigger_sequence`. Recover it
      with `find_trigger_edges`. Confirm intervals to within a sample or two.
- [ ] H4.2 Establish timing resolution at the intended decimation and confirm
      it is adequate for the wavelength calibration.
- [ ] H4.3 Confirm IN1 and IN2 are sample-aligned — a fixed skew between the
      signal and trigger channels would bias every wavelength assignment.
      **This is worth measuring explicitly, not assuming.**
- [ ] H4.4 Confirm triggering the acquisition from IN2 works, and determine
      where the trigger lands in the record.

### H5 — long waveform generation

The emulated-DUT test at full sweep length needs a waveform longer than the
16384-sample arbitrary buffer, which means Deep Memory Generation.

- [ ] H5.1 Establish whether DMG is available on this OS version and what its
      SCPI interface is.
- [ ] H5.2 Play a 60 ms emulated DUT response and recover it. Compare against
      ground truth; expect agreement to a few percent.
- [ ] H5.3 Scale up as memory allows. Record the maximum achievable.
- [ ] H5.4 If DMG proves unavailable, fall back to short emulated sweeps and
      record the limitation. The physics validation still holds; only the
      duration is reduced.

### H6 — full-length capture

**Wiring:** OUT1 → IN1, OUT2 → IN2.

- [ ] H6.1 Enlarge the reserved DMA region to 512 MB, **based at `0x20000000`,
      not at `0x1000000`** (`docs/05-hardware-notes.md`). The board has 1 GB but
      Linux is capped to the lower half by `mem=512M`; basing the region in the
      upper half costs the OS nothing, whereas the original instruction ran a
      512 MB region from the 16 MB mark straight through Linux's own memory.
      Back up `dtraw.dts` first. Reboot. Confirm `ACQ:AXI:SIZE?`.
- [ ] H6.2 Capture 1 s on both channels at decimation 2. Confirm the sample
      count and measure the transfer time.
- [ ] H6.3 Demodulate to exactly 5000 points. Confirm the count and that the
      time axis spans the sweep correctly.
- [ ] H6.4 **Verify the pre-roll works.** Filter settling costs ~108 output
      points (22 ms). Confirm that placing the trigger inside the record, with
      pre-trigger data ahead of it, yields a trace that is already settled when
      the sweep begins. Without this the first 2% of every sweep is garbage.
- [ ] H6.5 End-to-end: emulated DUT response plus emulated trigger train,
      captured together, demodulated, and mapped onto a time axis using the
      recovered trigger edges. Compare against ground truth. **This is the
      Phase 1 exit criterion.**

### H7 — robustness

- [ ] H7.1 Repeat H6.5 twenty times. Quantify sweep-to-sweep repeatability of
      amplitude, phase and timing.
- [ ] H7.2 Confirm behaviour when the trigger never arrives — should time out
      cleanly, not hang.
- [ ] H7.3 Confirm behaviour on a mid-capture disconnect.
- [ ] H7.4 Confirm outputs end up off after a crash.

---

## Cannot be tested in loopback

Carry this list forward to the Phase 2 planning session. Each item is a place
where a loopback pass does **not** imply the real system works.

| # | Item | Why loopback cannot reach it | Risk if wrong |
|---|---|---|---|
| U1 | Absolute 80 MHz drive amplitude at the AOM | Round trip is attenuated twice; no calibrated reference | Under- or over-driving the AOM |
| U2 | Amplifier chain linearity and saturation | Not in the loop | Intermodulation generated by the amplifiers, not the DUT — a false signal indistinguishable from the real one |
| U3 | DUT mixing behaviour | Emulated, by construction | The entire measurement premise |
| U4 | Photodetector bandwidth at 1 MHz | Not connected | Response rolled off or absent |
| U5 | Photodetector output level and input range choice | Unknown until measured | Clipping, or burying the signal in ADC quantisation |
| U6 | Real noise environment | Loopback is quiet | SNR far worse than predicted |
| U7 | Laser trigger electrical characteristics | Emulated | Trigger missed or mis-timed |
| U8 | Actual sweep repeatability of the laser | Not in the loop | Wavelength calibration drift |
| U9 | Ground loops and pickup with everything connected | Single-box loopback | 80 MHz leakage into the detector path |

U2 deserves particular attention. Amplifier intermodulation would appear at
exactly |f2 − f1| — the same frequency as the real signal — and would look
entirely legitimate. Worth designing a control measurement for it: for example,
driving one tone only and confirming nothing appears at the difference
frequency.

---

## Phase 2 — planning session (not started)

Do not begin connecting hardware without this. It needs, at minimum:

- Safe drive levels for the amplifier chain and AOMs, from the human
- Photodetector damage thresholds
- An order of connection that fails safe
- A control measurement for U2
- Agreement on what the agent may command unattended versus what needs a human
  present

Write the outcome into a new `docs/07-phase2-plan.md`.
