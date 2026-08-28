#!/usr/bin/env python3
"""
THE FULL SWEEP TEST -- one laser sweep, end to end, to a wavelength CSV.

This is `pipeline.reduce_sweep`'s first run against real hardware. It captures
IN1 (detector) and IN2 (laser trigger) in ONE acquisition, runs a real sweep on
the TSL-775, reads the laser's own wavelength log, and reduces the lot to
amplitude against wavelength.

    python scripts/full_sweep_test.py --laser-ip 10.101.0.197

WHAT IT DOES NOT PROVE. With no RF drive there are no AOMs, no DUT and no
intermodulation, so the trace is the noise floor mapped onto a wavelength axis.
That is the point: it exercises the whole deliverable path -- trigger, log,
alignment, demodulation, axis, CSV -- while the only thing that can be wrong is
plumbing. A signal would hide plumbing errors, not reveal them.

SAFETY. The script enables emission, because a sweep cannot run without it.

  * It REFUSES if the shutter is open, unless --shutter-open-ok. The
    photodetector is connected, it saturates around 0.96 mW, and its DAMAGE
    threshold is unknown (still outstanding from Kevin). With the shutter shut
    the trigger train and the wavelength log both work perfectly -- verified
    2026-08-28 -- so the entire electrical path can be tested with no light.
  * It restores every laser setting it changed and turns emission off in a
    finally block, as sweep_capture.py does.
  * It drives NO board output. There is no RF anywhere in this script.

TWO TRAPS THIS SCRIPT EXISTS TO AVOID, both silent:

  * `reduce_sweep(trigger_threshold=...)` DEFAULTS TO 0.0, which is right for a
    bipolar trigger and wrong for ours. IN2 idles near 6 counts and peaks near
    302, so it never crosses zero: the default finds NO edges. The threshold is
    computed from the record here, never assumed.
  * The capture must PRE-ROLL before the trigger and leave a TAIL after the
    sweep, or the first ~113 output points are filter settling and the last
    ~17 ms are missing. Both come from `planning`, not from guesswork.
"""
from __future__ import annotations

import argparse
import os
import sys
import threading
import time

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

from rp_lockin import plan_two_tone_grid                      # noqa: E402
from rp_lockin.hardware import RedPitaya                      # noqa: E402
from rp_lockin.pipeline import reduce_sweep                   # noqa: E402
from rp_lockin.planning import recommended_tail, settling_points  # noqa: E402
from rp_lockin.output import write_trace_csv, write_raw_npz   # noqa: E402
from tsl775 import TSL775                                     # noqa: E402

# The August-validated sweep. Do not change these casually: the 0.02 nm step at
# 100 nm/s is what makes the trigger a 5 kHz train, which is what the 5000 Sa/s
# output rate is built around.
START_NM, STOP_NM = 1500.0, 1600.0
SPEED_NM_S, TRIG_STEP_NM = 100.0, 0.02
MODE, CYCLES = 1, 1              # continuous, ONE WAY -- two-way overwrites the log
EXPECTED_POINTS = int(round((STOP_NM - START_NM) / TRIG_STEP_NM)) + 1

DECIMATION = 8
OUTPUT_RATE = 5000.0
# (5001 logged points - 1) x 200 us. The table covers exactly this much time,
# and the trace may not run past it.
SWEEP_SECONDS = (EXPECTED_POINTS - 1) * (TRIG_STEP_NM / SPEED_NM_S)


def parse():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default=os.environ.get("RP_HOST", "rp-fffe42.local"),
                    help="board hostname (default $RP_HOST)")
    ap.add_argument("--laser-ip", default="10.101.0.197")
    ap.add_argument("--out", default="data/sweep",
                    help="output basename; data/ is gitignored for captures")
    ap.add_argument("--shutter-open-ok", action="store_true",
                    help="proceed even with the shutter OPEN. The detector's "
                         "damage threshold is unknown; do not pass this "
                         "casually.")
    ap.add_argument("--arm-delay", type=float, default=3.0,
                    help="seconds to let the capture arm before the sweep starts")
    return ap.parse_args()


