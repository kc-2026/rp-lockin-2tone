# rp-lockin-2tone

Lock-in detection of a nonlinear optical signal against laser wavelength, on a
Red Pitaya SIGNALlab 250-12.

An AOM chops 1550 nm laser light at f1 (default **915 kHz**). A crystal in the
beam does something nonlinear. A detector on IN1 sees the result; the laser's
trigger on IN2 says where in the recording each wavelength sits. One laser
sweep in, one **amplitude-against-wavelength** trace out, as CSV.

**It works.** SHG was measured on 2026-09-03 — a clear peak at ~1559 nm.

- **Repository:** <https://github.com/kc-2026/rp-lockin-2tone>
- **Lives at:** `C:\dev\rp-lockin-2tone` on the bench PC
- **Everything else:** `docs/` — start at `docs/00-index.md`

---

## 1. Start the GUI

Double-click **`run_bench.cmd`**, or from a terminal in the project folder:

```bash
.venv\Scripts\python.exe scripts\bench.py
```

That is the whole thing. If it opens, you are ready.

**If it does not open**, the machine has not been set up — go to §7.

---

## 2. Try it with no hardware, right now

Before touching the bench, prove the software works:

```bash
run_gui.cmd
```

In the window that opens: **Acquire** tab → **Simulate**, then **Demodulate**
tab → **Demodulate**. You will get a trace. That runs the whole chain —
capture, demodulation, trigger edges, the laser log, the wavelength mapping —
with nothing plugged in.

(`run_gui.cmd` is the older tabbed GUI, kept only because it has that Simulate
path. For real work use `run_bench.cmd`.)

---

## 3. Before you plug into real hardware

Five things, in this order:

1. **Board on**, and start its SCPI server: web interface → Development → SCPI
   server → **Run**. It does **not** auto-start after a reboot. If it is
   already running, leave it alone.
2. **Start the deep-capture helper** (see below). It lives in RAM and **dies
   on every board reboot**, so this is a routine, not a one-off.
3. **Laser on**, and check it answers at `10.101.0.197:5000`. If not, reapply
   the LAN settings on its front panel: Other → Communication → LAN.
4. **Check the laser's power setpoint.** It has been found at 12 dBm ≈ 15.8 mW.
   **Keep it at or under 0 dBm (1 mW).**
5. **Connect the AOM before applying RF.** Never power the amplifier into an
   open port.

The helper:

```bash
scp scripts/rp_fastread.py root@rp-fffe42.local:/dev/shm/
ssh -n root@rp-fffe42.local "nohup setsid python3 /dev/shm/rp_fastread.py > /dev/shm/rp_fastread.log 2>&1 < /dev/null &"
```

The bench prints `fast-read helper running` or `NOT RUNNING` when you press
Connect. If NOT RUNNING, read `/dev/shm/rp_fastread.log`.

---

## 4. What is on screen

```
+--------------------------------------------------------------+
| board | OUT1 OUT2 | laser | sweep |        [ALL OUTPUTS OFF]  |  header: live state
+-----------------+--------------------------------------------+
|  Board          |                                            |
|  Laser          |                                            |
|  Drive (OUT1)   |                  PLOT                      |
|  Drive (OUT2)   |                                            |
|  Sweep          |                                            |
|  Acquire        +--------------------------------------------+
|  Demodulate     |  Workspace: capture / laser log /          |
|  Map            |             lock-in / trace                |
|  Export         +--------------------------------------------+
|  Sequences      |                                            |
+-----------------+--------------------------------------------+
|  Log                                                          |
+--------------------------------------------------------------+
```

**The header** shows what the instruments actually report — board, both
outputs, laser wavelength and power, LD, shutter, sweep state. It is polled,
never remembered, so it cannot lie about a live output.

**The workspace** holds four results: `capture`, `laser log`, `lock-in`,
`trace`. Panels write to these slots instead of calling each other, which is
why you can capture once and then demodulate the same recording three different
ways without touching hardware.

**The plot** shows one of six things, chosen in the `show:` dropdown:

