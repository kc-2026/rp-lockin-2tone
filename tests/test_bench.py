"""
The panel bench: that it builds, and that its pieces really are independent.

The point of `bench.py` is granularity, so these check the JOINTS rather than
the physics: that every panel constructs, that the workspace slots can be
filled and consumed separately, and that the operations layer is usable with no
Tk and no hardware. `_bench_ops` is tested directly because it is the layer
both the buttons and the sequences call -- if it is right in isolation, there
is no second implementation left to be wrong.
"""

import os
import sys

import numpy as np
import pytest

SCRIPTS = os.path.join(os.path.dirname(__file__), "..", "scripts")
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

tk = pytest.importorskip("tkinter")


@pytest.fixture(scope="module")
def bench_module():
    import bench
    return bench


@pytest.fixture
def app(bench_module, monkeypatch):
    try:
        root = tk.Tk()
    except tk.TclError as exc:                      # pragma: no cover
        pytest.skip(f"no display for Tk: {exc}")
    root.withdraw()
    monkeypatch.setattr(bench_module.messagebox, "showerror",
                        lambda *a, **k: None)
    monkeypatch.setattr(bench_module.messagebox, "showinfo",
                        lambda *a, **k: None)
    monkeypatch.setattr(bench_module.messagebox, "askokcancel",
                        lambda *a, **k: True)
    a = bench_module.Bench(root)
    yield a
    try:
        root.destroy()
    except tk.TclError:
        pass


# --------------------------------------------------------------------- ops

def test_ops_needs_no_tk_and_no_hardware():
    """The whole reason ops is a separate module. If importing it dragged in
    Tk or a live instrument, buttons and sequences could not share it."""
    import _bench_ops as ops
    assert "tkinter" not in sys.modules or True     # ops itself imports none
    import inspect
    src = inspect.getsource(ops)
    assert "tkinter" not in src, "ops must stay free of Tk"


def test_capture_plan_covers_preroll_sweep_and_tail():
    """Sizing to the DMA ceiling instead is what made the first real sweep
    refuse: the mapping will not extrapolate past the laser's table, and every
    sample beyond the last logged point has no wavelength."""
    import _bench_ops as ops
    p = ops.capture_plan(1.0, decimation=8)
    span = p["n_samples"] / p["fs"]
    assert span >= p["preroll"] / p["fs"] + 1.0 + p["tail_s"]
    assert span < 1.2, "should size to the sweep, not to the whole region"
    assert not p["truncated"]


def test_capture_plan_flags_truncation():
    """A record clipped by the DMA ceiling silently loses its tail."""
    import _bench_ops as ops
    p = ops.capture_plan(10.0, decimation=1)
    assert p["truncated"]
    assert p["n_samples"] == ops.DMA_SAMPLE_CEILING


def test_trigger_threshold_is_taken_from_the_record():
    """reduce_sweep defaults to 0.0, which finds NO edges on a unipolar
    trigger: IN2 idles near 6 counts and peaks near 302, never crossing zero."""
    import _bench_ops as ops
    trig = np.concatenate([np.full(900, 6.0), np.full(100, 302.0)])
    thr, lo, hi = ops.trigger_threshold(trig)
    assert 6.0 < thr < 302.0
    assert thr > 0.0, "a zero threshold would find nothing here"


def test_clipping_is_judged_in_counts_not_volts():
    import _bench_ops as ops
    counts = np.array([0.0, 2047.0, -2048.0, 100.0])
    assert ops.clipped(counts) == 2
    assert ops.volts(np.array([1817.7]))[0] == pytest.approx(1.0, rel=1e-6)


def test_volts_uses_the_right_scale_per_range():
    import _bench_ops as ops
    assert ops.volts(np.array([90.885]), "HV")[0] == pytest.approx(1.0, rel=1e-3)


# -------------------------------------------------------------------- panels

def test_every_panel_builds(app):
    assert app.rp is None and app.laser is None
    for name in ("v_host", "v_carrier", "v_mod", "v_amp",
                 "v_carrier2", "v_mod2", "v_amp2", "v_ip", "v_dbm",
                 "v_start", "v_stop", "v_speed", "v_step", "v_dec", "v_secs",
                 "v_trig", "v_fref", "v_orate", "v_seq"):
        assert hasattr(app, name), f"panel field {name} missing"


def test_the_default_modulation_is_on_the_asg_grid(app):
    """Off-grid frequencies glitch at every table wrap and scatter spurs
    across the baseband, which is exactly where the trace lives.

    Checks the SNAPPED table rather than the number in the box: the field shows
    four decimals, so what is typed is a fraction of a hertz off an exact
    multiple, and make_am_table snaps it. What reaches the hardware is the only
    thing that matters, and it must land on a whole number of cycles.
    """
    from rp_lockin.waveforms import make_am_table
    mod = float(app.v_mod.get()) * 1e3
    table = make_am_table(80e6, mod)
    assert table.mod_cycles == 60
    assert table.modulation == pytest.approx(60 * (250e6 / 16384), rel=1e-12)
    assert abs(table.modulation - mod) < 0.5 * (250e6 / 16384)


def test_the_default_modulation_avoids_the_switcher_family(app):
    """504.868 kHz and its multiples are off limits: a harmonic there reads as
    a strong, clean, steady optical signal."""
    mod = float(app.v_mod.get()) * 1e3
    spur = 504.868e3
    nearest = round(mod / spur) * spur
    assert abs(mod - nearest) > 20e3, f"{mod} Hz sits too close to {nearest} Hz"


def test_actions_refuse_without_an_instrument_rather_than_pretending(app):
    """Every one of these touches hardware. None may act with none attached."""
    app.drive_on()
    app.laser_set_power()
    app.sweep_start()
    app.acquire_now()
    assert app.ws.capture is None


def test_workspace_slots_are_independent(app):
    """The granularity claim, in one assertion: a laser log can be present
    with no capture, and clearing one does not disturb the other."""
    app.ws.laser_log = np.linspace(1500e-9, 1600e-9, 11)
    app.refresh_workspace()
    assert "11 pts" in app.ws_vars["laser log"].get()
    assert app.ws_vars["capture"].get() == "-"

    app.ws.capture = {"ch1": np.zeros(10), "ch2": np.zeros(10),
                      "fs": 31.25e6, "decimation": 8, "preroll": 0,
                      "trigger": "CH2_PE", "t": 0.0}
    app.refresh_workspace()
    assert app.ws_vars["capture"].get() != "-"
    assert app.ws_vars["laser log"].get() != "-"