def configure_laser(d, args):
    """The exact working order from TSL775_HANDOFF.md section 6. Order matters."""
    print(f"laser: {d.query('*IDN?')}")

    shutter = d.query(":POW:SHUT?").strip().lstrip("+")
    print(f"shutter: {shutter} (1 = closed)")
    if shutter == "0" and not args.shutter_open_ok:
        raise SystemExit(
            "REFUSING: the shutter is OPEN and the photodetector is connected.\n"
            "It saturates around 0.96 mW and its damage threshold is unknown.\n"
            "The trigger train and the wavelength log both work with the "
            "shutter CLOSED, so close it and run again -- or pass "
            "--shutter-open-ok if you have decided the power is safe.")

    before = {k: d.query(q) for k, q in (
        ("start", ":WAV:SWE:STAR?"), ("stop", ":WAV:SWE:STOP?"),
        ("speed", ":WAV:SWE:SPE?"), ("cycles", ":WAV:SWE:CYCL?"),
        ("mode", ":WAV:SWE:MOD?"), ("trig", ":TRIG:OUTP?"),
        ("trigstep", ":TRIG:OUTP:STEP?"))}
    print(f"original: {before}")

    d.write(":POW:STAT 1"); time.sleep(2.0)          # laser ON first, always
    if d.query(":POW:STAT?").strip().lstrip("+") != "1":
        raise SystemExit("emission did not enable; the sweep cannot start")
    d.write(":WAV:SWE 0"); time.sleep(0.5)           # explicit stop before config
    d.write(f":WAV:SWE:SPE {SPEED_NM_S}")            # speed FIRST -- range depends on it
    d.write(f":WAV:SWE:STAR {START_NM * 1e-9:.9E}")  # METRES
    d.write(f":WAV:SWE:STOP {STOP_NM * 1e-9:.9E}")
    d.write(f":WAV:SWE:MOD {MODE}")
    d.write(f":WAV:SWE:CYCL {CYCLES}")
    d.write(f":TRIG:OUTP 3")                         # 3 = Step. MANDATORY.
    d.write(f":TRIG:OUTP:STEP {TRIG_STEP_NM * 1e-9:.9E}")

    got = {k: d.query(q) for k, q in (
        ("mode", ":WAV:SWE:MOD?"), ("trig", ":TRIG:OUTP?"),
        ("setting", ":TRIG:OUTP:SETT?"))}
    print(f"configured: {got}   (setting 0 = periodic in WAVELENGTH -- Q24)")
    if got["trig"].strip().lstrip("+") != "3":
        raise SystemExit(":TRIG:OUTP is not 3; there would be no train and no log")
    return before


def restore(d, before):
    for cmd, key in ((":WAV:SWE:STAR", "start"), (":WAV:SWE:STOP", "stop"),
                     (":WAV:SWE:SPE", "speed"), (":WAV:SWE:CYCL", "cycles"),
                     (":WAV:SWE:MOD", "mode"), (":TRIG:OUTP", "trig"),
                     (":TRIG:OUTP:STEP", "trigstep")):
        try:
            d.write(f"{cmd} {before[key].strip()}")
        except Exception:
            pass


def edge_report(edges):
    """The residual profile. This is what settles the 43.2 us question (Q29)."""
    if edges.size < 10:
        print("too few edges to profile")
        return
    k = np.arange(edges.size, dtype=float)
    slope, ic = np.polyfit(k, edges, 1)
    r = edges - (slope * k + ic)
    g = np.diff(edges)
    print(f"\n--- trigger train ---")
    print(f"edges {edges.size}   gaps: mean {g.mean()*1e6:.4f} us  "
          f"sd {g.std()*1e6:.4f}  min {g.min()*1e6:.3f}  max {g.max()*1e6:.3f}")
    print(f"line fit: step {slope*1e6:.4f} us   residual rms {r.std()*1e6:.3f} us"
          f"   peak {np.abs(r).max()*1e6:.3f} us")
    print("residual by decile (us) -- a SMOOTH ramp means sweep-speed variation;")
    print("a STEP means a discrete stall. They look nothing alike:")
    for i in range(10):
        a, b = i * edges.size // 10, (i + 1) * edges.size // 10
        print(f"  {i*10:3d}-{(i+1)*10:3d}%  mean {r[a:b].mean()*1e6:9.3f}  "
              f"rms {r[a:b].std()*1e6:8.3f}")
    big = np.flatnonzero(np.abs(g - np.median(g)) > 5e-6)
    print(f"gaps more than 5 us off the median: {big.size}")
    for i in big[:10]:
        print(f"  after edge {i} (t = {edges[i]*1e3:.3f} ms): {g[i]*1e6:.3f} us")


