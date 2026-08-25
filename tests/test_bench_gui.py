"""
Smoke tests for scripts/bench_gui.py.

A GUI is easy to leave untested and easy to break, and this one can drive the
physical outputs, so the parts worth pinning are the wiring and the safety
gates rather than the pixels:

  * every tab builds,
  * the simulate -> demodulate path produces a real trace with no hardware,
  * writes to the laser are refused while the gate is unticked,
  * closing the window disarms the outputs.

Skipped wholesale when Tk cannot open a display, so a headless machine does not
report a failure it cannot help.
"""

import importlib.util
import os
import sys

import numpy as np
import pytest

tk = pytest.importorskip("tkinter")

_GUI = os.path.join(os.path.dirname(__file__), "..", "scripts", "bench_gui.py")


@pytest.fixture(scope="module")
def gui_module():
    spec = importlib.util.spec_from_file_location("bench_gui", _GUI)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["bench_gui"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def app(gui_module, monkeypatch):
    """A live BenchGui with the modal dialogs stubbed out."""
    try:
        root = tk.Tk()
    except tk.TclError as exc:                      # pragma: no cover
        pytest.skip(f"no display for Tk: {exc}")
    root.withdraw()
    calls = {"warning": [], "error": [], "info": [], "ok": []}
    monkeypatch.setattr(gui_module.messagebox, "showwarning",
                        lambda t, m, **k: calls["warning"].append((t, m)))
    monkeypatch.setattr(gui_module.messagebox, "showerror",
                        lambda t, m, **k: calls["error"].append((t, m)))
    monkeypatch.setattr(gui_module.messagebox, "showinfo",
                        lambda t, m, **k: calls["info"].append((t, m)))
    monkeypatch.setattr(gui_module.messagebox, "askokcancel",
                        lambda t, m, **k: calls["ok"].append((t, m)) or True)
    a = gui_module.BenchGui(root)
    a.dialogs = calls
    yield a
    try:
        root.destroy()
    except tk.TclError:
        pass


def settle(app, timeout=90.0):
    """Run the Tk loop until the worker is idle and its results are drained."""
    import time as _t
    deadline = _t.monotonic() + timeout
    while _t.monotonic() < deadline:
        app.root.update()
        if (not app.worker.busy and app.worker.jobs.empty()
                and app.results.empty()):
            app.root.update()
            return
        _t.sleep(0.01)
    raise AssertionError("worker did not finish in time")


def test_every_tab_builds(app):
    labels = [app.nb.tab(i, "text") for i in range(app.nb.index("end"))]
    assert labels == ["Board", "Outputs", "Acquire", "Demodulate", "Laser",
                      "Log"]


def test_simulate_then_demodulate_produces_a_trace(app, gui_module):
    """The whole no-hardware path, which is what makes this GUI testable."""
    app.sim_ms.set("60")
    app.decim.set("16")
    app.simulate()
    settle(app)
    assert 1 in app.st.raw and 2 in app.st.raw
    assert app.st.raw[1].size == pytest.approx(0.060 * 250e6 / 16, rel=1e-6)

    app.demod()
    settle(app)
    res = app.st.result
    assert res is not None
    # 60 ms at 5000 Sa/s is 300 points before the filter's settling and group
    # delay are trimmed; it must come out shorter, and not by everything.
    assert 0 < res.t.size < 300
    # The f_ref box is human-editable text, so it cannot be bit-exact against
    # the plan. It must still be the PLAN's frequency and not the round number:
    # 1 mHz of tolerance passes the displayed value and fails 1e6 by 8 kHz.
    assert res.f_ref == pytest.approx(gui_module.PLAN.difference, abs=1e-3)
    assert np.all(np.isfinite(res.amplitude()))


def test_the_lockin_frequency_is_not_the_round_number(gui_module):
    """991.821 kHz, not 1 MHz. Hardcoding the round number is a listed trap."""
    assert gui_module.PLAN.difference != pytest.approx(1e6, abs=1.0)
    assert gui_module.PLAN.difference == pytest.approx(991821, abs=1.0)


def test_find_edges_recovers_the_simulated_trigger_train(app):
    app.sim_ms.set("60")
    app.decim.set("16")
    app.simulate()
    settle(app)
    app.find_edges()
    settle(app)
    text = app.logbox.get("1.0", "end")
    assert "edges; first at" in text
    # The simulated train steps every 200 us; anything else means the edge
    # finder or the generator disagree about what a trigger looks like.
    assert "mean step 200." in text


def test_a_laser_write_is_refused_while_the_gate_is_unticked(app):
    class DummyLaser:
        def __init__(self):
            self.written = []

        def write(self, cmd):
            self.written.append(cmd)

        def query(self, cmd):
            return "unused"

    app.st.laser = DummyLaser()
    assert app.allow_writes.get() is False
    app.laser_cmd.set(":WAV 1.55e-6")
    app.laser_send()
    settle(app)
    assert app.st.laser.written == [], "a write escaped the gate"
    assert app.dialogs["warning"], "the user was not told why nothing happened"


def test_a_laser_query_is_allowed_while_the_gate_is_unticked(app):
    class DummyLaser:
        def query(self, cmd):
            return "+1"

    app.st.laser = DummyLaser()
    app.laser_cmd.set(":SYST:COMM:CODE?")
    app.laser_send()
    settle(app)
    assert "'+1'" in app.logbox.get("1.0", "end")


def test_closing_the_window_disarms_the_outputs(app):
    """H7.4 was exactly this failure in a script. A close button is the same
    hazard with a friendlier face."""
    class DummyBoard:
        def __init__(self):
            self.closed = False

        def close(self, disable_outputs=True):
            self.closed = True

    board = DummyBoard()
    app.st.rp = board
    app.on_close()
    assert board.closed, "close() was not called, so outputs may still drive"


def test_outputs_off_is_safe_with_no_board_connected(app):
    app.st.rp = None
    app.st.outputs_on.add(1)
    app.outputs_off()
    settle(app)
    assert app.st.outputs_on == set()


# ------------------------------------------------ the X/Y/R/theta readout

def _demodulated(app):
    app.sim_ms.set("60")
    app.decim.set("16")
    app.simulate()
    settle(app)
    app.demod()
    settle(app)
    return app.st.result


def test_readout_shows_trace_means_until_the_plot_is_hovered(app):
    res = _demodulated(app)
    assert all(v.get() != "--" for v in app.readouts.values())
    assert "mean across all" in app.readout_mode.get()
    assert str(res.t.size) in app.readout_mode.get()


def test_hovering_switches_the_readout_to_a_single_point(app):
    res = _demodulated(app)
    i = res.t.size // 3
    app._cursor_readout(i)
    assert f"point {i} of {res.t.size}" in app.readout_mode.get()
    # theta is the one shown as a plain signed number rather than engineering
    # notation, because degrees are already human-sized.
    assert app.readouts["theta"].get() == f"{res.theta_deg[i]:+.2f}"


def test_leaving_the_plot_returns_the_readout_to_the_means(app):
    _demodulated(app)
    app._cursor_readout(5)
    assert "point 5" in app.readout_mode.get()
    app._cursor_readout(None)
    assert "mean across all" in app.readout_mode.get()


def test_mean_R_is_averaged_not_recomputed_from_mean_X_and_Y(app, gui_module):
    """hypot(mean X, mean Y) is NOT mean R once the response phase moves.

    With a rotating phase the quadratures partly cancel in the mean while R
    does not, so recomputing R from the averaged quadratures reads low -- a
    plausible small number, which is this project's characteristic failure.
    """
    res = _demodulated(app)
    app._cursor_readout(None)
    assert app.readouts["R"].get() == gui_module._eng(float(np.mean(res.R)))


def test_point_R_is_consistent_with_that_point_X_and_Y(app, gui_module):
    """At a single point the two agree, and must -- R is hypot(X, Y) there."""
    res = _demodulated(app)
    i = res.t.size // 2
    app._cursor_readout(i)
    assert app.readouts["R"].get() == gui_module._eng(
        float(np.hypot(res.X[i], res.Y[i])))


def test_zoom_window_slices_the_record_without_touching_the_stats(app):
    """Whole-record min/max/rms must not change as the zoom slider moves."""
    app.sim_ms.set("60")
    app.decim.set("16")
    app.simulate()
    settle(app)
    app.raw_span.set("full")
    app._redraw_raw()
    full_points = app.raw_plot.y.size
    stats_full = app.acq_info.get().split("|")[0].strip()

    app.raw_span.set("10 us")
    app._redraw_raw()
    assert app.raw_plot.y.size < full_points
    # 10 us at 250/16 MS/s is ~156 samples.
    assert app.raw_plot.y.size == pytest.approx(10e-6 * 250e6 / 16, rel=0.02)
    assert app.acq_info.get().split("|")[0].strip() == stats_full
    assert "showing" in app.acq_info.get()


# ------------------------------------------------------ the spectrum view

def test_spectrum_finds_the_simulated_tone_at_the_plan_frequency(app,
                                                                 gui_module):
    """The point of the view: is the tone where we think it is?

    The emulator puts a single tone at the plan's difference frequency, so the
    FFT peak must land there. A peak somewhere else would mean the generator,
    the sample rate or the plan disagree -- which is exactly what someone would
    open this view to find out.
    """
    app.sim_ms.set("60")
    app.decim.set("16")
    app.sim_noise.set("0.00001")
    app.simulate()
    settle(app)
    app.raw_domain.set("spectrum")
    app._redraw_raw()

    info = app.spec_info.get()
    assert "peak" in info
    peak_khz = float(info.split("peak ")[1].split(" kHz")[0])
    assert peak_khz == pytest.approx(gui_module.PLAN.difference / 1e3,
                                     abs=0.05)
    # And it must agree with the plan to well inside one FFT bin.
    offset = float(info.split("is ")[1].split(" Hz")[0])
    assert abs(offset) < 60.0


def test_spectrum_amplitude_scaling_is_calibrated_in_volts(app):
    """A Hann-windowed FFT needs 2/sum(w), not 1/n.

    Getting it wrong leaves the spectrum's SHAPE right and its numbers
    meaningless, so the reported peak is checked against the amplitude the
    emulator was asked for (0.2 V, before any clipping rescale).
    """
    app.sim_ms.set("60")
    app.decim.set("16")
    app.sim_noise.set("0.0")
    app.simulate()
    settle(app)
    app.raw_domain.set("spectrum")
    app._redraw_raw()
    shown = app.spec_info.get().split(" at ")[1].split("V")[0]
    # _eng renders 0.2 V as "200m". The envelope is Lorentzian so the tone is
    # amplitude-modulated across the record; the peak bin carries less than the
    # full 0.2 V, but it must be the right order rather than out by 2 or by n.
    assert shown.endswith("m")
    assert 1.0 < float(shown[:-1]) < 200.0


def test_switching_back_to_time_clears_the_spectrum_readout(app):
    app.sim_ms.set("60")
    app.decim.set("16")
    app.simulate()
    settle(app)
    app.raw_domain.set("spectrum")
    app._redraw_raw()
    assert app.spec_info.get() != ""
    app.raw_domain.set("time")
    app._redraw_raw()
    assert app.spec_info.get() == ""
