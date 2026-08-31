#!/usr/bin/env python3
"""
Bench GUI -- a human-driven front end for what this project implements.

Answers Q14, which asked whether a GUI was wanted and what it would show
(deferred 2026-08-14, requested 2026-08-25). It exists so the features can be
exercised by hand rather than only through scripts and pytest: board
connection, front-end settings, the two-tone drive, deep capture, demodulation,
a look at the trace, the CSV deliverable, and the laser link.

    python scripts/bench_gui.py

Tkinter, from the standard library, because this has to run on the bench
Windows box without installing anything. matplotlib is deliberately NOT used --
it is an optional extra and is not currently installed -- so the plot is drawn
on a Tk canvas. Raw records are min/max reduced per pixel column, which keeps a
31-million-sample waveform honest: plotting every Nth sample instead would hide
exactly the narrow features (a trigger pulse, a glitch at a block boundary)
that someone opens a raw record to look for.

SAFETY, and it is not incidental here
-------------------------------------
This is the first thing in the project that lets a human drive an output from a
button, so the safeguards are part of the design rather than bolted on:

  * **Outputs are switched off when the window closes**, on every path. H7.4
    was exactly this failure in a script.
  * **An OUTPUTS OFF button is visible from every tab**, never behind one.
  * **Enabling an output requires confirming a dialog** naming the channel,
    frequencies and amplitude. Nothing enables an output as a side effect.
  * **Laser writes are refused unless "allow writes" is ticked**, which starts
    off. Reads (*IDN?, :READout:*) are always safe and always available; writes
    go somewhere the light goes.
  * **Every command and reply is logged** with a timestamp. On this project an
    unsupported command returns zero bytes exactly like a supported one, so
    "what was actually sent" is the first question in any diagnosis.
  * There is deliberately **no control that restarts the board's SCPI server**.
    That is Kevin's, by request.

All instrument traffic runs on ONE worker thread. That is not only for
responsiveness: the SCPI server wedges when connections are opened per command,
and two threads sharing one socket desynchronise it into returning believable
wrong values rather than errors. Both cost a day each, and are in the log.
"""
from __future__ import annotations

import os
import queue
import sys
import threading
import time
import tkinter as tk
from dataclasses import dataclass, field
from tkinter import filedialog, messagebox, ttk

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
# This directory too, so tsl775 imports whether bench_gui is run as a script
# or imported by the test suite. Without it the GUI tests fail at collection
# and the tab that drives the amplifier goes untested.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from rp_lockin import (  # noqa: E402
    demodulate,
    find_trigger_edges,
    make_trigger_pulses,
    plan_two_tone_grid,
    recommended_preroll,
    recommended_tail,
    reduce_sweep,
    settling_points,
    synthesise_dut_output,
    write_raw_npz,
    write_trace_csv,
)
from rp_lockin.constants import (BASE_SAMPLE_RATE,  # noqa: E402
                                 ADC_COUNTS_PER_V_LV, ADC_COUNT_MAX,
                                 ADC_COUNT_MIN)
from rp_lockin.hardware import RedPitaya  # noqa: E402
from rp_lockin.santec import SantecTSL  # noqa: E402
# Sweep control. santec.py can read the log and set the
# trigger mode, but it has no sweep setters and cannot START
# a sweep; tsl775.py is the proven path for that.
from tsl775 import TSL775  # noqa: E402

PLAN = plan_two_tone_grid(1e6)


# --------------------------------------------------------------- plotting


def _eng(v: float) -> str:
    """Compact number for an axis label."""
    if v is None or not np.isfinite(v):
        return "nan"
    a = abs(v)
    if a == 0:
        return "0"
    if a < 1e-9:
        return f"{v * 1e12:.3g}p"
    if a < 1e-6:
        return f"{v * 1e9:.3g}n"
    if a < 1e-3:
        return f"{v * 1e6:.3g}u"
    if a < 1:
        return f"{v * 1e3:.3g}m"
    if a < 1e3:
        return f"{v:.4g}"
    if a < 1e6:
        return f"{v / 1e3:.4g}k"
    return f"{v / 1e6:.4g}M"


class Plot(tk.Canvas):
    """A minimal line plot. No matplotlib, no dependencies, no zoom.

    Reduces to two points per pixel column -- the min and the max of everything
    falling in it -- so a 31 M-sample record draws quickly AND keeps its narrow
    features. Decimating by stride would drop a 25 us trigger pulse entirely
    and show a clean flat line, which is the wrong kind of wrong.
    """

    PAD_L, PAD_R, PAD_T, PAD_B = 66, 16, 14, 36

    def __init__(self, master, on_cursor=None, **kw):
        super().__init__(master, background="#ffffff", highlightthickness=1,
                         highlightbackground="#c0c0c0", **kw)
        self.x = np.array([])
        self.y = np.array([])
        self.xlabel = ""
        self.ylabel = ""
        # Called with the sample index under the pointer, or None on leaving.
        # Lets the Demodulate tab show X/Y/R/theta at the cursor the way a
        # lock-in's front panel does, without this widget knowing about them.
        self.on_cursor = on_cursor
        self._limits = (0.0, 1.0, 0.0, 1.0)
        self._readout = ""
        # Per-axis tick formatters. _eng is right for volts and seconds, and
        # wrong for a wavelength axis: it renders 1500 nm as "1.5k", which is
        # unreadable when every tick differs in the third digit.
        self.xfmt = None
        self.yfmt = None
        self.bind("<Configure>", lambda _e: self._draw())
        self.bind("<Motion>", self._hover)
        self.bind("<Leave>", lambda _e: self._clear_readout())

    def show(self, x, y, xlabel="", ylabel="", xfmt=None, yfmt=None):
        self.x = np.asarray(x, dtype=float).ravel()
        self.y = np.asarray(y, dtype=float).ravel()
        self.xlabel, self.ylabel = xlabel, ylabel
        self.xfmt, self.yfmt = xfmt, yfmt
        self._draw()

    def clear(self):
        self.x = np.array([])
        self.y = np.array([])
        self._draw()

    # -- internals

    def _box(self):
        w, h = self.winfo_width(), self.winfo_height()
        return self.PAD_L, self.PAD_T, w - self.PAD_R, h - self.PAD_B

    def _draw(self):
        self.delete("all")
        x0, y0, x1, y1 = self._box()
        if x1 <= x0 or y1 <= y0:
            return
        self.create_rectangle(x0, y0, x1, y1, outline="#b0b0b0")
        if self.x.size == 0:
            self.create_text((x0 + x1) / 2, (y0 + y1) / 2, text="no data",
                             fill="#909090")
            return
        if not np.isfinite(self.y).any():
            self.create_text((x0 + x1) / 2, (y0 + y1) / 2,
                             text="every value is NaN", fill="#b00000")
            return

        xmin, xmax = float(self.x[0]), float(self.x[-1])
        if xmax <= xmin:
            xmax = xmin + 1.0
        ymin = float(np.nanmin(self.y))
        ymax = float(np.nanmax(self.y))
        if ymax <= ymin:
            ymin, ymax = ymin - 1e-12, ymax + 1e-12
        pad = 0.05 * (ymax - ymin)
        ymin, ymax = ymin - pad, ymax + pad
        self._limits = (xmin, xmax, ymin, ymax)

        def sy(v):
            return y1 - (v - ymin) / (ymax - ymin) * (y1 - y0)

        for frac in (0.0, 0.25, 0.5, 0.75, 1.0):
            gy = y1 - frac * (y1 - y0)
            self.create_line(x0, gy, x1, gy, fill="#ececec")
            self.create_text(x0 - 6, gy, anchor="e", font=("TkDefaultFont", 7),
                             text=(self.yfmt or _eng)(ymin + frac * (ymax - ymin)))
            gx = x0 + frac * (x1 - x0)
            self.create_line(gx, y0, gx, y1, fill="#ececec")
            self.create_text(gx, y1 + 6, anchor="n", font=("TkDefaultFont", 7),
                             text=(self.xfmt or _eng)(xmin + frac * (xmax - xmin)))

        coords = []
        for px, lo, hi in self._reduce(int(x1 - x0)):
            gx = x0 + px
            coords.extend([gx, sy(hi), gx, sy(lo)])
        if len(coords) >= 4:
            self.create_line(*coords, fill="#1a5fb4", width=1)

        if self.xlabel:
            self.create_text((x0 + x1) / 2, y1 + 21, anchor="n",
                             font=("TkDefaultFont", 8), text=self.xlabel)
        if self.ylabel:
            self.create_text(13, (y0 + y1) / 2, angle=90,
                             font=("TkDefaultFont", 8), text=self.ylabel)
        if self._readout:
            self.create_text(x1 - 5, y0 + 5, anchor="ne", fill="#505050",
                             font=("TkDefaultFont", 8), text=self._readout)

    def _reduce(self, width: int):
        """One (pixel, min, max) triple per column."""
        n = self.y.size
        width = max(1, width)
        if n <= width:
            return [(i / max(1, n - 1) * width, v, v)
                    for i, v in enumerate(self.y) if np.isfinite(v)]
        edges = np.linspace(0, n, width + 1).astype(int)
        out = []
        for px in range(width):
            a, b = edges[px], edges[px + 1]
            if b <= a:
                continue
            seg = self.y[a:b]
            seg = seg[np.isfinite(seg)]
            if seg.size:
                out.append((px, float(seg.min()), float(seg.max())))
        return out

    def _hover(self, event):
        if self.x.size == 0:
            return
        x0, y0, x1, y1 = self._box()
        if not (x0 <= event.x <= x1 and y0 <= event.y <= y1):
            return self._clear_readout()
        xmin, xmax, _ymin, _ymax = self._limits
        xv = xmin + (event.x - x0) / max(1, x1 - x0) * (xmax - xmin)
        i = int(np.clip(np.searchsorted(self.x, xv), 0, self.y.size - 1))
        if self.on_cursor:
            self.on_cursor(i)
        readout = (f"x={(self.xfmt or _eng)(self.x[i])}   "
                   f"y={(self.yfmt or _eng)(self.y[i])}")
        if readout != self._readout:
            self._readout = readout
            self._draw()

    def _clear_readout(self):
        if self.on_cursor:
            self.on_cursor(None)
        if self._readout:
            self._readout = ""
            self._draw()


# ----------------------------------------------------------------- worker


@dataclass
class Job:
    name: str
    fn: object
    on_done: object = None


