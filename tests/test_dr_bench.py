"""The dynamic-range bench: the analysis, and the plot it needs.

Kept in its own file because `dr_bench.py` is a characterisation tool rather
than part of the measurement path -- it answers one question about the
detector's gain knob and then stops being used. The ANALYSIS is tested hard
anyway, because a wrong noise floor would send the gain to the wrong setting
and every measurement after that inherits it.
"""

import os
import sys

import numpy as np
import pytest

SCRIPTS = os.path.join(os.path.dirname(__file__), "..", "scripts")
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

tk = pytest.importorskip("tkinter")


@pytest.fixture
def wl():
    return np.linspace(1500.0, 1600.0, 5000)


def _sweeps(shape, sigma, n=4, seed=1):
    rng = np.random.default_rng(seed)
    return [shape + rng.normal(0, sigma, shape.size) for _ in range(n)]


# ------------------------------------------------------------ the floor

def test_the_floor_recovers_a_known_sigma(wl):
    """The whole measurement rests on this number. Across-repeat scatter, so
    it needs no idea where the signal is."""
    import _bench_ops as ops
    shape = 0.134 * np.sinc((wl - 1550.0) / 3.0)
    for sigma in (3.57e-6, 50e-6, 500e-6):
        r = ops.trace_dynamic_range(_sweeps(shape, sigma))
        assert r["floor_across"] == pytest.approx(sigma, rel=0.10), sigma


def test_the_floor_does_not_care_about_the_signal(wl):
    """Same noise, wildly different signals -- the floor must not move."""
    import _bench_ops as ops
    sigma = 10e-6
    floors = []
    for shape in (np.zeros(wl.size),
                  0.1 * np.sinc((wl - 1550.0) / 3.0),
                  0.5 * np.exp(-((wl - 1520.0) / 0.5) ** 2)):
        floors.append(ops.trace_dynamic_range(
            _sweeps(shape, sigma))["floor_across"])
    assert max(floors) / min(floors) < 1.15, floors


def test_averaging_lowers_the_reported_floor_by_root_n(wl):
    import _bench_ops as ops
    shape = 0.134 * np.sinc((wl - 1550.0) / 3.0)
    r = ops.trace_dynamic_range(_sweeps(shape, 20e-6, n=9))
    assert r["floor_averaged"] == pytest.approx(r["floor_single"] / 3.0,
                                                rel=1e-9)
    assert r["dr_averaged_db"] == pytest.approx(
        r["dr_single_db"] + 20 * np.log10(3.0), abs=1e-9)


def test_a_single_sweep_falls_back_to_the_off_peak_region(wl):
    """With one sweep there is no scatter to measure. The off-peak rms stands
    in, and is an UPPER bound -- see the tail-ratio tests."""
    import _bench_ops as ops
    shape = 0.134 * np.exp(-((wl - 1550.0) / 1.5) ** 2)
    r = ops.trace_dynamic_range(_sweeps(shape, 8e-6, n=1))
    assert np.isnan(r["floor_across"])
    assert r["floor_single"] == pytest.approx(8e-6, rel=0.15)


# --------------------------------------------------------- the tail ratio

def test_a_compact_signal_gives_a_tail_ratio_near_one(wl):
    """Nothing out in the wings, so the off-peak rms IS the floor."""
    import _bench_ops as ops
    shape = 0.134 * np.exp(-((wl - 1550.0) / 1.5) ** 2)
    r = ops.trace_dynamic_range(_sweeps(shape, 3.57e-6))
    assert 0.7 < r["tail_ratio"] < 1.4, r["tail_ratio"]


def test_a_sinc_gives_a_large_tail_ratio_and_that_is_the_answer(wl):
    """A sinc's tails never stop, so the off-peak region is full of signal.
    That is not a fault -- it is the measurement saying there is real
    structure down in the skirts."""
    import _bench_ops as ops
    shape = 0.134 * np.sinc((wl - 1550.0) / 3.0)
    r = ops.trace_dynamic_range(_sweeps(shape, 3.57e-6))
    assert r["tail_ratio"] > 100, r["tail_ratio"]
    # and the floor itself is still right, which is the point of using
    # across-repeat scatter rather than the off-peak region
    assert r["floor_across"] == pytest.approx(3.57e-6, rel=0.10)


# ------------------------------------------------------- dynamic range

def test_dynamic_range_is_peak_over_floor_in_dB(wl):
    import _bench_ops as ops
    shape = 0.2 * np.sinc((wl - 1550.0) / 3.0)
    r = ops.trace_dynamic_range(_sweeps(shape, 20e-6))
    assert r["peak"] == pytest.approx(0.2, rel=0.01)
    expect = 20 * np.log10(r["peak"] / r["floor_single"])
    assert r["dr_single_db"] == pytest.approx(expect, abs=1e-9)
    assert r["dr_single_db"] == pytest.approx(80.0, abs=1.5)


def test_more_gain_shows_up_as_more_range_until_the_noise_scales_too(wl):
    """The point of the whole exercise. Gain that lifts signal and noise
    equally buys nothing; gain that lifts signal over a fixed board floor
    buys range."""
    import _bench_ops as ops
    shape = np.sinc((wl - 1550.0) / 3.0)
    board = 3.57e-6
    drs = []
    for m in (1.0, 10.0, 100.0):
        # signal scales with M; the board floor does not
        r = ops.trace_dynamic_range(_sweeps(0.001 * m * shape, board))
        drs.append(r["dr_single_db"])
    assert drs[1] > drs[0] + 15 and drs[2] > drs[1] + 15, drs

    flat = []
    for m in (1.0, 10.0, 100.0):
        # detector-limited: noise scales with M too, so nothing is gained
        r = ops.trace_dynamic_range(_sweeps(0.001 * m * shape, 50e-6 * m))
        flat.append(r["dr_single_db"])
    assert max(flat) - min(flat) < 1.5, flat


