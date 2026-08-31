#!/usr/bin/env python3
"""
P4L -- the LINEAR sweep: one AOM, no crystal, no DUT, demodulate AT f1.

The whole chain end to end with nothing exotic in it:

    OUT1 --AM at f1--> amplifier --> AOM --> light --> detector --> IN1
    laser trigger --------------------------------------------> IN2

Every component is exercised and the expected answer is boring and readable:
amplitude against wavelength, which is the AOM's diffraction efficiency times
the detector's responsivity across the band. Smooth. A resonance would be a
surprise, and that is what makes it a good test -- there is nothing here to
mistake for a result.

    python scripts/p4_linear_sweep.py --i-am-present
    python scripts/p4_linear_sweep.py --i-am-present --blocked    # the control

WHY f1 AND NOT 2*f1. There is no crystal, so nothing squares the light. The
photodiode is linear in optical power, so light modulated at f1 gives a
photocurrent at f1. Demodulating there is the LINEAR measurement, and it is the
one that proves the plumbing.

WHAT IT CLOSES

  * Q11b -- whether the photodetector responds to light at all. Everything
    measured before this ran with the shutter closed, where a working detector
    and a disconnected one are indistinguishable.
  * The first RF this board has ever sent into an amplifier.
  * The first time the wavelength axis carries a real optical signal.

THE CONTROL RUN IS NOT OPTIONAL. --blocked expects the beam blocked (or the
shutter closed) and everything else identical. The amplifier is radiating a
heavily amplitude-modulated 80 MHz a short distance from the detector cable, so
a peak at f1 can be electrical pickup rather than light. A signal here proves
nothing until the blocked run is clean -- the same reasoning that makes P5.2
refuse to run before P5.1.

CHOICE OF f1. 915.527 kHz, 60 grid steps. Whole cycles in the 16384-entry ASG
table, so the buffer wraps without a glitch, and 94 kHz clear of the switching
supply's 504.868 kHz harmonic family -- better separation than the two-tone
plan's own 991.821 kHz, which sits 17.9 kHz off it. Do NOT move this to
1007.080 kHz: that is 2.7 kHz from a switcher harmonic, where interference
reads as a strong, clean, steady optical signal.

FRONT END. IN1 on LV and AC-coupled: the detector is 0-10 V unipolar into
Hi-Z and its DC level would otherwise sit the input against the rail, while
AC coupling costs nothing at these frequencies (Q25: 17 Hz corner). IN2 stays
on HV for the 3.3 V trigger. Aim for a few hundred mV of AC swing -- roughly
50-100 uW at the detector, which is also well inside its 0.96 mW saturation.
"""
from __future__ import annotations

import argparse
import os
import sys
import threading
import time

import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from _bench import (add_common_args, check_helper, require_consent,  # noqa: E402
                    Results, session)
from rp_lockin.pipeline import reduce_sweep                   # noqa: E402
from rp_lockin.constants import (ADC_COUNTS_PER_V_LV,        # noqa: E402
                                 ADC_COUNT_MAX, ADC_COUNT_MIN)
from rp_lockin.planning import recommended_tail, settling_points  # noqa: E402
from rp_lockin.output import write_trace_csv, write_raw_npz   # noqa: E402
from tsl775 import TSL775                                     # noqa: E402

GRID = 250e6 / 16384
F1 = 60 * GRID                    # 915.527 kHz -- see the docstring
CARRIER = 80e6                    # snapped to 80.001831 MHz by make_am_table
START_NM, STOP_NM = 1500.0, 1600.0
SPEED_NM_S, TRIG_STEP_NM = 100.0, 0.02
EXPECTED_POINTS = int(round((STOP_NM - START_NM) / TRIG_STEP_NM)) + 1
SWEEP_SECONDS = (EXPECTED_POINTS - 1) * (TRIG_STEP_NM / SPEED_NM_S)
DECIMATION = 8
OUTPUT_RATE = 5000.0


def parse():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    add_common_args(ap, needs_output=True)
    ap.add_argument("--laser-ip", default="10.101.0.197")
    ap.add_argument("--out", default="data/linear",
                    help="output basename; data/ is gitignored")
    ap.add_argument("--amplitude", type=float, default=1.0,
                    help="OUT1 drive amplitude, V. Default 1.0 = full scale, "
                         "which is where Kevin tuned the AOM. Q12 settled that "
                         "no attenuator is wanted; do not add one here.")
    ap.add_argument("--max-dbm", type=float, default=0.0,
                    help="refuse to emit above this laser setpoint (0 dBm = "
                         "1 mW). The detector sees the FUNDAMENTAL here and "
                         "saturates near 0.96 mW.")
    ap.add_argument("--blocked", action="store_true",
                    help="THE CONTROL RUN. Beam blocked, everything else the "
                         "same. Whatever appears at f1 in this run is "
                         "electrical pickup, and is the floor the real run "
                         "has to beat.")
    ap.add_argument("--arm-delay", type=float, default=3.0)
    return ap.parse_args()


