"""
Offline tests for the fast bulk read path (`RedPitaya.fast_read`).

There were none before 2026-08-25, which mattered because this is the one
transport carrying the actual measurement: every sample of every sweep arrives
through it. The two failure modes it has to get right are both silent ones --
a short read that looks like a full one, and a byte order that turns a real
waveform into a different plausible waveform -- so both are pinned here.

A real loopback socket is used rather than a fake, because the change these
tests were written alongside replaced `recv` + join with `recv_into` over a
preallocated buffer. A fake socket would have exercised the mock, not the
buffer arithmetic, and the buffer arithmetic is the part that can go wrong.
"""

import socket
import threading

import numpy as np
import pytest

from rp_lockin.hardware import RedPitaya


class FakeScpi:
    """Stands in for the SCPI connection so RedPitaya() can be constructed."""

    def __init__(self):
        self.sent: list[str] = []

    def sendall(self, data: bytes) -> None:
        self.sent.append(data.decode("ascii").strip())

    def settimeout(self, _t) -> None:
        pass

    def close(self) -> None:
        pass


class FastReadServer:
    """The board helper's wire protocol, in process.

    Speaks enough of scripts/rp_fastread.py to exercise the client: GET returns
    the requested slice of `payload`, PING answers PONG, and `truncate_to`
    makes it under-deliver the way an out-of-range refusal does.
    """

    def __init__(self, payload: bytes, truncate_to: int | None = None):
        self.payload = payload
        self.truncate_to = truncate_to
        self.srv = socket.socket()
        self.srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.srv.bind(("127.0.0.1", 0))
        self.srv.listen(4)
        self.port = self.srv.getsockname()[1]
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _serve(self):
        while True:
            try:
                conn, _ = self.srv.accept()
            except OSError:
                return
            with conn:
                req = b""
                while not req.endswith(b"\n") and len(req) < 128:
                    got = conn.recv(128)
                    if not got:
                        break
                    req += got
                parts = req.decode("ascii", "replace").strip().split()
                if not parts:
                    continue
                if parts[0] == "PING":
                    conn.sendall(b"PONG\n")
                elif parts[0] == "GET" and len(parts) == 3:
                    off, length = int(parts[1]), int(parts[2])
                    body = self.payload[off:off + length]
                    if self.truncate_to is not None:
                        body = body[:self.truncate_to]
                    # Deliberately dribbled out in small pieces: the client must
                    # loop until it has everything, not assume one recv is one
                    # reply. TCP is free to split a 62 MB send anywhere.
                    for i in range(0, len(body), 1024):
                        conn.sendall(body[i:i + 1024])

    def close(self):
        self.srv.close()


@pytest.fixture
def rp(monkeypatch):
    """A RedPitaya whose SCPI link is fake but whose sockets are real.

    Only the SCPI port is intercepted; anything else -- notably the fast-read
    port -- gets a genuine connection, which is the whole point.
    """
    real_create = socket.create_connection

    def create(address, *a, **k):
        host, port = address
        if port == 5000:
            return FakeScpi()
        return real_create(address, *a, **k)

    monkeypatch.setattr(socket, "create_connection", create)
    return RedPitaya("127.0.0.1")


def _payload(n_samples: int, seed: int = 0) -> tuple[bytes, np.ndarray]:
    rng = np.random.default_rng(seed)
    vals = rng.integers(-30000, 30000, n_samples, dtype=np.int16)
    return vals.tobytes(), vals


def test_fast_read_returns_every_sample(rp):
    raw, vals = _payload(200_000)
    srv = FastReadServer(raw)
    try:
        got = rp.fast_read(0, len(raw), port=srv.port)
    finally:
        srv.close()
    assert got.shape == vals.shape
    np.testing.assert_array_equal(got, vals.astype(np.float64))


def test_fast_read_is_little_endian(rp):
    """A byte swap does not fail -- it returns a different plausible waveform.

    Verified against the board on 2026-08-12 by comparing sigma on a quiet
    channel; this pins the same convention offline so a refactor cannot quietly
    flip it. 0x0102 little-endian is 513; big-endian it is 258.
    """
    srv = FastReadServer(bytes([0x01, 0x02]))
    try:
        got = rp.fast_read(0, 2, port=srv.port)
    finally:
        srv.close()
    assert got[0] == 513.0


def test_fast_read_offset_is_honoured(rp):
    raw, vals = _payload(50_000, seed=3)
    srv = FastReadServer(raw)
    try:
        got = rp.fast_read(1000, 2000, port=srv.port)
    finally:
        srv.close()
    np.testing.assert_array_equal(got, vals[500:1500].astype(np.float64))


def test_a_short_reply_raises_rather_than_truncating(rp):
    """The helper answers an out-of-range GET with zero bytes and closes.

    Returning the short array would be the project's classic failure: a record
    that is quietly missing its tail, demodulating without complaint into a
    trace that merely ends early.
    """
    raw, _ = _payload(10_000)
    srv = FastReadServer(raw, truncate_to=4096)
    try:
        with pytest.raises(ConnectionError, match="of .* bytes"):
            rp.fast_read(0, len(raw), port=srv.port)
    finally:
        srv.close()


def test_missing_helper_raises_instead_of_falling_back(rp):
    """No silent fallback to SCPI: 'the fast path broke' must not present as
    'everything got mysteriously slower'."""
    free = socket.socket()
    free.bind(("127.0.0.1", 0))
    port = free.getsockname()[1]
    free.close()
    with pytest.raises(ConnectionError, match="no fast-read helper"):
        rp.fast_read(0, 1024, port=port)
