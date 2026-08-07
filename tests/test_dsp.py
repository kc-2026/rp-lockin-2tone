"""
Offline validation of the demodulation core. No hardware required.

Each test here corresponds to a property the measurement depends on. Three of
them (chunk equality, settling, noise scaling) exist because the corresponding
bug was actually present and produced plausible-looking wrong answers. Do not
delete them to make a refactor pass.
"""

import numpy as np
import pytest

from rp_lockin import demodulate, estimate_frequency, min_record_seconds
from rp_lockin import dsp as dsp_mod

FS = 250e6
F_REF = 1e6  # the project's |f2 - f1|


def _tone(amp, phase_deg, ms, f=F_REF, fs=FS):
    n = int(ms * 1e-3 * fs)
    t = np.arange(n) / fs
    return amp * np.cos(2 * np.pi * f * t + np.radians(phase_deg))


def _vector_mean(r):
    """Unbiased amplitude estimator. mean(R) is biased upward by noise."""
    return np.mean(r.X + 1j * r.Y)


# --------------------------------------------------------------------------
# Amplitude and phase
# --------------------------------------------------------------------------

@pytest.mark.parametrize("amp,phase", [(1.0, 0.0), (0.25, 37.0), (0.01, -120.0)])
def test_amplitude_and_phase_exact(amp, phase):
    r = demodulate(_tone(amp, phase, ms=2), FS, F_REF, bandwidth=20e3)
    assert abs(r.R.mean() - amp) / amp < 1e-6
    got = np.degrees(np.angle(_vector_mean(r)))
    assert abs((got - phase + 180) % 360 - 180) < 0.01


def test_amplitude_convention_is_peak_not_rms():
    """A*cos(...) must give R = A. Getting this wrong silently scales results."""
    r = demodulate(_tone(1.0, 0.0, ms=2), FS, F_REF, bandwidth=20e3)
    assert abs(r.R.mean() - 1.0) < 1e-6


# --------------------------------------------------------------------------
# Noise
# --------------------------------------------------------------------------

@pytest.mark.parametrize("snr_db,ms,bw", [(0, 4, 10e3), (-20, 20, 2e3), (-40, 80, 500.0)])
def test_recovery_in_noise(snr_db, ms, bw):
    rng = np.random.default_rng(0)
    n = int(ms * 1e-3 * FS)
    t = np.arange(n) / FS
    noise_rms = 1.0 / np.sqrt(2) / (10 ** (snr_db / 20))
    x = np.cos(2 * np.pi * F_REF * t) + rng.normal(0, noise_rms, n)
    r = demodulate(x, FS, F_REF, bandwidth=bw)
    assert abs(abs(_vector_mean(r)) - 1.0) < 0.05


def test_output_noise_scales_as_sqrt_bandwidth():
    """Halving the bandwidth must drop output noise by sqrt(2).

    This is the check that the filter chain has the equivalent noise bandwidth
    it claims. A silently-too-wide filter passes every amplitude test and fails
    only here.
    """
    rng = np.random.default_rng(1)
    noise = rng.normal(0, 1.0, int(0.04 * FS))
    sigma = {bw: np.std(demodulate(noise, FS, F_REF, bandwidth=bw).X)
             for bw in (8e3, 4e3, 2e3, 1e3)}
    for bw in (8e3, 4e3, 2e3):
        assert abs(sigma[bw] / sigma[bw / 2] - np.sqrt(2)) < 0.12


# --------------------------------------------------------------------------
# Filter behaviour
# --------------------------------------------------------------------------

def test_2f_product_rejected():
    """Residual at 2*f_ref shows up as ripple on R. Must be near machine zero."""
    r = demodulate(_tone(1.0, 0.0, ms=2), FS, F_REF, bandwidth=20e3)
    assert r.R.std() / r.R.mean() < 1e-9


