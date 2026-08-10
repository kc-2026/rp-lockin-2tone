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
| RAM | 1 GB — but Linux only sees the lower 512 MB, see below |
| Arbitrary buffer | 16384 samples |

The 60 MHz analog bandwidth is central to two things: the 80 MHz carrier is
attenuated on the way out (accepted, compensated downstream), and decimation 2
is aliasing-free because 62.5 MHz Nyquist sits above the rolloff.

## To be recorded on first contact

- [x] **OS version — 2.00, build 37** (commit `a0457d3aa`, Ubuntu 22.04.4,
      U-Boot `redpitaya-v2022.1`, kernel `branch-redpitaya-v2024.1`,
      `5.15.0-xilinx`). This is the 2.x line, which is what `hardware.py` was
      written against. Not in `/etc/redpitaya_version` (absent on this image) —
      it is in `/opt/redpitaya/version.txt`.
- [x] `*IDN?` string — `REDPITAYA,INSTR2024,0,01-16`
- [x] Reserved DMA region size as shipped — **2 MiB, not the 32 MB assumed**
- [ ] Whether Deep Memory Generation is available
- [x] `RP_HOST` — `rp-fffe42.local` (preferred) or `169.254.56.245`
- [x] Board model — `monitor -f` returns `z20_250`, confirming the 250-12
      independently of the case label

## Use the hostname, not the IP

`rp-fffe42.local` resolves over mDNS from Windows and reaches port 5000. The
link-local IP is negotiated and changes on reconnect, so prefer the hostname
in `RP_HOST`. The board's own hostname derives from its MAC (`ff:fe:42`).

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

### H1.2 cannot be satisfied by `*IDN?` — confirmed by label instead

The test plan assumes `*IDN?` distinguishes a 250-12 from a 125-14. It does
not — the string carries no model name. Since a 125-14 would make every
frequency in this project wrong *silently*, the model must be confirmed another
way: the label on the board, `monitor -f` over SSH, or a loopback measurement
of the actual sample rate. `ACQ:SOUR<n>:COUP` being supported is suggestive
(it is documented as 250-12 only) but is not proof on its own.

**Resolved 2026-08-10: Edwin read the board's label — it is a SIGNALlab
250-12.** The 250 MS/s base rate and the whole frequency plan therefore stand.
H1.3 should still confirm the rate by measurement once loopback is wired, since
the label proves the hardware but not that the OS is configured for it.

**Update H1.2 in the test plan** to say "confirm the model by label or
`monitor -f`; `*IDN?` cannot do it."

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

### H1.5 progress — `setup_acquisition` is fully verified

Validated by set-then-read-back on OS 2.00, because a misspelled setting
command returns zero bytes exactly like a correct one. Every command in
`setup_acquisition()` is correct as written:

| Command | Verified |
|---|---|
| `ACQ:DEC <n>` | yes, readback via `ACQ:DEC?` |
| `ACQ:SOUR<n>:COUP AC\|DC` | yes, both values |
| `ACQ:SOUR<n>:GAIN LV\|HV` | yes, both values |
| `ACQ:DATA:FORMAT BIN` | yes, readback via `ACQ:DATA:FORMAT?` |
| `ACQ:DATA:Units RAW` | yes — see below |
| `ACQ:AXI:DEC <n>` | yes, readback via `ACQ:AXI:DEC?` |

**The units setting is a trap worth understanding.** It defaults to `VOLTS`,
and `query_binary_int16()` decodes replies as big-endian int16. In `VOLTS` the
board returns floats, so reinterpreting them as int16 gives the correct sample
*count* and plausible magnitudes while being complete nonsense — a
believable-wrong-answer failure. `ACQ:DATA:Units RAW` does take effect
(confirmed by readback), so the code is right, but any future change here must
keep format and units consistent.

`ACQ:DATA:UNITS?`, `ACQ:DATA:Units?` and `ACQ:AXI:DATA:UNITS?` all return the
same value, so the normal and AXI paths appear to share one units setting.
`hardware.py` sets it on both paths, which is redundant but harmless.

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

### A wedged SCPI server looks like a broken network — RESOLVED

Worth knowing because the symptom is thoroughly misleading.

Twenty identical `ACQ:DEC?` queries over one warm connection gave min 0.078 s,
**median 5.4 s, max 21.9 s**, with the multi-second values clustering near TCP
retransmission backoff sums. That looks exactly like a failing cable, and the
adapter's 11546 historical receive errors made it look more so. It was neither.

