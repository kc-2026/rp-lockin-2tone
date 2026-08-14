"""
Map a demodulated trace onto laser wavelength.

The wavelength axis comes from the laser, not from trigger-edge intervals
(Kevin, 2026-08-14). A Santec TSL-770/775 sweeps, emits a trigger pulse per step,
and logs its own wavelength at each pulse.

**The log is wavelength ONLY -- one value per trigger pulse, with no timestamps.**
Confirmed against both manuals 2026-08-14; an earlier note here said the laser
reported wavelength against time, and it does not. `:READout:DATa?` returns a
bare array and `:READout:POINts?` returns its length.

So the pairing is **by index**: the laser's Nth logged wavelength belongs to the
Nth trigger pulse in the record. Feed that in by passing the recorded edge times
as `table_t` and the laser's array as `table_wavelength`:

    edges = find_trigger_edges(in2_record, fs)
    sweep = map_to_wavelength(result.t, amplitude,
                              edges[0], edges - edges[0], laser_wavelengths)

Pairing by index rather than by time is why `check_alignment` matters so much
here. A miscount does not degrade the answer gradually -- it shifts every
wavelength after the miscount by one step, silently.

Nothing here talks to the laser. The serial command set is not known yet and
**must not be guessed** -- on this project a misspelled SCPI command returns zero
bytes exactly like a correct one, so an invented command set would fail silently.
Everything in this module works from data already in hand: the digitised trigger
train and whatever table the future driver returns.

Two things this module exists to prevent, both of which produce a trace that
looks perfectly normal:

  1. **The off-by-one-trigger error (Q21/U12).** The laser counts time from ITS
     first trigger; we count from OURS. If the acquisition armed late and the
     first pulse in the record is really the laser's second, every wavelength is
     offset by exactly one time step. Same shape, same amplitudes, wrong labels,
     and no internal evidence anywhere in the data. `check_alignment` is the
     guard: the record should hold as many pulses as the table holds rows, and
     they should span the same interval.
  2. **Silent extrapolation.** Interpolating past the end of the laser's table
     invents a wavelength. Points outside the table get NaN and are counted, not
     extrapolated.

And one thing it exists to exploit: because the pulses are evenly spaced in
*time*, the recorded train measures the laser's clock against the board's for
free -- see `analyse_trigger_train`. That turns U11 from an assumption into a
per-sweep measurement, and it is the check that an external timebase is actually
doing its job.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

__all__ = [
    "SweepTrace",
    "TrainAnalysis",
    "AlignmentCheck",
    "analyse_trigger_train",
    "check_alignment",
    "logged_point_times",
    "map_to_wavelength",
]


@dataclass
class TrainAnalysis:
    """What the recorded trigger train says about itself and the two clocks."""

    n_edges: int
    step: float  # measured step between pulses, seconds
    residual_rms: float  # rms deviation from a straight line, seconds
    n_missing: int  # pulses inferred absent from double-length gaps
    gap_indices: tuple[int, ...]  # edge indices followed by a gap
    nominal_step: float | None
    ratio: float | None  # measured / nominal
    ppm: float | None  # (ratio - 1) * 1e6

    def describe(self) -> str:
        lines = [
            f"{self.n_edges} edges, step {self.step * 1e6:.4f} us, "
            f"line-fit residual {self.residual_rms * 1e9:.2f} ns",
        ]
        if self.n_missing:
            lines.append(
                f"{self.n_missing} pulse(s) inferred missing at edge indices "
                f"{self.gap_indices}"
            )
        else:
            lines.append("no missing pulses")
        if self.ratio is not None:
            lines.append(
                f"vs nominal {self.nominal_step * 1e6:.4f} us: "
                f"ratio {self.ratio:.9f} ({self.ppm:+.2f} ppm)"
            )
        else:
            lines.append("no nominal step given, so no clock comparison")
        return "\n".join(lines)


@dataclass
class AlignmentCheck:
    """Whether our first trigger edge is the laser's first trigger."""

    ok: bool
    n_edges: int
    n_table: int
    edge_span: float
    table_span: float
    diagnosis: str

    def describe(self) -> str:
        return (
            f"{'OK' if self.ok else 'SUSPECT'}: {self.n_edges} edges vs "
            f"{self.n_table} table rows; spans {self.edge_span * 1e3:.3f} ms "
            f"vs {self.table_span * 1e3:.3f} ms\n{self.diagnosis}"
        )


