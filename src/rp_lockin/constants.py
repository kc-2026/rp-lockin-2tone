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

# Largest DMA region Red Pitaya recommends reserving on a 1 GB board; Linux
# needs the rest. The 250-12 has 1 GB.
MAX_DMA_MB = 924

# Arbitrary-waveform buffer depth of the stock generator.
ASG_BUFFER_MAX = 16384