def test_settling_trim_removes_ringing():
    """Trimming by group delay instead of full impulse length leaves ringing at
    the cutoff frequency, which reads as real noise. Guard against regression."""
    r = demodulate(_tone(1.0, 0.0, ms=2), FS, F_REF, bandwidth=20e3)
    assert r.settle > 0
    assert np.ptp(r.R) / r.R.mean() < 1e-8


def test_offset_tone_rejected():
    r = demodulate(_tone(1.0, 0.0, ms=2, f=F_REF + 500e3), FS, F_REF, bandwidth=20e3)
    assert r.R.mean() < 1e-3


def test_envelope_tracked_at_20khz():
    n = int(0.010 * FS)
    t = np.arange(n) / FS
    depth = 0.5
    x = (1 + depth * np.cos(2 * np.pi * 20e3 * t)) * np.cos(2 * np.pi * F_REF * t)
    r = demodulate(x, FS, F_REF, bandwidth=60e3)
    ac = r.R - r.R.mean()
    assert abs(ac.std() * np.sqrt(2) / r.R.mean() - depth) < 0.02
    spec = np.abs(np.fft.rfft(ac * np.hanning(len(ac))))
    peak = np.fft.rfftfreq(len(ac), 1 / r.fs_out)[np.argmax(spec)]
    assert abs(peak - 20e3) / 20e3 < 0.02


def test_short_record_raises_rather_than_lying():
    with pytest.raises(ValueError, match="too short"):
        demodulate(np.zeros(int(2e-4 * FS)), FS, F_REF, bandwidth=100.0)


def test_min_record_seconds_is_sufficient():
    for bw in (1e3, 10e3, 20e3):
        n = int(min_record_seconds(FS, bw) * FS)
        r = demodulate(_tone(1.0, 0.0, ms=n / FS * 1e3), FS, F_REF, bandwidth=bw)
        assert len(r.t) > 0


# --------------------------------------------------------------------------
# Streaming
# --------------------------------------------------------------------------

def test_chunked_equals_single_shot(monkeypatch):
    """Block boundaries must be invisible.

    They are periodic, so a boundary artefact appears at the same position in
    every sweep and is indistinguishable from a real feature of the DUT.
    """
    rng = np.random.default_rng(2)
    n = int(0.003 * FS)
    t = np.arange(n) / FS
    x = ((1 + 0.3 * np.cos(2 * np.pi * 15e3 * t))
         * np.cos(2 * np.pi * F_REF * t + 0.4) + rng.normal(0, 0.05, n))

    results = {}
    for cs in (1 << 22, 1 << 16, 9973):
        monkeypatch.setattr(dsp_mod, "CHUNK_SAMPLES", cs)
        results[cs] = demodulate(x, FS, F_REF, bandwidth=50e3)

    ref = results[1 << 22]
    for cs, r in results.items():
        assert len(r.X) == len(ref.X), f"length differs at chunk {cs}"
        dev = np.max(np.abs((ref.X + 1j * ref.Y) - (r.X + 1j * r.Y)))
        assert dev == 0.0, f"chunk {cs} deviates by {dev:.3e}"


@pytest.mark.slow
def test_long_record_memory_bounded():
    import resource
    n = int(0.30 * FS)
    big = np.zeros(n, dtype=np.float32)
    step = 1 << 22
    for s in range(0, n, step):
        e = min(s + step, n)
        big[s:e] = np.cos(2 * np.pi * F_REF * np.arange(s, e) / FS).astype(np.float32)
    before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    r = demodulate(big, FS, F_REF, bandwidth=20e3)
    grew_mb = (resource.getrusage(resource.RUSAGE_SELF).ru_maxrss - before) / 1024
    assert abs(r.R.mean() - 1.0) < 1e-3
    assert grew_mb < 800, f"peak RSS grew {grew_mb:.0f} MB"


# --------------------------------------------------------------------------
# Output rate (the deliverable is a fixed number of points)
# --------------------------------------------------------------------------

