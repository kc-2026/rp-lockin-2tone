"""
santec TSL-775 Tunable Semiconductor Laser -- USB driver + CLI.

Protocol notes, from the TSL-775 Operation Manual section 7 (Operation by
Communication):

  * The command delimiter is CR (0x0D).  A command is parsed once the
    delimiter is seen; responses have the delimiter appended (7.2.2, p.56).
  * USB transfer is specified as "1 MBps (with D2XX driver)" (7.2.2, p.56),
    and the supplied driver enumerates the unit as "Santec USB TSL-775"
    (7.2.3, p.58).  The instrument's USB bridge is an FTDI FT232H.
  * Two command sets exist, "Legacy" and "SCPI", selected on the front panel
    (Other > Communication) or via :SYSTem:COMMunicate:CODe (7.4.4, p.67).
    Both accept the same command mnemonics -- only response *formatting*
    differs:
        Legacy -> plain decimal, wavelength in nm     e.g. "1550.0000"
        SCPI   -> exponential, SI base units (meters) e.g. "+1.5500000E-006"
    So *IDN? and friends work regardless of which set is active.
  * IEEE-488.2 common commands (*IDN?, *STB?, *ESR?, ...) are listed on p.61.
  * The default d2xx init sequence mirrors santec's own reference driver
    (Ftd2xxhelper._initialize in github.com/santec-corporation/Python-FTDI):
    8-N-1, no flow control, 9600 baud, then FT_SetBitMode(0x00, 0x40) --
    synchronous 245 FIFO.

Three backends are provided:

  d2xx  (default)  FTDI's D2XX interface, which is what the manual specifies
                   for USB.  Addresses the device directly by its FTDI
                   descriptor, so no COM port is needed.
  vcp              A serial/virtual-COM port, for when the FTDI VCP driver is
                   bound instead (e.g. COM29) or when talking over another
                   serial transport.
  lan              A raw TCP socket.  Same commands and same CR delimiter
                   (manual 7.3.2, p.59); set the IP and port on the front
                   panel under Other > Communication > LAN.

Every command issued by `probe` is READ-ONLY.  Nothing in the default paths
enables laser emission, opens the shutter, or resets the instrument.
"""

# ---------------------------------------------------------------------------
# VENDORED into this repository on 2026-08-28, from the separate TSL-775
# bring-up effort (`TSL775_HANDOFF.md`). Until then the only working laser code
# lived in a folder on the Desktop, which is why two sessions in a row
# described the laser as an unsolved blocker while it had in fact been working
# since 2026-08-21.
#
# HOW THIS RELATES TO src/rp_lockin/santec.py -- they are NOT duplicates:
#
#   santec.py   written from the manuals, never yet exercised against the
#               instrument. Reads the log (read_wavelengths, logged_points),
#               reads and sets the trigger mode, reports sweep state. It has
#               NO sweep span/speed/mode setters and cannot START a sweep.
#   tsl775.py   THIS FILE. Proven against the instrument. Configures and runs
#               sweeps, and reads both logs. Use it to drive a sweep.
#
# Use LAN. The USB path here is retained only for diagnostics -- USB is a
# hardware fault inside this instrument and cannot carry commands.
# ---------------------------------------------------------------------------


from __future__ import annotations

import argparse
import sys
import time

DEFAULT_PORT = "COM29"
DEFAULT_BAUD = 9600
DEFAULT_TCP_PORT = 5000
TERM = b"\r"

# Baud rates tried by --scan-baud, most likely first.
CANDIDATE_BAUDS = [9600, 115200, 57600, 38400, 19200, 230400, 4800, 460800, 921600]


class TSL775Error(Exception):
    pass


class Timeout(TSL775Error):
    pass


# ---------------------------------------------------------------- backends


