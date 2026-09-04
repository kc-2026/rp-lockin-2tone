# rp-lockin-2tone

Lock-in detection of a nonlinear optical signal against laser wavelength, on a
Red Pitaya SIGNALlab 250-12.

**Repository:** <https://github.com/kc-2026/rp-lockin-2tone>
**Lives at:** `C:\dev\rp-lockin-2tone` on the bench PC.

**This file is how to USE it.** The reasoning, the reference material and every
measured number are in `docs/` — start at `docs/00-index.md`. The current state
of the work is the HANDOFF block at the top of `SESSION_LOG.md`.

---

## What it does, in one paragraph

An AOM gates 1550 nm laser light on and off at f1 (default **915 kHz**), by
amplitude-modulating the 80 MHz acoustic drive the AOM needs. **The 80 MHz is
the AOM's requirement — the sample only ever sees light varying in
brightness.** A photodetector on IN1 returns the response; the laser's trigger
output on IN2 says where in the record each logged wavelength sits. One laser
sweep is captured, demodulated in software, and delivered as a 5000-point trace
of amplitude against wavelength, as CSV.

---

## 1. Install

Needs **Python ≥ 3.10** (3.13 is what the bench PC runs). Everything else comes
from the venv.

```bash
git clone https://github.com/kc-2026/rp-lockin-2tone.git C:\dev\rp-lockin-2tone
cd C:\dev\rp-lockin-2tone
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
```

On Linux the last line is `.venv/bin/python -m pip install -e ".[dev]"`.

Check it:

```bash
.venv\Scripts\python -m pytest -q
```

Expect **450 passed, 2 skipped, 11 deselected**, in about four minutes. The
deselected ones need the board.

Optional extras: `.[laser]` adds `pyserial`, `.[laser-d2xx]` adds the D2XX probe
used by `scripts/laser_comms_diag.py`, `.[plot]` adds matplotlib. **None of
them are needed for the bench**, which talks to the laser over TCP and draws on
a Tk canvas.

### Two rules about where you run it from

- **Do not put the project in a OneDrive folder.** OneDrive scanning a `.venv`
  is slow, and a nested-repo incident started that way.
- **Do not run from a copy on the Desktop.** A snapshot at
  `Desktop\rp-lockin-2tone-main` has no `.venv` and falls further behind every
  commit. Starting the GUI from it fails with `ModuleNotFoundError: No module
  named 'numpy'`, which names the interpreter but not the real problem, which
  is the folder.

---

## 2. Before you connect anything

| | |
|---|---|
| **Power the board** and start its SCPI server | Web interface → Development → SCPI server → **Run**. Port 5000. **It does not auto-start after a reboot.** Do not restart it yourself if it is already running — that is Kevin's, by request |
| **Start the deep-capture helper** | Two commands, below. It lives in RAM and **dies on every board reboot** |
| **Power the laser** and check its LAN | `10.101.0.197:5000`. If it does not answer, reapply the LAN settings on the front panel: Other → Communication → LAN |
| **Check the laser's power setpoint** | It has been found at 12 dBm ≈ 15.8 mW. **Keep it at or under 0 dBm (1 mW)** — the detector saturates near 0.96 mW |
| **Connect the AOM before applying RF** | The amplifier is not to be powered into an open port |

The deep-capture helper:

```bash
scp scripts/rp_fastread.py root@rp-fffe42.local:/dev/shm/
ssh -n root@rp-fffe42.local "nohup setsid python3 /dev/shm/rp_fastread.py > /dev/shm/rp_fastread.log 2>&1 < /dev/null &"
```

`setsid` and the redirects matter — without them it dies when the SSH session
closes, which looks exactly like never having started it. The bench prints
`fast-read helper running` or `NOT RUNNING` when you press Connect; if it says
NOT RUNNING, read `/dev/shm/rp_fastread.log`.

---

## 3. Start the bench

```bash
run_bench.cmd
```

Double-clickable. Or, from a terminal:

```bash
.venv\Scripts\python.exe scripts\bench.py
```

There are three programs. **`bench.py` is the one you want.**

