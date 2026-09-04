"""
DUT emulator for loopback testing.

WHY THIS EXISTS
---------------
You cannot produce |f2 - f1| by combining two Red Pitaya outputs. Passive
summing is linear; the difference frequency only exists because the DUT is
nonlinear. So a loopback rig can never generate the real signal by wiring
OUT1 and OUT2 together -- that path produces 80 MHz sidebands and nothing at
the difference frequency at all.

Instead the board computes what the DUT *would* emit and plays that. The
recovered trace is then compared against the exact analytic response that was
synthesised, which validates the entire receive and analysis chain against
ground truth: mixing, filtering, decimation, streaming, trigger alignment,
time-to-point mapping.

WHAT IT DOES NOT TEST
---------------------
The DUT physics, the real optical path, the photodetector, the downstream
amplifier chain, and the true 80 MHz drive amplitude. Those are the
human-in-the-loop items in docs/12-test-campaigns.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .constants import BASE_SAMPLE_RATE

__all__ = [
    "SyntheticResponse",
    "lorentzian",
    "make_trigger_sequence",
    "synthesise_dut_output",
]


def lorentzian(t: np.ndarray, centre: float, width: float,
               amplitude: float = 1.0, phase_swing: float = np.pi) -> np.ndarray:
    """
    A complex resonance to sweep through: Lorentzian magnitude with the
    accompanying phase roll. Returned as a complex envelope, so the test can
    check that BOTH quadratures are recovered, not just magnitude.

    centre/width are in the same units as t (seconds of sweep time).
    """
    x = (t - centre) / (width / 2)
    mag = amplitude / (1 + x ** 2)
    phase = phase_swing * np.arctan(x) / (np.pi / 2) / 2
    return mag * np.exp(1j * phase)


@dataclass
class SyntheticResponse:
    """Ground truth for a loopback test: the envelope that was synthesised."""

    t: np.ndarray                 # sweep time axis, seconds
    envelope: np.ndarray          # complex response at the difference frequency
    difference: float             # Hz
    fs: float                     # DAC rate the waveform was built at
    noise_rms: float = 0.0
    metadata: dict = field(default_factory=dict)

    @property
    def R(self) -> np.ndarray:
        return np.abs(self.envelope)

    @property
    def theta(self) -> np.ndarray:
        return np.angle(self.envelope)

    def resample_to(self, t_new: np.ndarray) -> np.ndarray:
        """Interpolate the ground truth onto a recovered trace's time axis."""
        re = np.interp(t_new, self.t, self.envelope.real)
        im = np.interp(t_new, self.t, self.envelope.imag)
        return re + 1j * im


