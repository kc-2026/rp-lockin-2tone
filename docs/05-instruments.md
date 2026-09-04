# 05 — Instrument reference: lasers, detectors, RF chain

**What this is:** how everything that is *not* the Red Pitaya behaves. The
board itself is `04-board-reference.md`; measured numbers are in
`06-results.md`; what is physically plugged in right now is
`08-the-bench.md`.

---

# 1. The santec lasers — TSL-770 and TSL-775

There are **two**, and this was only established on 2026-08-25. Anything
written before that date describing "the laser" means the TSL-775.

| | Role |
|---|---|
| **TSL-775 — the fine sweeper** | Sweeps ~100 nm in ~1 s, 5001 logged points, **carries the trigger BNC into IN2**, and supplies the wavelength axis from its own log. This is the one that works |
| **TSL-770 — the stepper** | Sits at 11 discrete wavelengths, one per sweep. No trigger, no log — set it, let it settle, read `:WAVelength?`. **Never contacted.** Parked at Kevin's request |

**Naming collision, and it will cause a bug if it is not watched.** This
project's **f1/f2** are the AOM *modulation* frequencies, in megahertz. Kevin's
**freq1/freq2** are the *lasers*, in terahertz. Same names, nine orders of
magnitude apart.

## 1.1 USB does not work, and never will

**USB is a hardware fault inside the instrument.** Not a driver problem, not
fixable on the host, and not worth another minute. Established 2026-08-21,
re-confirmed on the rebuilt control PC 2026-08-28.

The evidence, recorded so nobody re-debugs it. The FT232H bridge enumerates
correctly and the PC→chip half is provably healthy, but the instrument never
replies — across **9 baud rates × 3 terminators**, D2XX as UART, D2XX async and
synchronous 245 FIFO, santec's own init sequence replicated byte for byte, a
full power cycle, and a 3 s passive listen. The **identical commands with the
identical CR delimiter work perfectly over LAN**. The fault is between the
FT232H and the internal controller. It is a warranty item for santec.

**Windows will show `CM_PROB_FAILED_INSTALL` on the USB node
(`FTDIBUS\VID_2428+PID_0116+2601S967A\0000`). Ignore it.** This unit's EEPROM
sets `IsVCP=0`, so a COM port is the wrong end state anyway. That driver state
was once called "the most concrete lead this blocker has ever had". It was a
red herring and chasing it cost real time.

**Keep the USB cable plugged in.** The FT232H is self-powered from the
instrument, so its presence in Device Manager is the fastest proof the laser
has power — which separates "network problem" from "someone turned it off".

The `d2xx` and `vcp` backends in `scripts/tsl775.py` are retained for
diagnostics only.

## 1.2 LAN is the working path

```
10.101.0.197 : 5000     raw TCP, ASCII, bare CR delimiter
```

**Open one connection and hold it for the whole session.** Roughly one
reconnect in four dies with `WinError 10054`, while a single held session went
20/20.

**A connection attempt is a consumable (Q33).** Measured 2026-09-01: port 10001
went from accepting to silently dropping SYNs after **exactly two**
connect-and-close cycles, with nothing else on the network talking to the
instrument, while every closed port on the same host kept answering RST
normally — so it is not a firewall. Port 5000 was already in that state. A
front-panel LAN reset did **not** recover it; a power cycle with the control PC
quiet did. **Never retry a failed connect. Power cycle instead. Do not run two
benches.**

**The LAN interface drops out entirely, and this recurs.** Symptom: no ping, no
TCP, while the instrument is plainly powered. Recovery is to reapply the LAN
settings on the front panel (Other → Communication → LAN); it has worked in one
go every time. Two dropouts occurred in one afternoon on 2026-08-28, both after
sustained activity including 40 KB and 20 KB binary log reads — **two data
points for the theory that the bulk log reads provoke it, and the open question
of whether pacing them would fix it.**

One triage note: the "no ARP entry" indicator inherited from the original
bring-up notes is **vacuous in this topology**, because the laser is off-subnet
and routed, so it would never have an ARP entry either way.

## 1.3 The delimiter is a trap

The Red Pitaya's SCPI uses **CRLF**; the santec uses **CR alone**. A transport
written for one will hang waiting on the other, and the symptom is a timeout
that looks like a dead cable. Do not reuse `hardware.py`'s line reader
unchanged.

