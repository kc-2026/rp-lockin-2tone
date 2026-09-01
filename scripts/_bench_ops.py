#!/usr/bin/env python3
"""
Bench operations: every instrument action, with no Tk anywhere.

This module is the reason the bench can be granular. Each function does ONE
thing to ONE instrument, so a button and a sequence step are the same call --
there is no second implementation of "run a sweep" that can drift from the
buttons. The old GUI's Linear Sweep tab was exactly that second
implementation, and fixes had to be made twice.

Everything takes the instrument as an argument and returns data. Nothing here
knows what a widget is, which is also what makes it testable.
"""
from __future__ import annotations

import threading
import time

import numpy as np

from rp_lockin.constants import (ADC_COUNTS_PER_V_LV, ADC_COUNT_MAX,
                                 ADC_COUNT_MIN, BASE_SAMPLE_RATE)
from rp_lockin.dsp import demodulate
from rp_lockin.emulator import find_trigger_edges
from rp_lockin.pipeline import reduce_sweep
from rp_lockin.planning import recommended_tail, settling_points

ASG_GRID = BASE_SAMPLE_RATE / 16384
DMA_SAMPLE_CEILING = 33554432          # per channel, the reserved region

# TSL-775 sweep speeds are a DISCRETE selection, not a continuous setting
# (manual p.87). Anything else is rejected by the instrument. The usable
# wavelength range also depends on the speed, so :WAV:SWE:RANG:MIN?/MAX? are
# worth re-reading after changing it.
SWEEP_SPEEDS_NM_S = (0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 50.0, 100.0, 200.0)

# :WAVelength:SWEep:MODe. Two-way is a trap for logging: one round trip counts
# as two cycles and the return pass OVERWRITES the log, so a two-way run comes
# back with only the descending half.
SWEEP_MODES = {0: "step, one way", 1: "continuous, one way",
               2: "step, two way (log is overwritten)",
               3: "continuous, two way (log is overwritten)"}


# ----------------------------------------------------------------- the board

def front_end(rp, in1_coupling="AC", in1_gain="LV",
              in2_coupling="DC", in2_gain="HV", decimation=8):
    """Per-channel coupling and gain.

    IN1 AC on LV: the detector is 0-10 V unipolar into Hi-Z, so DC coupling
    parks the input on the rail. AC coupling costs nothing here -- the corner
    is 17 Hz (Q25).

    IN2 on HV: the laser trigger swings to 3.3 V and CLIPS on the +/-1 V range
    into a flat line, which reads as "the laser is not triggering" rather than
    as a range error.
    """
    rp.setup_acquisition(decimation=decimation, coupling="DC", gain="LV")
    rp.setup_channel(1, coupling=in1_coupling, gain=in1_gain)
    rp.setup_channel(2, coupling=in2_coupling, gain=in2_gain)
    return {"in1": f"{in1_gain}/{in1_coupling}", "in2": f"{in2_gain}/{in2_coupling}",
            "decimation": decimation}


def drive_on(rp, carrier, modulation, amplitude, depth=1.0, channel=1,
             exact=True):
    """Enable an AM output. Returns the table, whose frequencies are SNAPPED.

    Both frequencies land on the fs/16384 grid because that is the only way the
    16384-entry table wraps without a discontinuity. What comes back is what is
    actually being generated; what was asked for is not.
    """
    return rp.setup_am_generator(carrier=carrier, modulation=modulation,
                                 amplitude=amplitude, depth=depth,
                                 channel=channel, exact=exact)


def drive_off(rp):
    for ch in (1, 2):
        rp.write(f"OUTPUT{ch}:STATE OFF")
    return True


def drive_state(rp, channel=1):
    """What the board says, not what we remember telling it."""
    return rp.query(f"OUTPUT{channel}:STATE?").strip() not in ("0", "OFF", "off")


