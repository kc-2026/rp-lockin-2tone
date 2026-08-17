"""
Tests for the Santec transport, against a fake laser.

No hardware. A fake socket replays the byte-level replies the manuals describe,
which is enough to pin the three things most likely to be got wrong and most
likely to fail silently: the CR delimiter, the little-endian payload, and the
two command sets returning different units in the same command.

None of this proves the laser behaves as documented. It proves we read what the
manual says the laser sends. P1 is where those meet.
"""

import socket
import struct

import numpy as np
import pytest

from rp_lockin.santec import TRIGGER_OUTPUT_MODES, SantecTSL


class FakeLaser:
    """Replies to queries from a script; records what was sent."""

    def __init__(self, replies=None):
        self.sent: list[str] = []
        self.replies = dict(replies or {})
        self._out = b""
        self.closed = False

    # -- socket interface --------------------------------------------------
    def sendall(self, data: bytes) -> None:
        assert data.endswith(b"\r"), "Santec delimiter is a bare CR"
        assert not data.endswith(b"\r\n"), "CRLF is the Red Pitaya's, not this"
        cmd = data[:-1].decode("ascii")
        self.sent.append(cmd)
        if cmd in self.replies:
            r = self.replies[cmd]
            self._out += r if isinstance(r, bytes) else (str(r).encode() + b"\r")

    def recv(self, n: int) -> bytes:
        if not self._out:
            raise TimeoutError("fake laser has nothing more to say")
        out, self._out = self._out[:n], self._out[n:]
        return out

    def settimeout(self, _t) -> None:
        pass

    def close(self) -> None:
        self.closed = True


def block(payload: bytes) -> bytes:
    """Wrap bytes in an IEEE 488.2 definite-length block, as the manuals show."""
    n = str(len(payload))
    return b"#" + str(len(n)).encode() + n.encode() + payload


@pytest.fixture
def laser(monkeypatch):
    fake = FakeLaser()
    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: fake)
    return fake


def connect(fake):
    return SantecTSL("fake-laser")


# ------------------------------------------------------------- the basics


def test_commands_are_terminated_with_bare_cr(laser):
    """CRLF would hang a real laser. The fake asserts it, so this pins it."""
    rp = connect(laser)
    laser.replies["*IDN?"] = "SANTEC,TSL-775,12345,1.0"
    assert rp.idn() == "SANTEC,TSL-775,12345,1.0"
    assert laser.sent == ["*IDN?"]


def test_point_count_accepts_both_command_sets(laser):
    """Legacy answers '10000', native answers '+10000'."""
    for reply, want in (("10000", 10000), ("+10000", 10000)):
        laser.replies[":READ:POIN?"] = reply
        assert connect(laser).logged_points() == want


# --------------------------------------------------- the wavelength log


def test_native_format_is_doubles_in_metres(laser):
    """8 bytes per point: IEEE-754 doubles, already in metres, little-endian."""
    wl = np.array([1520e-9, 1545e-9, 1570e-9])
    laser.replies[":READ:POIN?"] = "+3"
    laser.replies[":READ:DAT?"] = block(wl.astype("<f8").tobytes())
    got = connect(laser).read_wavelengths()
    assert np.allclose(got, wl)


def test_legacy_format_is_integers_in_tenths_of_a_picometre(laser):
    """
    4 bytes per point, 0.1 pm units. Getting the scale wrong here would put
    every wavelength out by ~10^7 -- obvious, but only once someone looks.
    """
    wl = np.array([1520e-9, 1545e-9, 1570e-9])
    counts = np.round(wl / 1e-13).astype("<i4")
    laser.replies[":READ:POIN?"] = "3"
    laser.replies[":READ:DAT?"] = block(counts.tobytes())
    got = connect(laser).read_wavelengths()
    assert np.allclose(got, wl, atol=1e-13)


def test_the_format_is_inferred_not_assumed(laser):
    """
    The same command returns different units depending on a laser setting we do
    not control. Inferring it from the byte count means neither has to be
    guessed -- which matters because both decode without error.
    """
    wl = np.linspace(1520e-9, 1570e-9, 50)
    for dtype, payload in (("<f8", wl.astype("<f8").tobytes()),
                           ("<i4", np.round(wl / 1e-13).astype("<i4").tobytes())):
        laser.replies[":READ:POIN?"] = "50"
        laser.replies[":READ:DAT?"] = block(payload)
        got = connect(laser).read_wavelengths()
        assert np.allclose(got, wl, atol=1e-13), dtype