Two command sets exist, selectable on the front panel (Other → Communication)
or via `:SYSTem:COMMunicate:CODe`. Both accept the same mnemonics; only
response *formatting* differs — legacy gives plain decimal nm, SCPI gives
exponential SI metres. **They also differ in the binary logging format**, which
matters much more:

| Command set | Log payload | Units |
|---|---|---|
| Legacy (TSL-550 compatible) | 4-byte signed integers | 0.1 pm |
| Native (TSL-770/775 SCPI) | 8-byte IEEE-754 doubles | metres |

**Both are little-endian** ("Intel byte order"). Note this is the **opposite**
of the Red Pitaya's SCPI path, which is big-endian — the same trap in a second
instrument. Reading `:READout:POINts?` and checking the byte count against the
block header is the cheap way to tell which set is active.

## 1.4 Two drivers, and they are not duplicates (Q35)

| | |
|---|---|
| `scripts/tsl775.py` — **`TSL775`** | **Proven against the instrument.** Write/query only, three backends (`lan`, `d2xx`, `vcp`). Configures and runs sweeps, reads both logs. **This is what the bench uses.** Vendored into the repo 2026-08-28 from a separate bring-up effort |
| `src/rp_lockin/santec.py` — **`SantecTSL`** | Written from the manuals, **never exercised against the instrument**. Reads the log, reads and sets the trigger mode, reports sweep state. Has **no** sweep span/speed/mode setters and **cannot start a sweep**. This is what `pipeline.py` assumes |

They should converge. Writing bench operations against the wrong one shipped a
bug on 2026-09-01 that the suite could not catch, because the test fake had
been modelled on the wrong one too.

`santec.py` contains one command string that is **inferred rather than quoted**
from the manuals (`set_wavelength_m`, whose SET form is not in the tables).
That is only safe because it verifies itself by read-back, and the module says
so. **Do not extend that pattern to a command whose effect cannot be read
back** — a misspelled command returns zero bytes exactly like a correct one.

**A serial read that times out desynchronises `santec.py` permanently** — every
later query returns the tail of the previous reply, plausibly and without
raising. Call `resync()`; it is read-only and safe any time.

## 1.5 Configuring a sweep — the order matters

This is the working order, and it is what `ops.configure_sweep` implements.

```
:POW:STAT 1                     laser ON first, always; wait ~2 s, verify
:WAV:SWE 0                      explicit stop before configuring
:WAV:SWE:SPE  <nm/s>            SPEED FIRST -- the legal range depends on it
:WAV:SWE:STAR <metres>          exponential SI, e.g. 1.500000000E-006
:WAV:SWE:STOP <metres>
:WAV:SWE:MOD  <mode>            1 = continuous one-way
:WAV:SWE:CYCL <n>
:TRIG:OUTP 3                    3 = Step. MANDATORY -- 0 gives no train and
                                an empty log
:TRIG:OUTP:STEP <metres>
```

**Write seven settings, verify seven.** `configure_sweep` used to verify one
and sleep a fixed 0.5 s; a sweep then silently reverted to step mode between
run 1 and run 2 and ran ~2000× slow. It now polls `:WAV:SWE?` and reads every
setting back. **The laser accepts writes it is not in a state to honour and
reports nothing.**

**Two-way mode is a trap.** The return pass overwrites the log, so the run
comes back with only the descending half.

**Wait between Configure and Start.** The laser must travel back to its start
wavelength on its own. Start early and it sweeps a *shorter range* at exactly
the right speed and step — measured, 80.96 nm of a requested 100 — so the trace
looks entirely normal. **Driving it there with `:WAV` is NOT a fix (Q32):** it
succeeded (1600 → 1500 nm in 0.41 s, read back on target) and then `:WAV:SWE 1`
produced no trigger train at all, twice. The change that did this was reverted
(`61088d0`).

**Check the configuration on arrival, not just on departure.** On 2026-08-28
the instrument's settings had drifted off the validated ones, and three of the
differences fail silently: `:TRIG:OUTP` was 0, `:WAV:SWE:MOD` was 3 (two-way),
and the speed/step pair gave a 10 Hz trigger where the board expects 5 kHz.

Legal sweep speeds are discrete (manual p.87): 0.5, 1, 2, 5, 10, 20, 50, 100,
200 nm/s. `ops.SWEEP_SPEEDS_NM_S` is that list, which is why the bench offers a
dropdown rather than a text box.

## 1.6 Reading the wavelength log

| Command | Does |
|---|---|
| `:READout:POINts?` | number of logged points, 0 to 500,000 |
| `:READout:DATa?` | the wavelength log |
| `:READout:DATa:POWer?` | the power log, dBm — a free cross-check |

