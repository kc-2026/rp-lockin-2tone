#!/usr/bin/env python3
"""
P4 -- optics connected, laser at low power. DRIVES AN OUTPUT in step 2.

    python scripts/p4_detector.py --step 1
    python scripts/p4_detector.py --step 2 --i-am-present
    python scripts/p4_detector.py --step 4

**P4.4 is the step that decides whether the project works.** Loopback says a
signal needs >=36 uV to be clearly visible, measured in a quiet box with 30 cm
of cable. It can only get worse from here; this is where you find out by how
much.

  --step 1  P4.1  Detector output level and DC offset, laser on, NO RF.
                  Sets the input range and coupling (Q11, U5). No output driven.
  --step 2  P4.2  Detector response near 1 MHz (U4). Modulates ONE AOM and
                  steps the modulation frequency. DRIVES AN OUTPUT.
  --step 3  P4.3  Nothing clips across a full wavelength sweep. No output
                  driven; you start the sweep from the front panel.
  --step 4  P4.4  Noise floor with everything connected and NO drive (U6) --
                  the real SNR number. No output driven.

WHAT TO EXPECT, so a wrong answer is recognisable

* **AC-couple IN1.** The detector sits on a 0-10 V pedestal that will not fit
  the +/-1 V range, and the +/-20 V range puts the ADC back in charge at 45 uV.
  AC coupling is free here: Q25 measured the corner at 17.0 Hz, so attenuation
  at 991.821 kHz is 1e-9 dB and the noise floor is unchanged.
* **P4.4 should land near 11-12 uV.** Near 3.6 uV means the detector is
  probably not in the path at all -- that is the board's own floor. Above
  ~25 uV means something is wrong beyond the datasheet.
* **U4 is already closed on paper**: the PDA05CF2 has 150 MHz of bandwidth, so
  there is no rolloff anywhere near 991.821 kHz. P4.2 confirms it in the real
  path rather than trusting it.
* Saturation is around 0.96 mW optical. **No damage threshold is in the
  manual**, so do not exceed saturation without asking.
"""
from __future__ import annotations

import argparse
import sys
import time

import numpy as np

sys.path.insert(0, "scripts")
from _bench import (PLAN, add_common_args, banner, check_helper,  # noqa
                    require_consent, Results, session, summarise)

sys.path.insert(0, "src")
from rp_lockin import asg_grid, demodulate  # noqa: E402

EXPECTED_FLOOR_V = 11e-6      # detector-dominated, from the PDA05CF2 datasheet
BOARD_FLOOR_V = 3.57e-6       # H3.3, loopback


def parse():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    add_common_args(ap, needs_output=True)
    ap.add_argument("--step", type=int, required=True, choices=(1, 2, 3, 4))
    ap.add_argument("--seconds", type=float, default=0.2)
    ap.add_argument("--amplitude", type=float, default=0.5)
    ap.add_argument("--coupling", default="AC", choices=("AC", "DC"),
                    help="IN1 coupling (default AC -- see the module docstring)")
    return ap.parse_args()


def capture(rp, args, coupling=None, gain="LV"):
    rp.setup_acquisition(decimation=args.decimation, coupling=coupling
                         or args.coupling, gain=gain)
    n = int(args.seconds * rp.base_rate / args.decimation)
    chans = rp.acquire_deep_fast(n_samples=n, decimation=args.decimation,
                                 channels=(1, 2), trigger="NOW")
    return chans[0], rp.base_rate / args.decimation


def step1(rp, args, res):
    """P4.1 -- level and offset with light but no RF."""
    print("Laser ON, no RF. Measuring the detector's resting output.")
    # DC first, because the pedestal is the thing being measured.
    raw, fs = capture(rp, args, coupling="DC")
    res.add("P4.1 IN1 DC-coupled", summarise(raw))
    pedestal = float(np.mean(raw))
    res.add("P4.1 DC pedestal (V)", f"{pedestal:.4f}")
    if abs(pedestal) > 0.9:
        res.add("P4.1 NOTE", "the pedestal is near or beyond the +/-1 V range. "
                             "That is expected for this detector and is exactly "
                             "why IN1 is AC coupled for the measurement.")
    ac, _ = capture(rp, args, coupling="AC")
    res.add("P4.1 IN1 AC-coupled", summarise(ac))
    span = float(np.max(np.abs(ac)))
    if span < 0.9:
        res.ok("P4.1 AC-coupled signal fits the +/-1 V range",
               f"peak |v| = {span:.4f} V")
    else:
        res.fail("P4.1 AC-coupled signal", f"peak |v| = {span:.4f} V -- close "
                                           f"to clipping even AC coupled")