def configure_laser(d, args):
    print(f"laser: {d.query('*IDN?')}")
    level = float(d.query(":POWer:LEVel?"))
    print(f"setpoint {level:.2f} dBm ({10 ** (level / 10):.3f} mW), "
          f"shutter {d.query(':POW:SHUT?').strip()}")
    if level > args.max_dbm:
        raise SystemExit(
            f"REFUSING: {level:.2f} dBm is above the {args.max_dbm:.2f} dBm "
            f"limit and the detector sees the fundamental in this test.")

    before = {k: d.query(q) for k, q in (
        ("start", ":WAV:SWE:STAR?"), ("stop", ":WAV:SWE:STOP?"),
        ("speed", ":WAV:SWE:SPE?"), ("cycles", ":WAV:SWE:CYCL?"),
        ("mode", ":WAV:SWE:MOD?"), ("trig", ":TRIG:OUTP?"),
        ("trigstep", ":TRIG:OUTP:STEP?"))}

    d.write(":POW:STAT 1"); time.sleep(2.0)      # laser ON before configuring
    d.write(":WAV:SWE 0"); time.sleep(0.5)       # explicit stop, or it never starts
    d.write(f":WAV:SWE:SPE {SPEED_NM_S}")        # speed first: the range depends on it
    d.write(f":WAV:SWE:STAR {START_NM * 1e-9:.9E}")   # METRES
    d.write(f":WAV:SWE:STOP {STOP_NM * 1e-9:.9E}")
    d.write(":WAV:SWE:MOD 1")                    # continuous, ONE WAY
    d.write(":WAV:SWE:CYCL 1")
    d.write(":TRIG:OUTP 3")                      # Step -- mandatory, or no log
    d.write(f":TRIG:OUTP:STEP {TRIG_STEP_NM * 1e-9:.9E}")
    if d.query(":TRIG:OUTP?").strip().lstrip("+") != "3":
        raise SystemExit(":TRIG:OUTP is not 3; no trigger train and no log")
    return before


def restore_laser(d, before):
    for cmd, key in ((":WAV:SWE:STAR", "start"), (":WAV:SWE:STOP", "stop"),
                     (":WAV:SWE:SPE", "speed"), (":WAV:SWE:CYCL", "cycles"),
                     (":WAV:SWE:MOD", "mode"), (":TRIG:OUTP", "trig"),
                     (":TRIG:OUTP:STEP", "trigstep")):
        try:
            d.write(f"{cmd} {before[key].strip()}")
        except Exception:                                    # noqa: BLE001
            pass