def synthesise_dut_output(difference: float, duration: float,
                          fs: float = BASE_SAMPLE_RATE,
                          envelope_fn=None, noise_rms: float = 0.0,
                          amplitude: float = 0.5,
                          seed: int | None = None,
                          envelope_points: int = 20001
                          ) -> tuple[np.ndarray, SyntheticResponse]:
    """
    Build a waveform emulating the DUT's photodetector output.

    The signal is a tone at `difference` whose complex envelope follows
    `envelope_fn(t)` across the sweep -- i.e. exactly what the real experiment
    produces, minus the physics.

    envelope_fn maps a sweep-time array (seconds) to a complex array. Defaults
    to a Lorentzian resonance centred in the sweep.

    Returns (samples, ground_truth). Samples are normalised to +/-1 for the
    generator; `amplitude` scales the tone within that range so there is
    headroom for the added noise.

    Memory note: at 250 MS/s a 1 s sweep is 250 M samples (2 GB as float64).
    Loopback tests should use a short duration -- 50 ms exercises every code
    path and still fits the default 32 MB DMA region. See docs/12-test-campaigns.md.
    """
    if duration <= 0:
        raise ValueError("duration must be positive")
    if not 0 < difference < fs / 2:
        raise ValueError(f"difference must be in (0, {fs / 2:.4g}) Hz")

    n = int(round(duration * fs))
    if envelope_fn is None:
        def envelope_fn(t):
            return lorentzian(t, centre=duration * 0.5, width=duration * 0.15)

    # The envelope varies on sweep timescales (kHz at most), so evaluating it on
    # a coarse grid and interpolating avoids materialising a second 250 M-point
    # array while changing nothing measurable.
    t_coarse = np.linspace(0.0, duration, min(envelope_points, n))
    env_coarse = np.asarray(envelope_fn(t_coarse), dtype=complex)
    if env_coarse.shape != t_coarse.shape:
        raise ValueError("envelope_fn must return one complex value per time point")

    t_full = np.arange(n) / fs
    env = (np.interp(t_full, t_coarse, env_coarse.real)
           + 1j * np.interp(t_full, t_coarse, env_coarse.imag))

    carrier = np.exp(2j * np.pi * difference * t_full)
    samples = amplitude * np.real(env * carrier)

    if noise_rms > 0:
        rng = np.random.default_rng(seed)
        samples = samples + rng.normal(0.0, noise_rms, n)

    # Clipping protection. Crucially, the SAME scale factor must be applied to
    # the recorded ground truth -- otherwise a test compares a rescaled waveform
    # against an un-rescaled expectation and reports a phantom amplitude error.
    # With noise_rms comparable to amplitude this is a factor of ~2, which looks
    # exactly like a broken gain calibration.
    peak = float(np.max(np.abs(samples)))
    scale = 1.0 / peak if peak > 1.0 else 1.0
    if scale != 1.0:
        samples = samples * scale

    truth = SyntheticResponse(
        t=t_coarse, envelope=env_coarse * amplitude * scale, difference=difference,
        fs=fs, noise_rms=noise_rms * scale,
        metadata={"duration": duration, "n_samples": n,
                  "amplitude": amplitude, "clip_scale": scale},
    )
    return samples, truth


def make_trigger_sequence(duration: float, edges: list[float],
                          fs: float = BASE_SAMPLE_RATE,
                          high: float = 0.8, low: float = -0.8,
                          rise_time: float = 20e-9) -> np.ndarray:
    """
    Build a laser-style trigger waveform: a train of level transitions at the
    given times (seconds from the start of the record).

    The real experiment derives its time-to-wavelength calibration from the
    RELATIVE timing of these edges, so the loopback test must prove we can
    recover edge positions to sample accuracy. Feeding a known edge list here
    and checking what comes back out of IN2 is that test.

    A finite rise time is included deliberately: a mathematically instant edge
    would be an unrealistically easy target for the edge-finder, and would also
    ring badly through a 60 MHz analog path.
    """
    n = int(round(duration * fs))
    t = np.arange(n) / fs
    out = np.full(n, low, dtype=float)
    state = low
    for e in sorted(edges):
        if not 0 <= e <= duration:
            raise ValueError(f"edge at {e} s lies outside the {duration} s record")
        target = high if state == low else low
        # smooth transition over rise_time
        ramp = np.clip((t - e) / max(rise_time, 1 / fs), 0.0, 1.0)
        out = out + (target - state) * ramp
        state = target
    return np.clip(out, -1.0, 1.0)


