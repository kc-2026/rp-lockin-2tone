# 04 — Board reference: Red Pitaya SIGNALlab 250-12

**What this is:** how the board behaves, and the traps it sets. Facts about the
instrument, not results from it.

- **Measured numbers** are in `06-results.md`.
- **The other instruments** — lasers, detectors, amplifier, AOM — are in
  `05-instruments.md`.
- **How each claim was checked**, step by step, is in `12-test-campaigns.md`.

Every "verified" claim here was checked against **OS 2.00, build 37**.

---

## Specifications that matter here

| | |
|---|---|
| ADC | AD9613, 12-bit, 250 MS/s, 2 channels |
| DAC | AD9746, 14-bit, 250 MS/s, 2 channels |
| Analog bandwidth | DC–60 MHz, **both input and output** |
| Input range | ±1 V (LV) / ±20 V (HV), software selectable, **per channel** |
| Input impedance | 1 MΩ, AC/DC coupling software selectable, **per channel** |
| Output range | ±1 V @ 50 Ω / ±2 V Hi-Z / ±5 V @ 50 Ω / ±10 V Hi-Z |
| FPGA | Zynq 7020 |
| RAM | 1 GB — but Linux only sees the lower 512 MB, see below |
| Arbitrary buffer | 16384 samples |
| OS | 2.00 build 37, commit `a0457d3aa`, Ubuntu 22.04.4, kernel 5.15.0-xilinx |
| `*IDN?` | `REDPITAYA,INSTR2024,0,01-16` |

The 60 MHz analog bandwidth is central to two things: the 80 MHz carrier is
attenuated by ~14 dB on the way out (accepted, compensated downstream), and
decimation 2 is aliasing-free because its 62.5 MHz Nyquist sits above the
rolloff.

**`*IDN?` cannot identify the model.** The string carries no model name, and a
125-14 would make every frequency in this project wrong *silently*. The model
was confirmed two other ways: the label on the case, and `monitor -f` over SSH
returning `z20_250`. The 250 MS/s base rate was then confirmed by measurement
in H1.3. `ACQ:SOUR<n>:COUP` being supported is suggestive — it is documented as
250-12 only — but is not proof on its own.

## Getting to it

```bash
export RP_HOST=rp-fffe42.local        # mDNS. Prefer this to the IP
```

- **Use the hostname.** Addressing is link-local (APIPA) over a direct
  Ethernet cable with no DHCP in the path, so the IP is negotiated and
  **changes on reconnect**. The board's hostname derives from its MAC
  (`ff:fe:42`). The last observed address was `169.254.56.245`.
- **ICMP is blocked.** Ping fails while TCP 5000 is open, so test reachability
  with a port check, never a ping.
- **The SCPI server does not auto-start after a reboot.** Web interface →
  Development → SCPI server → Run. Port 5000. **Restarting it is Kevin's job,
  by his request.**
- **Key-based SSH is installed** on the control PC (a new key was generated
  during the 2026-08-28 rebuild), so the deep-capture helper needs no human.
- If the Ethernet link ever dies again, put the board on a **switch** rather
  than a direct cable — that also ends the link-local address churn. See Q28.

## SCPI transport behaviour — three traps, all silent

1. **Unsupported commands return zero bytes.** There is no error string. A
   misspelled *query* blocks until timeout; a misspelled *setting* command is
   completely silent and indistinguishable from success. **Every write path
   must be validated by reading back**, which is how H1.5 was run.
2. **A read timeout desynchronises the connection permanently.** The unread
   remainder stays in the socket and every later response is off by one, which
   presents as plausible-but-wrong values rather than as an error. Observed
   exactly this: `ACQ:AXI:SIZE?` appearing to return the region *base*. Use
   `*IDN?` as a sync token after anything suspicious.
3. **One persistent connection, always.** Opening a connection per command
   wedges the server. The symptom is not an error — it is multi-second latency
   and truncated responses.

### A wedged SCPI server looks like a broken cable

Worth knowing because the symptom is thoroughly misleading, and it cost a
session.

Twenty identical `ACQ:DEC?` queries over one warm connection gave min 0.078 s,
**median 5.4 s, max 21.9 s**, with the multi-second values clustering near TCP
retransmission backoff sums. That looks exactly like a failing cable, and the
adapter's 11546 historical receive errors made it look more so. It was neither:
a probe had opened ten connections in quick succession — the thing
`tests/hardware/conftest.py` had already warned about — and wedged the server.
Restarting it gave min 0.046 s, **median 0.050 s**, max 0.052 s.

**~50 ms is the healthy round trip** for a trivial query. That is the SCPI
server's own processing, not the network, so any polling loop in `hardware.py`
runs at roughly 20 iterations per second. Budget accordingly.

---

## The arbitrary generator is a DDS

