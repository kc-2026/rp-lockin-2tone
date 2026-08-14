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

from rp_lockin import (asg_grid, make_am_table, make_am_waveform,
                       plan_two_tone, plan_two_tone_grid, snap_to_asg_grid)
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


# --------------------------------------------------------------------------
# The real ASG model
#
# These exist because the original code modelled a generator that does not
# exist: it assumed loading N samples and playing at fs/N replays those N
# samples. The real ASG always traverses a fixed 16384-entry table. Loading a
# 50-sample buffer produced NO OUTPUT AT ALL on the bench board -- min -2,
# max +4 counts. Measured 2026-08-12 against OS 2.00.
#
# Do not delete these to make a refactor pass. Offline tests could not have
# caught the original bug, but they can stop it coming back.
# --------------------------------------------------------------------------

def test_asg_grid_is_fs_over_the_table_size():
    """Every emittable frequency is a multiple of this. At 250 MS/s the table
    period is 65.536 us, giving 15258.7890625 Hz."""
    assert asg_grid(FS) == pytest.approx(FS / 16384)
    assert asg_grid(FS) == pytest.approx(15258.7890625)


def test_table_is_always_the_full_16384_entries():
    """The length is not negotiable. A short table is skipped over by the phase
    accumulator and emits nothing."""
    t = make_am_table(80e6, 5e6, FS)
    assert len(t.samples) == ASG_BUFFER_MAX


def test_play_frequency_steps_one_entry_per_clock():
    """This is the whole trick: at fs/16384 the accumulator advances exactly
    one table entry per DAC clock, so the table is reproduced at full rate.
    Any other frequency undersamples it."""
    t = make_am_table(80e6, 5e6, FS)
    assert t.play_freq == pytest.approx(FS / ASG_BUFFER_MAX)
    assert t.play_freq * len(t.samples) == pytest.approx(FS)


def test_snapped_frequencies_have_whole_cycles_per_table():
    """The property that makes the wrap seamless. Exact, not approximate --
    the table is built from integer cycle counts."""
    t = make_am_table(80e6, 5e6, FS)
    for cycles in (t.carrier_cycles, t.mod_cycles):
        assert cycles == int(cycles)
    assert t.carrier_cycles == 5243      # 80 MHz -> 80.0018 MHz
    assert t.mod_cycles == 328           # 5 MHz  -> 5.004883 MHz


def test_snap_error_is_at_most_half_a_grid_step():
    grid = asg_grid(FS)
    for target in (80e6, 5e6, 6e6, 1e6, 12.3456e6):
        got, _ = snap_to_asg_grid(target, FS)
        assert abs(got - target) <= grid / 2 + 1e-9


def test_table_wraps_seamlessly():
    """Continue the table one period on; it must line up exactly. This is the
    property whose violation sprays a 15.26 kHz spur comb across the baseband
    where the swept trace lives."""
    t = make_am_table(80e6, 5e6, FS)
    n = ASG_BUFFER_MAX
    k = np.arange(n, 2 * n)
    env = 1.0 + np.cos(2 * np.pi * t.mod_cycles * k / n)
    nxt = env * np.cos(2 * np.pi * t.carrier_cycles * k / n)
    nxt = nxt / np.max(np.abs(nxt))
    # 1e-9, not 1e-12: the second period is evaluated at phase arguments up to
    # 2*pi*5243*32767/16384 ~ 6.6e6 radians, where float64 spacing alone costs
    # ~1e-9. That is precision loss in this test, not roughness in the table.
    # A genuine wrap discontinuity is order 1, so the margin is still nine
    # orders of magnitude.
    assert np.max(np.abs(t.samples - nxt)) < 1e-9


def test_table_spectrum_is_carrier_plus_two_sidebands():
    t = make_am_table(80e6, 5e6, FS)
    spec = np.abs(np.fft.rfft(t.samples))
    lines = sorted(np.flatnonzero(spec > 1e-6 * spec.max()))
    assert lines == [t.carrier_cycles - t.mod_cycles,
                     t.carrier_cycles,
                     t.carrier_cycles + t.mod_cycles]


def test_table_stays_in_range():
    t = make_am_table(80e6, 5e6, FS, depth=1.0)
    assert np.max(np.abs(t.samples)) <= 1.0 + 1e-12


def test_grid_plan_difference_is_exact_not_accumulated():
    """The difference must be a whole number of grid steps. Deriving it from
    two independently snapped tones would carry both rounding errors into the
    lock-in frequency."""
    p = plan_two_tone_grid(difference=1e6, f1=5e6, carrier=80e6, fs=FS)
    steps = (p.f2 - p.f1) / asg_grid(FS)
    assert steps == pytest.approx(round(steps), abs=1e-9)
    assert p.f2_cycles - p.f1_cycles == 65
    assert p.difference == pytest.approx(65 * asg_grid(FS))


def test_grid_plan_matches_the_agreed_operating_point():
    """The frequencies Kevin signed off on 2026-08-12. If these change, the
    drive frequencies changed, and that is a decision not a refactor."""
    p = plan_two_tone_grid(difference=1e6, f1=5e6, carrier=80e6, fs=FS)
    assert p.carrier_cycles == 5243
    assert p.f1_cycles == 328
    assert p.f2_cycles == 393
    assert p.carrier == pytest.approx(80.0018310546875e6)
    assert p.difference == pytest.approx(991821.28, abs=1.0)


def test_grid_plan_keeps_enough_cycles_per_integration_time():
    """R4 wants >= 5-10 cycles of the difference frequency per tau. The move
    onto the grid drops it from 71 to ~70, which is immaterial -- but check,
    do not assume."""
    p = plan_two_tone_grid(difference=1e6)
    tau = 1 / (2 * np.pi * (0.9 * 5000 / 2))
    assert p.periods_per_tau(tau) >= 10


def test_grid_plan_refuses_a_sideband_above_nyquist():
    with pytest.raises(ValueError, match="Nyquist"):
        plan_two_tone_grid(difference=1e6, f1=5e6, carrier=120e6, fs=FS)
