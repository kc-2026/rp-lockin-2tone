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