**This is the single most consequential thing to understand about the board,
and this document got it wrong twice.** The full derivation, the measurements
and both wrong models are in `03-frequency-plan.md`. In brief:

```
output frequency = cycles written into the table x play rate
```

`SOUR<n>:FREQ:FIX` is the **play rate** — how many times per second the table
is traversed — not a per-sample clock. The DAC runs at a fixed 250 MS/s and the
table is decimated on the fly, so the index advances by
`16384 x play_rate / 250e6` entries per DAC clock.

Consequences that bite:

- **The play rate is quantised to 1 Hz**, so a modulation must be a whole
  number of hertz to have an exact table. That is the only remaining grid.
- **The play rate clamps at 100 MHz.** Ask for 130 or 200 and it reports 100.
- **The output must stay under 125 MHz** or it folds. Measured: 200 cycles at
  1 MHz came back at 50.003 MHz, 260 cycles at 9.995 MHz — exactly where a
  250 MS/s sampler puts them.
- **A short buffer is not ignored.** The board treats what you write as the
  whole table, so the frequency scales as `16384/N`.
- **Never hand-roll a frequency.** Use `plan_exact_am()` / `make_am_table()`.

Amplitude falls off steeply with frequency — 1793 counts at 1 MHz, 844 at
60 MHz, **135 at 80 MHz**, 27 at 100 MHz. That is the analog path, not the
generator, and it is why the drive cannot be pushed into the amplifier's
damage rating even at full scale.

**`SOUR<n>:VOLT X` commands X volts PEAK-TO-PEAK.** Measured 2026-09-03 with a
scope on OUT1: a commanded 0.200 V read 70 mV RMS, which is 99 mV amplitude.
The bench's lock-in trace read 100 mV on the same signal, agreeing to 1%. See
`06-results.md` for what that settles and what it leaves open.

---

## Front end: coupling and gain are PER CHANNEL

```python
rp.setup_acquisition(decimation=8, coupling="AC", gain="LV")   # both channels
rp.setup_channel(2, gain="HV")                                 # then IN2 alone
```

The order matters — `setup_acquisition` sets both, `setup_channel` overrides
one afterwards.

**This is not a nicety.** The real experiment needs IN1 on LV for the detector
and IN2 on HV for the laser's 3.3 V trigger. An earlier single-pair version
forced both to one setting after every reset, putting IN2 back on LV where a
3.3 V trigger clips into a flat line. **That does not present as a range
error. It presents as "the laser is not triggering"**, and would have sent
somebody to check the BNC.

### `ACQ:RST` resets more than it looks like

Measured: it resets gain to **LV**, coupling to **DC**, `ACQ:DEC` to **1**,
`ACQ:DATA:FORMAT` to **ASCII** and units to **VOLTS**.

`acquire_deep_fast` and `acquire_deep_2ch` both issue it, so anything
`setup_acquisition` applied is discarded. For LV/DC work that is harmless,
because LV/DC is what the reset lands on; it would silently ruin an HV or
AC-coupled deep capture — succeeding, and wrong by 20×. `_reapply_front_end()`
remembers and restores, per channel.

### The units setting is a trap

`ACQ:DATA:Units` defaults to `VOLTS` while `query_binary_int16()` decodes
big-endian int16. In `VOLTS` the board returns floats, so reinterpreting them
as int16 gives the correct sample *count* and plausible magnitudes while being
complete nonsense. `ACQ:DATA:Units RAW` does take effect (confirmed by
readback), so the code is right — but any change here must keep format and
units consistent.

### Captures return RAW COUNTS, never volts

`acquire()`, `acquire_deep()` and `acquire_deep_fast()` all return raw ADC
counts. Nothing in the capture path scales them, deliberately: `hardware.py`
stays clear of the maths. **Anything comparing a capture against a physical
specification has to convert, and forgetting to is not obvious** — a trigger
reported as "302 V" was the P2 failure on 2026-08-28, when it was 302 counts on
the HV range, i.e. 3.32 V and exactly on spec.

| | |
|---|---|
| `ADC_COUNTS_PER_V_LV` | **1817.7** |
| `ADC_COUNTS_PER_V_HV` | 1817.7 / 20 = 90.9 |
| Clipping | ±2047 / −2048. A clipped sine still demodulates to a clean-looking number |

### The fast-read path's little-endian decode is proven

`fast_read()` decodes little-endian while `query_binary_int16()` decodes
big-endian. This was flagged "not yet proven" for a while, and the way it was
proven matters: **a byte-swapped noise record still looks like noise**, just
with the wrong amplitude, so a waveform test proves less than you would think.
The check is to compare the deep record's raw σ against a plain `acquire()` on
the same quiet input — 0.6797 against 0.6781 counts, a ratio of 1.002, where a
byte swap would be off by ~100×. **Re-check it that way after any change.**

