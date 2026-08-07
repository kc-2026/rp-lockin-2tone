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

- [ ] H1.1 Record the OS version into `docs/05-hardware-notes.md`.
- [ ] H1.2 Connect, `*IDN?`, confirm it is a 250-12 and not a 125-14. A 125-14
      would make every frequency in this project wrong, silently.
- [ ] H1.3 Confirm the sample rate the board reports matches 250 MS/s.
- [ ] H1.4 Read `ACQ:AXI:START?` and `ACQ:AXI:SIZE?`. Record the region size.
- [ ] H1.5 Verify each command in `setup_generator`, `setup_am_generator`,
      `setup_acquisition`, `acquire`, `acquire_deep`, `acquire_deep_2ch`.
      Fix spellings in place; note every correction in `SESSION_LOG.md`.
- [ ] H1.6 Confirm binary block transfer (`ACQ:DATA:FORMAT BIN`) returns the
      expected sample count and a sane amplitude range.

**Exit:** every method in `hardware.py` has been executed successfully at least
once, and its `VERIFY:` note either removed or replaced with a confirmation.

### H2 — transmit path

**Wiring:** OUT1 → IN1.

- [ ] H2.1 Generate 80 MHz AM at 5 MHz. Confirm three spectral lines at 75, 80,
      85 MHz.
- [ ] H2.2 Repeat at a 20 MHz carrier. **This is the quantitative check** — the
      analog path is flat at 20 MHz, so sideband amplitudes and modulation
      depth are meaningful there. At 80 MHz the round trip is attenuated twice
      (output and input both roll off at 60 MHz), so only relative line
      positions are trustworthy.
- [ ] H2.3 Confirm no wrap-glitch comb. Look for spurious content between
      100 kHz and 40 MHz; there should be essentially none. This is the test
      that catches an incommensurate buffer.
- [ ] H2.4 Both channels generating at once, at f1 and f2. Confirm both are
      alive and that starting them is synchronous. **Open question:** whether
      `SOUR:TRig:INT` starts channels together or a combined trigger is
      required. Resolve and document.
- [ ] H2.5 Confirm relative carrier phase between OUT1 and OUT2 is repeatable
      across restarts. If it is not, the difference-frequency phase will vary
      sweep to sweep and will need referencing.

### H3 — receive path

**Wiring:** OUT1 → IN1.

- [ ] H3.1 Generate a plain 1 MHz tone. Demodulate. Confirm recovered amplitude
      tracks the commanded amplitude linearly across at least a decade.
- [ ] H3.2 Confirm recovered phase is stable within a capture and repeatable
      across captures.
- [ ] H3.3 Measure the noise floor with the output off and the input
      terminated. Convert to an equivalent input noise density. Record it —
      this is the number that predicts whether the real measurement will work.
- [ ] H3.4 Confirm the √bandwidth law holds on real data, not just synthetic:
      halving the bandwidth should drop the noise by √2.
- [ ] H3.5 Deliberately offset the demodulation frequency by a few kHz and
      confirm the response falls off as the filter predicts.

### H4 — trigger digitisation

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

- [ ] H6.1 Enlarge the reserved DMA region to 512 MB
      (`docs/05-hardware-notes.md`). Reboot. Confirm `ACQ:AXI:SIZE?`.
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