Both data responses are IEEE 488.2 definite-length blocks — the same `#4nnnn`
header the Red Pitaya uses.

**The log carries wavelength values; the time axis is IMPLICIT.**
`:READout:DATa?` returns a bare array, so `wavelength[i]` belongs to logged
point `i`. No time column is transmitted. With the trigger stepping in time
that *is* wavelength against relative time from the first trigger — the times
are reconstructed as `first_edge + i × step`, not read. How that reconstruction
is done, and why it is done that way, is `07-pipeline.md`.

**It reads AFTER the sweep, not during.** `:READout:DATa?` dumps a completed
log, so the driver runs after the capture rather than alongside it.

**The internal power monitor sits BEFORE the shutter**, so the power log reads
correctly (3.983–4.027 dBm measured) even with the shutter closed and no light
emitted at all. Useful, and a trap if you take a healthy power log as evidence
that light came out.

## 1.7 The trigger output

| Command | Values |
|---|---|
| `:TRIGger:OUTPut` | 0 None, 1 Stop, 2 Start, **3 Step** |
| `:TRIGger:OUTPut:ACTive` | 0 rising, 1 falling |
| `:TRIGger:OUTPut:STEP[:WIDTh]` | step size, 0.1 pm resolution |
| `:TRIGger:OUTPut:SETTing` | wavelength-periodic or time-periodic — see below |

Electrical spec, TSL-775 manual p46 §6.5:

| | |
|---|---|
| Levels | **3.3 V high, 0 V low** |
| **Pulse width** | **25 µs** (measured 24.997 µs, sd 0.001) |
| Max repetition rate | 20 kHz, so pulses are ≥50 µs apart |
| Minimum trigger step | 0.1 pm at 0.5–2 nm/s, rising to 10 pm at 200 nm/s |

**Three consequences that settle arguments this project has had:**

1. **3.3 V will not fit the ±1 V range.** IN2 must be on **HV**. On LV it
   clips to a flat line, which reads as "the laser is not triggering".
2. **The missed-edge worry is dead on the real signal.** A 25 µs pulse is
   **780 samples at decimation 8**, with pulses ≥1560 samples apart. Every
   anxiety about losing edges came from a synthetic 20 ns pattern that was an
   artefact of the ASG's 4 ns table step. Decimation 8 is comfortably adequate.
3. **Every logged point makes TWO edges** — one rising, one falling 25 µs
   later. `find_trigger_edges` defaults to `polarity="both"`, so anything
   deriving a step or counting pulses **must pass `polarity="rising"`** or it
   reads half the step and compresses the whole wavelength axis 2× while still
   drawing a clean trace.

**Also worth a deliberate decision:** mode **2 (Start)** emits a single pulse at
sweep start, which is all the alignment strictly needs and removes the miscount
risk entirely. Mode **3 (Step)** gives the train, which is what lets the
recorded edges carry the index pairing, the measured time axis and the free
clock-ratio check. The bench uses 3.

### `:TRIGger:OUTPut:SETTing` — answered, after a documentation conflict

The two manuals define it with **opposite encodings**:

| | 0 | 1 |
|---|---|---|
| TSL-775 manual, p100 | periodic in **wavelength** | periodic in **time** |
| TSL-770 manual, p99 | periodic in **time** | periodic in **wavelength** |

**ANSWERED on the bench 2026-08-28 (Q24): on the TSL-775, 0 = periodic in
WAVELENGTH.** The readback alone cannot settle it — a 0 is a 0 under either
manual — but the sweep runs at 0 and produces sub-picometre-linear points at
exactly 0.02 nm spacing, which is only consistent with that encoding. **The
TSL-775 manual is right; the TSL-770's table is the erroneous one.**

It matters less than was feared: at constant sweep speed, uniform-in-wavelength
is also uniform-in-time. But **the sweep speed is not perfectly constant** — it
ripples ±11% with a 0.41 nm period — which is why the wavelength axis is built
from the **measured** edge times rather than a uniform grid. See Q29 and
`07-pipeline.md`.

## 1.8 Optical power

**Keep the laser under 1 mW (0 dBm).** Below the PDA05CF2's ~0.96 mW
saturation, and therefore comfortably below damage. Enforced as `--max-dbm` in
the P-series scripts.

**The gate is POWER, not the shutter** (Kevin, 2026-08-28). Fibre and connector
loss only widen the margin: the limit is the setpoint at the laser, not the
power arriving at the detector.