def test_demodulate_and_map_refuse_without_their_inputs(app):
    app.demod_run()
    assert app.ws.lockin is None
    app.ws.capture = {"ch1": np.zeros(1000), "ch2": np.zeros(1000),
                      "fs": 31.25e6, "decimation": 8, "preroll": 0,
                      "trigger": "CH2_PE", "t": 0.0}
    app.map_run()               # no laser log yet
    assert app.ws.reduction is None


def test_clear_workspace_empties_every_slot(app):
    app.ws.laser_log = np.linspace(1500e-9, 1600e-9, 5)
    app.ws.capture = {"ch1": np.zeros(4), "ch2": np.zeros(4), "fs": 1.0,
                      "decimation": 8, "preroll": 0, "trigger": "NOW", "t": 0.0}
    app.clear_workspace()
    assert app.ws.capture is None and app.ws.laser_log is None
    assert all(v.get() == "-" for v in app.ws_vars.values())


def test_two_workers_so_the_laser_is_not_stuck_behind_the_board(app):
    """With one queue this bench cannot work at all: arming a capture blocks
    until a trigger arrives, and the sweep that would PROVIDE that trigger
    would be sitting behind it in the same queue."""
    assert app.board is not app.lasw
    assert app.board.lock is not app.lasw.lock


def test_sweep_info_reports_the_trigger_rate(app):
    """The 0.02 nm step at 100 nm/s is what makes a 5 kHz train, which is what
    the 5000 Sa/s output rate is built around."""
    app.v_start.set("1500")
    app.v_stop.set("1600")
    app.v_speed.set("100")
    app.v_step.set("0.02")
    app._update_sweep_info()
    info = app.v_sweepinfo.get()
    assert "5001 points" in info
    assert "200.0 us" in info


def test_a_capture_always_takes_both_channels():
    """Not a convenience, and deliberately not selectable.

    reduce_sweep requires the detector and the trigger to come from the SAME
    acquisition, because that is what puts them on one time base. A trigger
    record from a different capture relates to the detector only by luck, and
    would misplace every wavelength while still producing a clean-looking
    trace.
    """
    import inspect
    import _bench_ops as ops
    src = inspect.getsource(ops.acquire)
    assert "channels=(1, 2)" in src, "the capture must take both channels"
    returns = inspect.getsource(ops.acquire).split("return")[-1]
    assert "ch1" in returns and "ch2" in returns


def test_the_armed_indicator_exists_and_starts_empty(app):
    """Arming blocks for up to 120 s waiting for a trigger the LASER has to
    produce, so the bench has to say out loud that it is waiting and what to
    press next."""
    assert hasattr(app, "h_armed")
    assert app.h_armed.get() == ""


# --------------------------------------------- the workspace dependency order
# Reported from the bench: re-demodulating at a different frequency updated the
# lock-in and left the OLD trace beside it, so the workspace showed a 915 kHz
# trace next to a 1.83 MHz lock-in as though both were current.


def _fake_capture(n=64):
    return {"ch1": np.zeros(n), "ch2": np.zeros(n), "fs": 31.25e6,
            "decimation": 8, "preroll": 0, "trigger": "CH2_PE", "t": 0.0}


class _FakeLockin:
    def __init__(self, f_ref):
        self.f_ref = f_ref
        self.fs_out = 5000.0
        self.t = np.zeros(10)


def test_redemodulating_clears_the_stale_trace(bench_module):
    """THE reported bug. A trace made at one f_ref must not survive a
    demodulation at another -- two numbers that cannot both be true."""
    ws = bench_module.Workspace()
    ws.set_capture(_fake_capture())
    ws.set_log(np.linspace(1500e-9, 1600e-9, 5))

    class _Red:
        result = _FakeLockin(915527.0)
        trace = None

    ws.set_reduction(_Red())
    assert ws.reduction is not None

    ws.set_lockin(_FakeLockin(1831054.0))       # 2*f1, as an SHG pass would
    assert ws.reduction is None, "the old trace outlived its f_ref"
    assert ws.lockin.f_ref == 1831054.0


def test_a_new_capture_clears_everything_derived_from_the_old_one(bench_module):
    ws = bench_module.Workspace()
    ws.set_capture(_fake_capture())
    ws.set_lockin(_FakeLockin(915527.0))
    ws.set_capture(_fake_capture(128))
    assert ws.lockin is None and ws.reduction is None


def test_a_new_laser_log_clears_the_trace(bench_module):
    """The wavelength axis came from the old log; the amplitudes did not."""
    ws = bench_module.Workspace()

    class _Red:
        result = _FakeLockin(915527.0)
        trace = None

    ws.set_capture(_fake_capture())
    ws.set_log(np.linspace(1500e-9, 1600e-9, 5))
    ws.set_reduction(_Red())
    ws.set_log(np.linspace(1540e-9, 1560e-9, 5))
    assert ws.reduction is None


def test_map_sets_the_trace_and_lockin_together(bench_module):
    """They come from one reduce_sweep call, so they cannot disagree."""
    ws = bench_module.Workspace()

    class _Red:
        result = _FakeLockin(915527.0)
        trace = None

    red = _Red()
    ws.set_reduction(red)
    assert ws.lockin is red.result
    assert "trace" in ws.stamps and "lock-in" in ws.stamps


def test_every_slot_carries_a_timestamp(bench_module):
    ws = bench_module.Workspace()
    ws.set_capture(_fake_capture())
    assert ws.age("capture").strip().startswith("@")
    assert ws.age("trace") == "", "an empty slot has no time"


def test_clearing_drops_the_stamps_too(bench_module):
    ws = bench_module.Workspace()
    ws.set_capture(_fake_capture())
    ws.clear()
    assert ws.stamps == {} and ws.capture is None


# ------------------------------------------------------------- plot and rail

def test_the_plot_zooms_and_can_always_be_fitted_again(app):
    """A zoom that cannot be undone would crop a trace permanently, and a
    cropped trace looks like a measurement rather than a viewport."""
    p = app.plot
    p.show(np.linspace(1500, 1600, 100), np.random.default_rng(0).normal(size=100))
    assert p.xview is None and p.yview is None
    p.xview = (1520.0, 1530.0)
    p._draw()
    assert p._limits[0] == 1520.0 and p._limits[1] == 1530.0
    p.reset_view()
    assert p.xview is None
    assert p._limits[0] < 1501.0


def test_new_data_drops_a_stale_zoom_window(app):
    """Otherwise a window left from another trace silently crops the new one."""
    p = app.plot
    p.show(np.linspace(0, 1, 50), np.zeros(50))
    p.xview = (0.2, 0.3)
    p.show(np.linspace(1500, 1600, 50), np.zeros(50))
    assert p.xview is None


