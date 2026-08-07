"""
Drive waveform construction for the two-tone AOM experiment.

Both outputs carry an 80 MHz carrier amplitude-modulated at f1 and f2. The DUT
mixes them and the response appears at |f2 - f1|.

The whole design turns on one arithmetic fact: a repeating buffer only replays
seamlessly if it contains a whole number of cycles of BOTH the carrier and the
modulation. Miss that and every buffer wrap injects a discontinuity, scattering
spurs across the baseband -- exactly where the swept trace lives. See
docs/03-frequency-plan.md.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .constants import ASG_BUFFER_MAX, BASE_SAMPLE_RATE

__all__ = ["TwoTonePlan", "make_am_waveform", "plan_two_tone"]


def make_am_waveform(carrier: float, modulation: float,
                     fs: float = BASE_SAMPLE_RATE,
                     depth: float = 1.0) -> tuple[np.ndarray, float]:
    """
    Build the shortest seamless repeating buffer for an AM carrier.

    The buffer must contain a whole number of cycles of BOTH the carrier and
    the modulation, so the minimal length is the smallest N with N*carrier/fs
    and N*modulation/fs both integers. For 80 MHz AM'd at 5 MHz on the 250 MS/s
    board that is 50 samples; at 6 MHz it is 125. Do not assume N = fs/f_mod --
    that only happens to be right when fs/f_mod is itself an integer.

    Getting this wrong is not a subtle error: a fractional buffer glitches at
    every wrap, putting spurs at multiples of fs/N straight across the baseband
    where the swept trace lives.

    Returns (samples, playback_frequency). Load `samples` into the generator's
    arbitrary buffer and set the generator frequency to `playback_frequency`
    = fs/N, which advances the buffer exactly one sample per DAC clock.

    Raises ValueError if no buffer within the generator's depth works.
    """
    if not 0 < depth <= 1.0:
        raise ValueError("depth must be in (0, 1]")
    if not 0 < carrier < fs / 2:
        raise ValueError(f"carrier must be below Nyquist ({fs / 2 / 1e6:.1f} MHz)")
    if not 0 < modulation < carrier:
        raise ValueError("modulation frequency must be below the carrier")

    n = _minimal_buffer(fs, (carrier, modulation))
    if n is None:
        raise ValueError(
            f"No buffer <= {ASG_BUFFER_MAX} samples holds whole cycles of both "
            f"carrier={carrier / 1e6:g} MHz and modulation={modulation / 1e6:g} MHz "
            f"at {fs / 1e6:g} MS/s, so every wrap would glitch. Move the "
            f"frequencies onto the fs/N grid -- see docs/03-frequency-plan.md."
        )

    k = np.arange(n)
    env = 1.0 + depth * np.cos(2 * np.pi * modulation * k / fs)
    wave = env * np.cos(2 * np.pi * carrier * k / fs)
    wave = wave / np.max(np.abs(wave))     # normalise to the generator's -1..+1
    return wave, fs / n


def _minimal_buffer(fs: float, freqs, limit: int = ASG_BUFFER_MAX) -> int | None:
    """Smallest N <= limit making N*f/fs an integer for every f."""
    for n in range(1, limit + 1):
        if all(abs(n * f / fs - round(n * f / fs)) < 1e-9 for f in freqs):
            return n
    return None


@dataclass(frozen=True)
class TwoTonePlan:
    """A validated set of drive frequencies and the buffer that realises them."""

    carrier: float          # Hz, the AOM carrier both channels share
    f1: float               # Hz, modulation on channel 1
    f2: float               # Hz, modulation on channel 2
    buffer_samples: int     # length of the repeating buffer, both channels
    fs: float               # DAC sample rate

    @property
    def difference(self) -> float:
        """The lock-in frequency: where the DUT response appears."""
        return abs(self.f2 - self.f1)

    @property
    def buffer_period(self) -> float:
        return self.buffer_samples / self.fs

    def periods_per_tau(self, tau: float) -> float:
        """Cycles of the difference frequency inside one integration time.

        Lock-in detection needs this comfortably above ~5-10; below that the
        integrator has not seen enough of the waveform to average the carrier
        away, and the output carries residual 1f/2f ripple.
        """
        return tau * self.difference

    def check(self) -> list[str]:
        """Return a list of problems; empty means the plan is exact."""
        problems = []
        for name, f in (("carrier", self.carrier), ("f1", self.f1), ("f2", self.f2)):
            cycles = self.buffer_samples * f / self.fs
            if abs(cycles - round(cycles)) > 1e-9:
                problems.append(
                    f"{name}={f / 1e6:.6g} MHz gives {cycles:.6f} cycles per buffer, "
                    f"not an integer -> discontinuity at every wrap"
                )
        if self.buffer_samples > ASG_BUFFER_MAX:
            problems.append(
                f"buffer {self.buffer_samples} exceeds the generator's "
                f"{ASG_BUFFER_MAX}-sample limit"
            )
        if self.difference <= 0:
            problems.append("f1 and f2 must differ")
        if max(self.carrier + self.f1, self.carrier + self.f2) >= self.fs / 2:
            problems.append("upper sideband is above Nyquist")
        return problems

    def describe(self) -> str:
        lines = [
            f"carrier      {self.carrier / 1e6:g} MHz",
            f"f1           {self.f1 / 1e6:g} MHz   -> sidebands "
            f"{(self.carrier - self.f1) / 1e6:g} / {(self.carrier + self.f1) / 1e6:g} MHz",
            f"f2           {self.f2 / 1e6:g} MHz   -> sidebands "
            f"{(self.carrier - self.f2) / 1e6:g} / {(self.carrier + self.f2) / 1e6:g} MHz",
            f"|f2 - f1|    {self.difference / 1e6:g} MHz  "
            f"(period {1e6 / self.difference:.3f} us)  <-- lock-in frequency",
            f"buffer       {self.buffer_samples} samples = "
            f"{self.buffer_period * 1e6:.3f} us at {self.fs / 1e6:g} MS/s",
        ]
        problems = self.check()
        lines.append("exact: yes" if not problems else "PROBLEMS: " + "; ".join(problems))
        return "\n".join(lines)


def plan_two_tone(difference: float, f1: float = 5e6, carrier: float = 80e6,
                  fs: float = BASE_SAMPLE_RATE) -> TwoTonePlan:
    """
    Find the shortest exact repeating buffer for a two-tone AM drive.

    The buffer length N must make N*f/fs an integer for the carrier and both
    modulations simultaneously. For an 80 MHz carrier at 250 MS/s that forces
    N to be a multiple of 25; the modulations must then land on the resulting
    fs/N frequency grid.

    Raises ValueError if no buffer under the generator's limit works, rather
    than returning one that glitches at every wrap.
    """
    f2 = f1 + difference
    n = _minimal_buffer(fs, (carrier, f1, f2))
    if n is not None:
        plan = TwoTonePlan(carrier=carrier, f1=f1, f2=f2, buffer_samples=n, fs=fs)
        if not plan.check():
            return plan
    raise ValueError(
        f"No buffer <= {ASG_BUFFER_MAX} samples holds whole cycles of "
        f"carrier={carrier / 1e6:g} MHz, f1={f1 / 1e6:g} MHz and "
        f"f2={f2 / 1e6:g} MHz at {fs / 1e6:g} MS/s. Move the frequencies onto "
        f"the fs/N grid -- see docs/03-frequency-plan.md."
    )
