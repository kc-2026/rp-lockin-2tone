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
               "p5_first_measurement", "p6_robustness"]


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