@dataclass
class SweepTrace:
    """A demodulated trace with a wavelength for every point."""

    wavelength: np.ndarray  # NaN where the point falls outside the laser's table
    amplitude: np.ndarray
    t_rel: np.ndarray  # seconds from the first trigger edge
    n_outside: int  # points with no wavelength
    n_before: int  # of those, points before the sweep began (pre-roll: expected)
    n_after: int  # of those, points past the end of the table (suspicious)

    @property
    def valid(self) -> np.ndarray:
        """Boolean mask of points that carry a real wavelength."""
        return np.isfinite(self.wavelength)

    def dropna(self) -> tuple[np.ndarray, np.ndarray]:
        """(wavelength, amplitude) for the points that have a wavelength."""
        m = self.valid
        return self.wavelength[m], self.amplitude[m]


def analyse_trigger_train(edges: np.ndarray,
                          nominal_step: float | None = None) -> TrainAnalysis:
    """
    Characterise a fixed-time-step trigger train, and compare the laser's clock
    against the board's if the nominal step is known.

    The step is recovered by fitting a straight line through edge time against
    edge *ordinal*, where the ordinal accounts for any missing pulses. That is
    deliberately not a mean of the intervals: a single missing pulse inflates a
    mean, whereas a line fit through the surviving edges is unaffected as long as
    the ordinals are right.

    Missing pulses are found from intervals that come out near an integer
    multiple of the step, which is what a lost edge looks like -- one interval of
    twice the length rather than a slightly wrong one.

    Raises ValueError on fewer than three edges; two edges give a step with no
    way to tell whether it is right.
    """
    e = np.asarray(edges, dtype=float).ravel()
    if e.size < 3:
        raise ValueError(
            f"need at least 3 edges to characterise a train, got {e.size}. "
            "With two there is no redundancy to check the step against."
        )
    if np.any(np.diff(e) <= 0):
        raise ValueError("edge times must be strictly increasing")

    d = np.diff(e)
    # Median, not mean: robust to the double-length gaps left by lost pulses.
    step0 = float(np.median(d))
    if step0 <= 0:
        raise ValueError("median interval is not positive")

    # How many step-periods each interval spans. A clean interval gives 1.
    mult = np.maximum(np.rint(d / step0).astype(int), 1)
    gap_idx = tuple(int(i) for i in np.flatnonzero(mult > 1))
    n_missing = int(np.sum(mult - 1))

    # Ordinal of each edge in the train the laser actually emitted.
    ordinal = np.concatenate([[0], np.cumsum(mult)]).astype(float)

    slope, intercept = np.polyfit(ordinal, e, 1)
    residual = e - (slope * ordinal + intercept)
    step = float(slope)

    ratio = ppm = None
    if nominal_step is not None:
        if nominal_step <= 0:
            raise ValueError("nominal_step must be positive")
        ratio = step / float(nominal_step)
        ppm = (ratio - 1.0) * 1e6

    return TrainAnalysis(
        n_edges=int(e.size),
        step=step,
        residual_rms=float(np.sqrt(np.mean(residual ** 2))),
        n_missing=n_missing,
        gap_indices=gap_idx,
        nominal_step=None if nominal_step is None else float(nominal_step),
        ratio=ratio,
        ppm=ppm,
    )