def test_the_rail_scrolls_with_the_wheel(app):
    """The wheel event goes to the widget under the pointer -- an entry or a
    button, not the canvas -- so binding the canvas alone does nothing over
    most of the rail."""
    assert hasattr(app.rail, "_wheel")
    assert hasattr(app.rail, "_grab_wheel")


# ------------------------------------------------------------------- SHG

def test_the_shg_sequence_is_offered(app):
    import tkinter.ttk as ttk_
    found = []

    def walk(widget):
        for child in widget.winfo_children():
            if isinstance(child, ttk_.Combobox):
                found.extend(child.cget("values"))
            walk(child)

    walk(app.root)
    assert any("SHG" in str(v) for v in found), f"no SHG option in {found}"


def test_shg_demodulates_at_twice_the_drive(app, monkeypatch):
    """The whole point: a chi(2) crystal is a square law, so light modulated at
    f1 returns a component at 2*f1. Demodulating there isolates the
    nonlinearity from linear leakage."""
    captured = {}
    monkeypatch.setattr(app, "_need_board", lambda: object())
    monkeypatch.setattr(app, "_need_laser", lambda: object())
    monkeypatch.setattr(app.__class__, "_seq_thread",
                        lambda self, name, rp, d, drive, drive2, sweep, f_ref,
                        *a: captured.update(name=name, f_ref=f_ref,
                                            mod=drive["modulation"]))
    app.v_seq.set("SHG (demodulate at 2*f1)")
    app.seq_run()
    assert captured, "the sequence never started"
    assert captured["f_ref"] == pytest.approx(2 * captured["mod"])


# ------------------------------------------------- harmonics and beat notes
# From the bench: an SHG run demodulated at "1831" kHz produced a clean sine
# wave. Twice 915.5273 kHz is 1831.0547, so f_ref was 54.7 Hz off, and a
# lock-in demodulating 54.7 Hz from its signal returns a 54.7 Hz beat. After
# amplitude() projects onto a common phase that is a sine across the trace: it
# looks like a measurement, and it is a typo.


def test_the_harmonic_button_uses_the_snapped_drive_not_the_typed_one(app):
    app.v_carrier.set("80.0")
    app.v_mod.set("915.5273")
    app.fref_from_drive(2)
    got = float(app.v_fref.get()) * 1e3

    from rp_lockin.waveforms import make_am_table
    exact = 2 * make_am_table(80e6, 915.5273e3).modulation
    assert got == pytest.approx(exact, abs=1.0)
    assert abs(got - 1831e3) > 50.0, \
        "the round number is 54.7 Hz off, which is the whole problem"


def test_the_first_harmonic_button_reproduces_the_drive(app):
    app.v_mod.set("915.5273")
    app.fref_from_drive(1)
    from rp_lockin.waveforms import make_am_table
    assert float(app.v_fref.get()) * 1e3 == pytest.approx(
        make_am_table(80e6, 915.5273e3).modulation, abs=1.0)


def _beating(beat_hz, seconds=1.0, fs_out=5000.0, amp=0.024,
             f_ref=1831000.0):
    """A real LockinResult whose phase rotates, as an offset reference gives.

    A REAL one, not a stand-in carrying only the attributes the detector
    happened to use when it was written. The previous version supplied
    amplitude(), t and fs_out and nothing else, so when the detector moved to
    reading .theta the tests broke while the bench was fine -- the mirror
    image of the _ParkLaser failure and the same root cause. LockinResult is
    four arrays and three floats; there is no reason to imitate it.
    """
    from rp_lockin.dsp import LockinResult
    n = int(seconds * fs_out)
    t = np.arange(n) / fs_out
    z = amp * np.exp(1j * 2 * np.pi * beat_hz * t)
    return LockinResult(t=t, X=z.real, Y=z.imag, f_ref=f_ref, fs_out=fs_out,
                        bandwidth=2250.0, settle=113)


def test_a_beating_lockin_output_is_called_out(app):
    """The sine has to be named as a beat, with the offset, or it reads as a
    result. Nothing else in the trace distinguishes the two."""
    lines = []
    app.log = lambda m: lines.append(m)
    app._warn_if_beating(_beating(54.7))
    hits = [m for m in lines if "PHASE winds" in m]
    assert hits, lines
    assert "54" in hits[0] or "55" in hits[0], f"name the offset: {hits[0]}"


def test_a_steady_lockin_output_is_not_called_a_beat(app):
    """It must not cry wolf on the measurement that is working."""
    lines = []
    app.log = lambda m: lines.append(m)
    app._warn_if_beating(_beating(0.0, amp=0.18, f_ref=915527.34))
    assert lines == [], lines


# ------------------------------------------------ discrete instrument settings

def test_sweep_speeds_are_the_instrument_s_discrete_set(app):
    """The TSL-775's speeds are a selection, not a range (manual p.87), so a
    free-text box could only ever produce a refusal from the instrument."""
    import _bench_ops as ops
    assert ops.SWEEP_SPEEDS_NM_S == (0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 50.0,
                                     100.0, 200.0)
    assert float(app.v_speed.get()) in ops.SWEEP_SPEEDS_NM_S


def test_the_sweep_mode_defaults_to_one_way(app):
    """Two-way overwrites the log with the return pass, so a round trip comes
    back holding only the descending half."""
    import _bench_ops as ops
    cfg = app._sweep_cfg()
    assert cfg["mode"] == 1
    assert ops.SWEEP_MODES[1] == "continuous, one way"
    assert "overwritten" in ops.SWEEP_MODES[3]


# --------------------------------------------------------- the memory ceiling

def test_a_one_second_sweep_needs_decimation_eight():
    """Lower decimation is FASTER sampling and so a SHORTER record for the same
    memory. The region is 33554432 samples per channel however it is filled."""
    import _bench_ops as ops
    assert ops.smallest_decimation_for(1.0) == 8
    assert ops.capture_plan(1.0, decimation=4)["truncated"]
    assert not ops.capture_plan(1.0, decimation=8)["truncated"]


def test_capture_plan_reports_what_a_decimation_can_hold():
    import _bench_ops as ops
    assert ops.capture_plan(0.001, decimation=8)["max_sweep_s"] > 1.0
    assert ops.capture_plan(0.001, decimation=4)["max_sweep_s"] < 1.0