def test_output_rate_gives_exact_point_count():
    r = demodulate(_tone(1.0, 0.0, ms=100), FS, F_REF, output_rate=5000)
    assert r.fs_out == 5000.0


def test_output_rate_clamps_bandwidth_to_avoid_folding():
    """Asking for more bandwidth than the output rate can represent must be
    silently corrected, not honoured -- otherwise noise folds into the trace."""
    r = demodulate(_tone(1.0, 0.0, ms=100), FS, F_REF,
                   bandwidth=5305.0, output_rate=5000)
    assert r.bandwidth <= 0.9 * 2500
    assert r.fs_out == 5000.0


def test_non_integer_output_rate_rejected():
    with pytest.raises(ValueError, match="not an integer"):
        demodulate(_tone(1.0, 0.0, ms=10), FS, F_REF, output_rate=3333.0)


def test_requires_bandwidth_or_output_rate():
    with pytest.raises(ValueError, match="either bandwidth or output_rate"):
        demodulate(_tone(1.0, 0.0, ms=10), FS, F_REF)


# --------------------------------------------------------------------------
# Time axis -- feeds the time-to-wavelength calibration, so it must be right
# --------------------------------------------------------------------------

def test_time_axis_locates_a_feature_correctly():
    """A burst at a known input time must come back at that time.

    The returned axis has to compensate BOTH the trimmed settling samples and
    the filter group delay. Getting only one of them right shifts the whole
    trace by ~10 ms at 5000 Sa/s, which would silently bias every wavelength
    assignment in the sweep.
    """
    fs = 125e6
    duration = 0.060
    n = int(duration * fs)
    t = np.arange(n) / fs
    burst_at, burst_w = 0.030, 0.002
    env = np.exp(-0.5 * ((t - burst_at) / burst_w) ** 2)
    x = env * np.cos(2 * np.pi * F_REF * t)

    r = demodulate(x, fs, F_REF, output_rate=5000)
    peak_t = r.t[np.argmax(r.R)]
    assert abs(peak_t - burst_at) < 3 / r.fs_out, (
        f"feature recovered at {peak_t * 1e3:.2f} ms, expected "
        f"{burst_at * 1e3:.2f} ms")


def test_time_axis_starts_after_settling_not_at_zero():
    r = demodulate(_tone(1.0, 0.0, ms=100), FS, F_REF, output_rate=5000)
    assert r.t[0] > 0
    assert r.t[0] == pytest.approx(r.settle / 2 / r.fs_out)


# --------------------------------------------------------------------------
# Frequency estimation (only needed if a drive is ever externally generated)
# --------------------------------------------------------------------------

def test_frequency_fit_recovers_ppm_offset():
    f_true = F_REF * (1 + 25e-6)
    n = int(0.004 * FS)
    t = np.arange(n) / FS
    x = np.cos(2 * np.pi * f_true * t + 0.7)
    assert abs(estimate_frequency(x, FS, F_REF) - f_true) / f_true < 1e-6


def test_reference_channel_removes_capture_start_phase():
    n = int(0.002 * FS)
    t = np.arange(n) / FS
    start, rel = np.radians(157.0), np.radians(42.0)
    ref = np.cos(2 * np.pi * F_REF * t + start)
    sig = 0.3 * np.cos(2 * np.pi * F_REF * t + start + rel)
    r = demodulate(sig, FS, F_REF, bandwidth=20e3, reference=ref)
    assert abs(np.degrees(np.angle(_vector_mean(r))) - 42.0) < 0.05


# --------------------------------------------------------------------------
# Input validation
# --------------------------------------------------------------------------

@pytest.mark.parametrize("kwargs", [
    dict(f_ref=200e6, bandwidth=1e3),
    dict(f_ref=5e6, bandwidth=6e6),
    dict(f_ref=-1.0, bandwidth=1e3),
])
def test_bad_parameters_rejected(kwargs):
    with pytest.raises(ValueError):
        demodulate(np.zeros(10_000), FS, **kwargs)
