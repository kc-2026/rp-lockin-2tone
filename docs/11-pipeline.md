# 11 — The pipeline: one captured sweep in, a wavelength trace out

**This is the deliverable path.** Everything else in the project exists to feed
it. Written 2026-08-25; `reduce_sweep` is verified against emulator truth,
`measure_sweep` has **never run against a board**.

```
IN1 detector ─┐
              ├─ reduce_sweep ─→ SweepReduction ─→ write_trace_csv
IN2 trigger  ─┤                                 └─→ SweepSeries → write_series
laser log ────┘
```

---

## Why this module exists

Every component of this path was written and tested on its own by 2026-08-14:
`demodulate`, `find_trigger_edges`, `analyse_trigger_train`,
`logged_point_times`, `check_alignment`, `map_to_wavelength`, `write_trace_csv`.

**Nothing joined them.** The project passed 180 tests without ever having run
the measurement it exists to make. Joining them found five real defects that no
component test could have seen, because they all live in the seams — see
"What joining it up found", below.

---

## The one real design decision: where the time step comes from

The laser's log is bare wavelengths. `wavelength[i]` belongs to logged point
`i`, with **no timestamps** (`04-hardware-reference.md`). Placing it in time
needs one anchor and one step.

**The anchor is the FIRST TRIGGER EDGE, located once.** Never a count of edges.
If the code counted, a single missed pulse mid-record would shift every
wavelength after it by one step — and the trace would look entirely normal.
That is Q21, and `logged_point_times()` is built to avoid it.

**The step is the trigger train's own SPAN divided by (N − 1)**, where N is the
number of logged points:

```python
step = (edges[-1] - edges[0]) / (n_logged_points - 1)
```

This is Kevin's scheme (2026-08-25) with one refinement. He proposed dividing
the sweep *duration* by the number of logged wavelengths; measuring the span
from the record costs nothing, because the trigger channel is captured anyway,
and it survives a sweep that did not run exactly as long as configured.

### Three consequences worth knowing

**1. It killed Q26.** That question — does the laser log exactly one point per
trigger pulse, which no manual states — mattered only while the step came from
the trigger *interval*. Taking it from the span over (N − 1) never counts
pulses, so a laser logging one point per five pulses gives the same answer.

**2. Watch the (N − 1).** Dividing by N instead is an error of 1 part in N,
which sounds negligible and is **exactly one whole step of accumulated drift by
the far end** — the same off-by-one Q21 warns about, arriving from the other
side. On a 5000-point sweep that is 200 µs at the end of the trace. Pinned by
`test_dividing_by_N_instead_of_N_minus_1_would_shift_the_far_end`.

**3. It makes `check_alignment`'s span test vacuous, and that is not obvious.**
Because the step comes from the span, `table_span` equals `edge_span`
identically — the comparison is a number against itself. **Verified**: a capture
that misses the first two pulses, where every wavelength really is shifted,
still reports a span error of exactly 0.00%. Only the **count** check catches
it. `SweepReduction.describe()` now says so at the point of use, because the
summary otherwise prints two matching spans that read like corroboration.

### What still matters

**Q24 is still live.** The step arithmetic assumes the trigger is periodic in
**TIME**, not in wavelength. `:TRIGger:OUTPut:SETTing` selects which, and the
two manuals document **opposite encodings**. Read it back; never hardcode a
literal. In wavelength-periodic mode the logged points are unevenly spaced in
time and this whole scheme is wrong.

---

## API

| Callable | Does |
|---|---|
| `reduce_sweep(detector, trigger, fs, wavelengths, *, f_ref, ...)` | The whole path. Pure arrays in, `SweepReduction` out. Offline-testable. |
| `measure_sweep(rp, wavelengths, *, f_ref, ...)` | Thin hardware wrapper around `acquire_deep_fast` + `reduce_sweep`. **Never run.** |
| `SweepReduction` | The trace plus everything needed to judge whether to trust it: the `LockinResult`, the edges, the train analysis, the alignment check, and where the step came from. |
| `SweepReduction.describe()` | Human summary. Read this before believing a trace. |
| `SweepReduction.metadata()` | Provenance for the CSV header. |
| `SweepSeries` / `write_series(dir, series)` | The 11-step set: one CSV per sweep plus an index. |

