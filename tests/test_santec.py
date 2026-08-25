"""
Tests for the Santec transport, against a fake laser.

No hardware. A fake transport replays the byte-level replies the manuals
describe, which is enough to pin the three things most likely to be got wrong
and most likely to fail silently: the CR delimiter, the little-endian payload,
and the two command sets returning different units from the same command.

None of this proves the laser behaves as documented. It proves we read what the
manual says the laser sends. P1 is where those meet.

The fake sits at the transport seam, so these tests cover the serial path and the
LAN path identically -- which is the point of having that seam. Only the bytes'
route differs, and neither route is exercised here.
"""

import struct

import numpy as np
import pytest

from rp_lockin.santec import TRIGGER_OUTPUT_MODES, SantecTSL


class FakeLaser:
    """A transport that answers queries from a script, and records what was sent."""

    def __init__(self, replies=None):
        self.sent: list[str] = []
        self.replies = dict(replies or {})
        self.description = "fake"
        self._out = b""
        self.closed = False

    def send(self, data: bytes) -> None:
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

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def laser():
    return FakeLaser()


def connect(fake):
    return SantecTSL(fake)


def block(payload: bytes) -> bytes:
    """Wrap bytes in an IEEE 488.2 definite-length block, as the manuals show."""
    n = str(len(payload))
    return b"#" + str(len(n)).encode() + n.encode() + payload


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


# --------------------------------------------------- the serial transport


class StubSerial:
    """Enough of pyserial's Serial to exercise the chunking logic."""

    def __init__(self, data=b""):
        self.buf = bytearray(data)
        self.written = bytearray()
        self.closed = False
        self.read_sizes = []

    @property
    def in_waiting(self):
        return len(self.buf)

    def read(self, n):
        self.read_sizes.append(n)
        out, self.buf = bytes(self.buf[:n]), self.buf[n:]
        return out

    def write(self, data):
        self.written += data

    def flush(self):
        pass

    def close(self):
        self.closed = True


def test_serial_transport_never_asks_for_more_than_is_buffered():
    """
    The one piece of real logic in the serial transport.

    pyserial's read(n) blocks until n bytes arrive OR the timeout expires. Asking
    for 4096 when three bytes are waiting would stall for the whole timeout on
    every single line read, turning a fast link into a crawl. So it asks for what
    is buffered, and for at least one byte so the caller's loop still advances.
    """
    from rp_lockin.santec import SerialTransport
    stub = StubSerial(b"ABC")
    t = SerialTransport("COM_TEST", _serial=stub)
    assert t.recv(4096) == b"ABC"
    assert stub.read_sizes == [3], "should ask for exactly what was buffered"
    # Nothing buffered: still asks for one byte rather than returning empty,
    # so a blocking read can wait for the reply that has not arrived yet.
    t.recv(4096)
    assert stub.read_sizes[-1] == 1


def test_serial_transport_sends_and_closes():
    from rp_lockin.santec import SerialTransport
    stub = StubSerial()
    t = SerialTransport("COM_TEST", baud=115200, _serial=stub)
    assert "115200 baud" in t.description
    t.send(b"*IDN?\r")
    assert bytes(stub.written) == b"*IDN?\r"
    t.close()
    assert stub.closed


def test_the_same_client_works_over_serial(laser):
    """
    The seam earning its keep: identical behaviour whichever transport is under
    it. This is the serial path, byte for byte the same test as the LAN one.
    """
    from rp_lockin.santec import SantecTSL, SerialTransport
    stub = StubSerial()
    transport = SerialTransport("COM_TEST", _serial=stub)
    client = SantecTSL(transport)
    client.write("*IDN?")
    assert bytes(stub.written) == b"*IDN?\r", "bare CR over serial too"


# ------------------------------------------------------- the command set


def test_command_set_is_reported(laser):
    for reply, want in (("1", "SCPI"), ("+1", "SCPI"),
                        ("0", "Legacy"), ("+0", "Legacy")):
        laser.replies[":SYST:COMM:CODE?"] = reply
        assert connect(laser).command_set() == want


