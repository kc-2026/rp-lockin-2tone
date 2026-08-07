"""
End-to-end validation against synthetic ground truth. No hardware required.

This is the closest offline analogue of the real experiment: synthesise what
the DUT would emit across a sweep, run it through the full demodulation chain,
and check the recovered trace against the analytic envelope that went in.
Everything except the DUT physics and the analog path is exercised here.
"""

import numpy as np
import pytest

from rp_lockin import (
    demodulate,
    find_trigger_edges,
    lorentzian,
    make_trigger_sequence,
    plan_two_tone,
    synthesise_dut_output,
)

FS = 125e6          # decimation 2: aliasing-free and half the memory
DIFF = 1e6


def test_recovered_trace_matches_ground_truth():
    duration = 0.060   # > 2x the 21.6 ms filter settling at 5000 Sa/s
    samples, truth = synthesise_dut_output(DIFF, duration, fs=FS, amplitude=0.5)
    r = demodulate(samples, FS, DIFF, output_rate=5000)

    # r.t is already referenced to the start of the input record.
    expect = truth.resample_to(r.t)
    got = r.X + 1j * r.Y

    rel = np.max(np.abs(got - expect)) / np.max(np.abs(expect))
    assert rel < 0.05, f"trace deviates from ground truth by {rel:.1%}"


def test_resonance_position_and_width_recovered():
    duration = 0.060   # > 2x the 21.6 ms filter settling at 5000 Sa/s
    centre, width = duration * 0.6, duration * 0.15
    samples, truth = synthesise_dut_output(
        DIFF, duration, fs=FS, amplitude=0.5,
        envelope_fn=lambda t: lorentzian(t, centre, width))
    r = demodulate(samples, FS, DIFF, output_rate=5000)

    t_abs = r.t
    peak_t = t_abs[np.argmax(r.R)]
    assert abs(peak_t - centre) < 0.02 * duration

    half = r.R.max() / 2
    above = t_abs[r.R >= half]
    assert abs((above[-1] - above[0]) - width) < 0.15 * width


def test_both_quadratures_recovered_not_just_magnitude():
    """A magnitude-only check would pass even with the phase completely wrong."""
    duration = 0.060   # > 2x the 21.6 ms filter settling at 5000 Sa/s
    samples, truth = synthesise_dut_output(DIFF, duration, fs=FS, amplitude=0.5)
    r = demodulate(samples, FS, DIFF, output_rate=5000)
    expect = truth.resample_to(r.t)
    scale = np.max(np.abs(expect))
    assert np.max(np.abs(r.X - expect.real)) / scale < 0.05
    assert np.max(np.abs(r.Y - expect.imag)) / scale < 0.05


def test_survives_realistic_noise():
    duration = 0.060   # > 2x the 21.6 ms filter settling at 5000 Sa/s
    samples, truth = synthesise_dut_output(
        DIFF, duration, fs=FS, amplitude=0.3, noise_rms=0.3, seed=7)
    r = demodulate(samples, FS, DIFF, output_rate=5000)
    expect = truth.resample_to(r.t)
    # Complex RMS error, not |R| error: R is biased upward by noise wherever the
    # true signal approaches zero, so a magnitude comparison flatters or damns
    # the result depending only on how much of the sweep is off-resonance.
    got = r.X + 1j * r.Y
    err = np.sqrt(np.mean(np.abs(got - expect) ** 2)) / np.max(np.abs(expect))
    assert err < 0.15, f"complex RMS error {err:.1%} at ~unity SNR"


def test_point_count_matches_sweep_specification():
    """The deliverable is 4000-5000 points per 1 s sweep."""
    duration = 0.200
    samples, _ = synthesise_dut_output(DIFF, duration, fs=FS, amplitude=0.5)
    r = demodulate(samples, FS, DIFF, output_rate=5000)
    assert r.fs_out == 5000.0
    # Full 1 s sweep would give 5000 points less the settling transient.
    # Settling eats ~108 points off the front; see planning.settling_points.
    assert len(r.t) == pytest.approx(duration * 5000 - 108, rel=0.05)


# --------------------------------------------------------------------------
# Trigger digitisation -- the time-to-wavelength calibration path
# --------------------------------------------------------------------------

def test_trigger_edges_recovered_to_sample_accuracy():
    fs = 15.625e6
    duration = 0.010
    edges = [0.001, 0.0025, 0.006, 0.0075]
    wave = make_trigger_sequence(duration, edges, fs=fs)
    found = find_trigger_edges(wave, fs)
    assert len(found) == len(edges)
    for got, want in zip(found, edges):
        assert abs(got - want) < 2 / fs, f"edge off by {(got - want) * 1e9:.0f} ns"


def test_trigger_intervals_are_what_calibration_uses():
    """Absolute offset does not matter; the intervals carry the calibration."""
    fs = 15.625e6
    edges = [0.001, 0.0025, 0.006, 0.0075]
    wave = make_trigger_sequence(0.010, edges, fs=fs)
    found = find_trigger_edges(wave, fs)
    assert np.allclose(np.diff(found), np.diff(edges), atol=2 / fs)


def test_trigger_rejects_out_of_range_edge():
    with pytest.raises(ValueError, match="outside"):
        make_trigger_sequence(0.010, [0.02], fs=1e6)


def test_emulator_rejects_bad_parameters():
    with pytest.raises(ValueError):
        synthesise_dut_output(DIFF, -1.0, fs=FS)
    with pytest.raises(ValueError):
        synthesise_dut_output(FS, 0.01, fs=FS)   # difference above Nyquist


def test_emulator_output_within_dac_range():
    samples, _ = synthesise_dut_output(DIFF, 0.005, fs=FS,
                                       amplitude=0.9, noise_rms=0.5, seed=1)
    assert np.max(np.abs(samples)) <= 1.0 + 1e-12


def test_clip_normalisation_is_reflected_in_ground_truth():
    """If added noise pushes the waveform past full scale the emulator rescales
    it. The recorded truth must be rescaled identically, or every amplitude
    comparison is wrong by the clip factor -- which looks like a gain bug."""
    samples, truth = synthesise_dut_output(
        DIFF, 0.060, fs=FS, amplitude=0.3, noise_rms=0.3, seed=7)
    scale = truth.metadata["clip_scale"]
    assert scale < 1.0, "this case is meant to exercise clipping"
    assert np.max(np.abs(truth.envelope)) == pytest.approx(0.3 * scale)
    r = demodulate(samples, FS, DIFF, output_rate=5000)
    assert r.R.max() == pytest.approx(np.max(np.abs(truth.envelope)), rel=0.15)


def test_settling_cost_is_known_and_bounded():
    """The trace loses its first ~108 points to filter start-up. That is a
    design constraint the capture must pre-roll around, so pin the number: a
    regression that doubles it silently eats 4% of every sweep."""
    from rp_lockin import recommended_preroll, settling_points
    pts, secs = settling_points(5000, fs=FS)
    assert 80 <= pts <= 140, f"settling changed to {pts} points"
    assert secs == pytest.approx(pts / 5000)
    assert recommended_preroll(5000, fs=FS) >= 2 * secs


def test_plan_and_emulator_agree_on_difference_frequency():
    p = plan_two_tone(difference=DIFF)
    samples, truth = synthesise_dut_output(p.difference, 0.010, fs=FS)
    assert truth.difference == pytest.approx(p.difference)