def make_trigger_pulses(duration: float, first: float, period: float,
                        width: float = 25e-6,
                        fs: float = BASE_SAMPLE_RATE,
                        n_pulses: int | None = None,
                        high: float = 0.8, low: float = -0.8,
                        rise_time: float = 20e-9) -> np.ndarray:
    """
    A Santec-shaped trigger train: a PULSE per step, not a square wave.

    The real trigger is 3.3 V, **25 us wide**, at most 20 kHz, so pulses are at
    least 50 us apart (TSL-775 p46, section 6.5). That shape matters to anything
    downstream: each pulse gives a rising edge AND a falling edge 25 us later,
    so an edge finder asked for both polarities sees alternating 25 us and
    (period - 25 us) gaps. `make_trigger_sequence` alternates state at every
    time it is given, which makes a SQUARE WAVE -- a trigger with a 50% duty
    cycle that no laser produces, and one that hides this whole problem.

    Emits pulses at first, first + period, first + 2*period, ...

    **Pass `n_pulses` when modelling a real sweep.** Without it the train runs
    to the end of the record, which no laser does -- it triggers while it is
    sweeping and then stops. A train that keeps going past the sweep makes the
    trigger span longer than the wavelength log covers, and anything deriving a
    step from that span comes out proportionally too large. That is not a
    hypothetical: it is what these pulses got wrong on first use.
    """
    if period <= 0:
        raise ValueError(f"period must be positive, got {period}")
    if not 0 < width < period:
        raise ValueError(
            f"width {width} must be positive and shorter than the period "
            f"{period}; a pulse wider than its spacing is a square wave"
        )
    transitions = []
    t = float(first)
    emitted = 0
    while t + width <= duration:
        if n_pulses is not None and emitted >= n_pulses:
            break
        transitions.extend([t, t + width])
        t += period
        emitted += 1
    if n_pulses is not None and emitted < n_pulses:
        raise ValueError(
            f"only {emitted} of {n_pulses} pulses fit in a {duration} s record "
            f"starting at {first} s with period {period} s. Lengthen the "
            f"record rather than silently returning a short train."
        )
    if not transitions:
        raise ValueError(
            f"no complete pulse fits: first={first}, width={width}, "
            f"duration={duration}"
        )
    return make_trigger_sequence(duration, transitions, fs=fs, high=high,
                                 low=low, rise_time=rise_time)


def find_trigger_edges(samples: np.ndarray, fs: float,
                       threshold: float = 0.0,
                       min_separation: float = 1e-6,
                       polarity: str = "both") -> np.ndarray:
    """
    Recover edge times from a digitised trigger channel, with sub-sample
    resolution by linear interpolation across the threshold crossing.

    Returns times in seconds from the start of the record.

    `polarity` selects which transitions count: "both" (the default, and what
    this function has always done), "rising", or "falling".

    **"both" is the wrong choice for a real laser trigger, and wrong in a quiet
    way.** The Santec emits a 25 us PULSE every step (TSL-775 p46), so each
    logged point produces TWO transitions -- up, then down 25 us later. Asking
    for both and averaging the intervals gives a step halfway between 25 us and
    the real spacing: a number that looks perfectly plausible and is roughly
    half of the truth, which would compress the whole wavelength axis.
    Anything deriving a STEP or counting PULSES wants "rising".

    "both" remains the default because interval-symmetric callers exist and
    were written against it, and because a square-wave trigger (which is what
    the emulator produced before pulse trains were modelled) is unaffected.
    """
    if polarity not in ("both", "rising", "falling"):
        raise ValueError(
            f"polarity must be 'both', 'rising' or 'falling', got {polarity!r}"
        )
    x = np.asarray(samples, dtype=float)
    above = x > threshold
    step = np.diff(above.astype(np.int8))
    if polarity == "rising":
        idx = np.flatnonzero(step > 0)
    elif polarity == "falling":
        idx = np.flatnonzero(step < 0)
    else:
        idx = np.flatnonzero(step != 0)
    if idx.size == 0:
        return np.zeros(0)

    times = []
    for i in idx:
        y0, y1 = x[i], x[i + 1]
        frac = 0.0 if y1 == y0 else (threshold - y0) / (y1 - y0)
        times.append((i + frac) / fs)
    times = np.array(times)

    # Debounce: drop edges closer together than min_separation.
    keep = [0]
    for j in range(1, len(times)):
        if times[j] - times[keep[-1]] >= min_separation:
            keep.append(j)
    return times[keep]
