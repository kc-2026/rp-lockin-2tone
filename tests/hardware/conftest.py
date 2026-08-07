"""
Fixtures for tests that need a real Red Pitaya.

These are skipped unless RP_HOST is set, so the offline suite stays runnable
anywhere:

    export RP_HOST=192.168.1.100
    pytest tests/hardware -m hardware

Before running any of this, read docs/04-test-plan.md. In particular: the
loopback wiring must be in place, and the DUT must NOT be connected. Several
tests drive outputs at full scale.
"""

import os

import pytest

RP_HOST = os.environ.get("RP_HOST")
RP_PORT = int(os.environ.get("RP_PORT", "5000"))

requires_hardware = pytest.mark.skipif(
    not RP_HOST, reason="set RP_HOST to run hardware tests"
)


@pytest.fixture(scope="session")
def rp():
    """A connected board. Session-scoped: reconnecting per test is slow and the
    SCPI server does not always like rapid reconnects."""
    if not RP_HOST:
        pytest.skip("set RP_HOST to run hardware tests")
    from rp_lockin.hardware import RedPitaya

    board = RedPitaya(RP_HOST, RP_PORT)
    yield board
    # Always leave the outputs off. An agent crashing mid-test must not leave
    # the board driving.
    try:
        for ch in (1, 2):
            board.write(f"OUTPUT{ch}:STATE OFF")
    finally:
        board.close()


@pytest.fixture(autouse=True)
def outputs_off_after_each(rp):
    """Belt and braces: outputs off between tests regardless of outcome."""
    yield
    for ch in (1, 2):
        try:
            rp.write(f"OUTPUT{ch}:STATE OFF")
        except OSError:
            pass