class _Backend:
    """Byte-level transport.  Subclasses provide open/close/write/read_some."""

    def open(self):
        raise NotImplementedError

    def close(self):
        raise NotImplementedError

    def write(self, data: bytes):
        raise NotImplementedError

    def read_some(self) -> bytes:
        """Return whatever bytes are available right now (possibly b'')."""
        raise NotImplementedError

    def reset_input(self):
        pass


class D2xxBackend(_Backend):
    """FTDI D2XX -- the interface the manual specifies for USB.

    This unit's FT232H is configured in its EEPROM for 245 FIFO mode
    (word 0x00 bit0 IsFifo = 1, bit4 IsVCP = 0), not UART mode.

    Three init sequences are available:

      santec  (default)  exactly what santec's own reference driver does --
                         8-N-1, no flow control, 9600 baud, then
                         FT_SetBitMode(0x00, 0x40) for synchronous 245 FIFO.
      fifo               asynchronous 245 FIFO with RTS/CTS, per FTDI's
                         application guidance.
      uart               plain UART, for a unit whose EEPROM configures one.
    """

    name = "d2xx"

    FT_FLOW_NONE = 0x0000
    FT_FLOW_RTS_CTS = 0x0100

    def __init__(self, baud=DEFAULT_BAUD, timeout=2.0, index=0, mode="santec"):
        self.baud = baud
        self.timeout = timeout
        self.index = index
        self.mode = mode
        self.dev = None

    @staticmethod
    def _ftd2xx():
        try:
            import ftd2xx
        except ImportError as e:
            raise TSL775Error(
                "the d2xx backend needs the ftd2xx package:\n"
                "    python -m pip install ftd2xx"
            ) from e
        return ftd2xx

    @classmethod
    def list_devices(cls):
        ftd2xx = cls._ftd2xx()
        out = []
        for i in range(ftd2xx.createDeviceInfoList()):
            try:
                out.append(ftd2xx.getDeviceInfoDetail(i))
            except Exception:  # noqa: BLE001
                pass
        return out

    def open(self):
        ftd2xx = self._ftd2xx()
        try:
            self.dev = ftd2xx.open(self.index)
        except Exception as e:  # noqa: BLE001
            raise TSL775Error(f"cannot open FTDI device {self.index}: {e}") from e
        ms = int(self.timeout * 1000) or 1000
        if self.mode == "santec":
            # santec's own reference sequence, from Ftd2xxhelper._initialize()
            # in github.com/santec-corporation/Python-FTDI.  Order matters:
            # the UART parameters are set first, then the bit mode.  0x40 is
            # synchronous 245 FIFO; there is no purge and no latency change.
            self.dev.setDataCharacteristics(8, 0, 0)   # 8-N-1
            self.dev.setFlowControl(self.FT_FLOW_NONE, 17, 19)
            self.dev.setBaudRate(9600)
            self.dev.setTimeouts(ms, ms)
            self.dev.setBitMode(0x00, 0x40)
            return self

        self.dev.setTimeouts(ms, ms)
        self.dev.setBitMode(0x00, 0x00)  # reset to the EEPROM-configured default
        if self.mode == "fifo":
            # Asynchronous 245 FIFO: no baud/line settings.  Small latency
            # timer so short replies are not held back, large USB buffers, and
            # the RTS/CTS handshake FTDI specifies for FIFO transfers.
            self.dev.setLatencyTimer(2)
            self.dev.setUSBParameters(65536, 65536)
            self.dev.setFlowControl(self.FT_FLOW_RTS_CTS, 0, 0)
        else:
            self.dev.setBaudRate(self.baud)
            self.dev.setDataCharacteristics(8, 0, 0)  # 8 data bits, 1 stop, no parity
        self.dev.purge()
        return self

    def eeprom_mode(self):
        """Read EEPROM word 0 and report the configured chip mode.

        Read-only; this never writes to the EEPROM.
        """
        import ctypes

        dll = ctypes.WinDLL("ftd2xx.dll")
        val = ctypes.c_ushort()
        if dll.FT_ReadEE(self.dev.handle, ctypes.c_ulong(0), ctypes.byref(val)) != 0:
            return None
        lo = val.value & 0xFF
        return {
            "word0": val.value,
            "is_fifo": bool(lo & 0x01),
            "is_fifo_target": bool(lo & 0x02),
            "is_fast_serial": bool(lo & 0x04),
            "is_ft1248": bool(lo & 0x08),
            "is_vcp": bool(lo & 0x10),
        }

    def close(self):
        if self.dev is not None:
            try:
                self.dev.close()
            except Exception:  # noqa: BLE001
                pass
            self.dev = None

    def write(self, data: bytes):
        self.dev.write(data)

    def read_some(self) -> bytes:
        q = self.dev.getQueueStatus()
        if not q:
            time.sleep(0.01)
            return b""
        return self.dev.read(q)

    def reset_input(self):
        self.dev.purge()

    def describe(self) -> str:
        try:
            info = self.dev.getDeviceInfo()
            desc = info.get("description", b"")
            ser = info.get("serial", b"")
            dec = lambda v: v.decode(errors="replace") if isinstance(v, bytes) else str(v)
            return f"FTDI '{dec(desc)}' serial {dec(ser)}"
        except Exception:  # noqa: BLE001
            return "FTDI device"


