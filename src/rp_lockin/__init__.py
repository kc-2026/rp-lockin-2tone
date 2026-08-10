"""
rp_lockin -- two-tone lock-in detection on a Red Pitaya SIGNALlab 250-12.

Measures a DUT's intermodulation response: two 80 MHz carriers amplitude
modulated at f1 and f2 drive the device, which mixes them, and the response
appears at |f2 - f1|. That difference frequency is demodulated in software and
delivered as a time-series trace across a laser wavelength sweep.

Module map
----------
constants   Board limits and design constants.
dsp         Demodulation. Pure numpy/scipy, fully tested offline. TRUSTED.
waveforms   Drive waveform construction and the two-tone frequency planner.
planning    Capture sizing: memory budget, decimation, aliasing.
emulator    Synthetic DUT output for loopback testing.
hardware    SCPI transport. NOT VERIFIED AGAINST HARDWARE -- see the module
            docstring and docs/04-test-plan.md task H1.

Start here
----------
    from rp_lockin import plan_two_tone, describe_capture_plan
    print(plan_two_tone(difference=1e6).describe())
    print(describe_capture_plan(1.0, 1e6))
"""

from .constants import (
    ANALOG_BANDWIDTH,
    ASG_BUFFER_MAX,
    BASE_SAMPLE_RATE,
    BOARD_RAM_MB,
    DMA_REGION_BASE,
    MAX_DMA_MB,
)
from .dsp import LockinResult, demodulate, estimate_frequency, min_record_seconds
from .emulator import (
    SyntheticResponse,
    find_trigger_edges,
    lorentzian,
    make_trigger_sequence,
    synthesise_dut_output,
)
from .planning import (
    CaptureOption,
    describe_capture_plan,
    plan_capture,
    recommended_preroll,
    settling_points,
)
from .waveforms import TwoTonePlan, make_am_waveform, plan_two_tone

__version__ = "0.1.0"

__all__ = [
    "ANALOG_BANDWIDTH",
    "ASG_BUFFER_MAX",
    "BASE_SAMPLE_RATE",
    "BOARD_RAM_MB",
    "DMA_REGION_BASE",
    "MAX_DMA_MB",
    "CaptureOption",
    "LockinResult",
    "SyntheticResponse",
    "TwoTonePlan",
    "demodulate",
    "describe_capture_plan",
    "estimate_frequency",
    "find_trigger_edges",
    "lorentzian",
    "make_am_waveform",
    "make_trigger_sequence",
    "min_record_seconds",
    "plan_capture",
    "plan_two_tone",
    "recommended_preroll",
    "settling_points",
    "synthesise_dut_output",
]
