"""
Drive waveform and frequency-plan validation. No hardware required.

The central property: a repeating buffer must contain whole cycles of the
carrier AND both modulations. Violating it puts a discontinuity at every wrap,
which scatters spurs across the baseband at multiples of the buffer repetition
rate -- precisely where the swept trace lives, and easy to mistake for DUT
structure.
"""

import numpy as np
import pytest

from rp_lockin import make_am_waveform, plan_two_tone
from rp_lockin.constants import ASG_BUFFER_MAX

FS = 250e6


# --------------------------------------------------------------------------
# Single-channel AM waveform
# --------------------------------------------------------------------------

def test_am_buffer_is_minimal_and_exact():
    wave, play = make_am_waveform(80e6, 5e6, FS)
    assert len(wave) == 50
    assert abs(play - 5e6) < 1


def test_am_buffer_wraps_seamlessly():
    wave, _ = make_am_waveform(80e6, 5e6, FS)
    k = np.arange(len(wave), 2 * len(wave))
    nxt = (1 + np.cos(2 * np.pi * 5e6 * k / FS)) * np.cos(2 * np.pi * 80e6 * k / FS)
    nxt = nxt / np.max(np.abs(nxt))
    assert np.max(np.abs(wave - nxt)) < 1e-12


def test_am_spectrum_is_carrier_plus_two_sidebands():
    wave, _ = make_am_waveform(80e6, 5e6, FS)
    rep = np.tile(wave, 400)
    spec = np.abs(np.fft.rfft(rep)) / len(rep) * 2
    freqs = np.fft.rfftfreq(len(rep), 1 / FS)
    lines = sorted(round(freqs[i] / 1e6) for i in np.flatnonzero(spec > 1e-6))
    assert lines == [75, 80, 85]


def test_am_output_stays_in_range():
    wave, _ = make_am_waveform(80e6, 5e6, FS, depth=1.0)
    assert np.max(np.abs(wave)) <= 1.0 + 1e-12


@pytest.mark.parametrize("carrier,mod", [
    (80e6, 5.1234e6),   # no buffer <= 16384 works
    (80e6, 1234567.0),  # ditto
    (200e6, 5e6),       # carrier above Nyquist
])
def test_incommensurate_combinations_rejected(carrier, mod):
    with pytest.raises(ValueError):
        make_am_waveform(carrier, mod, FS)


@pytest.mark.parametrize("carrier,mod,expected_n", [
    (80e6, 5e6, 50),
    (80e6, 6e6, 125),
    (80e6, 3e6, 250),     # fs/mod is NOT an integer here, but a buffer exists
    (77e6, 5e6, 250),     # carrier/mod is NOT an integer either
    (80e6, 4.7e6, 2500),
])
def test_minimal_buffer_found_even_when_fs_over_mod_is_fractional(
        carrier, mod, expected_n):
    """The naive rule N = fs/f_mod only works when that happens to be an
    integer. The real requirement is the smallest N making N*f/fs whole for the
    carrier AND the modulation, which is often larger."""
    wave, play = make_am_waveform(carrier, mod, FS)
    assert len(wave) == expected_n
    assert play == pytest.approx(FS / expected_n)
    for f in (carrier, mod):
        assert len(wave) * f / FS == pytest.approx(round(len(wave) * f / FS), abs=1e-9)


# --------------------------------------------------------------------------
# Two-tone plan
# --------------------------------------------------------------------------

def test_project_default_plan_is_exact():
    p = plan_two_tone(difference=1e6, f1=5e6, carrier=80e6)
    assert p.check() == []
    assert p.buffer_samples == 250
    assert p.difference == pytest.approx(1e6)
    assert p.f1 == pytest.approx(5e6)
    assert p.f2 == pytest.approx(6e6)


def test_project_default_plan_cycle_counts_are_whole():
    p = plan_two_tone(difference=1e6)
    for f, expected in ((p.carrier, 80), (p.f1, 5), (p.f2, 6), (p.difference, 1)):
        assert p.buffer_samples * f / p.fs == pytest.approx(expected, abs=1e-9)


def test_plan_gives_enough_cycles_per_integration_time():
    """Lock-in detection needs >= 5-10 cycles of the difference frequency inside
    one integration time. This is the constraint that sets |f2-f1|."""
    p = plan_two_tone(difference=1e6)
    tau = 1 / (2 * np.pi * (0.9 * 5000 / 2))   # tau implied by 5000 points/s
    assert p.periods_per_tau(tau) >= 10


@pytest.mark.parametrize("diff", [200e3, 250e3, 500e3, 1e6, 2e6])
def test_planner_returns_exact_plans_across_range(diff):
    p = plan_two_tone(difference=diff)
    assert p.check() == []
    assert p.buffer_samples <= ASG_BUFFER_MAX
    assert p.buffer_samples % 25 == 0


def test_planner_refuses_impossible_difference():
    """A difference off the fs/N grid has no exact buffer. Must raise, not
    return something that glitches."""
    with pytest.raises(ValueError, match="grid"):
        plan_two_tone(difference=333333.0, f1=5e6)


def test_both_channel_buffers_share_a_length():
    """Both outputs must use the same buffer length or they drift apart in
    phase, and the difference-frequency phase becomes meaningless."""
    p = plan_two_tone(difference=1e6)
    w1, p1 = make_am_waveform(p.carrier, p.f1, p.fs)
    w2, p2 = make_am_waveform(p.carrier, p.f2, p.fs)
    # Individually minimal buffers may differ; both must divide the plan buffer.
    assert p.buffer_samples % len(w1) == 0
    assert p.buffer_samples % len(w2) == 0
