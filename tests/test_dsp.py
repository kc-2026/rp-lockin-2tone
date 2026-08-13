"""
Offline validation of the demodulation core. No hardware required.

Each test here corresponds to a property the measurement depends on. Three of
them (chunk equality, settling, noise scaling) exist because the corresponding
bug was actually present and produced plausible-looking wrong answers. Do not
delete them to make a refactor pass.
"""

import tracemalloc

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
    """Streaming must bound peak memory. A 0.30 s record at 250 MS/s is 300 MB
    of input; demodulating it in one piece instead of in chunks costs several
    GB. Measured at 346 MB with CHUNK_SAMPLES = 1<<22 against 4295 MB at 1<<26,
    so the 800 MB bound below sits an order of magnitude clear of both.

    Uses tracemalloc rather than resource.getrusage because `resource` is
    Unix-only and most machines running this are Windows -- a skip there would
    leave the property unguarded on the primary platform. It is also the better
    probe: reset_peak() scopes the measurement to this one call, whereas
    ru_maxrss is a process-lifetime high-water mark, so any earlier test that
    peaked higher would mask a regression here and pass silently.

    Caveat: tracemalloc sees numpy's allocations (numpy registers its own
    domain) but not raw mallocs inside scipy's compiled kernels, so this reads
    slightly under true RSS. That is fine for what is being guarded -- a
    non-streaming regression materialises a whole-record numpy array, which is
    precisely what tracemalloc does see.
    """
    n = int(0.30 * FS)
    big = np.zeros(n, dtype=np.float32)
    step = 1 << 22
    for s in range(0, n, step):
        e = min(s + step, n)
        big[s:e] = np.cos(2 * np.pi * F_REF * np.arange(s, e) / FS).astype(np.float32)

    # Started after the record is built, so `big` itself is untraced and the
    # peak reflects only what demodulate allocates on top of it.
    tracemalloc.start()
    try:
        tracemalloc.reset_peak()
        r = demodulate(big, FS, F_REF, bandwidth=20e3)
        peak_mb = tracemalloc.get_traced_memory()[1] / 1024**2
    finally:
        tracemalloc.stop()

    assert abs(r.R.mean() - 1.0) < 1e-3
    assert peak_mb < 800, f"peak tracked allocation {peak_mb:.0f} MB"


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
# Noise gain -- the conversion H3.3's noise floor depends on
# --------------------------------------------------------------------------

def test_quadrature_noise_gain_matches_filter_chain():
    """Input noise density -> quadrature variance must stay predictable.

    H3.3 measures a noise DENSITY on the board and converts it to the scatter
    on one demodulated quadrature, which is what limits an amplitude reading.
    The conversion factor is fs * sum(h_eff^2) for the cascaded impulse
    response: with a one-sided input density S, var(X) = S * fs * sum(h_eff^2).

    At the operating point (125 MS/s, 5000 Sa/s out) that factor is 4233 Hz --
    1.88x the nominal 2250 Hz bandwidth, so anyone assuming the two are equal
    understates the noise by 37%. This test exists because a change to the
    filter design would silently move the factor and quietly invalidate every
    noise figure derived from it, with nothing failing.
    """
    from scipy import signal as sps

    fs, output_rate = 125e6, 5000.0
    bandwidth = 0.9 * output_rate / 2
    decim = int(round(fs / output_rate))

    stages, _ = dsp_mod._design_filter_chain(fs, bandwidth, decim)
    h, upsample = np.array([1.0]), 1
    for taps, f in stages:
        if upsample > 1:
            stuffed = np.zeros((len(taps) - 1) * upsample + 1)
            stuffed[::upsample] = taps
        else:
            stuffed = taps
        h = sps.fftconvolve(h, stuffed)
        upsample *= f
    analytic = fs * float(np.sum(h ** 2))

    assert analytic == pytest.approx(4232.7, rel=1e-3), (
        f"quadrature noise gain moved to {analytic:.1f} Hz from 4232.7 Hz. The "
        f"filter chain changed; H3.3's noise floor and any SNR derived from it "
        f"must be recomputed. See SESSION_LOG.md 2026-08-12."
    )

    # Independently: push known white noise through the real demodulate() call.
    rng = np.random.default_rng(20260812)
    sigma_in = 100.0
    n = (108 + 900) * decim
    r = demodulate(rng.normal(0.0, sigma_in, n), fs, 991821.2890625,
                   output_rate=output_rate)
    empirical = 0.5 * (r.X.var(ddof=1) + r.Y.var(ddof=1)) / (
        sigma_in ** 2 / (fs / 2))
    assert empirical == pytest.approx(analytic, rel=0.06)


def test_magnitude_is_biased_upward_in_pure_noise():
    """R = hypot(X, Y) reads ~1.25 sigma with NO signal present.

    X and Y are independent and zero-mean in noise, so R is Rayleigh: its mean
    is sigma*sqrt(pi/2), never zero. Quoting mean(R) from a signal-free record
    therefore reports an amplitude that does not exist, and quoting it as the
    noise floor overstates the uncertainty on a real amplitude by 25%. The
    honest figure is the per-quadrature standard deviation.
    """
    rng = np.random.default_rng(7)
    fs, output_rate = 125e6, 5000.0
    decim = int(round(fs / output_rate))
    r = demodulate(rng.normal(0.0, 50.0, (108 + 900) * decim), fs,
                   991821.2890625, output_rate=output_rate)
    sigma = 0.5 * (r.X.std(ddof=1) + r.Y.std(ddof=1))
    assert r.R.mean() == pytest.approx(np.sqrt(np.pi / 2) * sigma, rel=0.05)
    assert r.R.min() > 0


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
