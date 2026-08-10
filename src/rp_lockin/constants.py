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

# Physical RAM. MEASURED, not from the datasheet: /proc/iomem on the bench board
# reports "00000000-1fffffff : System RAM" = 0x20000000 = 512 MiB, and Linux
# sees 460 MB of it. Earlier versions of this file said 1 GB, which is what the
# 250-12 is often quoted as having. It is wrong for this unit and it mattered:
# every capture-size decision derives from it.
BOARD_RAM_MB = 512

# Largest DMA region it is safe to reserve. The region is carved out of the same
# 512 MB Linux runs in, so this is a real tradeoff, not a formality. 320 MB
# leaves ~190 MB for the OS, which is tight but workable. 256 MB is the
# comfortable choice and still holds a 1 s two-channel sweep at decimation 4
# (238 MB). Always confirm with ACQ:AXI:SIZE? after a device-tree change --
# asking for more than exists does not fail loudly.
MAX_DMA_MB = 320

# Arbitrary-waveform buffer depth of the stock generator.
ASG_BUFFER_MAX = 16384
