"""
Writing the deliverable.

CSV for the transfer function (Kevin, 2026-08-14, R9). Human-readable, opens
anywhere, and a sweep is only ~5000 rows.

**Keep the raw capture as `.npz` alongside it.** CSV of 32 M samples would be
absurd, and the raw record is the only way to revisit a demodulation choice
after the fact -- which this project has already had to do more than once.

The header carries provenance as `#` comment lines, followed by a normal CSV
column row. A file found in six months can still say what produced it, and it
still opens in Excel.

**What reads it cleanly:** `pandas.read_csv(path, comment="#")`, the stdlib `csv`
module after filtering `#` lines, Excel, and anything else that treats the first
non-comment row as column names.

**What does not, and why that is fine:** numpy's text readers. `loadtxt`'s
`skiprows` counts comment lines too, and `genfromtxt(names=True)` takes the first
*comment* line as its header. Both need to be told how many comment lines there
are. That is those functions being awkward about a normal CSV, not a defect in
the file -- and a real column-name row is what makes the format useful to a human,
which is why CSV was chosen.
"""

from __future__ import annotations

import csv
import os
from datetime import datetime, timezone

import numpy as np

__all__ = ["write_trace_csv", "write_raw_npz"]


def write_trace_csv(path: str | os.PathLike, wavelength_m, amplitude,
                    metadata: dict | None = None,
                    extra_columns: dict | None = None,
                    keep_invalid: bool = False) -> int:
    """
    Write a wavelength/amplitude trace as CSV. Returns the number of rows.

    `wavelength_m` in metres, written as **nanometres** because that is how
    anyone reading a 1550 nm sweep thinks. `amplitude` in volts at the ADC.

    Points with no wavelength -- NaN, which is what `map_to_wavelength` returns
    for samples outside the laser's table, normally the pre-roll -- are dropped
    by default and **the count is recorded in the header** rather than silently
    disappearing. `keep_invalid=True` writes them with an empty wavelength
    field instead.

    Raises if nothing would be written: an empty CSV is a failure that looks
    like a success until someone opens it.
    """
    wl = np.asarray(wavelength_m, dtype=float).ravel()
    amp = np.asarray(amplitude, dtype=float).ravel()
    if wl.size != amp.size:
        raise ValueError(
            f"wavelength and amplitude must be the same length, got "
            f"{wl.size} and {amp.size}"
        )

    extra_columns = dict(extra_columns or {})
    for name, col in extra_columns.items():
        col = np.asarray(col).ravel()
        if col.size != wl.size:
            raise ValueError(
                f"extra column {name!r} has {col.size} values, expected "
                f"{wl.size}"
            )
        extra_columns[name] = col

    valid = np.isfinite(wl)
    n_dropped = int((~valid).sum())
    keep = np.ones(wl.size, dtype=bool) if keep_invalid else valid
    if not keep.any():
        raise ValueError(
            f"nothing to write: all {wl.size} points lack a wavelength. "
            f"Suspect the trace and the laser's table were not aligned."
        )

    header = {
        "written": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "points": int(keep.sum()),
        "points_without_wavelength": n_dropped,
    }
    header.update(metadata or {})

    with open(path, "w", newline="", encoding="utf-8") as fh:
        for k, v in header.items():
            fh.write(f"# {k}: {v}\n")
        w = csv.writer(fh)
        w.writerow(["wavelength_nm", "amplitude_V", *extra_columns])
        for i in np.flatnonzero(keep):
            wl_field = "" if not valid[i] else f"{wl[i] * 1e9:.6f}"
            w.writerow([wl_field, f"{amp[i]:.9g}",
                        *(f"{extra_columns[n][i]:.9g}" for n in extra_columns)])
    return int(keep.sum())


def write_raw_npz(path: str | os.PathLike, **arrays) -> None:
    """
    Save the raw capture beside the CSV, compressed.

    Deliberately unopinionated about what goes in -- typically the two channel
    records, the sample rate and the laser's wavelength log. The point is that
    the demodulation can be redone later with different settings, which a CSV of
    the finished trace cannot support.
    """
    np.savez_compressed(path, **arrays)
