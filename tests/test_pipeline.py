"""
The end-to-end reduction, checked against known truth.

This is the Phase 0 method -- build a synthetic sweep whose answer is known,
push it through the real code, and compare -- applied to the path that had never
run end to end. Every component here was already tested alone; what these tests
cover is the JOINS, which is where the off-by-one and wrong-step failures live,
and which no component test could see.

The failures being guarded are all silent ones. A wavelength axis that is
shifted by one step, compressed by a factor, or built from the wrong trigger
edges produces a trace of exactly the right shape with the wrong labels, and
nothing downstream can tell.
"""

import numpy as np
import pytest

from rp_lockin import (
    make_trigger_pulses,
    plan_two_tone_grid,
    recommended_preroll,
    recommended_tail,
    reduce_sweep,
    settling_points,
    synthesise_dut_output,
)
from rp_lockin.emulator import find_trigger_edges

PLAN = plan_two_tone_grid(1e6)

# Short and heavily decimated so the suite stays usable. The arithmetic under
# test does not care about the sweep's length, only about the relationships
# between the trigger, the log and the trace.
FS = 250e6 / 16
SWEEP = 40e-3
FIRST_EDGE = 6e-3
N_LOG = 120
STEP = SWEEP / (N_LOG - 1)


def build(noise=0.0, duration=None, first_edge=FIRST_EDGE, n_log=N_LOG,
          centre_frac=0.5, width_frac=0.12, seed=1):
    """A synthetic capture plus the laser log that belongs to it.

    The resonance is placed at a known WAVELENGTH, and the record is built so
    that wavelength really does occur at the corresponding time. That is what
    makes the test a truth check rather than a self-consistency check.
    """
    duration = duration or (first_edge + SWEEP + 6e-3)
    step = SWEEP / (n_log - 1)
    # Wavelength runs 1540 -> 1560 nm linearly across the sweep.
    wavelengths = np.linspace(1540e-9, 1560e-9, n_log)

    # The envelope peaks at `centre_frac` of the way through the SWEEP, which
    # begins at first_edge -- not at the start of the record.
    peak_t = first_edge + centre_frac * SWEEP

    def envelope(t):
        w = width_frac * SWEEP
        return 1.0 / (1.0 + ((t - peak_t) / w) ** 2)

    detector, _truth = synthesise_dut_output(
        PLAN.difference, duration, fs=FS, envelope_fn=envelope,
        noise_rms=noise, amplitude=0.2, seed=seed)
    # EXACTLY one pulse per logged point, and no more: a real laser triggers
    # while it sweeps and then stops. A train running on to the end of the
    # record stretches the measured span and inflates the step.
    trigger = make_trigger_pulses(duration, first_edge, step, width=25e-6,
                                  fs=FS, n_pulses=n_log)
    expected_peak_wl = float(np.interp(centre_frac * SWEEP,
                                       np.arange(n_log) * step, wavelengths))
    return detector, trigger, wavelengths, expected_peak_wl, step


def test_the_resonance_lands_at_the_wavelength_it_was_put_at():
    """The whole point of the pipeline, in one assertion."""
    detector, trigger, wl, expected, _step = build()
    red = reduce_sweep(detector, trigger, FS, wl, f_ref=PLAN.difference)

    w, a = red.trace.dropna()
    found = float(w[int(np.argmax(a))])
    # One logged step is 20 nm / 119 = 0.168 nm. Landing inside a fifth of a
    # step means the axis is not shifted by a step, which is the failure mode.
    assert found == pytest.approx(expected, abs=0.2 * (wl[1] - wl[0]) * 1e9 * 1e-9
                                  + 0.03e-9)


def test_the_step_is_measured_from_the_trigger_span():
    detector, trigger, wl, _e, step = build()
    red = reduce_sweep(detector, trigger, FS, wl, f_ref=PLAN.difference)
    assert red.step == pytest.approx(step, rel=1e-6)
    assert "measured" in red.step_source


