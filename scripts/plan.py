#!/usr/bin/env python3
"""Print the frequency and capture plan. No hardware needed."""
import argparse
import sys

from rp_lockin import describe_capture_plan, plan_two_tone, settling_points


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--difference", type=float, default=1e6, help="|f2-f1|, Hz")
    p.add_argument("--f1", type=float, default=5e6)
    p.add_argument("--carrier", type=float, default=80e6)
    p.add_argument("--sweep", type=float, default=1.0, help="sweep length, s")
    p.add_argument("--points", type=int, default=5000)
    a = p.parse_args()

    plan = plan_two_tone(a.difference, a.f1, a.carrier)
    print("=== Drive plan ===")
    print(plan.describe())

    out_rate = a.points / a.sweep
    pts, secs = settling_points(out_rate)
    print(f"\ncycles per integration time: "
          f"{plan.periods_per_tau(1 / (2 * 3.14159 * 0.9 * out_rate / 2)):.0f}")
    print(f"settling cost: {pts} points ({secs * 1e3:.1f} ms) "
          f"-- pre-roll at least {2 * secs * 1e3:.0f} ms before the trigger")

    print("\n=== Capture plan ===")
    print(describe_capture_plan(a.sweep, plan.difference, a.points))
    return 0


if __name__ == "__main__":
    sys.exit(main())
