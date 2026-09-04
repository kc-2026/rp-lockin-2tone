#!/usr/bin/env python3
"""
Characterise the lock-in OUTPUT filter, and answer the sampling question.

    .venv\\Scripts\\python.exe scripts\\filter_study.py

**Offline. Touches no hardware.** Every number in `docs/13-output-filter.md`
comes from this script, so it can be re-run after any change to `dsp.py`.

The question it exists to answer (Kevin, 2026-09-04):

    "Traditionally, the output of a lock-in amplifier must be sampled ~5x more
     coarsely than the filter. The ~5000 points here comes from a 30 us time
     constant and a 0.8 s sweep, which gives 5600 points. Is the current
     approach compatible with this? Something seems off since a sub-second
     sweep can be rendered into 5000 points despite having a 2250 Hz
     bandwidth."

Two traps this script exists to avoid, both of which produced a wrong answer
the first time round (see `docs/11-mistakes.md` 2.9 and 2.10):

  * **Measuring an impulse width on the output grid.** At 2250 Hz the impulse
    is ~255 us and the output steps every 200 us, so a FWHM read off the trace
    quantises to about half its own value -- it reads 450 us and looks like the
    resolution formula is 2x optimistic. `impulse_width()` raises the output
    rate while holding the bandwidth: same filter, finer ruler.
  * **Summing only the positive autocorrelation lags.** This chain's
    autocorrelation alternates in sign, so dropping the negative terms counts
    the correlation and ignores the anticorrelation cancelling it.
    `independent_values()` sums all lags and cross-checks against the variance
    of block means.
"""
from __future__ import annotations

import os
import sys

import numpy as np
import scipy.signal as sps

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "src"))

from rp_lockin.dsp import demodulate, _design_filter_chain   # noqa: E402

FS = 31.25e6            # decimation 8, the operating point
F_REF = 915e3           # the bench default f1
ORATE = 5000.0
BW = 2250.0
SPEED_NM_S = 100.0      # for the wavelength columns

# sigma_f = K * f3dB for a Gaussian:  exp(-f3^2 / 2 sigma^2) = 1/sqrt(2)
K_GAUSS = 1.0 / np.sqrt(2 * np.log(np.sqrt(2.0)))


# --------------------------------------------------------------- the filter

def final_stage(bw=BW, orate=ORATE, fs=FS):
    stages, settle = _design_filter_chain(fs, bw, int(round(fs / orate)))
    return stages[-1][0], stages, settle


def response_db(taps, fs_out, freqs):
    """Normalise by the DC response, NOT by the first frequency asked for --
    doing the latter silently returns 0.0 dB for every single-frequency call."""
    dc = abs(float(np.sum(taps)))
    _, h = sps.freqz(taps, worN=2 * np.pi * np.asarray(freqs, float) / fs_out)
    return 20 * np.log10(np.maximum(np.abs(h) / dc, 1e-14))


def minus_3db(taps, fs_out):
    f = np.linspace(1.0, fs_out / 2, 5000)
    return float(f[int(np.argmax(response_db(taps, fs_out, f) < -3.0))])


def gaussian_db(freq, f3):
    """Closed form. A Gaussian with a 2223 Hz -3 dB point has sigma_t = 60 us,
    which is 0.30 of a sample at 5000 Sa/s -- it is not a realisable FIR at
    that rate, so a discrete version collapses to a delta and reads flat."""
    return 20 * np.log10(np.exp(-0.5 * (np.asarray(freq, float)
                                        / (K_GAUSS * f3)) ** 2))


def one_pole_db(freq, f3):
    return -10 * np.log10(1 + (np.asarray(freq, float) / f3) ** 2)


# ------------------------------------------------------------ measurements

def impulse_width(bw=BW, probe_rate=50000.0, secs=0.40, burst=10e-6):
    """FWHM of the chain's impulse response, with the OUTPUT oversampled."""
    n = int(FS * secs)
    t = np.arange(n) / FS
    sig = np.zeros(n)
    sig[(t > secs / 2) & (t < secs / 2 + burst)] = 1.0
    sig *= np.cos(2 * np.pi * F_REF * t)
    r = demodulate(sig, FS, F_REF, bandwidth=bw, output_rate=probe_rate)
    y = np.abs(r.X + 1j * r.Y)
    half, i = y.max() / 2.0, int(np.argmax(y))

    def cross(a, b):
        return (r.t[a] if y[b] == y[a] else
                r.t[a] + (half - y[a]) * (r.t[b] - r.t[a]) / (y[b] - y[a]))

    lo = i
    while lo > 0 and y[lo] > half:
        lo -= 1
    hi = i
    while hi < len(y) - 1 and y[hi] > half:
        hi += 1
    return cross(hi, hi - 1) - cross(lo, lo + 1)


