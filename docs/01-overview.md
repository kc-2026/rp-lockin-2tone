# Project overview

## Goal

Measure a DUT's two-tone intermodulation response as a function of laser
wavelength, using lock-in detection on a Red Pitaya SIGNALlab 250-12.

The DUT has two inputs and one output. Both inputs are driven with an 80 MHz
carrier (required by the DUT, via AOMs). One input is held at constant
amplitude and modulated at f1; the other is modulated at f2. The DUT's
nonlinearity mixes them, and the response appears at the difference frequency
|f2 − f1|. A photodetector returns that response and nothing else.

Meanwhile a laser sweeps its wavelength across a span in approximately one
second. It is a **Santec**, and it can report its own wavelength against time
over a serial link.

**Wavelength calibration comes from the laser over serial, NOT from trigger-edge
timing (Kevin, 2026-08-14).** The laser reports **wavelength against relative time
from its first trigger**. Its trigger output fires at fixed time steps and goes to
the Red Pitaya's trigger input; **only the first edge is used**, to give both
instruments the same t = 0. The wavelength for each trace point is then a lookup
against the laser's table, with no sweep-rate assumption anywhere, and the
deliverable becomes power against wavelength directly.

**The one silent failure to design against:** both sides define t = 0 as "the
first trigger", but independently. If the acquisition arms late and latches the
second pulse, every wavelength shifts by exactly one time step and the trace
looks perfectly normal. Arm before the sweep, use pre-roll, and check the pulse
count against the table length. See Q21.

The trigger train is still digitised on IN2, but its job shrank from "encode the
wavelength axis in its interval timing" to "mark where the sweep begins".

The deliverable per sweep is a 4000–5000 point time series of the demodulated
response — **amplitude only** — mapped onto wavelength using the laser's serial
report, with the trigger fixing the time origin.

**Scope narrowed 2026-08-12 (Kevin): amplitude, not amplitude and phase.**
Phase is still computed and returned by `demodulate()`, and is still useful
within a sweep, but it is not a deliverable and nothing should be gated on it.
This is what downgraded Q6 (the OUT1/OUT2 relative carrier phase is not
repeatable) from a blocker to a noted limitation.

One consequence worth acting on: with an amplitude-only deliverable, `R =
sqrt(X² + Y²)` is the obvious estimator and it is **biased upward in noise**.
Because the phase is steady *within* a sweep, rotating X + jY to a common angle
and taking the real part is unbiased and quieter. Not yet implemented — see
`SESSION_LOG.md`.

## Requirements

| # | Requirement | Source |
|---|---|---|
| R1 | 80 MHz carrier on both drive outputs | DUT |
| R2 | Independent amplitude modulation at f1 and f2 | measurement principle |
| R3 | Demodulate at \|f2 − f1\| | measurement principle |
| R4 | Integration time ≥ 5–10 periods of \|f2 − f1\| | lock-in validity |
| R5 | 4000–5000 output points per 1 s sweep | sufficient sampling of the sweep |
| R6 | Trigger the capture from the laser's trigger output, to fix the time origin | sweep alignment |
| R6b | Read the laser's wavelength-versus-time over serial, and map the trace onto it | wavelength axis (Kevin, 2026-08-14) |
| R7 | Software only; no FPGA development | scope decision, see ADR-0001 |
| R8 | Runs on a control PC over the network | environment |

R4 and R5 together set the frequency plan. See `03-frequency-plan.md`.

## Chosen operating point

| Parameter | Value | Why |
|---|---|---|
| Carrier | 80 MHz | DUT requirement |
| f1 | 5 MHz | on the commensurate grid |
| f2 | 6 MHz | on the grid; gives a convenient difference |
| \|f2 − f1\| | 1 MHz | 71 cycles per integration time — R4 wants ≥ 5–10 |
| Drive buffer | 250 samples | exact for carrier and both tones |
| Output rate | 5000 Sa/s | R5 |
| Bandwidth | 2250 Hz | 0.9 × output Nyquist; the widest honest value |
| Equivalent τ | 71 µs | follows from the bandwidth |
| Acquisition | 125 MS/s (decimation 2) | aliasing-free, half the memory |