def step2(rp, args, res):
    """P4.2 -- is the detector flat near the lock-in frequency? (U4)"""
    require_consent(args, "P4.2 modulation sweep",
                    f"OUT1 will drive one AOM at {args.amplitude} V while the "
                    f"modulation frequency is stepped around 991.821 kHz.")
    # Around the real lock-in frequency, and every point snapped to the ASG
    # grid: an off-grid modulation glitches at every table wrap and scatters
    # spurs across the baseband, which is exactly where the response lives.
    grid = asg_grid(PLAN.fs)
    mults = [int(round(f / grid)) for f in
             (0.25e6, 0.5e6, PLAN.difference, 2e6, 4e6)]
    for m in mults:
        f_mod = m * grid
        table = rp.setup_am_generator(carrier=PLAN.carrier, modulation=f_mod,
                                      amplitude=args.amplitude, channel=1)
        time.sleep(0.3)
        raw, fs = capture(rp, args)
        r = demodulate(raw, fs, table.modulation, output_rate=5000.0)
        amp = float(np.median(r.amplitude()))
        res.add(f"P4.2 response at {table.modulation / 1e3:.1f} kHz (V)",
                f"{amp:.6g}")
    rp.write("OUTPUT1:STATE OFF")
    res.add("P4.2 read the numbers above as a shape",
            "flat to a few percent means U4 is closed in the real path. A "
            "rolloff at ~1 MHz would mean the measurement premise needs "
            "revisiting -- that is what this step exists to find.")


def step3(rp, args, res):
    """P4.3 -- nothing clips across a full sweep."""
    print("START A WAVELENGTH SWEEP from the front panel now.")
    rp.setup_acquisition(decimation=args.decimation, coupling=args.coupling,
                         gain="LV")
    rp.setup_channel(2, gain="HV")
    n = int(1.2 * rp.base_rate / args.decimation)
    chans = rp.acquire_deep_fast(n_samples=n, decimation=args.decimation,
                                 channels=(1, 2), trigger="CH2_PE",
                                 trigger_level=1.0, trigger_timeout=90.0)
    raw = chans[0]
    res.add("P4.3 IN1 across the sweep", summarise(raw))
    # The ADC is 16-bit signed over the range; clipping shows as a hard rail
    # rather than as a smooth maximum, so count how many samples sit at it.
    peak = float(np.max(np.abs(raw)))
    at_rail = int(np.sum(np.abs(raw) >= 0.999 * peak))
    res.add("P4.3 samples within 0.1% of the peak", at_rail)
    if at_rail > raw.size * 1e-5:
        res.fail("P4.3 clipping", f"{at_rail} samples pinned at the peak -- a "
                                  f"flat top, not a waveform")
    else:
        res.ok("P4.3 no clipping across the sweep", f"peak |v| = {peak:.4f} V")


def step4(rp, args, res):
    """P4.4 -- the real noise floor. The number that decides the project."""
    print("Everything connected, laser ON, NO RF. Measuring the noise floor.")
    raw, fs = capture(rp, args)
    r = demodulate(raw, fs, PLAN.difference, output_rate=5000.0)
    # Per-quadrature sigma, which is what 3.57 uV was quoted as -- NOT mean(R),
    # which reads 1.25 sigma with no signal at all.
    sigma = float(np.std(np.concatenate([r.X, r.Y])))
    res.add("P4.4 sigma per quadrature (uV)", f"{sigma * 1e6:.3f}")
    res.add("P4.4 signal for SNR 10 (uV)", f"{10 * sigma * 1e6:.1f}")
    res.add("P4.4 against loopback", f"board alone was {BOARD_FLOOR_V * 1e6:.2f} uV; "
                                     f"detector-dominated expectation was "
                                     f"~{EXPECTED_FLOOR_V * 1e6:.0f} uV")
    if sigma < 1.5 * BOARD_FLOOR_V:
        res.fail("P4.4 floor", f"{sigma * 1e6:.2f} uV is the BOARD's own floor. "
                               f"Suspect the detector is not actually in the "
                               f"path.")
    elif sigma > 25e-6:
        res.fail("P4.4 floor", f"{sigma * 1e6:.2f} uV is well above the ~11 uV "
                               f"the datasheet implies -- something is wrong "
                               f"beyond the detector.")
    else:
        res.ok("P4.4 floor is detector-dominated, as expected",
               f"{sigma * 1e6:.2f} uV")


def main():
    args = parse()
    handler = {1: step1, 2: step2, 3: step3, 4: step4}[args.step]
    res = Results(f"P4.{args.step} -- detector in the real path")
    with session(args.host, f"P4.{args.step}") as rp:
        check_helper(rp)
        handler(rp, args, res)
    return res.finish()


if __name__ == "__main__":
    raise SystemExit(main())