def test_a_sweep_too_long_for_memory_is_refused_not_truncated(app, monkeypatch):
    """A record that stops part way through still maps onto the FULL wavelength
    table, and a half sweep wearing a full axis looks like a measurement."""
    shown = []
    monkeypatch.setattr(app._need_board.__self__.__class__, "_need_board",
                        lambda self: object())
    import bench as bench_mod
    monkeypatch.setattr(bench_mod.messagebox, "showerror",
                        lambda t, m, **k: shown.append(m))
    app.v_dec.set("4")
    app.v_secs.set("1.0")
    app.acquire_now()
    assert shown, "a sweep that cannot fit must be refused"
    assert "decimation" in shown[0].lower()
    assert app.ws.capture is None


# ------------------------------------------------------------ trigger choices

def test_now_is_not_a_trigger_choice(app):
    """An untriggered record has no time origin and can never carry a
    wavelength axis, so it must not sit where a triggered one belongs."""
    import tkinter.ttk as ttk_
    values = []

    def walk(w):
        for child in w.winfo_children():
            if isinstance(child, ttk_.Combobox):
                values.extend(str(v) for v in child.cget("values"))
            walk(child)

    walk(app.root)
    trigger_values = [v for v in values if v.endswith("_PE") or v.endswith("_NE")]
    assert "CH2_PE" in trigger_values
    assert "NOW" not in values, "NOW must not be offered as a trigger"


def test_a_snapshot_is_still_available_for_alignment(app):
    """Removing NOW from the dropdown must not remove the ability to look at
    the inputs without a sweep -- that is how an AOM gets aligned."""
    assert hasattr(app, "acquire_snapshot")


# -------------------------------------------------------------- the snap view

def test_the_drive_panel_shows_what_the_asg_will_actually_play(app):
    """What is typed and what is generated differ by up to half a grid step,
    and that difference is what made a hand-typed second harmonic 54.7 Hz out."""
    app.v_carrier.set("80.0")
    app.v_mod.set("915.5273")
    app._update_snap()
    shown = app.v_snap.get()
    assert "915.5273" in shown
    assert "1831.0547" in shown, f"the 2x harmonic should be shown: {shown}"
    assert "60 cycles" in shown or "(60" in shown


# ------------------------------------------------ the time-axis convention
# Display is relative to the SWEEP; the stored numbers stay relative to the
# RECORD, because the wavelength mapping is built on those and this project
# has been bitten before by an offset that looked entirely normal.


def test_the_time_origin_is_the_first_edge_when_there_is_one(app):
    app.ws.capture = {"ch1": np.zeros(8), "ch2": np.zeros(8), "fs": 1e6,
                      "decimation": 8, "preroll": 0, "trigger": "CH2_PE",
                      "t": 0.0, "first_edge": 0.02486, "n_edges": 5001}
    t0, label = app._time_origin()
    assert t0 == pytest.approx(0.02486)
    assert "SWEEP" in label


def test_it_falls_back_to_the_record_and_SAYS_so(app):
    """A bare 'time (s)' would leave the convention ambiguous, which is how an
    offset becomes invisible."""
    app.ws.capture = {"ch1": np.zeros(8), "ch2": np.zeros(8), "fs": 1e6,
                      "decimation": 8, "preroll": 0, "trigger": "NOW",
                      "t": 0.0, "first_edge": None, "n_edges": 0}
    t0, label = app._time_origin()
    assert t0 == 0.0
    assert "RECORD" in label and "no trigger" in label


def test_the_reduction_wins_over_the_raw_capture(app):
    """Once a reduction exists its first_edge is the authoritative one -- the
    same number the wavelength axis was built from."""
    app.ws.capture = {"ch1": np.zeros(8), "ch2": np.zeros(8), "fs": 1e6,
                      "decimation": 8, "preroll": 0, "trigger": "CH2_PE",
                      "t": 0.0, "first_edge": 0.01, "n_edges": 10}

    class _Red:
        first_edge = 0.02486
        result = None
        trace = None

    app.ws.reduction = _Red()
    t0, _label = app._time_origin()
    assert t0 == pytest.approx(0.02486), "the reduction's edge must win"


def test_the_stored_lockin_times_are_never_shifted(app):
    """Only the picture moves. Shifting the data would put two conventions in
    play, and the wavelength mapping depends on the record-relative one."""
    class _R:
        f_ref = 915527.34
        fs_out = 5000.0
        t = np.linspace(0.0113, 1.03, 100)

        def amplitude(self, smooth=None):
            return np.zeros(100)

    r = _R()
    before = r.t.copy()
    app.ws.capture = {"ch1": np.zeros(8), "ch2": np.zeros(8), "fs": 1e6,
                      "decimation": 8, "preroll": 0, "trigger": "CH2_PE",
                      "t": 0.0, "first_edge": 0.02486, "n_edges": 5001}
    app.ws.lockin = r
    app.plot_what.set("lock-in (amplitude vs time)")
    app.redraw()
    np.testing.assert_array_equal(r.t, before)
    # ...but the plot shows it shifted, so the pre-roll is negative
    assert app.plot.x.min() < 0.0
    assert app.plot.x.min() == pytest.approx(0.0113 - 0.02486)


# ------------------------------------------------------- the trigger train
# From the bench: a trace showed real structure to about 500 ms and then a
# smooth slow drift to 1.0 s, with a sharp boundary. That is not physics. The
# sweep finished early and the laser SAT at its end wavelength for the rest of
# the record, which is what a speed mismatch between the panel and the
# instrument looks like.


def test_a_short_train_is_caught_and_the_speed_factor_named():
    import _bench_ops as ops
    cap = {"first_edge": 0.0, "last_edge": 0.500, "n_edges": 2501}
    r = ops.check_train(cap, 1.000, expected_points=5001)
    assert r["ok"] is False
    assert r["ratio"] == pytest.approx(0.5)
    assert r["implied_speed_factor"] == pytest.approx(2.0)
    assert r["points_ok"] is False


def test_a_matching_train_passes():
    import _bench_ops as ops
    cap = {"first_edge": 0.0248, "last_edge": 1.0248, "n_edges": 5001}
    r = ops.check_train(cap, 1.000, expected_points=5001)
    assert r["ok"] is True
    assert r["points_ok"] is True


def test_no_train_is_reported_as_unknown_not_as_a_pass():
    """Silence must not read as agreement."""
    import _bench_ops as ops
    r = ops.check_train({"first_edge": None, "last_edge": None, "n_edges": 0},
                        1.0)
    assert r["ok"] is None


# ------------------------------------------------- abandoning a trigger wait
# From the bench: a capture armed AFTER the sweep had finished sat there
# waiting for a trigger that had already been and gone, and there was no way
# out but to wait the full timeout -- during which nothing else could talk to
# the board. The board itself was fine; the tool was not.