**`f_ref` is required and deliberately not defaulted.** It is 991.821 kHz, not
1 MHz, and a default here would be the easiest place in the codebase to bake in
the round number. Use `plan_two_tone_grid().difference`.

### Why one file per sweep, not one file with a λ₂ column

Considered and rejected. One CSV per sweep plus an index keeps each trace
independently openable, keeps the per-sweep provenance in a header instead of
repeating it on 55,000 rows, and means a failed sweep costs one file rather than
the set.

---

## What joining it up found

All five are silent-failure kind — plausible wrong answers, not crashes.

**1. `find_trigger_edges` returns BOTH polarities, and a real trigger is a
25 µs PULSE.** Each logged point produces a rising edge and a falling edge
25 µs later (TSL-775 p46). A step averaged over both is near **half** the truth,
which compresses the whole wavelength axis 2× and still looks like a clean
trace. Pass `polarity="rising"`. **This would have been live on the first real
sweep.**

**2. The emulator only made SQUARE WAVES**, which hid trap 1 completely.
`make_trigger_sequence` alternates state at every time given — a 50% duty cycle
no laser emits. `make_trigger_pulses` produces the real shape. Pass `n_pulses`:
a train running past the end of the sweep inflates the measured span and
therefore the step.

**3. The recommended TAIL makes the trace legitimately overrun the laser's
table**, and `map_to_wavelength` refuses an overrun by default. Those points are
correctly NaN. `overrun_tol` now defaults to `recommended_tail()` — a real
misalignment is off by a large fraction of a sweep, far more than a tail, so it
is still caught.

**4. Pre-roll shorter than the filter's settling yields NO pre-sweep points.**
Settling trims 113 output points, 22.6 ms. An 8 ms pre-roll leaves nothing, and
`n_before == 0` looks exactly like a mapping bug. Use `recommended_preroll()`
(45.2 ms).

**5. The front end was not per channel** — which made P2 impossible to run as
specified. Fixed in `hardware.py` with `setup_channel()`; see
`04-hardware-reference.md`.

---

## Checking a trace you do not trust

```python
red = reduce_sweep(detector, trigger, fs, wavelengths, f_ref=PLAN.difference)
print(red.describe())
```

Read, in order:

1. **`alignment_ok`.** False means the pulse count and the log row count
   disagree — every wavelength may be shifted. The trace will look normal.
2. **`step_source`.** "measured" is the default; "configured" means it fell back
   to `sweep_seconds`; "given explicitly" means someone overrode it.
3. **`n_missing` from the train.** Missing pulses do not move the wavelengths
   under this scheme, but they say something about the trigger path.
4. **`n_before` / `n_after`.** Pre-roll points before the sweep are expected.
   Points after the table are expected too, bounded by the tail.

---

## Testing

`tests/test_pipeline.py`. The method is Phase 0's: build a synthetic sweep whose
answer is known, push it through the real code, compare. A resonance planted at
a known wavelength comes back at that wavelength, with 11 µV of detector noise
in the record.

The tests cover the **joins**, which is where these failures live and which no
component test could reach.

---

## Not done

- **`measure_sweep` has never touched hardware.** It is written against APIs
  verified in Phase 1, but the wrapper itself is untested in the real world.
- **The emulator's envelope is prescribed, not derived.** It does not model two
  AOM-modulated beams through a nonlinearity — it starts from the assumed
  answer. So the pipeline is tested against the *software's* correctness, not
  against the *physics*. Building the honest version is still open work.
- **The 11-step loop is semi-manual**, because serial control of the stepping
  laser is parked. `scripts/p6_robustness.py --step 2` prompts for each
  wavelength.