def transfer(bw=BW, orate=ORATE, freqs=(200, 1000, 2000, 2200, 2400, 2500),
             secs=0.5, depth=0.5):
    """What survives to the output, measured the way the filter is used:
    amplitude-modulate the carrier and recover the modulation."""
    out = {}
    for f_m in freqs:
        n = int(FS * secs)
        t = np.arange(n) / FS
        sig = (1 + depth * np.cos(2 * np.pi * f_m * t)) \
            * np.cos(2 * np.pi * F_REF * t)
        r = demodulate(sig, FS, F_REF, bandwidth=bw, output_rate=orate)
        y = np.abs(r.X + 1j * r.Y)
        y = y - y.mean()
        out[f_m] = 2.0 * abs(np.sum(y * np.exp(-2j * np.pi * f_m * r.t))) / len(y)
    ref = out[freqs[0]]
    return {k: 20 * np.log10(max(v / ref, 1e-12)) for k, v in out.items()}


def step_overshoot(bw=BW, orate=ORATE, secs=0.30):
    n = int(FS * secs)
    t = np.arange(n) / FS
    sig = (t >= secs / 2).astype(float) * np.cos(2 * np.pi * F_REF * t)
    r = demodulate(sig, FS, F_REF, bandwidth=bw, output_rate=orate)
    y = np.abs(r.X + 1j * r.Y)
    settled = float(np.median(y[int(len(y) * 0.75):]))
    after = y[int(np.argmax(r.t >= secs / 2)):] / settled
    return after.max() - 1.0, after[:10]


def independent_values(bw=BW, orate=ORATE, secs=3.0, seed=1, kmax=40):
    """Degrees of freedom per second. ALL lags, plus a block-variance check."""
    rng = np.random.default_rng(seed)
    x = demodulate(rng.standard_normal(int(FS * secs)), FS, F_REF,
                   bandwidth=bw, output_rate=orate).X
    x = (x - x.mean()) / x.std()
    ac = [float(np.mean(x[:len(x) - k] * x[k:])) for k in range(1, kmax)]
    tau_all = 1.0 + 2.0 * sum(ac)
    tau_pos = 1.0 + 2.0 * sum(a for a in ac if a > 0.02)
    blocks = {}
    for b in (16, 32, 64, 128):
        m = len(x) // b
        blocks[b] = float(x[:m * b].reshape(m, b).mean(axis=1).var(ddof=1)
                          * b / x.var(ddof=1))
    return dict(ac=ac[:5], tau_all=tau_all, tau_positive_only=tau_pos,
                blocks=blocks, per_second=orate / tau_all)


