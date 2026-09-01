# Hardware reference — Red Pitaya SIGNALlab 250-12

**What this is:** how the instrument behaves, and the traps it sets. Facts about
the board, not results from it.

**Measured numbers live in `05-results.md`.** If you want the noise floor, the
decimation cost or the spur frequencies, look there.

Every "verified" claim here was checked against OS 2.00 during Phase 1
(`07-phase1-loopback.md`).

---

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

**Resolved 2026-08-10: Kevin read the board's label — it is a SIGNALlab
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
of **238** against the 2 MiB as shipped.

**Superseded 2026-08-14: the enlargement below is NOT mandatory, and was not
done.** The region was raised to 128 MiB, which fits a full 1 s two-channel
capture at **decimation 8** — H6.2 through H6.5 all ran that way. Decimation 8
costs 1.1 dB of noise, and the trigger-recovery objection to it evaporated once
the wavelength axis moved to the laser's serial report. The 512 MB move remains
rejected; see the decimation section further down.

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

### The arbitrary generator does not work the way `waveforms.py` assumes

**This is the most consequential finding of the first hardware session, and it
invalidates `make_am_waveform`'s model of the hardware.** Measured 2026-08-12
on OS 2.00.

`make_am_waveform()` returns `(samples, fs/N)` on the assumption that loading N
samples and setting `SOUR:FREQ:FIX` to `fs/N` replays exactly those N samples,
one per DAC clock. **It does not.** The generator always traverses a fixed
16384-entry table; `SOUR:FREQ:FIX` sets how many times per second that table is
traversed. Entries never written stay zero.

Evidence — three tables loaded in full and played at `fs/16384` =
15258.789 Hz, which steps exactly one entry per clock:

| Table contents | Predicted output | Measured | Purity |
|---|---:|---:|---|
| 1 cycle | 0.0153 MHz | 0.0153 MHz | next line −76 dBc |
| 5243 cycles | 80.0018 MHz | 80.0018 MHz | next line −53 dBc |
| 65 cycles | 0.9918 MHz | 0.9918 MHz | next line −76 dBc |

And the failure mode of the current code, measured directly:

| What `setup_am_generator` does today | Result |
|---|---|
| 50-sample buffer, `FREQ = 5 MHz` | **min −2, max 4 counts — no output at all** |
| 250-sample buffer, `FREQ = 1 MHz` | strong signal, but dominant content near 7 MHz; the 75/80/85 MHz lines are 54–89 dB down |

The 50-sample case produces nothing because the phase accumulator steps
`16384 × 5e6 / 250e6` ≈ 328 entries per clock, so the 50 non-zero entries are
almost never sampled. The 250-sample case aliases the sparse table into junk.

**Consequences.**

1. `setup_am_generator()` cannot drive the board as written. It is not a
   spelling error — the frequency argument means something different.
2. The commensurability rule changes. The buffer period is fixed at
   16384 samples = 65.536 µs, so **every frequency must be an integer multiple
   of fs/16384 = 15258.7890625 Hz**. Buffer length is no longer a free
   parameter, which is what `_minimal_buffer()` exists to choose.
3. 80 MHz is not on that grid: 80e6 / 15258.789 = 5242.88. Nor are 5 and 6 MHz.
   The frequency plan needs moving onto the grid — see `03-frequency-plan.md`.

**Why the offline tests did not catch this.** They verify the commensurability
arithmetic, which is correct, against a model of the generator that is not.
No amount of offline testing could have found it; only the board could.

**Still open:** whether the ASG's table size is settable (the FPGA has such a
register). If SCPI exposes it, setting it to 250 would restore the original
plan unchanged. Not yet probed.

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
| `0x00000000`–`0x1FFFFFFF` | 512 MiB | Linux — **and the capture buffer is in here too** |
| `0x20000000`–`0x3FFFFFFF` | 512 MiB | **unused — reserve the capture buffer here** |

**The capture buffer is NOT in the free upper half.** Confirmed on the board
2026-08-14: `buffer@1000000` has base `0x01000000` and size `0x08000000` —
128 MiB at the 16 MB mark, carved straight out of Linux's own half.

| | Recorded here previously | Measured 2026-08-14 |
|---|---|---|
| `MemTotal` | 470932 kB (460 MB) | **341908 kB (334 MB)** |
| `MemAvailable` | — | **144756 kB (141 MB)** |

