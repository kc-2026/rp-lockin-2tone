# rp-lockin-2tone

Two-tone lock-in detection on a Red Pitaya SIGNALlab 250-12.

Two 80 MHz carriers, amplitude modulated at 5 and 6 MHz, drive a DUT through
AOMs. The DUT mixes them and a photodetector returns the intermodulation
response at their 1 MHz difference. A laser sweeps wavelength over ~1 s; we
capture the response and the laser's trigger train, demodulate in software, and
deliver a 5000-point amplitude/phase trace across the sweep.

No FPGA development. Everything runs on a control PC over the network.

## Status

Phase 0 (offline) complete — 62 tests pass, no hardware touched.
Phase 1 (loopback) not started.

The signal processing is validated. **The SCPI hardware layer has never been
run against a board** and should be treated as a draft until test plan H1 is
done.

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

Read `docs/04-test-plan.md` first. The loopback wiring must be in place and the
DUT must not be connected.

## Layout

```
CLAUDE.md          agent onboarding — read first
SESSION_LOG.md     continuity between sessions
docs/
  01-project-spec.md    goals, requirements, phasing
  02-architecture.md    design decisions and their rationale
  03-frequency-plan.md  why 5/6/1 MHz and a 250-sample buffer
  04-test-plan.md       phased loopback plan + what it cannot test
  05-hardware-notes.md  board specifics, SCPI, DMA region, safety
  06-open-questions.md  what is still undecided
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