class Worker(threading.Thread):
    """Serialises every piece of instrument traffic onto one thread."""

    def __init__(self, results: queue.Queue):
        super().__init__(daemon=True)
        self.jobs: queue.Queue = queue.Queue()
        self.results = results
        self.busy = False

    def submit(self, name, fn, on_done=None):
        self.jobs.put(Job(name, fn, on_done))

    def run(self):
        while True:
            job = self.jobs.get()
            self.busy = True
            self.results.put(("busy", job.name))
            try:
                value = job.fn()
                self.results.put(("done", (job, value, None)))
            except Exception as exc:  # surfaced in the UI, never swallowed
                self.results.put(("done", (job, None, exc)))
            finally:
                self.busy = False


# -------------------------------------------------------------------- app


@dataclass
class State:
    rp: object = None
    laser: object = None
    raw: dict = field(default_factory=dict)   # channel -> samples
    fs: float = 0.0
    result: object = None                     # LockinResult
    wavelengths: object = None                # the laser's log, metres, or None
    reduction: object = None                  # SweepReduction, when mapped
    outputs_on: set = field(default_factory=set)


class BenchGui:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.st = State()
        self.results: queue.Queue = queue.Queue()
        self.worker = Worker(self.results)
        self.worker.start()

        root.title("rp-lockin-2tone -- bench")
        root.geometry("1100x780")
        root.minsize(900, 620)
        root.protocol("WM_DELETE_WINDOW", self.on_close)

        self.nb = ttk.Notebook(root)
        self.nb.pack(fill="both", expand=True, padx=6, pady=(6, 0))
        self._build_log()        # first: every other tab may log while building
        self._build_board()
        self._build_outputs()
        self._build_acquire()
        self._build_view()
        self._build_laser()
        self._build_sweep()
        self._reorder_tabs()
        self._build_statusbar()

        self.log("Bench GUI started. Nothing is connected.")
        self.log(f"Plan: f1 {PLAN.f1 / 1e6:.6f} MHz, f2 {PLAN.f2 / 1e6:.6f} "
                 f"MHz, lock-in {PLAN.difference / 1e3:.3f} kHz")
        self.root.after(80, self._pump)

    def _reorder_tabs(self):
        """Log was built first so it could receive messages; it belongs last."""
        self.nb.insert("end", self.tab_log)

    # -- shared

    def _build_statusbar(self):
        bar = ttk.Frame(self.root)
        bar.pack(fill="x", padx=6, pady=6)
        self.status = tk.StringVar(value="idle")
        ttk.Label(bar, textvariable=self.status).pack(side="left")
        self.out_state = tk.StringVar(value="outputs: off")
        self.out_lbl = tk.Label(bar, textvariable=self.out_state)
        self.out_lbl.pack(side="left", padx=18)
        tk.Button(bar, text="OUTPUTS OFF", command=self.outputs_off,
                  background="#c01c28", foreground="white",
                  activebackground="#a01018", activeforeground="white",
                  font=("TkDefaultFont", 9, "bold"), padx=10).pack(side="right")

    def log(self, msg: str):
        stamp = time.strftime("%H:%M:%S")
        self.logbox.configure(state="normal")
        self.logbox.insert("end", f"{stamp}  {msg}\n")
        self.logbox.see("end")
        self.logbox.configure(state="disabled")

    def submit(self, name, fn, on_done=None):
        if self.worker.busy:
            self.log(f"queued: {name} (worker busy)")
        self.worker.submit(name, fn, on_done)

    def _pump(self):
        """Marshal worker results back onto the Tk thread."""
        try:
            while True:
                kind, payload = self.results.get_nowait()
                if kind == "busy":
                    self.status.set(f"working: {payload}")
                elif kind == "done":
                    job, value, exc = payload
                    if exc is not None:
                        self.log(f"FAILED {job.name}: "
                                 f"{exc.__class__.__name__}: {exc}")
                        messagebox.showerror(job.name, str(exc))
                    elif job.on_done:
                        job.on_done(value)
                    self.status.set("idle")
        except queue.Empty:
            pass
        self.root.after(80, self._pump)

    # -- tab: board

    def _build_board(self):
        f = ttk.Frame(self.nb, padding=10)
        self.nb.add(f, text="Board")

        row = ttk.Frame(f)
        row.pack(fill="x")
        ttk.Label(row, text="Host").pack(side="left")
        self.host = tk.StringVar(
            value=os.environ.get("RP_HOST", "rp-fffe42.local"))
        ttk.Entry(row, textvariable=self.host, width=26).pack(side="left",
                                                              padx=6)
        ttk.Button(row, text="Connect", command=self.board_connect).pack(
            side="left")
        ttk.Button(row, text="Disconnect",
                   command=self.board_disconnect).pack(side="left", padx=4)
        ttk.Button(row, text="*IDN?", command=self.board_idn).pack(side="left")

        self.board_status = tk.StringVar(value="not connected")
        ttk.Label(f, textvariable=self.board_status,
                  foreground="#606060").pack(anchor="w", pady=(8, 12))

        box = ttk.LabelFrame(f, text="Front end", padding=8)
        box.pack(fill="x")
        ttk.Label(box, wraplength=780, foreground="#805000",
                  text="Sets BOTH channels the same. The real experiment needs "
                       "them different -- IN1 on LV for the detector, IN2 on "
                       "HV because the laser trigger is 3.3 V. Use the raw "
                       "commands for that.").grid(row=0, column=0, columnspan=7,
                                                  sticky="w", pady=(0, 6))
        self.decim = tk.StringVar(value="8")
        self.coupling = tk.StringVar(value="DC")
        self.gain = tk.StringVar(value="LV")
        ttk.Label(box, text="Decimation").grid(row=1, column=0, sticky="w")
        ttk.Combobox(box, textvariable=self.decim, width=6, state="readonly",
                     values=("1", "2", "4", "8", "16")).grid(row=1, column=1,
                                                             padx=6)
        ttk.Label(box, text="Coupling").grid(row=1, column=2, sticky="w")
        ttk.Combobox(box, textvariable=self.coupling, width=6, state="readonly",
                     values=("DC", "AC")).grid(row=1, column=3, padx=6)
        ttk.Label(box, text="Gain").grid(row=1, column=4, sticky="w")
        ttk.Combobox(box, textvariable=self.gain, width=6, state="readonly",
                     values=("LV", "HV")).grid(row=1, column=5, padx=6)
        ttk.Button(box, text="Apply", command=self.board_front_end).grid(
            row=1, column=6, padx=12)

        box2 = ttk.LabelFrame(f, text="Deep-capture helper", padding=8)
        box2.pack(fill="x", pady=12)
        ttk.Label(box2, wraplength=780, foreground="#606060",
                  text="rp_fastread.py runs ON THE BOARD from /dev/shm, which "
                       "is RAM -- it is gone after every reboot. Without it, "
                       "deep captures fail rather than falling back."
                  ).pack(anchor="w")
        ttk.Button(box2, text="Check helper",
                   command=self.board_check_helper).pack(anchor="w", pady=6)
        self.helper_status = tk.StringVar(value="unknown")
        ttk.Label(box2, textvariable=self.helper_status).pack(anchor="w")

    def board_connect(self):
        host = self.host.get().strip()

        def go():
            rp = RedPitaya(host)
            return rp, rp.idn()

        def done(v):
            self.st.rp, idn = v
            self.board_status.set(f"connected to {host} -- {idn}")
            self.log(f"connected to {host}: {idn}")

        self.submit(f"connect {host}", go, done)

    def board_disconnect(self):
        rp = self.st.rp
        if rp is None:
            return self.log("board not connected")

        def go():
            rp.close()            # disarms both outputs
            return True

        def done(_v):
            self.st.rp = None
            self.st.outputs_on.clear()
            self._refresh_outputs()
            self.board_status.set("not connected")
            self.log("disconnected; close() disabled both outputs")

        self.submit("disconnect", go, done)

    def board_idn(self):
        rp = self._need_board()
        if rp:
            self.submit("*IDN?", rp.idn, lambda v: self.log(f"*IDN? -> {v}"))

    def board_front_end(self):
        rp = self._need_board()
        if not rp:
            return
        dec = int(self.decim.get())
        coup, gain = self.coupling.get(), self.gain.get()

        def go():
            rp.setup_acquisition(decimation=dec, coupling=coup, gain=gain)
            return dec, coup, gain

        self.submit("front end", go,
                    lambda v: self.log(f"front end: decimation {v[0]}, {v[1]}, "
                                       f"{v[2]} (both channels)"))

    def board_check_helper(self):
        rp = self._need_board()
        if not rp:
            return

        def done(v):
            self.helper_status.set(
                "running" if v else "NOT running -- deep captures will fail")
            self.log(f"fast-read helper: {'available' if v else 'absent'}")

        self.submit("helper check", rp.fast_read_available, done)

    def _need_board(self):
        if self.st.rp is None:
            messagebox.showwarning("No board", "Connect to the board first.")
            return None
        return self.st.rp

    # -- tab: outputs

    def _build_outputs(self):
        f = ttk.Frame(self.nb, padding=10)
        self.nb.add(f, text="Outputs")

        tk.Label(f, background="#fdf2c0", foreground="#5a4500", padx=8, pady=6,
                 justify="left", wraplength=940,
                 text="These buttons drive the physical outputs. The RF drive "
                      "level is tuned on the bench by maximising the "
                      "diffracted light with an unmodulated carrier -- three "
                      "separate recommendations to attenuate it were made and "
                      "all three withdrawn. Amplitude below is the board's "
                      "output setting, not a correction to that."
                 ).pack(fill="x", pady=(0, 10))

        box = ttk.LabelFrame(f, text="Two-tone plan (fs/16384 grid)", padding=8)
        box.pack(fill="x")
        txt = tk.Text(box, height=6, width=88, relief="flat", borderwidth=0,
                      font=("TkFixedFont", 9))
        txt.insert("1.0", PLAN.describe())
        txt.configure(state="disabled")
        txt.pack(anchor="w")

        ctl = ttk.LabelFrame(f, text="Drive", padding=8)
        ctl.pack(fill="x", pady=12)
        ttk.Label(ctl, text="Amplitude (V)").grid(row=0, column=0, sticky="w")
        self.amp = tk.StringVar(value="0.5")
        ttk.Entry(ctl, textvariable=self.amp, width=8).grid(row=0, column=1,
                                                            padx=6)
        ttk.Button(ctl, text="Enable OUT1 (f1)",
                   command=lambda: self.output_on(1)).grid(row=0, column=2,
                                                           padx=(18, 4))
        ttk.Button(ctl, text="Enable OUT2 (f2)",
                   command=lambda: self.output_on(2)).grid(row=0, column=3,
                                                           padx=4)
        ttk.Button(ctl, text="Outputs off", command=self.outputs_off).grid(
            row=0, column=4, padx=18)

        self.out_detail = tk.StringVar(value="OUT1 off    OUT2 off")
        ttk.Label(f, textvariable=self.out_detail,
                  font=("TkFixedFont", 10)).pack(anchor="w")

    def output_on(self, channel: int):
        rp = self._need_board()
        if not rp:
            return
        try:
            amp = float(self.amp.get())
        except ValueError:
            return messagebox.showerror("Amplitude", "Not a number.")
        mod = PLAN.f1 if channel == 1 else PLAN.f2
        if not messagebox.askokcancel(
                "Enable an output",
                f"Enable OUT{channel}?\n\n"
                f"Carrier      {PLAN.carrier / 1e6:.6f} MHz\n"
                f"Modulation   {mod / 1e6:.6f} MHz  (AM, depth 1)\n"
                f"Amplitude    {amp} V\n\n"
                f"This drives the physical output. Whatever is connected to it "
                f"will receive this signal."):
            return self.log(f"OUT{channel} enable cancelled")

        def go():
            return rp.setup_am_generator(carrier=PLAN.carrier, modulation=mod,
                                         amplitude=amp, channel=channel)

        def done(table):
            self.st.outputs_on.add(channel)
            self._refresh_outputs()
            self.log(f"OUT{channel} ON: carrier {table.carrier / 1e6:.6f} MHz, "
                     f"modulation {table.modulation / 1e6:.6f} MHz, {amp} V")

        self.submit(f"enable OUT{channel}", go, done)

    def outputs_off(self):
        rp = self.st.rp
        if rp is None:
            self.st.outputs_on.clear()
            self._refresh_outputs()
            return self.log("outputs off (no board connected)")

        def go():
            for ch in (1, 2):
                rp.write(f"OUTPUT{ch}:STATE OFF")
            return True

        def done(_v):
            self.st.outputs_on.clear()
            self._refresh_outputs()
            self.log("OUTPUT1:STATE OFF / OUTPUT2:STATE OFF sent")

        self.submit("outputs off", go, done)

    def _refresh_outputs(self):
        self.out_detail.set("    ".join(
            f"OUT{c} {'ON' if c in self.st.outputs_on else 'off'}"
            for c in (1, 2)))
        if self.st.outputs_on:
            self.out_state.set(f"outputs: ON {sorted(self.st.outputs_on)}")
            self.out_lbl.configure(foreground="#c01c28",
                                   font=("TkDefaultFont", 9, "bold"))
        else:
            self.out_state.set("outputs: off")
            self.out_lbl.configure(foreground="#404040",
                                   font=("TkDefaultFont", 9))

    # -- tab: acquire

    def _build_acquire(self):
        f = ttk.Frame(self.nb, padding=10)
        self.nb.add(f, text="Acquire")

        box = ttk.LabelFrame(f, text="Deep capture", padding=8)
        box.pack(fill="x")
        self.n_samples = tk.StringVar(value="2000000")
        self.trig_src = tk.StringVar(value="NOW")
        self.trig_lev = tk.StringVar(value="0.1")
        self.preroll = tk.StringVar(value="0")
        fields = (("Samples/ch", self.n_samples, 12),
                  ("Trigger", self.trig_src, 9),
                  ("Level (V)", self.trig_lev, 8),
                  ("Pre-roll", self.preroll, 10))
        for col, (lab, var, w) in enumerate(fields):
            ttk.Label(box, text=lab).grid(row=0, column=col * 2, sticky="w",
                                          padx=(0 if col == 0 else 14, 0))
            if var is self.trig_src:
                ttk.Combobox(box, textvariable=var, width=w, state="readonly",
                             values=("NOW", "CH1_PE", "CH2_PE",
                                     "EXT_PE")).grid(row=0, column=col * 2 + 1,
                                                     padx=4)
            else:
                ttk.Entry(box, textvariable=var, width=w).grid(
                    row=0, column=col * 2 + 1, padx=4)
        ttk.Button(box, text="Capture", command=self.acquire).grid(
            row=1, column=0, pady=10, sticky="w")
        ttk.Label(box, foreground="#606060",
                  text="Decimation comes from the Board tab. Pre-roll needs a "
                       "real trigger source, not NOW.").grid(
            row=1, column=1, columnspan=7, sticky="w")

        sim = ttk.LabelFrame(f, text="Simulate -- no hardware needed",
                             padding=8)
        sim.pack(fill="x", pady=12)
        ttk.Label(sim, wraplength=860, foreground="#606060",
                  text="Builds a whole synthetic sweep: a tone at the lock-in "
                       "frequency with a Lorentzian resonance, a 25 us trigger "
                       "PULSE per logged point on CH2, and a matching laser "
                       "log -- so the full path to a wavelength axis runs with "
                       "nothing connected. The record is laid out as a real "
                       "one must be: pre-roll, sweep, tail. The envelope is a "
                       "stand-in, not DUT physics -- this tests the software, "
                       "not the measurement.").grid(row=0, column=0,
                                                    columnspan=7, sticky="w",
                                                    pady=(0, 6))
        self.sim_ms = tk.StringVar(value="200")
        self.sim_noise = tk.StringVar(value="0.000011")
        ttk.Label(sim, text="Duration (ms)").grid(row=1, column=0, sticky="w")
        ttk.Entry(sim, textvariable=self.sim_ms, width=8).grid(row=1, column=1,
                                                               padx=6)
        ttk.Label(sim, text="Noise rms (V)").grid(row=1, column=2, sticky="w",
                                                  padx=(14, 0))
        ttk.Entry(sim, textvariable=self.sim_noise, width=10).grid(
            row=1, column=3, padx=6)
        ttk.Label(sim, text="Log points").grid(row=1, column=4, sticky="w",
                                               padx=(14, 0))
        self.sim_points = tk.StringVar(value="200")
        ttk.Entry(sim, textvariable=self.sim_points, width=8).grid(
            row=1, column=5, padx=6)
        ttk.Button(sim, text="Simulate", command=self.simulate).grid(
            row=1, column=6, padx=18)

        self.acq_info = tk.StringVar(value="no record")
        ttk.Label(f, textvariable=self.acq_info,
                  font=("TkFixedFont", 9)).pack(anchor="w", pady=(6, 0))
        self.spec_info = tk.StringVar(value="")
        ttk.Label(f, textvariable=self.spec_info, foreground="#1a5fb4",
                  font=("TkFixedFont", 9)).pack(anchor="w", pady=(0, 4))

        ttk.Label(f, wraplength=980, foreground="#606060",
                  text="This is the RAW ADC record -- the lock-in's INPUT, not "
                       "its result. In 'time' it is volts against time; at "
                       "full span a ~991 kHz tone in a 60 ms record is ~60,000 "
                       "cycles in ~900 pixels, so it draws as a solid band. "
                       "Zoom to 10 us for actual cycles. In 'spectrum' it is "
                       "an FFT -- use that to check the tone is where you "
                       "think it is BEFORE demodulating. The sweep-shaped "
                       "trace lives on the Demodulate tab."
                  ).pack(anchor="w", pady=(0, 4))

        which = ttk.Frame(f)
        which.pack(fill="x")
        self.raw_channel = tk.StringVar(value="1")
        ttk.Label(which, text="Channel").pack(side="left")
        for ch in ("1", "2"):
            ttk.Radiobutton(which, text=f"CH{ch}", value=ch,
                            variable=self.raw_channel,
                            command=self._redraw_raw).pack(side="left", padx=4)
        ttk.Label(which, text="View").pack(side="left", padx=(16, 4))
        self.raw_domain = tk.StringVar(value="time")
        for name in ("time", "spectrum"):
            ttk.Radiobutton(which, text=name, value=name,
                            variable=self.raw_domain,
                            command=self._redraw_raw).pack(side="left", padx=2)
        ttk.Label(which, text="Zoom").pack(side="left", padx=(16, 4))
        self.raw_span = tk.StringVar(value="full")
        ttk.Combobox(which, textvariable=self.raw_span, width=8,
                     state="readonly",
                     values=("full", "10 ms", "1 ms", "100 us", "10 us",
                             "2 us")).pack(side="left")
        ttk.Label(which, text="Position").pack(side="left", padx=(16, 4))
        self.raw_pos = tk.DoubleVar(value=0.0)
        ttk.Scale(which, from_=0.0, to=100.0, variable=self.raw_pos,
                  orient="horizontal", length=200,
                  command=lambda _v: self._redraw_raw()).pack(side="left")
        ttk.Button(which, text="Find trigger edges on CH2",
                   command=self.find_edges).pack(side="left", padx=16)
        self.raw_span.trace_add("write", lambda *_a: self._redraw_raw())

        self.raw_plot = Plot(f, height=250)
        self.raw_plot.pack(fill="both", expand=True, pady=(6, 0))

    def acquire(self):
        rp = self._need_board()
        if not rp:
            return
        try:
            n = int(self.n_samples.get())
            lev = float(self.trig_lev.get())
            pre = int(self.preroll.get())
        except ValueError:
            return messagebox.showerror("Capture", "Check the numeric fields.")
        dec, src = int(self.decim.get()), self.trig_src.get()

        def go():
            t0 = time.monotonic()
            chans = rp.acquire_deep_fast(n_samples=n, decimation=dec,
                                         channels=(1, 2), trigger=src,
                                         trigger_level=lev,
                                         preroll_samples=pre)
            return chans, time.monotonic() - t0

        def done(v):
            chans, dt = v
            self._store_raw({1: chans[0], 2: chans[1]},
                            BASE_SAMPLE_RATE / dec)
            mb = sum(c.size for c in chans) * 2 / 1024 ** 2
            rate = f", {mb / dt:.1f} MB/s" if dt > 0 else ""
            self.log(f"captured {chans[0].size} samples/channel at decimation "
                     f"{dec} in {dt:.2f} s ({mb:.0f} MB{rate})")

        self.submit("deep capture", go, done)

    def simulate(self):
        try:
            dur = float(self.sim_ms.get()) / 1e3
            noise = float(self.sim_noise.get())
        except ValueError:
            return messagebox.showerror("Simulate", "Check the numeric fields.")
        fs = BASE_SAMPLE_RATE / int(self.decim.get())

        # The record is laid out the way a real capture must be: pre-roll long
        # enough for the filter to settle, then the sweep, then a tail. A
        # pre-roll shorter than the settling (22.6 ms) leaves NO pre-sweep
        # points at all, which looks exactly like a mapping bug.
        preroll = recommended_preroll(float(self.out_rate.get() or 5000))
        tail = recommended_tail(float(self.out_rate.get() or 5000))
        sweep = dur - preroll - tail
        if sweep <= 5e-3:
            return messagebox.showerror(
                "Simulate",
                f"{dur * 1e3:.0f} ms is too short. The record has to hold "
                f"{preroll * 1e3:.1f} ms of pre-roll and {tail * 1e3:.1f} ms "
                f"of tail around the sweep, so try at least "
                f"{(preroll + tail + 20e-3) * 1e3:.0f} ms.")
        n_log = max(2, int(self.sim_points.get() or 200))
        step = sweep / (n_log - 1)
        peak_frac = 0.4

        def go():
            peak_t = preroll + peak_frac * sweep

            def envelope(t):
                return 1.0 / (1.0 + ((t - peak_t) / (0.08 * sweep)) ** 2)

            sig, _truth = synthesise_dut_output(
                PLAN.difference, dur, fs=fs, envelope_fn=envelope,
                noise_rms=noise, amplitude=0.2, seed=1)
            # A PULSE train, 25 us wide, one pulse per logged point -- the
            # shape the Santec actually emits (TSL-775 p46). The square wave
            # this used to make has a 50% duty cycle, which no laser produces
            # and which hides the fact that each pulse gives TWO edges.
            trig = make_trigger_pulses(dur, preroll, step, width=25e-6, fs=fs,
                                       n_pulses=n_log)
            wl = np.linspace(1545e-9, 1555e-9, n_log)
            return sig, trig, fs, wl

        def done(v):
            sig, trig, fs_used, wl = v
            self.st.wavelengths = wl
            self.st.reduction = None
            self._store_raw({1: sig, 2: trig}, fs_used)
            self._refresh_log_status()
            self.log(f"simulated {sig.size} samples at "
                     f"{fs_used / 1e6:.3f} MS/s: {preroll * 1e3:.1f} ms "
                     f"pre-roll, {sweep * 1e3:.1f} ms sweep, "
                     f"{tail * 1e3:.1f} ms tail; {n_log} trigger pulses "
                     f"{step * 1e6:.2f} us apart; noise "
                     f"{noise * 1e6:.1f} uV rms")
            self.log(f"synthetic laser log loaded: {n_log} points, "
                     f"1545.0000 to 1555.0000 nm. Resonance planted at "
                     f"{np.interp(peak_frac * sweep, np.arange(n_log) * step, wl) * 1e9:.4f} nm")

        self.submit("simulate", go, done)

    def _store_raw(self, raw: dict, fs: float):
        self.st.raw = raw
        self.st.fs = fs
        self._redraw_raw()

    _SPANS = {"full": None, "10 ms": 10e-3, "1 ms": 1e-3, "100 us": 100e-6,
              "10 us": 10e-6, "2 us": 2e-6}

    def _redraw_raw(self):
        if not self.st.raw:
            return
        ch = int(self.raw_channel.get())
        y = self.st.raw.get(ch)
        if y is None:
            return
        fs = self.st.fs

        # Stats always describe the WHOLE record, not the zoomed window --
        # a min/max that changed as you dragged the slider would be an easy
        # thing to misread as the signal changing.
        whole = (f"CH{ch}  {y.size} samples @ {fs / 1e6:.4f} MS/s "
                 f"({y.size / fs * 1e3:.2f} ms total)   "
                 f"min {y.min():.5g}   max {y.max():.5g}   "
                 f"rms {np.sqrt(np.mean(y ** 2)):.5g}")

        if self.raw_domain.get() == "spectrum":
            return self._draw_spectrum(y, fs, ch, whole)
        self.spec_info.set("")

        span = self._SPANS.get(self.raw_span.get())
        if span is None:
            lo, hi = 0, y.size
        else:
            n_win = max(2, int(round(span * fs)))
            n_win = min(n_win, y.size)
            lo = int((y.size - n_win) * self.raw_pos.get() / 100.0)
            hi = lo + n_win
            whole += f"   |  showing {(hi - lo) / fs * 1e6:.1f} us from " \
                     f"{lo / fs * 1e3:.3f} ms"
        self.acq_info.set(whole)
        t = np.arange(lo, hi) / fs
        self.raw_plot.show(t, y[lo:hi], "time (s)", f"CH{ch} raw (V)")

    # A fixed block rather than the zoom window: the frequency resolution of a
    # spectrum is set by how many samples go into it, so letting the time-domain
    # zoom drive it would silently change the resolution as you scrubbed. 2^20
    # samples at 31.25 MS/s is 33 ms and ~30 Hz per bin, which resolves the
    # 991.821 kHz line and its neighbours with room to spare.
    _FFT_SAMPLES = 1 << 20

    def _draw_spectrum(self, y, fs, ch, whole):
        n = min(self._FFT_SAMPLES, y.size)
        if n < 1024:
            self.acq_info.set(whole + "   |  too few samples for a spectrum")
            return self.raw_plot.clear()
        lo = int((y.size - n) * self.raw_pos.get() / 100.0)
        block = y[lo:lo + n]

        # Hann window, and the amplitude scaling that goes with it: a sinusoid
        # of amplitude A reads A, not A/2 and not A*n. Getting this wrong gives
        # a spectrum whose shape is right and whose numbers are meaningless,
        # which is the kind of plausible wrong answer this project collects.
        w = np.hanning(n)
        amp = 2.0 * np.abs(np.fft.rfft(block * w)) / np.sum(w)
        freq = np.fft.rfftfreq(n, 1.0 / fs)
        with np.errstate(divide="ignore"):
            db = 20.0 * np.log10(np.maximum(amp, 1e-12))

        # Ignore DC and the window's skirt around it when hunting the peak,
        # or a few millivolts of offset wins every time.
        first = max(1, int(round(50e3 * n / fs)))
        k = first + int(np.argmax(amp[first:]))
        peak_f, peak_a = float(freq[k]), float(amp[k])

        target = PLAN.difference
        kt = int(round(target * n / fs))
        at_plan = float(amp[kt]) if 0 <= kt < amp.size else float("nan")

        self.acq_info.set(
            f"{whole}   |  spectrum of {n} samples ({n / fs * 1e3:.1f} ms, "
            f"{fs / n:.1f} Hz/bin)")
        self.spec_info.set(
            f"peak {peak_f / 1e3:.3f} kHz at {_eng(peak_a)}V   |   "
            f"at the plan's {target / 1e3:.3f} kHz: {_eng(at_plan)}V   |   "
            f"peak is {(peak_f - target):+.1f} Hz from the plan")
        self.raw_plot.show(freq, db, "frequency (Hz)", f"CH{ch} (dBV)")

    def find_edges(self):
        if 2 not in self.st.raw:
            return messagebox.showwarning("No record",
                                          "Capture or simulate first.")
        trig, fs = self.st.raw[2], self.st.fs

        def done(edges):
            if len(edges) == 0:
                self.log("no trigger edges found on CH2")
                return messagebox.showinfo("Edges", "No edges found on CH2.")
            if len(edges) == 1:
                return self.log(f"1 edge at {edges[0] * 1e3:.4f} ms")
            step = np.diff(edges)
            self.log(f"{len(edges)} rising edges (= pulses); first at "
                     f"{edges[0] * 1e3:.4f} ms; mean step "
                     f"{np.mean(step) * 1e6:.3f} us "
                     f"(sd {np.std(step) * 1e9:.1f} ns)")

        self.submit("find edges",
                    lambda: find_trigger_edges(trig, fs, polarity="rising"),
                    done)

    # -- tab: demodulate

    def _build_view(self):
        f = ttk.Frame(self.nb, padding=10)
        self.nb.add(f, text="Demodulate")

        box = ttk.LabelFrame(f, text="Lock-in", padding=8)
        box.pack(fill="x")
        # Six decimals, not three. The box is human-editable so it can never be
        # bit-exact, but rounding the plan's 991821.2890625 Hz to 3 places
        # demodulates 62 uHz off -- harmless over a 1 s record (0.02 degrees of
        # phase across the whole sweep, against 0.002 measured drift in H3.2),
        # and pointless to accept when the digits are free.
        self.f_ref = tk.StringVar(value=f"{PLAN.difference:.6f}")
        self.out_rate = tk.StringVar(value="5000")
        ttk.Label(box, text="f_ref (Hz)").grid(row=0, column=0, sticky="w")
        ttk.Entry(box, textvariable=self.f_ref, width=14).grid(row=0, column=1,
                                                               padx=6)
        ttk.Label(box, text="Output rate (Sa/s)").grid(row=0, column=2,
                                                       sticky="w", padx=(14, 0))
        ttk.Entry(box, textvariable=self.out_rate, width=10).grid(
            row=0, column=3, padx=6)
        ttk.Button(box, text="Demodulate", command=self.demod).grid(
            row=0, column=4, padx=18)
        ttk.Label(box, wraplength=860, foreground="#606060",
                  text="f_ref defaults to the plan's difference frequency. It "
                       "is 991.821 kHz, not 1 MHz -- never hardcode the round "
                       "number.").grid(row=1, column=0, columnspan=6,
                                       sticky="w", pady=(6, 0))

        wlbox = ttk.LabelFrame(f, text="Wavelength axis", padding=8)
        wlbox.pack(fill="x", pady=(8, 0))
        ttk.Label(wlbox, wraplength=860, foreground="#606060",
                  text="With a laser log loaded, Demodulate runs the full "
                       "pipeline and the x axis becomes WAVELENGTH. Without "
                       "one it stops at time, and the CSV's wavelength column "
                       "is written empty rather than filled with something "
                       "plausible.").grid(row=0, column=0, columnspan=4,
                                          sticky="w", pady=(0, 6))
        ttk.Button(wlbox, text="Load log from laser",
                   command=self.load_log_from_laser).grid(row=1, column=0)
        ttk.Button(wlbox, text="Load log from file",
                   command=self.load_log_from_file).grid(row=1, column=1,
                                                         padx=6)
        ttk.Button(wlbox, text="Clear log",
                   command=self.clear_log_data).grid(row=1, column=2, padx=6)
        self.log_status = tk.StringVar(value="no laser log loaded")
        ttk.Label(wlbox, textvariable=self.log_status).grid(
            row=1, column=3, padx=14, sticky="w")

        sel = ttk.Frame(f)
        sel.pack(fill="x", pady=8)
        self.trace_kind = tk.StringVar(value="amplitude")
        for name in ("amplitude", "R", "X", "Y", "phase"):
            ttk.Radiobutton(sel, text=name, value=name,
                            variable=self.trace_kind,
                            command=self._redraw_trace).pack(side="left",
                                                             padx=(0, 10))
        ttk.Button(sel, text="Save CSV", command=self.save_csv).pack(
            side="right")
        ttk.Button(sel, text="Save raw .npz", command=self.save_npz).pack(
            side="right", padx=6)

        # The four-parameter readout, in the spirit of a lock-in front panel.
        # Unlike an instrument, this trace is a WHOLE SWEEP rather than a live
        # value, so each box shows the mean across the trace by default and
        # switches to the value under the pointer while hovering the plot.
        # Which of the two you are looking at is labelled, because a mean and
        # a point value are very different numbers and look identical.
        read = ttk.LabelFrame(f, text="X / Y / R / theta", padding=8)
        read.pack(fill="x")
        self.readout_mode = tk.StringVar(value="mean across the trace")
        self.readouts = {}
        for col, (key, unit) in enumerate((("X", "V"), ("Y", "V"),
                                           ("R", "V"), ("theta", "deg"))):
            cell = ttk.Frame(read)
            cell.grid(row=0, column=col, padx=(0 if col == 0 else 26, 0),
                      sticky="w")
            ttk.Label(cell, text=f"{key} ({unit})",
                      foreground="#606060").pack(anchor="w")
            var = tk.StringVar(value="--")
            self.readouts[key] = var
            ttk.Label(cell, textvariable=var,
                      font=("TkFixedFont", 15)).pack(anchor="w")
        ttk.Label(read, textvariable=self.readout_mode,
                  foreground="#606060").grid(row=1, column=0, columnspan=4,
                                             sticky="w", pady=(6, 0))

        self.demod_info = tk.StringVar(value="not demodulated")
        ttk.Label(f, textvariable=self.demod_info,
                  font=("TkFixedFont", 9)).pack(anchor="w", pady=(8, 0))
        self.trace_plot = Plot(f, height=280, on_cursor=self._cursor_readout)
        self.trace_plot.pack(fill="both", expand=True, pady=(4, 0))

    def demod(self):
        if 1 not in self.st.raw:
            return messagebox.showwarning("No record",
                                          "Capture or simulate first.")
        try:
            f_ref = float(self.f_ref.get())
            rate = float(self.out_rate.get())
        except ValueError:
            return messagebox.showerror("Demodulate", "Check the fields.")
        sig, fs = self.st.raw[1], self.st.fs

        wl = self.st.wavelengths
        trig = self.st.raw.get(2)

        def go():
            # With a laser log AND a trigger record, run the whole pipeline --
            # the same reduce_sweep the deliverable uses, not a GUI-local
            # reimplementation of it. Without either, stop at demodulation.
            if wl is not None and trig is not None:
                return reduce_sweep(sig, trig, fs, wl, f_ref=f_ref,
                                    output_rate=rate)
            return demodulate(sig, fs, f_ref, output_rate=rate)

        def done(out):
            reduction = out if hasattr(out, "trace") else None
            res = reduction.result if reduction else out
            self.st.reduction = reduction
            self.st.result = res
            spacing = (res.t[1] - res.t[0]) * 1e6 if res.t.size > 1 else 0.0
            info = (f"{res.t.size} points   spacing {spacing:.3f} us   "
                    f"bandwidth {res.bandwidth:.1f} Hz   "
                    f"{res.settle} settling samples trimmed   "
                    f"t = {res.t[0] * 1e3:.3f} to {res.t[-1] * 1e3:.3f} ms")
            if reduction:
                info += f"   |  {int(reduction.trace.valid.sum())} mapped"
            self.demod_info.set(info)
            self.log(f"demodulated at {res.f_ref:.3f} Hz -> {res.t.size} "
                     f"points at {res.fs_out:.1f} Sa/s")
            if reduction:
                # The full diagnosis goes in the log rather than the tab: it is
                # what tells you whether to believe the axis, and it is the
                # thing worth having in a saved log after the fact.
                for line in reduction.describe().splitlines():
                    self.log("  " + line)
                if not reduction.alignment.ok:
                    messagebox.showwarning(
                        "Alignment suspect",
                        "The trigger count and the laser log do not agree:\n\n"
                        + reduction.alignment.diagnosis +
                        "\n\nThe trace is still shown, but every wavelength "
                        "on it may be shifted. See the Log tab.")
            self._redraw_trace()

        self.submit("demodulate", go, done)

    # -- the laser log

    def _refresh_log_status(self):
        wl = self.st.wavelengths
        if wl is None:
            self.log_status.set("no laser log loaded -- x axis stays as time")
        else:
            self.log_status.set(
                f"{wl.size} points, {wl.min() * 1e9:.4f} to "
                f"{wl.max() * 1e9:.4f} nm")

    def _accept_log(self, wl, source: str):
        wl = np.asarray(wl, dtype=float).ravel()
        if wl.size < 2:
            return messagebox.showerror(
                "Laser log", f"{source} gave {wl.size} point(s); at least 2 "
                             f"are needed to interpolate.")
        # Metres, not nanometres. A log in nm would map every point 10^9 out,
        # and 1550 is a perfectly plausible-looking number to see in a file.
        if not (1e-7 < np.nanmedian(wl) < 1e-5):
            return messagebox.showerror(
                "Laser log",
                f"{source} has a median of {np.nanmedian(wl):.6g}, which is "
                f"not metres. A C-band log should read ~1.55e-6. If the file "
                f"is in nanometres, convert it before loading -- guessing "
                f"would be wrong by 10^9 without anything looking odd.")
        self.st.wavelengths = wl
        self.st.reduction = None
        self._refresh_log_status()
        self.log(f"laser log from {source}: {wl.size} points, "
                 f"{wl.min() * 1e9:.4f} to {wl.max() * 1e9:.4f} nm")

    def load_log_from_laser(self):
        laser = self._need_laser()
        if not laser:
            return
        self.log("laser <- :READout:DATa?")
        self.submit("read wavelength log", laser.read_wavelengths,
                    lambda wl: self._accept_log(wl, "the laser"))

    def load_log_from_file(self):
        path = filedialog.askopenfilename(
            filetypes=[("numpy", "*.npy *.npz"), ("text/CSV", "*.csv *.txt"),
                       ("all files", "*.*")])
        if not path:
            return
        try:
            if path.endswith(".npz"):
                with np.load(path) as z:
                    key = next(iter(z.files))
                    wl = z[key]
            elif path.endswith(".npy"):
                wl = np.load(path)
            else:
                wl = np.loadtxt(path, delimiter=",", comments="#").ravel()
        except Exception as exc:
            return messagebox.showerror("Laser log", f"could not read: {exc}")
        self._accept_log(wl, os.path.basename(path))

    def clear_log_data(self):
        self.st.wavelengths = None
        self.st.reduction = None
        self._refresh_log_status()
        self.log("laser log cleared; the x axis returns to time")

    def _trace_values(self):
        res = self.st.result
        kind = self.trace_kind.get()
        if kind == "amplitude":
            return res.amplitude(), "amplitude (V)"
        if kind == "R":
            return res.R, "R (V) -- biased high in noise"
        if kind == "X":
            return res.X, "X (V)"
        if kind == "Y":
            return res.Y, "Y (V)"
        return res.theta_deg, "phase (deg)"

    def _redraw_trace(self):
        if self.st.result is None:
            return
        y, label = self._trace_values()
        red = self.st.reduction
        if red is None:
            self._plot_index = np.arange(y.size)
            self.trace_plot.show(self.st.result.t, y, "time (s)", label)
        else:
            # Only the mapped points. The unmapped ones are pre-roll and tail,
            # and plotting them against a NaN wavelength would either drop them
            # silently or, worse, bunch them at one end of the axis.
            m = red.trace.valid
            self._plot_index = np.flatnonzero(m)
            self.trace_plot.show(red.trace.wavelength[m] * 1e9, y[m],
                                 "wavelength (nm)", label)
        self._cursor_readout(None)

    def _cursor_readout(self, index):
        """Fill X/Y/R/theta -- at `index` while hovering, else trace means.

        `index` addresses the PLOT, which shows only the mapped points once a
        wavelength axis exists. Translating through _plot_index is what keeps
        the readout describing the point under the pointer rather than a
        different one some pre-roll's worth away.
        """
        res = self.st.result
        if res is None:
            return
        idx_map = getattr(self, "_plot_index", None)
        if index is not None and idx_map is not None and 0 <= index < idx_map.size:
            index = int(idx_map[index])
        if index is None or not 0 <= index < res.t.size:
            # R is averaged, not recomputed from mean X and mean Y: with the
            # response phase moving across a sweep those two differ, and
            # hypot(mean X, mean Y) would read low without looking wrong.
            vals = {"X": float(np.mean(res.X)), "Y": float(np.mean(res.Y)),
                    "R": float(np.mean(res.R)),
                    "theta": float(np.degrees(np.mean(res.theta)))}
            self.readout_mode.set(
                f"mean across all {res.t.size} points -- hover the plot for a "
                f"single point. Note mean R is biased high in noise "
                f"(1.25 sigma with no signal at all); the amplitude trace is "
                f"the unbiased one.")
        else:
            i = int(index)
            vals = {"X": float(res.X[i]), "Y": float(res.Y[i]),
                    "R": float(res.R[i]), "theta": float(res.theta_deg[i])}
            where = f"point {i} of {res.t.size}, t = {res.t[i] * 1e3:.4f} ms"
            red = self.st.reduction
            if red is not None and np.isfinite(red.trace.wavelength[i]):
                where += f", {red.trace.wavelength[i] * 1e9:.4f} nm"
            self.readout_mode.set(where)
        for key, var in self.readouts.items():
            v = vals[key]
            var.set(f"{v:+.2f}" if key == "theta" else _eng(v))

    def save_csv(self):
        if self.st.result is None:
            return messagebox.showwarning("Nothing to save",
                                          "Demodulate first.")
        path = filedialog.asksaveasfilename(defaultextension=".csv",
                                            filetypes=[("CSV", "*.csv")])
        if not path:
            return
        res = self.st.result
        red = self.st.reduction
        amp = res.amplitude()

        def go():
            if red is not None:
                # The real deliverable: every row carries the wavelength the
                # laser reported, and the header carries enough provenance to
                # reconstruct how the axis was built -- where the step came
                # from above all, since that is the one number nothing in the
                # data would reveal as wrong.
                meta = {"source": "bench_gui"}
                meta.update(red.metadata())
                return write_trace_csv(path, red.trace.wavelength,
                                       red.trace.amplitude, metadata=meta,
                                       extra_columns={"time_s": res.t})
            # No laser log behind this trace, so the wavelength column is
            # written EMPTY rather than filled with something plausible. A
            # time-indexed trace wearing a wavelength column is exactly the
            # silent failure the whole wavelength design guards against.
            return write_trace_csv(
                path, np.full(res.t.size, np.nan), amp,
                metadata={"source": "bench_gui",
                          "f_ref_Hz": f"{res.f_ref:.3f}",
                          "output_rate_Sa_s": f"{res.fs_out:.3f}",
                          "bandwidth_Hz": f"{res.bandwidth:.3f}",
                          "NOTE": "no laser log: wavelength column is empty "
                                  "and time_s is the real axis"},
                extra_columns={"time_s": res.t}, keep_invalid=True)

        self.submit("save CSV", go,
                    lambda n: self.log(f"wrote {n} rows to {path}"))

    def save_npz(self):
        if not self.st.raw:
            return messagebox.showwarning("Nothing to save", "Capture first.")
        path = filedialog.asksaveasfilename(defaultextension=".npz",
                                            filetypes=[("npz", "*.npz")])
        if not path:
            return
        arrays = {f"ch{k}": v for k, v in self.st.raw.items()}
        arrays["fs"] = np.array([self.st.fs])

        def go():
            write_raw_npz(path, **arrays)
            return path

        self.submit("save npz", go, lambda p: self.log(f"wrote {p}"))

    # -- tab: laser

    def _build_laser(self):
        f = ttk.Frame(self.nb, padding=10)
        self.nb.add(f, text="Laser")

        tk.Label(f, background="#e8f0fe", foreground="#102a43", padx=8, pady=6,
                 justify="left", wraplength=940,
                 text="Reads are always safe. Writes are not -- the light goes "
                      "somewhere -- so they are refused unless the box below "
                      "is ticked. As of 2026-08-25 this laser has never "
                      "answered anything, and the host side is eliminated: "
                      "cable, driver, port, six baud rates, three "
                      "terminators, both flow-control states and both driver "
                      "interfaces. What is left to try is line settings other "
                      "than 8N1, a power cycle, Santec's own software, or LAN."
                 ).pack(fill="x", pady=(0, 10))

        row = ttk.Frame(f)
        row.pack(fill="x")
        ttk.Label(row, text="Port").pack(side="left")
        self.laser_port = tk.StringVar(value="COM29")
        ttk.Entry(row, textvariable=self.laser_port, width=10).pack(
            side="left", padx=6)
        ttk.Label(row, text="Baud").pack(side="left", padx=(10, 0))
        self.laser_baud = tk.StringVar(value="9600")
        ttk.Combobox(row, textvariable=self.laser_baud, width=8,
                     state="readonly",
                     values=("9600", "19200", "38400", "57600", "115200",
                             "230400")).pack(side="left", padx=6)
        ttk.Button(row, text="Connect", command=self.laser_connect).pack(
            side="left", padx=(10, 4))
        ttk.Button(row, text="Disconnect",
                   command=self.laser_disconnect).pack(side="left")

        self.laser_status = tk.StringVar(value="not connected")
        ttk.Label(f, textvariable=self.laser_status,
                  foreground="#606060").pack(anchor="w", pady=8)

        q = ttk.LabelFrame(f, text="Read-only queries -- always safe",
                           padding=8)
        q.pack(fill="x")
        queries = (("*IDN?", "idn"), ("Command set", "command_set"),
                   ("Wavelength", "wavelength_m"),
                   ("Logged points", "logged_points"),
                   ("Trigger config", "trigger_config"),
                   ("Sweep state", "sweep_state"))
        for i, (label, meth) in enumerate(queries):
            ttk.Button(q, text=label, width=16,
                       command=lambda m=meth, la=label: self.laser_query(m, la)
                       ).grid(row=i // 3, column=i % 3, padx=4, pady=3)

        w = ttk.LabelFrame(f, text="Raw command", padding=8)
        w.pack(fill="x", pady=12)
        self.allow_writes = tk.BooleanVar(value=False)
        ttk.Checkbutton(w, variable=self.allow_writes,
                        text="Allow writes (anything without a trailing '?')"
                        ).grid(row=0, column=0, columnspan=3, sticky="w",
                               pady=(0, 6))
        self.laser_cmd = tk.StringVar(value=":READout:POINts?")
        ttk.Entry(w, textvariable=self.laser_cmd, width=48).grid(row=1,
                                                                 column=0,
                                                                 sticky="w")
        ttk.Button(w, text="Send", command=self.laser_send).grid(row=1,
                                                                 column=1,
                                                                 padx=8)
        ttk.Button(w, text="Read wavelength log",
                   command=self.laser_read_log).grid(row=1, column=2, padx=8)

    def laser_connect(self):
        port = self.laser_port.get().strip()
        baud = int(self.laser_baud.get())

        def done(laser):
            self.st.laser = laser
            self.laser_status.set(f"port open: {port} at {baud} 8N1")
            self.log(f"laser port opened: {port} at {baud}. Opening the port "
                     f"proves nothing -- it enumerates cleanly and stays "
                     f"silent. Try a query.")

        self.submit(f"open {port}",
                    lambda: SantecTSL.over_serial(port, baud=baud), done)

    def laser_disconnect(self):
        laser = self.st.laser
        if laser is None:
            return self.log("laser not connected")

        def done(_v):
            self.st.laser = None
            self.laser_status.set("not connected")
            self.log("laser port closed")

        def go():
            laser.close()
            return True

        self.submit("close laser", go, done)

    def _need_laser(self):
        if self.st.laser is None:
            messagebox.showwarning("No laser", "Open the laser port first.")
            return None
        return self.st.laser

    def laser_query(self, method: str, label: str):
        laser = self._need_laser()
        if not laser:
            return

        def go():
            value = getattr(laser, method)()
            return value.describe() if hasattr(value, "describe") else value

        self.log(f"laser <- {label}")
        self.submit(label, go, lambda v: self.log(f"laser -> {v}"))

    def laser_send(self):
        laser = self._need_laser()
        if not laser:
            return
        cmd = self.laser_cmd.get().strip()
        if not cmd:
            return
        is_query = cmd.endswith("?")
        if not is_query and not self.allow_writes.get():
            return messagebox.showwarning(
                "Writes are off",
                f"{cmd!r} is not a query, and writes are disabled.\n\n"
                f"Tick 'Allow writes' if you intend to change the laser's "
                f"state. Reads cannot disturb anything; writes can.")
        if not is_query and not messagebox.askokcancel(
                "Write to the laser",
                f"Send {cmd!r} to the laser?\n\n"
                f"This changes its state, and the light goes somewhere."):
            return self.log(f"laser write cancelled: {cmd}")

        def go():
            if is_query:
                return laser.query(cmd)
            laser.write(cmd)
            # Not evidence of success. An unsupported command is silent here,
            # exactly like a supported one -- read something back to know.
            return "(write sent; no reply expected)"

        self.log(f"laser <- {cmd}")
        self.submit(f"laser {cmd}", go, lambda v: self.log(f"laser -> {v!r}"))

    def laser_read_log(self):
        """Read the log and hand it to the pipeline, not to the plot.

        An earlier version drew the log over the trace plot, which was worse
        than useless: it looked like a result, and it silently replaced the
        measurement someone had just taken.
        """
        self.load_log_from_laser()
        self.nb.select(3)

    # -- tab: log

    # ------------------------------------------------- the linear sweep

    def _build_sweep(self):
        """One click: modulation on, sweep, demodulate, wavelength vs power.

        Deliberately self-contained. The Laser tab talks through santec.py,
        which can read the log but CANNOT start a sweep; this tab opens its own
        TSL775 connection for the run and closes it again.
        """
        f = ttk.Frame(self.nb, padding=10)
        self.nb.add(f, text="Linear Sweep")

        ttk.Label(f, text=(
            "OUT1 --AM--> amplifier --> modulator --> light --> detector --> IN1"
            "\nlaser trigger --> IN2.   Demodulates AT the modulation frequency:"
            "\nnothing here squares the light, so the signal is at f1, not 2*f1."),
            justify="left").grid(row=0, column=0, columnspan=6, sticky="w",
                                 pady=(0, 8))

        g = ttk.LabelFrame(f, text="Drive", padding=8)
        g.grid(row=1, column=0, sticky="nw", padx=(0, 8))
        self.sw_carrier = tk.StringVar(value="80.0")
        self.sw_mod = tk.StringVar(
            value="%.4f" % (60 * BASE_SAMPLE_RATE / 16384 / 1e3))
        self.sw_amp = tk.StringVar(value="1.0")
        for r, (lbl, var, unit) in enumerate((
                ("Carrier", self.sw_carrier, "MHz"),
                ("Modulation", self.sw_mod, "kHz"),
                ("Amplitude", self.sw_amp, "V"))):
            ttk.Label(g, text=lbl).grid(row=r, column=0, sticky="w")
            ttk.Entry(g, textvariable=var, width=12).grid(row=r, column=1)
            ttk.Label(g, text=unit).grid(row=r, column=2, sticky="w")
        ttk.Label(g, text=("915.527 kHz = 60 ASG grid steps: whole cycles in\n"
                           "the table, and 94 kHz clear of the 504.868 kHz\n"
                           "switcher family. Avoid 1007.080 kHz -- 2.7 kHz off\n"
                           "a harmonic, where interference reads as a clean,\n"
                           "steady optical signal."),
                  justify="left", foreground="#555").grid(
            row=3, column=0, columnspan=3, sticky="w", pady=(6, 0))

        h = ttk.LabelFrame(f, text="Laser sweep", padding=8)
        h.grid(row=1, column=1, sticky="nw")
        self.sw_ip = tk.StringVar(value="10.101.0.197")
        self.sw_start = tk.StringVar(value="1500")
        self.sw_stop = tk.StringVar(value="1600")
        self.sw_speed = tk.StringVar(value="100")
        self.sw_step = tk.StringVar(value="0.02")
        self.sw_maxdbm = tk.StringVar(value="0.0")
        # Loss between the laser and the detector. Kevin's bench on 2026-08-28:
        # modulator, then a 90/10, then a 50/50. Taking the 10% arm that is
        # 10 + 3 = 13 dB before the modulator's own insertion loss, so the
        # detector sees a small fraction of the setpoint and gating on the
        # LASER's number refuses runs that were never near saturation.
        self.sw_loss = tk.StringVar(value="13.0")
        for r, (lbl, var, unit) in enumerate((
                ("Laser IP", self.sw_ip, ""),
                ("Start", self.sw_start, "nm"),
                ("Stop", self.sw_stop, "nm"),
                ("Speed", self.sw_speed, "nm/s"),
                ("Trigger step", self.sw_step, "nm"),
                ("Path loss", self.sw_loss, "dB"),
                ("Max at detector", self.sw_maxdbm, "dBm"))):
            ttk.Label(h, text=lbl).grid(row=r, column=0, sticky="w")
            ttk.Entry(h, textvariable=var, width=14).grid(row=r, column=1)
            ttk.Label(h, text=unit).grid(row=r, column=2, sticky="w")

        c = ttk.Frame(f)
        c.grid(row=2, column=0, columnspan=6, sticky="w", pady=(10, 6))
        self.sw_blocked = tk.BooleanVar(value=False)
        ttk.Checkbutton(c, text="CONTROL RUN -- close the shutter",
                        variable=self.sw_blocked).pack(side="left", padx=(0, 12))
        ttk.Button(c, text="Modulation ON",
                   command=self.sweep_mod_on).pack(side="left", padx=(0, 4))
        ttk.Button(c, text="Modulation OFF",
                   command=self.sweep_mod_off).pack(side="left", padx=(0, 12))
        self.sw_run = ttk.Button(c, text="RUN SWEEP", command=self.sweep_run)
        self.sw_run.pack(side="left")
        ttk.Button(c, text="Save CSV",
                   command=self.sweep_save).pack(side="left", padx=6)

        self.sw_mod_state = tk.StringVar(value="OUT1: off")
        ttk.Label(c, textvariable=self.sw_mod_state,
                  font=("TkDefaultFont", 9, "bold")).pack(side="left", padx=12)

        c2 = ttk.Frame(f)
        c2.grid(row=3, column=0, columnspan=6, sticky="w", pady=(0, 6))
        ttk.Label(c2, text="Light:").pack(side="left", padx=(0, 6))
        ttk.Button(c2, text="Shutter CLOSE (block the light)",
                   command=lambda: self.sweep_shutter(True)).pack(side="left")
        ttk.Button(c2, text="Shutter OPEN",
                   command=lambda: self.sweep_shutter(False)).pack(side="left",
                                                                   padx=6)
        self.sw_shutter_state = tk.StringVar(value="shutter: unknown")
        ttk.Label(c2, textvariable=self.sw_shutter_state,
                  font=("TkDefaultFont", 9, "bold")).pack(side="left", padx=12)
        ttk.Button(c2, text="Read state",
                   command=lambda: self.sweep_shutter(None)).pack(side="left")

        self.sw_status = tk.StringVar(value="idle")
        ttk.Label(f, textvariable=self.sw_status).grid(
            row=4, column=0, columnspan=6, sticky="w")

        self.sw_plot = Plot(f, height=300)
        self.sw_plot.grid(row=5, column=0, columnspan=6, sticky="nsew",
                          pady=(8, 0))
        f.rowconfigure(5, weight=1)
        for col in range(6):
            f.columnconfigure(col, weight=1)

    def sweep_shutter(self, close):
        """Open, close, or just read the laser's shutter.

        close=True closes it, False opens it, None only reads it back.

        This is the honest way to block the light. Blocking it by hand and
        remembering to do so is not: on 2026-08-28 a "control" run came back
        with the same amplitude as the live run because the checkbox had been
        ticked but the beam was never blocked, and nothing in the result could
        have revealed that.

        Opens its own short-lived connection, so it works whether or not a
        sweep is running. Every write is read back -- a shutter command that
        silently did nothing is exactly the failure this is meant to remove.
        """
        p = self._sweep_params()
        if p is None:
            return
        if self.st.laser is not None:
            return messagebox.showerror(
                "Laser already connected",
                "Disconnect on the Laser tab first -- this instrument is "
                "unreliable with more than one connection.")
        if close and not messagebox.askokcancel(
                "Close the shutter",
                "Close the laser's shutter?\n\nNo light will leave the "
                "instrument until it is opened again."):
            return
        if close is False and not messagebox.askokcancel(
                "Open the shutter",
                "OPEN the laser's shutter?\n\nLight will reach whatever is "
                "connected to the output fibre."):
            return

        def go():
            d = TSL775.connect("lan", host=p["ip"], timeout=5.0)
            try:
                if close is not None:
                    d.write(":POW:SHUT %d" % (1 if close else 0))
                    time.sleep(0.5)
                return d.query(":POW:SHUT?").strip().lstrip("+")
            finally:
                d.close()

        def done(state):
            if state == "1":
                self.sw_shutter_state.set("shutter: CLOSED (no light)")
            elif state == "0":
                self.sw_shutter_state.set("shutter: OPEN (light out)")
            else:
                self.sw_shutter_state.set("shutter: ? (%s)" % state)
            self.log("laser shutter read back as %s" % state)

        self.submit("shutter", go, done)

    def _refresh_mod_state(self):
        on = 1 in self.st.outputs_on
        self.sw_mod_state.set("OUT1: ON" if on else "OUT1: off")

    def sweep_mod_on(self):
        """Turn the drive on and LEAVE it on, so it can be looked at.

        RUN SWEEP sets the drive itself and disarms it afterwards, which is
        right for a measurement and wrong for aligning an AOM or putting a
        scope on the amplifier. This is the standalone switch.
        """
        rp = self._need_board()
        if not rp:
            return
        p = self._sweep_params()
        if p is None:
            return
        if not messagebox.askokcancel(
                "Enable the modulation",
                "Enable OUT1 and LEAVE it on?\n\n"
                "Carrier      %.6f MHz\n"
                "Modulation   %.4f kHz  (AM, depth 1)\n"
                "Amplitude    %s V\n\n"
                "This reaches the amplifier and the modulator. It stays on "
                "until you press Modulation OFF, close the GUI, or run a "
                "sweep (which disarms it at the end)."
                % (p["carrier"] / 1e6, p["mod"] / 1e3, p["amp"])):
            return self.log("modulation enable cancelled")

        def go():
            return rp.setup_am_generator(carrier=p["carrier"],
                                         modulation=p["mod"],
                                         amplitude=p["amp"], depth=1.0,
                                         channel=1)

        def done(table):
            self.st.outputs_on.add(1)
            self._refresh_outputs()
            self._refresh_mod_state()
            # The ASG snaps both frequencies onto the fs/16384 grid, so what
            # is actually being generated is not exactly what was typed.
            self.log("OUT1 ON: carrier %.6f MHz, modulation %.4f kHz "
                     "(snapped to the ASG grid), %s V"
                     % (table.carrier / 1e6, table.modulation / 1e3, p["amp"]))
            self.sw_status.set("modulation on -- OUT1 %.4f kHz AM"
                               % (table.modulation / 1e3))

        self.submit("modulation on", go, done)

    def sweep_mod_off(self):
        rp = self.st.rp
        if rp is None:
            self.st.outputs_on.clear()
            self._refresh_mod_state()
            return self.log("no board connected, so nothing to disable")

        def go():
            for ch in (1, 2):
                rp.write("OUTPUT%d:STATE OFF" % ch)
            return True

        def done(_v):
            self.st.outputs_on.clear()
            self._refresh_outputs()
            self._refresh_mod_state()
            self.log("OUT1/OUT2 disabled")
            self.sw_status.set("modulation off")

        self.submit("modulation off", go, done)

    def _sweep_params(self):
        try:
            return dict(
                carrier=float(self.sw_carrier.get()) * 1e6,
                mod=float(self.sw_mod.get()) * 1e3,
                amp=float(self.sw_amp.get()),
                ip=self.sw_ip.get().strip(),
                start=float(self.sw_start.get()),
                stop=float(self.sw_stop.get()),
                speed=float(self.sw_speed.get()),
                step=float(self.sw_step.get()),
                loss=float(self.sw_loss.get()),
                maxdbm=float(self.sw_maxdbm.get()),
            )
        except ValueError as e:
            messagebox.showerror("Sweep settings", "Not a number: %s" % e)
            return None

    def sweep_run(self):
        rp = self._need_board()
        if not rp:
            return
        p = self._sweep_params()
        if p is None:
            return
        if self.st.laser is not None:
            return messagebox.showerror(
                "Laser already connected",
                "The Laser tab holds a connection. This instrument is "
                "unreliable with more than one, and roughly one reconnect in "
                "four fails outright.\n\nDisconnect on the Laser tab first.")

        n_points = int(round((p["stop"] - p["start"]) / p["step"])) + 1
        sweep_s = (n_points - 1) * (p["step"] / p["speed"])
        msg = (
            "This DRIVES OUT1 into the amplifier and the modulator, and "
            "sweeps the laser.\n\n"
            "OUT1     %.6f MHz, AM at %.4f kHz, depth 1, %s V\n"
            "Laser    %g-%g nm at %g nm/s (%.3f s)\n"
            "Trigger  every %g nm -> %d points, %.1f us apart\n"
            "Demod    AT %.4f kHz\n\n" % (
                p["carrier"] / 1e6, p["mod"] / 1e3, p["amp"],
                p["start"], p["stop"], p["speed"], sweep_s,
                p["step"], n_points, p["step"] / p["speed"] * 1e6,
                p["mod"] / 1e3))
        if self.sw_blocked.get():
            msg += ("CONTROL RUN: the shutter will be CLOSED in software for "
                    "this run and restored afterwards. You do not need to "
                    "block the beam by hand.\n\n")
        if not messagebox.askokcancel("Run the sweep",
                                      msg + "Light goes somewhere. Continue?"):
            return self.log("sweep cancelled")

        self.sw_run.configure(state="disabled")
        self.sw_status.set("running...")
        p["blocked"] = bool(self.sw_blocked.get())
        self.submit("linear sweep", lambda: self._sweep_job(rp, p),
                    self._sweep_done)

    def _sweep_job(self, rp, p):
        """Runs on the worker thread. Returns everything the UI needs."""
        fs = BASE_SAMPLE_RATE / 8
        _n_settle, t_settle = settling_points(5000.0, fs=fs)
        tail = recommended_tail(5000.0, fs=fs)
        preroll = int(t_settle * 1.1 * fs)
        n_points = int(round((p["stop"] - p["start"]) / p["step"])) + 1
        sweep_s = (n_points - 1) * (p["step"] / p["speed"])
        n = min(int(np.ceil((preroll / fs + sweep_s + tail) * fs)), 33554432)

        d = TSL775.connect("lan", host=p["ip"], timeout=5.0)
        before = None
        cap = {}
        try:
            level = float(d.query(":POWer:LEVel?"))
            # What the DETECTOR sees, which is the number that matters. The
            # laser's own setpoint says nothing without the splitters between
            # them. The detector saturates near 0.96 mW = 0 dBm; above that it
            # stops being linear, and a saturated detector still produces a
            # smooth, plausible, wrong trace.
            at_det = level - p["loss"]
            if at_det > p["maxdbm"]:
                raise RuntimeError(
                    "laser is at %.2f dBm and you have declared %.1f dB of "
                    "path loss, so about %.2f dBm (%.3f mW) reaches the "
                    "detector -- above the %.2f dBm limit. Lower the laser, or "
                    "correct the path loss if it is really lossier than that."
                    % (level, p["loss"], at_det, 10 ** (at_det / 10),
                       p["maxdbm"]))
            before = {k: d.query(q) for k, q in (
                ("start", ":WAV:SWE:STAR?"), ("stop", ":WAV:SWE:STOP?"),
                ("speed", ":WAV:SWE:SPE?"), ("cycles", ":WAV:SWE:CYCL?"),
                ("mode", ":WAV:SWE:MOD?"), ("trig", ":TRIG:OUTP?"),
                ("trigstep", ":TRIG:OUTP:STEP?"))}
            shutter_before = d.query(":POW:SHUT?").strip().lstrip("+")
            if shutter_before == "1" and not p.get("blocked"):
                raise RuntimeError(
                    "the laser's shutter is CLOSED, so this run would see no "
                    "light at all -- a control run wearing the label of a real "
                    "one, and nothing in the trace would show it. Press "
                    "'Shutter OPEN', or tick CONTROL RUN if that is what you "
                    "meant.")
            if p.get("blocked"):
                # A REAL control. The checkbox used to only label the output
                # file, which meant a control run that forgot to block the beam
                # was indistinguishable from a real one -- and on 2026-08-28 a
                # "control" came back with the same 300 mV as the live run,
                # which is exactly what that looks like.
                d.write(":POW:SHUT 1")
                time.sleep(0.5)
                if d.query(":POW:SHUT?").strip().lstrip("+") != "1":
                    raise RuntimeError(
                        "asked for a CONTROL run but the shutter did not "
                        "close; refusing rather than reporting a control that "
                        "was not one")
            d.write(":POW:STAT 1")
            time.sleep(2.0)                        # laser ON before configuring
            d.write(":WAV:SWE 0")
            time.sleep(0.5)                        # explicit stop, or it never starts
            d.write(":WAV:SWE:SPE %g" % p["speed"])   # speed first: range depends on it
            d.write(":WAV:SWE:STAR %.9E" % (p["start"] * 1e-9))   # METRES
            d.write(":WAV:SWE:STOP %.9E" % (p["stop"] * 1e-9))
            d.write(":WAV:SWE:MOD 1")              # continuous, ONE WAY
            d.write(":WAV:SWE:CYCL 1")
            d.write(":TRIG:OUTP 3")                # Step -- or nothing is logged
            d.write(":TRIG:OUTP:STEP %.9E" % (p["step"] * 1e-9))
            if d.query(":TRIG:OUTP?").strip().lstrip("+") != "3":
                raise RuntimeError(":TRIG:OUTP is not 3; no train and no log")

            rp.setup_acquisition(decimation=8, coupling="DC", gain="LV")
            rp.setup_channel(1, coupling="AC", gain="LV")   # detector is unipolar
            rp.setup_channel(2, gain="HV")                  # 3.3 V trigger
            table = rp.setup_am_generator(
                carrier=p["carrier"], modulation=p["mod"],
                amplitude=p["amp"], depth=1.0, channel=1)

            def grab():
                try:
                    ch = rp.acquire_deep_fast(
                        n_samples=n, decimation=8, channels=(1, 2),
                        trigger="CH2_PE", trigger_level=1.0,
                        preroll_samples=preroll, trigger_timeout=120.0)
                    cap["det"], cap["trg"] = ch[0], ch[1]
                except Exception as e:                       # noqa: BLE001
                    cap["error"] = e

            th = threading.Thread(target=grab, daemon=True)
            th.start()
            time.sleep(3.0)                        # let the capture arm first
            d.write(":WAV:SWE 1")
            t0 = time.time()
            while time.time() - t0 < 30.0:
                if (d.query(":WAV:SWE?").strip().lstrip("+") == "0"
                        and time.time() - t0 > 2):
                    break
                time.sleep(0.1)
            th.join(timeout=180.0)
            if "error" in cap:
                raise cap["error"]
            wl = np.asarray(d.query_wavelength_log(scpi=True), dtype=float)
        finally:
            try:
                d.write(":WAV:SWE 0")
                d.write(":POW:STAT 0")
                if p.get("blocked"):
                    d.write(":POW:SHUT %s" % shutter_before)
                if before:
                    for cmd, key in ((":WAV:SWE:STAR", "start"),
                                     (":WAV:SWE:STOP", "stop"),
                                     (":WAV:SWE:SPE", "speed"),
                                     (":WAV:SWE:CYCL", "cycles"),
                                     (":WAV:SWE:MOD", "mode"),
                                     (":TRIG:OUTP", "trig"),
                                     (":TRIG:OUTP:STEP", "trigstep")):
                        try:
                            d.write("%s %s" % (cmd, before[key].strip()))
                        except Exception:                    # noqa: BLE001
                            pass
            except Exception:                                # noqa: BLE001
                pass
            d.close()
            try:
                for ch in (1, 2):
                    rp.write("OUTPUT%d:STATE OFF" % ch)
            except Exception:                                # noqa: BLE001
                pass

        det_counts = np.asarray(cap["det"], dtype=float)
        trg = np.asarray(cap["trg"], dtype=float)
        # Clipping has to be judged in COUNTS, before scaling -- the rail is a
        # property of the converter, not of the volts it represents.
        dclip = int(np.count_nonzero((det_counts >= ADC_COUNT_MAX)
                                     | (det_counts <= ADC_COUNT_MIN)))
        swing_counts = float(np.percentile(det_counts, 99)
                             - np.percentile(det_counts, 1))
        # IN1 is on LV, so this is the scale that applies. Everything derived
        # below -- amplitude, the plot, the CSV -- is then in VOLTS rather than
        # raw converter counts, which mean nothing outside this program.
        det = det_counts / ADC_COUNTS_PER_V_LV
        lo, hi = np.percentile(trg, 1), np.percentile(trg, 99)
        if hi - lo < 50:
            raise RuntimeError(
                "IN2 swings only %.1f counts -- nothing is arriving on the "
                "trigger channel. Is the BNC in analog IN2 rather than the "
                "external-trigger socket?" % (hi - lo))
        # Unipolar in COUNTS, so reduce_sweep's 0.0 default would find no edges.
        thr = float(0.5 * (lo + hi))
        red = reduce_sweep(det, trg, fs, wl, f_ref=p["mod"], output_rate=5000.0,
                           trigger_threshold=thr, trigger_polarity="rising",
                           nominal_step=p["step"] / p["speed"])
        return dict(red=red, det=det, trg=trg, wl=wl, table=table,
                    clipped=dclip, swing_counts=swing_counts,
                    blocked=bool(p.get("blocked")),
                    shutter_before=shutter_before,
                    swing_v=swing_counts / ADC_COUNTS_PER_V_LV)

    def _sweep_done(self, out):
        self.sw_run.configure(state="normal")
        # _sweep_job disarms the outputs in its finally, so whatever the
        # indicator said before, OUT1 is off now.
        self.st.outputs_on.discard(1)
        self._refresh_outputs()
        self._refresh_mod_state()
        if not isinstance(out, dict):
            self.sw_status.set("failed -- see the Log tab")
            return
        red = out["red"]
        self.st.reduction = red
        self.st.result = red.result
        self.st.wavelengths = out["wl"]
        w, a = red.trace.dropna()
        self.sw_plot.show(w * 1e9, a, xlabel="wavelength (nm)",
                          ylabel="amplitude (V)",
                          xfmt=lambda v: "%.1f" % v,
                          yfmt=lambda v: _eng(v) + "V")
        tag = ("CONTROL (shutter CLOSED in software)" if out.get("blocked")
               else "beam")
        self.sw_status.set(
            "%s: %d points | IN1 swing %s V (%.0f counts)%s | amplitude "
            "median %sV, max %sV" % (
                tag, w.size, _eng(out["swing_v"]), out["swing_counts"],
                "  CLIPPED!" if out["clipped"] else "",
                _eng(float(np.median(a))), _eng(float(a.max()))))
        self.log("linear sweep done (%s): drive %.6f MHz AM %.4f kHz; "
                 "shutter was %s at the start; axis from %s"
                 % (tag, out["table"].carrier / 1e6,
                    out["table"].modulation / 1e3,
                    "CLOSED" if out.get("shutter_before") == "1" else "open",
                    red.table_source))
        if out.get("blocked"):
            self.log("This is the PICKUP FLOOR, measured with no light. A real "
                     "optical signal has to stand clear of it.")
        if out["clipped"]:
            self.log("WARNING: %d IN1 samples at the ADC rail. Every amplitude "
                     "above is derived from a flattened waveform. Reduce the "
                     "laser power." % out["clipped"])

    def sweep_save(self):
        red = self.st.reduction
        if red is None:
            return messagebox.showinfo("Save", "Run a sweep first.")
        tag = "blocked" if self.sw_blocked.get() else "beam"
        path = filedialog.asksaveasfilename(
            defaultextension=".csv", initialfile="linear_%s.csv" % tag,
            filetypes=[("CSV", "*.csv")])
        if not path:
            return
        write_trace_csv(path, red.trace.wavelength, red.trace.amplitude,
                        metadata=red.metadata())
        self.log("wrote %s" % path)

    def _build_log(self):
        f = ttk.Frame(self.nb, padding=10)
        self.nb.add(f, text="Log")
        self.tab_log = f
        bar = ttk.Frame(f)
        bar.pack(fill="x", pady=(0, 6))
        ttk.Button(bar, text="Save log", command=self.save_log).pack(
            side="left")
        ttk.Button(bar, text="Clear", command=self.clear_log).pack(side="left",
                                                                   padx=6)
        ttk.Label(bar, wraplength=680, foreground="#606060",
                  text="Every command and reply. On this project an "
                       "unsupported command returns zero bytes exactly like a "
                       "supported one, so this is the first place to look."
                  ).pack(side="left", padx=12)
        self.logbox = tk.Text(f, wrap="word", font=("TkFixedFont", 9),
                              state="disabled")
        self.logbox.pack(fill="both", expand=True)

    def save_log(self):
        path = filedialog.asksaveasfilename(defaultextension=".txt",
                                            filetypes=[("Text", "*.txt")])
        if path:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(self.logbox.get("1.0", "end"))
            self.log(f"log written to {path}")

    def clear_log(self):
        self.logbox.configure(state="normal")
        self.logbox.delete("1.0", "end")
        self.logbox.configure(state="disabled")

    # -- shutdown

    def on_close(self):
        """Outputs off and connections closed, on every exit path.

        H7.4 failed on real hardware because an unhandled exception left the
        generator driving. A window with a close button is the same hazard
        wearing a friendlier face, so this runs INLINE rather than being
        queued behind whatever the worker happens to be doing.
        """
        rp, laser = self.st.rp, self.st.laser
        try:
            if rp is not None:
                rp.close()          # disables both outputs
        except Exception as exc:
            print(f"WARNING: could not disarm outputs on exit: {exc}",
                  file=sys.stderr)
        try:
            if laser is not None:
                laser.close()
        except Exception:
            pass
        self.root.destroy()


def main():
    root = tk.Tk()
    for theme in ("vista", "clam"):
        try:
            ttk.Style().theme_use(theme)
            break
        except tk.TclError:
            continue
    BenchGui(root)
    root.mainloop()


if __name__ == "__main__":
    main()