def test_it_refuses_an_empty_set():
    import _bench_ops as ops
    with pytest.raises(ValueError):
        ops.trace_dynamic_range([])


# ------------------------------------------------------- the mask itself

def test_the_mask_widens_around_the_peak(wl):
    """Without a guard band the skirts of the peak are counted as noise, so
    the floor reads high on exactly the traces with the most signal."""
    import _bench_ops as ops
    shape = np.exp(-((wl - 1550.0) / 0.5) ** 2)
    narrow = ops.find_signal_mask(shape, guard=0).sum()
    wide = ops.find_signal_mask(shape, guard=20).sum()
    assert wide > narrow


def test_pure_noise_flags_almost_nothing_as_signal():
    import _bench_ops as ops
    rng = np.random.default_rng(3)
    mask = ops.find_signal_mask(rng.normal(0, 1e-6, 5000), guard=0)
    assert mask.sum() < 50, mask.sum()


# ------------------------------------------------------------ the plot

def test_the_plot_draws_several_series():
    """The waterfall needs one trace per gain on one pair of axes."""
    from _bench_widgets import Plot
    try:
        root = tk.Tk()
    except tk.TclError as exc:                          # pragma: no cover
        pytest.skip(f"no display: {exc}")
    root.withdraw()
    try:
        p = Plot(root, height=200)
        x = np.linspace(0, 1, 100)
        p.show_many([(x, x), (x, x + 1), (x, x + 2)], "x", "y",
                    labels=["a", "b", "c"])
        assert len(p.series) == 3
        # limits must span every series, not just the first
        _xmin, _xmax, ymin, ymax = p._data_limits()
        assert ymin < 0.1 and ymax > 2.9, (ymin, ymax)
    finally:
        root.destroy()


def test_a_single_series_still_works_the_old_way():
    """bench.py calls show(); it must be unaffected by show_many existing."""
    from _bench_widgets import Plot
    try:
        root = tk.Tk()
    except tk.TclError as exc:                          # pragma: no cover
        pytest.skip(f"no display: {exc}")
    root.withdraw()
    try:
        p = Plot(root, height=200)
        x = np.linspace(0, 1, 50)
        p.show(x, x ** 2, "x", "y")
        assert len(p.series) == 1
        assert p.y[-1] == pytest.approx(1.0)
    finally:
        root.destroy()


def test_the_bench_builds_with_nothing_connected():
    import dr_bench
    try:
        root = tk.Tk()
    except tk.TclError as exc:                          # pragma: no cover
        pytest.skip(f"no display: {exc}")
    root.withdraw()
    try:
        app = dr_bench.DrBench(root)
        assert app.rp is None and app.laser is None
        assert app.points == []
        app.redraw()                     # must not raise with no points
    finally:
        root.destroy()


# ------------------------------------------------------------- the pump
# "connect shows nothing on the log." The workers were never started, AND
# _pump treated the queue items as Job objects when Worker posts
# (kind, payload) tuples. The first result raised AttributeError, the
# exception escaped the loop, and root.after was never rescheduled -- so the
# pump died silently and every button after that did nothing.


def _app():
    import dr_bench
    try:
        root = tk.Tk()
    except tk.TclError as exc:                          # pragma: no cover
        pytest.skip(f"no display: {exc}")
    root.withdraw()
    return dr_bench.DrBench(root), root


def test_the_workers_are_actually_running():
    """A Worker that is never start()ed queues jobs forever and runs none."""
    app, root = _app()
    try:
        assert app.board.is_alive(), "the board worker was never started"
        assert app.lasw.is_alive(), "the laser worker was never started"
    finally:
        root.destroy()


def test_a_job_reaches_its_callback():
    """End to end through the real Worker and the real pump."""
    import time as _t
    app, root = _app()
    got = []
    try:
        app.submit(app.board, "unit test", lambda: 42, lambda v: got.append(v))
        for _ in range(200):
            root.update()
            if got:
                break
            _t.sleep(0.01)
        assert got == [42], "the callback never fired"
    finally:
        root.destroy()


def test_a_failing_job_is_logged_and_does_not_kill_the_pump():
    """The original failure mode: one bad result and nothing works again."""
    import time as _t
    app, root = _app()
    later = []
    try:
        def boom():
            raise RuntimeError("expected")

        app.submit(app.board, "will fail", boom)
        for _ in range(200):
            root.update()
            if "will fail" in app.logbox.get("1.0", "end"):
                break
            _t.sleep(0.01)
        assert "will fail" in app.logbox.get("1.0", "end")

        # and the pump must still be alive afterwards
        app.submit(app.board, "after the failure", lambda: 7,
                   lambda v: later.append(v))
        for _ in range(200):
            root.update()
            if later:
                break
            _t.sleep(0.01)
        assert later == [7], "the pump stopped after a failed job"
    finally:
        root.destroy()


def test_a_raising_callback_does_not_kill_the_pump():
    import time as _t
    app, root = _app()
    later = []
    try:
        app.submit(app.board, "bad callback", lambda: 1,
                   lambda _v: (_ for _ in ()).throw(ValueError("nope")))
        for _ in range(100):
            root.update()
            _t.sleep(0.01)
        app.submit(app.board, "still alive", lambda: 9,
                   lambda v: later.append(v))
        for _ in range(200):
            root.update()
            if later:
                break
            _t.sleep(0.01)
        assert later == [9], "a raising callback killed the pump"
    finally:
        root.destroy()


def test_the_rail_scrolls():
    from _bench_widgets import ScrollFrame
    app, root = _app()
    try:
        assert isinstance(app.rail, ScrollFrame)
    finally:
        root.destroy()

