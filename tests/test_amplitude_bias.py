"""
Tests for the unbiased amplitude estimators.

`R = sqrt(X^2 + Y^2)` reads high in noise, and `01-overview.md` has flagged that
since Phase 0 without anything being done about it. It matters more now than it
did then: the photodetector puts the noise floor at ~11 uV, so the interesting
signals sit only a few times above it -- which is precisely the regime where R's
bias stops being a rounding error and starts being a fake signal.
"""

import numpy as np
import pytest

from rp_lockin.dsp import LockinResult, debiased_amplitude

SIGMA = 1.0
N = 40000


def result(amplitude, phase=0.7, sigma=SIGMA, n=N, seed=0):
    """A LockinResult carrying a known amplitude in known noise."""
    rng = np.random.default_rng(seed)
    z = amplitude * np.exp(1j * phase) + (rng.normal(0, sigma, n)
                                          + 1j * rng.normal(0, sigma, n))
    return LockinResult(t=np.arange(n) / 5000.0, X=z.real, Y=z.imag,
                        f_ref=991821.3, fs_out=5000.0,
                        bandwidth=2250.0, settle=113)


def test_R_is_biased_high_when_there_is_no_signal():
    """The problem, stated as a test. With nothing there, R reads sigma*1.25."""
    r = result(amplitude=0.0)
    assert r.R.mean() == pytest.approx(SIGMA * np.sqrt(np.pi / 2), rel=0.02)
    assert r.R.mean() > 1.2 * SIGMA  # a confident reading of a signal that is absent


def test_projection_is_unbiased_when_there_is_no_signal():
    r = result(amplitude=0.0)
    assert abs(r.amplitude().mean()) < 0.05 * SIGMA


def test_projection_recovers_a_weak_signal_without_inflating_it():
    """At A = 2*sigma, R overstates by several percent; the projection does not."""
    a = 2.0 * SIGMA
    r = result(amplitude=a)
    assert r.R.mean() > a * 1.05
    assert r.amplitude().mean() == pytest.approx(a, rel=0.01)


def test_projection_wins_on_TOTAL_error_not_on_variance():
    """
    Worth pinning because it is easy to state wrongly -- and was, in this
    module's first docstring.

    With no signal R's VARIANCE is lower than the projection's: Rayleigh spread
    is 0.655*sigma against the projection's 1.0*sigma. What R carries instead is
    a 1.25*sigma offset that never averages away. So the projection is not
    "quieter"; it trades variance for the removal of that offset, and wins on
    total error wherever the bias matters.
    """
    r = result(amplitude=0.0)
    assert r.R.std() < r.amplitude().std()          # R really is lower-variance
    rmse_R = np.sqrt(np.mean(r.R ** 2))             # truth is zero
    rmse_proj = np.sqrt(np.mean(r.amplitude() ** 2))
    assert rmse_proj < rmse_R                        # but worse overall
    assert r.amplitude().std() == pytest.approx(SIGMA, rel=0.03)


def test_projection_can_go_negative():
    """
    An honest estimator returns negative values when noise happens to point the
    wrong way. R cannot, which is exactly why it is biased.
    """
    r = result(amplitude=0.0)
    assert (r.amplitude() < 0).sum() > 0.4 * N


def test_an_explicit_phase_is_honoured():
    r = result(amplitude=5.0, phase=0.7)
    assert r.amplitude(phase=0.7).mean() == pytest.approx(5.0, rel=0.01)
    # Ninety degrees off, the projection sees essentially nothing -- which is the
    # failure mode to understand before using this on a phase-varying response.
    off = r.amplitude(phase=0.7 + np.pi / 2).mean()
    assert abs(off) < 0.1


def test_debiased_amplitude_helps_only_at_very_low_signal():
    """Below ~1.5 sigma it is a real improvement on R."""
    a = 0.5 * SIGMA
    r = result(amplitude=a)
    assert abs(debiased_amplitude(r.R, SIGMA).mean() - a) < \
        0.2 * abs(r.R.mean() - a)


def test_debiased_amplitude_is_WORSE_than_raw_R_in_the_band_we_care_about():
    """
    The finding that stopped this being recommended, pinned so it is not
    quietly reintroduced.

    sqrt() is concave, so the debiased estimator reads low, and between about 2
    and 6 sigma it overshoots by more than R overshoots the other way. That band
    is exactly where this project's signals are expected: the detector puts the
    floor near 11 uV and a healthy response is a few times that.
    """
    for mult in (2.0, 3.0, 4.0):
        a = mult * SIGMA
        r = result(amplitude=a, seed=int(mult))
        err_R = abs(r.R.mean() - a)
        err_deb = abs(debiased_amplitude(r.R, SIGMA).mean() - a)
        assert err_deb > err_R, f"at {mult} sigma the debias should overcorrect"
        # And the projection beats both by two orders of magnitude.
        assert abs(r.amplitude().mean() - a) < 0.05 * err_R


def test_a_moving_phase_defeats_the_global_angle_but_not_a_local_one():
    """
    Why `smooth` exists. Near a DUT resonance the response phase rotates across
    the sweep, and one global angle then suppresses real signal wherever the
    phase has walked away from it.
    """
    n, a = 20000, 5.0 * SIGMA
    rng = np.random.default_rng(7)
    phase = np.linspace(-1.2, 1.2, n)          # a slow rotation across the sweep
    z = a * np.exp(1j * phase) + (rng.normal(0, SIGMA, n)
                                  + 1j * rng.normal(0, SIGMA, n))
    r = LockinResult(t=np.arange(n) / 5000.0, X=z.real, Y=z.imag,
                     f_ref=991821.3, fs_out=5000.0, bandwidth=2250.0, settle=113)

    glob = r.amplitude().mean()
    local = r.amplitude(smooth=201).mean()
    assert glob < 0.9 * a, "a global angle should lose signal here"
    assert local == pytest.approx(a, rel=0.02), "a local angle should not"


def test_debiased_amplitude_is_honest_about_nothing_being_there():
    r = result(amplitude=0.0)
    naive = r.R.mean()
    fixed = debiased_amplitude(r.R, SIGMA).mean()
    assert naive == pytest.approx(SIGMA * np.sqrt(np.pi / 2), rel=0.02)
    assert fixed < 0.45 * naive
    # It cannot reach zero: clipping at zero is unavoidable and leaves a small
    # positive residue. Documented rather than hidden.
    assert fixed > 0


def test_debiased_amplitude_clips_rather_than_returning_nan():
    assert np.all(debiased_amplitude(np.array([0.0, 0.1, 5.0]), 1.0) >= 0)


def test_debiased_amplitude_rejects_a_negative_sigma():
    with pytest.raises(ValueError, match="non-negative"):
        debiased_amplitude(np.array([1.0]), -1.0)


def test_a_too_short_smoothing_window_brings_the_bias_back():
    """
    The failure mode of `smooth`, and the one worth understanding: with too few
    points the phase reference carries a real share of the same noise it is
    projecting, the two correlate, and R's upward bias returns in a subtler
    form. Longer is safer; the limit is only how fast the response phase moves.
    """
    r = result(amplitude=0.0, n=20000)          # nothing there at all
    honest = r.amplitude(smooth=501).mean()
    too_short = r.amplitude(smooth=3).mean()
    assert abs(honest) < 0.1 * SIGMA
    assert too_short > 0.4 * SIGMA, "a short window should re-inflate the noise"


def test_smooth_rejects_nonsense():
    with pytest.raises(ValueError, match="smooth must be"):
        result(amplitude=1.0).amplitude(smooth=0.5)
