"""
rp_lockin -- two-tone lock-in detection on a Red Pitaya SIGNALlab 250-12.

Measures a DUT's intermodulation response. Two AOMs gate light at f1 and f2 by
amplitude modulating the 80 MHz acoustic drive they require -- the DUT sees only
the gated light, never the 80 MHz itself. The DUT mixes the two, and the response
appears at |f2 - f1|. That difference frequency is demodulated in software and
delivered as a trace against laser wavelength.

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
pipeline    THE DELIVERABLE PATH: one captured sweep in, amplitude against
            wavelength out. Joins demodulate, the trigger edges, the laser log
            and the mapping. Checked against the emulator's known truth.
hardware    SCPI transport. VERIFIED against the board, Phase 1 complete
            2026-08-14. See docs/12-test-campaigns.md.

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
    make_trigger_pulses,
    make_trigger_sequence,
    synthesise_dut_output,
)
from .pipeline import (SweepReduction, SweepSeries, measure_sweep,
                       reduce_sweep, write_series)
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
    logged_point_times,
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
    "SweepReduction",
    "SweepSeries",
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
    "logged_point_times",
    "make_trigger_pulses",
    "map_to_wavelength",
    "measure_sweep",
    "min_record_seconds",
    "plan_capture",
    "plan_two_tone",
    "plan_two_tone_grid",
    "snap_to_asg_grid",
    "reduce_sweep",
    "recommended_preroll",
    "recommended_tail",
    "settling_points",
    "write_raw_npz",
    "write_series",
    "write_trace_csv",
    "synthesise_dut_output",
]
