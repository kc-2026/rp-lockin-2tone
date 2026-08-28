"""Board constants and design limits for the SIGNALlab 250-12."""

# Base ADC/DAC rate. A STEMlab 125-14 would be 125e6.
BASE_SAMPLE_RATE = 250e6

# Analog front-end bandwidth, both input and output (Hz). The board's own
# rolloff. Usefully, this doubles as a free anti-alias filter: decimating by 2
# puts Nyquist at 62.5 MHz, above this, so there is nothing left to fold.
ANALOG_BANDWIDTH = 60e6

# Intermediate anti-alias filter stages need deep rejection -- anything that
# folds into the output band is unrecoverable.
STOPBAND_DB = 90.0

# The final bandwidth-setting stage does not: aliasing and the 2*f_ref product
# are already gone by then. Settling time scales as
# (stopband_dB - 7.95) / transition_width, so relaxing 90 -> 60 dB cuts dead
# time at the start of the record by ~40% for free.
FINAL_STOPBAND_DB = 60.0

# Streaming block size in input samples. Bounds peak memory so a 1 s record at
# 125 MS/s processes in a few hundred MB rather than several GB.
CHUNK_SAMPLES = 1 << 22

# Physical RAM: 1 GB. The device tree reports base 0x0, size 0x40000000.
#
# Linux does NOT see all of it. The kernel command line carries mem=512M, so
# the OS is confined to 0x00000000-0x1FFFFFFF and reports ~460 MB. That is
# deliberate Red Pitaya configuration, not a fault: it leaves the upper half
# permanently outside Linux's control for DMA capture buffers.
#
# Do not read free memory as installed memory. /proc/iomem and MemTotal both
# show the capped view and will tell you this is a 512 MB board.
BOARD_RAM_MB = 1024

# Start of the upper half -- the region Linux cannot see. Base the DMA buffer
# here, not in Linux's half, so a large reservation costs the OS nothing.
DMA_REGION_BASE = 0x20000000

# What is ACTUALLY reserved on the bench board, and therefore what any
# recommendation has to fit. The 2026-08-12 device-tree work left a 128 MiB
# region at 0x1000000; H6.2 filled 125.2 MB of it, 97.8% full, and every
# capture from H6.2 onwards ran that way.
#
# Not to be confused with MAX_DMA_MB below. Enlarging the region to 512 MB to
# buy decimation 2 was CONSIDERED AND REJECTED (docs/04-hardware-reference.md):
# the objection that motivated it -- needing to recover trigger intervals
# exactly -- vanished when the wavelength axis moved to the laser's own log.
# Do not start the move. `describe_capture_plan` used to recommend it by
# default, which is how that stale advice survived; it now plans inside this.
DMA_REGION_MB = 128

# Largest DMA region it is safe to reserve IF the move were ever made: the
# whole upper half. Bounded by
# where Linux ends, not by the OS's needs, precisely because reserving from up
# here takes nothing away from it. A 1 s two-channel sweep at decimation 2
# needs 477 MB and fits with ~35 MB spare.
#
# Confirm with ACQ:AXI:SIZE? after any device-tree change -- asking for more
# than exists does not fail loudly.
MAX_DMA_MB = 512

# Arbitrary-waveform buffer depth of the stock generator.
ASG_BUFFER_MAX = 16384

# ---- ADC scaling -----------------------------------------------------------
#
# acquire(), acquire_deep() and acquire_deep_fast() all return RAW ADC COUNTS,
# not volts. Nothing in the capture path scales them, deliberately: hardware.py
# stays clear of the maths. Anything comparing a capture against a physical
# specification has to convert, and forgetting to is not obvious -- a trigger
# reported as "302 V" was the P2 failure on 2026-08-28.
#
# Counts per volt on the LV (+/-1 V) range. A commanded 0.5 V returned 902.8
# counts, implying 1816.9 counts/V, which matches the 1817.7 inherited from an
# unrelated measurement to 0.04%.
#
# CAVEAT -- this is Q23, and it is still open. Loopback measures DAC x cable x
# ADC as ONE number and cannot say where the 0.882 factor lives. If it sits in
# the DAC, this figure is ~12.7% low for a signal driven straight into the
# input, which is exactly what the real experiment does. Good enough for "is
# this the right order of magnitude and the right input range?" -- which is all
# P2 asks. NOT a calibrated absolute until an external source settles Q23.
ADC_COUNTS_PER_V_LV = 1817.7

# The HV range is +/-20 V, so the same full scale covers 20x the voltage.
ADC_COUNTS_PER_V_HV = ADC_COUNTS_PER_V_LV / 20.0

# 12-bit signed converter. A record containing either limit is CLIPPED, and an
# amplitude derived from it is wrong rather than merely noisy -- the failure is
# silent, because a clipped sine still demodulates to a clean-looking number.
ADC_COUNT_MAX = 2047
ADC_COUNT_MIN = -2048