def main():
    taps, stages, settle = final_stage()
    nyq = ORATE / 2
    cutoff = min(BW, 0.9 * nyq)
    f3 = minus_3db(taps, ORATE)

    print("=" * 70)
    print("1. WHAT THE OUTPUT FILTER IS")
    print("=" * 70)
    print(f"  Kaiser FIR, {len(taps)} taps at {ORATE:.0f} Sa/s, 60 dB stopband")
    print(f"  preceded by decimation stages {[f for _, f in stages[:-1]]}")
    print(f"  cutoff {cutoff:.0f} Hz, measured -3 dB {f3:.0f} Hz")
    print(f"  settling {settle:.0f} output samples")
    print()
    print("  transition width, and which term binds:")
    print(f"    0.8 x cutoff              = {0.8 * cutoff:7.1f} Hz  <- intent")
    print(f"    0.10 x Nyquist            = {0.10 * nyq:7.1f} Hz")
    print(f"    0.95 x (Nyquist - cutoff) = {0.95 * (nyq - cutoff):7.1f} Hz  <- binds")
    print("  A brickwall by accident, and only where bandwidth = 0.9 x Nyquist.")

    print("\n" + "=" * 70)
    print("2. TRANSFER FUNCTION, against a Gaussian and an RC of the same -3 dB")
    print("=" * 70)
    meas = transfer()
    print(f"  {'f Hz':>8} {'measured':>10} {'from taps':>10} "
          f"{'Gaussian':>10} {'1-pole RC':>10}")
    for f_m in sorted(meas):
        print(f"  {f_m:>8} {meas[f_m]:>10.1f} "
              f"{response_db(taps, ORATE, [f_m])[0]:>10.1f} "
              f"{float(gaussian_db(f_m, f3)):>10.1f} "
              f"{float(one_pole_db(f_m, f3)):>10.1f}")
    print("\n  A Gaussian and an RC are equally leaky at the output Nyquist.")
    print("  THAT is what the 5x rule exists to manage. Ours has no tails.")

    f60 = np.sqrt(2 * np.log(1000.0)) * K_GAUSS * f3
    print(f"\n  For 60 dB at its own Nyquist a Gaussian needs {2 * f60:.0f} Sa/s")
    print(f"  = {2 * f60 / f3:.1f}x its -3 dB point, against our {ORATE / f3:.1f}x.")
    print("  That is affordable: 25000 Sa/s divides 31.25 MS/s exactly and")
    print("  max_output_rate allows 31250 at f1 = 915 kHz. The 5000 is R5, a")
    print("  SPECIFICATION, not a hardware limit.")

    print("\n" + "=" * 70)
    print("3. WHAT THE SHARPNESS COSTS -- step overshoot")
    print("=" * 70)
    for bw in (2250.0, 2000.0, 1500.0, 1000.0, 500.0):
        over, _ = step_overshoot(bw)
        print(f"  bandwidth {bw:>6.0f} Hz   overshoot {over * 100:+5.2f}%")
    _, first = step_overshoot()
    print("  first output samples after a step: "
          + ", ".join(f"{v:.3f}" for v in first))
    print("  A Gaussian has no overshoot and no sidelobes, by construction.")

    print("\n" + "=" * 70)
    print("4. RESOLUTION -- measure it OVERSAMPLED or you measure your own grid")
    print("=" * 70)
    print(f"  {'bw Hz':>8} {'FWHM us':>10} {'1/(2B) us':>11} {'ratio':>7} {'pm':>7}")
    for bw in (2250.0, 2000.0, 1500.0, 1000.0):
        w = impulse_width(bw)
        pred = 1.0 / (2 * bw)
        print(f"  {bw:>8.0f} {w * 1e6:>10.1f} {pred * 1e6:>11.1f} "
              f"{w / pred:>7.2f} {w * SPEED_NM_S * 1e3:>7.1f}")
    print(f"  (pm column is at {SPEED_NM_S:g} nm/s)")
    print(f"  On the 5000 Sa/s grid the same 2250 Hz measurement reads "
          f"{impulse_width(2250.0, probe_rate=ORATE) * 1e6:.0f} us -- twice the truth.")

    print("\n" + "=" * 70)
    print("5. DEGREES OF FREEDOM -- 5000 samples are not 5000 measurements")
    print("=" * 70)
    r = independent_values()
    print("  autocorrelation lags 1-5: "
          + ", ".join(f"{a:+.3f}" for a in r["ac"]))
    print(f"  tau_int, all lags            {r['tau_all']:.2f}")
    print(f"  tau_int, positive terms only {r['tau_positive_only']:.2f}  <- WRONG")
    print("  tau_int from block variance  "
          + ", ".join(f"{b}:{v:.2f}" for b, v in r["blocks"].items()))
    print(f"  -> {r['per_second']:.0f} independent values per second, "
          f"of {ORATE:.0f} taken")
    print(f"  -> 2 x bandwidth = {2 * BW:.0f}")

    print("\n" + "=" * 70)
    print("6. THE ORIGINAL SPECIFICATION, checked")
    print("=" * 70)
    tau, sweep = 30e-6, 0.8
    corner = 1 / (2 * np.pi * tau)
    rate = 1 / (5 * tau)
    print(f"  tau = {tau * 1e6:.0f} us  ->  RC corner {corner:.0f} Hz")
    print(f"  5*tau spacing  ->  {rate:.0f} Sa/s = {rate * sweep:.0f} points "
          f"in {sweep:g} s")
    print(f"  Nyquist there  ->  {rate / 2:.0f} Hz")
    print(f"  corner / Nyquist = {corner / (rate / 2):.2f}   >1 means IT ALIASES")


if __name__ == "__main__":
    main()
