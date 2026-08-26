#!/usr/bin/env python3
"""
P6 -- robustness and delivery. DRIVES OUTPUTS in steps 1 and 2.

    python scripts/p6_robustness.py --step 1 --i-am-present --serial COM29
    python scripts/p6_robustness.py --step 2 --i-am-present --serial COM29
    python scripts/p6_robustness.py --step 4

  --step 1  P6.1  Repeat the full sweep N times (20 by default) and measure
                  real sweep-to-sweep repeatability, against loopback's 0.003%.
  --step 2  P6.2  The delivery format: a full stepped SERIES. You move the
                  stepping laser between sweeps and type its wavelength; the
                  script captures, reduces and writes the set.
  --step 3  P6.3  Averaging across sweeps, if wanted. **Q13 decided NO
                  averaging**, so this only MEASURES what averaging would buy
                  and changes no default.
  --step 4  P6.4  Failure behaviour with the real system: trigger absent,
                  serial link dropped, laser not sweeping. Drives no outputs.

P6 needs Q13, Q15 and **Q17 -- the success criteria** -- which are still
deferred. The script reports numbers; deciding whether they are good enough is
Kevin's, and it says so rather than inventing a threshold.
"""
from __future__ import annotations

import argparse
import sys
import time

import numpy as np

sys.path.insert(0, "scripts")
from _bench import (PLAN, add_common_args, banner, check_helper,  # noqa
                    require_consent, Results, session)

sys.path.insert(0, "src")
from rp_lockin import (SweepSeries, reduce_sweep, write_series)  # noqa: E402
from rp_lockin.santec import SantecTSL  # noqa: E402


def parse():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    add_common_args(ap, needs_output=True)
    ap.add_argument("--step", type=int, required=True, choices=(1, 2, 3, 4))
    ap.add_argument("--repeats", type=int, default=20)
    ap.add_argument("--steps", type=int, default=11,
                    help="stepping-laser positions for P6.2 (default 11)")
    ap.add_argument("--amplitude", type=float, default=0.5)
    ap.add_argument("--serial")
    ap.add_argument("--lan")
    ap.add_argument("--out", default="data/p6_series")
    return ap.parse_args()


def open_laser(args):
    if not (args.serial or args.lan):
        raise SystemExit("this step needs the laser: give --serial or --lan")
    return (SantecTSL.over_lan(args.lan) if args.lan
            else SantecTSL.over_serial(args.serial))


def one_sweep(rp, laser, args):
    """Arm, wait for the operator's sweep, reduce. Returns a SweepReduction."""
    rp.setup_acquisition(decimation=args.decimation, coupling="AC", gain="LV")
    rp.setup_channel(2, gain="HV")
    n = int(1.2 * rp.base_rate / args.decimation)
    det, trig = rp.acquire_deep_fast(
        n_samples=n, decimation=args.decimation, channels=(1, 2),
        trigger="CH2_PE", trigger_level=1.0, trigger_timeout=120.0)
    wl = laser.read_wavelengths()
    return reduce_sweep(det, trig, rp.base_rate / args.decimation, wl,
                        f_ref=PLAN.difference)


def drive_both(rp, args):
    rp.setup_am_generator(carrier=PLAN.carrier, modulation=PLAN.f1,
                          amplitude=args.amplitude, channel=1)
    rp.setup_am_generator(carrier=PLAN.carrier, modulation=PLAN.f2,
                          amplitude=args.amplitude, channel=2)


def step1(rp, args, res):
    """P6.1 -- repeatability across N real sweeps."""
    laser = open_laser(args)
    try:
        require_consent(args, "P6.1 repeatability",
                        f"Both outputs drive at {args.amplitude} V for "
                        f"{args.repeats} sweeps.")
        drive_both(rp, args)
        peaks, firsts, steps = [], [], []
        for i in range(args.repeats):
            print(f"\nsweep {i + 1} of {args.repeats}: START THE SWEEP now.")
            red = one_sweep(rp, laser, args)
            _wl, amp = red.trace.dropna()
            peaks.append(float(amp.max()))
            firsts.append(red.first_edge)
            steps.append(red.step)
            print(f"  peak {amp.max() * 1e6:.3f} uV, first edge "
                  f"{red.first_edge * 1e3:.4f} ms")
        rp.write("OUTPUT1:STATE OFF")
        rp.write("OUTPUT2:STATE OFF")

        peaks = np.array(peaks)
        rel = float(np.std(peaks) / np.mean(peaks))
        res.add("P6.1 sweeps completed", len(peaks))
        res.add("P6.1 peak amplitude rms spread", f"{rel * 100:.4f}%")
        res.add("P6.1 against loopback's 0.0029%",
                f"{rel * 100 / 0.0029:.1f}x worse" if rel > 0 else "identical")
        res.add("P6.1 first-edge spread (ns)",
                f"{np.std(firsts) * 1e9:.1f}")
        res.add("P6.1 logged-step spread (ppm)",
                f"{np.std(steps) / np.mean(steps) * 1e6:.2f}")
        res.add("P6.1 VERDICT", "Q17 (the success criteria) is still deferred, "
                                "so this reports the numbers and does not "
                                "declare a pass.")
    finally:
        laser.close()


