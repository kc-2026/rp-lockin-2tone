"""
SCPI transport for the Red Pitaya.

*** VERIFIED AGAINST HARDWARE. Phase 1 complete, 2026-08-14. ***

Every method here has been executed against a SIGNALlab 250-12 running OS 2.00
build 37. See docs/07-phase1-loopback.md (task H1) and docs/05-results.md.

Two exceptions, both documented at their definitions:
  - acquire_deep_2ch: the SCPI read returns garbage. Superseded by
    acquire_deep_fast. Kept for reference; do not build on it.
  - setup_am_generator: rewritten, not merely corrected -- the original modelled
    a generator this board is not.

The trap worth knowing before editing anything here: **a misspelled setting
command returns zero bytes, exactly like a correct one.** Verify by setting and
reading back, never by absence of an error.

This layer is deliberately separate from dsp.py so that a wrong command string
produces a connection error rather than corrupted physics. Keep it that way.
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

    *** Every method here has been executed against a real board on OS 2.00
    (Phase 1, complete 2026-08-14). Command spellings do change between OS
    releases, so if one errors on a different image, check it against
    https://redpitaya.readthedocs.io for that version -- and remember that a
    misspelled SETTING command will not error at all, it will simply do
    nothing. ***
    """

    def __init__(self, host: str, port: int = 5000, timeout: float = 15.0,
                 base_rate: float = BASE_SAMPLE_RATE):
        self.host = host
        self.port = port
        self.base_rate = base_rate
        self.decimation = 1
        # What ACQ:RST leaves behind, so the deep-capture paths restore a known
        # state even if setup_acquisition was never called. PER CHANNEL, because
        # the real experiment needs them to differ: the photodetector wants LV
        # on IN1 for sensitivity while the laser's 3.3 V trigger needs HV on
        # IN2. A single pair of values quietly forced both the same, which made
        # P2 impossible to run as specified. Fixed 2026-08-25.
        self.front_end = {1: {"coupling": "DC", "gain": "LV"},
                          2: {"coupling": "DC", "gain": "LV"}}
        self._sock = socket.create_connection((host, port), timeout=timeout)
        self._sock.settimeout(timeout)
        self._buf = b""

    # -- plumbing ----------------------------------------------------------

    def close(self, disable_outputs: bool = True) -> None:
        """
        Disconnect, switching both outputs off on the way out.

        H7.4 caught this: before 2026-08-14, close() only shut the socket, so an
        unhandled exception anywhere in a measurement script left the generator
        driving indefinitely with nobody watching. `tests/hardware/conftest.py`
        disarms outputs for the test suite, which masked the gap -- every ad-hoc
        script had it.

        The disarm is best-effort and never raises. It runs on the way out of a
        failure most of the time, and the useful exception is the original one,
        not whatever a doomed write hits afterwards. A wedged or already-closed
        socket therefore just skips it.

        `disable_outputs=False` opts out, for the rare case of deliberately
        leaving a signal running across a disconnect. Nothing in this project
        does that, and the loopback safety rule in CLAUDE.md is that outputs are
        never left enabled -- so if you reach for it, say why in the log.
        """
        if disable_outputs:
            for ch in (1, 2):
                try:
                    self.write(f"OUTPUT{ch}:STATE OFF")
                except OSError:
                    pass
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

        VERIFIED against OS 2.00 on 2026-08-12, after the original version was
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
        VERIFIED on OS 2.00. ACQ:SOUR<n>:COUP is 250-12 only. ACQ:SOUR<n>:GAIN
        takes LV/HV, selecting the 1:1 and 1:20 attenuators.

        Both are **per channel**, which matters for the real experiment: the
        photodetector wants LV on IN1 for sensitivity, while the laser's 3.3 V
        trigger needs HV on IN2. This sets both channels the same; use the raw
        commands if they need to differ.

        The choice is REMEMBERED, and `acquire_deep_fast` re-applies it after its
        `ACQ:RST`. Without that an AC-coupled deep capture is impossible, because
        `ACQ:RST` silently reverts coupling to DC -- and the capture succeeds and
        looks entirely normal, just DC coupled.
        """
        if coupling not in ("AC", "DC"):
            raise ValueError(f"coupling must be AC or DC, got {coupling!r}")
        if gain not in ("LV", "HV"):
            raise ValueError(f"gain must be LV or HV, got {gain!r}")
        self.write("ACQ:RST")
        self.write(f"ACQ:DEC {int(decimation)}")
        self.decimation = int(decimation)
        # Sets BOTH channels, which is what this call has always meant. Use
        # setup_channel() afterwards where they must differ -- and note the
        # order matters, since this overwrites both.
        for ch in (1, 2):
            self.front_end[ch] = {"coupling": coupling, "gain": gain}
            self.write(f"ACQ:SOUR{ch}:COUP {coupling}")
            self.write(f"ACQ:SOUR{ch}:GAIN {gain}")
        self.write("ACQ:DATA:FORMAT BIN")
        self.write("ACQ:DATA:Units RAW")

    def _reapply_front_end(self) -> None:
        """Restore coupling and gain after an ACQ:RST has wiped them.

        Per channel. Forcing both to one setting is not a simplification here:
        IN1 and IN2 genuinely differ in the real experiment, and an IN2 quietly
        put back to LV clips a 3.3 V trigger into a flat line -- which reads as
        "the laser is not triggering" rather than as a range error.
        """
        for ch in (1, 2):
            fe = self.front_end[ch]
            self.write(f"ACQ:SOUR{ch}:COUP {fe['coupling']}")
            self.write(f"ACQ:SOUR{ch}:GAIN {fe['gain']}")

    @property
    def coupling(self) -> str:
        """Channel 1's coupling. Kept so older callers still read something
        meaningful; use `front_end` when the two channels differ."""
        return self.front_end[1]["coupling"]

    @property
    def gain(self) -> str:
        """Channel 1's gain. See `coupling`."""
        return self.front_end[1]["gain"]

    def setup_channel(self, channel: int, coupling: str | None = None,
                      gain: str | None = None) -> None:
        """Set ONE channel's coupling and/or gain, and remember it.

        This is what the real experiment needs and what `setup_acquisition`
        cannot express: IN1 on LV for the detector, IN2 on HV for the laser's
        3.3 V trigger. The setting is remembered so the deep-capture paths put
        it back after their ACQ:RST.
        """
        if channel not in (1, 2):
            raise ValueError(f"channel must be 1 or 2, got {channel}")
        if coupling is not None:
            if coupling not in ("AC", "DC"):
                raise ValueError(f"coupling must be AC or DC, got {coupling!r}")
            self.front_end[channel]["coupling"] = coupling
            self.write(f"ACQ:SOUR{channel}:COUP {coupling}")
        if gain is not None:
            if gain not in ("LV", "HV"):
                raise ValueError(f"gain must be LV or HV, got {gain!r}")
            self.front_end[channel]["gain"] = gain
            self.write(f"ACQ:SOUR{channel}:GAIN {gain}")

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
        buf = bytearray(n_bytes)
        with s:
            s.settimeout(timeout)
            # Bulk receiver: the request is one line and the reply is tens
            # of megabytes, so there is no ping-pong for Nagle to help
            # with. Off on both ends or it is off on neither.
            s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            s.sendall(f"GET {offset} {n_bytes}\n".encode("ascii"))
            # recv_into a preallocated buffer rather than accumulating a
            # list and joining it. The join held the whole reply TWICE at
            # its peak -- 62 MB of fragments plus the 62 MB result -- on
            # top of the float64 array below. Same bytes, one copy fewer.
            view = memoryview(buf)
            have = 0
            while have < n_bytes:
                got = s.recv_into(view[have:], n_bytes - have)
                if not got:
                    break
                have += got
        if have != n_bytes:
            raise ConnectionError(
                f"fast read returned {have} of {n_bytes} bytes. The helper "
                f"refuses out-of-range requests -- check offset + length "
                f"against ACQ:AXI:SIZE?."
            )
        # LITTLE-endian here, BIG-endian in query_binary_int16. Not a typo:
        # these are different things. SCPI hands over an IEEE 488.2 block in
        # network byte order, whereas this reads the DMA region as the FPGA
        # wrote it, and the ARM is little-endian.
        #
        # VERIFIED 2026-08-12. A wrong guess here does not fail -- it returns
        # byte-swapped values that still look like a plausible waveform -- so
        # the check was made against a QUIET input rather than a waveform:
        # this path's raw sigma was 0.6797 counts against 0.6781 from
        # acquire() on the same silent channel, a ratio of 1.002, where a byte
        # swap would be off by ~100x. Re-check it the same way if this changes;
        # a byte-swapped noise record still looks exactly like noise.
        # astype(float64) quadruples this: 31 M samples is 62 MB of int16
        # becoming 250 MB of float64, with both live at once. It stays
        # float64 because the DSP chain expects it, but if a record ever
        # gets much bigger this conversion is the thing to attack next,
        # not the transfer.
        return np.frombuffer(buf, dtype="<i2").astype(np.float64)

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

    def _fast_read_wrapped(self, region_start: int, region_samples: int,
                           first_sample: int, n_samples: int,
                           port: int) -> np.ndarray:
        """Read n_samples from a ring, starting at first_sample, handling wrap.

        Offsets are in SAMPLES within one channel's sub-region; the byte
        arithmetic is done here so callers cannot get the factor of two wrong.
        """
        first_sample %= region_samples
        end = first_sample + n_samples
        if end <= region_samples:
            return self.fast_read((region_start + first_sample) * 2,
                                  n_samples * 2, port=port)
        head = region_samples - first_sample
        return np.concatenate([
            self.fast_read((region_start + first_sample) * 2, head * 2,
                           port=port),
            self.fast_read(region_start * 2, (n_samples - head) * 2,
                           port=port),
        ])

    def acquire_deep_fast(self, n_samples: int = 1_000_000,
                          decimation: int = 1,
                          channels: tuple[int, ...] = (1, 2),
                          port: int = 9999,
                          trigger: str = "NOW",
                          trigger_level: float = 0.1,
                          preroll_samples: int = 0,
                          trigger_timeout: float = 30.0) -> list[np.ndarray]:
        """
        Deep capture, read back over the fast path. USE THIS, not
        acquire_deep_2ch.

        Verified 2026-08-12: driving 1 MHz then 2 MHz and capturing each gave
        1.0000 and 2.0000 MHz back, amplitude 361 counts against 362 measured
        independently, rms exactly amplitude/sqrt(2). Each capture tracks its
        own drive, so this is live data rather than leftovers.

        That result also settled what was wrong with acquire_deep_2ch: the DMA
        capture itself was always fine, and the SCPI read of the AXI region is
        what returns garbage. Same trigger and arming sequence here, different
        read.

        Requires scripts/rp_fastread.py running on the board.

        TRIG:DLY IS A POST-TRIGGER SAMPLE COUNT, not a delay before starting.
        It has to cover everything you intend to read after the trigger, or the
        tail of the record is whatever occupied the region beforehand -- which
        looks like a partly corrupted capture rather than an error.

        `trigger` is any ACQ:TRig source: NOW, CH1_PE, CH2_PE, EXT_PE and so
        on. `preroll_samples` asks for that many samples BEFORE the trigger,
        which is what H6.4 needs so the demodulator's filter is already settled
        when the sweep begins. Pre-roll requires a real trigger source; with
        NOW there is nothing to be early relative to.

        On ACQ:AXI:SOUR<n>:Trig:Pos?, which an earlier revision of this
        docstring declared broken: **it works.** It returns 0x7F800000 when no
        trigger has occurred, and every reading that led to the "broken"
        conclusion was taken idle or after ACQ:TRig NOW. After a genuine
        triggered capture it returns the trigger's sample index. Validated by
        reading from a known distance before it: across four captures with
        different positions, the rising edge appeared at exactly the expected
        offset every time.

        It sits a fixed **1.14 samples (9.1 ns) after** the actual threshold
        crossing, reproducible to 0.00 samples. Not corrected for here, because
        the offset depends on trigger level and edge slew and so belongs to the
        signal rather than to this transport. Subtract it if the absolute
        instant matters.
        """
        if preroll_samples and trigger.upper() == "NOW":
            raise ValueError(
                "pre-roll needs a real trigger source (e.g. CH2_PE); with "
                "ACQ:TRig NOW the capture starts immediately and there is "
                "nothing to be early relative to."
            )
        if preroll_samples >= n_samples:
            raise ValueError(
                f"preroll_samples={preroll_samples} must be less than "
                f"n_samples={n_samples}"
            )
        if not self.fast_read_available(port=port):
            raise ConnectionError(
                f"fast-read helper not running on {self.host}:{port}. Start it "
                f"with: python3 /dev/shm/rp_fastread.py"
            )

        self.write("ACQ:RST")
        # ACQ:RST reverts coupling to DC and gain to LV. Put back whatever
        # setup_acquisition asked for, or an AC-coupled or HV capture silently
        # comes back DC/LV -- succeeding, and looking completely normal.
        self._reapply_front_end()
        self.write(f"ACQ:AXI:DEC {int(decimation)}")
        self.decimation = int(decimation)

        start = int(self.query("ACQ:AXI:START?"))
        size = int(self.query("ACQ:AXI:SIZE?"))
        per_ch = size // len(channels)
        max_samples = per_ch // 2
        if n_samples > max_samples:
            print(
                f"NOTE: requested {n_samples} samples, reserved region allows "
                f"{max_samples} per channel. Truncating.",
                file=sys.stderr,
            )
            n_samples = max_samples

        post = n_samples - preroll_samples
        self.write(f"ACQ:TRig:LEV {trigger_level}")
        for i, ch in enumerate(channels):
            self.write(f"ACQ:AXI:SOUR{ch}:Trig:Dly {post}")
            self.write(f"ACQ:AXI:SOUR{ch}:SET:Buffer {start + i * per_ch},{per_ch}")
            self.write(f"ACQ:AXI:SOUR{ch}:ENable ON")

        # The cleanup below covers EVERYTHING from here on, not just the read.
        # It used to start at the read, which left the DMA running and the
        # channels enabled whenever the trigger never arrived -- H7.2's exact
        # path. A board left armed that way stops answering SCPI queries
        # altogether: the connection still accepts, so it presents as a dead
        # cable or a hung PC rather than as a capture that was never disarmed,
        # and recovering needs the SCPI server restarted by hand.
        per_ch_samples = per_ch // 2
        out = []
        try:
            self.write("ACQ:START")
            if preroll_samples:
                # THE RING MUST ALREADY HOLD THAT MUCH HISTORY before the
                # trigger is allowed to fire. The DMA only starts writing at
                # ACQ:START, so a trigger arriving immediately leaves nothing
                # behind it and the "pre-roll" is memory that was never written
                # this capture -- it reads back as near-silence, which looks
                # like a dead input rather than a sequencing error. Measured
                # that way once; hence the wait.
                time.sleep(1.5 * preroll_samples * decimation / self.base_rate)
            self.write(f"ACQ:TRig {trigger}")
            self.wait_until("ACQ:TRig:STAT?", "TD", timeout=trigger_timeout,
                            what=f"deep acquisition trigger ({trigger})")
            fill_timeout = 30.0 + 4 * n_samples * decimation / self.base_rate
            self.wait_until(f"ACQ:AXI:SOUR{channels[0]}:TRIG:FILL?", "1",
                            timeout=fill_timeout, what="deep memory fill")
            self.write("ACQ:STOP")

            for i, ch in enumerate(channels):
                if trigger.upper() != "NOW":
                    # Reference to the trigger whenever there IS one, not only
                    # when pre-roll is asked for. Reading from offset 0 after a
                    # real trigger returns data from an arbitrary point in the
                    # ring -- it looks plausible, and silently misplaces every
                    # event in the record. Trig:Pos is only meaningful once a
                    # trigger has actually fired.
                    pos = int(self.query(f"ACQ:AXI:SOUR{ch}:Trig:Pos?"))
                    first = pos - preroll_samples
                else:
                    # ACQ:TRig NOW starts the capture at the region base.
                    first = 0
                out.append(self._fast_read_wrapped(
                    (i * per_ch) // 2, per_ch_samples, first, n_samples, port))
        finally:
            # Best-effort, and deliberately swallowing errors: this runs while
            # an exception is already propagating, and the useful one is the
            # original failure, not whatever the disarm hits on the way out.
            for cmd in ["ACQ:STOP"] + [f"ACQ:AXI:SOUR{ch}:ENable OFF"
                                       for ch in channels]:
                try:
                    self.write(cmd)
                except OSError:
                    pass
        return out

    def acquire_deep_2ch(self, n_samples: int = 1_000_000, decimation: int = 1,
                         channels: tuple[int, ...] = (1, 2)) -> list[np.ndarray]:
        """
        Deep capture on both channels, read back over SCPI.

        *** THE SCPI READ IS BROKEN. Use acquire_deep_fast() instead. ***

        The arming and triggering below are correct -- acquire_deep_fast()
        performs the identical sequence and returns good data. What fails is
        the SCPI read of the AXI region at the end of this method. Reading the
        same physical bytes directly gave a clean sine at the commanded
        frequency while this returned structureless values, so the fault is in
        the SCPI read path, not in the capture.

        Kept for reference and in case the SCPI read is ever fixed or needed
        on a board without the helper. Do not build on it.

        Symptoms, for whoever revisits it: it worked once after a reboot, then
        returned railed data (min -2048, max +2047) byte-identical at
        decimation 1 and 2 -- which a live capture cannot produce. With both
        outputs off, ordinary acquire() read a quiet 25-31 count band on the
        same input while this returned full-scale noise.

        Two further defects, independent of the read:

        * The ACQ:RST below wipes the coupling and gain that
          setup_acquisition() just applied. Any caller following the documented
          setup-then-acquire sequence silently loses its input configuration.
        * ACQ:AXI:DATA:Units RAW does not take effect -- ACQ:DATA:UNITS? reads
          VOLTS afterwards. The set spelling is probably unsupported and
          silently ignored.

        Also note Trig:Dly is set to the full record below, so everything lands
        after the trigger and there is NO pre-roll. H6.4 requires pre-trigger
        data so the filter is settled when the sweep starts; this needs to
        become a parameter in acquire_deep_fast() too.

        See SESSION_LOG.md 2026-08-12 for the diagnosis.
        """
        self.write("ACQ:RST")
        # ACQ:RST reverts coupling to DC and gain to LV. Put back whatever
        # setup_acquisition asked for, or an AC-coupled or HV capture silently
        # comes back DC/LV -- succeeding, and looking completely normal.
        self._reapply_front_end()
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