**Found at 12.00 dBm ≈ 15.8 mW on 2026-08-28** — roughly 16× the detector's
saturation — against the August-validated 4.00 dBm, with the detector already
connected. Set back before anything was enabled. **Read the setpoint before
opening the shutter, every time.**

The range is −5 to +13 dBm, which is an 18 dB lever arm — useful, because
power scaling is how a P² nonlinearity is separated from a P¹ background.

---

# 2. Detectors

## 2.1 What is actually on IN1 right now

**A Thorlabs APD410-series avalanche detector**, on its minimum gain setting
(Kevin, 2026-09-03). `scripts/dr_bench.py` exists to characterise its gain
knob — see `06-results.md`.

**Confirm the model suffix from the label before relying on any spectral
claim.** The APD410A is **InGaAs** (roughly 900–1700 nm) and the APD410A2 is
**silicon** (roughly 200–1000 nm), and the difference decides whether it can
see 1550 nm, 775 nm, or both. That distinction is load-bearing for the SHG plan
in `09-whats-next.md`, where the whole point of a silicon detector is that it
cannot see the fundamental.

Figures recorded during the 2026-09-03 dynamic-range work, from the datasheet:
bandwidth **DC–10 MHz**, transimpedance up to **26.5 × 10⁶ V/A** into 50 Ω,
avalanche gain **M = 10–100**, CW saturation around **1.5 µW at M = 10**. Treat
these as working numbers, not as verified specification.

**Nothing reads the detector's gain over any interface.** In `dr_bench.py` the
gain box is a **label** — whatever the knob says — and it only has to be a
number and to mean the same thing at every point, because it becomes the x
axis.

## 2.2 Thorlabs PDA05CF2 — InGaAs, the original detector

Recorded 2026-08-14 from the Thorlabs manual (Rev B, 3 January 2018).

| | |
|---|---|
| Detector | InGaAs, Ø0.5 mm active area |
| Wavelength range | 800–1700 nm — covers a 1520–1570 nm sweep comfortably |
| Peak response | 1.04 A/W at 1590 nm |
| **Small-signal bandwidth** | **150 MHz** |
| NEP at peak | 1.26 × 10⁻¹¹ W/√Hz |
| Output noise | 2 mV rms |
| Transimpedance gain | 5 × 10³ V/A into 50 Ω, **1 × 10⁴ V/A into Hi-Z** |
| Output voltage | 0 to 5 V into 50 Ω, **0 to 10 V into Hi-Z** |
| Dark offset | ±20 mV |
| Output | includes a **50 Ω series resistor**, forming a divider with the load |

**150 MHz closes U4 comfortably.** "Does the photodetector roll off at 1 MHz"
was a live risk to the entire measurement premise; 991.821 kHz sits four orders
of magnitude inside the passband.

**Two things about the output shape the whole input stage.**

*It is unipolar with a DC pedestal.* The output runs 0 to 10 V and the DC level
tracks average optical power; our signal is a small modulation riding on top.

*Into the Red Pitaya it behaves as Hi-Z, not 50 Ω.* The board's inputs are
1 MΩ, so the 50 Ω series resistor divides by 0.99995 — negligible — and the
detector delivers its **Hi-Z figures: 10⁴ V/A and up to 10 V**.

Ten volts against a ±1 V range needs **AC coupling**, and Q25 measured that as
free: the corner is **17.0 Hz**, single-pole, so attenuation at 991.821 kHz is
1.3 × 10⁻⁹ dB and the noise floor is unchanged. The alternative — the ±20 V
range — is a bad trade: σ there is 45 µV, four times the detector's own noise,
so the ADC would dominate a measurement it currently does not. The one thing AC
coupling costs is any DC reading of average optical power, and the laser's own
`:READout:DATa:POWer?` log can supply that.

**Saturation and damage.** Output saturates at 10 V = 1.00 mA of photocurrent,
about **0.96 mW** optical at peak responsivity. **No explicit optical damage
threshold is stated in the manual** — treat ~1 mW as the working ceiling and
ask Thorlabs or Kevin before exceeding it. This is still an open request to
Kevin.

**One electrical hazard, because it destroys the instrument:** do **not** add a
50 Ω terminator when the load is already 50 Ω. The combined 25 Ω allows
~135 mA and damages the output driver. With the Red Pitaya's 1 MΩ input this
does not arise — but it would if a scope is teed in alongside.

## 2.3 Thorlabs PDA100A2 — silicon, for the SHG product

