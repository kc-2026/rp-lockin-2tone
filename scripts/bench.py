#!/usr/bin/env python3
"""
The bench: independent instrument panels that compose into a sweep.

    python scripts/bench.py

Replaces the tabbed `bench_gui.py`, which is kept working alongside it until
this one has earned the bench. What is different, and why:

GRANULARITY. Every panel does ONE thing to ONE instrument and works on its
own. Arm a capture, fire a sweep by hand, read the log ten minutes later,
demodulate the same record three times at different frequencies without
touching hardware. The old Linear Sweep tab could only do all of it or none.

A WORKSPACE. Panels do not call each other; they read and write named slots --
capture, laser log, lock-in, trace. That is what makes the steps independent,
and it is why re-demodulating costs nothing.

ONE IMPLEMENTATION. A sequence runs the same functions the buttons run, from
`_bench_ops`. The old Linear Sweep tab was a second implementation of the
laser setup and the reduction, so every fix had to be made twice, and twice it
was not.

TWO WORKERS, one per instrument. The board and the laser are independent, and
a shared queue makes them falsely dependent: arming a capture blocks until a
trigger arrives, so a single worker leaves the sweep that would PROVIDE that
trigger stuck behind it. That is not a detail -- with one queue, manual
composition cannot work at all.

STATE IS MEASURED, NEVER INFERRED. The header polls the board and the laser.
An indicator that remembers which buttons were pressed goes stale the moment
anything changes the instrument from outside this program, and an indicator
that lies about a physical output is worse than none.

SAFETY lives with the capability, not the recipe: the Drive panel owns the
confirmation and the outputs-off guarantee, so a sequence gets both for free
and cannot route around them.
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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "src"))

import _bench_ops as ops                                    # noqa: E402
from _bench_widgets import Plot, ScrollFrame, Worker, eng, field as fld  # noqa: E402
from rp_lockin.hardware import RedPitaya                    # noqa: E402
from rp_lockin.output import write_raw_npz, write_trace_csv  # noqa: E402
from tsl775 import TSL775                                   # noqa: E402

DEFAULT_MOD_HZ = 60 * ops.ASG_GRID          # 915.527 kHz -- see the Drive panel


@dataclass
class Workspace:
    """What is currently in memory, and when each piece was made.

    The slots have a dependency order -- capture -> lock-in -> trace, with the
    laser log feeding the trace as well -- and the setters enforce it by
    CLEARING what downstream of them is now stale.

    That is not tidiness. Re-demodulating a capture at a different frequency
    used to update the lock-in and leave the old trace sitting beside it, so
    the workspace showed a 915 kHz trace next to a 1.83 MHz lock-in as though
    both were current. Two numbers on screen that cannot both be true is
    exactly the kind of quiet wrongness this project keeps finding.
    """

    capture: dict = None
    laser_log: np.ndarray = None
    lockin: object = None
    reduction: object = None
    stamps: dict = field(default_factory=dict)
    meta: dict = field(default_factory=dict)

    def _stamp(self, key):
        self.stamps[key] = time.time()

    def set_capture(self, cap):
        self.capture = cap
        self._stamp("capture")
        self.lockin = None                  # both were derived from the old
        self.reduction = None               # record and no longer belong to it
        self.stamps.pop("lock-in", None)
        self.stamps.pop("trace", None)

    def set_log(self, wl):
        self.laser_log = wl
        self._stamp("laser log")
        self.reduction = None               # the axis came from the old log
        self.stamps.pop("trace", None)

    def set_lockin(self, r):
        self.lockin = r
        self._stamp("lock-in")
        self.reduction = None               # the trace used a different f_ref
        self.stamps.pop("trace", None)

    def set_reduction(self, red):
        """Map produces both at once, so they are consistent by construction."""
        self.reduction = red
        self.lockin = red.result
        self._stamp("trace")
        self._stamp("lock-in")

    def clear(self):
        self.capture = self.laser_log = self.lockin = self.reduction = None
        self.stamps.clear()

    def age(self, key):
        t = self.stamps.get(key)
        return "" if t is None else time.strftime("  @%H:%M:%S",
                                                  time.localtime(t))

    def summary(self):
        rows = []
        if self.capture:
            c = self.capture
            rows.append(("capture", f"{c['ch1'].size / 1e6:.1f} Msa x2 @ "
                                    f"{c['fs'] / 1e6:.3f} MS/s, trig "
                                    f"{c['trigger']}" + self.age("capture")))
        else:
            rows.append(("capture", "-"))
        if self.laser_log is not None:
            w = self.laser_log
            rows.append(("laser log", f"{w.size} pts, {w[0] * 1e9:.3f} -> "
                                      f"{w[-1] * 1e9:.3f} nm"
                                      + self.age("laser log")))
        else:
            rows.append(("laser log", "-"))
        if self.lockin is not None:
            rows.append(("lock-in", f"{self.lockin.f_ref / 1e3:.4f} kHz, "
                                    f"{self.lockin.t.size} pts @ "
                                    f"{self.lockin.fs_out:.0f} Sa/s"
                                    + self.age("lock-in")))
        else:
            rows.append(("lock-in", "-"))
        if self.reduction is not None:
            w, a = self.reduction.trace.dropna()
            rows.append(("trace", f"{w.size} pts, {np.median(a) * 1e3:.3f} mV "
                                  f"median, {a.max() * 1e3:.3f} mV max"
                                  + self.age("trace")))
        else:
            rows.append(("trace", "-"))
        return rows


class Bench:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.ws = Workspace()
        self.rp = None
        self.laser = None
        self.results: queue.Queue = queue.Queue()
        self.board = Worker(self.results, "board")
        self.lasw = Worker(self.results, "laser")
        self.board.start()
        self.lasw.start()
        self._seq_running = False

        root.title("rp-lockin-2tone -- bench")
        root.geometry("1280x860")
        root.minsize(1080, 700)
        root.protocol("WM_DELETE_WINDOW", self.on_close)

        self._build_header()
        body = ttk.Frame(root)
        body.pack(fill="both", expand=True, padx=6, pady=(0, 4))
        self.rail = ScrollFrame(body, width=340)
        self.rail.pack(side="left", fill="y")
        right = ttk.Frame(body)
        right.pack(side="left", fill="both", expand=True, padx=(8, 0))
        self._build_plot(right)
        self._build_workspace(right)
        self._build_log()

        for build in (self._panel_board, self._panel_drive, self._panel_laser,
                      self._panel_sweep, self._panel_acquire,
                      self._panel_demod, self._panel_map, self._panel_export,
                      self._panel_sequences):
            build(self.rail.body)

        self.log("Bench started. Nothing is connected.")
        self.log(f"Default modulation {DEFAULT_MOD_HZ / 1e3:.3f} kHz "
                 f"= 60 ASG grid steps.")
        self.root.after(80, self._pump)
        self.root.after(600, self._poll)

    # ------------------------------------------------------------- plumbing

    def log(self, msg):
        self.txt.configure(state="normal")
        self.txt.insert("end", f"{time.strftime('%H:%M:%S')}  {msg}\n")
        self.txt.see("end")
        self.txt.configure(state="disabled")

    def submit(self, worker, name, fn, on_done=None, on_error=None):
        worker.submit(name, fn, on_done, on_error)

    def _pump(self):
        try:
            while True:
                kind, payload = self.results.get_nowait()
                if kind == "busy":
                    who, what = payload
                    self.status.set(f"{who}: {what}")
                else:
                    job, value, exc = payload
                    if exc is not None:
                        self.log(f"FAILED {job.name}: "
                                 f"{exc.__class__.__name__}: {exc}")
                        if job.on_error:
                            try:
                                job.on_error(exc)
                            except Exception:            # noqa: BLE001
                                pass
                        messagebox.showerror(job.name, str(exc))
                    elif job.on_done:
                        job.on_done(value)
                    if not (self.board.busy or self.lasw.busy):
                        self.status.set("idle")
        except queue.Empty:
            pass
        self.root.after(80, self._pump)

    def _poll(self):
        """Measured state, once a second, skipped while an instrument is busy."""
        try:
            if self.rp is not None and not self.board.busy:
                def go():
                    return ops.drive_state(self.rp, 1)

                self.submit(self.board, "poll OUT1", go,
                            lambda on: self.h_out.set(
                                f"OUT1 {'ON' if on else 'off'}"),
                            lambda _e: None)
            elif self.rp is None:
                self.h_out.set("OUT1 --")
            if self.laser is not None and not self.lasw.busy:
                def go2():
                    return ops.laser_state(self.laser)

                self.submit(self.lasw, "poll laser", go2, self._show_laser,
                            lambda _e: None)
        finally:
            self.root.after(1000, self._poll)

    def _show_laser(self, st):
        try:
            dbm = float(st.get("power_dbm", "nan"))
        except ValueError:
            dbm = float("nan")
        sh = {"+1": "CLOSED", "+0": "OPEN"}.get(st.get("shutter", ""), "?")
        ld = {"+1": "ON", "+0": "off"}.get(st.get("ld", ""), "?")
        sw = {"+0": "idle", "+1": "RUNNING", "+3": "standby",
              "+4": "preparing"}.get(st.get("sweep", ""), "?")
        self.h_laser.set(f"laser {dbm:+.2f} dBm | LD {ld} | shutter {sh}")
        self.h_sweep.set(f"sweep {sw}")

    # --------------------------------------------------------------- header

    def _build_header(self):
        h = ttk.Frame(self.root, padding=(8, 6))
        h.pack(fill="x")
        self.h_board = tk.StringVar(value="board --")
        self.h_out = tk.StringVar(value="OUT1 --")
        self.h_laser = tk.StringVar(value="laser --")
        self.h_sweep = tk.StringVar(value="sweep --")
        self.h_armed = tk.StringVar(value="")
        bold = ("TkDefaultFont", 9, "bold")
        for var in (self.h_board, self.h_out, self.h_laser, self.h_sweep):
            ttk.Label(h, textvariable=var, font=bold).pack(side="left",
                                                           padx=(0, 18))
        ttk.Label(h, textvariable=self.h_armed, font=bold,
                  foreground="#a04000").pack(side="left", padx=(0, 18))
        ttk.Button(h, text="ALL OUTPUTS OFF",
                   command=self.all_off).pack(side="right")
        self.status = tk.StringVar(value="idle")
        ttk.Label(h, textvariable=self.status,
                  foreground="#606060").pack(side="right", padx=12)
        ttk.Separator(self.root, orient="horizontal").pack(fill="x")

    def _build_plot(self, parent):
        f = ttk.LabelFrame(parent, text="Plot", padding=6)
        f.pack(fill="both", expand=True)
        bar = ttk.Frame(f)
        bar.pack(fill="x")
        self.plot_what = tk.StringVar(value="trace")
        ttk.Label(bar, text="show:").pack(side="left")
        cb = ttk.Combobox(bar, textvariable=self.plot_what, width=22,
                          state="readonly",
                          values=("trace (amplitude vs wavelength)",
                                  "lock-in (amplitude vs time)",
                                  "raw IN1 (volts vs time)",
                                  "raw IN2 (counts vs time)"))
        cb.pack(side="left", padx=6)
        cb.set("trace (amplitude vs wavelength)")
        ttk.Button(bar, text="Redraw", command=self.redraw).pack(side="left")
        ttk.Button(bar, text="Fit",
                   command=lambda: self.plot.reset_view()).pack(side="left",
                                                                padx=4)
        ttk.Label(bar, text="wheel = zoom X | shift+wheel = Y | "
                            "ctrl+wheel = both | drag = pan | double-click = fit",
                  foreground="#666").pack(side="left", padx=10)
        self.plot = Plot(f, height=340)
        self.plot.pack(fill="both", expand=True, pady=(6, 0))

    def _build_workspace(self, parent):
        f = ttk.LabelFrame(parent, text="Workspace", padding=6)
        f.pack(fill="x", pady=(6, 0))
        self.ws_vars = {}
        for i, key in enumerate(("capture", "laser log", "lock-in", "trace")):
            ttk.Label(f, text=key, width=10).grid(row=i, column=0, sticky="w")
            v = tk.StringVar(value="-")
            self.ws_vars[key] = v
            ttk.Label(f, textvariable=v, foreground="#333").grid(
                row=i, column=1, sticky="w")
        ttk.Button(f, text="Clear all",
                   command=self.clear_workspace).grid(row=0, column=2,
                                                      rowspan=4, sticky="e")
        f.columnconfigure(1, weight=1)

    def _build_log(self):
        f = ttk.LabelFrame(self.root, text="Log", padding=4)
        f.pack(fill="x", padx=6, pady=(0, 6))
        self.txt = tk.Text(f, height=7, wrap="word", state="disabled",
                           font=("TkFixedFont", 8))
        sb = ttk.Scrollbar(f, command=self.txt.yview)
        self.txt.configure(yscrollcommand=sb.set)
        self.txt.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

    def refresh_workspace(self):
        for key, val in self.ws.summary():
            self.ws_vars[key].set(val)

    def clear_workspace(self):
        self.ws.clear()
        self.refresh_workspace()
        self.plot.clear()
        self.log("workspace cleared")

    def _time_origin(self):
        """Where the sweep began in this record, and how to label the axis.

        Display only. The stored numbers stay referenced to the START OF THE
        RECORD, because the wavelength mapping is built on that and this
        project has been bitten more than once by an offset that looked
        entirely normal. Shifting the PICTURE costs nothing; shifting the data
        would put two conventions in play.

        Sweep-relative is the more readable of the two: negative time is
        obviously the pre-roll, 0 is the first trigger, and the points with no
        wavelength explain themselves instead of looking like lost data.
        """
        cap = self.ws.capture or {}
        edge = cap.get("first_edge")
        if self.ws.reduction is not None:
            edge = self.ws.reduction.first_edge
        if edge is None:
            return 0.0, "time from RECORD start (s) -- no trigger in this record"
        return float(edge), "time from SWEEP start (s)"

    def redraw(self):
        what = self.plot_what.get()
        try:
            if what.startswith("trace"):
                if self.ws.reduction is None:
                    return self.log("no trace: run Map first")
                w, a = self.ws.reduction.trace.dropna()
                self.plot.show(w * 1e9, a, "wavelength (nm)", "amplitude (V)",
                               xfmt=lambda v: f"{v:.1f}",
                               yfmt=lambda v: eng(v, "V"))
            elif what.startswith("lock-in"):
                if self.ws.lockin is None:
                    return self.log("no lock-in: run Demodulate first")
                r = self.ws.lockin
                t0, label = self._time_origin()
                self.plot.show(r.t - t0, r.amplitude(), label, "amplitude (V)",
                               yfmt=lambda v: eng(v, "V"))
            elif what.startswith("raw IN1"):
                if not self.ws.capture:
                    return self.log("no capture")
                c = self.ws.capture
                t0, label = self._time_origin()
                t = np.arange(c["ch1"].size) / c["fs"] - t0
                self.plot.show(t, ops.volts(c["ch1"]), label, "IN1 (V)",
                               yfmt=lambda v: eng(v, "V"))
            else:
                if not self.ws.capture:
                    return self.log("no capture")
                c = self.ws.capture
                t0, label = self._time_origin()
                t = np.arange(c["ch2"].size) / c["fs"] - t0
                self.plot.show(t, c["ch2"], label, "IN2 (counts)",
                               yfmt=lambda v: f"{v:.0f}")
        except Exception as exc:                         # noqa: BLE001
            self.log(f"plot failed: {exc}")

    # ---------------------------------------------------------------- panels

    def _panel(self, parent, title):
        f = ttk.LabelFrame(parent, text=title, padding=8)
        f.pack(fill="x", pady=4, padx=2)
        return f

    def _need_board(self):
        if self.rp is None:
            messagebox.showerror("No board", "Connect the board first.")
            return None
        return self.rp

    def _need_laser(self):
        if self.laser is None:
            messagebox.showerror("No laser", "Connect the laser first.")
            return None
        return self.laser

    # -- Board ---------------------------------------------------------------

    def _panel_board(self, parent):
        f = self._panel(parent, "Board")
        self.v_host = tk.StringVar(
            value=os.environ.get("RP_HOST", "rp-fffe42.local"))
        fld(f, 0, "host", self.v_host, width=20)
        self.v_in1 = tk.StringVar(value="LV / AC")
        self.v_in2 = tk.StringVar(value="HV / DC")
        ttk.Label(f, text="IN1").grid(row=1, column=0, sticky="w")
        ttk.Combobox(f, textvariable=self.v_in1, width=10, state="readonly",
                     values=("LV / AC", "LV / DC", "HV / AC", "HV / DC")
                     ).grid(row=1, column=1, sticky="w")
        ttk.Label(f, text="IN2").grid(row=2, column=0, sticky="w")
        ttk.Combobox(f, textvariable=self.v_in2, width=10, state="readonly",
                     values=("HV / DC", "HV / AC", "LV / DC", "LV / AC")
                     ).grid(row=2, column=1, sticky="w")
        ttk.Label(f, text="IN1 AC/LV for the detector (0-10 V unipolar);\n"
                          "IN2 HV or the 3.3 V trigger clips flat.",
                  foreground="#666", justify="left").grid(
            row=3, column=0, columnspan=3, sticky="w", pady=(4, 4))
        b = ttk.Frame(f)
        b.grid(row=4, column=0, columnspan=3, sticky="w")
        ttk.Button(b, text="Connect", command=self.board_connect).pack(side="left")
        ttk.Button(b, text="Disconnect",
                   command=self.board_disconnect).pack(side="left", padx=4)
        ttk.Button(b, text="Configure",
                   command=self.board_front_end).pack(side="left")

    def board_connect(self):
        host = self.v_host.get().strip()

        def go():
            rp = RedPitaya(host)
            return rp, rp.query("*IDN?"), rp.fast_read_available()

        def done(v):
            self.rp, idn, helper = v
            self.h_board.set(f"board {host}")
            self.log(f"board connected: {idn}; fast-read helper "
                     f"{'running' if helper else 'NOT RUNNING'}")
            if not helper:
                self.log("deep captures need the helper. scp rp_fastread.py to "
                         "/dev/shm and start it; it is RAM and dies on reboot.")

        self.submit(self.board, "connect board", go, done)

    def board_disconnect(self):
        rp, self.rp = self.rp, None
        self.h_board.set("board --")
        if rp is None:
            return
        self.submit(self.board, "disconnect board", lambda: rp.close(),
                    lambda _v: self.log("board closed, outputs disarmed"))

    def board_front_end(self):
        rp = self._need_board()
        if not rp:
            return
        g1, c1 = [x.strip() for x in self.v_in1.get().split("/")]
        g2, c2 = [x.strip() for x in self.v_in2.get().split("/")]
        dec = int(self.v_dec.get())
        self.submit(self.board, "configure front end",
                    lambda: ops.front_end(rp, c1, g1, c2, g2, dec),
                    lambda v: self.log(f"front end: IN1 {v['in1']}, "
                                       f"IN2 {v['in2']}, dec {v['decimation']}"))

    # -- Drive ---------------------------------------------------------------

    def _panel_drive(self, parent):
        f = self._panel(parent, "Drive (OUT1)")
        self.v_carrier = tk.StringVar(value="80.0")
        self.v_mod = tk.StringVar(value=f"{DEFAULT_MOD_HZ / 1e3:.4f}")
        self.v_amp = tk.StringVar(value="1.0")
        fld(f, 0, "carrier", self.v_carrier, "MHz")
        fld(f, 1, "modulation", self.v_mod, "kHz")
        fld(f, 2, "amplitude", self.v_amp, "V")
        # What the ASG will ACTUALLY play. Both frequencies are snapped to the
        # 15258.789 Hz grid, and the difference is what made a hand-typed
        # second harmonic 54.7 Hz wrong.
        self.v_snap = tk.StringVar(value="")
        ttk.Label(f, textvariable=self.v_snap, foreground="#144",
                  justify="left").grid(row=3, column=0, columnspan=3,
                                       sticky="w", pady=(2, 2))
        for v in (self.v_carrier, self.v_mod):
            v.trace_add("write", lambda *_a: self._update_snap())
        self._update_snap()
        ttk.Label(f, text="915.527 kHz = 60 grid steps, 94 kHz clear of\n"
                          "the 504.868 kHz switcher family. Avoid 1007.080.",
                  foreground="#666", justify="left").grid(
            row=4, column=0, columnspan=3, sticky="w", pady=(2, 4))
        b = ttk.Frame(f)
        b.grid(row=5, column=0, columnspan=3, sticky="w")
        ttk.Button(b, text="Drive ON", command=self.drive_on).pack(side="left")
        ttk.Button(b, text="Drive OFF",
                   command=self.all_off).pack(side="left", padx=4)

    def _update_snap(self):
        """Show what the ASG will really play, beside what was typed."""
        from rp_lockin.waveforms import make_am_table
        try:
            carrier = float(self.v_carrier.get()) * 1e6
            mod = float(self.v_mod.get()) * 1e3
            t = make_am_table(carrier, mod)
        except (ValueError, ZeroDivisionError, AssertionError):
            return self.v_snap.set("")
        except Exception:                            # noqa: BLE001
            return self.v_snap.set("")
        self.v_snap.set(
            f"ACTUAL: carrier {t.carrier / 1e6:.6f} MHz ({t.carrier_cycles} "
            f"cycles)\n            mod {t.modulation / 1e3:.4f} kHz "
            f"({t.mod_cycles} cycles), 2x = {2 * t.modulation / 1e3:.4f} kHz")

    def _drive_cfg(self):
        return dict(carrier=float(self.v_carrier.get()) * 1e6,
                    modulation=float(self.v_mod.get()) * 1e3,
                    amplitude=float(self.v_amp.get()))

    def drive_on(self):
        rp = self._need_board()
        if not rp:
            return
        try:
            cfg = self._drive_cfg()
        except ValueError as e:
            return messagebox.showerror("Drive", f"Not a number: {e}")
        if not messagebox.askokcancel(
                "Enable OUT1",
                f"Carrier      {cfg['carrier'] / 1e6:.6f} MHz\n"
                f"Modulation   {cfg['modulation'] / 1e3:.4f} kHz (AM, depth 1)\n"
                f"Amplitude    {cfg['amplitude']} V\n\n"
                f"This reaches the amplifier and the modulator, and light "
                f"goes somewhere. It stays on until you turn it off."):
            return self.log("drive enable cancelled")

        def done(table):
            self.log(f"OUT1 ON: carrier {table.carrier / 1e6:.6f} MHz, "
                     f"modulation {table.modulation / 1e3:.4f} kHz "
                     f"(snapped), {cfg['amplitude']} V")

        self.submit(self.board, "drive on", lambda: ops.drive_on(rp, **cfg), done)

    def all_off(self):
        rp = self.rp
        if rp is None:
            return self.log("no board connected")
        self.submit(self.board, "outputs off", lambda: ops.drive_off(rp),
                    lambda _v: self.log("OUT1/OUT2 disarmed"))

    # -- Laser ---------------------------------------------------------------

    def _panel_laser(self, parent):
        f = self._panel(parent, "Laser")
        self.v_ip = tk.StringVar(value="10.101.0.197")
        self.v_dbm = tk.StringVar(value="4.0")
        fld(f, 0, "address", self.v_ip, width=18)
        fld(f, 1, "power", self.v_dbm, "dBm")
        ttk.Label(f, text="One connection is held for the whole session:\n"
                          "about one reconnect in four fails outright.",
                  foreground="#666", justify="left").grid(
            row=2, column=0, columnspan=3, sticky="w", pady=(4, 4))
        b = ttk.Frame(f)
        b.grid(row=3, column=0, columnspan=3, sticky="w")
        ttk.Button(b, text="Connect", command=self.laser_connect).pack(side="left")
        ttk.Button(b, text="Disconnect",
                   command=self.laser_disconnect).pack(side="left", padx=4)
        ttk.Button(b, text="Set power",
                   command=self.laser_set_power).pack(side="left")
        b2 = ttk.Frame(f)
        b2.grid(row=4, column=0, columnspan=3, sticky="w", pady=(4, 0))
        ttk.Button(b2, text="Shutter CLOSE",
                   command=lambda: self.laser_shutter(True)).pack(side="left")
        ttk.Button(b2, text="Shutter OPEN",
                   command=lambda: self.laser_shutter(False)).pack(side="left",
                                                                   padx=4)
        ttk.Button(b2, text="LD off",
                   command=lambda: self.laser_ld(False)).pack(side="left")

    def laser_connect(self):
        ip = self.v_ip.get().strip()

        def go():
            d = TSL775.connect("lan", host=ip, timeout=5.0)
            return d, ops.laser_state(d)

        def done(v):
            self.laser, st = v
            self.log(f"laser connected: {st.get('idn')}")
            self._show_laser(st)

        self.submit(self.lasw, "connect laser", go, done)

    def laser_disconnect(self):
        d, self.laser = self.laser, None
        self.h_laser.set("laser --")
        if d is None:
            return
        self.submit(self.lasw, "disconnect laser", lambda: d.close(),
                    lambda _v: self.log("laser connection closed"))

    def laser_set_power(self):
        d = self._need_laser()
        if not d:
            return
        try:
            dbm = float(self.v_dbm.get())
        except ValueError:
            return messagebox.showerror("Power", "Not a number.")
        self.submit(self.lasw, "set laser power",
                    lambda: ops.set_laser_power(d, dbm),
                    lambda v: self.log(
                        f"laser power {v['readback']:+.2f} dBm"
                        + (f" (CLAMPED from {v['requested']:+.2f}; range "
                           f"{v['min']:+.2f} to {v['max']:+.2f})"
                           if v["clamped"] else "")))

    def laser_shutter(self, close):
        d = self._need_laser()
        if not d:
            return
        if not close and not messagebox.askokcancel(
                "Open the shutter", "Light will reach whatever is connected "
                                    "to the output fibre. Continue?"):
            return
        self.submit(self.lasw, "shutter",
                    lambda: ops.set_shutter(d, close),
                    lambda v: self.log(
                        f"shutter reads {v} "
                        f"({'closed' if v == '1' else 'open'}). NOTE: the "
                        f"instrument reopens it by itself when a sweep starts."))

    def laser_ld(self, on):
        d = self._need_laser()
        if not d:
            return
        self.submit(self.lasw, "LD", lambda: ops.set_ld(d, on),
                    lambda v: self.log(f"LD state reads {v}"))

    # -- Sweep ---------------------------------------------------------------

    def _panel_sweep(self, parent):
        f = self._panel(parent, "Sweep")
        self.v_start = tk.StringVar(value="1500")
        self.v_stop = tk.StringVar(value="1600")
        self.v_speed = tk.StringVar(value="100")
        self.v_step = tk.StringVar(value="0.02")
        self.v_mode = tk.StringVar(value="continuous, one way")
        fld(f, 0, "start", self.v_start, "nm")
        fld(f, 1, "stop", self.v_stop, "nm")
        # Discrete, not continuous (manual p.87). Anything else is rejected by
        # the instrument, so a free-text box could only ever produce a refusal.
        ttk.Label(f, text="speed").grid(row=2, column=0, sticky="w")
        ttk.Combobox(f, textvariable=self.v_speed, width=10, state="readonly",
                     values=tuple(("%g" % v) for v in ops.SWEEP_SPEEDS_NM_S)
                     ).grid(row=2, column=1, sticky="w")
        ttk.Label(f, text="nm/s").grid(row=2, column=2, sticky="w")
        fld(f, 3, "trigger step", self.v_step, "nm")
        # Two-way is a trap: the return pass overwrites the log, so the run
        # comes back with only the descending half.
        ttk.Label(f, text="mode").grid(row=4, column=0, sticky="w")
        ttk.Combobox(f, textvariable=self.v_mode, width=28, state="readonly",
                     values=tuple(ops.SWEEP_MODES.values())).grid(
            row=4, column=1, columnspan=2, sticky="w")
        self.v_sweepinfo = tk.StringVar(value="")
        ttk.Label(f, textvariable=self.v_sweepinfo, foreground="#666",
                  justify="left").grid(row=5, column=0, columnspan=3,
                                       sticky="w", pady=(4, 4))
        b = ttk.Frame(f)
        b.grid(row=6, column=0, columnspan=3, sticky="w")
        ttk.Button(b, text="Configure",
                   command=self.sweep_configure).pack(side="left")
        ttk.Button(b, text="Start",
                   command=self.sweep_start).pack(side="left", padx=4)
        ttk.Button(b, text="Stop", command=self.sweep_stop).pack(side="left")
        ttk.Button(b, text="Read log",
                   command=self.sweep_read_log).pack(side="left", padx=4)
        self._update_sweep_info()
        for v in (self.v_start, self.v_stop, self.v_speed, self.v_step):
            v.trace_add("write", lambda *_a: self._update_sweep_info())

    def _sweep_cfg(self):
        mode = next((k for k, v in ops.SWEEP_MODES.items()
                     if v == self.v_mode.get()), 1)
        return dict(start_nm=float(self.v_start.get()),
                    stop_nm=float(self.v_stop.get()),
                    speed_nm_s=float(self.v_speed.get()),
                    step_nm=float(self.v_step.get()), mode=mode)

    def _update_sweep_info(self):
        try:
            c = self._sweep_cfg()
            n = int(round(abs(c["stop_nm"] - c["start_nm"]) / c["step_nm"])) + 1
            dt = c["step_nm"] / c["speed_nm_s"]
            secs = (n - 1) * dt
            need = ops.smallest_decimation_for(secs)
            info = (f"{n} points, {dt * 1e6:.1f} us apart "
                    f"({1 / dt / 1e3:.2f} kHz), {secs:.3f} s")
            if need is not None:
                info += f"\nneeds decimation {need} or higher to fit in memory"
            self.v_sweepinfo.set(info)
        except (ValueError, ZeroDivisionError):
            self.v_sweepinfo.set("")

    def sweep_configure(self):
        d = self._need_laser()
        if not d:
            return
        try:
            cfg = self._sweep_cfg()
        except ValueError as e:
            return messagebox.showerror("Sweep", f"Not a number: {e}")
        self.submit(self.lasw, "configure sweep",
                    lambda: ops.configure_sweep(d, **cfg),
                    lambda v: self.log(f"sweep configured; trig="
                                       f"{v['after']['trig']}, mode="
                                       f"{v['after']['mode']}"))

    def sweep_start(self):
        d = self._need_laser()
        if not d:
            return
        self.submit(self.lasw, "start sweep", lambda: ops.start_sweep(d),
                    lambda _v: self.log("sweep started"))

    def sweep_stop(self):
        d = self._need_laser()
        if not d:
            return
        self.submit(self.lasw, "stop sweep", lambda: ops.stop_sweep(d),
                    lambda _v: self.log("sweep stopped"))

    def sweep_read_log(self):
        d = self._need_laser()
        if not d:
            return

        def done(v):
            had = self.ws.reduction is not None
            self.ws.set_log(v["wavelengths"])
            if had:
                self.log("new laser log: the previous trace used the old one "
                         "and has been cleared.")
            self.refresh_workspace()
            self.log(f"laser log: {v['wavelengths'].size} points "
                     f"(:READ:POIN? said {v['points_reported']})")

        self.submit(self.lasw, "read log", lambda: ops.read_log(d), done)

    # -- Acquire -------------------------------------------------------------

    def _panel_acquire(self, parent):
        f = self._panel(parent, "Acquire")
        self.v_dec = tk.StringVar(value="8")
        self.v_secs = tk.StringVar(value="1.0")
        self.v_trig = tk.StringVar(value="CH2_PE")
        self.v_level = tk.StringVar(value="1.0")
        fld(f, 0, "decimation", self.v_dec)
        fld(f, 1, "cover", self.v_secs, "s")
        ttk.Label(f, text="trigger").grid(row=2, column=0, sticky="w")
        # PE is POSITIVE EDGE (NE negative), so CH2_PE means "when analog
        # channel 2 crosses the level going up". NOW is gone from this list:
        # it captures immediately and produces a record with no time origin,
        # which cannot carry a wavelength axis. The Snapshot button below is
        # the deliberate way to take one.
        ttk.Combobox(f, textvariable=self.v_trig, width=10, state="readonly",
                     values=("CH2_PE", "CH2_NE", "CH1_PE", "EXT_PE")).grid(
            row=2, column=1, sticky="w")
        fld(f, 3, "level", self.v_level, "V")
        ttk.Label(f, text="Always captures IN1 AND IN2 together. Not\n"
                          "optional: the wavelength axis is only valid if\n"
                          "the detector and the trigger share one record,\n"
                          "and one time base.",
                  foreground="#666", justify="left").grid(
            row=4, column=0, columnspan=3, sticky="w", pady=(4, 2))
        ttk.Label(f, text="ORDER: Capture FIRST -- it arms and waits --\n"
                          "then Start in the Sweep panel above. The laser has\n"
                          "its own worker, so it is not stuck behind the\n"
                          "waiting capture.",
                  foreground="#144", justify="left").grid(
            row=5, column=0, columnspan=3, sticky="w", pady=(0, 4))
        b = ttk.Frame(f)
        b.grid(row=6, column=0, columnspan=3, sticky="w")
        ttk.Button(b, text="Capture (arms and waits)",
                   command=self.acquire_now).pack(side="left")
        ttk.Button(b, text="Snapshot (no trigger)",
                   command=self.acquire_snapshot).pack(side="left", padx=4)

    def acquire_snapshot(self, seconds=0.02):
        """A short UNTRIGGERED look at both inputs, for alignment and levels.

        Kept apart from Capture rather than offered as a trigger choice: this
        record has no time origin, so it can never carry a wavelength axis, and
        an untriggered record sitting in the workspace where a triggered one
        belongs is the kind of thing that gets mapped by accident.
        """
        rp = self._need_board()
        if not rp:
            return
        try:
            dec = int(self.v_dec.get())
        except ValueError as e:
            return messagebox.showerror("Acquire", f"Not a number: {e}")
        n = int(seconds * ops.BASE_SAMPLE_RATE / dec)

        def done(cap):
            self.ws.set_capture(cap)
            self.refresh_workspace()
            c1, c2 = cap["ch1"], cap["ch2"]
            self.log(f"snapshot {seconds * 1e3:.0f} ms, UNTRIGGERED: "
                     f"IN1 {ops.swing(c1) / 1817.7 * 1e3:.1f} mV, "
                     f"IN2 {ops.swing(c2):.0f} counts. No time origin, so "
                     f"this one cannot be mapped to wavelength.")
            self.plot_what.set("raw IN1 (volts vs time)")
            self.redraw()

        self.submit(self.board, "snapshot",
                    lambda: ops.acquire(rp, n_samples=n, decimation=dec,
                                        preroll=0, trigger="NOW", timeout=10.0),
                    done)

    def acquire_now(self):
        rp = self._need_board()
        if not rp:
            return
        try:
            dec = int(self.v_dec.get())
            secs = float(self.v_secs.get())
            level = float(self.v_level.get())
        except ValueError as e:
            return messagebox.showerror("Acquire", f"Not a number: {e}")
        plan = ops.capture_plan(secs, decimation=dec)
        if plan["truncated"]:
            need = ops.smallest_decimation_for(secs)
            return messagebox.showerror(
                "Not enough capture memory",
                f"{secs:.3f} s does not fit at decimation {dec}.\n\n"
                f"The reserved region is {ops.DMA_SAMPLE_CEILING} samples per "
                f"channel however it is filled, so a LOWER decimation is a "
                f"SHORTER record: at {dec} the most sweep it can hold is "
                f"{plan['max_sweep_s'] * 1e3:.0f} ms once pre-roll and tail "
                f"are paid for.\n\n"
                + (f"Use decimation {need} or higher."
                   if need else "No decimation up to 64 is enough.")
                + "\n\nRefusing rather than truncating: a record that stops "
                  "part way through the sweep still maps onto the full "
                  "wavelength table and looks like a measurement.")
        trig = self.v_trig.get()
        self.log(f"arming: {plan['n_samples']} samples x2 channels @ "
                 f"{plan['fs'] / 1e6:.3f} MS/s, pre-roll "
                 f"{plan['preroll'] / plan['fs'] * 1e3:.2f} ms, trig {trig}")
        if trig != "NOW":
            self.h_armed.set("capture ARMED")
            self.log(f">>> ARMED and waiting for {trig}. NOW press "
                     f"Sweep > Start (or fire the trigger by hand). It gives "
                     f"up after 120 s.")

        def go():
            return ops.acquire(rp, n_samples=plan["n_samples"],
                               decimation=dec, preroll=plan["preroll"],
                               trigger=trig, level=level)

        def done(cap):
            self.h_armed.set("")
            had = self.ws.lockin is not None or self.ws.reduction is not None
            self.ws.set_capture(cap)
            if had:
                self.log("new capture: the previous lock-in and trace were "
                         "derived from the old record and have been cleared.")
            self.refresh_workspace()
            c1, c2 = cap["ch1"], cap["ch2"]
            self.log(f"captured {c1.size} samples on BOTH channels. "
                     f"IN1 {ops.swing(c1) / 1817.7 * 1e3:.1f} mV "
                     f"({ops.swing(c1):.0f} counts), "
                     f"IN2 {ops.swing(c2):.0f} counts")
            if cap.get("first_edge") is not None:
                self.log(f"first trigger edge at "
                         f"{cap['first_edge'] * 1e3:.3f} ms into the record "
                         f"({cap['n_edges']} edges). Time views are plotted "
                         f"relative to it, so 0 is the start of the sweep.")
            if ops.swing(c2) < 50:
                self.log("WARNING: IN2 barely moves. Nothing is arriving on "
                         "the trigger channel -- is the BNC in the analog IN2 "
                         "socket rather than the external-trigger one?")
            if ops.clipped(c1):
                self.log(f"WARNING: {ops.clipped(c1)} IN1 samples at the ADC "
                         f"rail. Amplitudes from a flattened waveform are "
                         f"wrong, not noisy. Reduce the light.")

        self.submit(self.board, "capture", go, done,
                    lambda _e: self.h_armed.set(""))

    # -- Demodulate ----------------------------------------------------------

    def _panel_demod(self, parent):
        f = self._panel(parent, "Demodulate")
        self.v_fref = tk.StringVar(value=f"{DEFAULT_MOD_HZ / 1e3:.4f}")
        self.v_orate = tk.StringVar(value="5000")
        fld(f, 0, "f_ref", self.v_fref, "kHz")
        fld(f, 1, "output rate", self.v_orate, "Sa/s")
        ttk.Label(f, text="Runs on the capture in the workspace, so the\n"
                          "same record can be examined at f1 and 2*f1\n"
                          "without touching hardware.",
                  foreground="#666", justify="left").grid(
            row=2, column=0, columnspan=3, sticky="w", pady=(4, 4))
        h = ttk.Frame(f)
        h.grid(row=3, column=0, columnspan=3, sticky="w")
        ttk.Label(h, text="set from drive:").pack(side="left")
        ttk.Button(h, text="f1", width=4,
                   command=lambda: self.fref_from_drive(1)).pack(side="left",
                                                                  padx=2)
        ttk.Button(h, text="2 x f1", width=7,
                   command=lambda: self.fref_from_drive(2)).pack(side="left")
        ttk.Button(h, text="3 x f1", width=7,
                   command=lambda: self.fref_from_drive(3)).pack(side="left",
                                                                 padx=2)
        ttk.Label(f, text="Type the harmonic in by hand and you will be a few\n"
                          "tens of hertz out, because the ASG SNAPS the drive\n"
                          "to its grid. The lock-in then beats at the offset\n"
                          "and the trace comes out as a sine wave.",
                  foreground="#a04000", justify="left").grid(
            row=4, column=0, columnspan=3, sticky="w", pady=(4, 4))
        ttk.Button(f, text="Demodulate capture",
                   command=self.demod_run).grid(row=5, column=0, columnspan=3,
                                                sticky="w")

    def fref_from_drive(self, harmonic):
        """Set f_ref to an exact harmonic of what the ASG is ACTUALLY playing.

        Not of what is typed in the Drive box. Both frequencies are snapped to
        the 15258.789 Hz grid, so 915.5273 kHz becomes 915.52734375 and its
        second harmonic is 1831.0547 kHz, not 1831. Entering the round number
        leaves f_ref 54.7 Hz off, and a lock-in demodulating 54.7 Hz away from
        its signal returns a 54.7 Hz BEAT -- which, after amplitude() projects
        onto a common phase, is a clean sine wave across the trace. It looks
        like a measurement. It is a typo.
        """
        from rp_lockin.waveforms import make_am_table
        try:
            cfg = self._drive_cfg()
        except ValueError as e:
            return messagebox.showerror("Drive", f"Not a number: {e}")
        table = make_am_table(cfg["carrier"], cfg["modulation"])
        f = harmonic * table.modulation
        self.v_fref.set(f"{f / 1e3:.6f}")
        self.log(f"f_ref = {harmonic} x the SNAPPED drive "
                 f"({table.modulation:.4f} Hz) = {f:.4f} Hz")

    def _warn_if_beating(self, r):
        """A lock-in output that oscillates is a frequency offset, not physics.

        amplitude() projects X+jY onto one phase, so a reference that is off by
        df makes the projection swing between +A and -A at df. Counting sign
        changes recovers df, which is the number needed to fix it -- so say it
        rather than leaving a sine on screen looking like a result.
        """
        a = r.amplitude()
        if a.size < 32:
            return
        crossings = int(np.count_nonzero(np.diff(np.signbit(a))))
        if crossings < 4:
            return
        duration = a.size / r.fs_out
        beat = crossings / (2.0 * duration)
        self.log(f"WARNING: the lock-in output changes sign {crossings} times "
                 f"-- that is a BEAT at about {beat:.1f} Hz, not a signal. "
                 f"f_ref is roughly {beat:.1f} Hz away from whatever is "
                 f"actually there. Use the f1 / 2 x f1 buttons, which take the "
                 f"SNAPPED drive frequency.")

    def demod_run(self):
        if not self.ws.capture:
            return messagebox.showinfo("Demodulate", "Capture something first.")
        try:
            f_ref = float(self.v_fref.get()) * 1e3
            orate = float(self.v_orate.get())
        except ValueError as e:
            return messagebox.showerror("Demodulate", f"Not a number: {e}")

        def done(r):
            had = self.ws.reduction is not None
            self.ws.set_lockin(r)
            if had:
                self.log("demodulated at a new frequency: the previous trace "
                         "was made at a different f_ref and has been cleared. "
                         "Run Map again.")
            self.refresh_workspace()
            a = r.amplitude()
            self.log(f"demodulated at {r.f_ref / 1e3:.4f} kHz: {a.size} points, "
                     f"median {np.median(a) * 1e3:.4f} mV, "
                     f"max {a.max() * 1e3:.4f} mV")
            self._warn_if_beating(r)
            self.plot_what.set("lock-in (amplitude vs time)")
            self.redraw()

        self.submit(self.board, "demodulate",
                    lambda: ops.run_demodulate(self.ws.capture, f_ref,
                                               output_rate=orate), done)

    # -- Map -----------------------------------------------------------------

    def _panel_map(self, parent):
        f = self._panel(parent, "Map to wavelength")
        ttk.Label(f, text="capture + laser log -> amplitude vs wavelength.\n"
                          "Goes through reduce_sweep, the offline-tested\n"
                          "join, rather than reusing the panel above.",
                  foreground="#666", justify="left").grid(
            row=0, column=0, sticky="w", pady=(0, 4))
        ttk.Button(f, text="Map", command=self.map_run).grid(row=1, column=0,
                                                             sticky="w")

    def map_run(self):
        if not self.ws.capture:
            return messagebox.showinfo("Map", "No capture in the workspace.")
        if self.ws.laser_log is None:
            return messagebox.showinfo("Map", "No laser log. Sweep > Read log.")
        try:
            f_ref = float(self.v_fref.get()) * 1e3
            orate = float(self.v_orate.get())
            cfg = self._sweep_cfg()
        except ValueError as e:
            return messagebox.showerror("Map", f"Not a number: {e}")

        def done(red):
            self.ws.set_reduction(red)
            self.refresh_workspace()
            self.log(red.describe())
            t = red.trace
            if t.n_outside:
                self.log(f"{t.n_outside} point(s) carry no wavelength: "
                         f"{t.n_before} BEFORE the sweep began and "
                         f"{t.n_after} after it ended. Both are expected -- "
                         f"the record deliberately extends past the sweep at "
                         f"each end, and no wavelength exists out there. They "
                         f"are NaN rather than guessed, and the CSV drops "
                         f"them. Nothing inside the sweep is lost.")
            self.plot_what.set("trace (amplitude vs wavelength)")
            self.redraw()

        self.submit(self.board, "map to wavelength",
                    lambda: ops.run_map(self.ws.capture, self.ws.laser_log,
                                        f_ref, output_rate=orate,
                                        nominal_step=cfg["step_nm"]
                                        / cfg["speed_nm_s"]), done)

    # -- Export --------------------------------------------------------------

    def _panel_export(self, parent):
        f = self._panel(parent, "Export")
        ttk.Button(f, text="Trace to CSV",
                   command=self.export_csv).pack(side="left")
        ttk.Button(f, text="Raw to .npz",
                   command=self.export_npz).pack(side="left", padx=4)

    def export_csv(self):
        if self.ws.reduction is None:
            return messagebox.showinfo("Export", "No trace. Run Map first.")
        path = filedialog.asksaveasfilename(defaultextension=".csv",
                                            initialfile="trace.csv",
                                            filetypes=[("CSV", "*.csv")])
        if not path:
            return
        n = write_trace_csv(path, self.ws.reduction.trace.wavelength,
                            self.ws.reduction.trace.amplitude,
                            metadata=self.ws.reduction.metadata())
        self.log(f"wrote {path} ({n} rows)")

    def export_npz(self):
        if not self.ws.capture:
            return messagebox.showinfo("Export", "No capture.")
        path = filedialog.asksaveasfilename(defaultextension=".npz",
                                            initialfile="raw.npz",
                                            filetypes=[("npz", "*.npz")])
        if not path:
            return
        kw = dict(detector=self.ws.capture["ch1"],
                  trigger=self.ws.capture["ch2"], fs=self.ws.capture["fs"])
        if self.ws.laser_log is not None:
            kw["wavelengths"] = self.ws.laser_log
        write_raw_npz(path, **kw)
        self.log(f"wrote {path}")

    # -- Sequences -----------------------------------------------------------

    def _panel_sequences(self, parent):
        f = self._panel(parent, "Sequences")
        ttk.Label(f, text="The same functions the buttons call, in order.\n"
                          "There is no second implementation to drift.",
                  foreground="#666", justify="left").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 4))
        self.v_seq = tk.StringVar(value="linear sweep")
        ttk.Combobox(f, textvariable=self.v_seq, width=26, state="readonly",
                     values=("linear sweep",
                             "SHG (demodulate at 2*f1)",
                             "control: no drive",
                             "control: low power")).grid(row=1, column=0,
                                                         sticky="w")
        ttk.Button(f, text="Run", command=self.seq_run).grid(row=1, column=1,
                                                             sticky="w", padx=4)
        self.v_seqstat = tk.StringVar(value="idle")
        ttk.Label(f, textvariable=self.v_seqstat).grid(row=2, column=0,
                                                       columnspan=2, sticky="w",
                                                       pady=(4, 0))

    def seq_run(self):
        rp, d = self._need_board(), self._need_laser()
        if not rp or not d:
            return
        if self._seq_running:
            return messagebox.showinfo("Sequence", "One is already running.")
        name = self.v_seq.get()
        try:
            drive = self._drive_cfg()
            sweep = self._sweep_cfg()
            f_ref = float(self.v_fref.get()) * 1e3
            orate = float(self.v_orate.get())
            dec = int(self.v_dec.get())
            ctrl_dbm = -5.0
        except ValueError as e:
            return messagebox.showerror("Sequence", f"Not a number: {e}")

        if name.startswith("SHG"):
            # A chi(2) crystal is a SQUARE law, so light modulated at f1 comes
            # back with a component at 2*f1. Demodulating there isolates the
            # nonlinearity from any linear leakage, exactly as |f2-f1| does in
            # the two-tone scheme.
            f_ref = 2.0 * drive["modulation"]
        detail = (f"OUT1 {drive['carrier'] / 1e6:.6f} MHz AM "
                  f"{drive['modulation'] / 1e3:.4f} kHz @ {drive['amplitude']} V\n"
                  f"Laser {sweep['start_nm']}-{sweep['stop_nm']} nm at "
                  f"{sweep['speed_nm_s']} nm/s\n"
                  f"Demodulate at {f_ref / 1e3:.4f} kHz\n\n")
        if name.startswith("SHG"):
            detail += ("SHG: demodulating at TWICE the drive frequency.\n"
                       "NOTE the AOM makes 2*f1 by itself -- depth-1 AM on a\n"
                       "sin^2 device -- so a signal here does NOT prove SHG\n"
                       "until a crystal-out run is compared against it.\n\n")
        if name == "control: no drive":
            detail += "CONTROL: OUT1 stays OFF. Tests whether the signal comes "\
                      "from our drive at all.\n\n"
        elif name == "control: low power":
            detail += (f"CONTROL: laser drops to {ctrl_dbm:+.1f} dBm and is "
                       f"restored. Tests whether the signal is OPTICAL.\n\n")
        if not messagebox.askokcancel("Run sequence",
                                      detail + "Light goes somewhere. Continue?"):
            return self.log("sequence cancelled")

        self._seq_running = True
        self.v_seqstat.set("running...")
        th = threading.Thread(
            target=self._seq_thread,
            args=(name, rp, d, drive, sweep, f_ref, orate, dec, ctrl_dbm),
            daemon=True)
        th.start()

    def _seq_thread(self, name, rp, d, drive, sweep, f_ref, orate, dec,
                    ctrl_dbm):
        """Runs the ops in order, taking each instrument's lock as it goes.

        The locks are what let this share the instruments with the status poll
        and the panel buttons without a second protocol: a worker holds its
        lock for the whole of each job, so nothing here can interleave with one.
        """
        def note(msg):
            self.root.after(0, lambda: self.log(f"[{name}] {msg}"))

        restore = None
        power_before = None
        try:
            with self.lasw.lock:
                power_before = float(d.query(":POWer:LEVel?"))
                if name == "control: low power":
                    r = ops.set_laser_power(d, ctrl_dbm)
                    note(f"laser -> {r['readback']:+.2f} dBm "
                         f"(from {power_before:+.2f})")
                cfg = ops.configure_sweep(d, **sweep)
                restore = cfg["before"]
                note("sweep configured")

            with self.board.lock:
                g1, c1 = [x.strip() for x in self.v_in1.get().split("/")]
                g2, c2 = [x.strip() for x in self.v_in2.get().split("/")]
                ops.front_end(rp, c1, g1, c2, g2, dec)
                if name == "control: no drive":
                    ops.drive_off(rp)
                    note("OUT1 left OFF (control)")
                else:
                    tbl = ops.drive_on(rp, **drive)
                    note(f"OUT1 ON at {tbl.modulation / 1e3:.4f} kHz")

            n_pts = int(round(abs(sweep["stop_nm"] - sweep["start_nm"])
                              / sweep["step_nm"])) + 1
            secs = (n_pts - 1) * (sweep["step_nm"] / sweep["speed_nm_s"])
            plan = ops.capture_plan(secs, decimation=dec)

            with self.board.lock:
                th, out = ops.acquire_async(
                    rp, n_samples=plan["n_samples"], decimation=dec,
                    preroll=plan["preroll"], trigger="CH2_PE", level=1.0)
                note(f"capture armed ({plan['n_samples']} samples)")
                time.sleep(2.0)
                with self.lasw.lock:
                    ops.start_sweep(d)
                    note("sweep started")
                    w = ops.wait_for_sweep(d)
                    note(f"sweep done in {w['elapsed']:.2f} s; shutter read "
                         f"{w['shutter_during']} DURING the sweep")
                th.join(timeout=180.0)
                if "error" in out:
                    raise out["error"]
                ops.drive_off(rp)

            with self.lasw.lock:
                log = ops.read_log(d)
                note(f"log: {log['wavelengths'].size} points")

            red = ops.run_map(out, log["wavelengths"], f_ref,
                              output_rate=orate,
                              nominal_step=sweep["step_nm"] / sweep["speed_nm_s"])

            def finish():
                self.ws.set_capture(out)
                self.ws.set_log(log["wavelengths"])
                self.ws.set_reduction(red)
                self.refresh_workspace()
                _w, a = red.trace.dropna()
                self.log(f"[{name}] DONE: median {np.median(a) * 1e3:.4f} mV, "
                         f"max {a.max() * 1e3:.4f} mV, axis from "
                         f"{red.table_source}")
                if name.startswith("SHG"):
                    self.log(f"[{name}] demodulated at "
                             f"{f_ref / 1e3:.4f} kHz = 2 x the drive. Run this "
                             f"again with the crystal OUT: the difference is "
                             f"the SHG, the common part is the AOM's own "
                             f"harmonic.")
                if name == "control: low power":
                    drop = power_before - ctrl_dbm
                    self.log(f"[{name}] a {drop:.1f} dB drop: an OPTICAL signal "
                             f"should be {100 * 10 ** (-drop / 10):.1f}% of the "
                             f"full-power run; pickup will not move at all.")
                self.plot_what.set("trace (amplitude vs wavelength)")
                self.redraw()

            self.root.after(0, finish)
        except Exception as exc:                             # noqa: BLE001
            self.root.after(0, lambda: self.log(f"[{name}] FAILED: "
                                                f"{exc.__class__.__name__}: {exc}"))
            self.root.after(0, lambda: messagebox.showerror(name, str(exc)))
        finally:
            try:
                with self.lasw.lock:
                    ops.stop_sweep(d)
                    if restore:
                        ops.restore_sweep(d, restore)
                    if name == "control: low power" and power_before is not None:
                        ops.set_laser_power(d, power_before)
                with self.board.lock:
                    ops.drive_off(rp)
            except Exception:                                # noqa: BLE001
                pass
            self._seq_running = False
            self.root.after(0, lambda: self.v_seqstat.set("idle"))

    # ----------------------------------------------------------------- close

    def on_close(self):
        try:
            if self.rp is not None:
                ops.drive_off(self.rp)
                self.rp.close()
        except Exception:                                    # noqa: BLE001
            pass
        try:
            if self.laser is not None:
                self.laser.close()
        except Exception:                                    # noqa: BLE001
            pass
        self.root.destroy()


def main():
    root = tk.Tk()
    Bench(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
