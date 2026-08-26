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
                        DMA_REGION_BASE, DMA_REGION_MB, MAX_DMA_MB)
from .dsp import min_record_seconds

__all__ = ["CaptureOption", "plan_capture", "describe_capture_plan",
           "settling_points", "recommended_preroll"]

# MEASURED 2026-08-12: 5.7 MB/s pulling deep-memory blocks over SCPI, six
# consecutive 7.6 MB reads within 0.02 s of each other.
#
# This is a limitation of the SCPI SERVER, not of the board or the link, and
# the difference matters because it is fixable. Raw TCP from the board's RAM to
# this PC measures 87 MB/s -- 15x faster -- over the same cable, and the board
# writes its own RAM at 151 MB/s. Neither the hardware nor the network is the
# constraint. Note the SCPI payload is already raw binary (FORMAT BIN, 2 bytes
# per sample, verified by byte count), so this is not a text-encoding cost; it
# is something inside the server's own data path.
#
# So a 477 MB one-second sweep is ~84 s over SCPI but would be ~5.5 s over a
# raw socket. If the transfer time ever matters -- H7.1's twenty repeats is
# half an hour over SCPI -- the fix is a raw read of the DMA region rather than
# a change of decimation. See SESSION_LOG.md 2026-08-12.
SCPI_MB_PER_S = 5.7

# What the path we ACTUALLY use manages. `acquire_deep_fast` reads over the raw
# socket, not SCPI, so quoting the SCPI figure in a capture plan overstates the
# transfer by ~2-3x for a path nothing takes.
#
# MEASURED in H6.2: 6.7-11.2 s for a 125 MB two-channel read INCLUDING arming
# and the 1 s capture itself, i.e. 11-19 MB/s. The conservative end is used
# here so an estimate errs slow. That is well short of the 87 MB/s a single
# 64 MB read reached, and the reason is NOT established -- the recorded
# explanation ("~125 round trips at ~50 ms") does not survive reading the code,
# since the client issues at most four GETs per capture. Per-GET timing was
# added to the board helper on 2026-08-25 to settle it; until a capture is run
# with that helper, treat this number as an observation and not a model.
FAST_READ_MB_PER_S = 11.0


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
        """Estimated read-back time over the FAST path, which is the one used.

        `acquire_deep_fast` reads the DMA region over a raw socket; SCPI is
        only used for configuration and arming. Estimating with the SCPI rate
        overstated a 1 s decimation-8 sweep as 21 s against a measured 7-11 s.
        """
        return self.megabytes / FAST_READ_MB_PER_S