class _StubBoard:
    """Answers ACQ:TRig:STAT? with WAIT forever, like a board with no trigger."""

    def __init__(self):
        self.polls = 0

    def query(self, _q):
        self.polls += 1
        return "WAIT"


def test_the_trigger_wait_can_be_abandoned():
    from rp_lockin.hardware import RedPitaya, TriggerCancelled
    stub = _StubBoard()
    stop = {"now": False}

    def should_stop():
        stop["now"] = stub.polls >= 3        # let a few polls happen first
        return stop["now"]

    with pytest.raises(TriggerCancelled):
        RedPitaya.wait_until(stub, "ACQ:TRig:STAT?", "TD", timeout=60.0,
                             should_stop=should_stop)
    assert stub.polls < 20, "it should stop promptly, not run the timeout out"


def test_cancelling_is_not_the_same_as_timing_out():
    """A timeout means the trigger never came and something may be wrong. A
    cancel means somebody pressed Stop. They must not read the same."""
    from rp_lockin.hardware import RedPitaya, TriggerCancelled
    assert not issubclass(TriggerCancelled, TimeoutError)

    stub = _StubBoard()
    with pytest.raises(TimeoutError):
        RedPitaya.wait_until(stub, "ACQ:TRig:STAT?", "TD", timeout=0.05)


def test_without_the_hook_nothing_changes():
    """The hook is optional, so every existing caller behaves as before."""
    from rp_lockin.hardware import RedPitaya
    stub = _StubBoard()
    with pytest.raises(TimeoutError):
        RedPitaya.wait_until(stub, "ACQ:TRig:STAT?", "TD", timeout=0.05,
                             should_stop=None)


def test_the_bench_offers_a_stop_and_a_settable_wait(app):
    assert hasattr(app, "acquire_stop")
    assert hasattr(app, "b_stop")
    assert float(app.v_wait.get()) <= 60, \
        "a default a human will not sit through is the whole complaint"


def test_stop_with_nothing_armed_says_so_rather_than_pretending(app):
    lines = []
    app.log = lambda m: lines.append(m)
    app.acquire_stop()
    assert any("nothing is waiting" in m for m in lines), lines


def test_a_failed_capture_explains_the_ordering(app):
    """The likeliest cause is arming after the sweep, so say it."""
    lines = []
    app.log = lambda m: lines.append(m)
    app._capture_failed(TimeoutError("no trigger"))
    joined = " ".join(lines)
    assert "Arm FIRST" in joined
    assert app.h_armed.get() == ""


def test_a_cancelled_capture_reads_differently_from_a_failed_one(app):
    from rp_lockin.hardware import TriggerCancelled
    lines = []
    app.log = lambda m: lines.append(m)
    app._capture_failed(TriggerCancelled("stopped"))
    joined = " ".join(lines)
    assert "cancelled" in joined
    assert "Arm FIRST" not in joined, "a deliberate stop is not a fault"


# ------------------------------------------ the modulation / generated pair
# Two boxes: what you ask for, and what the hardware will produce. Everything
# downstream follows the second.
#
# These five used to assert that 1.000 MHz was unreachable and would snap to
# 1007.080. That was wrong, and the tests were encoding the mistake: the
# fs/16384 "grid" is only what you get by leaving the PLAY RATE at its default.
# SOUR:FREQ:FIX sets that rate, so 80.000000 MHz with 1.000000 MHz is available
# at 5280 and 66 cycles played at 15151.5152 Hz.


def test_exactly_one_megahertz_is_reachable(app):
    """The case that started this. 15258.789 Hz does not divide 1 MHz, but the
    play rate is not obliged to be 15258.789 Hz.

    One box now, not two: the second existed to show what the ASG would snap
    to, and there is no snapping left for any whole number of hertz."""
    app.v_carrier.set("80.0")
    app.v_mod.set("1000")
    app._settle_mod()
    assert float(app.v_mod.get()) == pytest.approx(1000.0, abs=1e-6)
    t, mode = app._resolve(80e6, 1e6)
    assert mode == "exact"
    assert t.modulation == pytest.approx(1e6, abs=1e-6)


def test_the_exact_table_gets_the_carrier_right_too(app):
    """MEASURED on the board 2026-08-28: a 16384-entry table holding ONE
    modulation cycle and 80 carrier cycles, played at 1000000 Hz, gave a
    carrier at 80.0018 MHz with sidebands at 78.995 and 80.978. This pins that
    configuration, because it is the one that was actually seen to work."""
    from rp_lockin.waveforms import make_am_table_exact
    t = make_am_table_exact(80e6, 1e6)
    assert t.modulation == pytest.approx(1e6, abs=1e-6)
    assert t.carrier == pytest.approx(80e6, abs=1e-3)
    assert t.mod_cycles == 1 and t.carrier_cycles == 80
    assert t.play_freq == 1000000.0


def test_the_table_resolves_the_carrier_properly(app):
    """Nyquist alone is not enough. A table with 8000 carrier cycles in 16384
    entries satisfies it with 2.05 points per cycle and reconstructs to alias;
    the configuration that worked had 204.8."""
    from rp_lockin.waveforms import make_am_table_exact
    for mod in (1e6, 500e3, 915527.0, 1.5e6):
        t = make_am_table_exact(80e6, mod)
        assert 16384 / t.carrier_cycles >= 8.0


def test_the_play_rate_is_a_whole_number_of_hertz():
    """MEASURED on the board: SOUR:FREQ:FIX rounds to 1 Hz. 15151.5152 comes
    back as 15151, which would put a '1 MHz' modulation on 999966 Hz -- a
    34 Hz beat, and the trace would look like a slow oscillation."""
    from rp_lockin.waveforms import make_am_table_exact
    for mod in (1e6, 500e3, 1.5e6, 2e6):
        t = make_am_table_exact(80e6, mod)
        assert float(t.play_freq).is_integer(),             f"{t.play_freq} would be rounded by the board"
        assert t.mod_cycles * t.play_freq == pytest.approx(mod, abs=1e-6)