| Program | Command | For |
|---|---|---|
| **The bench** | `run_bench.cmd` | **Everything.** Panel GUI; each panel does one thing, and a sweep is those things in order |
| Gain study | `run_dr.cmd` | Characterising the detector's gain knob against dynamic range. A one-off tool |
| Old tabbed GUI | `run_gui.cmd` | Kept only because it has a **Simulate** path that needs no hardware at all |

---

## 4. Using the bench

The window is a **rail of panels down the left**, a **plot**, a **workspace**
and a **log**. Panels are independent: they read and write four named slots —
`capture`, `laser log`, `lock-in`, `trace` — rather than calling each other. So
you can arm a capture, fire a sweep by hand, read the log ten minutes later,
and demodulate the same record three times at different frequencies without
touching hardware.

The **header** always shows measured state (board, OUT1/OUT2, laser wavelength
and power, LD, shutter, sweep) and an **ALL OUTPUTS OFF** button. State is
polled from the instruments, never remembered from which buttons you pressed.

### The panels

**Board** — `host`, `IN1` and `IN2` coupling/gain, `Connect` / `Disconnect` /
`Configure`.
IN1 defaults to **LV / AC** (the detector is unipolar with a DC pedestal); IN2
to **HV / DC** (the 3.3 V trigger clips to a flat line on LV, which reads as
"the laser is not triggering"). Press **Configure** after Connect; it also
applies the decimation from the Acquire panel.

**Laser** — `address`, `power` (dBm), `wavelength` (nm), then `Connect`,
`Disconnect`, `Configure`, `Read back`, `Shutter CLOSE`/`OPEN`, `LD ON`/`off`.
`Configure` sets wavelength and power together and reads both back.
**Setting a wavelength stops the laser sweeping** until Sweep → Configure is
pressed again (Q32) — the panel says so in orange.

**Drive (OUT1) — f1** and **Drive (OUT2) — f2, for SFG** — `carrier` (MHz),
`modulation` (kHz), `amplitude` (V), then `OUTn ON` / `OUTn OFF` / `ALL OFF`.
A line under the boxes says what will actually be generated. **Nothing is
enabled without a dialog** naming channel, frequencies and amplitude.
Two degenerate settings, opposite ends of the same knob:

- **modulation 0** → an unmodulated carrier at constant amplitude (CW). Not a
  DC level — the AOM needs its 80 MHz and the amplifier is AC-coupled.
- **carrier 0** → a plain sine at the modulation frequency, one spectral line,
  exact to the hertz.

**Sweep** — `start` / `stop` (nm), `speed` (a dropdown; the laser only accepts
0.5, 1, 2, 5, 10, 20, 50, 100, 200 nm/s), `trigger step` (nm), `mode`, then
`Configure` / `Start` / `Stop` / `Read log`. The info line says how many points
the **laser** will log and how that lines up with the **lock-in**'s own points.

**Acquire** — `decimation`, `sweep length` (s, follows the Sweep panel until
you type in it), `trigger` (**CH2_PE** = channel 2, positive edge), `level` (V),
`wait up to` (s), then `Capture (arms and waits)` / `Snapshot (no trigger)` /
`STOP waiting`. Pre-roll and tail are added on top of the sweep length, and
both inputs are always captured together.

**Demodulate** — `f_ref` (kHz), `output rate` (Sa/s) with a **max** button,
`bandwidth` (Hz, blank = derive it), the frequency buttons, then
`Demodulate capture`. Runs on the capture already in the workspace, so the same
record can be examined at f1 and 2×f1 with the hardware untouched.
The buttons are **f1**, **2 × f1**, **3 × f1**, **f2**, **f1+f2**, **|f1−f2|**.
**Use them. Never type a harmonic or a sum by hand** — they build f_ref from
what the ASG will actually generate, and a lock-in sitting df from its signal
returns a df beat: a clean sine across the trace that looks like a result.
The readout underneath gives τ, the noise gain, the settling cost and the
wavelength resolution at the current sweep speed.

**Map to wavelength** — one button. Capture + laser log → amplitude against
wavelength, through `reduce_sweep`, the offline-tested join. **It refuses a
filter that smears wavelength past 100 pm.**