def test_scalar_wavelength_refuses_the_legacy_command_set(laser):
    """
    The two sets answer :WAVelength? in different UNITS -- metres in SCPI,
    nanometres in Legacy. Returning one as the other is wrong by 10^9 and
    nothing in the number would say so, so this refuses instead of guessing.
    """
    laser.replies[":SYST:COMM:CODE?"] = "0"
    with pytest.raises(RuntimeError, match="NANOMETRES"):
        connect(laser).wavelength_m()


def test_scalar_wavelength_works_in_scpi(laser):
    laser.replies[":SYST:COMM:CODE?"] = "+1"
    laser.replies[":WAV?"] = "+1.55000000E-006"
    assert connect(laser).wavelength_m() == pytest.approx(1550e-9)


# ------------------------------------------- setting the stepping laser

class SequencedLaser(FakeLaser):
    """FakeLaser, but a command may answer differently each time it is asked.

    `set_wavelength_m` polls the same query repeatedly and decides on the basis
    of how the answers CHANGE, so a fixed reply table cannot exercise it.
    """

    def __init__(self, sequences=None, replies=None):
        super().__init__(replies)
        self.sequences = {k: list(v) for k, v in (sequences or {}).items()}

    def send(self, data: bytes) -> None:
        cmd = data[:-1].decode("ascii")
        if cmd in self.sequences:
            self.sent.append(cmd)
            seq = self.sequences[cmd]
            value = seq.pop(0) if len(seq) > 1 else seq[0]
            self._out += str(value).encode() + b"\r"
            return
        super().send(data)


def _scpi(**kw):
    """A laser in the SCPI command set, which set_wavelength_m insists on."""
    kw.setdefault("replies", {})
    kw["replies"].setdefault(":SYST:COMM:CODE?", "+1")
    return SequencedLaser(**kw)


def test_setting_a_wavelength_in_nanometres_is_refused():
    """1550 instead of 1.55e-6 would command 1550 METRES.

    The read direction already guards this (wavelength_m raises in Legacy); the
    write direction is worse, because it reaches the hardware before anything
    can notice, so it is refused on the value alone before a byte is sent.
    """
    fake = _scpi()
    rp = connect(fake)
    with pytest.raises(ValueError, match="METRES"):
        rp.set_wavelength_m(1550.0)
    assert fake.sent == [], "nothing may be sent to the laser on a bad value"


def test_setting_a_wavelength_is_refused_in_the_legacy_command_set():
    fake = SequencedLaser(replies={":SYST:COMM:CODE?": "+0"})
    rp = connect(fake)
    with pytest.raises(RuntimeError, match="Legacy"):
        rp.set_wavelength_m(1.55e-6)
    assert not any(c.startswith(":WAV ") for c in fake.sent)


def test_setting_a_wavelength_waits_for_the_laser_to_settle():
    """Two on-target reads are required, not one."""
    target = 1.55e-6
    fake = _scpi(sequences={":WAV?": [1.40e-6, 1.52e-6, target, target]})
    rp = connect(fake)
    got = rp.set_wavelength_m(target, poll=0.001, timeout=5.0)
    assert got == target
    assert f":WAV {target:.12E}" in fake.sent


def test_a_laser_slewing_through_the_target_is_not_mistaken_for_settled():
    """The reading taken mid-slew is a wavelength it was PASSING.

    One on-target sample followed by a different one means it had not arrived.
    Accepting the first would tag the whole 5000-point trace with a wavelength
    the second laser was never parked at -- and nothing downstream could tell.
    """
    target = 1.55e-6
    fake = _scpi(sequences={":WAV?": [target, 1.58e-6, 1.60e-6]})
    rp = connect(fake)
    with pytest.raises(RuntimeError, match="did not reach"):
        rp.set_wavelength_m(target, poll=0.001, timeout=0.05)


def test_a_laser_that_never_moves_raises_and_names_the_likely_cause():
    """The SET form of :WAVelength is inferred, not quoted from a manual.

    An unsupported command returns zero bytes on this laser, so 'wrong command
    string' and 'laser never moved' look identical. The error has to say so.
    """
    fake = _scpi(sequences={":WAV?": [1.40e-6]})
    rp = connect(fake)
    with pytest.raises(RuntimeError, match="not what this driver assumes"):
        rp.set_wavelength_m(1.55e-6, poll=0.001, timeout=0.05)