| View | What it is |
|---|---|
| **trace** | amplitude vs wavelength — **the deliverable** |
| lock-in | amplitude vs time |
| **lock-in R** | magnitude vs time — check this whenever the trace goes negative |
| lock-in phase | unwrapped degrees; a frequency error shows as a straight slope |
| raw IN1 | volts vs time — the detector |
| raw IN2 | counts vs time — the trigger train |

`dB` re-plots in decibels. Wheel = zoom X, shift+wheel = Y, ctrl+wheel = both,
drag = pan, double-click = fit.

---

## 5. The panels

Each does one thing. Top to bottom is roughly the order you use them.

**Board** — `host`, `IN1` and `IN2` settings, then `Connect` / `Disconnect` /
`Configure`.
Leave IN1 on **LV / AC** and IN2 on **HV / DC**. Press **Configure** after
connecting; it also applies the decimation from the Acquire panel.

**Laser** — `address`, `power` (dBm), `wavelength` (nm), then `Connect`,
`Configure`, `Read back`, `Shutter CLOSE`/`OPEN`, `LD ON`/`off`.
`Configure` sets wavelength and power together and reads both back. **Setting a
wavelength stops the laser sweeping** until you press Sweep → Configure again.

**Drive (OUT1)** and **Drive (OUT2)** — `carrier` (MHz), `modulation` (kHz),
`amplitude` (V), then `OUTn ON` / `OUTn OFF` / `ALL OFF`.
A line under the boxes tells you what will actually be generated. Nothing is
enabled without a dialog naming the channel, frequencies and amplitude. OUT2 is
only needed for SFG.
Two special values: **modulation 0** gives an unmodulated carrier (CW);
**carrier 0** gives a plain sine at the modulation frequency.

**Sweep** — `start` / `stop` (nm), `speed` (dropdown — the laser only accepts
0.5, 1, 2, 5, 10, 20, 50, 100, 200 nm/s), `trigger step` (nm), `mode`, then
`Configure` / `Start` / `Stop` / `Read log`.

**Acquire** — `decimation`, `sweep length` (follows the Sweep panel until you
type in it), `trigger` (**CH2_PE**), `level`, `wait up to`, then
`Capture (arms and waits)` / `Snapshot (no trigger)` / `STOP waiting`.
Pre-roll and tail are added on top automatically. Both inputs are always
recorded together.

**Demodulate** — `f_ref` (kHz), `output rate` with a `max` button, `bandwidth`
(leave blank to derive it), the frequency buttons, then `Demodulate capture`.
**The buttons are the point: `f1`, `2 × f1`, `3 × f1`, `f2`, `f1+f2`,
`|f1−f2|`.** Press one instead of typing a number. The readout underneath gives
τ, the noise gain, the settling cost, and **the wavelength resolution you will
actually get**.

**Map to wavelength** — one button. Capture + laser log → the trace. It refuses
a filter that smears wavelength past 100 pm.

**Export** — `Trace to CSV`, `Raw to .npz`.

**Sequences** — `linear sweep`, `SHG (demodulate at 2*f1)`, `SFG`,
`control: no drive`, `control: low power`, then `Run`. These call the same
functions the buttons call, in order.

---

## 6. Taking a sweep

1. **Board** → Connect → **Configure**
2. **Laser** → Connect. Check the power in the header.
3. **Drive (OUT1)** → carrier 80 MHz, modulation 915 kHz → **OUT1 ON**, confirm
4. **Sweep** → start, stop, speed, trigger step → **Configure**
5. **Wait.** Watch the wavelength in the header until it stops moving.
6. **Acquire** → **Capture (arms and waits)**. Header says ARMED.
7. **Sweep → Start.** The capture fires on the laser's first trigger pulse.
8. **Demodulate** → press **2 × f1** (for SHG) → **Demodulate capture**
9. **Sweep → Read log**, then **Map**
10. **Export** → Trace to CSV

**Steps 5–7 are where it goes wrong.** Wait for the laser, arm the capture,
*then* start the sweep.

---

## 7. Six things that will bite you

1. **Wait between Sweep → Configure and Sweep → Start.** Start early and the
   laser covers a *shorter range* at exactly the right speed and step — so the
   trace looks completely normal. Measured: 80.96 nm of a requested 100.