**Export** — `Trace to CSV` and `Raw to .npz`.

**Sequences** — `linear sweep`, `SHG (demodulate at 2*f1)`, `SFG (two tones,
demodulate at f1+f2)`, `control: no drive`, `control: low power`, then `Run`.
These call exactly the same functions the buttons call. There is no second
implementation.

### The plot

Six views: **trace** (amplitude vs wavelength — the deliverable), **lock-in**
(amplitude vs time), **lock-in R** (magnitude), **lock-in phase** (unwrapped
degrees), **raw IN1** (volts), **raw IN2** (counts). Plus a **dB** checkbox
with a dB-range box, `Redraw` and `Fit`.

Wheel = zoom X, shift+wheel = Y, ctrl+wheel = both, drag = pan, double-click =
fit.

---

## 5. Taking one sweep, start to finish

1. **Board** → Connect, then **Configure**.
2. **Laser** → Connect. Check the power readout in the header.
3. **Drive (OUT1)** → set carrier 80 MHz and the modulation, then **OUT1 ON**
   and confirm the dialog.
4. **Sweep** → set start, stop, speed, trigger step, then **Configure**.
5. **Wait.** The laser has to travel back to its start wavelength on its own.
   Watch the wavelength in the header stop moving.
6. **Acquire** → **Capture (arms and waits)**. The header says ARMED.
7. **Sweep → Start.** The capture fires on the laser's first trigger pulse.
8. **Demodulate** → press **f1**, then **Demodulate capture**.
9. **Sweep → Read log**, then **Map**.
10. **Export** → Trace to CSV, and Raw to .npz.

**Order matters at steps 5–7.** Arm the capture first — it arms and *then*
waits — and only then start the sweep.

---

## 6. Six things that will bite you

1. **Wait between Sweep → Configure and Sweep → Start.** A sweep started early
   covers a *shorter range* at exactly the right speed and step, so the trace
   looks entirely normal. Measured: 80.96 nm of a requested 100.
2. **One laser connection, held for the whole session.** A connection attempt
   is a consumable — two connect-and-close cycles took a port from accepting to
   silently dropping SYNs, and only a power cycle recovered it. **Never retry a
   failed connect. Do not run two benches.**
3. **Use the frequency buttons, never a typed harmonic.** See above.
4. **A negative amplitude is the estimator, not the signal.** `amplitude()`
   projects onto one phase — unbiased, where `R` reads +1.25σ on pure noise —
   but it assumes the phase is steady. A sign change means the phase rotated
   past 90°, which no optical amplitude can do. **Plot lock-in R:** flat R
   under a swinging amplitude is phase, not physics.
5. **Front-end settings are per channel and both matter.** IN1 LV/AC, IN2
   HV/DC. On LV the 3.3 V trigger clips to a flat line.
6. **Narrowing the bandwidth is not free.** It is quieter *and* often settles
   faster, so nothing pushes back except the wavelength resolution, which is
   `speed / (2 × bandwidth)`. Map refuses anything past 100 pm.

Every trap, in the order it bites, is `docs/08-the-bench.md` §3. Every mistake
this project has ever made is `docs/11-mistakes.md`.

---

## 7. Without any hardware

```bash
run_gui.cmd
```

then **Acquire → Simulate**, **Demodulate → Demodulate**. The old tabbed GUI's
Simulate path runs the whole chain — capture handling, demodulation, trigger
edges, the laser log, the wavelength mapping and the CSV — with nothing
connected. It is the quickest proof an installation works.

Also useful, and instant:

```bash
.venv\Scripts\python -m pytest -q
.venv\Scripts\python -c "from rp_lockin import plan_two_tone_grid; print(plan_two_tone_grid(1e6).describe())"
.venv\Scripts\python -c "from rp_lockin import describe_capture_plan, plan_two_tone_grid as g; print(describe_capture_plan(1.0, g(1e6).difference))"
```

---

## 8. The other programs

