"""
Loopback tests against a real board. See docs/12-test-campaigns.md for the wiring
and the phase ordering -- run them in order, do not skip ahead.

STATUS: written from documentation, NEVER EXECUTED. Expect SCPI command
spellings to need correction on first contact. That is the point of phase H1:
these tests are as much a checklist for validating hardware.py as they are a
regression suite.

Every test here is marked `hardware` and skipped unless RP_HOST is set.
"""

import numpy as np
import pytest

from rp_lockin import (
    demodulate,
    find_trigger_edges,
    make_am_waveform,
    make_trigger_sequence,
    plan_two_tone,
    synthesise_dut_output,
)

pytestmark = pytest.mark.hardware

PLAN = plan_two_tone(difference=1e6)


# ==========================================================================
# H1 -- transport. Nothing else can be trusted until these pass.
# ==========================================================================

def test_h1_connect_and_identify(rp):
    idn = rp.idn()
    assert idn, "empty *IDN? response"
    print(f"\nboard reports: {idn}")


def test_h1_reports_expected_board(rp):
    """A 125-14 would silently give wrong sample rates everywhere. Catch it."""
    idn = rp.idn().upper()
    assert "250" in idn or "SIGNAL" in idn, (
        f"expected a SIGNALlab 250-12, got {idn!r}. If this is a 125-14, every "
        f"frequency plan in this project is wrong -- see docs/03-frequency-plan.md"
    )


def test_h1_dma_region_size(rp):
    """Report the reserved region. A 1 s sweep at decimation 2 needs 512 MB;
    the factory default is 32 MB. See docs/04-board-reference.md."""
    size = int(rp.query("ACQ:AXI:SIZE?"))
    mb = size / 1024 ** 2
    print(f"\nreserved DMA region: {mb:.0f} MB")
    if mb < 64:
        pytest.skip(f"region is only {mb:.0f} MB -- long-sweep tests will skip")


# ==========================================================================
# H2 -- transmit path. OUT1 -> IN1 coax.
# ==========================================================================

@pytest.mark.parametrize("carrier,mod", [(20e6, 5e6), (80e6, 5e6)])
def test_h2_am_spectrum_has_carrier_and_sidebands(rp, carrier, mod):
    """Confirm the generated AM waveform is structurally correct.

    The 20 MHz case is the real check: the analog path is flat there, so
    amplitudes are meaningful. At 80 MHz the round trip is attenuated twice
    (both the output and input roll off at 60 MHz), so only the RELATIVE line
    positions are trustworthy -- which is still enough to catch a wrap glitch
    or a wrong buffer length.
    """
    rp.setup_am_generator(carrier=carrier, modulation=mod, amplitude=0.5)
    rp.setup_acquisition(decimation=1)
    sig = rp.acquire(channel=1)

    spec = np.abs(np.fft.rfft(sig * np.hanning(len(sig))))
    freqs = np.fft.rfftfreq(len(sig), 1 / rp.sample_rate)
    peaks = freqs[np.argsort(spec)[-3:]] / 1e6
    for want in (carrier - mod, carrier, carrier + mod):
        assert np.min(np.abs(peaks - want / 1e6)) < 0.5, (
            f"no line near {want / 1e6:g} MHz; found {sorted(peaks)}")


def test_h2_no_wrap_glitch_spurs(rp):
    """A buffer holding a fractional number of cycles glitches at every wrap,
    producing a comb at multiples of the buffer repetition rate. That comb
    lands in the baseband and would be mistaken for DUT structure."""
    rp.setup_am_generator(carrier=80e6, modulation=5e6, amplitude=0.5)
    rp.setup_acquisition(decimation=1)
    sig = rp.acquire(channel=1)

    spec = np.abs(np.fft.rfft(sig * np.hanning(len(sig))))
    freqs = np.fft.rfftfreq(len(sig), 1 / rp.sample_rate)
    # Look well below the carrier, where only glitch products can live.
    band = (freqs > 100e3) & (freqs < 40e6)
    assert spec[band].max() < 0.02 * spec.max(), (
        "significant low-frequency content -- suspect a buffer wrap glitch")