def main():
    args = parse()
    f_ref = plan_two_tone_grid().difference
    fs = 250e6 / DECIMATION

    n_settle, t_settle = settling_points(OUTPUT_RATE, fs=fs)
    tail = recommended_tail(OUTPUT_RATE, fs=fs)
    preroll = int((t_settle * 1.1) * fs)
    # Size the record to pre-roll + sweep + tail, NOT to the DMA ceiling.
    # Capturing longer is not free: map_to_wavelength refuses to extrapolate
    # past the end of the laser's table, and rightly so -- every sample beyond
    # the last logged point has no wavelength. Filling the whole 1.0737 s
    # region overruns the 1.000 s table by ~37 ms and the reduction stops.
    n_samples = int(np.ceil((preroll / fs + SWEEP_SECONDS + tail) * fs))
    n_samples = min(n_samples, 33554432)      # the DMA ceiling, per channel
    print(f"f_ref {f_ref:.3f} Hz | fs {fs/1e6:.4f} MS/s | record "
          f"{n_samples/fs:.4f} s | pre-roll {preroll/fs*1e3:.2f} ms "
          f"(settling {t_settle*1e3:.2f} ms) | tail needed {tail*1e3:.2f} ms")
    if n_samples / fs < preroll / fs + SWEEP_SECONDS + tail:
        raise SystemExit("record too short for pre-roll + sweep + tail")

    captured = {}

    def capture(rp):
        try:
            ch = rp.acquire_deep_fast(
                n_samples=n_samples, decimation=DECIMATION, channels=(1, 2),
                trigger="CH2_PE", trigger_level=1.0,
                preroll_samples=preroll, trigger_timeout=120.0)
            captured["detector"], captured["trigger"] = ch[0], ch[1]
        except Exception as e:                      # noqa: BLE001
            captured["error"] = e

    d = TSL775.connect("lan", host=args.laser_ip, timeout=5.0)
    before = None
    try:
        before = configure_laser(d, args)
        with RedPitaya(args.host) as rp:
            print(f"board: {rp.query('*IDN?')}")
            rp.setup_acquisition(decimation=DECIMATION, coupling="DC", gain="LV")
            rp.setup_channel(1, coupling="AC", gain="LV")   # detector: 0-10 V unipolar
            rp.setup_channel(2, gain="HV")                  # 3.3 V trigger clips on LV

            t = threading.Thread(target=capture, args=(rp,), daemon=True)
            t.start()
            time.sleep(args.arm_delay)               # let the capture arm first
            print(">>> starting sweep")
            d.write(":WAV:SWE 1")

            t0 = time.time()
            while time.time() - t0 < 30.0:
                if d.query(":WAV:SWE?").strip().lstrip("+") == "0" and time.time() - t0 > 2:
                    break
                time.sleep(0.1)   # 10 Hz: the handoff blames high query rates
            print(f">>> sweep finished in {time.time()-t0:.2f} s")

            t.join(timeout=180.0)
            if "error" in captured:
                raise captured["error"]
            if "trigger" not in captured:
                raise SystemExit("the capture did not complete")

            n_log = int(d.query(":READ:POIN?").strip().lstrip("+"))
            wl = np.asarray(d.query_wavelength_log(scpi=True), dtype=float)
            print(f">>> laser log: {n_log} points, "
                  f"{wl[0]*1e9:.4f} -> {wl[-1]*1e9:.4f} nm")
    finally:
        try:
            d.write(":WAV:SWE 0")
            d.write(":POW:STAT 0")
            if before:
                restore(d, before)
            print(f"laser off: {d.query(':POW:STAT?')}   "
                  f"shutter {d.query(':POW:SHUT?')}")
        except Exception:                            # noqa: BLE001
            pass
        d.close()

    det = np.asarray(captured["detector"], dtype=float)
    trg = np.asarray(captured["trigger"], dtype=float)

    # The threshold trap: IN2 is unipolar in COUNTS, so the 0.0 default finds
    # nothing. Take the midpoint of the record's own levels.
    lo, hi = np.percentile(trg, 1), np.percentile(trg, 99)
    thr = float(0.5 * (lo + hi))
    print(f"\ntrigger levels {lo:.1f} .. {hi:.1f} counts -> threshold {thr:.1f}")
    if hi - lo < 50:
        raise SystemExit(f"IN2 swing is only {hi-lo:.1f} counts. Nothing is "
                         f"arriving on IN2 -- is the trigger BNC in the analog "
                         f"IN2 socket rather than the external-trigger one?")

    red = reduce_sweep(det, trg, fs, wl, f_ref=f_ref, output_rate=OUTPUT_RATE,
                       trigger_threshold=thr, trigger_polarity="rising",
                       nominal_step=TRIG_STEP_NM / SPEED_NM_S)

    print(f"\n--- reduction ---")
    print(f"points {red.n_points}   step {red.step*1e6:.4f} us "
          f"({red.step_source})   first edge {red.first_edge*1e3:.4f} ms")
    print(f"alignment: {red.alignment.diagnosis}")
    print("NOTE: the span check is vacuous when the step came from the edges "
          "themselves -- only the COUNT check does work there.")
    edge_report(red.edges)

    csv, npz = f"{args.out}.csv", f"{args.out}.npz"
    write_trace_csv(csv, red.trace.wavelength, red.trace.amplitude,
                    metadata=red.metadata())
    write_raw_npz(npz, detector=det, trigger=trg, wavelengths=wl,
                  edges=red.edges)
    print(f"\nwrote {csv} ({red.n_points} rows) and {npz}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