class VcpBackend(_Backend):
    """Plain serial / virtual COM port."""

    name = "vcp"

    def __init__(self, port=DEFAULT_PORT, baud=DEFAULT_BAUD, timeout=2.0):
        self.port = port
        self.baud = baud
        self.timeout = timeout
        self.ser = None

    @staticmethod
    def _serial():
        try:
            import serial
        except ImportError as e:
            raise TSL775Error(
                "the vcp backend needs pyserial:\n"
                "    python -m pip install pyserial"
            ) from e
        return serial

    def open(self):
        serial = self._serial()
        try:
            self.ser = serial.Serial(
                port=self.port,
                baudrate=self.baud,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=0.05,
                write_timeout=self.timeout,
            )
        except serial.SerialException as e:
            raise TSL775Error(f"cannot open {self.port}: {e}") from e
        self.ser.reset_input_buffer()
        self.ser.reset_output_buffer()
        return self

    def close(self):
        if self.ser is not None and self.ser.is_open:
            self.ser.close()
        self.ser = None

    def write(self, data: bytes):
        self.ser.write(data)
        self.ser.flush()

    def read_some(self) -> bytes:
        return self.ser.read(max(1, self.ser.in_waiting))

    def reset_input(self):
        self.ser.reset_input_buffer()

    def describe(self) -> str:
        return f"serial port {self.port}"


class LanBackend(_Backend):
    """Raw TCP socket.

    LAN uses the same CR delimiter and the same command set as USB
    (manual 7.3.2, p.59).  Set the IP, subnet, gateway and port on the front
    panel under Other > Communication > LAN.
    """

    name = "lan"

    def __init__(self, host, tcp_port=5000, timeout=2.0):
        self.host = host
        self.tcp_port = tcp_port
        self.timeout = timeout
        self.sock = None

    def open(self):
        import socket

        try:
            self.sock = socket.create_connection(
                (self.host, self.tcp_port), timeout=self.timeout)
        except OSError as e:
            raise TSL775Error(
                f"cannot connect to {self.host}:{self.tcp_port}: {e}") from e
        # Instrument commands are short single writes followed by a read, which
        # is exactly the pattern Nagle's algorithm delays.  Measured on this
        # unit: median round trip 6.7 ms with Nagle on, 4.7 ms with it off.
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.sock.settimeout(0.1)
        return self

    def close(self):
        if self.sock is not None:
            try:
                self.sock.close()
            except OSError:
                pass
            self.sock = None

    def write(self, data: bytes):
        self.sock.sendall(data)

    def read_some(self) -> bytes:
        import socket

        try:
            return self.sock.recv(4096)
        except socket.timeout:
            return b""

    def reset_input(self):
        """Drop any unread bytes.

        Without this the base-class no-op leaves a late reply sitting in the
        socket, and every subsequent query reads one response behind -- a
        desync that silently returns stale values rather than failing.
        """
        import socket

        self.sock.settimeout(0)
        try:
            while self.sock.recv(4096):
                pass
        except (BlockingIOError, socket.error):
            pass
        finally:
            self.sock.settimeout(0.1)

    def describe(self) -> str:
        return f"{self.host}:{self.tcp_port}"


