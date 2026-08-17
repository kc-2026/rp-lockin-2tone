"""
Offline tests for the safety behaviour of the SCPI transport.

These exist because H7.4 failed on real hardware on 2026-08-14: an unhandled
exception in a measurement script left the generator driving indefinitely.
`tests/hardware/conftest.py` disarms outputs for the hardware suite, which is
exactly why nobody noticed -- the gap only showed in ad-hoc scripts, which is
where most of this project's measuring actually happens.

No board needed: a fake socket records the command stream, which is enough to
pin the ordering and the best-effort behaviour that the hardware test cannot
easily check.
"""

import socket

import pytest

from rp_lockin.hardware import RedPitaya


class FakeSocket:
    """Records what was sent. Optionally fails, the way a dead link does."""

    def __init__(self, fail_on_send=False):
        self.sent: list[str] = []
        self.closed = False
        self.fail_on_send = fail_on_send

    def sendall(self, data: bytes) -> None:
        if self.fail_on_send:
            raise OSError("simulated dead link")
        self.sent.append(data.decode("ascii").strip())

    def settimeout(self, _t) -> None:
        pass

    def close(self) -> None:
        self.closed = True

    def recv(self, _n) -> bytes:  # pragma: no cover - not used here
        raise AssertionError("these tests do not read")


@pytest.fixture
def fake(monkeypatch):
    s = FakeSocket()
    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: s)
    return s


def test_close_switches_both_outputs_off(fake):
    rp = RedPitaya("fake-host")
    rp.close()
    assert "OUTPUT1:STATE OFF" in fake.sent
    assert "OUTPUT2:STATE OFF" in fake.sent
    assert fake.closed


def test_context_manager_disarms_on_a_crash(fake):
    """H7.4 in miniature: the output must not survive an exception."""
    with pytest.raises(RuntimeError):
        with RedPitaya("fake-host") as rp:
            rp.write("OUTPUT1:STATE ON")
            raise RuntimeError("simulated crash mid-measurement")
    assert fake.sent.count("OUTPUT1:STATE ON") == 1
    assert "OUTPUT1:STATE OFF" in fake.sent
    assert "OUTPUT2:STATE OFF" in fake.sent
    # The disarm must come after the enable, or it proves nothing.
    assert fake.sent.index("OUTPUT1:STATE OFF") > fake.sent.index("OUTPUT1:STATE ON")
    assert fake.closed


def test_disarm_is_best_effort_on_a_dead_link(monkeypatch):
    """
    A disarm that raises would replace the real exception with a useless one.

    This runs while something has already gone wrong, so a broken socket must
    be swallowed and the socket still closed.
    """
    s = FakeSocket(fail_on_send=True)
    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: s)
    rp = RedPitaya("fake-host")
    rp.close()  # must not raise
    assert s.closed


def test_original_exception_survives_a_failing_disarm(monkeypatch):
    s = FakeSocket(fail_on_send=True)
    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: s)
    with pytest.raises(RuntimeError, match="the real problem"):
        with RedPitaya("fake-host"):
            raise RuntimeError("the real problem")
    assert s.closed


def test_deep_capture_restores_coupling_after_the_reset(fake, monkeypatch):
    """
    ACQ:RST silently reverts coupling to DC and gain to LV.

    Without restoring them, an AC-coupled deep capture comes back DC coupled --
    and it succeeds, and looks entirely normal. That matters now the real input
    is a photodetector with a 0-10 V pedestal that only AC coupling removes.

    Checked at the command level, since the failure is invisible in the data.
    """
    rp = RedPitaya("fake-host")
    rp.setup_acquisition(decimation=2, coupling="AC", gain="HV")
    fake.sent.clear()
    rp._reapply_front_end()
    assert "ACQ:SOUR1:COUP AC" in fake.sent
    assert "ACQ:SOUR2:COUP AC" in fake.sent
    assert "ACQ:SOUR1:GAIN HV" in fake.sent
    assert "ACQ:SOUR2:GAIN HV" in fake.sent


def test_front_end_defaults_match_what_the_reset_leaves(fake):
    """Before setup_acquisition, the remembered state must be ACQ:RST's own."""
    rp = RedPitaya("fake-host")
    assert (rp.coupling, rp.gain) == ("DC", "LV")


def test_opting_out_leaves_the_outputs_alone(fake):
    """The escape hatch has to actually work, or people will avoid close()."""
    rp = RedPitaya("fake-host")
    rp.close(disable_outputs=False)
    assert not any("OUTPUT" in c for c in fake.sent)
    assert fake.closed
