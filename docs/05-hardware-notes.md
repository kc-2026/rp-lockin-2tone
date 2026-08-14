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

## First contact — 2026-08-12

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

**Resolved 2026-08-12: Kevin read the board's label — it is a SIGNALlab
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

### Decimation costs far less noise than ADR-0002 assumes — MEASURED

ADR-0002 rejects decimation beyond 2 on the grounds that everything above the
new Nyquist folds into the record. That is true in principle but the penalty is
small, because **the board applies its own anti-alias filter when decimating.**
Measured 2026-08-14, outputs off, loopback cables attached:

| Decimation | Rate | σ per output point | Cost vs dec 2 | Signal for SNR 10 | 1 s, 2 ch |
|---:|---:|---:|---:|---:|---:|
| 2 | 125 MS/s | 3.29 µV | — | 36.0 µV | 477 MB |
| 4 | 62.5 MS/s | 3.65 µV | +0.9 dB | 39.8 µV | 238 MB |
| **8** | **31.2 MS/s** | **3.75 µV** | **+1.1 dB** | **40.9 µV** | **119 MB** |
| 16 | 15.6 MS/s | 4.58 µV | +2.9 dB | 50.1 µV | 60 MB |

**Decimation 8 is the practical operating point on a 128 MB region.** It runs a
full 1 s two-channel capture for a 14% sensitivity cost, and avoids needing the
DMA region moved into the upper half of RAM — an edit that changes a node name,
an alias, and places the region outside the kernel's memory map, with a
non-booting board as the failure mode.

Note the margin is thin: 1 s at decimation 8 is 119 MB, and 43 ms of pre-roll
adds ~5 MB, so ~124 MB of 128 MB. Decimation 16 leaves comfortable headroom
(63 MB) for +2.9 dB if that becomes awkward.

**Why the folding penalty is small here.** Nothing in this measurement has
high-frequency content to fold: the photodetector returns only the ~1 MHz
intermodulation response, so only *noise* folds, not signal. The naive estimate
(~6 dB at decimation 8, from counting alias bands) is wrong because it ignores
the decimation filter.

Decimation 2 remains the best operating point if the memory is ever available,
and decimation 1 does not fit at any region size.

**Decimation 2 is right for the real measurement but wrong for loopback
testing, and this is not a contradiction.** At decimation 2 the Nyquist limit
is 62.5 MHz, so an 80 MHz carrier aliases down to 45 MHz. In the real
experiment that never arises: the photodetector returns only the ~1 MHz
intermodulation response, and the 80 MHz never reaches an input. In loopback we
wire an output carrying 80 MHz straight into an input, so it does.

**Use decimation 1 for any loopback test that looks at the carrier.** A
measurement of the 80 MHz carrier at decimation 2 is measuring a 45 MHz alias,
and it will look entirely plausible — that is how the first drift measurement
produced a confident fictitious answer. Do not "fix" the operating point in
response; the plan is correct.

### Decimation 4 as a fallback

Not needed, but worth keeping in mind if the region cannot be enlarged for some
reason. ADR-0002 rejects it because 31–60 MHz folds in, but for *this*
measurement the fold may be tolerable: content at `f` lands at `62.5 − f` MHz,
so the energy reaching our 1 MHz lock-in frequency comes from 61.5 and
63.5 MHz, both above the 60 MHz analog rolloff. Caveats: 60 MHz is a −3 dB
point rather than a wall, and if `ACQ:AVG` applies to the AXI path its boxcar
nulls fall near 62.5 MHz, which would suppress the fold further. Both are
unverified — measure in H3.3/H3.4 before relying on any of it.

## Measured noise floor and the on-board spur family — 2026-08-12 (H3.3)

Outputs off, loopback cables fitted, DC coupled, decimation 2.

| | IN1 | IN2 |
|---|---:|---:|
| Density at 991.821 kHz, ±1 V range | **45.6 nV/√Hz** | 52.5 nV/√Hz* |
| σ per quadrature at operating bandwidth | **2.96 µV** | 3.42 µV* |
| Density at 991.821 kHz, ±20 V range | 697 nV/√Hz* | 624 nV/√Hz* |
| σ per quadrature, ±20 V range | 45.4 µV* | 40.6 µV* |

IN1 on ±1 V is **measured directly** off a 256 ms deep capture: demodulate the
record, take the scatter of X and Y (2.961 and 2.957 µV, agreeing to 0.1%). A
second, independent route — measure the noise density and convert it with the
demodulator's noise gain — gave 3.16 µV, agreeing to 6%. \*Starred figures come
from the density route only and are likely ~6% high for the same reason.

Repeatable to 0.2%. Raw record σ is 0.68 counts against 0.289 counts for ideal
12-bit quantisation, so the floor is analog, not quantisation — though
quantisation is ~18% of the variance and not negligible.

**σ scales as √ENBW to ~1.5%**, confirmed on real data across a factor of 8 in
bandwidth (H3.4). Scale by √ENBW, not √(nominal bandwidth), which is only good
to 4% because the ENBW/bandwidth ratio drifts with bandwidth.

### The switching-supply spur family — the one real hazard H3.3 found