# ------------------------------------------------------------------ device


class TSL775:
    """Command-level interface to a TSL-775."""

    def __init__(self, backend: _Backend, timeout=2.0, verbose=False):
        self.backend = backend
        self.timeout = timeout
        self.verbose = verbose

    @classmethod
    def connect(cls, backend="d2xx", port=DEFAULT_PORT, baud=DEFAULT_BAUD,
                timeout=2.0, verbose=False, mode="santec",
                host=None, tcp_port=DEFAULT_TCP_PORT):
        if backend == "d2xx":
            be = D2xxBackend(baud, timeout, mode=mode)
        elif backend == "lan":
            be = LanBackend(host, tcp_port, timeout)
        else:
            be = VcpBackend(port, baud, timeout)
        return cls(be.open(), timeout, verbose)

    def close(self):
        self.backend.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # -- raw i/o ---------------------------------------------------------

    def write(self, cmd: str):
        """Send one command with the CR delimiter appended."""
        payload = cmd.strip().encode("ascii") + TERM
        if self.verbose:
            print(f"  TX  {payload!r}", file=sys.stderr)
        self.backend.write(payload)

    def read_line(self) -> str:
        """Read one CR-delimited response.

        The manual specifies CR; CR, LF and CRLF are all accepted so that a
        firmware which also appends LF cannot desynchronize the stream.
        """
        buf = bytearray()
        deadline = time.time() + self.timeout
        while time.time() < deadline:
            chunk = self.backend.read_some()
            if not chunk:
                continue
            for b in chunk:
                if b in (0x0D, 0x0A):
                    if buf:
                        if self.verbose:
                            print(f"  RX  {bytes(buf)!r}", file=sys.stderr)
                        return buf.decode("ascii", errors="replace").strip()
                else:
                    buf.append(b)
        raise Timeout(
            f"no response within {self.timeout}s"
            + (f" (partial: {bytes(buf)!r})" if buf else "")
        )

    def query(self, cmd: str) -> str:
        self.backend.reset_input()
        self.write(cmd)
        return self.read_line()

    # -- binary block transfers ------------------------------------------

    def read_block(self) -> bytes:
        """Read one IEEE 488.2 definite-length block.

        Format is '#', one digit giving the length of the byte count, that
        many digits of byte count, then the payload (manual p.93).  Reading
        this with read_line() would corrupt it -- 0x0D occurs freely inside
        binary payloads -- so the payload length is taken from the header and
        exactly that many bytes are consumed.
        """
        buf = bytearray()
        deadline = time.time() + self.timeout

        def fill(target):
            nonlocal deadline
            while len(buf) < target:
                if time.time() > deadline:
                    raise Timeout(
                        f"block truncated: got {len(buf)} of {target} bytes")
                chunk = self.backend.read_some()
                if chunk:
                    buf.extend(chunk)
                    deadline = time.time() + self.timeout

        fill(2)
        if buf[0:1] != b"#":
            raise TSL775Error(f"expected a '#' block header, got {bytes(buf[:8])!r}")
        n_digits = int(chr(buf[1]))
        header = 2 + n_digits
        fill(header)
        n_bytes = int(buf[2:header].decode("ascii"))
        fill(header + n_bytes)
        if self.verbose:
            print(f"  RX  block header {bytes(buf[:header])!r}, "
                  f"{n_bytes} payload bytes", file=sys.stderr)
        return bytes(buf[header:header + n_bytes])

    def query_wavelength_log(self, scpi=True) -> list:
        """Read the internal wavelength log via :READout:DATa?, in meters.

        SCPI returns 8-byte IEEE-754 doubles in meters; Legacy returns 4-byte
        integers in units of 0.1 pm.  Both are little-endian ("Intel byte
        order", p.93).
        """
        import struct

        self.backend.reset_input()
        self.write(":READout:DATa?")
        raw = self.read_block()
        if scpi:
            n = len(raw) // 8
            return list(struct.unpack(f"<{n}d", raw[:n * 8]))
        n = len(raw) // 4
        return [v * 1e-13 for v in struct.unpack(f"<{n}i", raw[:n * 4])]

    def query_power_log(self) -> list:
        """Read the internal power log via :READout:DATa:POWer?, in dBm.

        NOTE: the manual (p.94) states this is "32 bit IEEE Standard format",
        i.e. float32.  On this unit (firmware 0042.0038.0016) that is WRONG --
        the payload is little-endian **int32 in millidBm**.  Verified against
        raw bytes: a 4.00 dBm setpoint logs as 0x00000FA7 = 4007 = 4.007 dBm.
        Decoding those bytes as float32 yields denormals that all print as
        0.000, which is the giveaway if a future firmware changes this back.
        """
        import struct

        self.backend.reset_input()
        self.write(":READout:DATa:POWer?")
        raw = self.read_block()
        n = len(raw) // 4
        return [v / 1000.0 for v in struct.unpack(f"<{n}i", raw[:n * 4])]

    # -- convenience (all read-only) -------------------------------------

    def idn(self) -> str:
        return self.query("*IDN?")

    def identify(self) -> dict:
        """Read identity and state.  Each field is independent, so a command
        the firmware rejects is recorded rather than aborting the sweep."""
        fields = [
            ("identification", "*IDN?"),
            ("firmware version", ":SYSTem:VERSion?"),
            ("product code", ":SYSTem:CODe?"),
            ("command set", ":SYSTem:COMMunicate:CODe?"),
            ("status byte", "*STB?"),
            ("wavelength", ":WAVelength?"),
            ("wavelength unit", ":WAVelength:UNIT?"),
            ("frequency", ":FREQuency?"),
            ("power setting", ":POWer:LEVel?"),
            ("power actual", ":POWer:ACTual:LEVel?"),
            ("power unit", ":POWer:UNIT?"),
            ("LD output state", ":POWer:STATe?"),
            ("shutter", ":POWer:SHUTter?"),
            ("alert", ":SYSTem:ALERt?"),
        ]
        out = {}
        for name, cmd in fields:
            try:
                out[name] = self.query(cmd)
            except Timeout as e:
                out[name] = f"<timeout: {e}>"
            except Exception as e:  # noqa: BLE001
                out[name] = f"<error: {e}>"
        return out


