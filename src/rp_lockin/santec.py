"""
Transport for a Santec TSL-770 / TSL-775 tunable laser.

Written 2026-08-14 from the TSL-775 operation manual v1.0 and the TSL-770
manual. **Every command here came from a manual, none from memory** -- on this
project a misspelled SCPI command returns nothing and looks exactly like a
correct one, and the wavelength axis is the one subsystem whose silent failure
is invisible in the output.

**One exception, added 2026-08-25: `set_wavelength_m()`.** The manuals' command
tables carry the QUERY `:WAVelength?` but not its set form, so that one string
is inferred rather than quoted. It is safe to infer only because the method
verifies itself -- it polls the read-back until the laser is on target and has
stopped moving, so a wrong command string raises on timeout instead of passing
silently. Do not copy that pattern to a command whose effect cannot be read
back; there the silence would win.

**NOT THE DRIVER THE BENCH USES, and effectively unexercised.**
`scripts/tsl775.py` (`TSL775`) is what has hardware hours on it and what
`_bench_ops` talks to; this class is what `pipeline.py` assumes. Their
surfaces DIFFER -- `SantecTSL` has setters `TSL775` does not -- and writing
against the wrong one shipped a bug on 2026-09-01 that the suite could not
catch, because the test fake had been modelled on the wrong one too. A
one-off `over_lan` session on 2026-09-01 did answer `*IDN?` and the
`:READout:*` queries correctly, so the transport is sound. See Q35; they
should converge.

Two transports, because the laser offers GPIB, USB and LAN and which one is
convenient is a bench question, not a design one:

    laser = SantecTSL.over_serial("COM29")      # USB, via the FTDI VCP driver
    laser = SantecTSL.over_lan("192.168.1.50")  # LAN

Everything above the transport is identical either way -- same commands, same
delimiter, same binary framing. Only the bytes' route changes.

Three things this gets right that a transport copied from `hardware.py` would
get wrong, each of which fails as something else:

  * **The delimiter is a bare CR**, not CRLF. Reusing the Red Pitaya's line
    reader hangs waiting for a newline that never arrives, and presents as a
    dead cable.
  * **Binary payloads are little-endian.** The Red Pitaya's SCPI path is
    big-endian. Same IEEE 488.2 `#4nnnn` block header, opposite byte order.
  * **Two selectable command sets** change the payload itself: a legacy
    TSL-550-compatible set returns 4-byte integers in units of 0.1 pm, the
    native set returns 8-byte IEEE-754 doubles in metres. `read_wavelengths()`
    works this out from the byte count rather than being told, because both
    decode without error and only one is right.

**On USB the manual never states a baud rate** -- it documents the delimiter and
the throughput and nothing about line settings. Rather than bake in a guess, the
default is 9600 and `scripts/p1_laser_check.py` probes the standard set and
reports which one answers. Settle it there, then pass it explicitly.

What the manuals do NOT say, and this module therefore does not assume: that
there is exactly one logged wavelength per trigger pulse. See Q26, and
`wavelength.check_alignment`, which is how it gets tested.
"""

from __future__ import annotations

import socket
import time
from dataclasses import dataclass

import numpy as np

__all__ = [
    "SantecTSL",
    "TriggerConfig",
    "TcpTransport",
    "SerialTransport",
    "TRIGGER_OUTPUT_MODES",
    "COMMON_BAUD_RATES",
]

# :TRIGger:OUTPut -- TSL-775 manual p98, TSL-770 p98.
TRIGGER_OUTPUT_MODES = {0: "none", 1: "stop", 2: "start", 3: "step"}

# For the probe in p1_laser_check.py. The manual gives no baud rate for USB.
COMMON_BAUD_RATES = (9600, 19200, 38400, 57600, 115200, 230400)


