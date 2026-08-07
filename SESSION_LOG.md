# Session log

Append a new entry at the end of every session. This is the only continuity
between agent sessions — a fresh agent must be able to resume from it without
re-deriving anything.

Template:

```
## YYYY-MM-DD — <who> — <one-line summary>
**Goal:**
**Did:**
**Learned:**
**Broke / still broken:**
**Next:**
```

---

## 2026-08-07 — Claude (Cowork, scoping session) — project bootstrap

**Goal:** Establish feasibility, fix the measurement architecture, and hand a
Claude Code agent a working starting point.

**Did:**
- Investigated `marceluda/rp_lock-in_pid` at source level. It cannot serve this
  measurement: reference generator capped at 49.6 kHz, output filter capped at
  1.2 kHz, built for a different board on a five-year-old toolchain, and it
  disables the stock signal generator. Reasoning recorded in ADR-0001
  (`docs/02-architecture.md`).
- Established that this is a burst measurement (one trace per laser sweep), so
  software demodulation over Deep Memory Acquisition is sufficient. No FPGA.
- Derived the frequency plan: f1 = 5 MHz, f2 = 6 MHz, |f2−f1| = 1 MHz, exact
  250-sample buffer. See `docs/03-frequency-plan.md`.
- Built and validated the DSP core, waveform construction, capture planner and
  DUT emulator. 62 offline tests pass.
- Wrote `hardware.py` from documentation. **Never executed.**

**Learned (the expensive parts):**
- A single FIR cannot set a 2 kHz corner at 250 MS/s — needs ~2.4M taps. The
  first implementation silently capped taps and used a filter ~100x too wide.
- FIR settling is the full impulse-response length, not the group delay.
  Trimming by group delay leaves ringing at the cutoff that mimics real noise.
- The output time axis must compensate both the trim and the group delay, or
  the whole trace shifts ~10 ms — which would bias every wavelength assignment.
- Streaming block boundaries must be bit-exact, not approximately equal. They
  are periodic, so any artefact lands identically in every sweep.
- Emulator clipping protection must rescale the ground truth too, or loopback
  tests report a phantom 2x amplitude error.
- Filter settling costs ~108 output points (22 ms) at 5000 Sa/s. The capture
  must pre-roll before the laser trigger.
- The naive buffer rule N = fs/f_mod is wrong whenever that is not an integer;
  f2 = 6 MHz needs 125 samples, not 41.67.

**Broke / still broken:**
- `hardware.py` is entirely unverified. Highest risk item.
- Deep Memory Generation not implemented — blocks full-length emulated sweeps.

**Next:** Test plan H1 — validate the SCPI transport against the real board,
starting by recording the OS version.
