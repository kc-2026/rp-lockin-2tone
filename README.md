# rp-lockin-2tone

Two-tone lock-in detection on a Red Pitaya SIGNALlab 250-12.

Two AOMs gate light — one at 5 MHz, one at 6 MHz — by amplitude modulating the
80 MHz acoustic drive each AOM needs. **That 80 MHz is the AOM's requirement, not
the DUT's; the DUT only ever sees light varying in brightness.** The DUT mixes the
two, and a photodetector returns the intermodulation response at their ~1 MHz
difference.

**Two Santec lasers.** A fine sweeper covers ~1 s and 5000 points, carries the
trigger BNC, and supplies the wavelength axis from its own log; a stepper sits at
11 discrete wavelengths, one per sweep. Per sweep we capture the detector and the
trigger, demodulate in software, and deliver a 5000-point amplitude trace against
wavelength. Across the eleven, the deliverable is an **11 x 5000 map**.

No FPGA development. Everything runs on a control PC over the network.

## Status

**Phase 0 (offline) and Phase 1 (loopback) are both COMPLETE** — 233 offline
tests pass, and every loopback test has run against the board.

**The end-to-end pipeline exists** (`src/rp_lockin/pipeline.py`) and is checked
against emulator truth: a resonance planted at a known wavelength comes back at
that wavelength. Its hardware wrapper has never run against a board.

**Phase 2 (hardware in the loop) has not started** and is gated on a planning
session. Its three original blockers are all answered; see
`docs/08-phase2-hardware.md`.

**Two live problems, neither of them software:**

1. **The Ethernet link to the board has been dead since 2026-08-25.** The board
   is healthy — its LEDs confirm it boots. The control PC's port is the leading
   suspect.
2. **The laser has never answered a byte.** New on 2026-08-26: its virtual COM
   port driver reports `CM_PROB_FAILED_INSTALL` on the control PC, which is the
   most concrete lead this blocker has had.

**Start at the HANDOFF block at the top of `SESSION_LOG.md`** — it is the fastest
way to learn the current state, and it is kept current.

Headline measured numbers: noise floor **σ = 3.57 µV** per trace point on the
board, so a signal needs **≥36 µV**; with the real photodetector expect nearer
**11 µV** and **~120 µV**. Full set in `docs/05-results.md`.

## Install

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"        # Windows
.venv/bin/python -m pip install -e ".[dev]"            # Linux
```

Add `laser` for the serial transport, or `laser-d2xx` for that plus the D2XX
probe used by `scripts/laser_comms_diag.py`.

## Try it without hardware

```bash
python scripts/bench_gui.py     # then Acquire -> Simulate, Demodulate -> Demodulate
pytest -q                       # expect 233 passed, 11 deselected
```

The GUI's **Simulate** path runs the whole chain — capture handling,
demodulation, trigger edges, the laser log, the wavelength mapping and the CSV —
with nothing connected. It is the quickest proof an installation works.

```bash
python -c "from rp_lockin import plan_two_tone_grid; print(plan_two_tone_grid(1e6).describe())"
python -c "from rp_lockin import describe_capture_plan, plan_two_tone_grid as g; print(describe_capture_plan(1.0, g(1e6).difference))"
```

## With hardware

```bash
export RP_HOST=<board ip>
pytest tests/hardware -m hardware
```

Read `docs/07-phase1-loopback.md` first. The loopback wiring must be in place and the
DUT must not be connected.

## Layout

```
CLAUDE.md          agent onboarding — read first
SESSION_LOG.md     continuity between sessions
docs/
  00-index.md              START HERE — what each doc is for
  01-overview.md           goals, requirements, the four phases
  02-architecture.md       design decisions and their rationale
  03-frequency-plan.md     why the frequencies are what they are
  04-hardware-reference.md how the board behaves; SCPI, memory, safety
  05-results.md            every number this project has measured
  06-phase0-offline.md     offline development — COMPLETE
  07-phase1-loopback.md    the loopback campaign, H1–H7 — COMPLETE
  08-phase2-hardware.md    what Phase 2 needs; risks U1–U12; steps P1–P6
  10-open-questions.md     what is undecided, and what was decided
  11-pipeline.md           the deliverable path, and where its time axis comes from
src/rp_lockin/     the package
tests/             offline suite + hardware-gated loopback suite
scripts/
  bench_gui.py             Tkinter bench GUI; has a no-hardware Simulate path
  p1_laser_check.py        P1 — laser, read-only
  p2_trigger_check.py      P2 — laser trigger into IN2; no RF, no outputs
  p3_drive_chain.py        P3 — drive chain; DRIVES OUTPUTS
  p4_detector.py           P4 — detector in the real path
  p5_first_measurement.py  P5 — full system; enforces P5.1 before P5.2
  p6_robustness.py         P6 — repeatability and delivery
  rp_fastread.py           RUNS ON THE BOARD, not here
```

## Key numbers

| | |
|---|---|
| Carrier | **80.001831 MHz** |
| f1 / f2 | **5.004883 / 5.996704 MHz** |
| **Lock-in frequency** | **991.821 kHz — NOT 1 MHz** |
| Drive table | 16384 entries, played at fs/16384 |
| Acquisition | 31.25 MS/s (decimation 8) |
| Output | 5000 Sa/s, 2250 Hz bandwidth, τ = 71 µs |
| Memory for 1 s, 2 ch | **119.2 MiB** — 93% of the existing 128 MiB region |
| Settling cost | ~113 points (22.6 ms) — pre-roll AND tail required |

**None of the frequencies are round numbers and they cannot be.** The generator
always traverses a fixed 16384-entry table, so everything lands on a
15258.789 Hz grid. **Never hardcode `1e6` as the lock-in frequency** — use
`plan_two_tone_grid().difference`. Typing the round number into a demodulator
produces a flat trace and no error, because the real signal falls outside the
2250 Hz output filter. See `docs/03-frequency-plan.md`.
