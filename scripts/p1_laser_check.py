"""
P1 -- first contact with the Santec laser. READ-ONLY by default.

Runs with **no RF, no optics, and the Red Pitaya switched off**. Nothing here can
damage anything: it identifies the laser, reads back how its trigger output is
configured, and reads whatever wavelength log is already in memory.

    python scripts/p1_laser_check.py --serial COM29
    python scripts/p1_laser_check.py --serial COM29 --baud 115200
    python scripts/p1_laser_check.py --lan 192.168.1.50

It does NOT start a sweep and does NOT change any laser setting unless you pass
`--set-trigger-step`, which is the one action that writes. A log can only be read
after a sweep has happened, so run one from the front panel first if the point
count comes back zero.

What this settles, none of which any manual answers:

  Q26  Does the laser log exactly ONE wavelength per trigger pulse? Neither
       manual says so, and the whole index-based mapping depends on it. This
       reads the count; comparing it against pulses in a Red Pitaya capture is
       the other half, and needs P2.
  Q24  Which way round is `:TRIGger:OUTPut:SETTing`? The TSL-775 manual says
       0=wavelength/1=time and the TSL-770 says the reverse, so the value is
       reported RAW and never interpreted.
  --   Which command set the laser is in, inferred from the log's byte count
       rather than assumed: 4 bytes/point means legacy integers in 0.1 pm,
       8 means IEEE doubles in metres.
  --   Whether `santec.py` works at all. It was written entirely from the
       manuals and has never spoken to an instrument.
  --   On serial, the baud rate -- which the manual never states. Omit --baud
       and the standard rates are probed until one answers sensibly.
"""

from __future__ import annotations

import argparse
import sys

import numpy as np

sys.path.insert(0, "src")

from rp_lockin.santec import (  # noqa: E402
    COMMON_BAUD_RATES,
    TRIGGER_OUTPUT_MODES,
    SantecTSL,
)