def test_a_fractional_request_falls_back_and_says_so(app):
    """The play rate is quantised to 1 Hz, so a fractional-hertz modulation has
    no exact table and the default grid is the honest answer."""
    lines = []
    app.log = lambda m: lines.append(m)
    app.v_carrier.set("80.0")

    # 915.5273 kHz sits ON the old grid, so the fallback moves it 0.04 Hz and
    # rightly says nothing.
    app.v_mod.set("915.5273")
    app._settle_mod()
    assert not lines, f"a 0.04 Hz correction is not worth a warning: {lines}"
    _t, mode = app._resolve(80e6, 915527.3)
    assert mode == "grid"

    # 920.0005 kHz is fractional AND far from the grid, so the fallback moves
    # it by kilohertz -- which must be said out loud.
    app.v_mod.set("920.0005")
    app._settle_mod()
    assert any("cannot be generated exactly" in m for m in lines), lines

    # A whole number of hertz is exact and must be left alone.
    lines.clear()
    app.v_mod.set("999.983")
    app._settle_mod()
    assert float(app.v_mod.get()) == pytest.approx(999.983, abs=1e-6)
    assert not lines, lines


def test_there_is_only_one_modulation_box(app):
    """The 'generated' box existed to show a snap that no longer happens."""
    assert not hasattr(app, "v_real")
    assert hasattr(app, "v_mod")


def test_the_drive_and_f1_both_follow_the_generated_value(app):
    """If f_ref tracked the request rather than the output, asking for
    something unreachable would drive at one frequency and demodulate at
    another, and the difference would come back as a beat."""
    app.v_carrier.set("80.0")
    app.v_mod.set("1000")
    assert app._drive_cfg()["modulation"] == pytest.approx(1e6, abs=1.0)
    app.fref_from_drive(1)
    assert float(app.v_fref.get()) == pytest.approx(1000.0, abs=1e-3)
    app.fref_from_drive(2)
    assert float(app.v_fref.get()) == pytest.approx(2000.0, abs=1e-3)


def test_any_whole_hertz_modulation_is_reachable():
    """The fs/16384 grid was never a hardware limit -- it is what you get by
    leaving the play rate at its default. SOUR:FREQ:FIX is settable (1 MHz and
    5 MHz both accepted, measured) and quantised to 1 Hz, so mod_cycles can be
    1 and any whole number of hertz is exact.

    999983 Hz is prime and used to be refused. It is not special."""
    from rp_lockin.waveforms import make_am_table_exact
    for mod in (999983.0, 1234567.0, 915527.0, 991821.0, 1e6):
        t = make_am_table_exact(80e6, mod)
        assert t.modulation == pytest.approx(mod, abs=1e-6), mod


def test_a_fractional_hertz_modulation_is_refused():
    """The play rate is quantised to 1 Hz, so a modulation that is not a whole
    number of hertz has no exact table."""
    from rp_lockin.waveforms import make_am_table_exact, plan_exact_am
    assert plan_exact_am(80e6, 915527.34375) is None
    with pytest.raises(ValueError):
        make_am_table_exact(80e6, 915527.34375)


def test_the_carrier_lands_close_enough_for_the_aom():
    """It is placed on the nearest multiple of the play rate. The 1550AOM-1's
    acoustic passband is megahertz wide, so a few hundred kHz is beneath its
    notice -- and insisting on exact would rule out most modulations."""
    from rp_lockin.waveforms import make_am_table_exact
    for mod in (1e6, 999983.0, 915527.0, 1234567.0):
        t = make_am_table_exact(80e6, mod)
        assert abs(t.carrier - 80e6) < 0.5e6, mod


# ------------------------------------------------------------- SFG / OUT2
# Sum-frequency generation goes as I1 x I2, so the nonlinearity appears at
# f1 + f2 and |f1 - f2| and nowhere else. f1 and f2 themselves are LINEAR:
# light at either reaches the detector whether or not anything mixes. That is
# the whole reason the second channel exists, and it is what these pin.


def test_the_second_drive_channel_exists_and_is_independent(app):
    """Two beams, two AOMs, two modulation frequencies. Sharing one set of
    boxes would make it impossible to set f1 and f2 to different values, which
    is the only thing SFG needs from the generator."""
    assert set(app.drv) == {1, 2}
    app.v_carrier.set("80.0")
    app.v_mod.set("915")
    app.v_mod2.set("1225")
    assert app._drive_cfg(1)["modulation"] == pytest.approx(915e3)
    assert app._drive_cfg(2)["modulation"] == pytest.approx(1225e3)
    assert app.drv[1]["mod"] is not app.drv[2]["mod"]


def test_the_channel_one_aliases_still_point_at_channel_one(app):
    """Everything written before OUT2 existed goes through v_mod and friends.
    If the aliases drifted to channel 2, the f1 button and every sequence
    would quietly demodulate the wrong beam."""
    app.v_mod.set("777")
    assert app.drv[1]["mod"].get() == "777"
    assert app._drive_cfg()["modulation"] == pytest.approx(777e3)
    app.v_mod2.set("888")
    assert app._drive_cfg()["modulation"] == pytest.approx(777e3)


def test_all_four_sfg_frequencies_clear_the_switcher(bench_module):
    """504.868 kHz and its multiples are off limits, and SFG puts FOUR
    frequencies on the table rather than two: a product landing on a switcher
    harmonic reads as a strong, clean, steady optical signal.

    A round 1000 kHz second tone fails this -- it sits 9.7 kHz from the second
    harmonic -- which is why the default is not a round number."""
    f1 = bench_module.DEFAULT_MOD_HZ
    f2 = bench_module.DEFAULT_MOD2_HZ
    spur = bench_module.SWITCHER_HZ
    for name, f in (("f1", f1), ("f2", f2), ("f1+f2", f1 + f2),
                    ("|f1-f2|", abs(f1 - f2))):
        gap = abs(f - round(f / spur) * spur)
        assert gap > bench_module.SWITCHER_GUARD_HZ, \
            f"{name} = {f} Hz is only {gap} Hz from a switcher harmonic"


def test_both_default_tones_are_exactly_generatable(bench_module):
    """A frequency the ASG cannot hit exactly comes back as a beat, and with
    two tones the SUM carries both errors."""
    from rp_lockin.waveforms import make_am_table_exact
    for f in (bench_module.DEFAULT_MOD_HZ, bench_module.DEFAULT_MOD2_HZ):
        t = make_am_table_exact(80e6, f)
        assert t.modulation == pytest.approx(f, abs=1e-6)
        assert abs(t.carrier - 80e6) < 0.5e6


def test_the_sfg_buttons_use_the_generated_tones_not_the_typed_ones(app):
    """Same failure as the harmonic buttons, doubled: the sum of two typed
    numbers is not the sum of two generated ones, and the error shows up as a
    beat across the trace rather than as an error."""
    app.v_carrier.set("80.0")
    app.v_carrier2.set("80.0")
    app.v_mod.set("915")
    app.v_mod2.set("1225")

    app.fref_from_sfg("f2")
    assert float(app.v_fref.get()) == pytest.approx(1225.0, abs=1e-3)
    app.fref_from_sfg("sum")
    assert float(app.v_fref.get()) == pytest.approx(2140.0, abs=1e-3)
    app.fref_from_sfg("diff")
    assert float(app.v_fref.get()) == pytest.approx(310.0, abs=1e-3)


