# 02 — Architecture and design decisions

Read this before changing anything structural. The bugs that shaped these
decisions are catalogued in `11-mistakes.md`.

## Shape

```
src/rp_lockin/
  waveforms.py   drive construction, frequency planning
  planning.py    capture sizing: memory, decimation, settling, pre-roll, tail
  emulator.py    synthetic DUT output + ground truth, for loopback testing
  dsp.py         demodulation                              [TRUSTED]
  wavelength.py  trace -> wavelength, clock check, alignment guards
  pipeline.py    THE DELIVERABLE PATH: joins all of the above
  santec.py      santec TSL-770/775 transport   [NEVER RUN AGAINST A LASER]
  output.py      CSV deliverable + raw .npz
  hardware.py    SCPI transport   [VERIFIED against the board, Phase 1]
  constants.py   board constants and design limits

scripts/
  bench.py         THE WORKING TOOL. Panel bench; independent operations
  _bench_ops.py    every instrument operation, Tk-free. ONE implementation
  _bench_widgets.py  Plot, ScrollFrame, Worker, wheel_safe
  dr_bench.py      detector gain / dynamic-range study. Separate on purpose
  bench_gui.py     the older tabbed GUI. Kept for its no-hardware Simulate path
  tsl775.py        the laser driver that is PROVEN against the instrument
  _bench.py        safety contract shared by the P-series scripts
  p1..p6_*.py      the original bench campaign; outputs gated behind consent
  rp_fastread.py   RUNS ON THE BOARD, not the control PC
```

### Verified versus unverified — the table that matters

| Area | Status |
|---|---|
| `dsp.py`, `planning.py`, `emulator.py` | **Trusted.** Covered by the offline suite. Do not change without re-running it |
| `waveforms.py` — `make_am_table`, `make_am_table_exact`, `plan_exact_am`, `plan_two_tone_grid`, `make_cw_table`, `make_sine_table` | **Trusted and hardware-verified.** Use these to drive the board |
| `waveforms.py` — `make_am_waveform`, `plan_two_tone` | **Sound arithmetic, WRONG hardware model.** Kept because their tests are worth having. Driving the board with them produces no output at all |
| `hardware.py` — transport, generator, `acquire`, `acquire_deep_fast` | **Verified against the board.** Phase 1 complete |
| `hardware.py` — `acquire_deep_2ch` | **The SCPI read is broken.** Arming is fine; the read returns garbage. Use `acquire_deep_fast` |
| `wavelength.py` | Offline-tested. Contains **no serial code** |
| `pipeline.py` — `reduce_sweep` | **Trusted offline**, checked against emulator truth, and exercised on real captures |
| `pipeline.py` — `measure_sweep` | **Never run against a board.** The bench uses `_bench_ops` instead |
| `santec.py` (`SantecTSL`) | **Written from the manuals. Never run against a laser.** See Q35 |
| `scripts/tsl775.py` (`TSL775`) | **Proven against the instrument, over LAN.** This is what the bench uses |
| `scripts/rp_fastread.py` | **Runs ON THE BOARD.** The one deliberate exception to "everything runs on the PC" |

## The split that is load-bearing

`dsp.py` and `hardware.py` are kept apart **on purpose**. The signal processing
is fully testable offline; the transport is not. Keeping them separate means a
wrong SCPI command produces a **connection error** rather than a
plausible-but-wrong measurement. **Do not move processing into the transport
layer.**

`wavelength.py` follows the same principle for the laser: it holds **no serial
commands at all** and takes the laser's wavelength table as an argument. That
separation is why the mapping could be developed and tested while the laser was
silent.

**`pipeline.py` is where the two halves meet**, and it keeps the same split:
`reduce_sweep()` takes arrays and is fully offline-testable, while
`measure_sweep()` is a thin wrapper that only moves bytes. Everything that can
be wrong about the physics lives in the testable half, on purpose. See
`07-pipeline.md`.

**`scripts/_bench_ops.py` is the same idea for the bench.** Every instrument
operation lives there, Tk-free and testable; both GUIs call it. The old Linear
Sweep tab was a *second* implementation of the laser setup and the reduction,
so every fix had to be made twice — and twice it was not.

## Signal chain

```
IN1 samples --> mix with e^(-j2 pi f_ref t) --> decimating FIR chain --> X, Y
                                                                        |
IN2 samples --> threshold + RISING edges only --> trigger edge times ----+
                    (a 25 us pulse gives TWO edges;                      |
                     averaging both halves the step)                     v
laser log  ------------------------------------------> trace vs wavelength
```

`pipeline.reduce_sweep()` is that whole diagram in one call.

---

## ADR-0001 — Software, not FPGA

The existing open-source option, `marceluda/rp_lock-in_pid`, cannot do this job
and cannot be adapted cheaply:

- Its reference generator walks a fixed 2520-point table one entry per clock,
  capping the harmonic reference at 49.6 kHz (99 kHz even at 250 MHz). There is
  no phase accumulator to modify — it needs replacing.
- Its harmonic-channel output filter has a hard-coded accumulator slice fixing
  the fastest corner at 1.2 kHz.
- It targets a Zynq 7010 with Vivado 2015.2, forked from Red Pitaya's v0.95
  tree. The 250-12 is a 7020 on Vivado 2020.1 with entirely different converter
  interfaces.