def open_laser(args):
    """
    Connect, probing the baud rate if we are on serial and none was given.

    The manual documents the delimiter and the throughput for USB but **never a
    baud rate**, so guessing one and baking it in would be exactly the kind of
    silent-wrong-setting this project keeps tripping over. Probing is cheap and
    answers it: a wrong rate returns nothing, or bytes that are not ASCII, and
    `*IDN?` is a read that cannot disturb the instrument.
    """
    if args.lan:
        print(f"connecting over LAN to {args.lan}:{args.port} ...")
        return SantecTSL.over_lan(args.lan, args.port, timeout=args.timeout)

    rates = [args.baud] if args.baud else list(COMMON_BAUD_RATES)
    if len(rates) > 1:
        print(f"connecting over serial to {args.serial}, probing baud "
              f"{', '.join(str(r) for r in rates)} ...")
        print("  (the manual states no baud rate for USB, so this finds it)")
    for rate in rates:
        laser = None
        try:
            laser = SantecTSL.over_serial(args.serial, rate, timeout=1.5)
            idn = laser.idn()
            if idn and idn.isprintable() and len(idn) > 3:
                print(f"  {rate:>7} baud -> {idn}")
                print(f"\n*** baud rate is {rate}. Pass --baud {rate} to skip "
                      f"the probe next time. ***")
                return laser
            print(f"  {rate:>7} baud -> unusable reply {idn!r}")
        except Exception as exc:
            print(f"  {rate:>7} baud -> {type(exc).__name__}")
        if laser is not None:
            laser.close()
    raise ConnectionError(
        f"no baud rate in {rates} produced a sensible *IDN?. Check the laser is "
        f"powered and that {args.serial} is the right port -- Device Manager "
        f"shows it under Ports (COM & LPT) once the VCP driver is bound."
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--serial", metavar="PORT",
                     help="serial port, e.g. COM29 (USB via the FTDI VCP driver)")
    src.add_argument("--lan", metavar="HOST",
                     help="IP address or hostname, for the LAN port")
    ap.add_argument("--baud", type=int, default=None,
                    help="serial baud rate. Omitted, the standard rates are "
                         "probed -- the manual does not state one.")
    ap.add_argument("--port", type=int, default=5000, help="LAN port")
    ap.add_argument("--timeout", type=float, default=10.0)
    ap.add_argument(
        "--set-trigger-step", action="store_true",
        help="THE ONLY WRITE. Sets :TRIGger:OUTPut to 3 (Step) and reads it "
             "back. Step is what this project needs -- Start emits one pulse, "
             "leaving no train to measure the clocks against and no count to "
             "check the log against.")
    args = ap.parse_args()

    try:
        laser = open_laser(args)
    except Exception as exc:
        print(f"\n  FAILED: {type(exc).__name__}: {exc}")
        return 1
    print(f"connected: {laser.description}")

    ok = True
    try:
        # ---- identity ---------------------------------------------------
        print("\n=== identity ===")
        try:
            idn = laser.idn()
            print(f"  *IDN? -> {idn}")
            if "770" not in idn and "775" not in idn:
                print("  NOTE: the model string does not mention 770 or 775. "
                      "Everything below assumes that command set.")
        except Exception as exc:
            print(f"  *IDN? FAILED: {type(exc).__name__}: {exc}")
            return 1

        # ---- trigger configuration --------------------------------------
        print("\n=== trigger output (read-only) ===")
        try:
            cfg = laser.trigger_config()
            print("  " + cfg.describe().replace("\n", "\n  "))
            if cfg.mode != 3:
                print(f"\n  *** mode is {cfg.mode} ({cfg.mode_name}), not 3 "
                      f"(step). ***")
                print("  Step is what this project needs. Pass "
                      "--set-trigger-step to change it,")
                print("  or set it from the front panel.")
                ok = False
        except Exception as exc:
            print(f"  FAILED: {type(exc).__name__}: {exc}")
            ok = False

        if args.set_trigger_step:
            print("\n=== setting trigger output to Step (the only write) ===")
            try:
                got = laser.set_trigger_output(3)
                print(f"  set and read back: {got} "
                      f"({TRIGGER_OUTPUT_MODES[got]})")
            except Exception as exc:
                print(f"  FAILED: {type(exc).__name__}: {exc}")
                ok = False

        # ---- the wavelength log -----------------------------------------
        print("\n=== wavelength log ===")
        try:
            n = laser.logged_points()
            print(f"  :READout:POINts? -> {n}")
        except Exception as exc:
            print(f"  FAILED: {type(exc).__name__}: {exc}")
            return 1

        if n == 0:
            print("\n  The log is empty, which is expected if no sweep has run "
                  "since power-on.")
            print("  Run one sweep from the front panel and re-run this script.")
            print("  Everything above is still valid.")
            return 0 if ok else 2

        try:
            wl = laser.read_wavelengths(n)
        except Exception as exc:
            print(f"  reading the log FAILED: {type(exc).__name__}: {exc}")
            return 1

        print(f"  read {wl.size} wavelengths")
        print(f"  range      {wl.min()*1e9:.4f} to {wl.max()*1e9:.4f} nm")
        d = np.diff(wl)
        print(f"  step       mean {d.mean()*1e12:.4f} pm, "
              f"sd {d.std()*1e12:.4f} pm")
        mono = bool(np.all(d > 0) or np.all(d < 0))
        print(f"  monotonic  {mono}")

        # Sanity: are these plausible wavelengths at all? A wrong format
        # decode is off by ~10^7 and would be obvious here rather than later.
        if not (1.0e-6 < wl.mean() < 2.0e-6):
            print(f"\n  *** {wl.mean()*1e9:.1f} nm is not a plausible telecom "
                  f"wavelength. ***")
            print("  Suspect the payload format was misread. The driver infers "
                  "4-byte legacy\n  integers (0.1 pm) vs 8-byte doubles "
                  "(metres) from the byte count; if the\n  point count and the "
                  "payload disagree, that inference is wrong.")
            ok = False
        if not mono:
            print("\n  NOTE: a sweep should give a monotonic wavelength list. "
                  "Non-monotonic\n  suggests a repeat scan, or a log left over "
                  "from something else.")

        # ---- Q26, the half of it that can be answered here ---------------
        print("\n=== Q26: is the log one point per trigger pulse? ===")
        print(f"  the laser reports {n} logged points.")
        print("  UNANSWERED here, and no manual states it. The other half needs")
        print("  a Red Pitaya capture of the trigger train: count its pulses "
              "and compare.")
        print("  `wavelength.check_alignment(edges, table_t)` does exactly that "
              "-- P2.3.")
        if cfg.step_m:
            print(f"\n  For reference, the trigger step reads {cfg.step_m:g} "
                  f"(metres if periodic in")
            print("  wavelength, seconds if periodic in time -- Q24 says the "
                  "manuals disagree on")
            print("  which encoding means which, so this is deliberately not "
                  "interpreted).")
    finally:
        laser.close()
        print("\nconnection closed. Nothing was swept; no optics or RF "
              "involved.")

    print("\n--- P1 verdict ---")
    print("PASS" if ok else "NEEDS ATTENTION -- see the notes above")
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