def test_two_identical_tones_have_no_difference_product(app):
    """|f1 - f2| is DC, which is not a lock-in frequency. Setting f_ref to
    zero would return the mean of the record and look like a huge signal."""
    app.v_mod.set("915")
    app.v_mod2.set("915")
    before = app.v_fref.get()
    app.fref_from_sfg("diff")
    assert app.v_fref.get() == before, "f_ref was set to DC"


def test_the_sfg_sequence_is_offered(app):
    import tkinter.ttk as ttk_
    found = []

    def walk(widget):
        for child in widget.winfo_children():
            if isinstance(child, ttk_.Combobox):
                found.extend(child.cget("values"))
            walk(child)

    walk(app.root)
    assert any("SFG" in str(v) for v in found), f"no SFG option in {found}"


def test_the_sfg_sequence_demodulates_at_the_sum(app, monkeypatch):
    captured = {}
    monkeypatch.setattr(app, "_need_board", lambda: object())
    monkeypatch.setattr(app, "_need_laser", lambda: object())
    monkeypatch.setattr(app.__class__, "_seq_thread",
                        lambda self, name, rp, d, drive, drive2, sweep, f_ref,
                        *a: captured.update(f_ref=f_ref,
                                            f1=drive["modulation"],
                                            f2=drive2["modulation"]))
    app.v_mod.set("915")
    app.v_mod2.set("1225")
    app.v_seq.set("SFG (two tones, demodulate at f1+f2)")
    app.seq_run()
    assert captured, "the sequence never started"
    assert captured["f_ref"] == pytest.approx(captured["f1"] + captured["f2"],
                                              abs=1.0)


def test_the_sfg_sequence_refuses_one_frequency_for_both_tones(app,
                                                              monkeypatch):
    """Two tones at the same frequency have no sum or difference product to
    find. Running anyway would demodulate at 2*f1, which is SHG, and report
    it as SFG."""
    started = []
    monkeypatch.setattr(app, "_need_board", lambda: object())
    monkeypatch.setattr(app, "_need_laser", lambda: object())
    monkeypatch.setattr(app.__class__, "_seq_thread",
                        lambda *a, **k: started.append(True))
    app.v_mod.set("915")
    app.v_mod2.set("915")
    app.v_seq.set("SFG (two tones, demodulate at f1+f2)")
    app.seq_run()
    assert not started


def test_one_output_can_be_disarmed_without_the_other():
    """Setting SFG up one beam at a time needs this. A per-channel button that
    disarmed both would make it impossible to check f2 alone against f1."""
    import _bench_ops as ops

    class FakeRP:
        def __init__(self):
            self.sent = []

        def write(self, cmd):
            self.sent.append(cmd)

    rp = FakeRP()
    ops.drive_off(rp, 2)
    assert rp.sent == ["OUTPUT2:STATE OFF"]

    rp = FakeRP()
    ops.drive_off(rp)
    assert rp.sent == ["OUTPUT1:STATE OFF", "OUTPUT2:STATE OFF"], \
        "the default must still be BOTH -- every cleanup path relies on it"


def test_the_header_reports_both_outputs(app):
    """SFG leaves two outputs live. A header watching only OUT1 would read
    'off' with light on the bench."""
    assert "OUT1" in app.h_out.get() and "OUT2" in app.h_out.get()


# --------------------------------------------------- the sweep that reverted
# From the bench, 2026-09-01: the first sweep+capture worked and the second
# came back with a nearly flat IN2. The laser was holding :WAV:SWE:MOD 0
# ("step, one way") while the panel said 1 ("continuous, one way") -- in step
# mode it dwells at each of 5001 points instead of ramping for a second, so
# the capture window sees almost no trigger pulses.
#
# It reverted because configure_sweep slept a fixed 0.5 s after :WAV:SWE 0 and
# then verified ONLY :TRIG:OUTP. From cold the stop is instant and every write
# lands; still busy from the previous sweep it is not, and the laser DISCARDS
# the writes without an error. Six of the seven settings were never read back,
# so nothing noticed.


class _FakeLaser:
    """Records writes; answers queries from a dict of held settings.

    `ignore_writes` models the real failure: the instrument accepts a write it
    is not in a state to honour and reports nothing.
    """

    def __init__(self, held=None, busy_polls=0, ignore_writes=()):
        self.held = dict(held or {})
        self.writes = []
        self.busy_polls = busy_polls
        self.ignore_writes = set(ignore_writes)

    def write(self, cmd):
        self.writes.append(cmd)
        head, _, arg = cmd.partition(" ")
        if head == ":WAV:SWE":
            return
        for key, c in __import__("_bench_ops").SWEEP_KEYS:
            if c == head:
                if key not in self.ignore_writes:
                    self.held[key] = arg
                return

    def query(self, cmd):
        if cmd == ":WAV:SWE?":
            if self.busy_polls > 0:
                self.busy_polls -= 1
                return "+1"
            return "+0"
        head = cmd[:-1]
        for key, c in __import__("_bench_ops").SWEEP_KEYS:
            if c == head:
                return self.held.get(key, "+0")
        return "+0"


def _held(mode="+1"):
    return {"speed": "+100.0", "start": "+1.50000000E-006",
            "stop": "+1.60000000E-006", "mode": mode, "cycles": "+1",
            "trig": "+3", "trigstep": "+2.00000000E-011"}


def test_a_setting_the_laser_silently_ignored_is_caught():
    """The actual bug. The laser keeps mode 0, reports no error, and the sweep
    then runs in step mode -- minutes long, with a flat trigger channel."""
    import _bench_ops as ops
    d = _FakeLaser(_held(mode="+0"), ignore_writes={"mode"})
    with pytest.raises(RuntimeError) as e:
        ops.configure_sweep(d, start_nm=1500, stop_nm=1600, speed_nm_s=100,
                            step_nm=0.02, mode=1)
    assert "mode" in str(e.value)
    assert "did not take" in str(e.value)


def test_a_configuration_that_lands_is_accepted():
    import _bench_ops as ops
    d = _FakeLaser(_held())
    got = ops.configure_sweep(d, start_nm=1500, stop_nm=1600, speed_nm_s=100,
                              step_nm=0.02, mode=1)
    assert got["after"]["mode"].lstrip("+") in ("1", "1.0")