2. **One laser connection per session.** A failed connect is not free: two
   connect-and-close cycles have taken a port from working to silently dead,
   recoverable only by power-cycling the laser. **Never retry a failed
   connect, and never run two benches at once.**
3. **Use the frequency buttons, not typed numbers.** A lock-in sitting a few
   hertz from its signal returns a slow beat — a clean sine across the trace
   that looks exactly like a measurement.
4. **A negative trace is the maths, not the light.** Switch the plot to
   **lock-in R**. If R is flat while the trace swings through zero, you are
   looking at a phase rotation, not a signal.
5. **IN1 on LV/AC, IN2 on HV/DC.** On LV the laser's 3.3 V trigger clips to a
   flat line, which looks like "the laser is not triggering".
6. **A narrower filter is not free.** It is quieter *and* often faster to
   settle, so nothing warns you — except the wavelength resolution, which is
   `speed / (2 × bandwidth)`. Map refuses anything past 100 pm.

The full list, in the order they bite, is `docs/08-the-bench.md` §3. Every
mistake this project has ever made is `docs/11-mistakes.md`.

---

## 8. Setting up a new machine

Needs **Python ≥ 3.10** (the bench PC runs 3.13). Nothing else.

```bash
git clone https://github.com/kc-2026/rp-lockin-2tone.git C:\dev\rp-lockin-2tone
cd C:\dev\rp-lockin-2tone
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
.venv\Scripts\python -m pytest -q
```

Expect **450 passed, 2 skipped, 11 deselected**, about four minutes. On Linux
use `.venv/bin/python`.

**Do not put it in OneDrive, and do not run it from a copy on the Desktop.**
The Desktop snapshot has no `.venv`; starting the GUI from it fails with
`No module named 'numpy'`, which blames the interpreter when the problem is the
folder.

---

## 9. The other programs

**`run_dr.cmd`** — detector gain study. Set the gain by hand, type what you set,
press Run; it takes N sweeps and reduces them to peak, noise floor and dynamic
range. The gain box is just a **label** — nothing reads the detector. A point
flagged `clip` is not a measurement.

**`scripts/p1_laser_check.py` … `p6_robustness.py`** — the original
step-by-step campaign, superseded by the bench. They still hold the safety
contract: outputs disarmed on every exit path, and nothing drives an output
without `--i-am-present` *and* a typed confirmation.

**The hardware test suite**, with loopback cables fitted and the sample
disconnected:

```bash
set RP_HOST=rp-fffe42.local
.venv\Scripts\python -m pytest tests/hardware -m hardware
```

---

## 10. Numbers worth knowing

| | |
|---|---|
| Default f1 / f2 | 915 kHz / 1225 kHz |
| Acquisition | 31.25 MS/s (decimation 8) |
| Output | 5000 Sa/s, 2250 Hz bandwidth, τ = 71 µs |
| Noise floor | **σ = 3.57 µV** per point; **≥36 µV** for SNR 10 |
| Wavelength resolution | 22 pm at 100 nm/s; **100 pm is a hard limit** |

**Avoid 504.868 kHz and its multiples.** The board's switching supply puts
~32 µV there — nine times the noise floor — and a lock-in cannot tell that
apart from a real signal. This is why the default is 915 kHz and not a round
1 MHz, which sits 9.7 kHz from the second harmonic. For SFG, **four**
frequencies have to clear it: f1, f2, f1+f2 and |f1−f2|.

**There is no frequency grid.** Any whole number of hertz is exactly
generatable. If you find a comment or document claiming a 15258.789 Hz "ASG
grid" is a hardware limit, it is stale — that was a wrong model, corrected on
the board 2026-08-28. See `docs/03-frequency-plan.md`.

---

## 11. Where everything is

```
docs/00-index.md   what every document is for — start here
docs/08-the-bench  what is connected, and the traps in the order they bite
docs/09-whats-next what to do next
docs/11-mistakes   every wrong turn this project has taken
SESSION_LOG.md     history; the HANDOFF block at the top is the current state
CLAUDE.md          onboarding for an agent working on this project
scripts/bench.py   the bench
```
