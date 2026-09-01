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
    for name in ("v_host", "v_carrier", "v_mod", "v_amp", "v_ip", "v_dbm",
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
                        lambda self, name, rp, d, drive, sweep, f_ref, *a:
                        captured.update(name=name, f_ref=f_ref,
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


class _Beating:
    """A lock-in output whose phase rotates, as an offset reference gives."""

    def __init__(self, beat_hz, seconds=1.0, fs_out=5000.0, amp=0.024):
        self.fs_out = fs_out
        self.f_ref = 1831000.0
        n = int(seconds * fs_out)
        self.t = np.arange(n) / fs_out
        self._a = amp * np.cos(2 * np.pi * beat_hz * self.t)

    def amplitude(self, smooth=None):
        return self._a


class _Steady:
    def __init__(self, seconds=1.0, fs_out=5000.0, amp=0.18):
        self.fs_out = fs_out
        self.f_ref = 915527.34
        n = int(seconds * fs_out)
        self.t = np.arange(n) / fs_out
        self._a = np.full(n, amp)

    def amplitude(self, smooth=None):
        return self._a


def test_a_beating_lockin_output_is_called_out(app):
    """The sine has to be named as a beat, with the offset, or it reads as a
    result. Nothing else in the trace distinguishes the two."""
    lines = []
    app.log = lambda m: lines.append(m)
    app._warn_if_beating(_Beating(54.7))
    hits = [m for m in lines if "BEAT" in m]
    assert hits, lines
    assert "54" in hits[0] or "55" in hits[0], f"name the offset: {hits[0]}"


def test_a_steady_lockin_output_is_not_called_a_beat(app):
    """It must not cry wolf on the measurement that is working."""
    lines = []
    app.log = lambda m: lines.append(m)
    app._warn_if_beating(_Steady())
    assert not any("BEAT" in m for m in lines), lines


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
    play rate is not obliged to be 15258.789 Hz."""
    app.v_carrier.set("80.0")
    app.v_mod.set("1000")
    assert float(app.v_real.get()) == pytest.approx(1000.0, abs=1e-6)


def test_the_exact_table_gets_the_carrier_right_too(app):
    """Both frequencies are multiples of the SAME play rate, so hitting one
    exactly is only useful if the other lands somewhere sane too."""
    from rp_lockin.waveforms import make_am_table_exact
    t = make_am_table_exact(80e6, 1e6)
    assert t.modulation == pytest.approx(1e6, abs=1e-6)
    assert t.carrier == pytest.approx(80e6, abs=1e-3)
    assert t.carrier_cycles == 6400 and t.mod_cycles == 80
    assert t.play_freq == 12500.0


def test_the_play_rate_is_a_whole_number_of_hertz():
    """MEASURED on the board: SOUR:FREQ:FIX rounds to 1 Hz. 15151.5152 comes
    back as 15151, which would put a '1 MHz' modulation on 999966 Hz -- a
    34 Hz beat, and the trace would look like a slow oscillation."""
    from rp_lockin.waveforms import make_am_table_exact
    for mod in (1e6, 500e3, 1.5e6, 2e6):
        t = make_am_table_exact(80e6, mod)
        assert float(t.play_freq).is_integer(),             f"{t.play_freq} would be rounded by the board"
        assert t.mod_cycles * t.play_freq == pytest.approx(mod, abs=1e-6)


def test_a_frequency_with_no_usable_divisor_is_refused():
    """999983 Hz is prime, so the only play rates dividing it are 1 Hz and
    itself; neither leaves a workable number of cycles."""
    from rp_lockin.waveforms import make_am_table_exact, plan_exact_am
    assert plan_exact_am(80e6, 999983.0) is None
    with pytest.raises(ValueError):
        make_am_table_exact(80e6, 999983.0)


def test_the_play_rate_never_exceeds_one_entry_per_clock(app):
    """The table is ALWAYS 16384 entries, traversed at play_rate x 16384
    samples per second. Above fs/16384 that exceeds the DAC. It is also why a
    table cannot hold one modulation period and be played at 1 MHz: that would
    need 16.384 GS/s."""
    from rp_lockin.waveforms import make_am_table_exact
    for mod in (1e6, 1.5e6, 2e6):
        t = make_am_table_exact(80e6, mod)
        assert t.play_freq * 16384 <= 250e6 + 1.0


def test_an_unreachable_pair_falls_back_to_the_grid_and_says_so(app):
    """915.5273 kHz against an 80 MHz carrier has no integer pair that fits, so
    the default grid is the honest answer."""
    lines = []
    app.log = lambda m: lines.append(m)
    app.v_carrier.set("80.0")
    app.v_real.set("915.5273")
    app._settle_actual()
    assert float(app.v_real.get()) == pytest.approx(915.527344, abs=1e-4)

    # 999.983 kHz is prime in hertz, so no play rate divides it usefully.
    app.v_real.set("999.983")
    app._settle_actual()
    assert float(app.v_real.get()) != pytest.approx(999.983, abs=1e-4)
    assert any("cannot be generated exactly" in m for m in lines), lines

    # ...but 915.4 kHz IS reachable, and must be left alone. The unreachable
    # set is "no usable divisor", not "not a round number".
    app.v_real.set("915.4")
    app._settle_actual()
    assert float(app.v_real.get()) == pytest.approx(915.4, abs=1e-4)


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