class TcpTransport:
    """Raw bytes over TCP, for the laser's LAN port."""

    def __init__(self, host: str, port: int = 5000, timeout: float = 10.0):
        self.description = f"{host}:{port}"
        self._timeout = timeout
        self._sock = socket.create_connection((host, port), timeout=timeout)
        self._sock.settimeout(timeout)

    def send(self, data: bytes) -> None:
        self._sock.sendall(data)

    def recv(self, n: int) -> bytes:
        return self._sock.recv(n)

    def drain(self) -> None:
        """Throw away anything already in flight. Used by SantecTSL.resync."""
        self._sock.setblocking(False)
        try:
            while self._sock.recv(65536):
                pass
        except (BlockingIOError, OSError):
            pass
        finally:
            self._sock.setblocking(True)
            self._sock.settimeout(self._timeout)

    def close(self) -> None:
        """Close so the instrument sees a clean FIN, never an RST.

        `socket.close()` with unread data still buffered makes the OS send RST
        rather than FIN, and unread data is the normal state here -- a query
        that timed out mid-reply leaves its tail behind, which is exactly the
        desync `resync()` exists for. An RST is an abort, and a small embedded
        stack is likelier to leak a connection slot on abort than on an orderly
        close. This instrument's LAN server stops listening every so often and
        needs a front-panel reset; a leak across connect/close cycles fits
        that. Unproven as the cause, but free to rule out.
        """
        try:
            try:
                self._sock.shutdown(socket.SHUT_WR)
            except OSError:
                pass
            self._sock.settimeout(0.3)
            for _ in range(64):            # bounded: never block on close
                try:
                    if not self._sock.recv(4096):
                        break
                except OSError:
                    break
        finally:
            try:
                self._sock.close()
            except OSError:
                pass


class SerialTransport:
    """
    Raw bytes over a serial port, for USB via the FTDI VCP driver.

    `pyserial` is an OPTIONAL dependency (`pip install -e ".[laser]"`), imported
    here rather than at module scope so the package still imports, and the test
    suite still runs, on a machine that has never seen the laser.
    """

    def __init__(self, port: str, baud: int = 9600, timeout: float = 2.0,
                 _serial=None):
        self.description = f"{port} @ {baud} baud"
        if _serial is not None:  # test seam; see tests/test_santec.py
            self._ser = _serial
            return
        try:
            import serial
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise ImportError(
                "the serial transport needs pyserial: "
                'pip install -e ".[laser]"'
            ) from exc
        self._ser = serial.Serial(port=port, baudrate=baud, timeout=timeout)

    def send(self, data: bytes) -> None:
        self._ser.write(data)
        self._ser.flush()

    def recv(self, n: int) -> bytes:
        # Read what is buffered, but block for at least one byte so the caller's
        # loop makes progress. Asking pyserial for a big n directly would wait
        # out the whole timeout on every read, which makes line reads crawl.
        want = self._ser.in_waiting or 1
        return self._ser.read(max(1, min(n, want)))

    def drain(self) -> None:
        """Throw away anything already in the port's buffers."""
        # reset_input_buffer is the pyserial name; guarded because the test
        # seam passes a stub that need not implement it.
        for name in ("reset_input_buffer", "reset_output_buffer"):
            fn = getattr(self._ser, name, None)
            if fn is not None:
                fn()

    def close(self) -> None:
        try:
            self._ser.close()
        except Exception:  # pragma: no cover - pyserial raises various things
            pass


