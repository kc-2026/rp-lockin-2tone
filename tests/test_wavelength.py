"""
Tests for the laser-wavelength mapping.

The ones that matter most are the off-by-one-trigger tests. That failure produces
a trace of exactly the right shape with every wavelength label shifted by one
time step, and there is no evidence of it anywhere inside the data -- so it can
only be caught by cross-checking against the laser's table, which is what
`check_alignment` does and what these tests pin.
"""

import numpy as np
import pytest

from rp_lockin.wavelength import (
    analyse_trigger_train,
    check_alignment,
    map_to_wavelength,
)

STEP = 1e-3  # 1 ms between trigger pulses
N_PULSES = 1000  # 1 s sweep
WL_START, WL_STOP = 1520.0, 1570.0  # nm


def laser_table(n=N_PULSES, step=STEP, jitter=0.0, seed=0):
    """A Santec-style report: wavelength against time from the first trigger."""
    t = np.arange(n) * step
    if jitter:
        t = t + np.random.default_rng(seed).normal(0, jitter, n)
        t[0] = 0.0
    wl = np.linspace(WL_START, WL_STOP, n)
    return t, wl


def recorded_edges(table_t, t0=0.25, skip=0, drop=()):
    """
    Edges as they would appear in the record.

    `t0` is where the first pulse lands in the record, since the capture starts
    before the sweep. `skip` drops that many pulses from the FRONT -- the late-arm
    failure. `drop` removes pulses from the middle -- lost-edge recovery.
    """
    e = table_t[skip:] + t0
    if drop:
        e = np.delete(e, list(drop))
    return e


# ----------------------------------------------------------- train analysis


def test_train_recovers_step_and_reports_no_missing():
    t, _ = laser_table()
    a = analyse_trigger_train(recorded_edges(t), nominal_step=STEP)
    assert a.n_edges == N_PULSES
    assert a.n_missing == 0
    assert a.gap_indices == ()
    assert a.step == pytest.approx(STEP, rel=1e-12)
    assert a.ppm == pytest.approx(0.0, abs=1e-6)


def test_train_measures_a_clock_offset_in_ppm():
    """The whole point of keeping the train: it measures the two clocks."""
    ppm_true = 120.0
    t, _ = laser_table()
    # The board sees the laser's step stretched by the clock ratio.
    a = analyse_trigger_train(recorded_edges(t * (1 + ppm_true / 1e6)),
                              nominal_step=STEP)
    assert a.ppm == pytest.approx(ppm_true, rel=1e-6)


def test_a_missing_pulse_does_not_bias_the_step():
    """
    A lost edge must not corrupt the clock measurement.

    This is why the step comes from a line fit against corrected ordinals rather
    than from a mean of the intervals -- a mean would absorb the double-length
    gap and report a step that is wrong by 1/N.
    """
    t, _ = laser_table()
    a = analyse_trigger_train(recorded_edges(t, drop=(400,)), nominal_step=STEP)
    assert a.n_missing == 1
    assert a.gap_indices == (399,)
    assert a.step == pytest.approx(STEP, rel=1e-9)
    assert a.ppm == pytest.approx(0.0, abs=1e-3)


def test_several_missing_pulses_are_all_found():
    t, _ = laser_table()
    a = analyse_trigger_train(recorded_edges(t, drop=(100, 400, 401, 700)),
                              nominal_step=STEP)
    # 400 and 401 are adjacent, leaving one triple-length gap.
    assert a.n_missing == 4
    assert a.step == pytest.approx(STEP, rel=1e-9)


def test_train_needs_three_edges():
    with pytest.raises(ValueError, match="at least 3 edges"):
        analyse_trigger_train(np.array([0.0, 1e-3]))


def test_train_rejects_unsorted_edges():
    with pytest.raises(ValueError, match="strictly increasing"):
        analyse_trigger_train(np.array([0.0, 2e-3, 1e-3, 3e-3]))


# -------------------------------------------------------- alignment guard


def test_alignment_passes_when_the_first_edge_is_the_lasers_first():
    t, _ = laser_table()
    c = check_alignment(recorded_edges(t), t)
    assert c.ok
    assert c.n_edges == c.n_table


def test_alignment_catches_a_late_arm():
    """
    THE test. One missed leading pulse offsets every wavelength by one step and
    changes nothing else about the trace.
    """
    t, _ = laser_table()
    c = check_alignment(recorded_edges(t, skip=1), t)
    assert not c.ok
    assert c.n_edges == c.n_table - 1
    assert "armed late" in c.diagnosis


def test_alignment_catches_a_badly_late_arm():
    t, _ = laser_table()
    c = check_alignment(recorded_edges(t, skip=25), t)
    assert not c.ok
    assert "25" in c.diagnosis


def test_alignment_flags_extra_edges():
    t, _ = laser_table()
    e = np.sort(np.append(recorded_edges(t), 0.25 + 0.5 * STEP))
    c = check_alignment(e, t)
    assert not c.ok
    assert "MORE" in c.diagnosis


def test_lost_edge_and_late_arm_are_distinguishable():
    """
    Both show up as a short count, so the count alone cannot separate them.
    A lost edge leaves a double-length gap; a late arm does not. That is what
    lets a caller tell a harmless recovery slip from a corrupted wavelength axis.
    """
    t, _ = laser_table()
    late = analyse_trigger_train(recorded_edges(t, skip=1), nominal_step=STEP)
    lost = analyse_trigger_train(recorded_edges(t, drop=(400,)), nominal_step=STEP)

    assert check_alignment(recorded_edges(t, skip=1), t).n_edges == N_PULSES - 1
    assert check_alignment(recorded_edges(t, drop=(400,)), t).n_edges == N_PULSES - 1

    assert late.n_missing == 0  # no interior gap -> it started late
    assert lost.n_missing == 1  # interior gap -> an edge was lost


