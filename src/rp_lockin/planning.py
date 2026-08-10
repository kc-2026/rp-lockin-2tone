"""
Capture planning: does one sweep fit in the board's memory, and at what cost?

The binding constraint on this project is not processing speed, it is the
reserved DMA region. On the bench board it ships at 2 MiB, which at 125 MS/s on
two channels is 4.2 ms -- far short of a 1 s sweep. The region is a device-tree
parameter and goes to 512 MB, which is the size of the upper half of RAM that
mem=512M keeps outside Linux. Reserving from up there costs the OS nothing.

The second constraint is aliasing, and it has a pleasant resolution: the
board's own analog front end rolls off at 60 MHz, so decimating by 2 puts
Nyquist at 62.5 MHz -- above the rolloff, meaning nothing is left to fold.
Decimation 2 is therefore free. Below that you start folding real noise.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .constants import (ANALOG_BANDWIDTH, BASE_SAMPLE_RATE, BOARD_RAM_MB,
                        DMA_REGION_BASE, MAX_DMA_MB)
from .dsp import min_record_seconds

__all__ = ["CaptureOption", "plan_capture", "describe_capture_plan",
           "settling_points", "recommended_preroll"]

# Assumed transfer rate for the estimates below. MEASURED 2026-08-10 at only
# 3.6-4.3 MB/s pulling deep-memory blocks over SCPI -- about 25x slower than
# this. The bottleneck is the SCPI server, not the link. Every "transfer"
# figure this module prints is therefore optimistic by that factor: a 477 MB
# sweep is ~2 minutes, not 4.8 s. Left at 100 until the deep-memory path is
# trustworthy enough to characterise properly, but do not quote these numbers.
GBE_MB_PER_S = 100.0


@dataclass(frozen=True)
class CaptureOption:
    decimation: int
    sample_rate: float
    megabytes: float
    aliasing_free: bool
    fits_default: bool

    @property
    def nyquist(self) -> float:
        return self.sample_rate / 2

    @property
    def transfer_seconds(self) -> float:
        return self.megabytes / GBE_MB_PER_S


def plan_capture(sweep_seconds: float, f_lockin: float,
                 fs: float = BASE_SAMPLE_RATE, n_channels: int = 2,
                 dma_megabytes: int = 32,
                 min_oversample: int = 8) -> list[CaptureOption]:
    """
    Enumerate viable acquisition decimations for one sweep.

    min_oversample is how many samples per cycle of the lock-in frequency to
    insist on. Nyquist alone (2) is not enough in practice; 8 keeps the
    demodulator's mixing products well separated and leaves room for the
    anti-alias filters to work.
    """
    options = []
    for dec in (1, 2, 4, 8, 16, 32, 64):
        rate = fs / dec
        if rate < min_oversample * f_lockin:
            continue
        mb = sweep_seconds * rate * 2 * n_channels / 1024 ** 2
        options.append(CaptureOption(
            decimation=dec,
            sample_rate=rate,
            megabytes=mb,
            aliasing_free=rate / 2 >= ANALOG_BANDWIDTH,
            fits_default=mb <= dma_megabytes,
        ))
    return options


def recommend(options: list[CaptureOption]) -> CaptureOption | None:
    """Lowest decimation that is aliasing-free and fits the MAX_DMA_MB ceiling."""
    viable = [o for o in options if o.megabytes <= MAX_DMA_MB]
    if not viable:
        return None
    free = [o for o in viable if o.aliasing_free]
    return free[-1] if free else viable[0]


def describe_capture_plan(sweep_seconds: float, f_lockin: float,
                          output_points: int = 5000,
                          fs: float = BASE_SAMPLE_RATE,
                          n_channels: int = 2,
                          dma_megabytes: int = 32) -> str:
    """Human-readable capture plan, including the device-tree edit if needed."""
    out_rate = output_points / sweep_seconds
    bandwidth = 0.9 * out_rate / 2
    tau = 1 / (2 * np.pi * bandwidth)

    lines = [
        f"Sweep {sweep_seconds * 1e3:g} ms | lock-in {f_lockin / 1e6:g} MHz | "
        f"{output_points} points | {n_channels} input channel(s)",
        "",
        f"  output rate      {out_rate:g} Sa/s  (point spacing "
        f"{1e6 / out_rate:.0f} us)",
        f"  honest bandwidth {bandwidth:.0f} Hz  (0.9 x output Nyquist)",
        f"  equivalent tau   {tau * 1e6:.0f} us  = "
        f"{tau * f_lockin:.0f} cycles of the lock-in frequency",
    ]
    if tau * f_lockin < 5:
        lines.append("  ! Fewer than 5 cycles per integration time -- the lock-in "
                     "will not average the carrier away. Raise |f2-f1|.")

    min_rec = min_record_seconds(fs, bandwidth)
    if sweep_seconds < min_rec:
        lines.append(f"  ! Sweep is shorter than the filter settling time "
                     f"({min_rec * 1e3:.1f} ms).")

    options = plan_capture(sweep_seconds, f_lockin, fs, n_channels, dma_megabytes)
    lines += ["", f"  {'dec':>4} {'rate':>12} {'Nyquist':>10} {'MB':>7} "
                  f"{'fits 32MB':>10} {'transfer':>9}  aliasing"]
    for o in options:
        note = "none (below 60 MHz analog rolloff)" if o.aliasing_free \
            else f"{o.nyquist / 1e6:.0f}-60 MHz folds in"
        lines.append(
            f"  {o.decimation:>4} {o.sample_rate / 1e6:>9.1f} MS/s "
            f"{o.nyquist / 1e6:>8.1f} MHz {o.megabytes:>7.0f} "
            f"{'yes' if o.fits_default else 'no':>10} "
            f"{o.transfer_seconds:>8.1f}s  {note}"
        )

    best = recommend(options)
    lines.append("")
    if best is None:
        lines.append(f"  -> Does not fit the {MAX_DMA_MB} MB ceiling at any usable "
                     f"decimation. Shorten the sweep or split it into segments.")
    elif best.fits_default:
        lines.append(f"  -> decimation {best.decimation} ({best.megabytes:.0f} MB) "
                     f"fits the default {dma_megabytes} MB region. No board changes "
                     f"needed.")
    else:
        region = int(np.ceil(best.megabytes / 64) * 64)
        lines += [
            f"  -> Use decimation {best.decimation} "
            f"({best.sample_rate / 1e6:g} MS/s, "
            f"{'no aliasing penalty' if best.aliasing_free else 'some folding'}) "
            f"and enlarge the reserved DMA region to {region} MB.",
            f"     Transfer is ~{best.transfer_seconds:.1f} s per sweep over "
            f"gigabit Ethernet.",
            "",
            f"     On the board ({BOARD_RAM_MB} MB RAM; Linux is capped at "
            f"512 MB by mem=512M, so the upper half is free for this):",
            f"       rw",
            f"       nano /opt/redpitaya/dts/$(monitor -f)/dtraw.dts",
            f"         buffer@{DMA_REGION_BASE:x} {{ reg = "
            f"<0x{DMA_REGION_BASE:X} 0x{region * 1024 * 1024:X}>; }};",
            f"       cd /opt/redpitaya/dts/$(monitor -f)/",
            f"       dtc -I dts -O dtb ./dtraw.dts -o devicetree.dtb",
            f"       reboot",
        ]
    return "\n".join(lines)


def settling_points(output_rate: float, bandwidth: float | None = None,
                    fs: float = BASE_SAMPLE_RATE) -> tuple[int, float]:
    """
    How many output points, and how much wall-clock time, are lost to filter
    start-up before the trace is valid.

    THIS IS A DESIGN CONSTRAINT, NOT A DETAIL. At 5000 Sa/s with the honest
    2.25 kHz bandwidth the transient is ~108 points -- about 22 ms, or 2% of a
    1 s sweep. If the capture starts at the laser trigger, the first 2% of the
    wavelength range comes back as garbage.

    The fix is a pre-roll: arm the acquisition and place the trigger some
    milliseconds into the record, so the filter is already settled when the
    sweep begins. Deep Memory Acquisition supports this through the trigger
    delay / write-pointer-at-trigger mechanism. Budget at least
    2 x the value returned here.

    Returns (points, seconds).
    """
    from .dsp import _decimation_for, _design_filter_chain

    if bandwidth is None:
        bandwidth = 0.9 * output_rate / 2
    decim = int(round(fs / output_rate))
    _, settle = _design_filter_chain(fs, bandwidth, decim)
    pts = int(np.ceil(settle))
    return pts, pts / output_rate


def recommended_preroll(output_rate: float, bandwidth: float | None = None,
                        fs: float = BASE_SAMPLE_RATE, margin: float = 2.0) -> float:
    """Seconds of pre-trigger capture to request. See settling_points()."""
    _, seconds = settling_points(output_rate, bandwidth, fs)
    return margin * seconds
