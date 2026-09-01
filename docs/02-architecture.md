# Architecture and design decisions

## Shape

```
  waveforms.py  ── drive construction, frequency planning
  planning.py   ── capture sizing: memory, decimation, settling, pre-roll, tail
  emulator.py   ── synthetic DUT output + ground truth (loopback testing)
  dsp.py        ── demodulation                          [TRUSTED]
  wavelength.py ── trace → wavelength, clock check, alignment guards
  pipeline.py   ── THE DELIVERABLE PATH: joins all of the above
                                                         [TRUSTED offline,
                                                          never seen a laser]
  santec.py     ── Santec TSL-770/775 transport, USB or LAN
                                                         [NEVER RUN AGAINST
                                                          A LASER]
  output.py     ── CSV deliverable + raw .npz
  hardware.py   ── SCPI transport            [VERIFIED against the board,
                                              Phase 1 complete 2026-08-14]

  scripts/bench_gui.py   ── Tkinter bench GUI; Simulate path needs no hardware
  scripts/p2..p6_*.py    ── the bench campaign; outputs gated behind consent
  scripts/rp_fastread.py ── RUNS ON THE BOARD, not the control PC
```

The split between `dsp.py` and `hardware.py` is deliberate and load-bearing.
The signal processing is fully testable offline; the transport is not. Keeping
them apart means a wrong SCPI command produces a connection error rather than a
plausible-but-wrong measurement. **Do not move processing into the transport
layer.**

`wavelength.py` follows the same principle for the laser: it holds **no serial
commands at all** and takes the laser's wavelength table as an argument. That
separation is why the mapping could be developed and tested while the laser was
silent.

**`pipeline.py` is where the two halves finally meet**, and it keeps the same
split: `reduce_sweep()` takes arrays and is fully offline-testable, while
`measure_sweep()` is a thin wrapper that only moves bytes. Everything that can be
wrong about the physics lives in the testable half, on purpose. See
`11-pipeline.md`.

`santec.py` **is** now written — from the manuals, never from memory, with one
documented exception (`set_wavelength_m`, whose command string is inferred and
which verifies itself by read-back). It has still never spoken to a laser.

## Signal chain

```
IN1 samples ─► mix with e^(-j2π·991.821kHz·t) ─► decimating FIR chain ─► X, Y
                                                                        │
IN2 samples ─► threshold + RISING edges only ─► trigger edge times ─────┤
                    (a 25 us pulse gives TWO edges;                     │
                     averaging both halves the step)                    ▼
laser log  ────────────────────────────────────────────► trace vs wavelength
```

`pipeline.reduce_sweep()` is that whole diagram in one call. The step between
logged points comes from the trigger train's SPAN over (N - 1) points, not from
the interval between pulses — which is what makes it immune to the laser
logging at some other divisor. See `11-pipeline.md`.

## Why software and not FPGA (ADR-0001)

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
- It disables the stock signal generator outright (`disabled by LOLO` in
  `red_pitaya_top.v`, outputs tied to zero), which is why a board running that
  firmware cannot produce the 50 MHz its hardware is capable of.

Against that, the measurement is fundamentally a burst capture: one trace per
laser sweep, with gaps between sweeps entirely acceptable. That is exactly what
Deep Memory Acquisition plus offline demodulation does well, with no FPGA
toolchain and no timing closure.

**When FPGA would come back:** if continuous analog output of the demodulated
signal is ever needed — driving another instrument, or closing a feedback loop.
Worth recording that it would be cheaper than a general implementation: at
250 MS/s, 1 MHz is exactly fs/250, so the demodulation reference is a fixed
250-entry table stepped one entry per clock. No DDS, no fractional phase. The
thing that makes the existing project hopeless is precisely what would make
this case easy.

## Why decimation 2 is free (ADR-0002)

The board's analog front end rolls off at 60 MHz. Decimating by 2 puts Nyquist
at 62.5 MHz — *above* the rolloff — so there is nothing left to fold. Decimation
2 therefore costs nothing in noise while halving the memory and transfer time.
Decimation 4 and beyond start folding real noise into the trace.

**Superseded in practice, and the reasoning still stands.** Decimation 2 needs
477 MB for a 1 s two-channel capture and the reserved DMA region is 128 MiB.
Enlarging it was considered and **rejected** — the objection that motivated it
(recovering trigger intervals exactly) vanished when the wavelength axis moved
to the laser's own log. **The operating point is decimation 8**, measured at
1.1 dB worse than decimation 2, and H6.2 through H7.1 all ran that way.

`describe_capture_plan()` recommended decimation 2 plus the rejected board
change for eleven days, because `recommend()` bounded by `MAX_DMA_MB` — the
hypothetical enlarged region — instead of `DMA_REGION_MB`, which is what exists.
Fixed 2026-08-26. There were no tests on the planner at all, which is why it
drifted; `tests/test_planning.py` now asserts the recommendation and that the
output contains no device-tree instructions.

