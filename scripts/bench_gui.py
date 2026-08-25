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

from rp_lockin import (  # noqa: E402
    demodulate,
    find_trigger_edges,
    make_trigger_sequence,
    plan_two_tone_grid,
    synthesise_dut_output,
    write_raw_npz,
    write_trace_csv,
)
from rp_lockin.constants import BASE_SAMPLE_RATE  # noqa: E402
from rp_lockin.hardware import RedPitaya  # noqa: E402
from rp_lockin.santec import SantecTSL  # noqa: E402

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
        self.bind("<Configure>", lambda _e: self._draw())
        self.bind("<Motion>", self._hover)
        self.bind("<Leave>", lambda _e: self._clear_readout())

    def show(self, x, y, xlabel="", ylabel=""):
        self.x = np.asarray(x, dtype=float).ravel()
        self.y = np.asarray(y, dtype=float).ravel()
        self.xlabel, self.ylabel = xlabel, ylabel
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
                             text=_eng(ymin + frac * (ymax - ymin)))
            gx = x0 + frac * (x1 - x0)
            self.create_line(gx, y0, gx, y1, fill="#ececec")
            self.create_text(gx, y1 + 6, anchor="n", font=("TkDefaultFont", 7),
                             text=_eng(xmin + frac * (xmax - xmin)))

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
        readout = f"x={_eng(self.x[i])}   y={_eng(self.y[i])}"
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
                  text="Builds a synthetic detector record: a tone at the "
                       "lock-in frequency with a Lorentzian envelope, plus a "
                       "trigger train on CH2. Exercises capture handling, "
                       "demodulation, the plot and the CSV with nothing "
                       "connected. The envelope is a stand-in, not DUT "
                       "physics.").grid(row=0, column=0, columnspan=6,
                                        sticky="w", pady=(0, 6))
        self.sim_ms = tk.StringVar(value="200")
        self.sim_noise = tk.StringVar(value="0.000011")
        ttk.Label(sim, text="Duration (ms)").grid(row=1, column=0, sticky="w")
        ttk.Entry(sim, textvariable=self.sim_ms, width=8).grid(row=1, column=1,
                                                               padx=6)
        ttk.Label(sim, text="Noise rms (V)").grid(row=1, column=2, sticky="w",
                                                  padx=(14, 0))
        ttk.Entry(sim, textvariable=self.sim_noise, width=10).grid(
            row=1, column=3, padx=6)
        ttk.Button(sim, text="Simulate", command=self.simulate).grid(
            row=1, column=4, padx=18)

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

        def go():
            sig, _truth = synthesise_dut_output(
                PLAN.difference, dur, fs=fs, noise_rms=noise, amplitude=0.2,
                seed=1)
            # Trigger every 200 us -- the 5000-point spacing a real 1 s sweep
            # produces. The first edge is deliberately NOT at t=0, so anything
            # assuming the record starts at the trigger shows up here.
            edges = list(np.arange(0.1 * dur, dur, 200e-6))
            return sig, make_trigger_sequence(dur, edges, fs=fs), fs

        def done(v):
            sig, trig, fs_used = v
            self._store_raw({1: sig, 2: trig}, fs_used)
            self.log(f"simulated {sig.size} samples at "
                     f"{fs_used / 1e6:.3f} MS/s, noise {noise * 1e6:.1f} uV "
                     f"rms, lock-in {PLAN.difference / 1e3:.3f} kHz")

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
            self.log(f"{len(edges)} edges; first at {edges[0] * 1e3:.4f} ms; "
                     f"mean step {np.mean(step) * 1e6:.3f} us "
                     f"(sd {np.std(step) * 1e9:.1f} ns)")

        self.submit("find edges", lambda: find_trigger_edges(trig, fs), done)

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

        def done(res):
            self.st.result = res
            spacing = (res.t[1] - res.t[0]) * 1e6 if res.t.size > 1 else 0.0
            self.demod_info.set(
                f"{res.t.size} points   spacing {spacing:.3f} us   "
                f"bandwidth {res.bandwidth:.1f} Hz   "
                f"{res.settle} settling samples trimmed   "
                f"t = {res.t[0] * 1e3:.3f} to {res.t[-1] * 1e3:.3f} ms")
            self.log(f"demodulated at {res.f_ref:.3f} Hz -> {res.t.size} "
                     f"points at {res.fs_out:.1f} Sa/s")
            self._redraw_trace()

        self.submit("demodulate",
                    lambda: demodulate(sig, fs, f_ref, output_rate=rate), done)

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
        self.trace_plot.show(self.st.result.t, y, "time (s)", label)
        self._cursor_readout(None)

    def _cursor_readout(self, index):
        """Fill X/Y/R/theta -- at `index` while hovering, else trace means."""
        res = self.st.result
        if res is None:
            return
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
            self.readout_mode.set(
                f"point {i} of {res.t.size}, t = {res.t[i] * 1e3:.4f} ms")
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
        amp = res.amplitude()

        def go():
            # There is no laser log behind this trace, so the wavelength column
            # is written EMPTY rather than filled with something plausible.
            # A time-indexed trace wearing a wavelength column would be the
            # exact silent failure the whole wavelength design guards against.
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
        laser = self._need_laser()
        if not laser:
            return

        def done(wl):
            self.log(f"wavelength log: {wl.size} points, "
                     f"{wl.min() * 1e9:.4f} to {wl.max() * 1e9:.4f} nm")
            self.trace_plot.show(np.arange(wl.size), wl * 1e9,
                                 "log index", "wavelength (nm)")
            self.nb.select(3)

        self.log("laser <- :READout:DATa?")
        self.submit("read wavelength log", laser.read_wavelengths, done)

    # -- tab: log

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
