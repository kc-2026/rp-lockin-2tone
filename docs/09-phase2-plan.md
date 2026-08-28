# Phase 2 plan — the output of the planning gate

`08-phase2-hardware.md` is the input to a planning session; this is its output.
**Written 2026-08-28.** Kevin's view was that the session was largely redundant
by now, and checking its own agenda against what has since been answered, that
is substantially right — four of its five items were already settled, three of
them weeks ago. This records the answers so the gate stops blocking work.

## The gate is DISCHARGED. Phase 2 execution is NOT done.

Two different things were being conflated:

- **The planning gate** — a checklist of information and decisions needed before
  anything is connected. **Closed, below.**
- **Phase 2 itself** — the P1–P6 steps. **Two of six done.** No RF has ever left
  the board.

## The agenda, item by item

| Agenda item | Status |
|---|---|
| Safe drive levels for the amplifier chain and AOMs | **Settled 2026-08-17 (Q12): no attenuator.** Kevin tuned the drive by maximising diffracted light with an unmodulated carrier, which is correct here because the drive is depth-1 AM. Three attenuator recommendations were made and all three withdrawn. Do not reopen. |
| Photodetector damage threshold | **Settled 2026-08-28 (Kevin): keep the laser under 1 mW.** The manual gives saturation (~0.96 mW) and no damage figure, so the rule is to stay below saturation, which is comfortably below damage. `full_sweep_test.py` enforces it as `--max-dbm`, default 0 dBm. The setpoint is at the LASER; fibre and connector loss only widen the margin. |
| An order of connection that fails safe | **Settled: P1–P6 as proposed**, and it is enforced in code rather than in prose — the P-series scripts refuse to drive an output without `--i-am-present` and a typed confirmation, and P5.2 refuses to run before P5.1. |
| A control measurement for U2 | **Settled: P5.1 is it**, and P5.2 refuses to run until P5.1 has run clean. An amplifier-generated product sits at exactly the frequency P5.2 looks at, so a signal there proves nothing without the one-tone control. |
| What may be commanded unattended | **STILL OPEN.** See below. |

### The one item still open

**Nothing runs unattended until you say otherwise.** That is the working
assumption, and it costs nothing while you are at the bench. It needs a real
answer before any long or overnight run — particularly with the amplifiers live.

**Q17, the Phase 2 success criteria, is also still unset.** It does not block
starting: it decides when to *stop*, not how to begin. The number to set it
against is the noise floor — σ = 3.57 µV per trace point at the ADC, so a
response of ≥36 µV is clearly visible in a single sweep, and the detector's own
~11 µV noise pushes that to roughly 120 µV in practice.

## Where Phase 2 actually stands

| Step | State |
|---|---|
| **P1** laser link | **DONE** — over LAN, not serial. USB is a hardware fault inside the instrument. |
| **P2** trigger into IN2 | **DONE 2026-08-28** — 5001 pulses against 5001 logged rows, 24.997 µs wide, 199.997 µs apart, none lost at decimation 8. |
| **P3** drive chain, AOMs disconnected | **NOT DONE.** No RF has ever left this board into an amplifier. |
| **P4** optics connected, low power | **NOT DONE.** |
| **P5** full system, first real measurement | **NOT DONE.** |
| **P6** robustness and delivery | **NOT DONE.** |

Beyond the P-series, two things the deliverable needs and that have never been
touched:

- **The stepping laser (TSL-770) has never been contacted at all.** It supplies
  the second wavelength axis — the "11" in the 11 × 5000 map, so half the
  deliverable. The sweeper's LAN recipe should transfer, but nothing is proven.
- **The photodetector has never seen light.** Everything measured so far ran
  with the shutter closed, where a working detector and a disconnected one are
  indistinguishable. It reads ~0 V with ~1 count of noise, which is consistent
  with both.

## What is ready and waiting

The measuring instrument is finished. Verified against hardware on 2026-08-28:
the board captures and triggers, the sweeper sweeps and logs, and the full
software path — capture → demodulate → wavelength axis → CSV — runs end to end
(`scripts/full_sweep_test.py`). The wavelength axis is built from the measured
trigger edges rather than an assumed uniform step, which matters because the
sweep speed ripples ~11% (Q29).

## The order to work in

1. **Show the detector responds to light.** Laser under 1 mW, shutter open, look
   at IN1. Closes Q11b, and it is the cheapest remaining unknown.
2. **Talk to the stepping laser.** Unknown effort; never attempted.
3. **P3 — drive chain with the AOMs disconnected.** Both ZHL-1-2W+ amplifiers
   exist as of 2026-08-28, though the second is not yet connected.
4. **P4**, then **P5**.

Steps 1 and 2 are independent of each other and of the RF chain, so they can be
done in any order, or in parallel with wiring the second amplifier.