The 460 MB figure dates from when the region was 2 MiB. **Enlarging the region to
128 MiB took that memory from the OS.** This is very likely why
`rp_fastread.py` died on a 50 MB request and left the SCPI server degraded — with
~141 MB available it was an out-of-memory kill, and the 1 MB chunking fix
addressed the symptom. Moving the region to the upper half returns 128 MiB to
Linux **whatever size the region is then given**, which is an argument for the
move independent of capture length.

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

**Recovery is easy, contrary to what was recorded elsewhere.** `/dev/mmcblk0p1`
is **vfat (FAT16)**, mounted at *both* `/boot` and `/opt/redpitaya` — so the
files under `/opt/redpitaya/dts/` sit on the FAT partition. If the board will not
boot: pull the SD card, open it on any Windows machine, copy the backup back.
**No ext4 tooling is needed.** An earlier note claiming recovery "requires an
ext4 reader" overstated the risk considerably.

**Do it in two steps, not one.** Nobody has shown the FPGA can DMA to
`0x20000000` — every capture so far has used `0x1000000`. Move the region up but
keep it at **128 MB first**, and confirm a quiet-input capture still returns
σ ≈ 0.68 counts. Only then enlarge to 512 MB. A region that reports the right
size and returns zeros or plausible garbage is this project's signature failure,
and the two possible faults — "cannot reach the upper half" and "region too
big" — are indistinguishable if you change both at once.

**The move buys the decimation, not headroom.** `0x20000000` = 536,870,912
bytes; a 1 s two-channel capture at decimation 2 with 45 ms of pre-roll needs
522,600,000 — **97.3% full, the same margin** as decimation 8 in the present
128 MiB region, since both sides scale by four. Quote sizes in bytes when
comparing: 1 s × 2 ch at decimation 2 is exactly 500,000,000 bytes = 476.8 MiB,
and the region is 134,217,728 bytes = 128 MiB exactly. Mixing MB and MiB across
the two makes the comparison look wrong.

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
| 8 | 31.2 MS/s | 15.6 MHz | 119.2 MiB | yes | 1.2 s | 15.6–60 MHz folds |

### `ACQ:RST` resets gain to LV and coupling to DC — measured

Forced `ACQ:SOUR1:GAIN HV`, sent `ACQ:RST`, read back `LV`. It also resets
`ACQ:DEC` to 1, `ACQ:DATA:FORMAT` to `ASCII` and units to `VOLTS`.

This makes the documented defect precise: `acquire_deep_fast` and
`acquire_deep_2ch` both call `ACQ:RST` and so discard whatever
`setup_acquisition` applied. **For LV/DC work that is harmless, because LV/DC is
exactly what the reset lands on.** It would silently ruin an HV or AC-coupled
deep capture — the capture would succeed and be wrong by 20×. `ACQ:AXI:DEC` is
set explicitly after the reset, so the decimation survives.

**Fixed by `_reapply_front_end()`, which remembers and restores. And on
2026-08-26 that memory was made PER CHANNEL**, which it had not been:

```python
rp.setup_acquisition(decimation=8, coupling="AC", gain="LV")   # both channels
rp.setup_channel(2, gain="HV")                                 # then IN2 alone
```

**The old single-pair version made P2 impossible to run as specified.** The real
experiment needs IN1 on LV for the detector and IN2 on HV for the laser's 3.3 V
trigger, and forcing both to one setting put IN2 back on LV after every reset — 
where a 3.3 V trigger clips into a flat line. That does not present as a range
error. It presents as **"the laser is not triggering"**, and would have sent
somebody to check the BNC.

`setup_acquisition` still sets both channels, which is what it always meant;
call `setup_channel` afterwards where they must differ, and note the order
matters. `rp.coupling` and `rp.gain` still read channel 1 for older callers.

### The fast-read path's little-endian decode is proven

`fast_read()` decodes little-endian while `query_binary_int16()` decodes
big-endian, and `hardware.py` flagged this as "not yet proven". It is now
proven, and the method matters: a byte-swapped *noise* record still looks like
noise, just with the wrong amplitude, so a waveform test proves less than you
would think. The check is to compare the deep record's raw σ against a plain
`acquire()` on the same quiet input — 0.6797 against 0.6781 counts, a ratio of
1.002, where a byte swap would be off by ~100×. **Re-check it that way after any
change to that decode.**

## SCPI notes

Enable the server: web interface → Development → SCPI server → Run. Port 5000.

Commands used by `hardware.py`. **All verified against OS 2.00 during Phase 1**
(H1.5, completed 2026-08-14) — the "unverified" caveat that stood here is gone.
Three things learned doing it, each of which cost time:

- **A misspelled setting command returns zero bytes, exactly like a correct
  one.** Verify by setting and reading back, never by absence of an error.
- **`ACQ:RST` resets gain to LV, coupling to DC, decimation to 1, format to
  ASCII and units to VOLTS.** `acquire_deep_fast` issues it, so anything set
  beforehand is discarded. Harmless for LV/DC work because that is what it
  resets *to*; it would silently ruin an HV or AC-coupled capture, and it will
  break a following `acquire()` by leaving the format at ASCII.
- **`SOUR<n>:FREQ:FIX` does not mean what it appears to** for a loaded table: it
  sets how many times per second the fixed 16384-entry table is traversed, not a
  per-sample clock. That misunderstanding meant `setup_am_generator` produced no
  output at all.

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

## The Santec lasers — TSL-770 and TSL-775

Recorded 2026-08-14 from the **TSL-775 operation manual v1.0** (supplied by
Kevin) and the **TSL-770 operation manual** (santec.com). Nothing here is from
memory. Neither laser has been connected yet, so none of it is verified on the
bench — that is P1 in `08-the-bench.md`.

### Communication

| | |
|---|---|
| Interfaces | GPIB (IEEE-488), USB (type B, **"USB DEVICE"** socket — *not* "USB HOST" — ~1 MB/s), LAN (100BASE-TX, TCP/IP, configurable IP and port, ~30 Mb/s) |
| **In use here** | **USB, as `COM29`** (Kevin, 2026-08-14) |
| **Baud rate** | **NOT STATED IN THE MANUAL.** Probed by `scripts/p1_laser_check.py` |
| **Delimiter** | **bare `CR`** |
| Command sets | Two, selectable. A legacy TSL-550-compatible set, and the native TSL-770/775 SCPI set. **They differ in response formats AND in the binary logging format** |

**The delimiter is a trap.** The Red Pitaya's SCPI uses `CRLF`; the Santec uses
`CR` alone. A transport written for one will hang waiting on the other, and the
symptom is a timeout that looks like a dead cable. Do not reuse `hardware.py`'s
line reader unchanged.

### Getting USB working — the two-stage FTDI install

Done 2026-08-14; recorded because the intermediate state looks like a failure.

1. Install the Santec driver (ships on a disk with the laser). The device appears
   under **USB controllers** as "Santec USB TSL-775" — that is the **D2XX** node,
   and `pyserial` cannot see it.
2. **Device Manager → that device → Properties → Advanced → tick "Load VCP"**,
   then unplug and replug. A "USB Serial Port" child appears, initially under
   **Other devices** with no driver — which looks like it failed, and has not.
3. **Right-click that child → Update driver.** Windows Update usually has FTDI's
   VCP driver; otherwise browse to the Santec folder, or take it from
   `ftdichip.com/drivers/vcp-drivers`.
4. It moves to **Ports (COM & LPT)** with a COM number. **Here: COM29.**

**The baud rate is not in the manual** — the USB section documents the delimiter
and the throughput and nothing about line settings. `p1_laser_check.py` probes
9600 through 230400 and reports which answers `*IDN?` sensibly, rather than a
guess being baked into the driver. Once known, pass `--baud`.

The D2XX route (`ftd2xx`) would also work and needs no VCP checkbox, but VCP is
simpler and `pyserial` is a better-behaved dependency. **Do not reach for
`pyftdi`** — it wants the driver replaced with libusb/WinUSB, which would break
Santec's own software.

### Reading the wavelength log — the commands that matter

| Command | Does |
|---|---|
| `:READout:POINts?` | number of logged points, 0 to 500,000 |
| `:READout:DATa?` | the wavelength log |
| `:READout:DATa:POWer?` | the power log, 32-bit float, dBm — a free cross-check |

**The log carries wavelength values; the time axis is implicit.** Documented:
`:READout:DATa?` returns "a header and wavelength data array", `:READout:POINts?`
returns "the number of data points recorded by wavelength logging" (TSL-775 p93,
TSL-770 p93 and its command index). No time column is transmitted.

**That is not the same as the times being unknown.** `wavelength[i]` belongs to
trigger pulse `i`, so with the trigger stepping in time the log *is* wavelength
against relative time from the first trigger — the times are reconstructed as
`first_edge + i × step` rather than read. The distinction matters only because a
reconstructed axis depends on two things a transmitted one would not: that the
trigger really is stepping in time (**Q24**) and that there is one log point per
pulse (**Q26**). If either is false the times are wrong and nothing in the data
would say so.