def capture_plan(seconds, decimation=8, output_rate=5000.0, preroll_factor=1.1):
    """Samples and pre-roll for a record that must cover `seconds` of sweep.

    The record needs pre-roll BEFORE the trigger and a tail AFTER the sweep, or
    the first ~113 output points are filter settling and the last ~17 ms are
    missing. Sizing it to the DMA ceiling instead is worse, not safer: the
    mapping refuses to extrapolate past the end of the laser's table, and every
    sample beyond the last logged point has no wavelength.
    """
    fs = BASE_SAMPLE_RATE / decimation
    _n, t_settle = settling_points(output_rate, fs=fs)
    tail = recommended_tail(output_rate, fs=fs)
    preroll = int(t_settle * preroll_factor * fs)
    n = int(np.ceil((preroll / fs + seconds + tail) * fs))
    # What a full region could cover at this decimation, once pre-roll and
    # tail are paid for. Truncating instead would silently return a record
    # that stops part way through the sweep, and a half sweep mapped onto a
    # full wavelength table looks like a measurement.
    max_sweep = DMA_SAMPLE_CEILING / fs - preroll / fs - tail
    return {"fs": fs, "n_samples": min(n, DMA_SAMPLE_CEILING),
            "preroll": preroll, "settling_s": t_settle, "tail_s": tail,
            "decimation": decimation, "max_sweep_s": max_sweep,
            "truncated": n > DMA_SAMPLE_CEILING}


def smallest_decimation_for(seconds, output_rate=5000.0):
    """The lowest decimation whose region can still hold `seconds` of sweep.

    Lower decimation is faster sampling and so a shorter record for the same
    memory: the reserved region is 33554432 samples per channel however it is
    filled. At decimation 8 that is 1.03 s of sweep; at 4 it is 0.50 s, which
    cannot hold a 1 s sweep at all.
    """
    for d in (1, 2, 4, 8, 16, 32, 64):
        if capture_plan(seconds, decimation=d, output_rate=output_rate)["max_sweep_s"] >= seconds:
            return d
    return None


def acquire(rp, n_samples, decimation=8, preroll=0, trigger="CH2_PE",
            level=1.0, timeout=30.0, should_stop=None):
    """One two-channel deep capture. Returns RAW COUNTS plus provenance.

    Counts, not volts: the rail belongs to the converter, so clipping has to be
    judged before any scaling. `volts()` does the conversion when it is wanted.
    """
    ch = rp.acquire_deep_fast(n_samples=n_samples, decimation=decimation,
                              channels=(1, 2), trigger=trigger,
                              trigger_level=level, preroll_samples=preroll,
                              trigger_timeout=timeout, should_stop=should_stop)
    c1 = np.asarray(ch[0], dtype=float)
    c2 = np.asarray(ch[1], dtype=float)
    fs = BASE_SAMPLE_RATE / decimation
    # Where the sweep began, in this record's own time. Found once, here, so
    # every later view can show time relative to it without re-scanning 33 M
    # samples -- and so the number every view uses is the same number.
    first_edge, last_edge, n_edges = None, None, 0
    try:
        thr, lo, hi = trigger_threshold(c2)
        if hi - lo > 50:                    # a trigger is actually present
            edges = find_trigger_edges(c2, fs, threshold=thr,
                                       polarity="rising")
            if edges.size:
                first_edge = float(edges[0])
                last_edge = float(edges[-1])
                n_edges = int(edges.size)
    except Exception:                        # noqa: BLE001
        pass
    return {"ch1": c1, "ch2": c2, "fs": fs, "decimation": decimation,
            "preroll": preroll, "trigger": trigger, "t": time.time(),
            "first_edge": first_edge, "last_edge": last_edge,
            "n_edges": n_edges}


def acquire_async(rp, **kw):
    """Arm a capture on a background thread.

    The capture BLOCKS until the trigger arrives, and the thing that produces
    that trigger is the laser -- a different instrument. Returns
    (thread, result) so the caller can start the sweep while this waits.
    """
    out = {}

    def run():
        try:
            out.update(acquire(rp, **kw))
        except Exception as exc:                 # noqa: BLE001
            out["error"] = exc

    th = threading.Thread(target=run, daemon=True)
    th.start()
    return th, out


