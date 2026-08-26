#!/usr/bin/env python3
"""
P3 -- the drive chain, AOMs DISCONNECTED. THIS DRIVES PHYSICAL OUTPUTS.

Everything electrical, measured before anything optical exists.

    python scripts/p3_drive_chain.py --i-am-present --step 1

**This is the first step that can damage something and the first that needs you
in the room.** It refuses to run without --i-am-present and a typed
confirmation, and it disarms both outputs on every exit path.

BEFORE YOU RUN IT
-----------------
* **Connect the AOM (or a 50 ohm load) BEFORE applying RF.** The ZHL-1-2W+
  datasheet warns an open load can damage it and derates the maximum input by
  20 dB with no load. An amplifier driving an open circuit is the one way this
  step destroys hardware.
* **Do not add attenuators and do not retune the drive.** The amplifier sees
  about -4 dBm against a +10 dBm rating -- 14 dB of margin -- and the board's
  14 dB rolloff at 80 MHz means it cannot get closer. Three separate attenuator
  recommendations were made on this project and all three were withdrawn. See
  docs/04-hardware-reference.md.
* Steps are run ONE AT A TIME with --step, so nothing is energised as a side
  effect of something else.

WHAT EACH STEP DOES

  --step 1   P3.1  Board output at the amplifier INPUT, on a 50 ohm load.
                   Expect ~-4 dBm. Confirms on 50 ohm what was measured on a
                   1 MHz scope: 800 mVpp open-circuit halves into 50 ohm. An RF
                   voltage without its impedance is not a measurement.
  --step 2   P3.2  Amplifier OUTPUT level, before the AOMs are connected.
                   Measured on your instrument; this step only drives and tells
                   you what it is driving.
  --step 3   P3.3  Absolute 80 MHz drive amplitude at the AOM input (U1).
  --step 4   P3.4  One amplifier at a time, for its spectrum. Catches gross
                   nonlinearity early.
  --step 5   P3.5  BOTH channels together, looking for crosstalk -- the
                   mechanism that could fake a difference-frequency signal.

Steps 2, 3 and 4 are measured on YOUR instrument (power meter, scope, spectrum
analyser). The script energises the right thing, tells you exactly what is on
which connector, waits, and disarms. It deliberately does not pretend to measure
what it cannot reach.
"""
from __future__ import annotations

import argparse
import sys
import time

sys.path.insert(0, "scripts")
from _bench import (PLAN, add_common_args, banner, require_consent,  # noqa
                    Results, session)


def parse():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    add_common_args(ap, needs_output=True)
    ap.add_argument("--step", type=int, required=True, choices=(1, 2, 3, 4, 5),
                    help="which P3 sub-step to run. One at a time, deliberately.")
    ap.add_argument("--amplitude", type=float, default=0.5,
                    help="board output amplitude in volts (default 0.5). This "
                         "is the board's setting, NOT a retune of the drive.")
    ap.add_argument("--hold", type=float, default=30.0,
                    help="seconds to hold the output on while you measure")
    ap.add_argument("--carrier-only", action="store_true",
                    help="unmodulated carrier, as used for the CW tuning")
    return ap.parse_args()


STEPS = {
    1: ("P3.1 board output at the amplifier input",
        "Put a 50 ohm load (or the amplifier input) on OUT1 and measure there.\n"
        "Expect about -4 dBm / 400 mVpp into 50 ohm -- half the 800 mVpp the\n"
        "board shows open-circuit. The amplifier's absolute maximum input is\n"
        "+10 dBm, so this should show ~14 dB of margin."),
    2: ("P3.2 amplifier output, AOMs still disconnected",
        "Measure at the AMPLIFIER OUTPUT, into a 50 ohm load rated for it.\n"
        "Confirm the level is inside the AOM's rating BEFORE connecting one.\n"
        "The 1550AOM-1 takes 2.5 W nominal at 80 MHz."),
    3: ("P3.3 absolute 80 MHz drive at the AOM input (U1)",
        "Same connection as P3.2, recorded as the absolute figure U1 asks for."),
    4: ("P3.4 one amplifier alone, for its spectrum",
        "Spectrum analyser on the amplifier output. Looking for gross\n"
        "nonlinearity: harmonics of 80 MHz, and any product near 991.821 kHz."),
    5: ("P3.5 BOTH channels, looking for crosstalk",
        "Both amplifiers driven. Measure each output with the other running.\n"
        "Crosstalk between the arms is the mechanism that could produce a\n"
        "difference-frequency signal with no DUT in the path at all -- which\n"
        "is exactly what P5.1 later tries to rule out."),
}


def drive(rp, channel, args, res):
    mod = PLAN.f1 if channel == 1 else PLAN.f2
    if args.carrier_only:
        rp.setup_generator(PLAN.carrier, amplitude=args.amplitude,
                           channel=channel)
        res.add(f"OUT{channel} driving",
                f"unmodulated carrier {PLAN.carrier / 1e6:.6f} MHz at "
                f"{args.amplitude} V")
    else:
        table = rp.setup_am_generator(carrier=PLAN.carrier, modulation=mod,
                                      amplitude=args.amplitude,
                                      channel=channel)
        res.add(f"OUT{channel} driving",
                f"carrier {table.carrier / 1e6:.6f} MHz, AM at "
                f"{table.modulation / 1e6:.6f} MHz, depth 1, "
                f"{args.amplitude} V")


def main():
    args = parse()
    title, guidance = STEPS[args.step]
    res = Results(f"P3 -- drive chain ({title})")

    banner(title)
    print(guidance)
    print()
    print("CHECK BEFORE PROCEEDING:")
    print("  * the amplifier has a LOAD on its output (AOM or 50 ohm dummy).")
    print("    An open load can damage it -- ZHL-1-2W+ datasheet.")
    print("  * no optics are connected. P3 is the electrical step.")
    print("  * you are not adding attenuators. The drive level is correct.")

    channels = (1, 2) if args.step == 5 else (1,)
    require_consent(
        args, title,
        f"OUT{' and OUT'.join(str(c) for c in channels)} will be energised for "
        f"{args.hold:.0f} s at {args.amplitude} V.")

    with session(args.host, title) as rp:
        for ch in channels:
            drive(rp, ch, args, res)
        res.add("held for", f"{args.hold:.0f} s -- measure now")
        try:
            time.sleep(args.hold)
        except KeyboardInterrupt:
            print("\ninterrupted -- disarming.")
        # session() disarms in its finally; this is belt and braces so the
        # output is off before the operator reads the summary rather than after.
        for ch in channels:
            rp.write(f"OUTPUT{ch}:STATE OFF")
        res.ok("outputs off after the hold", "OUTPUT:STATE OFF sent")

    print()
    print("Record what your instrument showed against these checks:")
    for line in guidance.splitlines():
        print(f"  {line}")
    return res.finish()


if __name__ == "__main__":
    raise SystemExit(main())