**That there is exactly one log point per trigger pulse WAS an assumption, and
the design no longer depends on it (2026-08-25).** Neither manual states it, and
it used to be load-bearing. `pipeline.reduce_sweep` now derives the time step
from the trigger train's **span** over (N − 1) logged points rather than from the
interval between pulses, so nothing counts pulses and a laser logging at some
other divisor gives the same answer. **Q26 is dead**; see `11-pipeline.md`.

Comparing `:READout:POINts?` against the recorded pulse count is still worth
doing at P2 as a sanity check — `check_alignment` performs exactly that — but
nothing rests on the outcome.

**Q24 is still live and still matters.** The step arithmetic assumes the trigger
is periodic in TIME. In wavelength-periodic mode the logged points are unevenly
spaced in time and the whole scheme is wrong.

**And one trap the manual's own spec creates.** The trigger is a **25 µs
pulse**, so every logged point produces a rising edge AND a falling edge.
`find_trigger_edges` defaults to reporting both; anything deriving a step or
counting pulses must pass `polarity="rising"`, or it reads a step near half the
truth and compresses the wavelength axis 2× while still drawing a clean trace.

Both `:READout:DATa?` responses are IEEE 488.2 definite-length blocks — the same
`#4nnnn` header the Red Pitaya uses — followed by:

| Command set | Payload | Units |
|---|---|---|
| Legacy (TSL-550-compatible) | 4-byte signed integers | 0.1 pm |
| Native (TSL-770/775 SCPI) | 8-byte IEEE-754 doubles | metres |

**Both are little-endian** ("Intel byte order" in the manuals). Note this is the
opposite of the Red Pitaya's SCPI path, which is big-endian — the same trap that
`fast_read` documents, in a second instrument.

### Trigger output

| Command | Values |
|---|---|
| `:TRIGger:OUTPut` | 0 None, 1 Stop, 2 Start, **3 Step** |
| `:TRIGger:OUTPut:ACTive` | 0 rising, 1 falling |
| `:TRIGger:OUTPut:STEP[:WIDTh]` | the step size, 0.1 pm resolution |
| `:TRIGger:OUTPut:SETTing` | selects whether the step is in wavelength or in time — **see the warning below** |

### The trigger output's electrical spec — U7, answered from the manual

TSL-775 p46, section 6.5:

| | |
|---|---|
| Levels | **3.3 V high, 0 V low** |
| **Pulse width** | **25 µs** |
| **Maximum repetition rate** | **20 kHz** (so pulses are ≥50 µs apart) |
| Minimum trigger step | depends on sweep speed — 0.1 pm at 0.5–2 nm/s, rising to 10 pm at 200 nm/s |

**Three consequences, and they settle arguments this project has been having.**

**1. It will not fit the ±1 V range.** 3.3 V needs **HV (±20 V) on IN2**. That is
fine and costs nothing: `ACQ:SOUR<n>:GAIN` is **per channel**, so IN1 stays on LV
for the signal while IN2 runs HV for the trigger.

**2. The missed-edge worry is dead on the real signal.** A 25 µs pulse is **780
samples at decimation 8**, and pulses are at least 1560 samples apart. Every
anxiety about losing edges came from a synthetic 20 ns pattern that was an
artefact of the ASG's 4 ns table step — nothing like this. **Decimation 8 is
comfortably adequate for the real trigger.**

**3. The point count is modest.** At 20 kHz for 1 s that is at most 20,000
pulses, far below the 500,000-point logging ceiling and far sparser than the
122,000-pulse train used in H7.1.

### Trigger output mode

**`:TRIGger:OUTPut:SETTing` is documented with INVERTED encodings between the two
models:**

| | 0 | 1 |
|---|---|---|
| TSL-775 manual, p100 | periodic in **wavelength** | periodic in **time** |
| TSL-770 manual, p99 | periodic in **time** | periodic in **wavelength** |

One is a documentation error, or the models genuinely differ. **Set it and read
it back; never hardcode it** (Q24). The failure is silent — the wrong mode still
emits a trigger train, just periodic in the wrong variable, so the wavelength
spacing comes out wrong with nothing appearing broken.

Also worth knowing: mode **2 (Start)** emits a single pulse at sweep start. That
is all the current design actually needs for alignment, and it removes the
miscount risk entirely. Mode 3 (Step) gives the train, which is what lets the
recorded edges carry the index pairing and the clock check. Worth deciding
deliberately at P1 rather than inheriting whatever the laser is set to.

