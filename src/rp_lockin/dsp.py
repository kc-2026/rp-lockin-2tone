"""
Digital lock-in signal processing. Pure numpy/scipy -- no hardware required.

This is the validated core of the project. Everything here is covered by
tests/test_dsp.py, which runs offline. If you change this file, those tests
must pass before you touch hardware.

Three non-obvious things this code gets right, each a real bug caught in
testing (see docs/02-architecture.md for the full account):

  1. Multistage decimation. One FIR setting a 2 kHz corner at 250 MS/s needs
     ~2.4 million taps. Capping the tap count silently substitutes a filter
     orders of magnitude too wide -- wrong answers, no error raised.
  2. Settling is the FULL impulse-response length, not the group delay.
     Trimming by the group delay leaves ringing at the cutoff that looks
     exactly like real noise on R.
  3. Streaming with carried filter state. Block processing without carried
     state corrupts every block boundary; because boundaries are periodic, the
     artefact lands at the same place in every sweep and reads as physics.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import signal as sps

from .constants import (
    BASE_SAMPLE_RATE,
    CHUNK_SAMPLES,
    FINAL_STOPBAND_DB,
    STOPBAND_DB,
)

__all__ = [
    "LockinResult",
    "demodulate",
    "estimate_frequency",
    "min_record_seconds",
]


@dataclass
class LockinResult:
    """Demodulated output. X/Y/R are in the same units as the input signal."""

    t: np.ndarray  # time axis of the decimated output, seconds
    X: np.ndarray  # in-phase component
    Y: np.ndarray  # quadrature component
    f_ref: float  # demodulation frequency actually used, Hz
    fs_out: float  # output sample rate after decimation, Hz
    bandwidth: float  # -3 dB output bandwidth, Hz
    settle: int  # samples of filter transient trimmed from each end

    @property
    def R(self) -> np.ndarray:
        """Magnitude. Equals the amplitude of the detected sinusoid."""
        return np.hypot(self.X, self.Y)

    @property
    def theta(self) -> np.ndarray:
        """Phase in radians, wrapped to (-pi, pi]."""
        return np.arctan2(self.Y, self.X)

    @property
    def theta_deg(self) -> np.ndarray:
        return np.degrees(self.theta)

    def amplitude(self, phase: float | None = None,
                  smooth: int | None = None) -> np.ndarray:
        """
        Amplitude WITHOUT the upward bias that R carries in noise.

        `R = sqrt(X^2 + Y^2)` is biased high: with no signal at all its mean is
        sigma*sqrt(pi/2), not zero, because a magnitude cannot be negative and
        noise in both quadratures always adds something. Near the noise floor
        that turns absence into a small steady positive reading, which is
        exactly where this measurement will live -- the detector puts the floor
        at ~11 uV and the interesting signals are not far above it.

        Projecting onto a common phase instead is unbiased: it returns sigma per
        point, and noise can come out negative, which is what an honest
        estimator does when there is nothing there.

        **"Unbiased" rather than "quieter", and the distinction is worth
        keeping.** With no signal, R's *variance* is actually lower than the
        projection's -- a Rayleigh distribution has spread 0.655*sigma against
        the projection's 1.0*sigma. What R has instead is a 1.25*sigma offset
        that does not average away with more points. The projection trades a
        little variance for the removal of that offset, so it wins on total
        error wherever the bias matters, which is everywhere near the floor.

        `phase` defaults to the angle of the vector mean, which is the right
        choice when the response phase is steady across the record -- H3.2
        measured 0.002 degrees of drift over 28 ms, so it is steady within a
        capture.

        **The assumption to watch: a response whose phase varies with
        wavelength.** Near a DUT resonance it will, and then a single global
        angle suppresses real signal wherever the phase has rotated away from
        it.

        `smooth=N` handles that by tracking the phase locally: it averages the
        complex trace over N points and projects each sample onto the angle of
        that local average. A DUT phase moves slowly with wavelength, so a
        window that is long compared to the noise but short compared to the
        resonance recovers the amplitude without the global angle's blind spots.

        **Choose N with care in one direction only.** Too long merely
        reintroduces the global-angle problem. Too SHORT is the dangerous one:
        the reference then carries a real share of the same noise it is being
        used to project, the two correlate, and R's upward bias creeps back --
        the exact fault this method exists to remove, in a subtler form. Prefer
        the longest window the response's phase variation tolerates.

        (`debiased_amplitude()` is the last resort when there is no usable phase
        at all. It is worse than it looks -- see its docstring.)
        """
        z = self.X + 1j * self.Y
        if phase is not None:
            ref = np.exp(1j * float(phase))
        elif smooth:
            n = int(smooth)
            if n < 1:
                raise ValueError(f"smooth must be >= 1, got {smooth}")
            kernel = np.ones(n) / n
            local = np.convolve(z, kernel, mode="same")
            ref = np.exp(1j * np.angle(local))
        else:
            ref = np.exp(1j * float(np.angle(np.mean(z))))
        return np.real(z * np.conj(ref))

    def summary(self) -> str:
        return (
            f"f_ref      = {self.f_ref / 1e6:.6f} MHz\n"
            f"output fs  = {self.fs_out / 1e3:.1f} kSa/s  "
            f"({len(self.t)} pts, {self.t[-1] * 1e3:.3f} ms)\n"
            f"bandwidth  = {self.bandwidth / 1e3:.1f} kHz\n"
            f"R          = {self.R.mean():.6g} +/- {self.R.std():.3g}\n"
            f"theta      = {np.degrees(np.angle(np.mean(self.X + 1j * self.Y))):.4f} deg"
        )


# Intermediate anti-alias stages need deep rejection -- anything that folds into
# the output band is unrecoverable.
STOPBAND_DB = 90.0
# The final bandwidth-setting stage does not: aliasing and the 2*f_ref product
# are already gone by then, so it only has to shape the passband edge. Settling
# time scales as (stopband_dB - 7.95) / transition_width, so relaxing this from
# 90 dB to 60 dB cuts the dead time at each end of the record by ~40% for free.
FINAL_STOPBAND_DB = 60.0

# Streaming block size, in input samples. Bounds peak memory so that a 1 s
# sweep at 250 MS/s (250 M samples, which would be an 8 GB complex array in one
# shot) processes in ~130 MB.
CHUNK_SAMPLES = 1 << 22

# MAX_DMA_MB used to be duplicated here with a value of 924, on the assumption
# that the board has 1 GB. It has 512 MB, and this copy was never read -- only
# constants.py's is imported. Removed rather than corrected: two definitions of
# the same limit is how they drift apart.


def _factorize(d: int, maxf: int = 8) -> list[int]:
    """Split a decimation factor into small stages, largest first."""
    factors = []
    while d > 1:
        for f in range(min(maxf, d), 1, -1):
            if d % f == 0:
                factors.append(f)
                d //= f
                break
        else:
            # d is a prime larger than maxf; take it in one stage.
            factors.append(d)
            d = 1
    return factors


def debiased_amplitude(R: np.ndarray, sigma: float) -> np.ndarray:
    """
    Amplitude from the magnitude, with the noise contribution subtracted.

    Use this when the response phase varies across the sweep, which is where
    `LockinResult.amplitude()`'s single-angle projection stops being valid --
    near a DUT resonance, for instance.

    The identity is exact rather than approximate: for a signal of amplitude A
    in complex Gaussian noise with `sigma` per quadrature,

        E[R^2] = A^2 + 2*sigma^2

    so subtracting `2*sigma^2` from `R^2` gives an unbiased estimate of `A^2`.
    `sigma` is the per-quadrature noise -- the figure H3.3 measures, not the
    spread of R.

    **This is a last resort, and measurement says so.** The square root of an
    unbiased estimate of A^2 is not an unbiased estimate of A -- sqrt is
    concave, so it reads LOW -- and it overcorrects badly in the middle of the
    range. Measured against the truth, mean error in units of sigma:

        A/sigma:      0.5     1.0     1.5     2.0     3.0     4.0    10.0
        raw R:      +0.83   +0.55   +0.38   +0.28   +0.17   +0.13   +0.05
        debiased:   +0.05   -0.20   -0.31   -0.31   -0.22   -0.15   -0.05
        projection: +0.002  +0.003  +0.002  +0.002  +0.002  -0.001  +0.000

    So it helps only below about **1.5 sigma**. Between 2 and 6 sigma it is
    WORSE than doing nothing, and that band is exactly where this project's
    signals are expected to sit. Meanwhile the projection is essentially exact
    everywhere.

    **Use `LockinResult.amplitude(smooth=N)` instead** unless there is genuinely
    no usable phase reference. This function is kept because that case exists,
    not because it is a good default.
    """
    R = np.asarray(R, dtype=float)
    if sigma < 0:
        raise ValueError(f"sigma must be non-negative, got {sigma}")
    return np.sqrt(np.maximum(R ** 2 - 2.0 * sigma ** 2, 0.0))


def _kaiser_taps(cutoff: float, trans: float, fs: float,
                 stopband_db: float = STOPBAND_DB, cap: int = 4095) -> np.ndarray:
    ntaps, beta = sps.kaiserord(stopband_db, trans / (fs / 2))
    ntaps = min(int(ntaps) | 1, cap)  # odd -> integer group delay
    return sps.firwin(ntaps, cutoff, window=("kaiser", beta), fs=fs)


def _design_filter_chain(fs: float, bandwidth: float, decim: int):
    """
    Build a multistage decimating filter chain.

    A single FIR cannot do this job. Setting a 1 kHz corner at 250 MS/s in one
    stage needs ~2.4 million taps, because tap count scales with
    fs / transition_width. Cascading fixes it: each stage decimates by a small
    factor using a cheap wide-transition anti-alias filter, and only the final
    stage -- running at a few times the output bandwidth -- needs to be sharp.

    Intermediate stages only have to keep energy from folding into [0, bandwidth].
    Since bandwidth is far below each intermediate Nyquist, a lax filter
    (passband to 0.3*fs_stage, stopband from 0.7*fs_stage) suffices and costs
    only a few dozen taps.

    Returns (stages, settling_length_in_output_samples) where each stage is
    a (taps, decimation_factor) pair.
    """
    stages: list[tuple[np.ndarray, int]] = []
    factors = _factorize(decim)
    fs_cur = fs

    for f in factors:
        fs_new = fs_cur / f
        # Anti-alias only: protect [0, bandwidth] from folding.
        cutoff = 0.30 * fs_new
        trans = 0.40 * fs_new
        if cutoff <= bandwidth:
            # Rare: decimating so hard that even the lax filter would bite into
            # the band of interest. Tighten it.
            cutoff = min(0.45 * fs_new, max(bandwidth * 1.5, 0.05 * fs_new))
            trans = max(0.10 * fs_new, 0.5 * cutoff)
        stages.append((_kaiser_taps(cutoff, trans, fs_cur), f))
        fs_cur = fs_new

    # Final stage at the (low) output rate -- this sets the bandwidth.
    # Transition width is deliberately comparable to the cutoff: settling time
    # goes as 1/transition, and a lock-in output filter gains nothing from a
    # brick wall. This lands close to the settling of a 2-pole analog filter of
    # the same corner, which is the familiar behaviour.
    nyq_out = fs_cur / 2
    cutoff = min(bandwidth, 0.9 * nyq_out)
    trans = min(max(0.8 * cutoff, 0.10 * nyq_out), 0.95 * (nyq_out - cutoff))
    stages.append((_kaiser_taps(cutoff, trans, fs_cur,
                                stopband_db=FINAL_STOPBAND_DB), 1))

    # Accumulate the SETTLING length, expressed in samples of the final output
    # rate. Note this is the full impulse-response length (L-1), not the group
    # delay (L-1)/2: an FIR output is only fully valid once the entire impulse
    # response has entered the filter. Trimming by the group delay instead
    # leaves step-response ringing at the cutoff frequency on both edges, which
    # shows up as a spurious few-percent ripple on R.
    #
    # A stage's settling of S samples at its own input rate corresponds to
    # S / (product of decimation factors from this stage onward) output samples.
    settle_out = 0.0
    remaining = float(np.prod([f for _, f in stages]))
    for taps, f in stages:
        settle_out += (len(taps) - 1) / remaining
        remaining /= f
    return stages, settle_out


def _apply_chain(z: np.ndarray, stages) -> np.ndarray:
    for taps, f in stages:
        z = sps.upfirdn(taps, z, up=1, down=f)
    return z


class _StreamingDecimator:
    """
    One FIR decimation stage that can be fed in blocks.

    Needed because a 1 s sweep at 250 MS/s is 250 M samples; mixing that in one
    go would allocate an 8 GB complex array. Processing in blocks keeps peak
    memory bounded, but a naive split would corrupt the output at every block
    boundary. This carries two pieces of state across calls:

      tail   the last (ntaps-1) input samples, so each block sees the history
             the filter would have had in a single-shot run;
      phase  where the next block starts relative to the decimation grid, so
             the kept samples stay on one consistent lattice.

    With both, the concatenated block output is bit-for-bit what single-shot
    processing produces (verified in the self-test).
    """

    __slots__ = ("taps", "decim", "tail", "phase")

    def __init__(self, taps: np.ndarray, decim: int):
        self.taps = taps
        self.decim = decim
        self.tail = np.zeros(len(taps) - 1, dtype=np.complex128)
        self.phase = 0

    def feed(self, block: np.ndarray) -> np.ndarray:
        joined = np.concatenate((self.tail, block))
        full = np.convolve(joined, self.taps)
        # Outputs that saw a full window: aligned one-to-one with `block`.
        valid = full[len(self.taps) - 1: len(joined)]
        out = valid[self.phase:: self.decim]
        self.phase = (self.phase - len(valid)) % self.decim
        self.tail = joined[len(joined) - (len(self.taps) - 1):] if len(self.taps) > 1 \
            else joined[:0]
        return out


def _demodulate_stream(signal, fs: float, f_ref: float, stages, dc: float,
                       chunk: int) -> np.ndarray:
    """Mix to baseband and run the decimating chain, block by block."""
    chain = [_StreamingDecimator(taps, f) for taps, f in stages]
    pieces = []
    n_total = len(signal)
    two_pi_f_over_fs = 2j * np.pi * f_ref / fs

    for start in range(0, n_total, chunk):
        block = np.asarray(signal[start: start + chunk], dtype=np.float64)
        # Absolute sample index keeps the local oscillator phase-continuous
        # across block boundaries.
        n = np.arange(start, start + len(block))
        z = 2.0 * (block - dc) * np.exp(-two_pi_f_over_fs * n)
        for stage in chain:
            z = stage.feed(z)
            if z.size == 0:
                break
        if z.size:
            pieces.append(z)

    if not pieces:
        return np.zeros(0, dtype=np.complex128)
    return np.concatenate(pieces)


def _decimation_for(fs: float, bandwidth: float) -> int:
    decim = max(1, int(fs / (8 * bandwidth)))
    if decim > 1:
        decim = int(2 ** int(np.floor(np.log2(decim))))
    return decim


def min_record_seconds(fs: float, bandwidth: float, margin: float = 1.5) -> float:
    """
    Shortest capture that yields usable output at this bandwidth.

    The filter needs time to settle at both ends of the record, and that dead
    time scales as ~1/bandwidth -- so a narrow bandwidth costs a long capture.
    Use this to size a capture before taking it:

        >>> n = int(min_record_seconds(250e6, 20e3) * 250e6)

    margin sets how much valid data you get beyond the bare minimum.
    """
    decim = _decimation_for(fs, bandwidth)
    _, settle = _design_filter_chain(fs, bandwidth, decim)
    fs_out = fs / decim
    return (settle * (1.0 + margin) + 16) * (1 / fs_out) + decim / fs


def estimate_frequency(x: np.ndarray, fs: float, f_guess: float,
                       search_frac: float = 0.02) -> float:
    """
    Refine a frequency estimate from data.

    Needed when the drive is generated EXTERNALLY: the external source and the
    Red Pitaya's ADC clock are different crystals, so the nominal frequency is
    off by some ppm. Left uncorrected, that offset shows up as a slow phase ramp
    on the lock-in output.

    Not needed when the Red Pitaya generates the drive itself -- the DAC and ADC
    share one clock, so the ratio f_ref/fs is exact by construction.

    Two stages: FFT peak with parabolic interpolation, then a phase-slope fit
    which is far more precise for a long coherent record.
    """
    x = np.asarray(x, dtype=float)
    x = x - x.mean()
    n = len(x)

    # Stage 1: windowed FFT, parabolic peak interpolation.
    win = np.hanning(n)
    spec = np.abs(np.fft.rfft(x * win))
    freqs = np.fft.rfftfreq(n, 1 / fs)

    lo = np.searchsorted(freqs, f_guess * (1 - search_frac))
    hi = np.searchsorted(freqs, f_guess * (1 + search_frac))
    lo, hi = max(lo, 1), min(hi, len(spec) - 1)
    if hi <= lo:
        return f_guess
    k = lo + int(np.argmax(spec[lo:hi]))

    if 0 < k < len(spec) - 1:
        a, b, c = np.log(spec[k - 1: k + 2] + 1e-300)
        delta = 0.5 * (a - c) / (a - 2 * b + c) if (a - 2 * b + c) != 0 else 0.0
        delta = float(np.clip(delta, -0.5, 0.5))
    else:
        delta = 0.0
    f_coarse = (k + delta) * fs / n

    # Stage 2: mix down by the coarse estimate, fit the residual phase ramp.
    t = np.arange(n) / fs
    z = x * np.exp(-2j * np.pi * f_coarse * t)
    # Heavy smoothing so only the residual carrier survives.
    taps = sps.firwin(min(1023, (n // 8) | 1), 0.002, window="hann")
    z = sps.filtfilt(taps, 1.0, z)
    trim = len(taps)
    z = z[trim:-trim] if len(z) > 4 * trim else z
    if len(z) < 16:
        return f_coarse
    phase = np.unwrap(np.angle(z))
    tt = np.arange(len(phase)) / fs
    slope = np.polyfit(tt, phase, 1)[0]
    return float(f_coarse + slope / (2 * np.pi))


def demodulate(signal: np.ndarray, fs: float, f_ref: float,
               bandwidth: float | None = None,
               output_rate: float | None = None,
               reference: np.ndarray | None = None,
               fit_frequency: bool = False) -> LockinResult:
    """
    Digital lock-in detection.

    Parameters
    ----------
    signal      Raw samples from the measurement channel.
    fs          Sample rate, Hz (250e6 at decimation 1 on the 250-12).
    f_ref       Demodulation frequency, Hz.
    bandwidth   Desired -3 dB output bandwidth, Hz. Optional if output_rate is
                given, in which case it defaults to the widest value that is
                honest at that rate (0.9 x output Nyquist).
    output_rate Exact output sample rate, Hz. Use this when the deliverable is
                a fixed number of points -- e.g. 5000 Sa/s for 5000 points
                across a 1 s sweep. Without it the rate is chosen automatically
                from the bandwidth and lands on a power-of-two decimation.

                Setting output_rate also enforces honesty: bandwidth is clamped
                to 0.9 x (output_rate/2), because a filter wider than output
                Nyquist folds noise into the trace no matter what you asked
                for. See docs/03-frequency-plan.md.
    reference   Optional raw samples of a pickoff of the drive signal. If given,
                the returned phase is relative to the drive rather than to an
                arbitrary capture-start phase. Strongly recommended.
    fit_frequency
                Refine f_ref from the data before demodulating. Use when the
                drive is generated externally (different crystal).

    Returns
    -------
    LockinResult

    Notes
    -----
    Amplitude convention: a pure input A*cos(2*pi*f*t + phi) yields R = A.
    """
    signal = np.asarray(signal)
    if signal.ndim != 1:
        raise ValueError("signal must be 1-D")
    if not 0 < f_ref < fs / 2:
        raise ValueError(f"f_ref={f_ref:.4g} Hz must be in (0, {fs / 2:.4g}) Hz")
    if output_rate is not None:
        if not 0 < output_rate < fs:
            raise ValueError(f"output_rate must be in (0, {fs:.4g}) Hz")
        ratio = fs / output_rate
        if abs(ratio - round(ratio)) > 1e-6:
            raise ValueError(
                f"fs/output_rate = {ratio:.6f} is not an integer. Pick an output "
                f"rate that divides {fs / 1e6:g} MS/s exactly (5000 Sa/s does)."
            )
        honest = 0.9 * output_rate / 2
        bandwidth = honest if bandwidth is None else min(bandwidth, honest)
    if bandwidth is None:
        raise ValueError("give either bandwidth or output_rate")
    if not 0 < bandwidth < f_ref:
        raise ValueError(
            f"bandwidth={bandwidth:.4g} Hz must be positive and well below "
            f"f_ref={f_ref:.4g} Hz, otherwise the 2*f_ref mixing product leaks through"
        )

    if fit_frequency:
        src = reference if reference is not None else signal
        f_ref = estimate_frequency(src, fs, f_ref)

    # Choose decimation so the output rate comfortably oversamples the bandwidth.
    # Round to a product of small factors so the cascade stays cheap.
    decim = int(round(fs / output_rate)) if output_rate is not None \
        else _decimation_for(fs, bandwidth)
    fs_out = fs / decim

    stages, settle_len = _design_filter_chain(fs, bandwidth, decim)

    # Block size for streaming. Must be a multiple of the total decimation so
    # block boundaries land on the output lattice. ~4 M samples caps peak
    # working memory at roughly 130 MB regardless of how long the record is.
    chunk = max(decim, (CHUNK_SAMPLES // decim) * decim)

    def _mix_and_filter(x: np.ndarray) -> np.ndarray:
        # exp(-j w t) mixing -> real part is the in-phase (cos) product,
        # imaginary part the quadrature (sin) product. Factor 2 restores
        # amplitude: A*cos * cos = A/2 * (DC + 2f), and we keep DC.
        #
        # DC is removed up front. It would otherwise mix up to f_ref, which the
        # filter chain rejects anyway, but subtracting it keeps the arithmetic
        # well conditioned when the input carries a large offset.
        dc = float(np.mean(x))
        return _demodulate_stream(x, fs, f_ref, stages, dc, chunk)

    Z = _mix_and_filter(signal)

    if reference is not None:
        reference = np.asarray(reference, dtype=float)
        if len(reference) != len(signal):
            raise ValueError("reference must be the same length as signal")
        Zr = _mix_and_filter(reference)
        # Divide out the reference phasor's phase (not its magnitude -- we want
        # the signal's own amplitude, not a ratio).
        with np.errstate(invalid="ignore", divide="ignore"):
            unit = np.where(np.abs(Zr) > 0, Zr / np.abs(Zr), 1.0 + 0j)
        Z = Z * np.conj(unit)

    # Trim the start-up transient. Leaving it in is the classic way to get an
    # amplitude that reads low and a magnitude that looks noisy.
    #
    # Only the FRONT needs trimming. The streaming chain carries filter state
    # forward and simply stops at the last real sample, so unlike a one-shot
    # 'full' convolution there is no ring-out at the end.
    settle = int(np.ceil(settle_len))
    if len(Z) <= settle + 8:
        need = (settle + 16) * decim / fs
        raise ValueError(
            f"Record too short for bandwidth={bandwidth:.4g} Hz: the filter "
            f"start-up transient alone is {settle} output samples, but only "
            f"{len(Z)} were produced. Capture at least {need * 1e3:.2f} ms "
            f"({int(need * fs):,} samples), or widen the bandwidth."
        )
    Z = Z[settle:]

    # Time axis referenced to the START OF THE INPUT RECORD, not to the first
    # surviving output sample. Two corrections are folded in:
    #   - `settle` samples were trimmed off the front;
    #   - the filter chain has a group delay of settle/2 output samples.
    # Net: the first valid point reflects input time settle/2 / fs_out.
    #
    # This is not cosmetic. The sweep's time-to-wavelength calibration is
    # derived from trigger edge positions in the same record, so an offset here
    # translates directly into a wavelength error across the whole trace.
    t_out = (np.arange(len(Z)) + settle / 2.0) / fs_out

    return LockinResult(
        t=t_out,
        X=Z.real.copy(),
        Y=Z.imag.copy(),
        f_ref=f_ref,
        fs_out=fs_out,
        bandwidth=bandwidth,
        settle=settle,
    )


# ----------------------------------------------------------------------------
# Hardware layer -- SCPI over TCP
# ----------------------------------------------------------------------------
