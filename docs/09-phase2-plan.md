# Phase 2 plan — decisions, and where execution stands

**Updated 2026-09-01.** `08-phase2-hardware.md` was the input to a planning
gate; this is its output plus everything execution has since settled.

## The gate is DISCHARGED, and execution is well under way

Two things used to be conflated and are worth keeping apart:

- **The planning gate** — the information and decisions needed before anything
  was connected. **Closed 2026-08-28.**
- **Phase 2 itself** — the P1–P6 steps. **P1, P2 and P4 are done, P5 is part
  done.** Real optical measurements exist.

## The agenda, item by item

| Agenda item | Status |
|---|---|
| Safe drive levels for the amplifier chain and AOMs | **Settled 2026-08-17 (Q12): no attenuator.** Kevin tuned the drive by maximising diffracted light with an unmodulated carrier, which is correct here because the drive is depth-1 AM. Three attenuator recommendations were made and all three withdrawn. Do not reopen |
| Photodetector damage threshold | **Settled 2026-08-28 (Kevin): keep the laser under 1 mW.** The manual gives saturation (~0.96 mW) and no damage figure, so the rule is to stay below saturation, comfortably below damage. The setpoint is at the LASER; fibre and connector loss only widen the margin |
| An order of connection that fails safe | **Settled: P1–P6**, enforced in code rather than prose — the P-series scripts and `bench.py` refuse to drive an output without a typed confirmation, and P5.2 refuses to run before P5.1 |
| A control measurement for U2 | **Settled: P5.1 is it**, and P5.2 refuses to run until P5.1 has run clean. An amplifier-generated product sits at exactly the frequency P5.2 looks at |
| What may be commanded unattended | **STILL OPEN.** Nothing runs unattended. It costs nothing while Kevin is at the bench and needs an answer before any long run with the amplifiers live |

**Q17, the Phase 2 success criteria, is also still unset.** It decides when to
stop, not how to begin.

## Where Phase 2 actually stands

| Step | State |
|---|---|
| **P1** laser link | **DONE** — over LAN, not serial. USB is a hardware fault inside the instrument |
| **P2** trigger into IN2 | **DONE** — 5001 pulses against 5001 logged rows, 24.997 us wide, 199.997 us apart, none lost at decimation 8 |
| **P3** drive chain, AOMs disconnected | **SUPERSEDED** — the drive went in with the AOM connected and works |
| **P4** optics connected, low power | **DONE in substance** — full chain from `bench.py`, with a low-power control run |
| **P5** full system, first real measurement | **PART DONE** — a real 5000-point optical sweep exists. P5.1 and P5.2 have not run: no second tone, no crystal |
| **P6** robustness and delivery | **NOT DONE** |

## What is proven, and what it cost to learn

The measuring instrument is finished. Capture, trigger, sweep, log, demodulate,
wavelength axis and CSV all work end to end. Four things learned the hard way
and worth not relearning:

- **The wavelength axis uses the measured trigger edges**, not an assumed
  uniform step. The sweep speed ripples ±11% with a 0.41 nm period (Q29), which
  is 13.68 pm — 0.684 of a step — of error removed.
- **Every laser setting must be read back.** `configure_sweep` writes seven and
  now verifies seven. It used to verify one, and a sweep silently reverted to
  step mode between the first run and the second.
- **The laser must reach its start wavelength on its own.** A sweep started
  before it gets there covers a shorter range at exactly the right speed and
  step, so the trace looks entirely normal. Driving it there by hand with
  `:WAV` is not a fix — it leaves the instrument in a state where the sweep
  emits no trigger train at all.
- **`mod_cycles` multiplies the generator's frequency error.** The output is
  `mod_cycles x play_rate`, so a plan with 12 cycles carries 12x the error of
  one with 1. At 915 kHz that was a ~0.69 Hz offset, which the lock-in drew as
  a smooth arch through zero across the sweep — indistinguishable from a
  wavelength-dependent response.

## The order to work in

1. **Get the crystal.** Without it, U2 and U3 stay open and this is a
   transmission measurement.
2. **Wire the second amplifier and AOM** for SFG. The bench already drives OUT2.
3. **P5.1, then P5.2.**
4. **Install the PDA100A2** for the SHG product — silicon is blind at 1550, so
   what it sees near 775 nm is genuinely upconverted.
5. **Contact the TSL-770.** Half the deliverable. Parked at Kevin's request.
6. **P6.**

Items 1, 2, 4 and 5 are independent of each other.
