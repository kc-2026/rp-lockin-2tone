"""
SCPI transport for the Red Pitaya.

*** UNVERIFIED AGAINST HARDWARE. ***

Everything in this module was written from the Red Pitaya 2.x documentation and
has never been executed against a board. Command spellings drift between OS
releases. Methods carry VERIFY notes naming the specific commands to confirm.

This layer is deliberately separate from dsp.py so that a wrong command string
produces a connection error rather than corrupted physics. Task H1 in
docs/04-test-plan.md is to walk this file and confirm each command.
"""

from __future__ import annotations

import socket
import sys
import time

import numpy as np

from .constants import ANALOG_BANDWIDTH, BASE_SAMPLE_RATE
from .waveforms import AsgTable, make_am_table

__all__ = ["RedPitaya"]


class RedPitaya:
    """
    Minimal SCPI client for a Red Pitaya running the stock OS.

    Enable the SCPI server first: on the board's web interface, open
    "Development -> SCPI server" and press Run. Default port is 5000.

    *** Every method here is written from the Red Pitaya 2.x documentation but
    has NOT been executed against hardware. Command spellings occasionally
    change between OS releases -- if one errors, check it against
    https://redpitaya.readthedocs.io for your installed version. ***
    """

    def __init__(self, host: str, port: int = 5000, timeout: float = 15.0,
                 base_rate: float = BASE_SAMPLE_RATE):
        self.host = host
        self.port = port
        self.base_rate = base_rate
        self.decimation = 1
        self._sock = socket.create_connection((host, port), timeout=timeout)
        self._sock.settimeout(timeout)
        self._buf = b""

    # -- plumbing ----------------------------------------------------------

    def close(self) -> None:
        try:
            self._sock.close()
        except OSError:
            pass

    def __enter__(self) -> "RedPitaya":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def write(self, cmd: str) -> None:
        self._sock.sendall(cmd.encode("ascii") + b"\r\n")

    def _read_line(self) -> bytes:
        while b"\r\n" not in self._buf:
            chunk = self._sock.recv(65536)
            if not chunk:
                raise ConnectionError("SCPI connection closed by the Red Pitaya")
            self._buf += chunk
        line, self._buf = self._buf.split(b"\r\n", 1)
        return line

    def query(self, cmd: str) -> str:
        self.write(cmd)
        return self._read_line().decode("ascii").strip()

    def _read_exact(self, n: int) -> bytes:
        while len(self._buf) < n:
            chunk = self._sock.recv(max(65536, n - len(self._buf)))
            if not chunk:
                raise ConnectionError("SCPI connection closed mid-transfer")
            self._buf += chunk
        out, self._buf = self._buf[:n], self._buf[n:]
        return out

    def query_binary_int16(self, cmd: str) -> np.ndarray:
        """
        Read an IEEE 488.2 definite-length block: '#' <ndigits> <length> <data>.
        Requires ACQ:DATA:FORMAT BIN and RAW units.
        """
        self.write(cmd)
        if self._read_exact(1) != b"#":
            raise ValueError("expected a binary block header ('#') -- is FORMAT BIN set?")
        ndigits = int(self._read_exact(1))
        nbytes = int(self._read_exact(ndigits))
        raw = self._read_exact(nbytes)
        self._read_exact(2)  # trailing \r\n
        return np.frombuffer(raw, dtype=">i2").astype(np.float64)

    def wait_until(self, query: str, expected: str, timeout: float = 10.0,
                   what: str = "") -> None:
        """
        Poll `query` until it returns `expected`, or raise on timeout.

        Every poll costs a full SCPI round trip -- ~50 ms measured on OS 2.00 --
        so this runs at roughly 20 iterations per second. That is fine for
        waiting on a trigger and is why no extra sleep is needed.

        The unbounded `while self.query(...) != "TD": pass` this replaces would
        spin forever when a trigger never arrives, which is precisely H7.2's
        failure case. A socket timeout does not save you: the board keeps
        answering promptly, just with the wrong value.
        """
        deadline = time.monotonic() + timeout
        last = None
        while time.monotonic() < deadline:
            last = self.query(query)
            if last == expected:
                return
        raise TimeoutError(
            f"{what or query} did not reach {expected!r} within {timeout:g} s "
            f"(last value {last!r}). If this is a triggered acquisition, check "
            f"that the trigger source is actually firing."
        )

    # -- configuration -----------------------------------------------------

    @property
    def sample_rate(self) -> float:
        return self.base_rate / self.decimation

    def idn(self) -> str:
        return self.query("*IDN?")

    def setup_generator(self, freq: float, amplitude: float = 0.5,
                        channel: int = 1, offset: float = 0.0) -> None:
        """
        Configure an output channel as a continuous sine.

        VERIFY: SOUR<n>:FUNC / FREQ:FIX / VOLT / VOLT:OFFS / OUTPUT<n>:STATE
        """
        if freq > ANALOG_BANDWIDTH:
            print(
                f"WARNING: {freq / 1e6:.1f} MHz exceeds the 250-12 analog output "
                f"bandwidth of {ANALOG_BANDWIDTH / 1e6:.0f} MHz. The output will be "
                f"attenuated and distorted.",
                file=sys.stderr,
            )
        self.write(f"SOUR{channel}:FUNC SINE")
        self.write(f"SOUR{channel}:FREQ:FIX {freq}")
        self.write(f"SOUR{channel}:VOLT {amplitude}")
        self.write(f"SOUR{channel}:VOLT:OFFS {offset}")
        self.write(f"OUTPUT{channel}:STATE ON")
        self.write(f"SOUR{channel}:TRig:INT")

    def setup_am_generator(self, carrier: float = 80e6, modulation: float = 5e6,
                           amplitude: float = 1.0, depth: float = 1.0,
                           channel: int = 1) -> AsgTable:
        """
        Output an amplitude-modulated carrier from the arbitrary-waveform table.

        VERIFIED against OS 2.00 on 2026-08-10, after the original version was
        found not to work at all.

        The ASG always traverses a fixed 16384-entry table; SOUR:FREQ:FIX sets
        how many times per second. So the table is loaded in full and played at
        fs/16384, which steps exactly one entry per DAC clock and reproduces it
        at the full sample rate. The earlier implementation loaded 50 samples
        and played at 5 MHz on the assumption that the generator replays only
        what you write -- measured output was min -2, max +4 counts. Nothing.

        Both frequencies are snapped to the fs/16384 grid by make_am_table;
        the returned AsgTable reports what will actually be emitted, which is
        not exactly what was asked for. Check it if the exact value matters.

        The carrier is deliberately allowed above the board's 60 MHz spec --
        with downstream amplification and filtering that is a legitimate
        choice, and only the caller can judge it.
        """
        if carrier > ANALOG_BANDWIDTH:
            print(
                f"WARNING: {carrier / 1e6:.1f} MHz exceeds the 250-12 analog "
                f"output bandwidth of {ANALOG_BANDWIDTH / 1e6:.0f} MHz. The "
                f"output will be attenuated.",
                file=sys.stderr,
            )
        table = make_am_table(carrier, modulation, self.base_rate, depth)
        data = ",".join(f"{v:.6f}" for v in table.samples)
        self.write(f"SOUR{channel}:FUNC ARBITRARY")
        self.write(f"SOUR{channel}:TRAC:DATA:DATA {data}")
        # Not fs/len(table) by coincidence -- see the docstring. These are the
        # same number only because the table IS the full 16384 entries.
        self.write(f"SOUR{channel}:FREQ:FIX {table.play_freq:.4f}")
        self.write(f"SOUR{channel}:VOLT {amplitude}")
        self.write(f"OUTPUT{channel}:STATE ON")
        self.write(f"SOUR{channel}:TRig:INT")
        return table

    def setup_acquisition(self, decimation: int = 1, coupling: str = "DC",
                          gain: str = "LV") -> None:
        """
        VERIFY: ACQ:SOUR<n>:COUP is 250-12 only. ACQ:SOUR<n>:GAIN takes LV/HV,
        which on the 250-12 select the 1:1 and 1:20 attenuators.
        """
        self.write("ACQ:RST")
        self.write(f"ACQ:DEC {int(decimation)}")
        self.decimation = int(decimation)
        for ch in (1, 2):
            self.write(f"ACQ:SOUR{ch}:COUP {coupling}")
            self.write(f"ACQ:SOUR{ch}:GAIN {gain}")
        self.write("ACQ:DATA:FORMAT BIN")
        self.write("ACQ:DATA:Units RAW")

    # -- fast bulk read ----------------------------------------------------

    def fast_read(self, offset: int, n_bytes: int, port: int = 9999,
                  timeout: float = 120.0) -> np.ndarray:
        """
        Read raw samples straight from the capture buffer over a plain socket.

        Requires scripts/rp_fastread.py to be running on the board. Measured
        87 MB/s against 5.7 MB/s for the same bytes over SCPI -- a 477 MB sweep
        is 5.5 s instead of 84 s. The SCPI payload is already raw binary, so
        the difference is in the SCPI server's data path, not the encoding.

        `offset` is relative to the AXI region base (ACQ:AXI:START?), not an
        absolute physical address -- the board-side helper owns the base and
        refuses anything outside its region.

        Read only AFTER the capture has stopped. Reading while the DMA engine
        is still writing returns torn data: not dangerous, just wrong.

        Raises ConnectionError if the helper is not running, rather than
        falling back to SCPI. A silent fallback would turn "the fast path
        broke" into "everything got mysteriously slower", which is much harder
        to notice.
        """
        try:
            s = socket.create_connection((self.host, port), timeout=timeout)
        except OSError as e:
            raise ConnectionError(
                f"no fast-read helper on {self.host}:{port} ({e}). Start it "
                f"with: python3 /dev/shm/rp_fastread.py"
            ) from e
        with s:
            s.settimeout(timeout)
            s.sendall(f"GET {offset} {n_bytes}\n".encode("ascii"))
            parts, have = [], 0
            while have < n_bytes:
                chunk = s.recv(1 << 20)
                if not chunk:
                    break
                parts.append(chunk)
                have += len(chunk)
        if have != n_bytes:
            raise ConnectionError(
                f"fast read returned {have} of {n_bytes} bytes. The helper "
                f"refuses out-of-range requests -- check offset + length "
                f"against ACQ:AXI:SIZE?."
            )
        # LITTLE-endian here, BIG-endian in query_binary_int16. Not a typo and
        # not yet proven: these are different things. SCPI hands over an
        # IEEE 488.2 block in network byte order, whereas this reads the DMA
        # region as the FPGA wrote it, and the ARM is little-endian. Verify by
        # reading the same region both ways and comparing sample for sample --
        # a wrong guess here does not fail, it returns byte-swapped values that
        # still look like a plausible waveform.
        return np.frombuffer(b"".join(parts), dtype="<i2").astype(np.float64)

    def fast_read_available(self, port: int = 9999,
                            timeout: float = 3.0) -> bool:
        """Is the board-side helper running? Cheap PING, no data moved."""
        try:
            with socket.create_connection((self.host, port),
                                          timeout=timeout) as s:
                s.settimeout(timeout)
                s.sendall(b"PING\n")
                return s.recv(16).startswith(b"PONG")
        except OSError:
            return False

    # -- acquisition -------------------------------------------------------

    def acquire(self, channel: int = 1) -> np.ndarray:
        """
        One standard 16384-sample buffer. At 250 MS/s that is only 65.5 us --
        useful for alignment and quick checks, too short for a kHz-scale
        output bandwidth. Use acquire_deep for real records.
        """
        self.write("ACQ:START")
        self.write("ACQ:TRig NOW")
        self.wait_until("ACQ:TRig:STAT?", "TD", what="acquisition trigger")
        self.write("ACQ:STOP")
        return self.query_binary_int16(f"ACQ:SOUR{channel}:DATA?")

    def acquire_deep(self, channel: int = 1, n_samples: int = 1_000_000,
                     decimation: int = 1) -> np.ndarray:
        """
        Deep Memory Acquisition: stream straight into DDR3 at the full rate.

        With the default 32 MB region this reaches roughly 16 M samples, about
        67 ms of unbroken capture at 250 MS/s.

        VERIFY: the ACQ:AXI:* command set. Documented at
        redpitaya.readthedocs.io -> Remote control -> Deep Memory Mode.
        """
        return self.acquire_deep_2ch(n_samples, decimation, channels=(channel,))[0]

    def acquire_deep_2ch(self, n_samples: int = 1_000_000, decimation: int = 1,
                         channels: tuple[int, ...] = (1, 2)) -> list[np.ndarray]:
        """
        Deep capture on both channels simultaneously.

        *** NOT TRUSTWORTHY AS OF 2026-08-10. DO NOT BUILD ON THIS YET. ***

        It worked once after a reboot -- 200000 samples/channel at decimation 2,
        correct counts, IN1 at 1 MHz and IN2 at 2 MHz as driven -- and then
        began returning railed data (min -2048, max +2047) that is
        byte-identical at decimation 1 and 2. Two decimations cannot give
        identical data from a live capture. With both outputs off, ordinary
        acquire() reads a quiet 25-31 count band on the same input while this
        returns full-scale noise, so it is reading stale or uninitialised DMA
        memory rather than capturing. Suspect leftover state between calls
        rather than a wrong command spelling, since the first call worked.

        Two known defects, independent of that:

        * The ACQ:RST below wipes the coupling and gain that
          setup_acquisition() just applied. Any caller following the documented
          setup-then-acquire sequence silently loses its input configuration.
        * ACQ:AXI:DATA:Units RAW does not take effect -- ACQ:DATA:UNITS? reads
          VOLTS afterwards. The set spelling is probably unsupported and
          silently ignored.

        Also note Trig:Dly is set to the full record below, so everything lands
        after the trigger and there is NO pre-roll. H6.4 requires pre-trigger
        data so the filter is settled when the sweep starts; this needs to
        become a parameter.

        See SESSION_LOG.md 2026-08-10 for the diagnosis.
        """
        self.write("ACQ:RST")
        self.write(f"ACQ:AXI:DEC {int(decimation)}")
        self.decimation = int(decimation)

        start = int(self.query("ACQ:AXI:START?"))
        size = int(self.query("ACQ:AXI:SIZE?"))
        per_ch = size // len(channels)
        max_samples = per_ch // 2  # int16
        if n_samples > max_samples:
            print(
                f"NOTE: requested {n_samples} samples, reserved region allows "
                f"{max_samples} per channel. Truncating.",
                file=sys.stderr,
            )
            n_samples = max_samples

        for i, ch in enumerate(channels):
            self.write(f"ACQ:AXI:SOUR{ch}:Trig:Dly {n_samples}")
            self.write(f"ACQ:AXI:SOUR{ch}:SET:Buffer {start + i * per_ch},{per_ch}")
            self.write(f"ACQ:AXI:SOUR{ch}:ENable ON")

        self.write("ACQ:DATA:FORMAT BIN")
        self.write("ACQ:AXI:DATA:Units RAW")
        self.write("ACQ:START")
        self.write("ACQ:TRig NOW")
        self.wait_until("ACQ:TRig:STAT?", "TD", what="deep acquisition trigger")
        # Filling the region takes as long as the record itself, so the timeout
        # has to scale with it rather than being a fixed 10 s.
        fill_timeout = 30.0 + 4 * n_samples * decimation / self.base_rate
        self.wait_until(f"ACQ:AXI:SOUR{channels[0]}:TRIG:FILL?", "1",
                        timeout=fill_timeout, what="deep memory fill")
        self.write("ACQ:STOP")

        out = []
        for ch in channels:
            pos = int(self.query(f"ACQ:AXI:SOUR{ch}:Trig:Pos?"))
            out.append(
                self.query_binary_int16(
                    f"ACQ:AXI:SOUR{ch}:DATA:Start:N? {pos},{n_samples}"
                )
            )
        for ch in channels:
            self.write(f"ACQ:AXI:SOUR{ch}:ENable OFF")
        return out


# ----------------------------------------------------------------------------
# Self-test -- validates the DSP core without any hardware
# ----------------------------------------------------------------------------
