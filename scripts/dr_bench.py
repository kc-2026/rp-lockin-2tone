"""Dynamic-range bench: how much range does each detector gain actually buy?

**Separate from `bench.py` on purpose.** This is a characterisation tool, not a
measurement tool -- it exists to answer one question and then stop being used.
Keeping it apart leaves the working bench uncluttered, and it shares every
instrument operation through `_bench_ops`, so there is no second implementation
of anything that touches hardware.

## The question

The APD's gain knob trades signal against noise, and neither end is best. Too
little gain and the board's own floor dominates; too much and the detector
saturates, which compresses the peak and -- worse here -- manufactures a
second harmonic out of a pure tone, in exactly the place an SHG measurement
looks. Somewhere between is the setting with the most usable range.

## How a point is taken

The operator sets the gain by hand, types what they set, and presses Run. The
bench then takes N sweeps at that setting and reduces them to three numbers:

* **peak** -- the largest amplitude in the averaged trace.
* **floor** -- the scatter of the same wavelength ACROSS repeats. This needs no
  idea where the signal is and no assumption that it ever stops, which matters
  because a sinc's tails never do. Verified against known truth in the offline
  suite: 3.55 uV recovered from a true 3.57.
* **dynamic range** -- 20 log10(peak / floor), reported per single sweep and
  for the average of N.

`tail_ratio` comes along for free: the off-peak rms divided by the across-sweep
floor. Near 1 the trace really is empty away from the peak; well above 1 there
is real structure out in the skirts, which for a sinc is the answer rather than
a problem.

## Reading the result

The waterfall stacks one trace per gain. The number to maximise is the dynamic
range column -- but a point flagged CLIPPED is not a measurement at all, and a
point whose peak stopped rising while the gain went up is already compressing
even if nothing railed.
"""

from __future__ import annotations

import csv
import os
import queue
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "src"))

import _bench_ops as ops                                      # noqa: E402
from _bench_widgets import (Plot, ScrollFrame, Worker, eng,  # noqa: E402
                            field as fld, wheel_safe)
from tsl775 import TSL775                                     # noqa: E402
from rp_lockin.hardware import RedPitaya                      # noqa: E402