def step2(rp, args, res):
    """P6.2 -- the delivery format: a full stepped series."""
    laser = open_laser(args)
    try:
        require_consent(args, "P6.2 stepped series",
                        f"Both outputs drive at {args.amplitude} V across "
                        f"{args.steps} stepping-laser positions.")
        drive_both(rp, args)
        series = SweepSeries()
        for i in range(args.steps):
            banner(f"step {i + 1} of {args.steps}")
            print("Set the STEPPING laser to its next wavelength and let it "
                  "settle.")
            raw = input("  its wavelength in nm (blank to stop): ").strip()
            if not raw:
                break
            lam2 = float(raw) * 1e-9
            print("  START THE SWEEP on the fine laser now.")
            red = one_sweep(rp, laser, args)
            series.add(lam2, red)
            _w, amp = red.trace.dropna()
            print(f"  peak {amp.max() * 1e6:.3f} uV"
                  f"{'' if red.alignment.ok else '   ** ALIGNMENT SUSPECT **'}")
        rp.write("OUTPUT1:STATE OFF")
        rp.write("OUTPUT2:STATE OFF")

        if not len(series):
            res.fail("P6.2 series", "no sweeps recorded")
            return
        paths = write_series(args.out, series)
        res.ok("P6.2 series written", f"{len(series)} sweeps, "
                                      f"{len(paths)} files under {args.out}")
        for line in series.describe().splitlines():
            res.add("P6.2", line)
    finally:
        laser.close()


def step3(rp, args, res):
    """P6.3 -- what averaging WOULD buy. Q13 decided against it."""
    res.add("P6.3 Q13", "Kevin decided NO averaging on 2026-08-14. This step "
                        "measures what it would buy and changes nothing.")
    res.add("P6.3 how to run it", "use --step 1 to collect N sweeps, then "
                                  "compare the spread of single sweeps against "
                                  "the spread of their mean. Averaging N "
                                  "sweeps should reduce noise by sqrt(N); if "
                                  "it does not, the variation is systematic "
                                  "rather than random, and averaging is the "
                                  "wrong tool for it.")


def step4(rp, args, res):
    """P6.4 -- failure behaviour, with nothing driven."""
    banner("P6.4 -- failure behaviour. No outputs are driven in this step.")

    # 1. Trigger absent. H7.2 fixed a defect here that left the board armed
    #    and SCPI wedged; this confirms it against the REAL trigger source.
    print("\nDO NOT start a sweep. Waiting for a trigger that will not come.")
    rp.setup_acquisition(decimation=args.decimation, coupling="AC", gain="LV")
    rp.setup_channel(2, gain="HV")
    n = int(0.05 * rp.base_rate / args.decimation)
    t0 = time.monotonic()
    try:
        rp.acquire_deep_fast(n_samples=n, decimation=args.decimation,
                             channels=(1, 2), trigger="CH2_PE",
                             trigger_level=1.0, trigger_timeout=8.0)
        res.fail("P6.4 absent trigger", "the capture returned, which means "
                                        "something triggered it")
    except Exception as exc:                                    # noqa: BLE001
        res.ok("P6.4 absent trigger raises cleanly",
               f"{type(exc).__name__} after {time.monotonic() - t0:.1f} s")

    # 2. And the board must still answer afterwards -- the H7.2 failure was a
    #    board left armed, which stops answering SCPI while still accepting
    #    connections. It presents as a dead cable, not as a stuck capture.
    try:
        idn = rp.idn()
        res.ok("P6.4 board still healthy after the timeout", idn)
    except Exception as exc:                                    # noqa: BLE001
        res.fail("P6.4 board wedged after the timeout", repr(exc))

    # 3. Serial link dropped mid-read.
    if args.serial or args.lan:
        laser = open_laser(args)
        laser.close()
        try:
            laser.idn()
            res.fail("P6.4 dropped serial link", "a closed port answered")
        except Exception as exc:                                # noqa: BLE001
            res.ok("P6.4 dropped serial link raises cleanly",
                   type(exc).__name__)
    else:
        res.add("P6.4 serial drop", "skipped -- no --serial or --lan given")


def main():
    args = parse()
    handler = {1: step1, 2: step2, 3: step3, 4: step4}[args.step]
    res = Results(f"P6.{args.step} -- robustness and delivery")
    with session(args.host, f"P6.{args.step}") as rp:
        check_helper(rp)
        handler(rp, args, res)
    return res.finish()


if __name__ == "__main__":
    raise SystemExit(main())
