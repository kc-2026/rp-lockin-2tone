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
    """What is currently in memory. Panels read and write these."""

    capture: dict = None
    laser_log: np.ndarray = None
    lockin: object = None
    reduction: object = None
    meta: dict = field(default_factory=dict)

    def summary(self):
        rows = []
        if self.capture:
            c = self.capture
            rows.append(("capture", f"{c['ch1'].size / 1e6:.1f} Msa x2 @ "
                                    f"{c['fs'] / 1e6:.3f} MS/s, trig "
                                    f"{c['trigger']}"))
        else:
            rows.append(("capture", "-"))
        if self.laser_log is not None:
            w = self.laser_log
            rows.append(("laser log", f"{w.size} pts, {w[0] * 1e9:.3f} -> "
                                      f"{w[-1] * 1e9:.3f} nm"))
        else:
            rows.append(("laser log", "-"))
        if self.lockin is not None:
            rows.append(("lock-in", f"{self.lockin.f_ref / 1e3:.4f} kHz, "
                                    f"{self.lockin.t.size} pts @ "
                                    f"{self.lockin.fs_out:.0f} Sa/s"))
        else:
            rows.append(("lock-in", "-"))
        if self.reduction is not None:
            w, a = self.reduction.trace.dropna()
            rows.append(("trace", f"{w.size} pts, {np.median(a) * 1e3:.3f} mV "
                                  f"median, {a.max() * 1e3:.3f} mV max"))
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
        self.ws = Workspace()
        self.refresh_workspace()
        self.plot.clear()
        self.log("workspace cleared")

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
                self.plot.show(r.t, r.amplitude(), "time (s)", "amplitude (V)",
                               yfmt=lambda v: eng(v, "V"))
            elif what.startswith("raw IN1"):
                if not self.ws.capture:
                    return self.log("no capture")
                c = self.ws.capture
                t = np.arange(c["ch1"].size) / c["fs"]
                self.plot.show(t, ops.volts(c["ch1"]), "time (s)", "IN1 (V)",
                               yfmt=lambda v: eng(v, "V"))
            else:
                if not self.ws.capture:
                    return self.log("no capture")
                c = self.ws.capture
                t = np.arange(c["ch2"].size) / c["fs"]
                self.plot.show(t, c["ch2"], "time (s)", "IN2 (counts)",
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
        ttk.Button(b, text="Apply front end",
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
        self.submit(self.board, "front end",
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
        ttk.Label(f, text="Both snap to the 15258.789 Hz ASG grid.\n"
                          "915.527 kHz = 60 steps, 94 kHz clear of the\n"
                          "504.868 kHz switcher family. Avoid 1007.080.",
                  foreground="#666", justify="left").grid(
            row=3, column=0, columnspan=3, sticky="w", pady=(4, 4))
        b = ttk.Frame(f)
        b.grid(row=4, column=0, columnspan=3, sticky="w")
        ttk.Button(b, text="Drive ON", command=self.drive_on).pack(side="left")
        ttk.Button(b, text="Drive OFF",
                   command=self.all_off).pack(side="left", padx=4)

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
        fld(f, 0, "start", self.v_start, "nm")
        fld(f, 1, "stop", self.v_stop, "nm")
        fld(f, 2, "speed", self.v_speed, "nm/s")
        fld(f, 3, "trigger step", self.v_step, "nm")
        self.v_sweepinfo = tk.StringVar(value="")
        ttk.Label(f, textvariable=self.v_sweepinfo, foreground="#666").grid(
            row=4, column=0, columnspan=3, sticky="w", pady=(4, 4))
        b = ttk.Frame(f)
        b.grid(row=5, column=0, columnspan=3, sticky="w")
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
        return dict(start_nm=float(self.v_start.get()),
                    stop_nm=float(self.v_stop.get()),
                    speed_nm_s=float(self.v_speed.get()),
                    step_nm=float(self.v_step.get()))

    def _update_sweep_info(self):
        try:
            c = self._sweep_cfg()
            n = int(round(abs(c["stop_nm"] - c["start_nm"]) / c["step_nm"])) + 1
            dt = c["step_nm"] / c["speed_nm_s"]
            self.v_sweepinfo.set(f"{n} points, {dt * 1e6:.1f} us apart "
                                 f"({1 / dt / 1e3:.2f} kHz), "
                                 f"{(n - 1) * dt:.3f} s")
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
            self.ws.laser_log = v["wavelengths"]
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
        ttk.Combobox(f, textvariable=self.v_trig, width=10, state="readonly",
                     values=("CH2_PE", "CH1_PE", "EXT_PE", "NOW")).grid(
            row=2, column=1, sticky="w")
        fld(f, 3, "level", self.v_level, "V")
        ttk.Label(f, text="Always captures IN1 AND IN2 together. Not\n"
                          "optional: the wavelength axis is only valid if\n"
                          "the detector and the trigger share one record,\n"
                          "and one time base.",
                  foreground="#666", justify="left").grid(
            row=4, column=0, columnspan=3, sticky="w", pady=(4, 2))
        ttk.Label(f, text="ORDER: press Capture FIRST -- it arms and waits --\n"
                          "then Sweep > Start. The laser has its own worker,\n"
                          "so it is not stuck behind the waiting capture.",
                  foreground="#144", justify="left").grid(
            row=5, column=0, columnspan=3, sticky="w", pady=(0, 4))
        b = ttk.Frame(f)
        b.grid(row=6, column=0, columnspan=3, sticky="w")
        ttk.Button(b, text="1. Capture (arm)",
                   command=self.acquire_now).pack(side="left")
        ttk.Button(b, text="2. Sweep > Start",
                   command=self.sweep_start).pack(side="left", padx=4)

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
        trig = self.v_trig.get()
        self.log(f"arming: {plan['n_samples']} samples x2 channels @ "
                 f"{plan['fs'] / 1e6:.3f} MS/s, pre-roll "
                 f"{plan['preroll'] / plan['fs'] * 1e3:.2f} ms, trig {trig}")
        if trig != "NOW":
            self.h_armed.set("capture ARMED")
            self.log(f">>> ARMED and waiting for {trig}. NOW press "
                     f"Sweep > Start (or fire the trigger by hand). It gives "
                     f"up after 120 s.")
        if plan["truncated"]:
            self.log("WARNING: record hit the DMA ceiling and was truncated; "
                     "the trace may run past the end of the laser's table.")

        def go():
            return ops.acquire(rp, n_samples=plan["n_samples"],
                               decimation=dec, preroll=plan["preroll"],
                               trigger=trig, level=level)

        def done(cap):
            self.h_armed.set("")
            self.ws.capture = cap
            self.refresh_workspace()
            c1, c2 = cap["ch1"], cap["ch2"]
            self.log(f"captured {c1.size} samples on BOTH channels. "
                     f"IN1 {ops.swing(c1) / 1817.7 * 1e3:.1f} mV "
                     f"({ops.swing(c1):.0f} counts), "
                     f"IN2 {ops.swing(c2):.0f} counts")
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
        ttk.Button(f, text="Demodulate capture",
                   command=self.demod_run).grid(row=3, column=0, columnspan=3,
                                                sticky="w")

    def demod_run(self):
        if not self.ws.capture:
            return messagebox.showinfo("Demodulate", "Capture something first.")
        try:
            f_ref = float(self.v_fref.get()) * 1e3
            orate = float(self.v_orate.get())
        except ValueError as e:
            return messagebox.showerror("Demodulate", f"Not a number: {e}")

        def done(r):
            self.ws.lockin = r
            self.refresh_workspace()
            a = r.amplitude()
            self.log(f"demodulated at {r.f_ref / 1e3:.4f} kHz: {a.size} points, "
                     f"median {np.median(a) * 1e3:.4f} mV, "
                     f"max {a.max() * 1e3:.4f} mV")
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
            self.ws.reduction = red
            self.ws.lockin = red.result
            self.refresh_workspace()
            self.log(red.describe())
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
        ttk.Combobox(f, textvariable=self.v_seq, width=24, state="readonly",
                     values=("linear sweep",
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

        detail = (f"OUT1 {drive['carrier'] / 1e6:.6f} MHz AM "
                  f"{drive['modulation'] / 1e3:.4f} kHz @ {drive['amplitude']} V\n"
                  f"Laser {sweep['start_nm']}-{sweep['stop_nm']} nm at "
                  f"{sweep['speed_nm_s']} nm/s\n"
                  f"Demodulate at {f_ref / 1e3:.4f} kHz\n\n")
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
                self.ws.capture = out
                self.ws.laser_log = log["wavelengths"]
                self.ws.reduction = red
                self.ws.lockin = red.result
                self.refresh_workspace()
                _w, a = red.trace.dropna()
                self.log(f"[{name}] DONE: median {np.median(a) * 1e3:.4f} mV, "
                         f"max {a.max() * 1e3:.4f} mV, axis from "
                         f"{red.table_source}")
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
