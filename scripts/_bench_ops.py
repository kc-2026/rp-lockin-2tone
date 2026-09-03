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

import math
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
    """Enable an AM output. Returns the table that is REALLY being played.

    With `exact` the play rate is chosen so both frequencies come out on the
    nose, which any whole number of hertz can. Without it the table falls back
    to the default fs/16384 grid and the frequencies are snapped. Either way
    what comes back is what is on the wire; what was asked for is not.

    `channel` is 1 or 2. SFG drives both at once, at different modulation
    frequencies, and they are independent from here down.
    """
    return rp.setup_am_generator(carrier=carrier, modulation=modulation,
                                 amplitude=amplitude, depth=depth,
                                 channel=channel, exact=exact)


def drive_off(rp, channel=None):
    """Disarm one output, or both when `channel` is None.

    Both is the default because that is what every cleanup path wants, and a
    cleanup path that only disarmed the channel it happened to know about
    would leave light on the bench.
    """
    for ch in ((1, 2) if channel is None else (int(channel),)):
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


def find_signal_mask(amp, k=6.0, guard=8):
    """Which points are signal, without being told where the signal is.

    MAD rather than the standard deviation, because the peak is IN the data
    being measured and would inflate an ordinary sigma -- a narrow sinc on a
    5000-point trace barely moves the median absolute deviation, which is the
    point of using it.

    `guard` widens the mask by that many points on each side, so the skirts of
    the peak are not counted as noise. Without it the floor reads high on
    exactly the traces with the most signal, which is backwards.
    """
    a = np.asarray(amp, dtype=float)
    good = np.isfinite(a)
    med = float(np.median(a[good])) if good.any() else 0.0
    mad = 1.4826 * float(np.median(np.abs(a[good] - med))) if good.any() else 0.0
    if mad <= 0:
        # A noiseless trace, or one so flat that more than half its points are
        # identical. There is no noise scale to measure, so fall back to a
        # fraction of the peak -- returning "no signal anywhere" would be the
        # one answer that is certainly wrong when a peak is sitting there.
        peak = float(np.nanmax(np.abs(a - med))) if good.any() else 0.0
        if peak <= 0:
            return np.zeros(a.shape, dtype=bool)
        mad = peak / 100.0 / k
    mask = np.abs(a - med) > k * mad
    mask &= good
    if guard > 0 and mask.any():
        widened = mask.copy()
        for shift in range(1, int(guard) + 1):
            widened[shift:] |= mask[:-shift]
            widened[:-shift] |= mask[shift:]
        mask = widened
    return mask


def trace_dynamic_range(traces, k=6.0, guard=8):
    """Peak, noise floor and dynamic range from repeated sweeps of one setting.

**`floor_across` is the floor.** It is the scatter of the same
    wavelength across repeats, so it needs no idea where the signal is and no
    assumption that the signal ever stops. Verified against known truth: 3.55
    against a true 3.57 uV.

    `floor_offregion` -- the rms of the averaged trace away from the peak -- is
    NOT a second opinion on the floor. It only equals the floor when the signal
    is compact. Measured on synthetic traces at a true 3.57 uV:

        narrow gaussian            off-region 3.59 uV   ratio    1.0x
        sinc, tails everywhere     off-region 14561 uV  ratio 4100.0x

    So `tail_ratio` is the useful output, not a warning: **near 1 the trace
    really is empty away from the peak; well above 1 there is real structure
    out in the tails**, which for a sinc is the answer rather than a problem.
    It says how far down the skirts the measurement is still resolving
    something.

    Returns the peak from the averaged trace, the floor per single sweep and
    for the average, and the dynamic range against each.
    """
    stack = np.vstack([np.asarray(t, dtype=float).ravel() for t in traces])
    m = stack.shape[0]
    if m < 1:
        raise ValueError("need at least one trace")
    mean = np.nanmean(stack, axis=0)

    if m >= 2:
        per_point = np.nanstd(stack, axis=0, ddof=1)
        floor_across = float(np.sqrt(np.nanmean(per_point ** 2)))
    else:
        floor_across = float("nan")

    mask = find_signal_mask(mean, k=k, guard=guard)
    off = mean[~mask & np.isfinite(mean)]
    if off.size >= 16:
        # amplitude() is unbiased and zero-mean in noise, so rms about zero is
        # the estimator -- no baseline to subtract and none invented.
        floor_avg = float(np.sqrt(np.mean(off ** 2)))
        floor_offregion = floor_avg * np.sqrt(m)
    else:
        floor_avg = floor_offregion = float("nan")

    peak = float(np.nanmax(np.abs(mean)))
    # Across-repeats wherever there is more than one sweep. The off-region
    # number stands in only for a lone sweep, where it is the best available
    # and should be treated as an upper bound.
    single = floor_across if np.isfinite(floor_across) else floor_offregion

    def db(top, bottom):
        if not (np.isfinite(top) and np.isfinite(bottom)) or bottom <= 0:
            return float("nan")
        return 20.0 * np.log10(top / bottom)

    return {
        "n_sweeps": m,
        "peak": peak,
        "floor_across": floor_across,
        "floor_offregion": floor_offregion,
        "floor_single": single,
        "floor_averaged": single / np.sqrt(m) if np.isfinite(single) else
        float("nan"),
        "dr_single_db": db(peak, single),
        "dr_averaged_db": db(peak, single / np.sqrt(m))
        if np.isfinite(single) else float("nan"),
        "tail_ratio": (floor_offregion / floor_across
                       if np.isfinite(floor_offregion)
                       and np.isfinite(floor_across) and floor_across > 0
                       else float("nan")),
        "signal_points": int(mask.sum()),
        "noise_points": int((~mask).sum()),
        "mean": mean,
    }


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