**`run_dr.cmd` — the detector gain study.** Set the detector's gain by hand,
type what you set, press Run; it takes N sweeps at that setting and reduces
them to peak, noise floor and dynamic range. Views: waterfall by gain, dynamic
range against gain, peak and floor against gain. Exports CSV. The gain box is a
**label** — nothing reads the detector — so it only has to be a number and to
mean the same thing at every point. **A point flagged `clip` is not a
measurement.**

**The P-series scripts** (`scripts/p1_laser_check.py` … `p6_robustness.py`) are
the original step-by-step campaign, superseded by the bench but still holding
the safety contract. Outputs are disarmed on **every** exit path including
exceptions and Ctrl-C, nothing drives an output without `--i-am-present` *and*
a typed confirmation, and P5.2 refuses to run before a clean P5.1.

```bash
.venv\Scripts\python.exe scripts\p4_linear_sweep.py --i-am-present
```

**With the board, the hardware suite:**

```bash
set RP_HOST=rp-fffe42.local
.venv\Scripts\python -m pytest tests/hardware -m hardware
```

Read `docs/12-test-campaigns.md` first. Loopback wiring must be in place and
the sample must not be connected.

---

## 9. Key numbers

| | |
|---|---|
| Bench default f1 / f2 | **915 kHz / 1225 kHz** |
| Carrier | ~80 MHz (the exact value follows from the modulation) |
| Acquisition | 31.25 MS/s (decimation 8) |
| Output | 5000 Sa/s, 2250 Hz bandwidth, τ = 71 µs |
| **Noise gain** | **~4763 Hz — 1.9× the nominal bandwidth, not equal to it** |
| Noise floor | **σ = 3.57 µV** per trace point at the ADC; **≥36 µV** for SNR 10 |
| With the photodetector | expect nearer **11 µV** and **~120 µV** |
| Settling | ~113 output points, 22.6 ms — **pre-roll AND tail both required** |
| Wavelength resolution | 22 pm at 2250 Hz and 100 nm/s; **100 pm is a hard limit** |
| Memory, 1 s two-channel | **119.2 MiB** — 93% of the 128 MiB region |

**Two frequencies are forbidden and one is dangerous.** The board's switching
supply puts ~32 µV — nine times the noise floor — at **504.868 kHz and its
multiples**, and a lock-in cannot tell that apart from a steady signal. Round
numbers are the dangerous ones: 1.000 MHz sits 9.7 kHz from the second
harmonic, 500 kHz sits 4.9 kHz from the fundamental. 915 kHz clears the family
by 94.7 kHz, which is why it is the default. For SFG, **four** frequencies have
to clear it — f1, f2, f1+f2 and |f1−f2| — not the two being driven.

**There is no frequency grid.** Any whole number of hertz is exactly
generatable — the play rate is quantised to 1 Hz and that is the only
constraint. An older 15258.789 Hz "ASG grid" was a wrong model of the
generator, corrected on the board 2026-08-28; if you find a document, comment
or log line still asserting it, it is stale. `03-frequency-plan.md` has the
measurement.

**So round numbers are reachable — they are just bad choices**, because of the
switching supply above, not because the hardware cannot make them.

**Still use the bench's f1 / f2 / f1+f2 / |f1−f2| buttons rather than typing a
harmonic.** The reason is no longer snapping. It is that the table is built
from a whole number of modulation cycles times a play rate, so whatever
rounding is left gets multiplied by the cycle count and lands on the
modulation — and a lock-in sitting even a fraction of a hertz from its signal
returns a beat: a clean sine across the trace that looks like a result. The
buttons read the table the ASG will actually play.

---

## 10. Layout

```
README.md          this file — how to install and use it
CLAUDE.md          onboarding for an agent working on this project
SESSION_LOG.md     chronological history; its HANDOFF block is the current state
run_bench.cmd      launch the bench
run_dr.cmd         launch the gain study
run_gui.cmd        launch the old tabbed GUI (has a no-hardware Simulate path)
docs/              see docs/00-index.md
src/rp_lockin/     the package
scripts/           the bench, the shared operations, and the P-series campaign
tests/             offline suite + hardware-gated loopback suite
data/              captured sweeps
```