def check_train(capture, expected_seconds, expected_points=None,
                tol=0.05):
    """Did the trigger train last as long as the sweep that was asked for?

    A sweep that finishes early leaves the laser PARKED at its end wavelength
    for the rest of the record, and the trace then shows two quite different
    regimes with a sharp boundary: real structure while it sweeps, then a
    smooth slow drift while it sits. That reads as physics. It is a mismatch
    between the speed the capture was sized for and the speed the instrument
    actually ran at -- pressing Configure before or after changing the speed is
    enough to do it.

    Returns a dict, and `ok` False when the train is short.
    """
    fe, le, n = (capture.get("first_edge"), capture.get("last_edge"),
                 capture.get("n_edges", 0))
    if fe is None or le is None or n < 3:
        return {"ok": None, "reason": "no usable trigger train"}
    span = le - fe
    ratio = span / expected_seconds if expected_seconds else float("nan")
    out = {"ok": abs(ratio - 1.0) <= tol, "span": span, "n_edges": n,
           "expected": expected_seconds, "ratio": ratio,
           "implied_speed_factor": (1.0 / ratio) if ratio else float("nan")}
    if expected_points:
        out["expected_points"] = expected_points
        out["points_ok"] = abs(n - expected_points) <= max(2, expected_points // 100)
    return out


def volts(counts, gain="LV"):
    scale = ADC_COUNTS_PER_V_LV if gain == "LV" else ADC_COUNTS_PER_V_LV / 20.0
    return np.asarray(counts, dtype=float) / scale


def clipped(counts):
    c = np.asarray(counts)
    return int(np.count_nonzero((c >= ADC_COUNT_MAX) | (c <= ADC_COUNT_MIN)))


def swing(counts):
    c = np.asarray(counts, dtype=float)
    return float(np.percentile(c, 99) - np.percentile(c, 1))


def trigger_threshold(counts):
    """Midpoint of the record's own levels.

    reduce_sweep defaults to 0.0, which is right for a bipolar trigger and
    finds NO edges on ours: IN2 idles near 6 counts and peaks near 302, so it
    never crosses zero.
    """
    lo, hi = np.percentile(counts, 1), np.percentile(counts, 99)
    return float(0.5 * (lo + hi)), float(lo), float(hi)


# ----------------------------------------------------------------- the laser

def laser_state(laser):
    """Everything worth showing, in one round trip each. Read-only."""
    out = {}
    for key, q in (("idn", "*IDN?"), ("power_dbm", ":POWer:LEVel?"),
                   ("shutter", ":POW:SHUT?"), ("ld", ":POW:STAT?"),
                   ("sweep", ":WAV:SWE?"), ("wavelength_m", ":WAV?")):
        try:
            out[key] = laser.query(q).strip()
        except Exception as exc:                 # noqa: BLE001
            out[key] = f"?({exc.__class__.__name__})"
    return out


def laser_power_limits(laser):
    """The instrument's own range. Asking below the floor is IGNORED, not
    refused: the setpoint stays put and the query answers with the old value,
    which looks exactly like a control run that quietly did nothing."""
    return (float(laser.query(":POWer:LEVel? MIN")),
            float(laser.query(":POWer:LEVel? MAX")))


def set_laser_power(laser, dbm, tolerance=0.2):
    lo, hi = laser_power_limits(laser)
    want = min(max(dbm, lo), hi)
    laser.write(f":POWer:LEVel {want:.3f}")
    time.sleep(0.5)
    got = float(laser.query(":POWer:LEVel?"))
    if abs(got - want) > tolerance:
        raise RuntimeError(f"asked for {want:.2f} dBm, laser reads {got:.2f} "
                           f"(range {lo:.2f} to {hi:.2f})")
    return {"requested": dbm, "applied": want, "readback": got,
            "clamped": abs(want - dbm) > 1e-9, "min": lo, "max": hi}


def set_shutter(laser, close: bool):
    """Close or open, and read back.

    NOT a control for light during a sweep: this instrument REOPENS the shutter
    by itself when a sweep starts. Use it to block light between runs, and read
    it DURING a sweep if you need to know what actually happened.
    """
    laser.write(f":POW:SHUT {1 if close else 0}")
    time.sleep(0.5)
    return laser.query(":POW:SHUT?").strip().lstrip("+")


def set_ld(laser, on: bool):
    laser.write(f":POW:STAT {1 if on else 0}")
    time.sleep(2.0 if on else 0.3)
    return laser.query(":POW:STAT?").strip().lstrip("+")


SWEEP_KEYS = (("start", ":WAV:SWE:STAR"), ("stop", ":WAV:SWE:STOP"),
              ("speed", ":WAV:SWE:SPE"), ("cycles", ":WAV:SWE:CYCL"),
              ("mode", ":WAV:SWE:MOD"), ("trig", ":TRIG:OUTP"),
              ("trigstep", ":TRIG:OUTP:STEP"))


def read_sweep_config(laser):
    return {k: laser.query(c + "?").strip() for k, c in SWEEP_KEYS}


def configure_sweep(laser, start_nm, stop_nm, speed_nm_s, step_nm,
                    mode=1, cycles=1):
    """The exact working order. Every line of it was arrived at by failing.

    The laser must be ON before the sweep is stopped and reconfigured, and an
    explicit stop must precede configuration, or :WAV:SWE? stays 0 forever with
    no error anywhere. Speed comes first because the usable range depends on
    it. Wavelengths are METRES. Mode 1 is one-way: two-way overwrites the log
    with the return pass. :TRIG:OUTP must be 3 or nothing is logged and no
    trigger train is emitted.
    """
    before = read_sweep_config(laser)
    laser.write(":POW:STAT 1")
    time.sleep(2.0)
    laser.write(":WAV:SWE 0")
    time.sleep(0.5)
    laser.write(f":WAV:SWE:SPE {speed_nm_s:g}")
    laser.write(f":WAV:SWE:STAR {start_nm * 1e-9:.9E}")
    laser.write(f":WAV:SWE:STOP {stop_nm * 1e-9:.9E}")
    laser.write(f":WAV:SWE:MOD {int(mode)}")
    laser.write(f":WAV:SWE:CYCL {int(cycles)}")
    laser.write(":TRIG:OUTP 3")
    laser.write(f":TRIG:OUTP:STEP {step_nm * 1e-9:.9E}")
    got = read_sweep_config(laser)
    if got["trig"].strip().lstrip("+") != "3":
        raise RuntimeError(":TRIG:OUTP is not 3, so there would be no trigger "
                           "train and an empty log")
    return {"before": before, "after": got}


def restore_sweep(laser, before):
    for key, cmd in SWEEP_KEYS:
        try:
            laser.write(f"{cmd} {before[key].strip()}")
        except Exception:                        # noqa: BLE001
            pass


def start_sweep(laser):
    laser.write(":WAV:SWE 1")
    return True


def stop_sweep(laser):
    laser.write(":WAV:SWE 0")
    return True


def wait_for_sweep(laser, timeout=60.0, poll=0.1, on_tick=None):
    """Poll until the sweep returns to Stopped. Reports the shutter mid-run.

    The shutter state BEFORE a sweep says nothing, because the instrument opens
    it by itself when the sweep starts. This reads it about a second in, which
    is the state light actually had.
    """
    t0 = time.time()
    shutter_during = None
    while time.time() - t0 < timeout:
        if shutter_during is None and time.time() - t0 > 1.0:
            shutter_during = laser.query(":POW:SHUT?").strip().lstrip("+")
        state = laser.query(":WAV:SWE?").strip().lstrip("+")
        if on_tick:
            on_tick(state, time.time() - t0)
        if state == "0" and time.time() - t0 > 2.0:
            return {"elapsed": time.time() - t0, "shutter_during": shutter_during}
        time.sleep(poll)
    raise RuntimeError(f"sweep did not finish within {timeout} s")


def read_log(laser):
    """The wavelength log, in METRES. Carries no timestamps."""
    n = int(laser.query(":READ:POIN?").strip().lstrip("+"))
    wl = np.asarray(laser.query_wavelength_log(scpi=True), dtype=float)
    if wl.size == 0:
        raise RuntimeError("the laser's log is empty. :TRIG:OUTP must be 3 "
                           "BEFORE the sweep runs, or nothing is recorded.")
    return {"wavelengths": wl, "points_reported": n}


# --------------------------------------------------------------- reduction

def run_demodulate(capture, f_ref, output_rate=5000.0, bandwidth=None,
                   gain="LV"):
    """Lock-in on IN1 alone. No wavelength axis involved."""
    return demodulate(volts(capture["ch1"], gain), capture["fs"], f_ref,
                      bandwidth=bandwidth, output_rate=output_rate)


def run_map(capture, wavelengths, f_ref, output_rate=5000.0, bandwidth=None,
            gain="LV", nominal_step=None):
    """The deliverable path: capture + laser log -> amplitude vs wavelength.

    Goes through `reduce_sweep` rather than reusing the Demodulate panel's
    result, so the trusted, offline-tested join is the one that runs. It
    demodulates again, which costs a few seconds and buys not having a second
    reduction path that could drift from the tested one.
    """
    thr, _lo, _hi = trigger_threshold(capture["ch2"])
    return reduce_sweep(volts(capture["ch1"], gain), capture["ch2"],
                        capture["fs"], wavelengths, f_ref=f_ref,
                        output_rate=output_rate, bandwidth=bandwidth,
                        trigger_threshold=thr, trigger_polarity="rising",
                        nominal_step=nominal_step)