Present on both inputs **with the outputs off**. Measured at 59.6 Hz resolution,
with the amplitude estimator validated against an injected tone of known size
(recovered to 0.2%):

| | Centre | FWHM | Amplitude | vs σ | Offset from f_lockin |
|---|---:|---:|---:|---:|---:|
| Fundamental | **504 867.6 Hz** | 335 Hz | **33.7 µV** | 11.4× | −486.95 kHz |
| 2nd harmonic | **1 009 737.7 Hz** | 451 Hz | **32.2 µV** | 10.9× | **+17.92 kHz** |
| 3rd harmonic | 1 514 602.7 Hz | 750 Hz | 18.0 µV | 6.1× | +522.78 kHz |

**Nothing reaches the trace today** — the demodulator rejects a component
17.9 kHz off frequency by more than 200 dB, and at 59.6 Hz resolution there is
no line at all inside the ±2250 Hz measurement band (worst in-band bin 1.44× the
local floor, which is just what the maximum of 75 noise bins looks like).

**But the margin is a frequency margin, not a rejection margin, and the stakes
are higher than they look.** A **−1.77% drift** of the fundamental (504.868 →
495.911 kHz) puts the second harmonic exactly on 991.821 kHz, where there is no
rejection at all. It would then read as a **32 µV steady amplitude — 11× the
noise floor, and squarely inside the 30 µV range we would call a healthy real
signal.** It would not look like interference; it would look like a strong,
clean, steady DUT response. So:

- **504.868 kHz and its multiples are a forbidden zone for any future choice of
  difference frequency**, with several kHz of margin (relevant to Q9, which
  contemplates lower values). The present 991.821 kHz is safe by luck, not by
  design.
- Short-term the line is stable: it held to within one 476 Hz bin across all
  eight sub-segments of a 256 ms record, and its 335 Hz width implies only
  ~0.07% jitter — 25× less than the 1.77% needed. **But 256 ms says nothing
  about hours, load, or temperature**, and a switcher moving a few percent over
  its full range is ordinary. **Re-measure the fundamental after the board has
  been warm and loaded for some hours** and confirm it has not walked toward
  495.9 kHz.

An earlier coarse-resolution pass put this family at 505.447 kHz with a ~4 µV
amplitude. Both were wrong: a 450 Hz-wide line smeared across a 7.6 kHz bin
reads about 8× too low, and the frequencies were bin centres rather than
measurements. **Do not size a narrow line from a coarse spectrum.**

### Do not read broadband noise at high decimation

Measured at the same input on the same afternoon, the floor near 991.8 kHz
"improved" on IN1 from 52 to 17 nV/√Hz going from decimation 2 to 64, while on
IN2 it "worsened" from 54 to 134. At decimation 2 the two channels agree within
5%; at decimation 64 they disagree by 60×. Both trends are artefacts — folding
of 2–60 MHz into the reduced band, plus whatever averaging the FPGA applies at
high decimation. **This settles the "unverified" caveat on the decimation 4
fallback above: do not use a high-decimation noise measurement to justify it.**

High decimation *is* good for one thing: locating discrete lines. A 16384-sample
buffer at decimation 64 covers 4.19 ms and so resolves 238 Hz, and a real line
holds its frequency as fs changes whereas a folded one moves. That is how the
505.447 kHz family above was pinned without any deep capture.

### `ACQ:RST` resets gain to LV and coupling to DC — measured

Forced `ACQ:SOUR1:GAIN HV`, sent `ACQ:RST`, read back `LV`. It also resets
`ACQ:DEC` to 1, `ACQ:DATA:FORMAT` to `ASCII` and units to `VOLTS`.

This makes the documented defect precise: `acquire_deep_fast` and
`acquire_deep_2ch` both call `ACQ:RST` and so discard whatever
`setup_acquisition` applied. **For LV/DC work that is harmless, because LV/DC is
exactly what the reset lands on.** It would silently ruin an HV or AC-coupled
deep capture — the capture would succeed and be wrong by 20×. `ACQ:AXI:DEC` is
set explicitly after the reset, so the decimation survives.

### The fast-read path's little-endian decode is proven

`fast_read()` decodes little-endian while `query_binary_int16()` decodes
big-endian, and `hardware.py` flagged this as "not yet proven". It is now
proven, and the method matters: a byte-swapped *noise* record still looks like
noise, just with the wrong amplitude, so a waveform test proves less than you
would think. The check is to compare the deep record's raw σ against a plain
`acquire()` on the same quiet input — 0.6797 against 0.6781 counts, a ratio of
1.002, where a byte swap would be off by ~100×. **Re-check it that way after any
change to that decode.**

### Use a median, not a mean, for a noise floor

A mean density over a window around the lock-in frequency silently absorbs any
spur in that window. The first pass of H3.3 averaged over ±38 kHz, swallowed the
1010.895 kHz harmonic, and reported 6.2 µV instead of 3.16 µV — wrong by 2×,
with nothing looking wrong. A median ignores lines. The mean/median ratio is
itself the useful diagnostic: it ran 2.1–2.4 at decimation 2, which is the tell
that a line is present.

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
