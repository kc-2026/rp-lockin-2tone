#!/usr/bin/env python3
"""
P2 -- the laser's trigger into IN2. NO RF, NO OPTICS, NO OUTPUTS DRIVEN.

The cheapest step that can go wrong, and deliberately first: it validates the
whole wavelength path while the only thing connected is a BNC.

    python scripts/p2_trigger_check.py --serial COM29
    python scripts/p2_trigger_check.py --serial COM29 --skip-laser

Needs: the laser's trigger output on IN2, the laser able to sweep, and P1 done
so there is a wavelength table to compare against. **Start a sweep from the
front panel before running this** -- the script never commands one, because a
sweep sends light somewhere.

What it settles:

  P2.1  The trigger's shape against the manual: 3.3 V, 25 us wide, >=50 us
        apart (TSL-775 p46). Rise time is measured because no manual gives it
        (U7).
  P2.2  That it actually fires the acquisition, and what ACQ:TRig:LEV suits.
  P2.3  Recorded pulse count against :READout:POINts? -- the off-by-one guard
        (U12) and the one-log-point-per-pulse question (Q26).
  P2.4  The laser/board clock ratio across the sweep (U11).
  P2.5  The decimation choice against the REAL trigger. Loopback saw zero lost
        edges at decimation 8, but with a synthetic 20 ns edge; a real one is
        far slower, and this is where that is confirmed rather than assumed.

**IN2 MUST BE ON HV.** The trigger swings to 3.3 V and the +/-1 V range clips it
into a flat line -- which reads as "the laser is not triggering" rather than as
a range error. The script sets it, and IN1 stays on LV.
"""
from __future__ import annotations

import argparse
import sys

import numpy as np

sys.path.insert(0, "scripts")
from _bench import (add_common_args, check_helper, require_consent,  # noqa
                    Results, banner, session)

sys.path.insert(0, "src")
from rp_lockin import analyse_trigger_train, check_alignment  # noqa: E402
from rp_lockin.emulator import find_trigger_edges  # noqa: E402
from rp_lockin.santec import SantecTSL  # noqa: E402

# TSL-775 p46, section 6.5. Quoted, not remembered.
SPEC_HIGH_V = 3.3
SPEC_WIDTH_S = 25e-6
SPEC_MIN_GAP_S = 50e-6


def parse():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    add_common_args(ap)
    ap.add_argument("--serial", help="laser serial port, e.g. COM29")
    ap.add_argument("--lan", help="laser IP instead of serial")
    ap.add_argument("--baud", type=int, default=9600)
    ap.add_argument("--skip-laser", action="store_true",
                    help="capture the trigger only; skip P2.3/P2.4, which need "
                         "the laser's own point count")
    ap.add_argument("--seconds", type=float, default=1.2,
                    help="record length (default 1.2 s, to bracket a 1 s sweep)")
    ap.add_argument("--level", type=float, default=1.0,
                    help="ACQ:TRig:LEV in volts (default 1.0, mid-way up a "
                         "3.3 V edge)")
    return ap.parse_args()


def capture_trigger(rp, args, decimation, res=None):
    """One record of IN2, triggered by the laser itself."""
    rp.setup_acquisition(decimation=decimation, coupling="DC", gain="LV")
    # Per channel, and this is the whole reason setup_channel exists: a 3.3 V
    # trigger on the +/-1 V range is a flat clipped line.
    rp.setup_channel(2, gain="HV")
    n = int(args.seconds * rp.base_rate / decimation)
    chans = rp.acquire_deep_fast(n_samples=n, decimation=decimation,
                                 channels=(1, 2), trigger="CH2_PE",
                                 trigger_level=args.level,
                                 trigger_timeout=90.0)
    return chans[1], rp.base_rate / decimation


