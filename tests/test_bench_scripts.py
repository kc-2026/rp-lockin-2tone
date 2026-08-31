"""
The P-series bench scripts: their safety gates and their argument handling.

The measurements need hardware and cannot be tested here. The GATES can, and
they are the part that matters: every one of these scripts can energise an
amplifier feeding an AOM, and P5 has an ordering requirement that exists
because getting it wrong produces a convincing false positive.

What is pinned:

  * every script imports (a typo in one is otherwise found on the bench, with
    the hardware powered),
  * nothing drives an output without --i-am-present AND a typed confirmation,
  * P5.2 refuses to run before P5.1,
  * P5.2 refuses to run if P5.1 was not clean,
  * the result block that gets pasted into SESSION_LOG.md is well formed.
"""

import importlib.util
import json
import os
import sys
import types

import pytest

SCRIPTS = os.path.join(os.path.dirname(__file__), "..", "scripts")


def load(name):
    """Import a bench script without running it."""
    sys.path.insert(0, SCRIPTS)
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
    spec = importlib.util.spec_from_file_location(
        name, os.path.join(SCRIPTS, f"{name}.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


ALL_SCRIPTS = ["_bench", "p2_trigger_check", "p3_drive_chain", "p4_detector",
               "p5_first_measurement", "p6_robustness",
               # Added 2026-08-28. p4_linear_sweep drives OUT1 into an
               # amplifier and an AOM, so an import-time typo in it would be
               # found with the hardware powered -- exactly what this pins.
               "p4_linear_sweep", "full_sweep_test"]


@pytest.mark.parametrize("name", ALL_SCRIPTS)
def test_every_bench_script_imports(name):
    """A NameError in one of these is otherwise discovered on the bench, with
    an amplifier powered and an AOM connected."""
    mod = load(name)
    assert mod.__doc__, f"{name} has no docstring; these are run by a human"


# ------------------------------------------------------------- the gates


def _args(**kw):
    ns = types.SimpleNamespace(i_am_present=False, yes=False)
    for k, v in kw.items():
        setattr(ns, k, v)
    return ns


def test_driving_an_output_needs_the_present_flag():
    bench = load("_bench")
    with pytest.raises(SystemExit, match="i-am-present"):
        bench.require_consent(_args(), "P3.1", "OUT1 will be energised")


def test_the_flag_alone_is_not_enough(monkeypatch):
    """A flag left in a shell history is too easy. It also has to be typed."""
    bench = load("_bench")
    monkeypatch.setattr("builtins.input", lambda _p="": "yes")
    with pytest.raises(SystemExit, match="operator"):
        bench.require_consent(_args(i_am_present=True), "P3.1", "detail")


def test_typing_drive_proceeds(monkeypatch):
    bench = load("_bench")
    monkeypatch.setattr("builtins.input", lambda _p="": "drive")
    bench.require_consent(_args(i_am_present=True), "P3.1", "detail")


def test_no_console_refuses_rather_than_assuming_consent(monkeypatch):
    """An EOF is not a yes. Scripted runs must pass --yes deliberately."""
    bench = load("_bench")

    def no_console(_p=""):
        raise EOFError

    monkeypatch.setattr("builtins.input", no_console)
    with pytest.raises(SystemExit, match="no console"):
        bench.require_consent(_args(i_am_present=True), "P3.1", "detail")


def test_yes_skips_the_prompt_but_still_needs_the_flag():
    bench = load("_bench")
    bench.require_consent(_args(i_am_present=True, yes=True), "P3.1", "d")
    with pytest.raises(SystemExit, match="i-am-present"):
        bench.require_consent(_args(yes=True), "P3.1", "d")


# ------------------------------------------------- P5's ordering requirement


def test_p5_step2_refuses_before_the_control_has_run(tmp_path, monkeypatch):
    """P5.1 before P5.2, always.

    An amplifier-generated product sits at exactly the frequency P5.2 looks at
    and looks entirely legitimate, so a signal found there means nothing until
    the one-tone control is clean. The ordering is the whole value of the step,
    so it is enforced rather than documented.
    """
    p5 = load("p5_first_measurement")
    monkeypatch.setattr(p5, "CONTROL_RECORD", str(tmp_path / "absent.json"))
    with pytest.raises(SystemExit, match="P5.1 has not been run"):
        p5.step2(None, _args(i_am_present=True, yes=True), None)


def test_p5_step2_refuses_when_the_control_was_not_clean(tmp_path, monkeypatch):
    """A dirty control makes P5.2 meaningless, not merely suspect."""
    p5 = load("p5_first_measurement")
    record = tmp_path / "control.json"
    record.write_text(json.dumps({"amplitude_V": 50e-6, "snr": 12.0,
                                  "floor_V": 4e-6, "when": "2026-08-25"}))
    monkeypatch.setattr(p5, "CONTROL_RECORD", str(record))

    class Res:
        def add(self, *a, **k):
            pass

    with pytest.raises(SystemExit, match="was NOT clean"):
        p5.step2(None, _args(i_am_present=True, yes=True), Res())


# ----------------------------------------------------------- the log block


def test_the_result_block_is_pasteable_and_counts_failures():
    bench = load("_bench")
    res = bench.Results("P3.1 -- example")
    res.ok("levels", "-4.0 dBm")
    res.fail("spacing", "10 us, below spec")
    res.add("note", "measured on a 50 ohm load")

    text = res.report()
    assert "### P3.1 -- example" in text
    assert "- PASS levels: -4.0 dBm" in text
    assert "- **FAIL** spacing" in text
    assert "1 failure(s) of 3 checks" in text
    assert len(res.failures) == 1


def test_finish_returns_nonzero_when_something_failed(capsys):
    """The exit code matters: these get run from a shell and their result
    should be visible without reading the output."""
    bench = load("_bench")
    good = bench.Results("ok")
    good.ok("a", 1)
    assert good.finish() == 0

    bad = bench.Results("bad")
    bad.fail("a", 1)
    assert bad.finish() == 1


# ---------------------------------------------------------------------------
# P2.1 works on RAW ADC COUNTS. These pin the conversion, because getting it
# wrong does not crash -- it prints a confident, wrong, out-of-range number.
# On 2026-08-28 P2 failed on real hardware with "302.000 V, expected ~3.3 V"
# while the trigger was a perfectly correct 3.32 V, and the failure text sent
# the reader after an input-range fault that did not exist.


def _trigger_counts(n_pulses=20, fs=31.25e6, width_s=25e-6, period_s=200e-6,
                    high_v=3.3, low_v=0.0):
    """A synthetic TSL-775 trigger train, in ADC counts on the HV range."""
    import numpy as np
    from rp_lockin.constants import ADC_COUNTS_PER_V_HV

    n = int(n_pulses * period_s * fs)
    x = np.full(n, low_v * ADC_COUNTS_PER_V_HV)
    w = int(width_s * fs)
    for k in range(n_pulses):
        i = int(k * period_s * fs)
        x[i:i + w] = high_v * ADC_COUNTS_PER_V_HV
    return x, fs


def test_pulse_shape_reports_volts_not_counts():
    """The regression: counts must be scaled before meeting a volt spec."""
    p2 = load("p2_trigger_check")
    bench = load("_bench")
    trig, fs = _trigger_counts()

    res = bench.Results("t")
    p2.pulse_shape(trig, fs, res)

    level = [r for r in res.rows if r[0].startswith("P2.1 idle / high level")]
    assert level, "the level row disappeared"
    hi = float(level[0][1].split("/")[1])
    assert 2.8 < hi < 3.8, f"reported {hi}, which is not volts"

    assert not [r for r in res.failures if "high level" in r[0]],         f"a correct 3.3 V trigger was failed: {res.failures}"


def test_pulse_shape_rise_time_is_never_negative():
    """t10 and t90 are independent crossing lists, and pairing them by INDEX
    gives a rise time of about MINUS one period as soon as either has an extra
    crossing.

    The condition that does it, and the one a real capture hits: the record
    begins part way UP an edge. The signal is already above the 10% threshold,
    so no rising 10% crossing is found for that first pulse, but 90% is still
    crossed -- so t90 gains a leading entry t10 does not have, and every index
    pair is shifted by one whole pulse. A clean train cannot show this, which
    is why the first version of this test passed against the bug.
    """
    import numpy as np
    p2 = load("p2_trigger_check")
    bench = load("_bench")
    trig, fs = _trigger_counts()
    trig = np.asarray(trig, dtype=float)
    trig[0] = 0.5 * trig.max()   # start between the 10% and 90% thresholds

    res = bench.Results("t")
    p2.pulse_shape(trig, fs, res)

    rows = [r for r in res.rows if r[0].startswith("P2.1 rise time")]
    assert rows, "the rise-time row disappeared"
    rt_ns = float(rows[0][1].split()[0])
    assert rt_ns >= 0.0, f"negative rise time {rt_ns} ns"


def test_pulse_shape_flags_a_clipped_record():
    """A clipped record still yields clean-looking widths and spacings, so the
    clipping has to be reported separately or it is invisible."""
    import numpy as np
    from rp_lockin.constants import ADC_COUNT_MAX

    p2 = load("p2_trigger_check")
    bench = load("_bench")
    trig, fs = _trigger_counts()
    trig = np.asarray(trig)
    trig[100:200] = ADC_COUNT_MAX

    res = bench.Results("t")
    p2.pulse_shape(trig, fs, res)

    assert [r for r in res.failures if "clipped" in r[0]],         "clipping at the ADC rail went unreported"


def test_a_trigger_left_on_the_lv_range_is_still_caught():
    """The check must keep catching the real fault it was written for: a 3.3 V
    trigger on the +/-1 V range clips to a flat line."""
    p2 = load("p2_trigger_check")
    bench = load("_bench")
    # LV clips at +/-1 V, so the 3.3 V pulse arrives as ~1 V worth of counts
    # read against the HV scale -- about 0.17 V.
    trig, fs = _trigger_counts(high_v=0.17)

    res = bench.Results("t")
    p2.pulse_shape(trig, fs, res)

    assert [r for r in res.failures if "high level" in r[0]],         "a clipped LV trigger was accepted as a healthy 3.3 V one"