def test_h2_both_channels_generate_simultaneously(rp):
    """The experiment needs both carriers up at once and phase-stable relative
    to each other. VERIFY: whether SOUR:TRig:INT starts channels together or
    a combined trigger is required."""
    w1, p1 = make_am_waveform(PLAN.carrier, PLAN.f1, PLAN.fs)
    w2, p2 = make_am_waveform(PLAN.carrier, PLAN.f2, PLAN.fs)
    rp.setup_am_generator(PLAN.carrier, PLAN.f1, amplitude=0.4, channel=1)
    rp.setup_am_generator(PLAN.carrier, PLAN.f2, amplitude=0.4, channel=2)
    rp.setup_acquisition(decimation=1)
    a = rp.acquire(channel=1)
    assert np.std(a) > 0.001, "channel 1 appears dead"


# ==========================================================================
# H3 -- receive path. OUT1 -> IN1, playing an emulated DUT output.
# ==========================================================================

def test_h3_recovers_known_tone_amplitude_and_phase(rp):
    """Single tone at |f2-f1| straight into the demodulator."""
    rp.setup_generator(freq=PLAN.difference, amplitude=0.4, channel=1)
    rp.setup_acquisition(decimation=2)
    sig = rp.acquire_deep(channel=1, n_samples=2_000_000, decimation=2)
    r = demodulate(sig, rp.sample_rate, PLAN.difference, bandwidth=20e3)
    assert r.R.mean() > 0, "no signal recovered"
    print(f"\nrecovered R = {r.R.mean():.4f} (drive 0.4 V), "
          f"stability {r.R.std() / r.R.mean():.2%}")


@pytest.mark.slow
def test_h3_emulated_sweep_matches_ground_truth(rp):
    """The headline loopback test: play a synthetic DUT response and check the
    recovered trace against the analytic envelope.

    Uses a short sweep so the waveform fits the arbitrary buffer path. Scaling
    to a full 1 s sweep needs Deep Memory Generation -- task H5.
    """
    duration = 0.060
    fs_gen = rp.base_rate
    samples, truth = synthesise_dut_output(
        PLAN.difference, duration, fs=fs_gen, amplitude=0.5)
    pytest.skip("requires Deep Memory Generation; see docs/12-test-campaigns.md H5")


# ==========================================================================
# H4 -- trigger digitisation. OUT2 -> IN2.
# ==========================================================================

@pytest.mark.slow
def test_h4_trigger_edges_recovered(rp):
    """Feed a known edge pattern out and confirm the intervals come back.

    The intervals carry the time-to-wavelength calibration, so an error here
    propagates into every wavelength assignment.
    """
    pytest.skip("requires Deep Memory Generation; see docs/12-test-campaigns.md H5")


# ==========================================================================
# H6 -- long capture. Needs the enlarged DMA region.
# ==========================================================================

@pytest.mark.slow
def test_h6_full_length_sweep_capture(rp):
    """1 s at decimation 2 on two channels = 477 MB. Requires the device-tree
    change in docs/04-board-reference.md."""
    size_mb = int(rp.query("ACQ:AXI:SIZE?")) / 1024 ** 2
    if size_mb < 512:
        pytest.skip(f"needs a 512 MB region, board has {size_mb:.0f} MB")

    rp.setup_acquisition(decimation=2)
    n = int(1.0 * rp.sample_rate)
    sig, trig = rp.acquire_deep_2ch(n_samples=n, decimation=2)
    assert len(sig) == n
    r = demodulate(sig, rp.sample_rate, PLAN.difference, output_rate=5000)
    assert 4800 <= len(r.t) <= 5000, f"expected ~5000 points, got {len(r.t)}"
