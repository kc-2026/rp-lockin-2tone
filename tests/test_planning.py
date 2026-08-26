"""
Capture planning, and specifically that its ADVICE matches the settled plan.

These exist because there were none, and the gap was not theoretical:
`describe_capture_plan()` recommended decimation 2 plus a device-tree edit for
eleven days after both had been decided against. Nothing caught it, because
nothing tested what the function actually says -- only that it returned a
string, and not even that.

A planner that recommends a rejected board change is worse than no planner: it
carries the authority of being in the codebase.
"""

import numpy as np
import pytest

from rp_lockin import describe_capture_plan, plan_capture, plan_two_tone_grid
from rp_lockin.constants import DMA_REGION_MB, MAX_DMA_MB
from rp_lockin.planning import FAST_READ_MB_PER_S, SCPI_MB_PER_S, recommend

F_LOCKIN = plan_two_tone_grid(1e6).difference


def options(sweep=1.0, channels=2):
    return plan_capture(sweep, F_LOCKIN, n_channels=channels)


def test_the_recommendation_for_the_real_sweep_is_decimation_8():
    """The settled operating point. H6.2-H6.5 and H7.1 all ran this way."""
    best = recommend(options())
    assert best is not None
    assert best.decimation == 8
    assert best.megabytes <= DMA_REGION_MB


def test_the_plan_does_not_propose_the_rejected_device_tree_move():
    """The move was considered and rejected once the wavelength axis moved to
    the laser's log. A plan that still proposes it is stale advice with the
    codebase's authority behind it."""
    text = describe_capture_plan(1.0, F_LOCKIN)
    for forbidden in ("dtraw.dts", "devicetree.dtb", "reboot", "dtc -I dts"):
        assert forbidden not in text, f"still proposing the move: {forbidden!r}"
    assert "No board changes needed" in text


def test_planning_uses_the_region_that_exists_not_the_hypothetical_one():
    """DMA_REGION_MB is what is reserved; MAX_DMA_MB is what a rejected change
    would have bought. Planning against the latter is what produced the stale
    recommendation."""
    assert DMA_REGION_MB < MAX_DMA_MB
    # Decimation 2 fits the hypothetical ceiling and not the real one, which is
    # exactly the pair that made the bug possible.
    dec2 = next(o for o in options() if o.decimation == 2)
    assert dec2.megabytes > DMA_REGION_MB
    assert dec2.megabytes <= MAX_DMA_MB
    assert recommend(options()).decimation != 2


def test_a_1s_two_channel_capture_at_decimation_8_nearly_fills_the_region():
    """H6.2 measured 125.2 MB in the 128 MiB region, 97.8% full. The margin is
    thin enough that pre-roll matters, so the arithmetic should say so."""
    dec8 = next(o for o in options() if o.decimation == 8)
    assert dec8.megabytes == pytest.approx(119, abs=1)
    assert dec8.megabytes / DMA_REGION_MB > 0.9


def test_transfer_is_estimated_over_the_path_that_is_actually_used():
    """acquire_deep_fast reads over a raw socket; SCPI only configures.

    Quoting the SCPI rate overstated a 1 s decimation-8 sweep as 21 s against a
    measured 7-11 s -- and pointed at the wrong subsystem to fix.
    """
    assert FAST_READ_MB_PER_S > SCPI_MB_PER_S
    dec8 = next(o for o in options() if o.decimation == 8)
    assert dec8.transfer_seconds == pytest.approx(dec8.megabytes
                                                  / FAST_READ_MB_PER_S)
    # The H6.2 measurement was 6.7-11.2 s including arming and the capture, so
    # a bare transfer estimate must land at or below the top of that.
    assert dec8.transfer_seconds <= 11.5


def test_it_refuses_rather_than_recommending_something_that_does_not_fit():
    """A 10 s sweep fits nothing usable. Saying so beats naming a decimation
    whose capture would be silently truncated."""
    text = describe_capture_plan(10.0, F_LOCKIN)
    assert "Does not fit" in text
    assert recommend(options(sweep=10.0)) is None


def test_one_channel_buys_a_lower_decimation():
    """Dropping the trigger channel halves the bytes, which is the cheapest
    lever available if a sweep ever needs more sample rate."""
    two = recommend(options(channels=2))
    one = recommend(options(channels=1))
    assert one.decimation < two.decimation


def test_the_plan_names_the_settling_and_bandwidth_someone_would_check():
    text = describe_capture_plan(1.0, F_LOCKIN)
    assert "5000 Sa/s" in text
    assert "2250 Hz" in text
    assert "71 us" in text


def test_a_short_sweep_is_flagged_against_the_filter_settling():
    """1 ms cannot hold the filter's transient. It must say so rather than
    returning a plan that would produce a trace of pure ringing."""
    text = describe_capture_plan(1e-3, F_LOCKIN, output_points=5)
    assert "settling" in text.lower()