On the bench, **not installed**. Silicon cannot see 1550 nm at all, which is
exactly why it is wanted: it never receives the AOM's own second-harmonic
confound (Q30). Bandwidth collapses as gain rises, so gain and detection
frequency are one decision — the table is in `06-results.md` and the ladder is
in `09-whats-next.md`.

Setting-up notes: **AC-couple IN1** (the output is DC coupled with ±6 mV
offset, and at 30 dB any room light rides straight into the ±1 V range);
**cap it when not measuring** (the window is 75.4 mm², and at 30 dB **42 µW
saturates the Red Pitaya's LV range** while 421 µW saturates the detector
itself — ambient light will exceed that); **no 50 Ω terminator**, it has a 50 Ω
series resistor already and the board's inputs are 1 MΩ, so use the Hi-Z gain
column.

---

# 3. The RF chain — ZHL-1-2W+ and 1550AOM-1

From the Mini-Circuits and Aerodiode datasheets, both read 2026-08-17.

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
| Wavelength | 1470–1630 nm (typ 1550) |
| **RF drive** | **2.5 W nominal**, 50 Ω, SMA |
| **Frequency** | **80 MHz** |
| Frequency shift | ±80 MHz |
| **Average optical handling** | **0.5 W** |
| Insertion loss | 2.0–3.0 dB (2.5 typ) |
| Extinction ratio | 50–55 dB |
| Rise time | 50 ns |

**One of each is connected. A second amplifier and second AOM exist and are not
wired** — that is what SFG needs.

## 3.1 RF drive level: leave it where Kevin tuned it. No attenuator.

**Three recommendations were made — 20 dB, then 10 dB, then 6 dB — and all
three were withdrawn.** The reasoning is recorded because the mistake is an
easy one to repeat. The full version is in `11-mistakes.md`; the short version:

**What Kevin did:** laser CW, unmodulated 80 MHz through the amplifier into the
AOM, tuned the Red Pitaya output until the diffracted light on a scope was at
maximum. Standard AOM tuning.

**Why that is right here.** The drive is **depth-1 AM** — H2.2 measured
sideband/carrier = 0.5, and sideband/carrier is m/2, so m = 1.0. **The RF
envelope goes all the way to zero on every cycle**, so the AOM is switched
fully on and off rather than held at a bias point with a small wiggle on top.
The envelope sweeps the entire diffraction curve each cycle, from dark to peak.
There is no operating point whose slope matters; what matters is how bright the
"on" end is, which is exactly what maximising CW diffraction finds.

| Envelope peak | η at peak | signal at f1 | signal at 2f1 |
|---:|---:|---:|---:|
| 0.50 × Pπ | 80% | 0.425 | 0.062 |
| 0.75 × | 96% | 0.523 | 0.041 |
| **1.00 × — Kevin's tuning** | **100%** | **0.567** | **0.000** |
| 1.25 × | 97% | 0.570 | 0.055 |
| 1.50 × | 88% | 0.545 | 0.116 |

**99.4% of the theoretical best, and zero frequency doubling.** The 2f1 term
appears only when the envelope *overshoots* the peak, so the light dips at the
top of every cycle. Kevin's setting is precisely the point where the envelope
touches the peak and turns around — the one place that cannot happen.

**What still holds regardless:**

- **No attenuator is needed for protection.** The amplifier sees −4 dBm against
  a +10 dBm rating: 14 dB of margin, and the board's 14 dB rolloff at 80 MHz
  means it cannot get closer. The only scenario needing a pad is somebody
  running this below the rolloff, where the board *can* reach +10 dBm. **And
  the margin is 6 dB better than that arithmetic assumed**, because
  `SOUR:VOLT X` is peak-to-peak (`04-board-reference.md`).
- **The one-tone control (P5.1) still matters, whatever the drive level.**
  Drive f1 alone and look for anything at |f2 − f1|. That is what tests whether
  the amplifiers or the detector manufacture a false signal.
- **The board's 14 dB rolloff at 80 MHz answers U1.** If drive ever falls
  short, commanding a bigger number will not help — the board is already
  clamping.

## 3.2 Two ordering rules that damage things if ignored

**Connect the AOM before applying RF.** From the amplifier datasheet: "Open
load is not recommended, potentially can cause damage. With no load, derate max
input power by 20 dB." Never power the amplifier into an open port.

**The 12 mW laser is not a risk to the AOM** — 0.5 W rating is a 42× margin.
The optical constraint is entirely at the far end, where the detector
saturates.
