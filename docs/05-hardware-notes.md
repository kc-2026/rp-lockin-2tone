# Hardware notes — SIGNALlab 250-12

## Specifications that matter here

| | |
|---|---|
| ADC | AD9613, 12-bit, 250 MS/s, 2 channels |
| DAC | AD9746, 14-bit, 250 MS/s, 2 channels |
| Analog bandwidth | DC–60 MHz, **both input and output** |
| Input range | ±1 V / ±20 V, software selectable |
| Input impedance | 1 MΩ, AC/DC coupling software selectable |
| Output range | ±1 V @ 50 Ω / ±2 V Hi-Z / ±5 V @ 50 Ω / ±10 V Hi-Z |
| FPGA | Zynq 7020 |
| RAM | 1 GB |
| Arbitrary buffer | 16384 samples |

The 60 MHz analog bandwidth is central to two things: the 80 MHz carrier is
attenuated on the way out (accepted, compensated downstream), and decimation 2
is aliasing-free because 62.5 MHz Nyquist sits above the rolloff.

## To be recorded on first contact

- [ ] **OS version** — every SCPI question depends on it
- [ ] `*IDN?` string
- [ ] Reserved DMA region size as shipped
- [ ] Whether Deep Memory Generation is available
- [ ] `RP_HOST`

## Enlarging the reserved DMA region

Default is 32 MB. A 1 s sweep at decimation 2 on two channels needs 477 MB, so
reserve 512 MB. Ceiling is 924 MB on a 1 GB board — Linux needs the rest.

```bash
ssh root@<board>
rw
nano /opt/redpitaya/dts/$(monitor -f)/dtraw.dts
#   buffer@1000000 {
#       reg = <0x1000000 0x20000000>;    # 0x20000000 = 512 MB
#   };
cd /opt/redpitaya/dts/$(monitor -f)/
dtc -I dts -O dtb ./dtraw.dts -o devicetree.dtb
reboot
```

Confirm afterwards with `ACQ:AXI:SIZE?`. Rebooting the board is permitted;
nobody else uses it.

## Memory and transfer budget, 1 s sweep, 2 channels

| Decimation | Rate | Nyquist | Memory | Transfer @ 100 MB/s | Aliasing |
|---:|---:|---:|---:|---:|---|
| 1 | 250 MS/s | 125 MHz | 954 MB | 9.5 s | none |
| **2** | **125 MS/s** | **62.5 MHz** | **477 MB** | **4.8 s** | **none** |
| 4 | 62.5 MS/s | 31.2 MHz | 238 MB | 2.4 s | 31–60 MHz folds |
| 8 | 31.2 MS/s | 15.6 MHz | 119 MB | 1.2 s | 16–60 MHz folds |

Decimation 2 is the recommended operating point. Decimation 1 exceeds the
924 MB ceiling.

## SCPI notes

Enable the server: web interface → Development → SCPI server → Run. Port 5000.

Commands used by `hardware.py`, all **unverified**:

| Purpose | Command |
|---|---|
| Identify | `*IDN?` |
| Arbitrary waveform | `SOUR<n>:FUNC ARBITRARY`, `SOUR<n>:TRAC:DATA:DATA <v,...>` |
| Frequency / amplitude | `SOUR<n>:FREQ:FIX`, `SOUR<n>:VOLT` |
| Output enable | `OUTPUT<n>:STATE ON`, `SOUR<n>:TRig:INT` |
| Acquisition setup | `ACQ:RST`, `ACQ:DEC`, `ACQ:SOUR<n>:COUP`, `ACQ:SOUR<n>:GAIN` |
| Data format | `ACQ:DATA:FORMAT BIN`, `ACQ:DATA:Units RAW` |
| Deep memory | `ACQ:AXI:START?`, `ACQ:AXI:SIZE?`, `ACQ:AXI:DEC` |
| | `ACQ:AXI:SOUR<n>:SET:Buffer <addr>,<size>` |
| | `ACQ:AXI:SOUR<n>:ENable ON` |
| | `ACQ:AXI:SOUR<n>:Trig:Dly <n>` |
| | `ACQ:AXI:SOUR<n>:Trig:Pos?`, `ACQ:AXI:SOUR<n>:TRIG:FILL?` |
| | `ACQ:AXI:SOUR<n>:DATA:Start:N? <pos>,<size>` |

Open questions to settle in H1/H2:

- Does the generator accept a 250-point arbitrary buffer, or enforce a longer
  minimum? If it enforces one, use a multiple of 250 and scale the playback
  frequency by the same factor.
- Does `SOUR:TRig:INT` start both channels synchronously?
- Is the relative carrier phase between OUT1 and OUT2 repeatable across
  restarts?
- Are IN1 and IN2 sample-aligned? A fixed skew biases the wavelength mapping.

## Safety

Loopback phase: the board's own specifications are the limit. Do not command
amplitudes outside the selected output range. The DUT, amplifiers, AOMs,
photodetector and laser are **not connected**.

Outputs must be off when a session ends. `tests/hardware/conftest.py` enforces
this with an autouse fixture — keep it.

Anything beyond loopback requires the Phase 2 planning session.