---

## Memory: the part that is easy to get wrong

The board has **1 GB**, but the kernel command line carries `mem=512M`, so
Linux confines itself to the lower half.

| Range | Size | Owner |
|---|---:|---|
| `0x00000000`–`0x1FFFFFFF` | 512 MiB | Linux — **and the capture buffer is in here too** |
| `0x20000000`–`0x3FFFFFFF` | 512 MiB | unused |

**Do not diagnose installed RAM from `/proc/iomem` or `MemTotal`.** Both show
the capped view and will convincingly tell you this is a 512 MB board. An
earlier revision of this document did exactly that and concluded the 1 s
capture was impossible. The honest source is `/proc/device-tree/memory/reg`,
which reads base 0, size `0x40000000`.

**As it stands on the bench board:** `buffer@1000000`, base `0x01000000`, size
`0x08000000` — **128 MiB**, carved out of Linux's own half by the 2026-08-12
device-tree edit. That took the memory from the OS: `MemTotal` fell from
470932 kB to **341908 kB**, with ~141 MB available. It is very likely why
`rp_fastread.py` was OOM-killed on a 50 MB request; the 1 MB chunking fix
addressed the symptom.

### Do NOT move or enlarge the region

**The move to the upper half was considered and rejected, and the decision
should not be reopened.** It existed to buy decimation 2, and decimation 2 was
only wanted because the wavelength axis used to be derived from trigger
intervals. It no longer is — the laser reports its own wavelength. The
operating point is **decimation 8**, which costs 1.1 dB and fits a full 1 s
two-channel capture in the existing region.

`describe_capture_plan()` recommended the move for eleven days because
`recommend()` bounded by `MAX_DMA_MB` — the hypothetical enlarged region —
instead of `DMA_REGION_MB`, which is what exists. Fixed 2026-08-26.
`tests/test_planning.py` now asserts the recommendation and that the output
contains **no device-tree instructions**.

The procedure is kept below only in case some future design needs it.

```bash
ssh root@rp-fffe42.local
mount -o remount,rw /                       # `rw` is an interactive-shell
                                            # alias and does not exist in a
                                            # one-shot ssh host "..." command
cp /opt/redpitaya/dts/$(monitor -f)/dtraw.dts ~/dtraw.dts.backup
# buffer@20000000 { reg = <0x20000000 0x20000000>; };   base 512 MB, size 512 MB
cd /opt/redpitaya/dts/$(monitor -f)/
dtc -I dts -O dtb ./dtraw.dts -o devicetree.dtb
reboot
```

**Do it in two steps, not one.** Nobody has shown the FPGA can DMA to
`0x20000000`. Move the region up but keep it at 128 MB first and confirm a
quiet-input capture still returns σ ≈ 0.68 counts; only then enlarge. A region
that reports the right size and returns plausible garbage is this project's
signature failure, and "cannot reach the upper half" and "region too big" are
indistinguishable if you change both at once.

**Recovery is easy.** `/dev/mmcblk0p1` is **vfat**, mounted at both `/boot` and
`/opt/redpitaya`, so the device tree sits on the FAT partition — pull the SD
card, open it on any Windows machine, copy the backup back. No ext4 tooling.
(An earlier note claiming recovery "requires an ext4 reader" overstated the
risk considerably.)

**The instruction this replaces was unsafe.** It read
`buffer@1000000 { reg = <0x1000000 0x20000000>; }` — a 512 MB region based at
the 16 MB mark, running through the memory Linux is running in.

**The root filesystem is currently mounted read-write** (`/dev/root / ext4
rw,relatime,errors=remount-ro`), apparently left that way by the device-tree
edit. That is why the documented `rw` step looks unnecessary. A permanently
writable root on an SD card is a mild corruption risk on power loss; worth
putting back with `mount -o remount,ro /` if the device-tree work is ever
finished.

### Memory and transfer budget, 1 s sweep, 2 channels

**Quote sizes in the same unit.** `ACQ:AXI:SIZE?` and the device tree both use
MiB. 1 s × 2 ch at decimation 2 is exactly 500,000,000 bytes = 476.8 MiB; the
region is 134,217,728 bytes = 128 MiB exactly. Mixing MB and MiB across the two
makes the comparison look wrong.

| Decimation | Rate | Nyquist | 1 s, 2 ch | Fits 128 MiB? | Aliasing |
|---:|---:|---:|---:|:---:|---|
| 1 | 250 MS/s | 125 MHz | 954 MB | no | none |
| 2 | 125 MS/s | 62.5 MHz | 477 MB | no | none |
| 4 | 62.5 MS/s | 31.2 MHz | 238 MB | no | 31–60 MHz folds |
| **8** | **31.2 MS/s** | **15.6 MHz** | **119.2 MiB** | **yes, 93%** | 15.6–60 MHz folds |
| 16 | 15.6 MS/s | 7.8 MHz | 60 MB | yes | more |

