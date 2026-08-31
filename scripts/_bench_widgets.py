#!/usr/bin/env python3
"""
Widgets and threading shared by the bench GUIs.

Deliberately separate from both `bench_gui.py` (the old tabbed one) and
`bench.py` (the panel bench that replaces it), so the old tool keeps working
untouched while the new one comes up and can be deleted cleanly afterwards.

Nothing here talks to an instrument. It is Tk and threads only.
"""
from __future__ import annotations

import queue
import threading
import tkinter as tk
from dataclasses import dataclass
from tkinter import ttk

import numpy as np


def eng(v: float, unit: str = "") -> str:
    """Compact engineering-notation number.

    Right for volts and seconds, WRONG for a wavelength axis: it renders
    1550 nm as "1.55k". Anything with a natural unit should pass its own
    formatter rather than reach for this.
    """
    if v is None or not np.isfinite(v):
        return "nan"
    a = abs(v)
    if a == 0:
        return "0" + unit
    for limit, scale, suffix in ((1e-9, 1e12, "p"), (1e-6, 1e9, "n"),
                                 (1e-3, 1e6, "u"), (1.0, 1e3, "m")):
        if a < limit:
            return f"{v * scale:.3g}{suffix}{unit}"
    if a < 1e3:
        return f"{v:.4g}{unit}"
    if a < 1e6:
        return f"{v / 1e3:.4g}k{unit}"
    return f"{v / 1e6:.4g}M{unit}"


# ------------------------------------------------------------------ threads

@dataclass
class Job:
    name: str
    fn: object
    on_done: object = None
    on_error: object = None


class Worker(threading.Thread):
    """Serialises traffic to ONE instrument onto one thread.

    One worker per instrument, not one for the whole bench. The board and the
    laser are independent, and a shared worker makes them falsely dependent:
    arming a capture blocks for as long as it waits for a trigger, so a single
    queue means the sweep that would PROVIDE that trigger is stuck behind it
    and the capture can only ever time out.

    `lock` is held for the duration of each job so that status polling, which
    runs on a timer, can skip rather than interleave.
    """

    def __init__(self, results: queue.Queue, name: str):
        super().__init__(daemon=True, name=f"worker-{name}")
        self.jobs: queue.Queue = queue.Queue()
        self.results = results
        self.label = name
        self.busy = False
        self.lock = threading.Lock()

    def submit(self, name, fn, on_done=None, on_error=None):
        self.jobs.put(Job(name, fn, on_done, on_error))

    def run(self):
        while True:
            job = self.jobs.get()
            self.busy = True
            self.results.put(("busy", (self.label, job.name)))
            try:
                with self.lock:
                    value = job.fn()
                self.results.put(("done", (job, value, None)))
            except Exception as exc:            # surfaced, never swallowed
                self.results.put(("done", (job, None, exc)))
            finally:
                self.busy = False


# --------------------------------------------------------------------- plot