def test_dividing_by_N_instead_of_N_minus_1_would_shift_the_far_end():
    """Why the (N-1) in _resolve_step is not a detail.

    The two differ by 1 part in N, which sounds negligible and is exactly one
    whole step of accumulated error by the last point -- the same off-by-one
    Q21 guards, arriving from the other direction.
    """
    _d, _t, wl, _e, step = build()
    wrong = SWEEP / N_LOG
    drift_at_end = (step - wrong) * (N_LOG - 1)
    # The drift works out to exactly SWEEP/N, i.e. one whole step to within
    # 1/N. On a real 5000-point sweep that is 200 us of error at the far end,
    # from a difference of 0.02% in the divisor.
    assert drift_at_end == pytest.approx(wrong, rel=1e-12)
    assert drift_at_end == pytest.approx(step, rel=1.5 / N_LOG)


def test_a_pulse_train_needs_rising_edges_only():
    """Counting both edges of a 25 us pulse halves the apparent step.

    This is the trap that made `polarity` exist. The wrong answer is not an
    error: it is a step roughly half the truth, which compresses the whole
    wavelength axis into half the sweep and still looks like a clean trace.
    """
    _d, trigger, _wl, _e, step = build()
    rising = find_trigger_edges(trigger, FS, polarity="rising")
    both = find_trigger_edges(trigger, FS, polarity="both")
    assert both.size == 2 * rising.size
    assert np.mean(np.diff(rising)) == pytest.approx(step, rel=1e-4)
    # And the naive figure really is the plausible-but-wrong one.
    # Not exactly step/2 -- the alternating 25 us and (step - 25 us) gaps
    # average to step/2 only in the limit -- but close enough that nobody
    # eyeballing it would notice, which is the entire danger.
    assert np.mean(np.diff(both)) == pytest.approx(step / 2, rel=0.02)