def pulse_shape(trig, fs, res):
    """P2.1 -- levels, width, gap and rise time, against the manual."""
    lo, hi = float(np.percentile(trig, 1)), float(np.percentile(trig, 99))
    res.add("P2.1 idle / high level (V)", f"{lo:.3f} / {hi:.3f}")
    if abs(hi - SPEC_HIGH_V) < 0.5:
        res.ok("P2.1 high level matches the 3.3 V spec", f"{hi:.3f} V")
    else:
        res.fail("P2.1 high level", f"{hi:.3f} V, expected ~{SPEC_HIGH_V} V. "
                                    f"If it is ~1 V, IN2 is still on LV and "
                                    f"clipping.")

    mid = 0.5 * (lo + hi)
    rise = find_trigger_edges(trig, fs, threshold=mid, polarity="rising")
    fall = find_trigger_edges(trig, fs, threshold=mid, polarity="falling")
    if rise.size < 2:
        res.fail("P2.1 pulses found", rise.size)
        return rise
    res.ok("P2.1 pulses in the record", rise.size)

    # Width: each rising edge to the next falling edge after it.
    idx = np.searchsorted(fall, rise)
    ok = idx < fall.size
    width = fall[idx[ok]] - rise[ok]
    res.add("P2.1 pulse width (us)",
            f"mean {width.mean() * 1e6:.3f}, sd {width.std() * 1e6:.3f}")
    if abs(width.mean() - SPEC_WIDTH_S) < 0.2 * SPEC_WIDTH_S:
        res.ok("P2.1 width matches the 25 us spec", f"{width.mean() * 1e6:.2f} us")
    else:
        res.fail("P2.1 width", f"{width.mean() * 1e6:.2f} us vs 25 us spec")

    gap = np.diff(rise)
    res.add("P2.1 pulse spacing (us)",
            f"mean {gap.mean() * 1e6:.3f}, min {gap.min() * 1e6:.3f}")
    if gap.min() >= SPEC_MIN_GAP_S:
        res.ok("P2.1 spacing respects the 20 kHz maximum", f"{gap.min() * 1e6:.1f} us")
    else:
        res.fail("P2.1 spacing", f"{gap.min() * 1e6:.1f} us, below the 50 us "
                                 f"the 20 kHz maximum implies")

    # Rise time, 10-90%. U7: no manual gives it, and it decides whether
    # decimation 8 can still resolve an edge.
    t10 = find_trigger_edges(trig, fs, threshold=lo + 0.1 * (hi - lo),
                             polarity="rising")
    t90 = find_trigger_edges(trig, fs, threshold=lo + 0.9 * (hi - lo),
                             polarity="rising")
    m = min(t10.size, t90.size)
    if m:
        rt = float(np.median(t90[:m] - t10[:m]))
        res.add("P2.1 rise time 10-90% (ns) -- U7",
                f"{rt * 1e9:.1f}  (sample period is {1e9 / fs:.1f} ns)")
        if rt < 1.0 / fs:
            res.add("P2.1 NOTE", "the edge is faster than one sample at this "
                                 "decimation, so this is an upper bound set by "
                                 "the sample rate, not a measurement")
    return rise


def main():
    args = parse()
    res = Results("P2 -- laser trigger into IN2")

    laser = None
    if not args.skip_laser:
        if not (args.serial or args.lan):
            raise SystemExit("give --serial or --lan, or pass --skip-laser")
        laser = (SantecTSL.over_lan(args.lan) if args.lan
                 else SantecTSL.over_serial(args.serial, baud=args.baud))
        print(f"laser: {laser.idn()}")

    try:
        with session(args.host, "P2 -- trigger into IN2 (no RF, no optics)") as rp:
            check_helper(rp)

            print("\nwaiting for the laser to trigger. START A SWEEP NOW from "
                  "the front panel.")
            trig, fs = capture_trigger(rp, args, args.decimation, res)
            res.ok("P2.2 the capture triggered", f"{trig.size} samples at "
                                                 f"{fs / 1e6:.4f} MS/s")
            rise = pulse_shape(trig, fs, res)
            if rise.size < 3:
                return res.finish()

            # P2.4 -- the two clocks, from a line fit through the whole train.
            train = analyse_trigger_train(rise)
            res.add("P2.4 measured step (us)", f"{train.step * 1e6:.4f}")
            res.add("P2.4 line-fit residual (ns)",
                    f"{train.residual_rms * 1e9:.2f}")
            if train.n_missing == 0:
                res.ok("P2.5 no pulses lost at this decimation",
                       f"decimation {args.decimation}")
            else:
                res.fail("P2.5 pulses lost", f"{train.n_missing} at decimation "
                                             f"{args.decimation}; rerun with "
                                             f"--decimation 4 to compare")

            if laser is not None:
                n_log = laser.logged_points()
                res.add("P2.3 :READout:POINts?", n_log)
                res.add("P2.3 rising edges recorded", rise.size)
                if n_log == rise.size:
                    res.ok("P2.3 Q26: one log point per trigger pulse holds",
                           f"{n_log} = {rise.size}")
                elif n_log and rise.size % n_log == 0:
                    res.fail("P2.3 Q26", f"{rise.size} pulses for {n_log} rows "
                                         f"= exactly {rise.size // n_log} "
                                         f"pulses per row. Logging and "
                                         f"triggering are on different "
                                         f"divisors; the indexing needs that "
                                         f"factor.")
                else:
                    res.fail("P2.3 Q26", f"{rise.size} pulses vs {n_log} rows, "
                                         f"no integer relation. Suspect a late "
                                         f"arm or lost edges.")
                table_t = np.arange(n_log) * train.step
                al = check_alignment(rise, table_t)
                res.add("P2.3 alignment", al.diagnosis)
                cfg = laser.trigger_config()
                res.add("P2.x trigger config (Q24: raw, never inferred)",
                        cfg.describe().splitlines()[0])
    finally:
        if laser is not None:
            laser.close()

    return res.finish()


if __name__ == "__main__":
    raise SystemExit(main())