def main():
    args = parse()
    res = Results("P4L -- linear sweep, demodulated at f1")

    require_consent(
        args, "drive OUT1 into the amplifier and the AOM",
        f"OUT1: {CARRIER / 1e6:.3f} MHz carrier, AM at {F1 / 1e3:.3f} kHz, "
        f"depth 1, {args.amplitude:.2f} V. This reaches a ZHL-1-2W+ and an "
        f"AOM, and light goes somewhere."
        + ("  [BLOCKED CONTROL RUN]" if args.blocked else ""))

    fs = 250e6 / DECIMATION
    n_settle, t_settle = settling_points(OUTPUT_RATE, fs=fs)
    tail = recommended_tail(OUTPUT_RATE, fs=fs)
    preroll = int((t_settle * 1.1) * fs)
    n_samples = int(np.ceil((preroll / fs + SWEEP_SECONDS + tail) * fs))
    n_samples = min(n_samples, 33554432)
    print(f"f1 {F1:.3f} Hz | fs {fs / 1e6:.4f} MS/s | record {n_samples / fs:.4f} s"
          f" | pre-roll {preroll / fs * 1e3:.2f} ms")

    captured = {}

    def capture(rp):
        try:
            ch = rp.acquire_deep_fast(
                n_samples=n_samples, decimation=DECIMATION, channels=(1, 2),
                trigger="CH2_PE", trigger_level=1.0,
                preroll_samples=preroll, trigger_timeout=120.0)
            captured["det"], captured["trg"] = ch[0], ch[1]
        except Exception as e:                               # noqa: BLE001
            captured["error"] = e

    d = TSL775.connect("lan", host=args.laser_ip, timeout=5.0)
    before = None
    try:
        before = configure_laser(d, args)
        with session(args.host, "P4L -- linear sweep through the AOM") as rp:
            check_helper(rp)
            rp.setup_acquisition(decimation=DECIMATION, coupling="DC", gain="LV")
            rp.setup_channel(1, coupling="AC", gain="LV")   # detector is unipolar
            rp.setup_channel(2, gain="HV")                  # 3.3 V trigger

            table = rp.setup_am_generator(carrier=CARRIER, modulation=F1,
                                          amplitude=args.amplitude, depth=1.0,
                                          channel=1)
            print(f"drive: {table.describe()}")
            res.add("P4L.0 drive", f"{table.carrier / 1e6:.6f} MHz carrier, "
                                   f"AM {table.modulation / 1e3:.4f} kHz")

            t = threading.Thread(target=capture, args=(rp,), daemon=True)
            t.start()
            time.sleep(args.arm_delay)
            print(">>> starting sweep")
            d.write(":WAV:SWE 1")
            t0 = time.time()
            while time.time() - t0 < 30.0:
                if (d.query(":WAV:SWE?").strip().lstrip("+") == "0"
                        and time.time() - t0 > 2):
                    break
                time.sleep(0.1)
            print(f">>> sweep done in {time.time() - t0:.2f} s")

            t.join(timeout=180.0)
            if "error" in captured:
                raise captured["error"]
            wl = np.asarray(d.query_wavelength_log(scpi=True), dtype=float)
            print(f">>> laser log: {wl.size} points, "
                  f"{wl[0] * 1e9:.4f} -> {wl[-1] * 1e9:.4f} nm")
    finally:
        try:
            d.write(":WAV:SWE 0"); d.write(":POW:STAT 0")
            if before:
                restore_laser(d, before)
        except Exception:                                    # noqa: BLE001
            pass
        d.close()
        # session() disarms both outputs on every exit path, including this one.

    det_counts = np.asarray(captured["det"], dtype=float)
    trg = np.asarray(captured["trg"], dtype=float)
    # Clipping is judged in COUNTS -- the rail belongs to the converter. Then
    # scale to VOLTS, so amplitude, the plot and the CSV are all in volts
    # rather than raw counts, which mean nothing outside this program.
    det = det_counts / ADC_COUNTS_PER_V_LV

    lo, hi = np.percentile(trg, 1), np.percentile(trg, 99)
    if hi - lo < 50:
        raise SystemExit(f"IN2 swing is {hi - lo:.1f} counts -- nothing on the "
                         f"trigger channel. Is the BNC in analog IN2?")
    thr = float(0.5 * (lo + hi))

    dlo, dhi = np.percentile(det_counts, 1), np.percentile(det_counts, 99)
    res.add("P4L.1 IN1 swing", f"{(dhi - dlo) / ADC_COUNTS_PER_V_LV * 1e3:.2f} "
                               f"mV ({dhi - dlo:.0f} counts)")
    clipped = int(np.count_nonzero((det_counts >= ADC_COUNT_MAX)
                                   | (det_counts <= ADC_COUNT_MIN)))
    if clipped:
        res.fail("P4L.1 IN1 clipping", f"{clipped} samples at the rail -- "
                                       f"reduce the laser power")
    else:
        res.ok("P4L.1 IN1 inside range", f"0 clipped of {det.size}")

    red = reduce_sweep(det, trg, fs, wl, f_ref=F1, output_rate=OUTPUT_RATE,
                       trigger_threshold=thr, trigger_polarity="rising",
                       nominal_step=TRIG_STEP_NM / SPEED_NM_S)
    w, a = red.trace.dropna()
    res.add("P4L.2 points with a wavelength", w.size)
    res.add("P4L.2 amplitude median", f"{np.median(a) * 1e6:.3f} uV")
    res.add("P4L.2 amplitude min/max", f"{a.min() * 1e6:.3f} / {a.max() * 1e6:.3f} uV")
    res.add("P4L.3 wavelength axis from", red.table_source)
    print("\n" + red.describe())

    tag = "blocked" if args.blocked else "beam"
    write_trace_csv(f"{args.out}_{tag}.csv", red.trace.wavelength,
                    red.trace.amplitude, metadata=red.metadata())
    write_raw_npz(f"{args.out}_{tag}.npz", detector=det_counts, trigger=trg,
                  wavelengths=wl, edges=red.edges)
    print(f"wrote {args.out}_{tag}.csv / .npz")

    if args.blocked:
        res.add("P4L.4 CONTROL", "beam blocked: this amplitude is the "
                                 "electrical pickup floor, not a measurement")
    else:
        res.add("P4L.4 compare against the --blocked run",
                "a real optical signal must stand well clear of it")
    return res.finish()


if __name__ == "__main__":
    raise SystemExit(main())