def test_the_anchor_is_one_edge_not_a_count_so_a_missing_pulse_is_harmless():
    """Q21, the failure that looks entirely normal.

    Deleting a pulse from the middle must not move any wavelength. If the code
    ever counts edges instead of locating one, every point after the gap shifts
    by a step and the trace still looks perfect.
    """
    detector, trigger, wl, _e, _s = build()
    clean = reduce_sweep(detector, trigger, FS, wl, f_ref=PLAN.difference)

    # Flatten one pulse in the middle of the train.
    edges = find_trigger_edges(trigger, FS, polarity="rising")
    victim = edges[len(edges) // 2]
    lo = int((victim - 5e-6) * FS)
    hi = int((victim + 35e-6) * FS)
    damaged = trigger.copy()
    damaged[lo:hi] = trigger.min()

    hurt = reduce_sweep(detector, damaged, FS, wl, f_ref=PLAN.difference)
    assert hurt.train.n_edges == clean.train.n_edges - 1
    np.testing.assert_allclose(hurt.trace.wavelength, clean.trace.wavelength,
                               rtol=0, atol=1e-15, equal_nan=True)


def test_preroll_points_get_no_wavelength_rather_than_a_wrong_one():
    """Points before the sweep began are outside the laser's table.

    They must come back NaN and counted as 'before', not clamped to the first
    wavelength -- which would put a flat run of real-looking amplitude at
    1540 nm that the DUT never produced.

    The pre-roll here is `recommended_preroll()`, not an arbitrary few ms, and
    that is the point of the test as much as the NaNs are. Filter settling
    trims the first 113 output points -- 22.6 ms -- so a pre-roll SHORTER than
    that leaves no pre-sweep points at all: they are eaten before the mapping
    ever sees them. An 8 ms pre-roll was tried first and produced n_before = 0,
    looking exactly like a mapping bug.
    """
    preroll = recommended_preroll(5000.0)
    assert preroll > settling_points(5000.0)[1], "premise of this test"
    detector, trigger, wl, _e, _s = build(
        first_edge=preroll + 5e-3,
        duration=preroll + 5e-3 + SWEEP + recommended_tail(5000.0))
    red = reduce_sweep(detector, trigger, FS, wl, f_ref=PLAN.difference)
    assert red.trace.n_before > 0
    assert np.all(np.isnan(red.trace.wavelength[:red.trace.n_before]))
    assert red.trace.valid.sum() > 0

    # Points AFTER the table are expected too, and that surprised me: the tail
    # exists so the last sweep point survives group-delay compensation, and it
    # necessarily leaves trace points past the moment the laser stopped
    # logging. They are correctly NaN. What matters is that the overrun is
    # bounded by the tail rather than being some fraction of a sweep, which is
    # what a real misalignment looks like.
    assert red.trace.n_after > 0
    assert red.trace.n_after / 5000.0 <= recommended_tail(5000.0)


def test_it_survives_noise_at_the_detector_floor():
    """11 uV rms is the expected real floor. The peak must still be findable."""
    detector, trigger, wl, expected, _s = build(noise=11e-6)
    red = reduce_sweep(detector, trigger, FS, wl, f_ref=PLAN.difference,
                       amplitude_smooth=5)
    w, a = red.trace.dropna()
    found = float(w[int(np.argmax(a))])
    assert found == pytest.approx(expected, abs=0.5e-9)


def test_metadata_records_where_the_step_came_from():
    """A trace whose axis cannot be traced back is not a result."""
    detector, trigger, wl, _e, _s = build()
    red = reduce_sweep(detector, trigger, FS, wl, f_ref=PLAN.difference)
    meta = red.metadata()
    assert meta["step_source"].startswith("measured")
    assert float(meta["f_ref_Hz"]) == pytest.approx(PLAN.difference)
    assert float(meta["logged_point_step_s"]) == pytest.approx(red.step)
    assert "first_trigger_edge_s" in meta


def test_describe_mentions_the_things_someone_would_check():
    detector, trigger, wl, _e, _s = build()
    text = reduce_sweep(detector, trigger, FS, wl,
                        f_ref=PLAN.difference).describe()
    for token in ("trace points", "first trigger edge", "edges", "nm"):
        assert token in text


# ------------------------------------------------------- refusing to guess


def test_mismatched_record_lengths_are_refused():
    detector, trigger, wl, _e, _s = build()
    with pytest.raises(ValueError, match="same capture"):
        reduce_sweep(detector, trigger[:-10], FS, wl, f_ref=PLAN.difference)


def test_a_silent_trigger_channel_raises_and_says_what_to_check():
    detector, trigger, wl, _e, _s = build()
    with pytest.raises(ValueError, match="no trigger edges"):
        reduce_sweep(detector, np.zeros_like(trigger) - 1.0, FS, wl,
                     f_ref=PLAN.difference)


def test_a_one_row_log_is_refused_rather_than_interpolated():
    detector, trigger, _wl, _e, _s = build()
    with pytest.raises(ValueError, match="at least 2 points"):
        reduce_sweep(detector, trigger, FS, np.array([1550e-9]),
                     f_ref=PLAN.difference)


def test_a_single_edge_with_no_duration_refuses_to_guess_the_step():
    """One edge fixes t=0 but says nothing about how long the sweep was.

    Guessing would scale the entire wavelength axis, so it raises and names the
    argument that would fix it.
    """
    detector, trigger, wl, _e, _s = build()
    lone = np.full_like(trigger, -0.8)
    lone[int(0.2 * lone.size):int(0.2 * lone.size) + int(25e-6 * FS)] = 0.8
    with pytest.raises(ValueError, match="sweep_seconds"):
        reduce_sweep(detector, lone, FS, wl, f_ref=PLAN.difference)


def test_a_single_edge_plus_sweep_seconds_is_enough():
    detector, trigger, wl, _e, step = build()
    lone = np.full_like(trigger, -0.8)
    start = int(FIRST_EDGE * FS)
    lone[start:start + int(25e-6 * FS)] = 0.8
    red = reduce_sweep(detector, lone, FS, wl, f_ref=PLAN.difference,
                       sweep_seconds=SWEEP)
    assert red.step == pytest.approx(step, rel=1e-9)
    assert "configured" in red.step_source


# --------------------------------------------- the 11-step stepped series


def test_a_series_writes_one_file_per_sweep_plus_an_index(tmp_path):
    """Kevin's measurement is 11 steps of laser 2 x one 5000-point sweep each.

    One file per sweep rather than one long file with a lambda2 column: each
    trace stays independently openable, the per-sweep provenance stays in a
    header instead of being repeated on 55,000 rows, and a failed sweep costs
    one file rather than the set.
    """
    from rp_lockin import SweepSeries, write_series

    series = SweepSeries()
    for i in range(11):
        detector, trigger, wl, _e, _s = build(seed=i + 1)
        red = reduce_sweep(detector, trigger, FS, wl, f_ref=PLAN.difference)
        series.add(1550e-9 + i * 0.5e-9, red)

    assert len(series) == 11
    paths = write_series(tmp_path / "run", series)
    assert len(paths) == 12                      # 11 sweeps + the index

    index = (tmp_path / "run" / "sweep_index.csv").read_text()
    assert index.count(chr(10)) == 3 + 11        # 2 comments, header, 11 rows
    assert "1550.000000" in index and "1555.000000" in index

    first = (tmp_path / "run" / "sweep_00.csv").read_text()
    assert "# stepping_wavelength_nm: 1550.000000" in first
    assert "# sweep_index: 0" in first
    # The per-sweep provenance has to survive into every file, or a trace
    # cannot be traced back to how its axis was built.
    assert "# step_source: measured" in first


def test_a_series_refuses_a_stepping_wavelength_in_nanometres():
    """1550 instead of 1.55e-6 would mislabel a whole sweep by 10^9, and 1550
    is a perfectly plausible-looking number to type."""
    from rp_lockin import SweepSeries

    detector, trigger, wl, _e, _s = build()
    red = reduce_sweep(detector, trigger, FS, wl, f_ref=PLAN.difference)
    series = SweepSeries()
    with pytest.raises(ValueError, match="METRES"):
        series.add(1550.0, red)
    assert len(series) == 0


def test_an_empty_series_refuses_to_write_rather_than_making_a_bare_index():
    from rp_lockin import SweepSeries, write_series

    with pytest.raises(ValueError, match="empty"):
        write_series("unused", SweepSeries())


def test_the_series_summary_flags_a_suspect_alignment(tmp_path):
    """A shifted wavelength axis looks entirely normal in the trace, so the
    summary has to say which sweeps to distrust rather than leaving it in a
    per-sweep field nobody opens."""
    from rp_lockin import SweepSeries

    detector, trigger, wl, _e, _s = build()
    good = reduce_sweep(detector, trigger, FS, wl, f_ref=PLAN.difference)
    bad = reduce_sweep(detector, trigger, FS, wl, f_ref=PLAN.difference)
    bad.alignment.ok = False

    series = SweepSeries()
    series.add(1550e-9, good)
    series.add(1551e-9, bad)
    text = series.describe()
    assert "ALIGNMENT SUSPECT" in text
    assert "1 sweep(s) with a suspect alignment: [1]" in text


def test_the_span_check_is_vacuous_when_the_step_came_from_the_span():
    """A guard that reads stronger than it is, pinned so nobody trusts it.

    reduce_sweep derives the step as (edge span)/(N-1), which makes the table's
    span identically equal to the edges' span. check_alignment then compares a
    number against itself and reports 0.00% however wrong the alignment is --
    including a capture that missed the first two pulses, where the wavelengths
    really are all shifted. The COUNT check is what catches that, and the
    summary has to say so rather than showing two matching spans.
    """
    detector, trigger, wl, _e, _s = build()
    edges = find_trigger_edges(trigger, FS, polarity="rising")
    late = trigger.copy()
    late[:int((edges[1] + 1e-4) * FS)] = trigger.min()

    red = reduce_sweep(detector, late, FS, wl, f_ref=PLAN.difference)
    a = red.alignment
    assert not a.ok
    # The span error is zero even though the alignment is genuinely broken.
    assert (a.edge_span - a.table_span) / a.table_span == pytest.approx(0.0,
                                                                       abs=1e-12)
    # So the count is what actually found it.
    assert a.n_table - a.n_edges == 2
    assert "fewer pulse(s)" in a.diagnosis
    assert "span agreement above is automatic" in red.describe()