# ----------------------------------------------------------------- helpers


def decode_state(info: dict) -> dict:
    """Turn raw query responses into human-readable text.

    Value meanings come from the command reference: :WAVelength:UNIT 0=nm /
    1=THz (p.73), :POWer:UNIT 0=dBm / 1=mW and :POWer:SHUTter 0=open /
    1=close (p.79).  In the SCPI command set wavelength is returned in
    meters and frequency in Hz, both in exponential notation (p.73).
    """

    def num(key):
        try:
            return float(info[key])
        except (KeyError, ValueError, TypeError):
            return None

    def flag(key):
        v = info.get(key, "").strip().lstrip("+")
        return v if v in ("0", "1") else None

    out = {}
    wl_unit = flag("wavelength unit")
    pw_unit = flag("power unit")
    scpi = flag("command set") == "1"

    if scpi is not None:
        out["command set"] = "SCPI" if scpi else "Legacy"

    w = num("wavelength")
    if w is not None:
        # SCPI returns meters; Legacy returns nm directly.
        out["wavelength"] = f"{w * 1e9:.4f} nm" if scpi else f"{w:.4f} nm"

    f = num("frequency")
    if f is not None:
        out["frequency"] = f"{f / 1e12:.5f} THz" if scpi else f"{f:.5f} THz"

    unit = "dBm" if pw_unit == "0" else "mW" if pw_unit == "1" else ""
    for key in ("power setting", "power actual"):
        v = num(key)
        if v is not None:
            out[key] = f"{v:.2f} {unit}".strip()
    if num("power actual") is not None and num("power actual") <= -99:
        out["power actual"] += "  (no measurable output)"

    if wl_unit is not None:
        out["wavelength unit"] = "nm" if wl_unit == "0" else "THz"
    if pw_unit is not None:
        out["power unit"] = "dBm" if pw_unit == "0" else "mW"

    ld = flag("LD output state")
    if ld is not None:
        out["LD output state"] = "ON" if ld == "1" else "OFF"

    sh = flag("shutter")
    if sh is not None:
        out["shutter"] = "CLOSED" if sh == "1" else "OPEN"

    return out