## Why the output rate drives the bandwidth (ADR-0003)

The deliverable is a fixed point count, not a fixed bandwidth. Asking for
5000 points/s and 5.3 kHz of bandwidth is incoherent: 5000 Sa/s can only
represent 2500 Hz, so the extra bandwidth folds noise into the trace.

`demodulate(output_rate=...)` therefore clamps the bandwidth to 0.9 × output
Nyquist. The result is a 71 µs equivalent τ instead of 30 µs, which is ~3.7 dB
quieter, still gives 71 cycles of the difference frequency per integration
time, and delivers exactly the same 5000 points.

## Bugs worth remembering

All were live, all produced believable wrong answers rather than crashes, and
all now have tests. This list is the single most useful page in the repository
for anyone about to change something.

**Filter tap explosion.** A single FIR setting a 2 kHz corner at 250 MS/s needs
~2.4 million taps, because tap count scales with fs/transition_width. The
original code capped taps and silently substituted a filter ~100× too wide,
which inflated the noise floor and drooped the passband. Fixed with multistage
decimation: cheap wide-transition stages down to a low rate, then one sharp
stage there. Caught by `test_output_noise_scales_as_sqrt_bandwidth`.

**Settling versus group delay.** An FIR output is valid only after the *full*
impulse response has entered, not after half of it. Trimming by group delay
left step-response ringing at exactly the cutoff frequency — a few percent
wobble on R that looks like real noise. Caught by
`test_settling_trim_removes_ringing`.

**Time axis offset.** The returned axis must compensate both the trimmed
settling samples and the group delay. Getting only one right shifts the whole
trace by ~10 ms at 5000 Sa/s. Since the wavelength calibration comes from
trigger edges in the same record, that offset would bias every wavelength
assignment in the sweep. Caught by `test_time_axis_locates_a_feature_correctly`.

**Clipping normalisation**, in the emulator rather than the library: clipping
protection rescaled the synthesised waveform but not the recorded ground truth,
so a loopback test would have reported a phantom 2× amplitude error. Caught by
`test_clip_normalisation_is_reflected_in_ground_truth`.

### Found on 2026-08-25/26, by joining the pipeline together

**Both trigger polarities counted as pulses.** `find_trigger_edges` returns
rising AND falling edges, and a real Santec trigger is a 25 µs *pulse* — so
every logged point makes two edges. A step averaged over both is near half the
truth, which compresses the entire wavelength axis 2× and still draws a clean
trace. **This would have been live on the first real sweep.** Fixed with
`polarity="rising"`. Caught by `test_a_pulse_train_needs_rising_edges_only`.

**The emulator only made square waves**, which hid the above completely — a 50%
duty cycle no laser emits. `make_trigger_pulses` produces the real shape. The
lesson generalises: *an emulator that cannot reproduce the failure cannot test
for it.*

**A guard that read stronger than it was.** `check_alignment` documents two
independent checks, count and span. Under the pipeline's default step the span
one is **vacuous** — the step is derived from the span, so it compares a number
against itself and reports 0.00% error on a genuinely broken alignment. Kept,
because it does real work with a configured step, but now stated at the point of
use.

**A transport that could not resynchronise.** `santec.py`'s buffer persisted
between queries, so a read timing out mid-reply left the remainder behind and
every later query returned the tail of the previous one. `hardware.py` records
the identical failure against the board on 2026-08-12. Fixed with `resync()`.

**A front end that could not differ between channels.** `_reapply_front_end`
forced both to one coupling/gain after every `ACQ:RST`, so IN2 could not stay on
HV — which made P2 impossible to run as specified, and would have presented as
"the laser is not triggering" rather than as a range error. Fixed with
`setup_channel()`.

## Known limitations

- ~~`hardware.py` is unverified. This is the largest single risk.~~
  **Resolved 2026-08-14.** Every method has run against the board; Phase 1 is
  complete. `acquire_deep_2ch`'s SCPI read remains broken and is superseded by
  `acquire_deep_fast`.
- ~~Deep Memory Generation is not yet implemented; long emulated sweeps depend
  on it.~~ **It does not exist on this OS (H5.1), permanently.** The generator's
  unique-waveform ceiling is 16384 points = 65.536 µs. H6.5 emulated the DUT by
  stepping the amplitude during the capture instead.
- Filter settling costs ~113 output points per sweep. Mitigated by pre-roll,
  not eliminated — **and it needs a tail as well**, because `LockinResult.t`
  compensates group delay, so the valid window is shifted rather than merely
  shortened. See `planning.recommended_tail()`.
- No averaging across sweeps yet. Straightforward to add if wanted (Q13).
- **The largest single risk is now the Santec serial link**, which does not
  exist yet and cannot be written from memory. See `08-the-bench.md`. It is
  the one subsystem whose silent failure is invisible in the output.