@dataclass
class TriggerConfig:
    """What the laser says its trigger output is actually doing."""

    mode: int  # 0 none, 1 stop, 2 start, 3 step
    setting: int  # 0/1 -- periodic in wavelength or time, SEE THE WARNING

    # RAW `:TRIGger:OUTPut:STEP?`, and the name flatters it. Its unit is not
    # knowable from this value alone:
    #   * SCPI command set -> metres;  Legacy -> nanometres (the 10^9 trap that
    #     `wavelength_m()` guards and this deliberately does not, because it
    #     would cost an extra query on every read of a diagnostic);
    #   * and if SETTing selects periodic-in-TIME it is seconds, not a length
    #     at all -- while the two manuals disagree about which value that is.
    # Nothing in this project COMPUTES with it; it is reported so a human can
    # compare it against the sweep. Anything that starts computing with it must
    # resolve the units first via `command_set()`. Reviewed 2026-08-25.
    step_m: float
    active_low: bool

    @property
    def mode_name(self) -> str:
        return TRIGGER_OUTPUT_MODES.get(self.mode, f"unknown({self.mode})")

    def describe(self) -> str:
        return (
            f"trigger output: {self.mode_name} (mode {self.mode}), "
            f"SETTing={self.setting}, step={self.step_m:g}, "
            f"{'falling' if self.active_low else 'rising'} edge\n"
            f"  WARNING: the two manuals define SETTing with OPPOSITE encodings "
            f"(TSL-775 p100 says 0=wavelength/1=time, TSL-770 p99 says the "
            f"reverse). This reports the RAW value; do not infer time vs "
            f"wavelength from it without checking against the sweep. See Q24."
        )