def set_wavelength_m(laser, metres, tolerance=1e-12, timeout=60.0,
                     poll=0.2):
    """Drive the laser to `metres` and WAIT until the read-back agrees.

    **METRES, and checked.** In the Legacy command set these queries answer in
    NANOMETRES, and `:WAV 1550` would command the laser 1550 metres. A range
    check is the only thing standing between a unit slip and that.

    **Settling is decided by measurement, not a timer.** No busy flag is
    documented for the 775, so this polls until the read-back both matches the
    target and has stopped moving -- two consecutive on-target readings, so a
    value caught in passing does not count as arrival. It raises if the laser
    never converges.

    That read-back is also what proves the command string at all: the SET form
    of `:WAVelength` is not in the manuals' command tables, only the query. On
    this instrument a wrong command returns zero bytes exactly like a right
    one, so a write-only setter here would fail silently.

    **This leaves the sweep unable to run -- see Q32.** Setting a wavelength by
    hand and then starting a sweep produced no trigger train at all, twice,
    with every sweep setting still correct. Re-Configure the sweep afterwards,
    and treat a sweep that will not trigger as this having happened.
    """
    if not 1.0e-6 <= metres <= 2.0e-6:
        raise ValueError(
            f"wavelength must be in METRES, got {metres!r}. A C-band value is "
            f"~1.55e-6, not 1550. Refusing rather than commanding the laser "
            f"with a number that is 10^9 out.")
    t0 = time.time()
    laser.write(f":WAV {metres:.12E}")
    last = None
    while time.time() - t0 < timeout:
        time.sleep(poll)
        at = float(laser.query(":WAV?"))
        if (abs(at - metres) <= tolerance and last is not None
                and abs(at - last) <= tolerance):
            return {"target_m": metres, "arrived_m": at,
                    "waited_s": time.time() - t0}
        last = at
    raise RuntimeError(
        f"the laser did not reach {metres * 1e9:.4f} nm within {timeout:g} s"
        + ("" if last is None else f" (it reads {last * 1e9:.4f} nm)")
        + ". Nothing was swept and no measurement was taken.")


def set_ld(laser, on: bool):
    laser.write(f":POW:STAT {1 if on else 0}")
    time.sleep(2.0 if on else 0.3)
    return laser.query(":POW:STAT?").strip().lstrip("+")


# SPEED FIRST, deliberately. The usable start/stop range depends on the
# speed, so writing a wavelength before the speed it belongs to can be
# rejected. This tuple sets the order for BOTH configure and restore.
SWEEP_KEYS = (("speed", ":WAV:SWE:SPE"), ("start", ":WAV:SWE:STAR"),
              ("stop", ":WAV:SWE:STOP"), ("mode", ":WAV:SWE:MOD"),
              ("cycles", ":WAV:SWE:CYCL"), ("trig", ":TRIG:OUTP"),
              ("trigstep", ":TRIG:OUTP:STEP"))