43 ms of pre-roll adds ~5 MiB, giving ~124 MiB — 97% full. The margin is thin
and deliberate.

**The folding penalty is small here** because nothing in this measurement has
high-frequency content to fold: the photodetector returns only the ~1 MHz
response, so only *noise* folds, not signal — and the board applies its own
anti-alias filter when decimating. Measured cost of decimation 8 is **1.1 dB**
(`06-results.md`).

**Decimation 2 is right for the real measurement but wrong for loopback tests
that look at the carrier**, and that is not a contradiction: at 62.5 MHz
Nyquist an 80 MHz carrier aliases to 45 MHz, and it will look entirely
plausible. Use decimation 1 there. In the real experiment the 80 MHz never
reaches an input at all.

---

## Deep captures need a helper running on the board

`scripts/rp_fastread.py` **runs ON THE BOARD** — the one deliberate exception
to "everything runs on the control PC". It lives in `/dev/shm`, which is RAM,
so **it disappears on every reboot** and these two commands are the routine:

```bash
scp scripts/rp_fastread.py root@rp-fffe42.local:/dev/shm/
ssh -n root@rp-fffe42.local "nohup setsid python3 /dev/shm/rp_fastread.py > /dev/shm/rp_fastread.log 2>&1 < /dev/null &"
```

`setsid` and the redirects matter: without them the helper dies when the SSH
session closes, **which looks identical to "the helper was never started"**.
Confirm with `RedPitaya.fast_read_available()` (the bench prints it on
Connect), and read `/dev/shm/rp_fastread.log` if it says False. Stop it
cleanly by sending `QUIT` to port 9999.

---

## SCPI commands used by `hardware.py`

All verified against OS 2.00 in H1.5.

| Purpose | Command |
|---|---|
| Identify | `*IDN?` |
| Arbitrary waveform | `SOUR<n>:FUNC ARBITRARY`, `SOUR<n>:TRAC:DATA:DATA <v,...>` |
| Play rate / amplitude | `SOUR<n>:FREQ:FIX`, `SOUR<n>:VOLT` (peak-to-peak) |
| Output enable | `OUTPUT<n>:STATE ON`, `SOUR<n>:TRig:INT` |
| Acquisition setup | `ACQ:RST`, `ACQ:DEC`, `ACQ:SOUR<n>:COUP`, `ACQ:SOUR<n>:GAIN` |
| Data format | `ACQ:DATA:FORMAT BIN`, `ACQ:DATA:Units RAW` |
| Deep memory | `ACQ:AXI:START?`, `ACQ:AXI:SIZE?`, `ACQ:AXI:DEC` |
| | `ACQ:AXI:SOUR<n>:SET:Buffer <addr>,<size>` |
| | `ACQ:AXI:SOUR<n>:ENable ON` |
| | `ACQ:AXI:SOUR<n>:Trig:Dly <n>` |
| | `ACQ:AXI:SOUR<n>:Trig:Pos?`, `ACQ:AXI:SOUR<n>:TRIG:FILL?` |
| | `ACQ:AXI:SOUR<n>:DATA:Start:N? <pos>,<size>` |

### What is NOT available

| | |
|---|---|
| **Deep Memory Generation** | **Does not exist on this OS.** All nine candidate spellings return zero bytes, and sending a 32768-entry table **closes the SCPI connection outright**. The generator's unique-waveform ceiling is 16384 samples = 65.536 µs, permanently (H5.1) |
| **A settable ASG table size** | `SOUR:TRAC:DATA:LEN?`, `:LENGTH?`, `SOUR:ARB:LEN?`, `SOUR:BUFF:SIZE?`, `SOUR:TRAC:DATA:SIZE?` all return zero bytes. It no longer matters — see `03-frequency-plan.md` |
| **`acquire_deep_2ch`'s read** | Arming is fine; the SCPI read returns garbage. **Use `acquire_deep_fast`** |

---

## Safety on the board

- **Never exceed the board's own specifications.** The output range is
  software-selectable; do not command amplitudes outside it.
- **Leave outputs off when you finish.** `tests/hardware/conftest.py` enforces
  this with an autouse fixture and `RedPitaya.close()` disarms both outputs —
  keep both. H7.4 failed on exactly this and was fixed.
- **Nothing drives an output without a typed confirmation.** The P-series
  scripts require `--i-am-present` *and* a typed answer; the bench requires a
  dialog naming the channel, frequencies and amplitude. A flag alone is too
  easy to leave in a shell history, and EOF is not consent. **Match that
  contract in anything new.**
- **Do not restart the SCPI server.** That is Kevin's, by request.

Safety for the optical and RF chain is in `05-instruments.md`.
