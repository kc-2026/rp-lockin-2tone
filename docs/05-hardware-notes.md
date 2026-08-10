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

- [ ] **OS version** — every SCPI question depends on it. STILL UNKNOWN; not
      obtainable over SCPI, needs SSH or the web interface.
- [x] `*IDN?` string — `REDPITAYA,INSTR2024,0,01-16`
- [x] Reserved DMA region size as shipped — **2 MiB, not the 32 MB assumed**
- [ ] Whether Deep Memory Generation is available
- [x] `RP_HOST` — `169.254.56.245`

## First contact — 2026-08-10

Link-local (APIPA) addressing on a direct Ethernet cable; no DHCP in the path.
PC side self-assigned `169.254.96.225`, board `169.254.56.245`. Link negotiates
1 Gbps full duplex. **The address is not stable across reconnects** — link-local
is negotiated, so re-check `RP_HOST` after any cable or power cycle.

ICMP is blocked (ping fails) but TCP 5000 is open, so test reachability with a
port check, not a ping.

### Values read back (read-only queries, verified in sync)

| Query | Answer | Note |
|---|---|---|
| `*IDN?` | `REDPITAYA,INSTR2024,0,01-16` | **Does not identify the model** — see below |
| `ACQ:DEC?` | `1` | |
| `ACQ:SOUR1:COUP?` | `DC` | Command supported — indicative of a 250-12 |
| `ACQ:SOUR2:COUP?` | `DC` | |
| `ACQ:SOUR1:GAIN?` | `LV` | 1:1 attenuator |
| `ACQ:AXI:START?` | `16777216` (0x1000000) | Matches the device-tree `buffer@1000000` |
| `ACQ:AXI:SIZE?` | `2097152` | **2 MiB** |
| `ACQ:DATA:FORMAT?` | `ASCII` | Default; BIN must be set explicitly |

### H1.2 cannot be satisfied by `*IDN?`

The test plan assumes `*IDN?` distinguishes a 250-12 from a 125-14. It does
not — the string carries no model name. Since a 125-14 would make every
frequency in this project wrong *silently*, the model must be confirmed another
way: the label on the board, `monitor -f` over SSH, or a loopback measurement
of the actual sample rate. `ACQ:SOUR<n>:COUP` being supported is suggestive
(it is documented as 250-12 only) but is not proof on its own.

### The DMA region is 2 MiB, not 32 MB

Sixteen times smaller than this document previously assumed. What that buys:

| Channels | Rate | Samples/ch | Duration |
|---|---|---:|---:|
| 1 | 250 MS/s | 1048576 | 4.19 ms |
| 1 | 125 MS/s (dec 2) | 1048576 | 8.39 ms |
| 2 | 250 MS/s | 524288 | 2.10 ms |
| 2 | 125 MS/s (dec 2) | 524288 | 4.19 ms |

A 1 s sweep on two channels at decimation 2 needs 477 MiB — short by a factor
of **238**. The device-tree enlargement below is therefore mandatory before
H6, and it also constrains H5.2: a 60 ms emulated response does not fit either.

### SCPI transport behaviour — matters for H1.5

1. **Unsupported commands return zero bytes.** There is no error string. A
   misspelled *query* blocks until timeout; a misspelled *setting* command is
   completely silent and indistinguishable from success. Validating the write
   paths in `hardware.py` therefore requires reading each setting back, not
   just sending it.
2. **A read timeout desynchronises the connection permanently.** The unread
   remainder stays in the socket and every later response is off by one, which
   looks like plausible-but-wrong values rather than an error. Observed exactly
   this: `ACQ:AXI:SIZE?` appearing to return the region *base*. Use `*IDN?` as
   a sync token to confirm alignment after anything suspicious.
3. **Do not open a connection per command.** The server dislikes rapid
   reconnects (as `tests/hardware/conftest.py` already warned) and returns
   truncated responses.

### Unresolved: the link is pathologically slow

Twenty identical `ACQ:DEC?` queries over one warm connection: min 0.078 s,
**median 5.4 s, max 21.9 s**. Zero adapter receive errors accumulated during
the burst, so this is not packet corruption at the NIC. The multi-second values
cluster near TCP retransmission backoff sums, and the occasional 0.078 s proves
the path can be fast.

The adapter does carry 11546 historical receive errors out of 63873 packets,
but none accrued during measurement — treat as a separate, older event.

Suspected cause: the SCPI server was left wedged by an earlier probe that
opened ten connections in quick succession. Restart the SCPI server and
re-measure before investigating further. At this latency H6.2's 477 MB transfer
is not viable, so this must be resolved before Phase 1 can complete.

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
