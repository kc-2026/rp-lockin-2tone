"""
The end-to-end reduction: one captured sweep in, one wavelength trace out.

Every piece of this path already existed and was tested on its own -- demodulate,
find_trigger_edges, analyse_trigger_train, logged_point_times, check_alignment,
map_to_wavelength, write_trace_csv. **Nothing joined them**, which is why the
project could pass 180 tests without ever having run the measurement it exists
to make. This module is that join.

    reduction = reduce_sweep(detector, trigger, fs, wavelengths)
    print(reduction.describe())
    write_trace_csv("sweep.csv", reduction.trace.wavelength,
                    reduction.trace.amplitude, metadata=reduction.metadata())

Deliberately split from the hardware. `reduce_sweep` takes arrays, so it can be
checked against the emulator with known truth, which is how three real bugs were
caught in Phase 0. `measure_sweep` is the thin wrapper that gets those arrays
off the board, and is the only part that needs anything plugged in.

WHERE THE TIME STEP COMES FROM, which is the one real design decision here
-------------------------------------------------------------------------
The laser's log is bare wavelengths -- `wavelength[i]` belongs to logged point
i, with no timestamps (docs/04-hardware-reference.md). Placing it in time needs
one anchor and one step:

  * the anchor is the FIRST TRIGGER EDGE, located once. Never a count of
    edges -- a missed pulse mid-record would then shift every wavelength after
    it by a step, silently (Q21).
  * the step, by default, is **the trigger train's own span divided by
    (N - 1)**, where N is the number of logged points.

That default is Kevin's (2026-08-25), with one refinement. He proposed dividing
the sweep DURATION by the number of logged wavelengths; measuring the span from
the record instead costs nothing, because the trigger channel is captured
anyway, and it survives the sweep not being exactly as long as configured.

**It also kills Q26.** That question -- does the laser log exactly one point per
trigger pulse, which no manual states -- mattered only while the step came from
the trigger INTERVAL. Taking it from the span over (N - 1) never counts pulses,
so a laser logging one point per five pulses gives the same answer.

Watch the (N - 1). Dividing by N instead is a 1-in-5000 error on a 5000-point
sweep, which sounds like nothing and is exactly one step of accumulated drift by
the end -- the same off-by-one Q21 warns about, arriving from the other side.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

import numpy as np

from .dsp import LockinResult, demodulate
from .output import write_trace_csv
from .emulator import find_trigger_edges
from .planning import recommended_tail
from .wavelength import (
    AlignmentCheck,
    SweepTrace,
    TrainAnalysis,
    analyse_trigger_train,
    check_alignment,
    logged_point_times,
    map_to_wavelength,
)

__all__ = ["SweepReduction", "SweepSeries", "reduce_sweep",
           "measure_sweep", "write_series"]


@dataclass
class SweepReduction:
    """A reduced sweep, plus everything needed to judge whether to trust it."""

    trace: SweepTrace
    result: LockinResult
    edges: np.ndarray
    train: TrainAnalysis | None   # None when too few edges to characterise
    alignment: AlignmentCheck
    first_edge: float
    step: float
    step_source: str

    @property
    def n_points(self) -> int:
        return int(self.trace.amplitude.size)

    def metadata(self) -> dict:
        """Provenance for the CSV header. Numbers, not prose."""
        return {
            "f_ref_Hz": f"{self.result.f_ref:.6f}",
            "output_rate_Sa_s": f"{self.result.fs_out:.6f}",
            "bandwidth_Hz": f"{self.result.bandwidth:.4f}",
            "settling_samples_trimmed": str(self.result.settle),
            "first_trigger_edge_s": f"{self.first_edge:.9f}",
            "logged_point_step_s": f"{self.step:.12f}",
            "step_source": self.step_source,
            "trigger_edges_found": str(self.edges.size),
            "trigger_pulses_missing": (
                str(self.train.n_missing) if self.train else "unknown"),
            "alignment_ok": str(self.alignment.ok),
            "points_without_wavelength": str(self.trace.n_outside),
        }

    def describe(self) -> str:
        t = self.trace
        lines = [
            f"{self.n_points} trace points, "
            f"{int(t.valid.sum())} carrying a wavelength",
            f"demodulated at {self.result.f_ref:.3f} Hz -> "
            f"{self.result.fs_out:.1f} Sa/s, bandwidth "
            f"{self.result.bandwidth:.1f} Hz",
            f"first trigger edge at {self.first_edge * 1e3:.4f} ms; "
            f"logged-point step {self.step * 1e6:.4f} us ({self.step_source})",
            self.train.describe() if self.train else
            f"{self.edges.size} edge(s): too few to characterise the train",
            self.alignment.describe(),
        ]
        if t.n_outside:
            lines.append(
                f"{t.n_outside} point(s) without a wavelength: "
                f"{t.n_before} before the sweep began (pre-roll, expected), "
                f"{t.n_after} after the table ended"
            )
        wl, amp = t.dropna()
        if wl.size:
            lines.append(
                f"wavelength {wl.min() * 1e9:.4f} to {wl.max() * 1e9:.4f} nm; "
                f"amplitude {amp.min():.4g} to {amp.max():.4g} V"
            )
        return "\n".join(lines)


def reduce_sweep(detector: np.ndarray,
                 trigger: np.ndarray,
                 fs: float,
                 wavelengths: np.ndarray,
                 *,
                 f_ref: float,
                 output_rate: float = 5000.0,
                 bandwidth: float | None = None,
                 step: float | None = None,
                 sweep_seconds: float | None = None,
                 nominal_step: float | None = None,
                 trigger_threshold: float = 0.0,
                 trigger_polarity: str = "rising",
                 min_separation: float = 1e-6,
                 amplitude_smooth: int | None = None,
                 overrun_tol: float | None = None) -> SweepReduction:
    """
    Turn one captured sweep into amplitude against wavelength.

    Parameters
    ----------
    detector    Raw IN1 samples -- the photodetector.
    trigger     Raw IN2 samples -- the laser's trigger output, SAME capture.
                Sharing the capture is what puts both on one time base; do not
                pass a trigger record from a different acquisition.
    fs          Sample rate of both, Hz.
    wavelengths The laser's log, in METRES, in order. From
                `SantecTSL.read_wavelengths()`.
    f_ref       Demodulation frequency. Required, and deliberately not
                defaulted: it is 991.821 kHz rather than 1 MHz, and a default
                here would be the easiest place in the codebase to bake in the
                round number. Use `plan_two_tone_grid().difference`.
    step        Seconds between logged points. Normally left None and measured.
    sweep_seconds
                Fallback if the trigger train cannot supply a span. Divided by
                (N - 1), not N -- see the module docstring.
    nominal_step
                What the laser was CONFIGURED to step by, if known. Only used to
                report the clock ratio; never used to compute anything.
    trigger_polarity
                "rising" by default, because the real trigger is a pulse and
                counting both edges of a pulse halves the apparent step.
    amplitude_smooth
                Passed to `LockinResult.amplitude()`. Use when the response
                phase moves across the sweep.
    overrun_tol How far the trace may legitimately run past the end of the
                laser's table, seconds. None (the default) uses
                `recommended_tail()`, which is the RIGHT answer rather than a
                convenience: the capture is deliberately given a tail so the
                last sweep point survives the filter's group-delay
                compensation, and that tail necessarily produces trace points
                after the laser stopped logging. Those points are correctly
                NaN. `map_to_wavelength` refuses an overrun by default to catch
                misalignment, and a misalignment is off by a large fraction of
                a sweep -- far more than a tail -- so it is still caught.

    Raises rather than degrading: no trigger edge at all, a table too short to
    interpolate, or a trace that barely overlaps the table are all failures that
    would otherwise produce a plausible, wrong trace.
    """
    detector = np.asarray(detector, dtype=float).ravel()
    trigger = np.asarray(trigger, dtype=float).ravel()
    wl = np.asarray(wavelengths, dtype=float).ravel()

    if detector.size != trigger.size:
        raise ValueError(
            f"detector and trigger must come from the same capture, got "
            f"{detector.size} and {trigger.size} samples. Different lengths "
            f"mean different records, and their time bases do not relate."
        )
    if wl.size < 2:
        raise ValueError(
            f"the laser log needs at least 2 points to interpolate, got "
            f"{wl.size}. An empty or single-row log usually means the sweep "
            f"never ran, or :READout:DATa? was read before it finished."
        )

    edges = find_trigger_edges(trigger, fs, threshold=trigger_threshold,
                               min_separation=min_separation,
                               polarity=trigger_polarity)
    if edges.size == 0:
        raise ValueError(
            "no trigger edges found on the trigger channel. Check IN2 is on "
            "HV (the laser trigger is 3.3 V and overloads the +/-1 V range), "
            "that the trigger output mode is Step, and that the threshold "
            f"({trigger_threshold} V) sits inside the pulse's swing."
        )
    first_edge = float(edges[0])

    # Diagnostics only. The step used below does NOT come from this fit -- see
    # the module docstring on why counting pulses is the thing to avoid. It
    # needs three edges for its redundancy check, and a reduction with fewer
    # than that is still a valid reduction (given sweep_seconds), so a short
    # train costs the diagnostic rather than the measurement.
    try:
        train = analyse_trigger_train(edges, nominal_step)
    except ValueError:
        train = None

    step, step_source = _resolve_step(step, sweep_seconds, edges, wl.size)

    if overrun_tol is None:
        overrun_tol = recommended_tail(output_rate, bandwidth)

    result = demodulate(detector, fs, f_ref, bandwidth=bandwidth,
                        output_rate=output_rate)
    amplitude = result.amplitude(smooth=amplitude_smooth)

    table_t = logged_point_times(wl.size, 0.0, step)
    alignment = check_alignment(edges, table_t)
    trace = map_to_wavelength(result.t, amplitude, first_edge, table_t, wl,
                              overrun_tol=overrun_tol)

    return SweepReduction(trace=trace, result=result, edges=edges, train=train,
                          alignment=alignment, first_edge=first_edge,
                          step=step, step_source=step_source)


def _resolve_step(step: float | None, sweep_seconds: float | None,
                  edges: np.ndarray, n_points: int) -> tuple[float, str]:
    """Pick the seconds-per-logged-point, and say where it came from.

    Order matters and is deliberate: an explicit value wins, then the measured
    span, then a configured duration. The measured span is preferred over the
    configured duration because it is what the instrument ACTUALLY did, and a
    sweep that ran 2% short would otherwise stretch every wavelength by 2%
    without anything looking wrong.
    """
    if step is not None:
        if not step > 0:
            raise ValueError(f"step must be positive, got {step}")
        return float(step), "given explicitly"

    if n_points < 2:                      # already guarded, kept honest anyway
        raise ValueError("need at least 2 logged points to derive a step")

    if edges.size >= 2:
        span = float(edges[-1] - edges[0])
        if span > 0:
            return span / (n_points - 1), (
                f"measured: {span * 1e3:.4f} ms of trigger train over "
                f"{n_points - 1} intervals")

    if sweep_seconds is not None:
        if not sweep_seconds > 0:
            raise ValueError(
                f"sweep_seconds must be positive, got {sweep_seconds}")
        return float(sweep_seconds) / (n_points - 1), (
            f"configured: {sweep_seconds} s over {n_points - 1} intervals")

    raise ValueError(
        "cannot determine the logged-point step: only one trigger edge was "
        "found and no sweep_seconds or step was given. With a single edge the "
        "sweep's duration is unknown, and guessing it would scale the whole "
        "wavelength axis. Pass sweep_seconds=<the laser's sweep time>."
    )


def measure_sweep(rp, wavelengths, *, f_ref: float,
                  n_samples: int, decimation: int,
                  trigger: str = "CH2_PE",
                  trigger_level: float = 1.0,
                  preroll_samples: int = 0,
                  output_rate: float = 5000.0,
                  **reduce_kw) -> SweepReduction:
    """
    Capture one sweep from the board and reduce it. NEEDS HARDWARE.

    A thin wrapper, on purpose: everything that can be wrong about the physics
    lives in `reduce_sweep`, which runs offline against known truth. This part
    only moves bytes.

    `wavelengths` is the laser's log for THIS sweep, already read. Reading it
    here would put a serial transport inside the capture path, and whether the
    log can even be read while a sweep runs is still unknown (P1.4).

    NOTE the trigger defaults: CH2_PE, because the laser's trigger is wired to
    IN2, and a 1.0 V level because that trigger swings 0 to 3.3 V. IN2 must be
    on HV for that; on LV it overloads. Gain is per channel, so IN1 stays on LV.
    """
    detector, trig = rp.acquire_deep_fast(
        n_samples=n_samples, decimation=decimation, channels=(1, 2),
        trigger=trigger, trigger_level=trigger_level,
        preroll_samples=preroll_samples)
    fs = rp.base_rate / decimation
    return reduce_sweep(detector, trig, fs, wavelengths, f_ref=f_ref,
                        output_rate=output_rate, **reduce_kw)


# ------------------------------------------------------------- the series


@dataclass
class SweepSeries:
    """Several sweeps, each tagged with the STEPPING laser's wavelength.

    Kevin's measurement (2026-08-25) is a two-dimensional one: laser 2 steps
    through 11 discrete wavelengths, and at each the fine laser sweeps 5000
    points. The result is an 11 x 5000 map of intermodulation response against
    both wavelengths.

    The two axes are not symmetric and this class does not pretend otherwise.
    The swept axis comes from the laser's own log and differs slightly between
    sweeps; the stepped axis is a scalar read once the laser settled. Nothing
    is interpolated onto a common grid, because that would be a judgement about
    the data rather than a record of it -- each sweep keeps its own wavelengths.
    """

    reductions: list = field(default_factory=list)
    labels: list = field(default_factory=list)   # stepping wavelength, metres

    def add(self, label_m: float, reduction: SweepReduction) -> None:
        """Record one sweep taken at stepping wavelength `label_m` METRES."""
        label_m = float(label_m)
        # Same units guard as everywhere else: 1550 instead of 1.55e-6 is a
        # plausible-looking number that would mislabel a whole sweep by 10^9.
        if not 1.0e-7 < label_m < 1.0e-5:
            raise ValueError(
                f"the stepping wavelength must be in METRES, got {label_m!r}. "
                f"A C-band value is ~1.55e-6, not 1550."
            )
        self.reductions.append(reduction)
        self.labels.append(label_m)

    def __len__(self) -> int:
        return len(self.reductions)

    def describe(self) -> str:
        if not self.reductions:
            return "empty series"
        lines = [f"{len(self)} sweeps, stepping laser "
                 f"{min(self.labels) * 1e9:.4f} to {max(self.labels) * 1e9:.4f} nm"]
        for lab, red in zip(self.labels, self.reductions):
            wl, amp = red.trace.dropna()
            flag = "" if red.alignment.ok else "   ** ALIGNMENT SUSPECT **"
            lines.append(
                f"  lambda2 {lab * 1e9:9.4f} nm: {wl.size:5d} points, "
                f"{wl.min() * 1e9:.3f}-{wl.max() * 1e9:.3f} nm, "
                f"peak {amp.max():.4g} V{flag}")
        bad = [i for i, r in enumerate(self.reductions) if not r.alignment.ok]
        if bad:
            lines.append(f"  {len(bad)} sweep(s) with a suspect alignment: "
                         f"{bad}. Their wavelengths may all be shifted.")
        return chr(10).join(lines)


def write_series(directory, series: SweepSeries, prefix: str = "sweep") -> list:
    """Write one CSV per sweep plus an index. Returns the paths written.

    One file per sweep rather than one long file with a lambda2 column, which
    was the alternative considered: each trace stays independently openable,
    the per-sweep provenance stays in the header where it belongs rather than
    being repeated on 55,000 rows, and a sweep that fails costs one file rather
    than the set.

    The index names every sweep with its stepping wavelength, so the set is
    reassemblable without reading eleven headers.
    """
    if not series.reductions:
        raise ValueError("nothing to write: the series is empty")
    os.makedirs(directory, exist_ok=True)

    paths = []
    index_rows = []
    width = max(2, len(str(len(series) - 1)))
    for i, (label, red) in enumerate(zip(series.labels, series.reductions)):
        name = f"{prefix}_{i:0{width}d}.csv"
        path = os.path.join(directory, name)
        meta = {"sweep_index": str(i),
                "stepping_wavelength_nm": f"{label * 1e9:.6f}"}
        meta.update(red.metadata())
        rows = write_trace_csv(path, red.trace.wavelength,
                               red.trace.amplitude, metadata=meta)
        paths.append(path)
        index_rows.append((i, label * 1e9, rows, name, red.alignment.ok))

    index_path = os.path.join(directory, f"{prefix}_index.csv")
    with open(index_path, "w", encoding="utf-8", newline="") as fh:
        lines = ["# index for a stepped sweep series",
                 f"# {len(series)} sweeps",
                 "sweep_index,stepping_wavelength_nm,rows,file,alignment_ok"]
        lines += [f"{i},{nm:.6f},{rows},{name},{ok}"
                  for i, nm, rows, name, ok in index_rows]
        fh.write(chr(10).join(lines) + chr(10))
    paths.append(index_path)
    return paths