def logged_point_times(n_points: int, first_edge: float,
                       step: float) -> np.ndarray:
    """
    When each of the laser's N logged wavelengths happened, in the record's
    time base. **Prefer this over pairing wavelengths to individual edges.**

    Why it exists (Kevin, 2026-08-14). The obvious way to place the laser's log
    in time is to pair its Nth wavelength with the Nth trigger edge found in the
    record. That works, and it is what `check_alignment` guards -- but it makes
    every wavelength depend on having counted every edge, and one miscount
    shifts the whole remainder of the sweep by a step, silently.

    None of that is necessary when the trigger is periodic in TIME. The laser
    emits its pulses on a fixed interval, so the i-th logged point is simply

        t_i = (time of the first edge) + i * step

    Only ONE edge is ever located. A missed edge in the middle of the record
    changes nothing, because nothing is being counted.

    Getting `step` from `analyse_trigger_train(edges).step` rather than from the
    laser's nominal setting also removes the two-clock assumption: the step is
    then measured in the board's own time base, by a line fit through hundreds
    of edges, which a few missing ones do not disturb. That is U11 closed by
    measurement instead of trust.

        train = analyse_trigger_train(edges, nominal_step)
        t = logged_point_times(n_from_readout_points, edges[0], train.step)
        sweep = map_to_wavelength(result.t, amplitude, edges[0],
                                  t - edges[0], laser_wavelengths)

    **This is only valid when the trigger is periodic in time**, not in
    wavelength. On a Santec that is `:TRIGger:OUTPut:SETTing`, whose two manuals
    document opposite encodings -- so read it back rather than assuming (Q24).
    In wavelength-periodic mode the points are unevenly spaced in time and you
    must pair against the edges after all.
    """
    if n_points < 1:
        raise ValueError(f"n_points must be >= 1, got {n_points}")
    if not step > 0:
        raise ValueError(f"step must be positive, got {step}")
    return float(first_edge) + np.arange(n_points, dtype=float) * float(step)


def check_alignment(edges: np.ndarray, table_t: np.ndarray,
                    rel_tol: float = 0.02) -> AlignmentCheck:
    """
    Guard against the off-by-one-trigger error (Q21/U12).

    One pulse per row of the laser's log is not an assumption -- it is how the
    instrument is documented to work, and `:READout:POINts?` returns that row
    count directly, so the comparison below is against a number the laser itself
    reports rather than an inferred one. This still returns a diagnosis rather
    than raising, so a caller can override if a particular setup behaves
    differently.

    The tell for a late start is that the record holds fewer pulses than the
    table holds rows, and the edges span a correspondingly shorter interval.
    Both are checked, because either alone is weak: a count can also fall short
    through lost edges, and a span can shrink through a truncated capture.
    """
    e = np.asarray(edges, dtype=float).ravel()
    tt = np.asarray(table_t, dtype=float).ravel()
    if e.size < 2 or tt.size < 2:
        return AlignmentCheck(
            ok=False, n_edges=int(e.size), n_table=int(tt.size),
            edge_span=0.0, table_span=0.0,
            diagnosis="too few edges or table rows to check anything",
        )

    edge_span = float(e[-1] - e[0])
    table_span = float(tt[-1] - tt[0])
    deficit = int(tt.size) - int(e.size)
    span_err = (edge_span - table_span) / table_span if table_span > 0 else np.inf

    if deficit == 0 and abs(span_err) <= rel_tol:
        return AlignmentCheck(
            True, e.size, tt.size, edge_span, table_span,
            "count and span both match: the first recorded edge is the laser's "
            "first trigger.",
        )

    parts = []
    if deficit > 0:
        parts.append(
            f"the record holds {deficit} fewer pulse(s) than the table has "
            f"rows. If the capture armed late, the first recorded edge is the "
            f"laser's pulse #{deficit} and EVERY wavelength is offset by "
            f"{deficit} time step(s) -- a trace that looks entirely normal. "
            f"Alternatively {deficit} edge(s) were lost in recovery; "
            f"analyse_trigger_train() distinguishes these, since a lost edge "
            f"leaves a double-length gap and a late start does not."
        )
    elif deficit < 0:
        parts.append(
            f"the record holds {-deficit} MORE pulse(s) than the table has "
            f"rows, so something is emitting edges the table does not describe "
            f"-- spurious crossings, or a table that is not one row per pulse."
        )
    if abs(span_err) > rel_tol:
        parts.append(
            f"the edges span {span_err * 100:+.2f}% against the table, outside "
            f"the {rel_tol * 100:.1f}% tolerance."
        )
    return AlignmentCheck(False, e.size, tt.size, edge_span, table_span,
                          " ".join(parts))