def plan_capture(sweep_seconds: float, f_lockin: float,
                 fs: float = BASE_SAMPLE_RATE, n_channels: int = 2,
                 dma_megabytes: int = DMA_REGION_MB,
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
        # MiB, despite the field name -- 1024**2, matching how ACQ:AXI:SIZE?
        # and the device tree describe the region. H6.2's "125.2 MB" is also
        # MiB, and is LARGER than this only because that capture ran 1.05 s
        # including pre-roll: exactly 1.000 s is 119.2 MiB (93.1% of the
        # 128 MiB region), 1.050 s is 125.2 MiB (97.8%). Both figures are
        # right; they describe different captures.
        mb = sweep_seconds * rate * 2 * n_channels / 1024 ** 2
        options.append(CaptureOption(
            decimation=dec,
            sample_rate=rate,
            megabytes=mb,
            aliasing_free=rate / 2 >= ANALOG_BANDWIDTH,
            fits_default=mb <= dma_megabytes,
        ))
    return options


def recommend(options: list[CaptureOption],
              ceiling_megabytes: float = DMA_REGION_MB) -> CaptureOption | None:
    """Lowest decimation that fits `ceiling_megabytes`, preferring aliasing-free.

    The ceiling defaults to the region that EXISTS (128 MiB), not to
    MAX_DMA_MB, which is the hypothetical size after a device-tree move that
    was considered and rejected. Planning against the larger number recommended
    decimation 2 and a board change, contradicting the settled operating point
    of decimation 8 -- and did so for eleven days, because nothing tested it.
    """
    viable = [o for o in options if o.megabytes <= ceiling_megabytes]
    if not viable:
        return None
    free = [o for o in viable if o.aliasing_free]
    return free[-1] if free else viable[0]


def describe_capture_plan(sweep_seconds: float, f_lockin: float,
                          output_points: int = 5000,
                          fs: float = BASE_SAMPLE_RATE,
                          n_channels: int = 2,
                          dma_megabytes: int = DMA_REGION_MB) -> str:
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

    options = plan_capture(sweep_seconds, f_lockin, fs, n_channels,
                           dma_megabytes)
    fits_label = f"fits {dma_megabytes}MB"
    lines += ["", f"  {'dec':>4} {'rate':>12} {'Nyquist':>10} {'MB':>7} "
                  f"{fits_label:>10} {'transfer':>9}  aliasing"]
    for o in options:
        note = "none (below 60 MHz analog rolloff)" if o.aliasing_free \
            else f"{o.nyquist / 1e6:.0f}-60 MHz folds in"
        lines.append(
            f"  {o.decimation:>4} {o.sample_rate / 1e6:>9.1f} MS/s "
            f"{o.nyquist / 1e6:>8.1f} MHz {o.megabytes:>7.0f} "
            f"{'yes' if o.fits_default else 'no':>10} "
            f"{o.transfer_seconds:>8.1f}s  {note}"
        )

    best = recommend(options, dma_megabytes)
    lines.append("")
    if best is None:
        lines.append(
            f"  -> Does not fit the {dma_megabytes} MB region at any usable "
            f"decimation. Shorten the sweep, drop to one channel, or split it "
            f"into segments.")
    elif best.fits_default:
        lines.append(
            f"  -> decimation {best.decimation} ({best.megabytes:.0f} MB) fits "
            f"the {dma_megabytes} MB region. No board changes needed. "
            f"Read-back ~{best.transfer_seconds:.0f} s over the fast socket.")
    else:
        region = int(np.ceil(best.megabytes / 64) * 64)
        lines += [
            f"  -> Use decimation {best.decimation} "
            f"({best.sample_rate / 1e6:g} MS/s, "
            f"{'no aliasing penalty' if best.aliasing_free else 'some folding'}) "
            f"and enlarge the reserved DMA region to {region} MB.",
            f"     Transfer is ~{best.transfer_seconds:.0f} s per sweep over "
            f"the fast socket at {FAST_READ_MB_PER_S:g} MB/s (measured H6.2). "
            f"Over SCPI the same bytes would take "
            f"{best.megabytes / SCPI_MB_PER_S:.0f} s.",
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
    2.25 kHz bandwidth the transient is **113 points at the operating point** --
    about 22.6 ms, or 2% of a 1 s sweep. If the capture starts at the laser
    trigger, the first 2% of the wavelength range comes back as garbage.

    **It is 108 or 113 depending on `fs`, and that is not drift.** The multistage
    chain factorises differently at different input rates, so the transient
    length steps between 108 and 113 points (21.6 or 22.6 ms) non-monotonically
    with decimation. At decimation 8, the operating point, it is 113. Pass the
    `fs` you will actually capture at rather than trusting the 250 MS/s default,
    which describes decimation 1 -- a configuration nothing uses. The difference
    is 1 ms of pre-roll and never matters; being surprised by it does.

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


def recommended_tail(output_rate: float, bandwidth: float | None = None,
                     fs: float = BASE_SAMPLE_RATE, margin: float = 1.5) -> float:
    """
    Seconds to keep capturing AFTER the sweep ends. Pre-roll alone is not enough.

    Measured on hardware 2026-08-14, doing H6.3. A 1 s sweep captured with 45 ms
    of pre-roll and stopping exactly at the trigger + 1 s yielded **4943 output
    points, not 5000** -- 57 short, with no error anywhere and a trace that
    looked perfectly healthy, just ending early.

    The cause is that `LockinResult.t` compensates the filter's GROUP DELAY as
    well as trimming its settling. That SHIFTS the valid window rather than only
    shortening it, so the usable span ends roughly half the settling length
    before the record does. 57 points is almost exactly half of the 113 that
    were trimmed.

    So the record has to bracket the sweep on BOTH sides: settling before it, and
    about half the settling after it. Re-running with a 20 ms tail gave exactly
    5000 points spanning +0.1 to 999.9 ms, at exactly 200.000 us spacing with
    zero jitter.

    The default margin of 1.5 is deliberately smaller than the pre-roll's 2.0:
    the tail requirement is half the size and is competing for the same DMA
    region, which a 1 s two-channel capture already fills to 97%.

    Returns seconds.
    """
    _, seconds = settling_points(output_rate, bandwidth, fs)
    return margin * 0.5 * seconds