- It **disables the stock signal generator outright** (`disabled by LOLO` in
  `red_pitaya_top.v`, outputs tied to zero), which is why a board running that
  firmware cannot produce the 50 MHz its hardware is capable of.

Against that, the measurement is fundamentally a **burst capture**: one trace
per laser sweep, with gaps between sweeps entirely acceptable. That is exactly
what Deep Memory Acquisition plus offline demodulation does well, with no FPGA
toolchain and no timing closure.

**When FPGA would come back:** if continuous analog output of the demodulated
signal is ever needed — driving another instrument, or closing a feedback loop
(Q16).

## ADR-0002 — Decimation

The board's analog front end rolls off at 60 MHz, so decimating by 2 puts
Nyquist at 62.5 MHz — *above* the rolloff — and there is nothing left to fold.
Decimation 2 therefore costs nothing in noise while halving the memory and
transfer time.

**Superseded in practice, and the reasoning still stands.** Decimation 2 needs
477 MB for a 1 s two-channel capture and the reserved DMA region is 128 MiB.
Enlarging it was considered and **rejected**: the objection that motivated it —
recovering trigger intervals exactly — vanished when the wavelength axis moved
to the laser's own log.

**The operating point is decimation 8**, measured at **1.1 dB** worse than
decimation 2. H6.2 through H7.1 all ran that way, and so does every real sweep.

## ADR-0003 — The output rate drives the bandwidth

The deliverable is a fixed **point count**, not a fixed bandwidth. Asking for
5000 points/s and 5.3 kHz of bandwidth is incoherent: 5000 Sa/s can only
represent 2500 Hz, so the extra bandwidth folds noise into the trace.

`demodulate(output_rate=...)` therefore clamps the bandwidth to **0.9 × output
Nyquist**. The result is a 71 µs equivalent τ instead of 30 µs, which is
~3.7 dB quieter, still gives plenty of cycles of the difference frequency per
integration time, and delivers exactly the same 5000 points.

**The clamp is silent, and that is deliberate.** Requesting a wider bandwidth
alongside a fixed point count is ignored rather than honoured. To genuinely
shorten τ you must raise the point count.

**This is also why the traditional "sample no faster than 1/(5τ)" rule does not
apply here**, and the difference is measured (`06-results.md`). That rule
exists because a single-pole RC output filter has enormous out-of-band tails:
at the output Nyquist an RC is only ~3.5 dB down, so you must sample slowly to
keep what folds small. This chain is a sharp multistage FIR, **−82 dB at
2400 Hz and −140 dB at 2500 Hz**, so there is nothing to fold and plain
Nyquist applies: ≥ 2 × bandwidth. The rule's other half is real and worth
keeping — 5000 samples per second carry about **3800 independent values**, not
5000.

The bench exposes the bandwidth explicitly (blank = derive it from the output
rate) and reports the resulting τ, the noise gain, the settling cost and the
wavelength resolution, so the trade is visible rather than buried.

## ADR-0004 — A hard floor on wavelength resolution

`run_map` **refuses** a filter that smears wavelength past **100 pm**
(`RESOLUTION_LIMIT_NM`), where

```
resolution_nm = speed_nm_s / (2 x bandwidth)
```

A refusal rather than a warning, because the failure is invisible in the
output: an over-filtered trace is smooth, plausible, correctly mapped onto
wavelength, exports to CSV, and simply is not resolving what it claims to.
Nothing else in the bench pushes back on narrowing the bandwidth either — it is
quieter *and* often settles faster, so every other signal points the wrong way.

Enforced on the deliverable path rather than at the knob, because that is where
a trace becomes a result.

## ADR-0005 — One CSV per sweep, not one file with a second column

Considered and rejected. One CSV per sweep plus an index keeps each trace
independently openable, keeps the per-sweep provenance in a header instead of
repeating it on 55,000 rows, and means a failed sweep costs one file rather than
the set. `SweepSeries` / `write_series` handle the 11-step set.

---

## Known limitations

- **`acquire_deep_2ch`'s SCPI read is broken**, superseded by
  `acquire_deep_fast`.
- **Deep Memory Generation does not exist on this OS**, permanently (H5.1). The
  generator's unique-waveform ceiling is 16384 points = 65.536 µs. H6.5
  emulated the DUT by stepping the amplitude during the capture instead.
- **Filter settling costs ~113 output points per sweep** at the default
  bandwidth. Mitigated by pre-roll, not eliminated — **and it needs a tail as
  well**, because `LockinResult.t` compensates group delay, so the valid window
  is *shifted* rather than merely shortened. Use `planning.recommended_tail()`.
  A record stopping at trigger + 1 s yields 4943 points, not 5000, with no error
  and a trace that just ends early.
- **No averaging across sweeps** (Q13, Kevin's decision). Straightforward to add.
- **Two laser drivers with different surfaces** (Q35). `TSL775` is proven and
  drives the bench; `SantecTSL` is richer, unproven, and is what `pipeline.py`
  assumes. They should converge.
- **The bench can be launched twice**, and one instrument with one connection
  slot deserves a single-instance lock. Open, not tracked as a question.
- **The emulator's envelope is prescribed, not derived.** It does not model two
  AOM-modulated beams through a nonlinearity — it starts from the assumed
  answer. So the pipeline is tested against the *software's* correctness, not
  against the *physics*.