# Wavelengths arrive as metres near 1.5e-6 and the trigger step as ~2e-11, so
# the absolute floor has to be small; the relative term carries everything
# else. Modes and counts are small integers and compare exactly under this.
_SWEEP_RTOL, _SWEEP_ATOL = 1e-4, 1e-13


def read_sweep_config(laser):
    return {k: laser.query(c + "?").strip() for k, c in SWEEP_KEYS}


def wait_sweep_stopped(laser, timeout=15.0, poll=0.1):
    """Poll until :WAV:SWE? reads 0, and say so if it never does.

    This replaces a fixed 0.5 s sleep, which is what made the SECOND run of a
    sweep fail while the first passed. From cold the laser stops instantly and
    every later write lands; still busy from a previous sweep it does not, and
    the settings written into that window are DISCARDED WITHOUT AN ERROR.
    """
    t0 = time.time()
    while time.time() - t0 < timeout:
        if laser.query(":WAV:SWE?").strip().lstrip("+") == "0":
            return time.time() - t0
        time.sleep(poll)
    raise RuntimeError(
        f"the sweep did not stop within {timeout:g} s (:WAV:SWE? never read "
        f"0). Configuring now would write settings the laser discards without "
        f"an error -- which reads back later as a sweep in the wrong mode.")


def check_sweep_config(want, got):
    """Which requested settings did the laser NOT take? Returns a list.

    Every value is compared numerically against the read-back. The laser
    accepts a write it is not in a state to honour and says nothing, so a
    write-only setter here is a silent wrong answer rather than a failure.
    """
    bad = []
    for key, _cmd in SWEEP_KEYS:
        if key not in want:
            continue
        try:
            g = float(got[key])
        except (KeyError, ValueError):
            bad.append(f"{key}: unreadable ({got.get(key)!r})")
            continue
        w = float(want[key])
        if not math.isclose(g, w, rel_tol=_SWEEP_RTOL, abs_tol=_SWEEP_ATOL):
            bad.append(f"{key}: asked {w:g}, laser holds {g:g}")
    return bad


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
    stopped_in = wait_sweep_stopped(laser)
    laser.write(f":WAV:SWE:SPE {speed_nm_s:g}")
    laser.write(f":WAV:SWE:STAR {start_nm * 1e-9:.9E}")
    laser.write(f":WAV:SWE:STOP {stop_nm * 1e-9:.9E}")
    laser.write(f":WAV:SWE:MOD {int(mode)}")
    laser.write(f":WAV:SWE:CYCL {int(cycles)}")
    laser.write(":TRIG:OUTP 3")
    laser.write(f":TRIG:OUTP:STEP {step_nm * 1e-9:.9E}")
    got = read_sweep_config(laser)
    want = {"speed": speed_nm_s, "start": start_nm * 1e-9,
            "stop": stop_nm * 1e-9, "mode": int(mode), "cycles": int(cycles),
            "trig": 3, "trigstep": step_nm * 1e-9}
    bad = check_sweep_config(want, got)
    if bad:
        # EVERY setting, not just :TRIG:OUTP. Checking one of seven is how a
        # sweep silently reverted to step mode between the first run and the
        # second: nothing read the mode back, so nothing noticed.
        raise RuntimeError(
            "the laser did not take these sweep settings:\\n  "
            + "\\n  ".join(bad)
            + "\\nIt accepts a write it cannot honour and reports no error. "
              "Stop the sweep, wait for :WAV:SWE? to read 0, and configure "
              "again.")
    return {"before": before, "after": got, "stopped_in": stopped_in}


def restore_sweep(laser, before):
    """Put back what was there. Returns whatever would not go back.

    Runs in a `finally`, so it must not raise -- a failure here would mask the
    exception that got us there. It must not be SILENT either: the old version
    swallowed every error, so a restore that did nothing looked identical to
    one that worked. SWEEP_KEYS puts speed first for the same reason
    configure_sweep writes it first.
    """
    failed = []
    for key, cmd in SWEEP_KEYS:
        if key not in before:
            continue
        try:
            laser.write(f"{cmd} {before[key].strip()}")
        except Exception as exc:                 # noqa: BLE001
            failed.append(f"{key}: {exc.__class__.__name__}: {exc}")
    return failed