### Consequences for the driver

- **It reads AFTER the sweep, not during.** `:READout:DATa?` dumps a completed
  log, so the driver runs after the capture rather than alongside it.
- **A 1 s sweep fits comfortably.** The 500,000-point ceiling is well above the
  ~122,000 pulses a 1 s sweep at 8.192 µs steps would produce.
- **Which command set the laser is in must be established, not assumed** — it
  changes the payload from 4-byte integers in 0.1 pm to 8-byte doubles in metres.
  Reading `:READout:POINts?` and checking the byte count against the header is
  the cheap way to tell.

## The photodetector — Thorlabs PDA05CF2

Recorded 2026-08-14 from the Thorlabs manual (Rev B, 3 January 2018) supplied by
Kevin. Not connected yet, so nothing below is verified on the bench — that is P4
in `08-the-bench.md`.

| | |
|---|---|
| Detector | InGaAs, Ø0.5 mm active area |
| Wavelength range | 800–1700 nm — **covers a 1520–1570 nm sweep comfortably** |
| Peak response | 1.04 A/W at 1590 nm |
| **Small-signal bandwidth** | **150 MHz** |
| NEP at peak | 1.26 × 10⁻¹¹ W/√Hz |
| Output noise | 2 mV rms |
| Transimpedance gain | 5 × 10³ V/A into 50 Ω, **1 × 10⁴ V/A into Hi-Z** |
| Output voltage | 0 to 5 V into 50 Ω, **0 to 10 V into Hi-Z** |
| Dark offset | ±20 mV |
| Max output current | 100 mA |
| Output | includes a **50 Ω series resistor**, forming a divider with the load |

### U4 is closed, and comfortably

**The detector is flat to 150 MHz, so 991.821 kHz sits four orders of magnitude
inside its passband.** "Does the photodetector roll off at 1 MHz" was a live risk
to the entire measurement premise. It does not. Nothing more is needed here.

### Two things about the output that shape the whole input stage

**It is unipolar with a DC pedestal.** The output runs 0 to 10 V, and the DC
level tracks average optical power. Our signal is a small modulation at
991.821 kHz riding on top of it.

**Into the Red Pitaya it behaves as Hi-Z, not 50 Ω.** The board's inputs are
1 MΩ, so the 50 Ω series resistor divides by 0.99995 — negligible — and the
detector delivers its **Hi-Z figures: 10⁴ V/A and up to 10 V.**

Ten volts against a ±1 V range is a problem, and the answer is almost certainly
**AC coupling**, which `setup_acquisition(coupling="AC")` already supports. It
drops the pedestal and lets the sensitive ±1 V range see only the modulation.
The alternative — the ±20 V range — is a bad trade: σ there is 45 µV, four times
the detector's own noise, so the ADC would dominate a measurement it currently
does not. **Measured 2026-08-17 (Q25) and it is free: the corner is 17.0 Hz, single-pole,
so attenuation at 991.821 kHz is 1.3×10⁻⁹ dB, and the noise floor is unchanged
AC coupled.** The one thing AC coupling does cost is any DC reading of average
optical power; the laser's own `:READout:DATa:POWer?` log can supply that if it
is ever wanted.

### Saturation and damage

Output saturates at 10 V, which is 1.00 mA of photocurrent, about **0.96 mW**
optical at peak responsivity. **An explicit optical damage threshold is not
stated in the manual** — treat ~1 mW as the working ceiling and ask Thorlabs or
Kevin before exceeding it.

One electrical hazard from the manual, worth repeating because it destroys the
instrument: **do not add a 50 Ω terminator when the load is already 50 Ω.** The
combined 25 Ω allows ~135 mA and damages the output driver. With the Red Pitaya's
1 MΩ input this does not arise, but it would if a scope is teed in alongside.

## The RF chain — ZHL-1-2W+ amplifier and 1550AOM-1

From the Mini-Circuits and Aerodiode datasheets, both read 2026-08-17. Neither is
connected yet.

| Mini-Circuits ZHL-1-2W+ | |
|---|---|
| Frequency range | 5–500 MHz — 80 MHz is comfortably inside |
| Gain | 29 dB min, **32 dB typ** |
| Output at 1 dB compression | +32.5 dBm min, **+33 dBm typ** |
| Output IP3 | +44 dBm typ |
| **Absolute max input, no damage** | **+10 dBm** |
| Supply | +24 V, 0.9 A |
| Impedance | 50 Ω, BNC |