def _attempt(backend, port, baud, timeout, verbose, mode="santec",
             host=None, tcp_port=DEFAULT_TCP_PORT):
    """Return the *IDN? reply for these settings, or None if silent/garbled."""
    try:
        with TSL775.connect(backend, port, baud, timeout, verbose, mode,
                            host, tcp_port) as dev:
            resp = dev.idn()
    except Timeout:
        return None
    # A wrong baud on an FTDI link yields framing noise, not printable ASCII.
    printable = sum(1 for c in resp if 32 <= ord(c) < 127)
    if resp and printable >= max(1, int(0.8 * len(resp))):
        return resp
    return None


# ------------------------------------------------------------- CLI commands


def cmd_devices(args):
    print("FTDI devices (D2XX):")
    try:
        devs = D2xxBackend.list_devices()
        if not devs:
            print("  none")
        for d in devs:
            dec = lambda v: v.decode(errors="replace") if isinstance(v, bytes) else v
            print(f"  [{d.get('index')}] description={dec(d.get('description'))!r} "
                  f"serial={dec(d.get('serial'))!r} type={d.get('type')}")
    except TSL775Error as e:
        print(f"  unavailable: {e}")

    print("\nEEPROM-configured chip mode:")
    try:
        be = D2xxBackend(timeout=1.0).open()
        try:
            ee = be.eeprom_mode()
        finally:
            be.close()
        if ee is None:
            print("  could not read EEPROM")
        else:
            mode = ("245 FIFO" if ee["is_fifo"] else
                    "245 FIFO CPU-target" if ee["is_fifo_target"] else
                    "fast serial" if ee["is_fast_serial"] else
                    "FT1248" if ee["is_ft1248"] else "UART")
            print(f"  word0 = 0x{ee['word0']:04x}  ->  mode: {mode}")
            print(f"  load VCP driver (IsVCP): {ee['is_vcp']}")
            if ee["is_fifo"] and not ee["is_vcp"]:
                print("  => use --backend d2xx --mode fifo (the default).")
                print("     A 'USB Serial Port (COMnn)' entry under Ports in")
                print("     Device Manager is wrong for this unit and should be")
                print("     uninstalled; only 'Santec USB TSL-775' should remain.")
    except TSL775Error as e:
        print(f"  unavailable: {e}")
    except Exception as e:  # noqa: BLE001
        print(f"  unavailable: {type(e).__name__}: {e}")

    print("\nSerial ports:")
    try:
        from serial.tools import list_ports
        ports = sorted(list_ports.comports(), key=lambda p: p.device)
        if not ports:
            print("  none")
        for p in ports:
            print(f"  {p.device:<8} {p.description or '':<32} {p.hwid or ''}")
    except ImportError:
        print("  unavailable: pyserial not installed")
    return 0


