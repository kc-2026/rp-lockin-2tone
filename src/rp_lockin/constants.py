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

# Largest DMA region it is safe to reserve: the whole upper half. Bounded by
# where Linux ends, not by the OS's needs, precisely because reserving from up
# here takes nothing away from it. A 1 s two-channel sweep at decimation 2
# needs 477 MB and fits with ~35 MB spare.
#
# Confirm with ACQ:AXI:SIZE? after any device-tree change -- asking for more
# than exists does not fail loudly.
MAX_DMA_MB = 512

# Arbitrary-waveform buffer depth of the stock generator.
ASG_BUFFER_MAX = 16384