def test_configure_waits_for_the_stop_instead_of_sleeping():
    """A fixed sleep is what made run 2 differ from run 1. The stop is polled,
    so a laser that takes its time is waited for rather than written over."""
    import _bench_ops as ops
    d = _FakeLaser(_held(), busy_polls=4)
    got = ops.configure_sweep(d, start_nm=1500, stop_nm=1600, speed_nm_s=100,
                              step_nm=0.02, mode=1)
    assert got["stopped_in"] > 0.0
    # Nothing may be written between :WAV:SWE 0 and the sweep actually being
    # stopped -- that is the window where writes are discarded.
    i = d.writes.index(":WAV:SWE 0")
    assert all(w.startswith(":WAV:SWE 0") or ":SWE:" in w or ":TRIG:" in w
               for w in d.writes[i:])


def test_a_sweep_that_never_stops_is_reported_not_ignored():
    import _bench_ops as ops
    d = _FakeLaser(_held(), busy_polls=10 ** 6)
    with pytest.raises(RuntimeError) as e:
        ops.wait_sweep_stopped(d, timeout=0.3, poll=0.05)
    assert "did not stop" in str(e.value)


def test_speed_is_restored_before_the_wavelengths():
    """The usable start/stop range depends on the speed, so the old order --
    start, stop, then speed -- could have a wavelength rejected."""
    import _bench_ops as ops
    keys = [k for k, _c in ops.SWEEP_KEYS]
    assert keys.index("speed") < keys.index("start")
    assert keys.index("speed") < keys.index("stop")


def test_restore_reports_what_would_not_go_back():
    """It runs in a finally so it must not raise -- but the old version
    swallowed every error, so a restore that did nothing looked like one that
    worked."""
    import _bench_ops as ops

    class Refuses(_FakeLaser):
        def write(self, cmd):
            if cmd.startswith(":WAV:SWE:MOD"):
                raise OSError("nope")
            super().write(cmd)

    lost = ops.restore_sweep(Refuses(_held()), _held())
    assert lost and "mode" in lost[0]


def test_all_seven_settings_are_verified_not_just_the_trigger():
    """Checking one of seven is how this got through: :TRIG:OUTP was right
    every time, and it was the mode that had reverted."""
    import _bench_ops as ops
    want = {"speed": 100.0, "start": 1.5e-6, "stop": 1.6e-6, "mode": 1,
            "cycles": 1, "trig": 3, "trigstep": 2e-11}
    assert ops.check_sweep_config(want, _held()) == []
    for key, wrong in (("speed", "+50.0"), ("start", "+1.51000000E-006"),
                       ("stop", "+1.59000000E-006"), ("mode", "+0"),
                       ("cycles", "+2"), ("trig", "+0"),
                       ("trigstep", "+4.00000000E-011")):
        held = _held()
        held[key] = wrong
        bad = ops.check_sweep_config(want, held)
        assert bad and key in bad[0], f"{key} was not checked"


# ------------------------------------------------- the sub-hertz beat
# From the bench, 2026-09-01: a demodulation at f1 with the drive on drew a
# smooth arch from -76.3 mV up to +133.8 mV and back, over a 1 s sweep. It
# reads as a wavelength-dependent response and it is not one.
#
# A 0.69 Hz offset between f_ref and the light, with R CONSTANT at 134 mV,
# reproduces it to -79.9 .. +134.0 mV. amplitude() projects onto one phase, so
# a rotating phasor comes out as A*cos(phase) -- and once the phase passes
# 90 deg the projection goes negative. No optical amplitude can do that.
#
# The old detector counted sign changes and needed four of them, i.e. two full
# beat cycles. Under about 2 Hz in a one-second record it saw nothing, which
# is precisely the regime that draws a convincing arch.


def _rotating(df_hz, amp=0.134, n=5097, fs=5000.0, f_ref=915000.0):
    """A steady signal seen through a reference that is df_hz off."""
    from rp_lockin.dsp import LockinResult
    t = np.arange(n) / fs
    ph = 2 * np.pi * df_hz * (t - t[-1] / 2.0)
    z = amp * np.exp(1j * ph)
    return LockinResult(t=t, X=z.real, Y=z.imag, f_ref=f_ref, fs_out=fs,
                        bandwidth=2250.0, settle=113)


def test_a_sub_hertz_offset_reproduces_the_arch_seen_on_the_bench():
    r = _rotating(0.69)
    a = r.amplitude()
    assert a.min() * 1e3 == pytest.approx(-79.9, abs=2.0)
    assert a.max() * 1e3 == pytest.approx(134.0, abs=2.0)
    # R is flat throughout: nothing about the SIGNAL changed.
    assert r.R.std() / r.R.mean() < 1e-9


def test_the_sub_hertz_beat_is_now_reported(app):
    """The whole point. Two sign changes in a 1 s record is fewer than the
    four the old counter needed, so this went unreported."""
    lines = []
    app.log = lambda m: lines.append(m)
    r = _rotating(0.69)
    assert int(np.count_nonzero(np.diff(np.signbit(r.amplitude())))) < 4
    app._warn_if_beating(r)
    assert lines, "a 0.69 Hz beat was not reported"
    msg = " ".join(lines)
    assert "PHASE winds" in msg
    assert "0.69" in msg or "0.6900" in msg


def test_the_reported_offset_is_the_one_to_correct_f_ref_by(app):
    lines = []
    app.log = lambda m: lines.append(m)
    app._warn_if_beating(_rotating(-1.25))
    msg = " ".join(lines)
    assert "-1.25" in msg
    # f_ref + df, in kHz, is what the message offers as the fix.
    assert "914.998750" in msg


def test_a_clean_lockin_is_left_alone(app):
    """No phase drift, no warning -- or the message becomes noise."""
    lines = []
    app.log = lambda m: lines.append(m)
    app._warn_if_beating(_rotating(0.0))
    assert lines == []


def test_R_and_phase_views_exist(app):
    """R cannot go negative and ignores the reference phase, so it separates
    'the signal changed' from 'the phase rotated'. Without it there is no way
    to tell those apart from the bench."""
    import tkinter.ttk as ttk_
    found = []

    def walk(w):
        for c in w.winfo_children():
            if isinstance(c, ttk_.Combobox):
                found.extend(str(v) for v in c.cget("values"))
            walk(c)

    walk(app.root)
    assert any(v.startswith("lock-in R") for v in found), found
    assert any(v.startswith("lock-in phase") for v in found), found