def wait_until_at_start(laser, tolerance=1e-11, timeout=60.0, poll=0.2):
    """Block until the laser has finished returning to its sweep start.

    **Read-only.** It polls `:WAV?` and never writes `:WAV` -- which matters,
    because commanding the wavelength directly leaves the instrument unable to
    sweep at all (Q32). Configuring a sweep already sends the laser back to its
    start; this only waits for it to arrive.

**It REPORTS, it does not insist.** An earlier version raised on
    timeout, on the assumption that configuring a sweep sends the laser back
    to its start. Measured 2026-09-02: it does not. After `configure_sweep`
    the laser sat at 1600 nm for the full 60 s, so the wait was waiting for
    something that was never going to happen and the run failed instead of
    proceeding. Whatever returns the laser to its start, it is not Configure.

    So this polls for up to `timeout`, then returns either way with `arrived`
    saying which. The caller decides -- and every caller should say so out
    loud, because starting from the wrong wavelength sweeps a SHORT RANGE at
    exactly the right speed and step: the trigger train is correct in every
    respect except its length. Measured the same day, 5001 rows logged against
    a train spanning 393 ms, i.e. 1561 -> 1600 nm instead of 1500 -> 1600.
    `reduce_sweep` refused rather than inventing wavelengths, which is the only
    reason it was visible.

    Returns where the laser was, where it ended up, whether it arrived, and how
    long it took.
    """
    start = float(laser.query(":WAV:SWE:STAR?"))
    t0 = time.time()
    first = at = None
    while time.time() - t0 < timeout:
        at = float(laser.query(":WAV?"))
        if first is None:
            first = at
        if abs(at - start) <= tolerance:
            return {"start_m": start, "from_m": first, "at_m": at,
                    "arrived": True, "waited_s": time.time() - t0}
        time.sleep(poll)
    return {"start_m": start, "from_m": first, "at_m": at, "arrived": False,
            "short_by_m": abs((at if at is not None else start) - start),
            "waited_s": time.time() - t0}


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

def max_output_rate(fs, f_ref, min_cycles=10.0, cap=200000.0):
    """The fastest trace this capture and this f_ref can support.

    Three things bound it, and the third is the one that binds in practice:

    1. **fs / output_rate must be a whole number.** `demodulate` refuses
       otherwise rather than resampling behind your back.
    2. `cap`, a sanity ceiling.
    3. **The lock-in needs enough reference cycles per integration time.**
       Bandwidth is 0.9 x the output Nyquist, tau = 1/(2 pi BW), and below
       roughly 10 cycles per tau the output carries 1f and 2f ripple -- the
       demodulator stops averaging the carrier away and starts passing it.

    At fs = 31.25 MS/s that gives 31250 Sa/s for a 1 MHz reference and 62500
    for 2 MHz, both landing at 11.3 cycles per tau.

    **It is not free.** Bandwidth rises with the output rate and sigma goes as
    its square root, so 5000 -> 62500 Sa/s costs a factor 3.5 in noise -- 11 dB
    of dynamic range. Returns the rate and what it costs, so the caller can
    say so.
    """
    best = None
    for n in range(1, 200001):
        if fs % n:
            continue
        rate = fs / n
        if rate > cap or rate < 1.0:
            continue
        bw = 0.9 * rate / 2.0
        cycles = f_ref / (2.0 * math.pi * bw) if bw > 0 else float("inf")
        if cycles < min_cycles:
            continue
        if best is None or rate > best["output_rate"]:
            best = {"output_rate": float(rate), "bandwidth": bw,
                    "cycles_per_tau": cycles, "divisor": n}
    if best is None:
        raise ValueError(
            f"no output rate divides {fs / 1e6:g} MS/s exactly while keeping "
            f"{min_cycles:g} reference cycles per integration time at "
            f"{f_ref / 1e3:g} kHz. Lower the reference or the decimation.")
    return best


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
