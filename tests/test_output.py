"""Tests for the CSV deliverable."""

import numpy as np
import pytest

from rp_lockin.output import write_raw_npz, write_trace_csv


def read_back(path):
    """Header comments and data rows, the way a consumer would see them."""
    lines = path.read_text(encoding="utf-8").splitlines()
    header = [ln[2:] for ln in lines if ln.startswith("# ")]
    body = [ln for ln in lines if not ln.startswith("#")]
    return header, body


def test_writes_wavelength_in_nm_and_amplitude_in_volts(tmp_path):
    p = tmp_path / "t.csv"
    n = write_trace_csv(p, np.array([1520e-9, 1550e-9]), np.array([1e-6, 2e-6]))
    assert n == 2
    header, body = read_back(p)
    assert body[0] == "wavelength_nm,amplitude_V"
    assert body[1].startswith("1520.000000,")
    assert "1e-06" in body[1] or "1.0e-06" in body[1] or "1e-6" in body[1]


def test_a_consumer_can_read_it_without_knowing_the_header_length(tmp_path):
    """
    The point of `#` comments: nothing downstream needs to be told how many
    there are. This is the stdlib route, and the same shape `pandas.read_csv(
    comment="#")` and Excel take.

    Numpy's text readers are the exception -- `loadtxt`'s `skiprows` counts
    comment lines, and `genfromtxt(names=True)` takes the first COMMENT line as
    its header. Both need the count. That is those functions being awkward about
    an ordinary CSV rather than a fault in the file, and a real column row is
    what makes the format useful to a person, which is why CSV was chosen.
    """
    import csv as _csv

    p = tmp_path / "t.csv"
    wl = np.linspace(1520e-9, 1570e-9, 50)
    write_trace_csv(p, wl, np.ones(50) * 3e-6,
                    metadata={"f_lockin_Hz": 991821.3})

    with open(p, newline="", encoding="utf-8") as fh:
        rows = list(_csv.DictReader(
            ln for ln in fh if not ln.startswith("#")))
    assert len(rows) == 50
    assert set(rows[0]) == {"wavelength_nm", "amplitude_V"}
    assert np.allclose([float(r["wavelength_nm"]) for r in rows], wl * 1e9)
    assert np.allclose([float(r["amplitude_V"]) for r in rows], 3e-6)


def test_points_without_a_wavelength_are_dropped_and_counted(tmp_path):
    """
    Pre-roll samples have no wavelength. Dropping them is right; dropping them
    silently is not -- the count goes in the header.
    """
    p = tmp_path / "t.csv"
    wl = np.array([np.nan, np.nan, 1550e-9, 1551e-9])
    n = write_trace_csv(p, wl, np.arange(4.0))
    assert n == 2
    header, body = read_back(p)
    assert any("points_without_wavelength: 2" in h for h in header)
    assert len(body) == 3  # column row + 2 data rows


def test_invalid_points_can_be_kept_with_an_empty_field(tmp_path):
    p = tmp_path / "t.csv"
    n = write_trace_csv(p, np.array([np.nan, 1550e-9]), np.array([1.0, 2.0]),
                        keep_invalid=True)
    assert n == 2
    _, body = read_back(p)
    assert body[1].startswith(","), "a missing wavelength should be an empty field"


def test_metadata_reaches_the_header(tmp_path):
    p = tmp_path / "t.csv"
    write_trace_csv(p, np.array([1550e-9]), np.array([1.0]),
                    metadata={"f_lockin_Hz": 991821.3, "bandwidth_Hz": 2250})
    header, _ = read_back(p)
    assert any("f_lockin_Hz: 991821.3" in h for h in header)
    assert any("written:" in h for h in header)


def test_extra_columns_are_written(tmp_path):
    p = tmp_path / "t.csv"
    write_trace_csv(p, np.array([1550e-9, 1551e-9]), np.array([1.0, 2.0]),
                    extra_columns={"t_s": np.array([0.0, 2e-4])})
    _, body = read_back(p)
    assert body[0] == "wavelength_nm,amplitude_V,t_s"
    assert body[2].endswith("0.0002")


def test_an_all_invalid_trace_refuses_rather_than_writing_an_empty_file(tmp_path):
    """An empty CSV looks like a success until someone opens it."""
    with pytest.raises(ValueError, match="nothing to write"):
        write_trace_csv(tmp_path / "t.csv", np.array([np.nan, np.nan]),
                        np.array([1.0, 2.0]))


def test_length_mismatches_refuse(tmp_path):
    with pytest.raises(ValueError, match="same length"):
        write_trace_csv(tmp_path / "t.csv", np.zeros(3), np.zeros(4))
    with pytest.raises(ValueError, match="extra column"):
        write_trace_csv(tmp_path / "t.csv", np.array([1550e-9]),
                        np.array([1.0]), extra_columns={"bad": np.zeros(5)})


def test_raw_npz_round_trips(tmp_path):
    p = tmp_path / "raw.npz"
    write_raw_npz(p, ch1=np.arange(10), fs=np.array(125e6))
    with np.load(p) as d:
        assert np.array_equal(d["ch1"], np.arange(10))
        assert d["fs"] == 125e6
