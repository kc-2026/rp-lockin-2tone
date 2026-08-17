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
santec      Santec TSL-770/775 transport. Written from the manuals; has
            NEVER been run against a laser.
output      Writing the deliverable: CSV trace, npz raw capture.
wavelength  Trace -> wavelength, the laser/board clock check, and the
            off-by-one-trigger guard. Offline-tested; has never seen a laser.
hardware    SCPI transport. VERIFIED against the board, Phase 1 complete
            2026-08-14. See docs/07-phase1-loopback.md.

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
from .dsp import (
    LockinResult,
    debiased_amplitude,
    demodulate,
    estimate_frequency,
    min_record_seconds,
)
from .output import write_raw_npz, write_trace_csv
from .santec import TRIGGER_OUTPUT_MODES, SantecTSL, TriggerConfig
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
    recommended_tail,
    settling_points,
)
from .wavelength import (
    AlignmentCheck,
    SweepTrace,
    TrainAnalysis,
    analyse_trigger_train,
    check_alignment,
    map_to_wavelength,
)
from .waveforms import (
    AsgTable,
    GridTwoTonePlan,
    TwoTonePlan,
    asg_grid,
    make_am_table,
    make_am_waveform,
    plan_two_tone,
    plan_two_tone_grid,
    snap_to_asg_grid,
)

__version__ = "0.1.0"

__all__ = [
    "ANALOG_BANDWIDTH",
    "ASG_BUFFER_MAX",
    "BASE_SAMPLE_RATE",
    "BOARD_RAM_MB",
    "DMA_REGION_BASE",
    "MAX_DMA_MB",
    "AlignmentCheck",
    "AsgTable",
    "CaptureOption",
    "GridTwoTonePlan",
    "LockinResult",
    "SantecTSL",
    "SweepTrace",
    "TRIGGER_OUTPUT_MODES",
    "SyntheticResponse",
    "TrainAnalysis",
    "TriggerConfig",
    "TwoTonePlan",
    "analyse_trigger_train",
    "asg_grid",
    "check_alignment",
    "debiased_amplitude",
    "demodulate",
    "describe_capture_plan",
    "estimate_frequency",
    "find_trigger_edges",
    "lorentzian",
    "make_am_table",
    "make_am_waveform",
    "make_trigger_sequence",
    "map_to_wavelength",
    "min_record_seconds",
    "plan_capture",
    "plan_two_tone",
    "plan_two_tone_grid",
    "snap_to_asg_grid",
    "recommended_preroll",
    "recommended_tail",
    "settling_points",
    "write_raw_npz",
    "write_trace_csv",
    "synthesise_dut_output",
]