class SantecTSL:
    """
    Minimal client for a TSL-770/775, over USB/serial or LAN.

    Build one with a factory rather than the constructor:

        laser = SantecTSL.over_serial("COM29")       # USB, FTDI VCP driver
        laser = SantecTSL.over_lan("192.168.1.50")   # LAN

    Which transport is convenient is a bench question. Nothing above the
    transport differs -- same commands, same bare-CR delimiter, same `#4nnnn`
    binary framing, same little-endian payloads.

    Data volume is trivial either way: a 1 s sweep at the laser's 20 kHz maximum
    trigger rate is at most 20000 points, well under the 500,000 it can log, and
    about 160 kB on the wire.

    This class is READ-MOSTLY on purpose. It reports what the laser is doing and
    reads its logs; every method that changes laser state has `set_` in its name,
    so nothing here alters a sweep by accident.
    """

    def __init__(self, transport):
        self._t = transport
        self._buf = b""

    @classmethod
    def over_serial(cls, port: str, baud: int = 9600,
                    timeout: float = 2.0) -> "SantecTSL":
        """
        USB, through the FTDI virtual COM port.

        **The manual states no baud rate for USB** -- only the delimiter and the
        throughput. 9600 is a starting point, not a documented value; use
        `scripts/p1_laser_check.py` to probe, then pass the answer explicitly.
        """
        return cls(SerialTransport(port, baud, timeout))

    @classmethod
    def over_lan(cls, host: str, port: int = 5000,
                 timeout: float = 10.0) -> "SantecTSL":
        """LAN. 100BASE-TX, TCP/IP, port set on the laser's front panel."""
        return cls(TcpTransport(host, port, timeout))

    @property
    def description(self) -> str:
        return getattr(self._t, "description", "unknown transport")

    # -- plumbing ----------------------------------------------------------

    def close(self) -> None:
        self._t.close()

    def __enter__(self) -> "SantecTSL":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def write(self, cmd: str) -> None:
        # Bare CR. See the module docstring -- CRLF is the Red Pitaya's, and
        # sending it here would leave a stray byte for the next read to trip on.
        self._t.send(cmd.encode("ascii") + b"\r")

    def _read_exact(self, n: int) -> bytes:
        while len(self._buf) < n:
            chunk = self._t.recv(max(4096, n - len(self._buf)))
            if not chunk:
                raise ConnectionError(
                    f"laser stopped responding mid-transfer after "
                    f"{len(self._buf)} of {n} bytes. On serial, suspect the baud "
                    f"rate; on LAN, the connection."
                )
            self._buf += chunk
        out, self._buf = self._buf[:n], self._buf[n:]
        return out

    def _read_line(self) -> str:
        while b"\r" not in self._buf:
            chunk = self._t.recv(4096)
            if not chunk:
                raise ConnectionError(
                    f"no reply terminated with CR (got {self._buf[:40]!r}). On "
                    f"serial, a wrong baud rate looks exactly like this -- "
                    f"either nothing, or bytes that are not ASCII."
                )
            self._buf += chunk
        line, self._buf = self._buf.split(b"\r", 1)
        return line.decode("ascii", errors="replace").strip()

    def resync(self) -> str:
        """Discard anything buffered and prove the link is back in step.

        **Why this exists.** `self._buf` persists between queries, so a read
        that times out part-way through a reply leaves the remainder sitting
        there, and every subsequent query returns the TAIL OF THE PREVIOUS ONE.
        Values keep arriving and keep looking plausible; nothing raises. That is
        not hypothetical -- `hardware.py` records exactly this failure against
        the Red Pitaya on 2026-08-12, where `ACQ:AXI:SIZE?` appeared to return
        the region base, and the fix there was the same: a known query used as a
        sync token.

        Reads only, so it is always safe to call. Returns the identification
        string, which is the proof.

        **Limit worth knowing:** our buffer is not the only place bytes hide.
        Whatever the serial driver or the socket has already received sits
        below us, which is why this calls the transport's `drain()` as well.
        Both shipped transports implement it; a transport that does not cannot
        be fully resynchronised, and this returns the stale reply instead.
        """
        self._buf = b""
        # Drain whatever the transport is still holding. Serial keeps its own
        # buffer below ours, and clearing only ours would leave the stale bytes
        # to arrive on the next read.
        drain = getattr(self._t, "drain", None)
        if drain is not None:
            drain()
        self.write("*IDN?")
        return self._read_line()

    def query(self, cmd: str) -> str:
        self.write(cmd)
        return self._read_line()

    def query_int(self, cmd: str) -> int:
        # Both command sets may answer '+10000' or '10000'; int() takes either.
        return int(self.query(cmd))

    def query_float(self, cmd: str) -> float:
        return float(self.query(cmd))

    def _read_block(self) -> bytes:
        """
        An IEEE 488.2 definite-length block: '#' <ndigits> <length> <payload>.

        Same shape as the Red Pitaya's, so the parsing looks familiar -- but the
        payload byte order is the opposite, which is handled by the caller.
        """
        head = self._read_exact(1)
        if head != b"#":
            raise ValueError(
                f"expected a binary block header '#', got {head!r}. The laser "
                f"may be in a mode that answers in ASCII, or a previous reply "
                f"was left unread in the buffer."
            )
        ndigits = int(self._read_exact(1))
        nbytes = int(self._read_exact(ndigits))
        return self._read_exact(nbytes)

    # -- identity ----------------------------------------------------------

    def idn(self) -> str:
        return self.query("*IDN?")

    # -- the wavelength log ------------------------------------------------

    def logged_points(self) -> int:
        """`:READout:POINts?` -- how many points the last sweep logged (0..500000)."""
        return self.query_int(":READ:POIN?")

    def read_wavelengths(self, n_points: int | None = None) -> np.ndarray:
        """
        `:READout:DATa?` -- the logged wavelengths, in METRES.

        **The log carries wavelengths only. There are no timestamps**, so
        placing these in time is the caller's job -- see
        `wavelength.logged_point_times`.

        The two command sets return different payloads, and rather than being
        told which is active this works it out from the byte count: 4 bytes per
        point means the legacy integer format in units of 0.1 pm, 8 bytes means
        IEEE-754 doubles already in metres. Getting that backwards would scale
        every wavelength by ~10^7 and be obvious, but only after the fact.
        """
        if n_points is None:
            n_points = self.logged_points()
        if n_points <= 0:
            raise ValueError(
                f"the laser reports {n_points} logged points -- run a sweep "
                f"before reading the log."
            )
        self.write(":READ:DAT?")
        raw = self._read_block()

        per_point = len(raw) / n_points
        if per_point == 4:
            # Legacy TSL-550-compatible: signed int, 0.1 pm units, little-endian.
            counts = np.frombuffer(raw, dtype="<i4")
            return counts.astype(np.float64) * 1e-13
        if per_point == 8:
            # Native TSL-770/775 SCPI: IEEE-754 double, metres, little-endian.
            return np.frombuffer(raw, dtype="<f8").astype(np.float64)
        raise ValueError(
            f"cannot interpret the log: {len(raw)} bytes for {n_points} points "
            f"is {per_point} bytes each, and the manuals describe only 4 "
            f"(legacy, 0.1 pm integers) or 8 (native, doubles in metres). "
            f"Suspect a truncated read or a mismatched point count."
        )

    def read_powers(self) -> np.ndarray:
        """
        `:READout:DATa:POWer?` -- the power log, in dBm. 32-bit floats.

        Not needed for the measurement. Useful as a cross-check that the log
        lines up with the sweep, and as the DC power reading that AC coupling
        the photodetector throws away.
        """
        self.write(":READ:DAT:POW?")
        return np.frombuffer(self._read_block(), dtype="<f4").astype(np.float64)

    # -- trigger output ----------------------------------------------------

    def trigger_config(self) -> TriggerConfig:
        """Read back what the trigger output is set to. Never infers."""
        return TriggerConfig(
            mode=self.query_int(":TRIG:OUTP?"),
            setting=self.query_int(":TRIG:OUTP:SETT?"),
            step_m=self.query_float(":TRIG:OUTP:STEP?"),
            active_low=bool(self.query_int(":TRIG:OUTP:ACT?")),
        )

    def set_trigger_output(self, mode: int) -> int:
        """
        `:TRIGger:OUTPut` -- 0 none, 1 stop, 2 start, 3 step. Returns the
        read-back value.

        **Step (3) is what this project needs.** Start (2) emits a single pulse,
        which is enough to align the sweep but leaves no train to measure the
        laser's clock against the board's and no pulse count to check the log
        against.
        """
        if mode not in TRIGGER_OUTPUT_MODES:
            raise ValueError(
                f"mode must be one of {sorted(TRIGGER_OUTPUT_MODES)} "
                f"({TRIGGER_OUTPUT_MODES}), got {mode}"
            )
        self.write(f":TRIG:OUTP {int(mode)}")
        got = self.query_int(":TRIG:OUTP?")
        if got != mode:
            raise RuntimeError(
                f"asked for trigger output mode {mode}, laser reports {got}"
            )
        return got

    def set_trigger_setting(self, value: int) -> int:
        """
        `:TRIGger:OUTPut:SETTing` -- periodic in wavelength or in time.

        **The two manuals document OPPOSITE encodings** (TSL-775 p100: 0 =
        wavelength, 1 = time; TSL-770 p99: the reverse). So this takes the raw
        value, reads it back, and refuses to pretend it knows which is which.
        **Never hardcode a literal here for both models** -- a driver that does
        is wrong on one of them, and the failure is silent: the wrong mode still
        emits a train, just periodic in the wrong variable. See Q24.
        """
        if value not in (0, 1):
            raise ValueError(f"SETTing takes 0 or 1, got {value}")
        self.write(f":TRIG:OUTP:SETT {int(value)}")
        got = self.query_int(":TRIG:OUTP:SETT?")
        if got != value:
            raise RuntimeError(
                f"asked for trigger SETTing {value}, laser reports {got}"
            )
        return got

    # -- sweep -------------------------------------------------------------

    def sweep_state(self) -> int:
        """`:WAVelength:SWEep[:STATe]?` -- the current sweep status."""
        return self.query_int(":WAV:SWE?")

    def command_set(self) -> str:
        """
        `:SYSTem:COMMunicate:CODe?` -- "SCPI" or "Legacy".

        **Worth knowing before trusting any scalar wavelength.** The two sets
        return DIFFERENT UNITS from the same query: SCPI answers in metres,
        Legacy in nanometres. A driver that ignores this is right in one mode and
        wrong by a factor of 10^9 in the other, with nothing to show it.

        The binary log is safe either way -- `read_wavelengths()` infers its
        format from the byte count -- but scalars are not.
        """
        raw = self.query(":SYST:COMM:CODE?").strip()
        # Legacy answers "0"/"1", SCPI "+0"/"+1"; either way 1 is SCPI on the
        # 770/775. A model that spells it out is accepted as-is.
        if raw.lstrip("+-").isdigit():
            return "SCPI" if int(raw) == 1 else "Legacy"
        return raw

    def set_wavelength_m(self, wavelength: float, tolerance: float = 1e-12,
                         timeout: float = 30.0, poll: float = 0.2) -> float:
        """
        Drive the laser to `wavelength` METRES and wait until it gets there.
        Returns the wavelength actually reached.

        This is the stepping laser's path, not the sweeping one: the 11-step
        arm never sweeps in real time, so there is no trigger train and no log
        to index -- it is set, allowed to settle, and read.

        **Settling is decided by measurement, not by a timer.** No busy flag is
        documented for the 770/775, so this polls the read-back until it both
        matches the target and has stopped changing. That also makes the whole
        method self-verifying, which matters more here than usual: the SET form
        of `:WAVelength` is NOT in the command tables taken from the manuals
        (only the query is), and on this project an unsupported command returns
        zero bytes exactly like a supported one. If the command string is wrong
        the read-back simply never converges and this raises -- the one failure
        mode that is not silent.

        Units are metres, and are checked, because the write direction is where
        the SCPI/Legacy unit split is dangerous rather than merely wrong: 1550
        passed instead of 1.55e-6 would command 1550 METRES.
        """
        if not 1.0e-6 <= wavelength <= 2.0e-6:
            raise ValueError(
                f"wavelength must be in METRES, got {wavelength!r}. A C-band "
                f"value is ~1.55e-6, not 1550. Refusing rather than commanding "
                f"the laser with a number that is 10^9 out."
            )
        cs = self.command_set()
        if cs != "SCPI":
            raise RuntimeError(
                f"the laser is in the {cs} command set, which takes "
                f":WAVelength in NANOMETRES rather than metres. Switch it to "
                f"SCPI (Other tab -> Communication) before setting a "
                f"wavelength from this driver."
            )

        self.write(f":WAV {wavelength:.12E}")

        deadline = time.monotonic() + timeout
        previous = None
        while time.monotonic() < deadline:
            time.sleep(poll)
            actual = self.query_float(":WAV?")
            # Both conditions, deliberately: on target AND no longer moving.
            # A laser slewing THROUGH the target would satisfy the first alone
            # for one poll, and the reading taken then would be a wavelength it
            # was passing rather than one it settled at.
            if abs(actual - wavelength) <= tolerance and actual == previous:
                return actual
            previous = actual

        raise RuntimeError(
            f"laser did not reach {wavelength:.9e} m within {timeout} s; last "
            f"read-back {previous!r}. Either it is still slewing (raise "
            f"timeout), the target is outside its range, or the SET form of "
            f":WAVelength is not what this driver assumes -- an unsupported "
            f"command returns zero bytes here, so a wrong string looks exactly "
            f"like a laser that never moved."
        )

    def wavelength_m(self) -> float:
        """
        Present output wavelength, **in metres**.

        Requires the SCPI command set, which is what this project uses -- see
        `command_set()` for why mixing them is dangerous. Raises rather than
        silently returning nanometres if the laser is in Legacy.
        """
        cs = self.command_set()
        if cs != "SCPI":
            raise RuntimeError(
                f"the laser is in the {cs} command set, which answers "
                f":WAVelength? in NANOMETRES rather than metres. Returning that "
                f"as metres would be wrong by 10^9. Switch the laser to SCPI "
                f"(Other tab -> Communication), or read the raw value with "
                f"query_float(':WAV?') and convert deliberately."
            )
        return self.query_float(":WAV?")
