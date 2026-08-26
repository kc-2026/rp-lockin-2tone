#!/usr/bin/env python3
"""
P5 -- the full system, and the first real measurement. DRIVES OUTPUTS.

    python scripts/p5_first_measurement.py --step 1 --i-am-present
    python scripts/p5_first_measurement.py --step 2 --i-am-present
    python scripts/p5_first_measurement.py --step 3 --i-am-present --serial COM29

**P5.1 BEFORE P5.2, ALWAYS, and this script enforces it.** An amplifier-
generated product appears at exactly the frequency we are looking for and looks
entirely legitimate. Running P5.2 first and finding a signal proves nothing --
so step 2 refuses unless step 1 has been run and recorded a result.

  --step 1  P5.1  THE CONTROL. Drive ONE tone only and look at the difference
                  frequency. NOTHING SHOULD BE THERE. Whatever is, is the
                  amplifiers or crosstalk, not the DUT (U2).
  --step 2  P5.2  Both tones. Is there an intermodulation response at all --
                  the entire premise of the project (U3).
  --step 3  P5.3  A full swept trace, mapped to wavelength end to end, through
                  the same `reduce_sweep` the deliverable uses.
  --step 4  P5.4  Ground loops and 80 MHz leakage into the detector path (U9):
                  drives the carrier with the modulation OFF and looks for
                  anything at the lock-in frequency.

The verdicts are against the P4.4 noise floor, which this reads from
`--noise-floor`. Pass the sigma P4.4 actually measured; the default is the
datasheet expectation and is NOT a measurement.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

import numpy as np

sys.path.insert(0, "scripts")
from _bench import (PLAN, add_common_args, banner, check_helper,  # noqa
                    require_consent, Results, session)

sys.path.insert(0, "src")
from rp_lockin import demodulate, reduce_sweep, write_trace_csv  # noqa: E402
from rp_lockin.santec import SantecTSL  # noqa: E402

# Where step 1 leaves its verdict, so step 2 can refuse without it. A file
# rather than an honour system: the ordering is the point of the step.
CONTROL_RECORD = os.path.join("data", "p5_control.json")


def parse():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    add_common_args(ap, needs_output=True)
    ap.add_argument("--step", type=int, required=True, choices=(1, 2, 3, 4))
    ap.add_argument("--amplitude", type=float, default=0.5)
    ap.add_argument("--seconds", type=float, default=0.2)
    ap.add_argument("--noise-floor", type=float, default=11e-6,
                    help="sigma per quadrature from P4.4, volts. The default "
                         "is the DATASHEET EXPECTATION, not a measurement.")
    ap.add_argument("--serial", help="laser serial port, for step 3")
    ap.add_argument("--lan", help="laser IP, for step 3")
    ap.add_argument("--out", default="data/p5_sweep.csv")
    return ap.parse_args()


def lockin_amplitude(rp, args, seconds=None):
    """Capture IN1 and return the median amplitude at the lock-in frequency."""
    rp.setup_acquisition(decimation=args.decimation, coupling="AC", gain="LV")
    n = int((seconds or args.seconds) * rp.base_rate / args.decimation)
    chans = rp.acquire_deep_fast(n_samples=n, decimation=args.decimation,
                                 channels=(1, 2), trigger="NOW")
    fs = rp.base_rate / args.decimation
    r = demodulate(chans[0], fs, PLAN.difference, output_rate=5000.0)
    return float(np.median(r.amplitude())), r


def verdict(res, name, amp, floor, expect_signal):
    snr = amp / floor if floor > 0 else float("inf")
    res.add(f"{name} amplitude (uV)", f"{amp * 1e6:.3f}  (SNR {snr:.1f} vs a "
                                      f"{floor * 1e6:.1f} uV floor)")
    if expect_signal:
        if snr >= 10:
            res.ok(f"{name} a real response is present", f"SNR {snr:.1f}")
        elif snr >= 3:
            res.add(f"{name} marginal", f"SNR {snr:.1f} -- present but not "
                                        f"comfortably above the floor")
        else:
            res.fail(f"{name} no response above the floor", f"SNR {snr:.1f}")
    else:
        if snr < 3:
            res.ok(f"{name} control is clean, as it must be", f"SNR {snr:.1f}")
        else:
            res.fail(f"{name} SOMETHING IS THERE WITH ONE TONE",
                     f"SNR {snr:.1f}. This is the amplifiers or crosstalk, not "
                     f"the DUT. Do not proceed to P5.2 -- any 'signal' it finds "
                     f"is indistinguishable from this.")
    return snr


def step1(rp, args, res):
    """P5.1 -- the control. One tone. Nothing should be at the difference."""
    require_consent(args, "P5.1 control measurement",
                    f"OUT1 alone will drive one AOM at {args.amplitude} V. "
                    f"OUT2 stays off.")
    rp.setup_am_generator(carrier=PLAN.carrier, modulation=PLAN.f1,
                          amplitude=args.amplitude, channel=1)
    rp.write("OUTPUT2:STATE OFF")
    time.sleep(0.5)
    amp, _ = lockin_amplitude(rp, args)
    snr = verdict(res, "P5.1", amp, args.noise_floor, expect_signal=False)
    os.makedirs(os.path.dirname(CONTROL_RECORD) or ".", exist_ok=True)
    with open(CONTROL_RECORD, "w", encoding="utf-8") as fh:
        json.dump({"amplitude_V": amp, "snr": snr,
                   "floor_V": args.noise_floor,
                   "when": time.strftime("%Y-%m-%d %H:%M:%S")}, fh, indent=2)
    res.add("P5.1 recorded to", CONTROL_RECORD)


def step2(rp, args, res):
    """P5.2 -- both tones. The premise."""
    if not os.path.exists(CONTROL_RECORD):
        raise SystemExit(
            f"refusing: P5.1 has not been run.\n"
            f"An amplifier-generated product sits at exactly the frequency "
            f"this step looks at and looks entirely legitimate, so a signal "
            f"found here means nothing until the one-tone control is clean.\n"
            f"  python scripts/p5_first_measurement.py --step 1 --i-am-present")
    with open(CONTROL_RECORD, encoding="utf-8") as fh:
        control = json.load(fh)
    res.add("P5.2 control from P5.1", f"{control['amplitude_V'] * 1e6:.3f} uV "
                                      f"(SNR {control['snr']:.1f}), recorded "
                                      f"{control['when']}")
    if control["snr"] >= 3:
        raise SystemExit(
            f"refusing: the P5.1 control was NOT clean (SNR "
            f"{control['snr']:.1f}). Whatever this step measures would be "
            f"indistinguishable from it. Fix the control first.")

    require_consent(args, "P5.2 both tones",
                    f"OUT1 and OUT2 will both drive, at {args.amplitude} V.")
    rp.setup_am_generator(carrier=PLAN.carrier, modulation=PLAN.f1,
                          amplitude=args.amplitude, channel=1)
    rp.setup_am_generator(carrier=PLAN.carrier, modulation=PLAN.f2,
                          amplitude=args.amplitude, channel=2)
    time.sleep(0.5)
    amp, _ = lockin_amplitude(rp, args)
    verdict(res, "P5.2", amp, args.noise_floor, expect_signal=True)
    res.add("P5.2 against the control",
            f"{amp / max(control['amplitude_V'], 1e-12):.1f}x the one-tone "
            f"level. A ratio near 1 means this is not a DUT response.")


def step3(rp, args, res):
    """P5.3 -- a full swept trace, mapped end to end."""
    if not (args.serial or args.lan):
        raise SystemExit("step 3 needs the laser: give --serial or --lan")
    laser = (SantecTSL.over_lan(args.lan) if args.lan
             else SantecTSL.over_serial(args.serial))
    try:
        require_consent(args, "P5.3 full swept trace",
                        f"Both outputs drive at {args.amplitude} V while you "
                        f"run a wavelength sweep from the front panel.")
        rp.setup_am_generator(carrier=PLAN.carrier, modulation=PLAN.f1,
                              amplitude=args.amplitude, channel=1)
        rp.setup_am_generator(carrier=PLAN.carrier, modulation=PLAN.f2,
                              amplitude=args.amplitude, channel=2)
        rp.setup_acquisition(decimation=args.decimation, coupling="AC",
                             gain="LV")
        rp.setup_channel(2, gain="HV")

        print("\nSTART THE WAVELENGTH SWEEP NOW from the front panel.")
        n = int(1.2 * rp.base_rate / args.decimation)
        det, trig = rp.acquire_deep_fast(
            n_samples=n, decimation=args.decimation, channels=(1, 2),
            trigger="CH2_PE", trigger_level=1.0, trigger_timeout=120.0)
        rp.write("OUTPUT1:STATE OFF")
        rp.write("OUTPUT2:STATE OFF")

        wl = laser.read_wavelengths()
        red = reduce_sweep(det, trig, rp.base_rate / args.decimation, wl,
                           f_ref=PLAN.difference)
        for line in red.describe().splitlines():
            res.add("P5.3", line)
        rows = write_trace_csv(args.out, red.trace.wavelength,
                               red.trace.amplitude, metadata=red.metadata())
        res.ok("P5.3 wrote the trace", f"{rows} rows to {args.out}")
        if not red.alignment.ok:
            res.fail("P5.3 alignment", red.alignment.diagnosis)
    finally:
        laser.close()


def step4(rp, args, res):
    """P5.4 -- 80 MHz leakage and ground loops (U9)."""
    require_consent(args, "P5.4 leakage check",
                    f"OUT1 drives an UNMODULATED carrier at {args.amplitude} V. "
                    f"With no modulation there should be nothing at the "
                    f"difference frequency at all.")
    rp.setup_generator(PLAN.carrier, amplitude=args.amplitude, channel=1)
    time.sleep(0.5)
    amp_on, _ = lockin_amplitude(rp, args)
    rp.write("OUTPUT1:STATE OFF")
    time.sleep(0.5)
    amp_off, _ = lockin_amplitude(rp, args)
    res.add("P5.4 lock-in amplitude, carrier ON (uV)", f"{amp_on * 1e6:.3f}")
    res.add("P5.4 lock-in amplitude, carrier OFF (uV)", f"{amp_off * 1e6:.3f}")
    excess = amp_on - amp_off
    if abs(excess) < 2 * args.noise_floor:
        res.ok("P5.4 no detectable leakage into the detector path",
               f"difference {excess * 1e6:+.3f} uV")
    else:
        res.fail("P5.4 leakage", f"{excess * 1e6:+.3f} uV appears at the "
                                 f"lock-in frequency with the carrier alone "
                                 f"and NO modulation. That is a ground loop or "
                                 f"80 MHz coupling, and it will add to every "
                                 f"real measurement.")


def main():
    args = parse()
    handler = {1: step1, 2: step2, 3: step3, 4: step4}[args.step]
    res = Results(f"P5.{args.step} -- full system")
    if args.noise_floor == 11e-6:
        print("NOTE: --noise-floor is the datasheet expectation, not a "
              "measurement. Pass the sigma P4.4 actually measured.")
    with session(args.host, f"P5.{args.step}") as rp:
        check_helper(rp)
        handler(rp, args, res)
    return res.finish()


if __name__ == "__main__":
    raise SystemExit(main())
