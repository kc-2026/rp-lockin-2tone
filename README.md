# rp-lockin-2tone

Two-tone lock-in detection on a Red Pitaya SIGNALlab 250-12.

Two AOMs gate light — one at 5 MHz, one at 6 MHz — by amplitude modulating the
80 MHz acoustic drive each AOM needs. **That 80 MHz is the AOM's requirement, not
the DUT's; the DUT only ever sees light varying in brightness.** The DUT mixes the
two, and a photodetector returns the intermodulation response at their ~1 MHz
difference. A Santec laser sweeps wavelength over ~1 s; we capture the response
and the laser's trigger, demodulate in software, and deliver a 5000-point
amplitude trace against wavelength.

No FPGA development. Everything runs on a control PC over the network.

## Status

**Phase 0 (offline) and Phase 1 (loopback) are both COMPLETE** — 153 offline
tests pass, and every loopback test has run against the board.

**Phase 2 (hardware in the loop) has not started** and is gated on a planning
session. Its three original blockers are all answered; see
`docs/08-phase2-hardware.md`.

**The live problem is that the Santec laser does not reply over USB.** The host
side has been eliminated — see the HANDOFF block at the top of `SESSION_LOG.md`,
which is the fastest way to learn the current state.

Headline measured numbers: noise floor **σ = 3.57 µV** per trace point on the
board, so a signal needs **≥36 µV**; with the real photodetector expect nearer
**11 µV** and **~120 µV**. Full set in `docs/05-results.md`.

## Install

```bash
pip install -e ".[dev]"
```

## Try it without hardware

```bash
python -c "from rp_lockin import plan_two_tone; print(plan_two_tone(1e6).describe())"
python -c "from rp_lockin import describe_capture_plan; print(describe_capture_plan(1.0, 1e6))"
pytest
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
src/rp_lockin/     the package
tests/             offline suite + hardware-gated loopback suite
scripts/           command-line entry points
```

## Key numbers

| | |
|---|---|
| Carrier | 80 MHz |
| f1 / f2 | 5 / 6 MHz |
| Lock-in frequency | 1 MHz |
| Drive buffer | 250 samples (exact) |
| Acquisition | 125 MS/s (decimation 2, aliasing-free) |
| Output | 5000 Sa/s, 2250 Hz bandwidth, τ = 71 µs |
| Memory for 1 s, 2 ch | 477 MB — needs the DMA region enlarged to 512 MB |
| Settling cost | ~108 points (22 ms) — pre-roll required |