| Aerodiode 1550AOM-1 | |
|---|---|
| Wavelength | 1470–1630 nm (typ 1550) — covers a 1520–1570 sweep |
| **RF drive** | **2.5 W nominal**, 50 Ω, SMA |
| **Frequency** | **80 MHz** — matches the carrier exactly |
| Frequency shift | ±80 MHz |
| **Average optical handling** | **0.5 W** |
| Insertion loss | 2.0–3.0 dB (2.5 typ) |
| Extinction ratio | 50–55 dB |
| Rise time | 50 ns |

### RF DRIVE LEVEL: leave it where Kevin tuned it. No attenuator.

**Recommendation withdrawn 2026-08-17.** Three revisions of this section (20 dB,
then 10 dB, then 6 dB of attenuation, then "turn the drive down 4 dB") were all
solving a problem this experiment does not have. **Kevin's tuning is correct and
should not be changed.** The reasoning is recorded because the mistake is an easy
one to repeat.

**What Kevin did:** laser CW, unmodulated 80 MHz through the amplifier into the
AOM, tuned the Red Pitaya output until the diffracted light on a scope was at its
maximum. Standard AOM tuning.

**Why that is right here.** The drive is **depth-1 AM** — H2.2 measured
sideband/carrier = 0.5, and sideband/carrier is m/2, so m = 1.0. **The RF
envelope goes all the way to zero on every cycle.** The AOM is switched fully on
and off; it is not held at a bias point with a small wiggle on top.

So the envelope sweeps the *entire* diffraction curve each cycle, from dark to
peak. There is no operating point whose slope matters. What matters is how bright
the "on" end is — which is exactly what maximising the CW diffraction finds.

| Envelope peak | η at peak | signal at f1 | signal at 2f1 |
|---:|---:|---:|---:|
| 0.50 × Pπ | 80% | 0.425 | 0.062 |
| 0.75 × | 96% | 0.523 | 0.041 |
| **1.00 × — Kevin's tuning** | **100%** | **0.567** | **0.000** |
| 1.25 × | 97% | 0.570 | 0.055 |
| 1.50 × | 88% | 0.545 | 0.116 |

**99.4% of the theoretical best, and zero frequency doubling.** The 2f1 term
appears only when the envelope *overshoots* the peak — the light then dips at the
top of every cycle, giving two dips per period. Kevin's setting is precisely the
point where the envelope touches the peak and turns around, which is the one
place that cannot happen.

### The mistake, recorded so it is not repeated

The withdrawn analysis assumed **small-signal** modulation: a carrier at a bias
point with a small excursion, where the response is `dη/dP × ΔP` and sitting on a
peak means zero slope means no signal. That is the standard lock-in picture and
it is correct — **for a different experiment.**

This one is large-signal switching. The distinction is not a detail: the two
pictures give opposite advice about the same knob, and the small-signal one is
the more natural thing to reach for.

**The tell was in what Kevin observed** — "less light either side" — which was
read as "you are at a stationary point, therefore no first-order response". True
for a small excursion; irrelevant when the excursion covers the whole curve.

### What still holds

- **No attenuator is needed for protection.** The amplifier sees −4 dBm against a
  +10 dBm rating: 14 dB of margin, and the board's 14 dB rolloff at 80 MHz means
  it cannot get closer. The only scenario needing a pad is somebody running this
  below the rolloff, where the board *can* reach +10 dBm.
- **The one-tone control measurement (P5.1) is unaffected and still matters.**
  Drive f1 alone and look for anything at |f2 − f1|. That tests whether the
  amplifiers or the detector manufacture a false signal, and it is worth running
  whatever the drive level is.
- **The 14 dB of board rolloff at 80 MHz stands** and still answers U1. If drive
  ever falls short, commanding a bigger number will not help — the board is
  already clamping.

### Two ordering rules that damage things if ignored

**"Open load is not recommended, potentially can cause damage. With no load,
derate max input power by 20 dB."** — from the amplifier datasheet. **Connect the
AOM before applying RF**, and never power the amplifier into an open port.

**The 12 mW laser is not a risk to the AOM** — 0.5 W rating is a 42× margin. The
optical constraint is entirely at the far end, where the detector saturates at
0.96 mW.

## Safety

Loopback phase: the board's own specifications are the limit. Do not command
amplitudes outside the selected output range. The DUT, amplifiers, AOMs,
photodetector and laser are **not connected**.

Outputs must be off when a session ends. `tests/hardware/conftest.py` enforces
this with an autouse fixture — keep it.

Anything beyond loopback requires the Phase 2 planning session.