The cause was the SCPI server left wedged by a probe that opened ten
connections in quick succession — the thing `tests/hardware/conftest.py` had
already warned about. **Stopping and restarting the SCPI server from the web
interface fixed it completely**: the same 20 queries then ran at min 0.046 s,
median 0.050 s, max 0.052 s. The historical error counters reset with it.

Takeaways:

- **One persistent connection, always.** Never open a connection per command.
  The failure is not an error, it is silent latency and truncated responses.
- **~50 ms is the healthy round trip** for a trivial query on this board — that
  is the SCPI server's own processing, not the network. Budget accordingly: any
  polling loop in `hardware.py` runs at roughly 20 iterations per second.
- If the link ever looks broken again, restart the SCPI server *before*
  suspecting hardware.

## Memory layout — the part that is easy to get wrong

The board has **1 GB**, but the kernel command line carries `mem=512M`, so
Linux confines itself to the lower half and reports ~460 MB. This is deliberate
Red Pitaya configuration: it keeps the upper half permanently outside the OS,
free for DMA capture buffers.

| Range | Size | Owner |
|---|---:|---|
| `0x00000000`–`0x1FFFFFFF` | 512 MB | Linux (`MemTotal` 470932 kB) |
| `0x20000000`–`0x3FFFFFFF` | 512 MB | **unused — reserve the capture buffer here** |

Evidence: `/proc/device-tree/memory/reg` reads `00 00 00 00 40 00 00 00`, i.e.
base 0, size 0x40000000 = 1 GiB. `cat /proc/cmdline` shows the `mem=512M` cap.

**Do not diagnose installed RAM from `/proc/iomem` or `MemTotal`.** Both show
the capped view and will convincingly tell you this is a 512 MB board. An
earlier revision of this document did exactly that and concluded the 1 s
capture was impossible. It is not.

## Enlarging the reserved DMA region

As shipped the region is 2 MiB, based at `0x1000000` — down in Linux's half,
which is why it is small. Move it to the upper half and it can be the full
512 MB at no cost to the OS.

```bash
ssh root@rp-fffe42.local
rw
cp /opt/redpitaya/dts/$(monitor -f)/dtraw.dts ~/dtraw.dts.backup
nano /opt/redpitaya/dts/$(monitor -f)/dtraw.dts
#   buffer@20000000 {
#       reg = <0x20000000 0x20000000>;   # base 512 MB, size 512 MB
#   };
cd /opt/redpitaya/dts/$(monitor -f)/
dtc -I dts -O dtb ./dtraw.dts -o devicetree.dtb
reboot
```

`0x20000000 + 0x20000000 = 0x40000000` — exactly the top of RAM. Confirm
afterwards with `ACQ:AXI:SIZE?`; asking for more than exists does not fail
loudly. Take the backup first: a device tree that overlaps the running kernel's
memory will not boot.

**The instruction this replaces was unsafe.** It read
`buffer@1000000 { reg = <0x1000000 0x20000000>; }` — a 512 MB region based at
the 16 MB mark, running to 528 MB and straight through the memory Linux is
running in.

## Memory and transfer budget, 1 s sweep, 2 channels

Against a 512 MB ceiling — the size of the upper half:

| Decimation | Rate | Nyquist | Memory | Fits? | Transfer @ 100 MB/s | Aliasing |
|---:|---:|---:|---:|:---:|---:|---|
| 1 | 250 MS/s | 125 MHz | 954 MB | no | 9.5 s | none |
| **2** | **125 MS/s** | **62.5 MHz** | **477 MB** | **yes, ~35 MB spare** | **4.8 s** | **none** |
| 4 | 62.5 MS/s | 31.2 MHz | 238 MB | yes | 2.4 s | 31–60 MHz folds |
| 8 | 31.2 MS/s | 15.6 MHz | 119 MB | yes | 1.2 s | 15.6–60 MHz folds |

Decimation 2 is the operating point, as ADR-0002 always intended. Decimation 1
does not fit.

### Decimation 4 as a fallback

Not needed, but worth keeping in mind if the region cannot be enlarged for some
reason. ADR-0002 rejects it because 31–60 MHz folds in, but for *this*
measurement the fold may be tolerable: content at `f` lands at `62.5 − f` MHz,
so the energy reaching our 1 MHz lock-in frequency comes from 61.5 and
63.5 MHz, both above the 60 MHz analog rolloff. Caveats: 60 MHz is a −3 dB
point rather than a wall, and if `ACQ:AVG` applies to the AXI path its boxcar
nulls fall near 62.5 MHz, which would suppress the fold further. Both are
unverified — measure in H3.3/H3.4 before relying on any of it.

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