def cmd_probe(args):
    if args.backend == "lan":
        if not args.host:
            raise TSL775Error("--backend lan requires --host <ip address>")
        where = f"{args.host}:{args.tcp_port}"
    else:
        where = "FTDI/D2XX" if args.backend == "d2xx" else args.port
    fifo = (args.backend == "d2xx" and args.mode in ("santec", "fifo")) or args.backend == "lan"
    print(f"Probing TSL-775 via {args.backend} ({where})"
          f"{f' ({args.mode} init)' if args.backend == 'd2xx' else ''} ...\n")

    if fifo:
        # Baud rate has no meaning in FIFO mode; one attempt is the whole test.
        bauds = [args.baud]
    else:
        bauds = CANDIDATE_BAUDS if args.scan_baud else [args.baud]
        if args.scan_baud and args.baud in bauds:
            bauds = [args.baud] + [b for b in bauds if b != args.baud]

    # Hold ONE connection across the identity query and the state dump.
    # Measured: this unit's TCP stack resets roughly one reconnect in four,
    # while a single session handles queries indefinitely (20/20 with zero
    # failures).  Reopening between *IDN? and the state dump made `probe`
    # fail intermittently with WinError 10054.
    found_baud = idn = dev = None
    if len(bauds) == 1:
        try:
            dev = TSL775.connect(args.backend, args.port, bauds[0], args.timeout,
                                 args.verbose, args.mode, args.host, args.tcp_port)
            print("  querying *IDN? ... ", end="", flush=True)
            idn = dev.idn()
            found_baud = bauds[0]
            print(f"RESPONSE: {idn}")
        except Timeout:
            print("no response")
        except TSL775Error as e:
            print(f"no response ({e})")
    else:
        for baud in bauds:
            print(f"  {baud:>7} baud ... ", end="", flush=True)
            resp = _attempt(args.backend, args.port, baud, args.timeout,
                            args.verbose, args.mode, args.host, args.tcp_port)
            if resp:
                print(f"RESPONSE: {resp}")
                found_baud, idn = baud, resp
                break
            print("no response")

    if found_baud is None:
        print("\nThe instrument did not respond.\n")
        print("Things to check:")
        print("  * Is there a 'USB Serial Port (COMnn)' under Ports in Device")
        print("    Manager?  This unit's EEPROM sets IsVCP=0 and 245 FIFO mode,")
        print("    so that entry is the wrong (UART) driver bound to a FIFO")
        print("    device.  Uninstall it -- tick 'Delete the driver software'")
        print("    -- then replug the USB cable, cancelling any driver pop-up.")
        print("    Only 'Santec USB TSL-775' under USB controllers should remain.")
        print("    Run 'python tsl775.py devices' to check.")
        print("  * The FT232H is self-powered (it runs off the instrument's")
        print("    supply), so if it enumerates at all the instrument has power.")
        print("    Check the front panel: Other > Alerts for a system alert, and")
        print("    Other > Information to confirm the firmware is running.")
        print("  * Is the USB B cable in the rear 'USB DEVICE' port?  The")
        print("    'USB HOST' port is not used for communication (manual 7.2.1).")
        print("  * GPIB and LAN are the alternative interfaces (manual 7.1, 7.3).")
        return 1

    print(f"\n>>> TSL-775 responded via {args.backend}"
          f"{'' if fifo else f' at {found_baud} baud'}.\n")

    try:
        if dev is None:      # baud-scan path: reopen at the rate that answered
            dev = TSL775.connect(args.backend, args.port, found_baud,
                                 args.timeout, args.verbose, args.mode,
                                 args.host, args.tcp_port)
        info = dev.identify()
    finally:
        if dev is not None:
            dev.close()

    nice = decode_state(info)
    width = max(len(k) for k in info)
    raw_w = max(len(v) for v in info.values())
    print("Instrument state (read-only queries):")
    print("-" * (width + raw_w + 30))
    for k, v in info.items():
        extra = nice.get(k, "")
        print(f"  {k:<{width}}  {v:<{raw_w}}"
              + (f"   {extra}" if extra and extra != v else ""))
    print("-" * (width + raw_w + 30))

    if nice.get("LD output state") == "ON":
        print("\n  NOTE: the LD output is ON.")
    return 0