def map_to_wavelength(t: np.ndarray, amplitude: np.ndarray, t_first_edge: float,
                      table_t: np.ndarray, table_wavelength: np.ndarray,
                      overrun_tol: float = 0.0) -> SweepTrace:
    """
    Attach a wavelength to every trace point.

    `t` and `t_first_edge` must share a time base. They do if `t` came from
    `LockinResult.t` and `t_first_edge` from `find_trigger_edges()` on the IN2
    record of the same capture: both are referenced to the start of the input
    record. **Prefer that over the board's `Trig:Pos`** -- reading the edge out
    of the recorded data keeps one time base and sidesteps the fixed 1.14-sample
    offset that `Trig:Pos` carries.

    Points outside the table get NaN. Two cases, treated differently because
    they mean different things:

      * **before** the table starts -- normal. Pre-roll deliberately captures
        before the sweep, so these are the pre-sweep samples. Counted, never an
        error.
      * **after** the table ends -- suspicious. The capture outlasted the
        laser's report, which can mean a truncated table or a misalignment.
        Tolerated up to `overrun_tol` seconds, then raises.

    Raises ValueError if the table is not sorted in time, or if the trace and
    the table barely overlap at all -- that is a misalignment, not a mapping.
    """
    t = np.asarray(t, dtype=float).ravel()
    amplitude = np.asarray(amplitude, dtype=float).ravel()
    tt = np.asarray(table_t, dtype=float).ravel()
    wl = np.asarray(table_wavelength, dtype=float).ravel()

    if t.size != amplitude.size:
        raise ValueError(
            f"t and amplitude must be the same length, got {t.size} and "
            f"{amplitude.size}"
        )
    if tt.size != wl.size:
        raise ValueError(
            f"table_t and table_wavelength must be the same length, got "
            f"{tt.size} and {wl.size}"
        )
    if tt.size < 2:
        raise ValueError("the laser table needs at least 2 rows to interpolate")
    if np.any(np.diff(tt) <= 0):
        raise ValueError(
            "table_t must be strictly increasing. Sort the laser's table "
            "before mapping; np.interp does not check and would return "
            "plausible nonsense."
        )

    t_rel = t - float(t_first_edge)

    # Round-off guard, and it is not cosmetic. A trace sampled exactly at the
    # table times gives t_rel = (t0 + tt) - t0, which floating-point leaves a
    # few parts in 1e16 off tt -- enough to put the final point "past the end"
    # and trip the overrun check below on a perfectly aligned sweep. Scale the
    # epsilon to the table's own span so it stays meaningful at any sweep
    # length. np.interp clamps at the endpoints, so an excursion this small
    # takes the boundary wavelength rather than an extrapolated one.
    eps = 1e-9 * (tt[-1] - tt[0])
    before = t_rel < tt[0] - eps
    after = t_rel > tt[-1] + eps
    outside = before | after

    overrun = float(t_rel[after].max() - tt[-1]) if np.any(after) else 0.0
    if overrun > overrun_tol:
        raise ValueError(
            f"the trace runs {overrun * 1e3:.3f} ms past the end of the laser's "
            f"table, beyond the {overrun_tol * 1e3:.3f} ms tolerance. Either "
            f"the table is truncated or the alignment is wrong. Extrapolating "
            f"would invent a wavelength, so this refuses instead; pass "
            f"overrun_tol to accept it and take NaN for those points."
        )

    if int(np.count_nonzero(~outside)) < 2:
        raise ValueError(
            f"trace and table barely overlap: only "
            f"{int(np.count_nonzero(~outside))} of {t.size} points fall inside "
            f"the table. Trace spans {t_rel[0] * 1e3:.3f} to "
            f"{t_rel[-1] * 1e3:.3f} ms relative to the first edge; the table "
            f"spans {tt[0] * 1e3:.3f} to {tt[-1] * 1e3:.3f} ms. Suspect the "
            f"wrong edge was used as t = 0."
        )

    out = np.full(t.size, np.nan)
    out[~outside] = np.interp(t_rel[~outside], tt, wl)

    return SweepTrace(
        wavelength=out,
        amplitude=amplitude,
        t_rel=t_rel,
        n_outside=int(np.count_nonzero(outside)),
        n_before=int(np.count_nonzero(before)),
        n_after=int(np.count_nonzero(after)),
    )