# ------------------------------------------------------------- the mapping


def test_mapping_is_exact_on_the_table_points():
    t, wl = laser_table()
    t0 = 0.25
    trace_t = t0 + t  # sample exactly at the pulses
    s = map_to_wavelength(trace_t, np.ones(t.size), t0, t, wl)
    assert s.n_outside == 0
    assert np.allclose(s.wavelength, wl)


def test_preroll_points_get_nan_and_are_counted_as_before():
    """Pre-roll before the sweep is normal, not an error."""
    t, wl = laser_table()
    t0 = 0.25
    trace_t = np.linspace(0.0, t0 + t[-1], 5000)
    s = map_to_wavelength(trace_t, np.ones(5000), t0, t, wl)
    assert s.n_before > 0
    assert s.n_after == 0
    assert s.n_outside == s.n_before
    assert np.all(np.isnan(s.wavelength[trace_t < t0]))
    assert np.all(np.isfinite(s.wavelength[trace_t >= t0]))


def test_running_past_the_table_refuses_rather_than_extrapolating():
    t, wl = laser_table()
    t0 = 0.25
    trace_t = np.linspace(t0, t0 + t[-1] + 0.05, 5000)
    with pytest.raises(ValueError, match="past the end"):
        map_to_wavelength(trace_t, np.ones(5000), t0, t, wl)


def test_overrun_is_allowed_when_asked_for_explicitly():
    t, wl = laser_table()
    t0 = 0.25
    trace_t = np.linspace(t0, t0 + t[-1] + 0.05, 5000)
    s = map_to_wavelength(trace_t, np.ones(5000), t0, t, wl, overrun_tol=0.1)
    assert s.n_after > 0
    assert np.all(np.isnan(s.wavelength[trace_t - t0 > t[-1]]))


def test_wrong_edge_as_zero_is_caught_by_the_overlap_check():
    """A grossly wrong t=0 leaves almost no overlap, and must not map quietly."""
    t, wl = laser_table()
    with pytest.raises(ValueError, match="barely overlap"):
        map_to_wavelength(0.25 + t, np.ones(t.size), 0.25 + 3.0, t, wl)


def test_unsorted_table_refuses():
    t, wl = laser_table()
    bad = t.copy()
    bad[500], bad[501] = bad[501], bad[500]
    with pytest.raises(ValueError, match="strictly increasing"):
        map_to_wavelength(0.25 + t, np.ones(t.size), 0.25, bad, wl)


def test_off_by_one_trigger_shifts_wavelength_but_not_shape():
    """
    Why `check_alignment` has to exist.

    Map the same trace with the correct t=0 and with the next pulse as t=0. The
    amplitudes are untouched and the wavelength axis is shifted by exactly one
    step's worth of wavelength. Nothing inside the mapped data reveals which is
    right.
    """
    t, wl = laser_table()
    t0 = 0.25
    trace_t = t0 + t[:-1]
    amp = np.sin(np.linspace(0, 8, t.size - 1)) + 2.0

    good = map_to_wavelength(trace_t, amp, t0, t, wl)
    bad = map_to_wavelength(trace_t, amp, t0 - STEP, t, wl)

    assert np.array_equal(good.amplitude, bad.amplitude)
    dwl = (WL_STOP - WL_START) / (N_PULSES - 1)
    assert np.allclose(bad.wavelength - good.wavelength, dwl)
    # Both look entirely reasonable on their own.
    assert good.n_outside == 0 and bad.n_outside == 0


def test_mismatched_lengths_refuse():
    t, wl = laser_table()
    with pytest.raises(ValueError, match="same length"):
        map_to_wavelength(0.25 + t, np.ones(t.size - 1), 0.25, t, wl)
    with pytest.raises(ValueError, match="same length"):
        map_to_wavelength(0.25 + t, np.ones(t.size), 0.25, t, wl[:-1])


def test_end_to_end_with_a_real_demodulated_trace():
    """
    The whole path on synthetic but realistic data: a 5000-point trace at
    5000 Sa/s over a 1 s sweep, pre-roll included, checked and mapped.
    """
    t, wl = laser_table()
    t0 = 0.0432  # 43.2 ms of pre-roll, as H6.4 used
    edges = recorded_edges(t, t0=t0)

    align = check_alignment(edges, t)
    assert align.ok, align.describe()

    train = analyse_trigger_train(edges, nominal_step=STEP)
    assert train.n_missing == 0
    assert abs(train.ppm) < 1e-3

    trace_t = np.arange(0.0, t0 + t[-1], 1 / 5000.0)
    amp = 30e-6 * (1.0 + 0.5 * np.sin(2 * np.pi * 3 * trace_t))
    s = map_to_wavelength(trace_t, amp, t0, t, wl)

    w, a = s.dropna()
    assert w.size == a.size
    assert s.n_before == int(np.count_nonzero(trace_t < t0))
    assert WL_START <= w.min() and w.max() <= WL_STOP
    assert np.all(np.diff(w) > 0)  # a sweep gives a monotonic axis