class DrBench:
    def __init__(self, root):
        self.root = root
        root.title("Dynamic range vs detector gain")
        root.geometry("1180x820")
        self.rp = None
        self.laser = None
        self.results = queue.Queue()
        self.board = Worker(self.results, "board")
        self.lasw = Worker(self.results, "laser")
        self.board.start()
        self.lasw.start()
        self.points = []                 # one dict per gain setting
        self._running = False

        self._build()
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        root.after(80, self._pump)

    # ------------------------------------------------------------- layout

    def _build(self):
        head = ttk.Frame(self.root, padding=(8, 6))
        head.pack(fill="x")
        self.h_state = tk.StringVar(value="nothing connected")
        ttk.Label(head, textvariable=self.h_state,
                  font=("TkDefaultFont", 9, "bold")).pack(side="left")
        ttk.Button(head, text="OUTPUTS OFF",
                   command=self.all_off).pack(side="right")

        body = ttk.Frame(self.root, padding=(8, 0))
        body.pack(fill="both", expand=True)
        self.rail = ScrollFrame(body, width=345)
        self.rail.pack(side="left", fill="y")
        right = ttk.Frame(body)
        right.pack(side="left", fill="both", expand=True, padx=(8, 0))

        left = self.rail.body
        self._panel_setup(left)
        self._panel_point(left)
        self._panel_out(left)
        self._build_plot(right)
        self._build_log()
        self._wheel_proof(self.root)

    def _wheel_proof(self, widget):
        """Take the wheel away from every Combobox, or scrolling the rail past
        one silently changes its value."""
        for child in widget.winfo_children():
            if isinstance(child, ttk.Combobox):
                wheel_safe(child)
            self._wheel_proof(child)

    def _panel_setup(self, parent):
        f = ttk.LabelFrame(parent, text="Instruments", padding=8)
        f.pack(fill="x", pady=4)
        self.v_host = tk.StringVar(value=os.environ.get("RP_HOST",
                                                        "rp-fffe42.local"))
        self.v_ip = tk.StringVar(value="10.101.0.197")
        fld(f, 0, "board", self.v_host, width=18)
        fld(f, 1, "laser", self.v_ip, width=18)
        b = ttk.Frame(f)
        b.grid(row=2, column=0, columnspan=3, sticky="w", pady=(4, 0))
        ttk.Button(b, text="Connect", command=self.connect).pack(side="left")

        g = ttk.LabelFrame(parent, text="Drive and sweep", padding=8)
        g.pack(fill="x", pady=4)
        self.v_carrier = tk.StringVar(value="80.0")
        self.v_mod = tk.StringVar(value="1000")
        self.v_amp = tk.StringVar(value="1.0")
        self.v_start = tk.StringVar(value="1500")
        self.v_stop = tk.StringVar(value="1600")
        self.v_speed = tk.StringVar(value="100")
        self.v_step = tk.StringVar(value="0.02")
        self.v_dec = tk.StringVar(value="8")
        self.v_harm = tk.StringVar(value="2")
        fld(g, 0, "carrier", self.v_carrier, "MHz")
        fld(g, 1, "modulation", self.v_mod, "kHz")
        fld(g, 2, "amplitude", self.v_amp, "V")
        fld(g, 3, "start", self.v_start, "nm")
        fld(g, 4, "stop", self.v_stop, "nm")
        ttk.Label(g, text="speed").grid(row=5, column=0, sticky="w")
        wheel_safe(ttk.Combobox(
            g, textvariable=self.v_speed, width=10, state="readonly",
            values=tuple("%g" % v for v in ops.SWEEP_SPEEDS_NM_S)
        )).grid(row=5, column=1, sticky="w")
        ttk.Label(g, text="nm/s").grid(row=5, column=2, sticky="w")
        fld(g, 6, "trigger step", self.v_step, "nm")
        fld(g, 7, "decimation", self.v_dec)
        ttk.Label(g, text="demodulate at").grid(row=8, column=0, sticky="w")
        wheel_safe(ttk.Combobox(g, textvariable=self.v_harm, width=10,
                                state="readonly",
                                values=("1", "2", "3"))).grid(row=8, column=1,
                                                              sticky="w")
        ttk.Label(g, text="x f1").grid(row=8, column=2, sticky="w")

    def _panel_point(self, parent):
        f = ttk.LabelFrame(parent, text="Take a point", padding=8)
        f.pack(fill="x", pady=4)
        self.v_gain = tk.StringVar(value="10")
        self.v_reps = tk.StringVar(value="4")
        fld(f, 0, "gain (as set)", self.v_gain)
        fld(f, 1, "sweeps", self.v_reps)
        ttk.Label(f, text="The gain box is a LABEL -- nothing reads the "
                          "detector. Type whatever your knob says (M, turns, "
                          "volts); it only has to be a number, and to mean the "
                          "same thing at every point, because it becomes the "
                          "x axis.",
                  foreground="#666", justify="left", wraplength=300).grid(
            row=2, column=0, columnspan=3, sticky="w", pady=(4, 2))
        ttk.Label(f, text="Set the gain by hand, type it, then Run. The "
                          "repeats are the noise floor: the scatter of one "
                          "wavelength across sweeps.",
                  foreground="#666", justify="left", wraplength=300).grid(
            row=3, column=0, columnspan=3, sticky="w", pady=(0, 4))
        b = ttk.Frame(f)
        b.grid(row=4, column=0, columnspan=3, sticky="w")
        ttk.Button(b, text="Run point", command=self.run_point).pack(side="left")
        ttk.Button(b, text="Drop last",
                   command=self.drop_last).pack(side="left", padx=4)
        ttk.Button(b, text="Clear all", command=self.clear_all).pack(side="left")
        self.v_status = tk.StringVar(value="idle")
        ttk.Label(f, textvariable=self.v_status).grid(row=5, column=0,
                                                      columnspan=3, sticky="w",
                                                      pady=(4, 0))

    def _panel_out(self, parent):
        f = ttk.LabelFrame(parent, text="Result", padding=8)
        f.pack(fill="x", pady=4)
        self.v_view = tk.StringVar(value="waterfall")
        wheel_safe(ttk.Combobox(f, textvariable=self.v_view, width=26,
                                state="readonly",
                                values=("waterfall (traces by gain)",
                                        "dynamic range vs gain",
                                        "peak and floor vs gain"))).pack(
            fill="x")
        self.v_view.set("waterfall (traces by gain)")
        bb = ttk.Frame(f)
        bb.pack(fill="x", pady=(4, 4))
        ttk.Button(bb, text="Redraw", command=self.redraw).pack(side="left")
        ttk.Button(bb, text="Export CSV",
                   command=self.export).pack(side="left", padx=4)
        # Fixed height: inside a ScrollFrame there is no bottom to expand
        # against, and an expanding Text would grow without limit.
        self.table = tk.Text(f, height=14, width=40,
                             font=("Consolas", 8), wrap="none")
        self.table.pack(fill="x")

    def _build_plot(self, parent):
        f = ttk.LabelFrame(parent, text="Plot", padding=6)
        f.pack(fill="both", expand=True)
        self.plot = Plot(f, height=460)
        self.plot.pack(fill="both", expand=True)

    def _build_log(self):
        f = ttk.LabelFrame(self.root, text="Log", padding=6)
        f.pack(fill="x", padx=8, pady=(0, 8))
        self.logbox = tk.Text(f, height=8, font=("Consolas", 8), wrap="word")
        self.logbox.pack(fill="both", expand=True)

    def log(self, msg):
        self.logbox.insert("end", f"{time.strftime('%H:%M:%S')}  {msg}\n")
        self.logbox.see("end")

    # ------------------------------------------------------------- plumbing

    def submit(self, worker, name, fn, done=None, err=None):
        worker.submit(name, fn, done, err)

    def _pump(self):
        """Drain the worker queue onto the Tk thread.

        Worker posts ("busy", ...) and ("done", (job, value, exc)) tuples. An
        earlier version of this treated the item as a Job object; the first
        result raised AttributeError, the exception escaped the loop, and
        `after` was never rescheduled -- so the pump died and Connect appeared
        to do nothing at all. Hence the belt-and-braces try/finally: whatever
        happens, this reschedules.
        """
        try:
            while True:
                kind, payload = self.results.get_nowait()
                if kind == "busy":
                    who, what = payload
                    self.v_status.set(f"{who}: {what}")
                    continue
                job, value, exc = payload
                if exc is not None:
                    self.log(f"FAILED {job.name}: "
                             f"{exc.__class__.__name__}: {exc}")
                    if job.on_error:
                        try:
                            job.on_error(exc)
                        except Exception:                    # noqa: BLE001
                            pass
                elif job.on_done:
                    job.on_done(value)
                if not (self.board.busy or self.lasw.busy):
                    self.v_status.set("idle")
        except queue.Empty:
            pass
        except Exception as exc:                             # noqa: BLE001
            self.log(f"pump: {exc.__class__.__name__}: {exc}")
        finally:
            self.root.after(80, self._pump)

    # ------------------------------------------------------------- actions

    def connect(self):
        host, ip = self.v_host.get().strip(), self.v_ip.get().strip()

        def go_board():
            rp = RedPitaya(host)
            return rp, rp.idn()

        def board_done(v):
            self.rp, idn = v
            self.log(f"board: {idn}")
            self._state()

        def go_laser():
            d = TSL775.connect("lan", host=ip, timeout=5.0)
            return d, ops.laser_state(d)

        def laser_done(v):
            self.laser, st = v
            self.log(f"laser: {st.get('idn')}")
            self._state()

        self.submit(self.board, "connect board", go_board, board_done)
        self.submit(self.lasw, "connect laser", go_laser, laser_done)

    def _state(self):
        self.h_state.set(
            f"board {'OK' if self.rp else '--'} | "
            f"laser {'OK' if self.laser else '--'} | "
            f"{len(self.points)} gain point(s)")

    def all_off(self):
        if self.rp is not None:
            self.submit(self.board, "outputs off",
                        lambda: ops.drive_off(self.rp),
                        lambda _v: self.log("outputs disarmed"))

    def _cfg(self):
        return dict(
            carrier=float(self.v_carrier.get()) * 1e6,
            modulation=float(self.v_mod.get()) * 1e3,
            amplitude=float(self.v_amp.get()),
            start_nm=float(self.v_start.get()),
            stop_nm=float(self.v_stop.get()),
            speed_nm_s=float(self.v_speed.get()),
            step_nm=float(self.v_step.get()),
            dec=int(self.v_dec.get()),
            harmonic=int(self.v_harm.get()),
            reps=int(self.v_reps.get()),
            gain=float(self.v_gain.get()),
        )

    def run_point(self):
        if self.rp is None or self.laser is None:
            return messagebox.showerror("Not ready", "Connect both first.")
        if self._running:
            return messagebox.showinfo("Busy", "A point is already running.")
        try:
            c = self._cfg()
        except ValueError as e:
            return messagebox.showerror("Settings", f"Not a number: {e}")
        if any(abs(p["gain"] - c["gain"]) < 1e-9 for p in self.points):
            if not messagebox.askokcancel(
                    "Repeat gain",
                    f"There is already a point at gain {c['gain']:g}. "
                    f"Take another?"):
                return
        if not messagebox.askokcancel(
                "Run point",
                f"APD gain {c['gain']:g} -- CONFIRM you have set this on the "
                f"detector.\n\n"
                f"{c['reps']} sweeps, {c['start_nm']:g}-{c['stop_nm']:g} nm "
                f"at {c['speed_nm_s']:g} nm/s\n"
                f"OUT1 {c['carrier'] / 1e6:.3f} MHz AM "
                f"{c['modulation'] / 1e3:.1f} kHz @ {c['amplitude']} V\n\n"
                f"Light goes somewhere. Continue?"):
            return self.log("cancelled")
        self._running = True
        self.v_status.set("running...")
        threading.Thread(target=self._point_thread, args=(c,),
                         daemon=True).start()

    def _point_thread(self, c):
        def note(m):
            self.root.after(0, lambda: self.log(f"[M={c['gain']:g}] {m}"))

        rp, d = self.rp, self.laser
        traces, wl, clipped, restore = [], None, 0, None
        try:
            with self.lasw.lock:
                cfg = ops.configure_sweep(
                    d, start_nm=c["start_nm"], stop_nm=c["stop_nm"],
                    speed_nm_s=c["speed_nm_s"], step_nm=c["step_nm"], mode=1)
                restore = cfg["before"]
            with self.board.lock:
                ops.front_end(rp, "AC", "LV", "DC", "HV", c["dec"])
                table = ops.drive_on(rp, carrier=c["carrier"],
                                     modulation=c["modulation"],
                                     amplitude=c["amplitude"], channel=1)
            f_ref = c["harmonic"] * table.modulation
            note(f"drive {table.modulation / 1e3:.1f} kHz, demodulating at "
                 f"{f_ref / 1e3:.1f} kHz")

            n_pts = int(round(abs(c["stop_nm"] - c["start_nm"])
                              / c["step_nm"])) + 1
            secs = (n_pts - 1) * (c["step_nm"] / c["speed_nm_s"])
            plan = ops.capture_plan(secs, decimation=c["dec"])

            for i in range(c["reps"]):
                with self.board.lock:
                    th, out = ops.acquire_async(
                        rp, n_samples=plan["n_samples"], decimation=c["dec"],
                        preroll=plan["preroll"], trigger="CH2_PE", level=1.0)
                    with self.lasw.lock:
                        at = ops.wait_until_at_start(d, timeout=10.0)
                        if not at["arrived"]:
                            note(f"WARNING: laser at {at['at_m'] * 1e9:.3f} "
                                 f"nm, not the start "
                                 f"{at['start_m'] * 1e9:.3f}; sweeping anyway")
                        ops.start_sweep(d)
                        ops.wait_for_sweep(d)
                    th.join(timeout=180.0)
                    if "error" in out:
                        raise out["error"]
                clipped += ops.clipped(out["ch1"])
                with self.lasw.lock:
                    log = ops.read_log(d)
                red = ops.run_map(out, log["wavelengths"], f_ref,
                                  output_rate=5000.0,
                                  nominal_step=c["step_nm"] / c["speed_nm_s"])
                w, a = red.trace.dropna()
                traces.append(a)
                wl = w
                note(f"sweep {i + 1}/{c['reps']}: {a.size} points, "
                     f"max {np.nanmax(np.abs(a)) * 1e3:.3f} mV")

            n = min(t.size for t in traces)
            stats = ops.trace_dynamic_range([t[:n] for t in traces])
            point = dict(gain=c["gain"], wl=wl[:n], clipped=clipped,
                         f_ref=f_ref, **stats)
            self.root.after(0, lambda: self._add_point(point))
        except Exception as exc:                             # noqa: BLE001
            self.root.after(0, lambda: self.log(
                f"[M={c['gain']:g}] FAILED: {exc.__class__.__name__}: {exc}"))
        finally:
            try:
                with self.lasw.lock:
                    ops.stop_sweep(d)
                    if restore:
                        ops.restore_sweep(d, restore)
                with self.board.lock:
                    ops.drive_off(rp)
            except Exception:                                # noqa: BLE001
                pass
            self._running = False
            self.root.after(0, lambda: self.v_status.set("idle"))

    def _add_point(self, p):
        self.points.append(p)
        self.points.sort(key=lambda q: q["gain"])
        if p["clipped"]:
            self.log(f"WARNING: {p['clipped']} samples at the ADC rail at "
                     f"M={p['gain']:g}. This point is not a measurement -- "
                     f"a clipped peak is flat, so its dynamic range is a "
                     f"lower bound and its harmonics are manufactured.")
        self.log(f"M={p['gain']:g}: peak {eng(p['peak'], 'V')}, floor "
                 f"{eng(p['floor_single'], 'V')}, "
                 f"DR {p['dr_single_db']:.1f} dB single / "
                 f"{p['dr_averaged_db']:.1f} dB averaged, "
                 f"tail ratio {p['tail_ratio']:.1f}")
        self._state()
        self._refresh_table()
        self.redraw()

    def drop_last(self):
        if self.points:
            p = self.points.pop()
            self.log(f"dropped M={p['gain']:g}")
            self._state()
            self._refresh_table()
            self.redraw()

    def clear_all(self):
        if self.points and messagebox.askokcancel(
                "Clear", f"Discard all {len(self.points)} points?"):
            self.points.clear()
            self._state()
            self._refresh_table()
            self.plot.clear()

    def _refresh_table(self):
        self.table.delete("1.0", "end")
        self.table.insert("end",
                          f"{'M':>7} {'peak':>10} {'floor':>10} {'DR/dB':>7} "
                          f"{'tail':>6} {'clip':>5}\n")
        self.table.insert("end", "-" * 50 + "\n")
        for p in self.points:
            self.table.insert(
                "end",
                f"{p['gain']:>7.4g} {eng(p['peak'], 'V'):>10} "
                f"{eng(p['floor_single'], 'V'):>10} "
                f"{p['dr_single_db']:>7.1f} {p['tail_ratio']:>6.1f} "
                f"{p['clipped']:>5d}\n")
        if self.points:
            best = max(self.points, key=lambda q: (0 if q["clipped"] else 1,
                                                   q["dr_single_db"]))
            self.table.insert("end", "-" * 50 + "\n")
            self.table.insert("end", f"best unclipped: M={best['gain']:g} at "
                                     f"{best['dr_single_db']:.1f} dB\n")

    # ------------------------------------------------------------- plotting

    def redraw(self):
        if not self.points:
            return self.plot.clear()
        what = self.v_view.get()
        try:
            if what.startswith("waterfall"):
                self._plot_waterfall()
            elif what.startswith("dynamic"):
                g = [p["gain"] for p in self.points]
                self.plot.show(g, [p["dr_single_db"] for p in self.points],
                               "APD gain (M)", "dynamic range (dB)",
                               xfmt=lambda v: f"{v:.3g}",
                               yfmt=lambda v: f"{v:.0f}")
            else:
                g = [p["gain"] for p in self.points]
                self.plot.show_many(
                    [(g, [p["peak"] for p in self.points]),
                     (g, [p["floor_single"] for p in self.points])],
                    "APD gain (M)", "volts",
                    xfmt=lambda v: f"{v:.3g}",
                    yfmt=lambda v: eng(v, "V"),
                    labels=["peak", "noise floor"])
        except Exception as exc:                             # noqa: BLE001
            self.log(f"plot failed: {exc}")

    def _plot_waterfall(self):
        """One trace per gain, stacked. Each is normalised to its own peak so
        the SHAPES compare; the dynamic range column is where the levels are."""
        series, labels = [], []
        for i, p in enumerate(self.points):
            a = np.asarray(p["mean"], dtype=float)
            pk = np.nanmax(np.abs(a)) or 1.0
            series.append((np.asarray(p["wl"]) * 1e9, a / pk + i))
            labels.append(f"M={p['gain']:g}  {p['dr_single_db']:.0f} dB"
                          + ("  CLIPPED" if p["clipped"] else ""))
        self.plot.show_many(series, "wavelength (nm)",
                            "normalised trace, offset by gain",
                            xfmt=lambda v: f"{v:.1f}",
                            yfmt=lambda v: f"{v:.1f}", labels=labels)

    def export(self):
        if not self.points:
            return self.log("nothing to export")
        stamp = time.strftime("%Y%m%d-%H%M%S")
        base = os.path.join(os.getcwd(), f"dr_gain_{stamp}")
        with open(base + ".csv", "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["gain_M", "n_sweeps", "peak_V", "floor_single_V",
                        "floor_averaged_V", "dr_single_dB", "dr_averaged_dB",
                        "tail_ratio", "clipped_samples", "f_ref_Hz"])
            for p in self.points:
                w.writerow([p["gain"], p["n_sweeps"], p["peak"],
                            p["floor_single"], p["floor_averaged"],
                            p["dr_single_db"], p["dr_averaged_db"],
                            p["tail_ratio"], p["clipped"], p["f_ref"]])
        np.savez_compressed(
            base + ".npz",
            gain=np.array([p["gain"] for p in self.points]),
            **{f"trace_{i}": p["mean"] for i, p in enumerate(self.points)},
            **{f"wl_{i}": p["wl"] for i, p in enumerate(self.points)})
        self.log(f"wrote {base}.csv and .npz")

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
    DrBench(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