def cmd_send(args):
    with TSL775.connect(args.backend, args.port, args.baud, args.timeout,
                        args.verbose, args.mode,
                        args.host, args.tcp_port) as dev:
        for cmd in args.command:
            if cmd.rstrip().endswith("?"):
                try:
                    print(f"{cmd}  ->  {dev.query(cmd)}")
                except Timeout as e:
                    print(f"{cmd}  ->  <timeout: {e}>")
            else:
                dev.write(cmd)
                print(f"{cmd}  (sent, no response expected)")
    return 0


def cmd_repl(args):
    with TSL775.connect(args.backend, args.port, args.baud, args.timeout,
                        args.verbose, args.mode,
                        args.host, args.tcp_port) as dev:
        rate = "" if (args.backend == "d2xx" and args.mode == "fifo") else f" @ {args.baud} baud"
        print(f"TSL-775 shell on {dev.backend.describe()}{rate}.")
        print("Enter a command (queries end in '?').  'quit' or Ctrl-D exits.\n")
        while True:
            try:
                line = input("TSL-775> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if not line:
                continue
            if line.lower() in ("quit", "exit"):
                break
            try:
                if line.rstrip().endswith("?"):
                    print(dev.query(line))
                else:
                    dev.write(line)
                    print("(sent)")
            except Timeout as e:
                print(f"<timeout: {e}>")
            except Exception as e:  # noqa: BLE001
                print(f"<error: {e}>")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(
        description="Talk to a santec TSL-775 tunable laser over USB.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""examples:
  python tsl775.py devices                  list FTDI devices and COM ports
  python tsl775.py probe                    does the TSL-775 answer? (D2XX)
  python tsl775.py probe --scan-baud        ...trying every common baud rate
  python tsl775.py probe --backend vcp      ...over the COM29 virtual port
  python tsl775.py send "*IDN?" ":WAV?"     send specific commands
  python tsl775.py repl                     interactive command shell
  python tsl775.py --backend lan --host 192.168.1.50 probe    over Ethernet
""",
    )
    p.add_argument("--backend", choices=("d2xx", "vcp", "lan"), default="d2xx",
                   help="transport: d2xx (default, per manual), vcp, or lan")
    p.add_argument("--host", help="instrument IP address, for --backend lan")
    p.add_argument("--tcp-port", type=int, default=DEFAULT_TCP_PORT,
                   help=f"TCP port for --backend lan (default {DEFAULT_TCP_PORT})")
    p.add_argument("--mode", choices=("santec", "fifo", "uart"),
                   default="santec",
                   help="d2xx init sequence: santec (default, matches santec's "
                        "own Python-FTDI reference), fifo (async 245 FIFO), "
                        "or uart")
    p.add_argument("--port", default=DEFAULT_PORT,
                   help=f"serial port for the vcp backend (default {DEFAULT_PORT})")
    p.add_argument("--baud", type=int, default=DEFAULT_BAUD,
                   help=f"baud rate (default {DEFAULT_BAUD})")
    p.add_argument("--timeout", type=float, default=2.0,
                   help="read timeout in seconds (default 2.0)")
    p.add_argument("-v", "--verbose", action="store_true",
                   help="show raw bytes sent and received")

    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("devices", help="list FTDI devices and serial ports").set_defaults(func=cmd_devices)

    sp = sub.add_parser("probe", help="check whether the instrument responds, and dump its state")
    sp.add_argument("--scan-baud", action="store_true", help="try common baud rates until one answers")
    sp.set_defaults(func=cmd_probe)

    ss = sub.add_parser("send", help="send one or more commands")
    ss.add_argument("command", nargs="+", help="commands; those ending in '?' are read back")
    ss.set_defaults(func=cmd_send)

    sub.add_parser("repl", help="interactive command shell").set_defaults(func=cmd_repl)

    args = p.parse_args(argv)
    try:
        return args.func(args)
    except TSL775Error as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