class Plot(tk.Canvas):
    """A minimal line plot. No matplotlib, no dependencies, no zoom.

    Reduces to two points per pixel column -- the min and the max of everything
    falling in it -- so a 33 M-sample record draws quickly AND keeps its narrow
    features. Decimating by stride would drop a 25 us trigger pulse entirely
    and show a clean flat line, which is the wrong kind of wrong.
    """

    PAD_L, PAD_R, PAD_T, PAD_B = 72, 18, 16, 40

    def __init__(self, master, on_cursor=None, **kw):
        super().__init__(master, background="#ffffff", highlightthickness=1,
                         highlightbackground="#c0c0c0", **kw)
        self.x = np.array([])
        self.y = np.array([])
        self.xlabel = ""
        self.ylabel = ""
        self.xfmt = None
        self.yfmt = None
        self.on_cursor = on_cursor
        self._limits = (0.0, 1.0, 0.0, 1.0)
        self._readout = ""
        self.bind("<Configure>", lambda _e: self._draw())
        self.bind("<Motion>", self._hover)
        self.bind("<Leave>", lambda _e: self._clear_readout())

    def show(self, x, y, xlabel="", ylabel="", xfmt=None, yfmt=None):
        self.x = np.asarray(x, dtype=float).ravel()
        self.y = np.asarray(y, dtype=float).ravel()
        self.xlabel, self.ylabel = xlabel, ylabel
        self.xfmt, self.yfmt = xfmt, yfmt
        self._readout = ""
        self._draw()

    def clear(self):
        self.x = np.array([])
        self.y = np.array([])
        self._readout = ""
        self._draw()

    def _box(self):
        w = max(int(self.winfo_width()), 2 * (self.PAD_L + self.PAD_R))
        h = max(int(self.winfo_height()), 120)
        return (self.PAD_L, self.PAD_T, w - self.PAD_R, h - self.PAD_B)

    def _draw(self):
        self.delete("all")
        x0, y0, x1, y1 = self._box()
        self.create_rectangle(x0, y0, x1, y1, outline="#b0b0b0", fill="#ffffff")
        if self.x.size < 2:
            self.create_text((x0 + x1) / 2, (y0 + y1) / 2, fill="#909090",
                             text="no data")
            return

        finite = np.isfinite(self.y)
        if not finite.any():
            self.create_text((x0 + x1) / 2, (y0 + y1) / 2, fill="#909090",
                             text="all points are NaN")
            return
        xmin, xmax = float(np.nanmin(self.x)), float(np.nanmax(self.x))
        ymin, ymax = float(np.nanmin(self.y)), float(np.nanmax(self.y))
        if xmax <= xmin:
            xmax = xmin + 1.0
        if ymax <= ymin:
            ymin, ymax = ymin - 0.5, ymax + 0.5
        self._limits = (xmin, xmax, ymin, ymax)

        def sy(v):
            return y1 - (v - ymin) / (ymax - ymin) * (y1 - y0)

        xf = self.xfmt or (lambda v: eng(v))
        yf = self.yfmt or (lambda v: eng(v))
        for frac in (0.0, 0.25, 0.5, 0.75, 1.0):
            gy = y1 - frac * (y1 - y0)
            self.create_line(x0, gy, x1, gy, fill="#ececec")
            self.create_text(x0 - 6, gy, anchor="e", font=("TkDefaultFont", 7),
                             text=yf(ymin + frac * (ymax - ymin)))
            gx = x0 + frac * (x1 - x0)
            self.create_line(gx, y0, gx, y1, fill="#ececec")
            self.create_text(gx, y1 + 6, anchor="n", font=("TkDefaultFont", 7),
                             text=xf(xmin + frac * (xmax - xmin)))

        coords = []
        for px, lo, hi in self._reduce(int(x1 - x0)):
            gx = x0 + px
            coords.extend([gx, sy(hi), gx, sy(lo)])
        if len(coords) >= 4:
            self.create_line(*coords, fill="#1f5fa8")

        self.create_text((x0 + x1) / 2, y1 + 22, text=self.xlabel,
                         font=("TkDefaultFont", 8))
        self.create_text(14, (y0 + y1) / 2, text=self.ylabel, angle=90,
                         font=("TkDefaultFont", 8))
        if self._readout:
            self.create_text(x1 - 4, y0 + 4, anchor="ne", text=self._readout,
                             font=("TkDefaultFont", 8), fill="#404040")

    def _reduce(self, width: int):
        """min/max per pixel column, so narrow features survive."""
        width = max(int(width), 1)
        n = self.x.size
        if n == 0:
            return
        xmin, xmax = self._limits[0], self._limits[1]
        span = xmax - xmin or 1.0
        col = np.clip(((self.x - xmin) / span * (width - 1)).astype(int),
                      0, width - 1)
        y = self.y
        order = np.argsort(col, kind="stable")
        col, y = col[order], y[order]
        edges = np.flatnonzero(np.diff(col)) + 1
        for seg in np.split(np.arange(col.size), edges):
            if seg.size == 0:
                continue
            vals = y[seg]
            vals = vals[np.isfinite(vals)]
            if vals.size == 0:
                continue
            yield int(col[seg[0]]), float(vals.min()), float(vals.max())

    def _hover(self, event):
        if self.x.size < 2:
            return
        x0, _y0, x1, _y1 = self._box()
        xmin, xmax = self._limits[0], self._limits[1]
        xv = xmin + (event.x - x0) / max(1, x1 - x0) * (xmax - xmin)
        i = int(np.clip(np.searchsorted(self.x, xv), 0, self.y.size - 1))
        if self.on_cursor:
            self.on_cursor(i)
        xf = self.xfmt or (lambda v: eng(v))
        yf = self.yfmt or (lambda v: eng(v))
        readout = f"x={xf(self.x[i])}   y={yf(self.y[i])}"
        if readout != self._readout:
            self._readout = readout
            self._draw()

    def _clear_readout(self):
        if self.on_cursor:
            self.on_cursor(None)
        if self._readout:
            self._readout = ""
            self._draw()


# ------------------------------------------------------------- scrolling rail

class ScrollFrame(ttk.Frame):
    """A vertically scrolling container. The panel rail gets tall."""

    def __init__(self, master, width=330, **kw):
        super().__init__(master, **kw)
        self.canvas = tk.Canvas(self, width=width, highlightthickness=0,
                                borderwidth=0)
        bar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.body = ttk.Frame(self.canvas)
        self._win = self.canvas.create_window((0, 0), window=self.body,
                                              anchor="nw")
        self.canvas.configure(yscrollcommand=bar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")
        self.body.bind("<Configure>", self._on_body)
        self.canvas.bind("<Configure>", self._on_canvas)

    def _on_body(self, _e):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas(self, e):
        self.canvas.itemconfigure(self._win, width=e.width)


def field(parent, row, label, var, unit="", width=12):
    """One labelled entry on a grid row. Returns the Entry."""
    ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=1)
    e = ttk.Entry(parent, textvariable=var, width=width)
    e.grid(row=row, column=1, sticky="w", pady=1)
    if unit:
        ttk.Label(parent, text=unit).grid(row=row, column=2, sticky="w")
    return e