def test_payload_is_little_endian(laser):
    """
    Big-endian is the Red Pitaya's convention. Decoding this log that way gives
    numbers that are wrong by orders of magnitude but still parse cleanly.
    """
    wl = np.array([1550e-9])
    laser.replies[":READ:POIN?"] = "1"
    laser.replies[":READ:DAT?"] = block(struct.pack("<d", wl[0]))
    assert np.allclose(connect(laser).read_wavelengths(), wl)
    # The same bytes read big-endian are nowhere near a real wavelength.
    assert not np.isclose(struct.unpack(">d", struct.pack("<d", wl[0]))[0],
                          wl[0])


def test_an_unreadable_byte_count_refuses(laser):
    laser.replies[":READ:POIN?"] = "10"
    laser.replies[":READ:DAT?"] = block(b"x" * 33)  # 3.3 bytes per point
    with pytest.raises(ValueError, match="bytes each"):
        connect(laser).read_wavelengths()


def test_reading_an_empty_log_refuses(laser):
    laser.replies[":READ:POIN?"] = "0"
    with pytest.raises(ValueError, match="run a sweep"):
        connect(laser).read_wavelengths()


def test_a_missing_block_header_says_why(laser):
    laser.replies[":READ:POIN?"] = "3"
    laser.replies[":READ:DAT?"] = b"1550.0\r"
    with pytest.raises(ValueError, match="binary block header"):
        connect(laser).read_wavelengths()


def test_power_log_is_float32_dbm(laser):
    p = np.array([-3.5, -3.6, -3.4], dtype="<f4")
    laser.replies[":READ:DAT:POW?"] = block(p.tobytes())
    assert np.allclose(connect(laser).read_powers(), p, atol=1e-6)


# ------------------------------------------------------------ the trigger


def test_trigger_config_reports_the_raw_setting(laser):
    laser.replies[":TRIG:OUTP?"] = "3"
    laser.replies[":TRIG:OUTP:SETT?"] = "1"
    laser.replies[":TRIG:OUTP:STEP?"] = "+1.00000000E-010"
    laser.replies[":TRIG:OUTP:ACT?"] = "0"
    c = connect(laser).trigger_config()
    assert c.mode == 3 and c.mode_name == "step"
    assert c.setting == 1
    assert c.step_m == pytest.approx(1e-10)
    assert not c.active_low
    # It must NOT claim to know whether 1 means time or wavelength.
    assert "OPPOSITE" in c.describe() and "Q24" in c.describe()


def test_setting_the_trigger_mode_reads_it_back(laser):
    laser.replies[":TRIG:OUTP?"] = "3"
    assert connect(laser).set_trigger_output(3) == 3
    assert ":TRIG:OUTP 3" in laser.sent


def test_a_mode_that_does_not_stick_raises(laser):
    """A setting command that silently does nothing is this project's signature
    failure. Read-back is the only defence."""
    laser.replies[":TRIG:OUTP?"] = "0"
    with pytest.raises(RuntimeError, match="laser reports 0"):
        connect(laser).set_trigger_output(3)


def test_a_setting_that_does_not_stick_raises(laser):
    laser.replies[":TRIG:OUTP:SETT?"] = "0"
    with pytest.raises(RuntimeError, match="laser reports 0"):
        connect(laser).set_trigger_setting(1)


def test_bad_arguments_refuse_before_touching_the_laser(laser):
    rp = connect(laser)
    with pytest.raises(ValueError, match="mode must be one of"):
        rp.set_trigger_output(7)
    with pytest.raises(ValueError, match="SETTing takes 0 or 1"):
        rp.set_trigger_setting(2)
    assert laser.sent == [], "nothing should have been sent"


def test_mode_names_match_the_manual():
    assert TRIGGER_OUTPUT_MODES == {0: "none", 1: "stop", 2: "start", 3: "step"}


# ------------------------------------------------------------- lifecycle


def test_context_manager_closes(laser):
    with connect(laser) as rp:
        laser.replies["*IDN?"] = "SANTEC,TSL-770,1,1"
        rp.idn()
    assert laser.closed