**Note on τ.** The original spec suggested 30 µs. At a 5000 Sa/s output that
corresponds to 5.3 kHz of bandwidth, which is above the 2.5 kHz output Nyquist —
noise between 2.5 and 5.3 kHz would fold into the trace. Widening τ to 71 µs
keeps the same 5000 points, removes the folding, and gains about 3.7 dB of
noise performance. It still gives 71 cycles of the 1 MHz difference frequency
per integration time, far above the 5–10 that R4 requires.

**Decided 2026-08-12 (Q10, Kevin): keep τ = 71 µs at 5000 points.** The
alternative that also avoids aliasing is 12500 points at τ = 28.3 µs, which
would honour the original 30 µs convention but exceed R5's point count; it was
considered and not taken.

Note this is *not* a free parameter, despite what an earlier draft of this
section claimed. `dsp.demodulate()` clamps bandwidth to 0.9 × output Nyquist
whenever `output_rate` is given (`min(bandwidth, honest)`), so requesting a
wider bandwidth alongside a fixed point count is silently ignored rather than
honoured. That clamp is deliberate — see ADR-0003. To genuinely shorten τ you
must raise the point count, which is what the 12500-point option does.

## Channel allocation

The board has two inputs and two outputs. All four are committed.

| Port | Use |
|---|---|
| OUT1 | 80 MHz carrier, AM at f1 = 5 MHz |
| OUT2 | 80 MHz carrier, AM at f2 = 6 MHz |
| IN1 | Photodetector — response at \|f2 − f1\| |
| IN2 | Laser trigger train — digitised for calibration, and the acquisition trigger source |

There is no spare channel. A reference pickoff of the drive is *not* available,
but is also not needed: both tones are generated by this board, so the
difference frequency is clock-coherent with the ADC and its phase is
deterministic.

## Out of scope

- FPGA development. See ADR-0001 for the reasoning and the conditions under
  which it would come back.
- Real-time analog output of the demodulated signal. The deliverable is a
  captured trace per sweep, not a continuous voltage.
- Closed-loop feedback.

## Phasing

**Phase 0 — offline.** Signal processing, waveform construction, capture
planning, DUT emulator, test suite. No hardware. *Complete.*

**Phase 1 — loopback.** Validate the SCPI transport, the transmit path, the
receive path, trigger digitisation, and long captures, using only cables from
the board to itself. Detailed in `07-phase1-loopback.md`.
***COMPLETE — 2026-08-14.*** Every loopback test passed, except H6.1 and
H5.2/H5.3 which were deliberately skipped and recorded as such. 102 offline
tests pass. A plain-language status of every step is at the top of
`SESSION_LOG.md`.

**Phase 2 — hardware in the loop.** Everything loopback cannot reach: real
drive levels through the amplifier chain, the AOMs, the DUT, the photodetector,
the laser trigger. Requires a dedicated planning session with the human before
anything is connected. **Not started, and the gate is deliberate.**
What that session needs, and what is still missing, is written up in
`08-phase2-hardware.md`. The session's *output* goes in `09-phase2-plan.md`.

**Phase 3 — usability.** A GUI or equivalent, if wanted. Deferred.

## Success criteria

Phase 1 completing — every loopback test passing, with the untestable items
explicitly enumerated rather than forgotten — was the agreed near-term
definition of success. **That is met as of 2026-08-14:** all tests pass and
the untestable items are enumerated as U1–U12 in `07-phase1-loopback.md`.

**Phase 2 criteria are still not set, and now need to be** (Q17). The results
they were waiting on are in. The single most useful number to set them
against: the noise floor is **σ = 3.57 µV per trace point**, so an
intermodulation response of **≥36 µV** is clearly visible in a single sweep
and anything below ~4 µV is not visible at all. Whether the real measurement
clears that bar is the question Phase 2 exists to answer.
