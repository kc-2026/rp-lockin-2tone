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

## 1. Set up the machine

Skip this if the bench PC is already working. Needs **Python ≥ 3.10** (the bench
PC runs 3.13); nothing else.

```bash
git clone https://github.com/kc-2026/rp-lockin-2tone.git C:\dev\rp-lockin-2tone
cd C:\dev\rp-lockin-2tone
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
```

Then prove it, with no hardware connected:

```bash
.venv\Scripts\python -m pytest -q
```

Expect **~451 passed, 1-2 skipped, 11 deselected**, about four minutes.
Nothing should fail. The skip count moves because two GUI tests skip when Tk
cannot open a display; the 11 deselected need the board. On Linux use
`.venv/bin/python`.

**Do not put it in OneDrive, and do not run it from a copy on the Desktop.**
The Desktop snapshot has no `.venv`; starting the bench from it fails with
`No module named 'numpy'`, which blames the interpreter when the problem is the
folder.

---

## 2. Start the bench

Double-click **`run_bench.cmd`**, or from a terminal in the project folder:

```bash
.venv\Scripts\python.exe scripts\bench.py
```

That is the whole thing.

---

## 3. Before you plug into real hardware

1. **Board on**, and its SCPI server running: web interface → Development →
   SCPI server → **Run**. It does **not** auto-start after a reboot. If it is
   already running, leave it alone.
2. **Laser on**, and answering at `10.101.0.197:5000`.
3. **Know what the laser's power setpoint is** before opening the shutter — see
   §7.6.
4. **Connect the AOM before applying RF.** Never power the amplifier into an
   open port.

Then press Connect on the Board panel. It prints `fast-read helper running`,
and normally that is the end of it — see §10 if it ever says NOT RUNNING.

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
`Disconnect`, `Configure`, `Read back`, `Shutter OPEN` / `Shutter CLOSE`.
`Configure` sets wavelength and power together and reads both back. **Setting a
wavelength stops the laser sweeping** until you press Sweep → Configure again.
**The shutter is the only light control.** The laser diode is left on — Sweep →
Configure enables it — and the header reports its state.

**Drive (OUT1)** and **Drive (OUT2)** — `carrier` (MHz), `modulation` (kHz),
`amplitude` (V), then `OUTn ON` / `OUTn OFF` / `ALL OFF`.
A line under the boxes tells you what will actually be generated. Nothing is
enabled without a dialog naming the channel, frequencies and amplitude. OUT2 is
only needed for SFG.
Two special values: **modulation 0** gives an unmodulated carrier (CW);
**carrier 0** gives a plain sine at the modulation frequency.
That same line turns into a **WARNING** if the modulation lands within 20 kHz
of the switching supply — see §7.4.

**Sweep** — `start` / `stop` (nm), `speed` (dropdown — the laser only accepts
0.5, 1, 2, 5, 10, 20, 50, 100, 200 nm/s), `trigger step` (nm), `mode`, then
`Configure` / `Start` / `Stop` / `Read log`.

**Acquire** — `decimation`, `sweep length` (**read-only; always follows the
Sweep panel**), `trigger` (**CH2_PE**), `level`, `wait up to`, then
`Capture (arms and waits)` / `Snapshot (no trigger)` / `STOP waiting`.
Pre-roll and tail are added on top automatically. Both inputs are always
recorded together.
Underneath, a line says whether the record **fits in the board's memory at the
chosen decimation**, and which decimation to use if not. Lower decimation is
*faster* sampling and so a *shorter* record for the same memory, which is the
opposite of the intuition.

**Demodulate** — `f_ref` (kHz), `output rate` with a **`max`** button next to
its units (it sets the highest output rate this `f_ref` supports), `bandwidth`
(leave blank to derive it), the frequency buttons, then `Demodulate capture`.
**The buttons are the point: `f1`, `2 × f1`, `3 × f1`, `f2`, `f1+f2`,
`|f1−f2|`.** Press one instead of typing a number. The readout underneath gives
τ, the noise gain, the settling cost, and **the wavelength resolution you will
actually get**.

**Map to wavelength** — one button. Capture + laser log → the trace. It refuses
a filter that smears wavelength past 100 pm.

**Export** — `Trace to CSV`, `Raw to .npz`.

**Sequences** — **not trusted. Drive the panels by hand.** The dropdown offers
`linear sweep`, `SHG (demodulate at 2*f1)`, `SFG`, `control: no drive` and
`control: low power`, and they call the same functions the buttons call — but
they are not exercised against hardware, and the SHG one has been seen to fail
part way through on a timing overrun. Every result so far came from the panels.

---

## 6. Taking a sweep

1. **Board** → Connect → **Configure**
2. **Laser** → Connect. Check the power in the header.
3. **Drive (OUT1)** → carrier 80 MHz, modulation 915 kHz → **OUT1 ON**, confirm
4. **Sweep** → start, stop, speed, trigger step → **Configure**
5. **Wait.** Watch the wavelength in the header until it stops moving — the
   laser is travelling back to its start on its own.
6. **Acquire** → **Capture (arms and waits)**. Header says ARMED.
7. **Sweep → Start.** The capture fires on the laser's first trigger pulse.
8. **Demodulate** → press **2 × f1** (for SHG) → **Demodulate capture**
9. **Sweep → Read log**, then **Map**
10. **Export** → Trace to CSV

---

## 7. Things that will bite you

1. **If the laser will not connect, reapply its LAN settings** on the front
   panel: **Other → Communication → LAN**. That has fixed it every time. Do
   **not** just try again — see 2.
2. **One laser connection per session.** A failed connect is not free: two
   connect-and-close cycles have taken a port from working to silently dead,
   recoverable only by power-cycling the laser. **Never retry a failed
   connect, and never run two benches at once.**
3. **Wait between Sweep → Configure and Sweep → Start.** Start early and the
   laser covers a *shorter range* at exactly the right speed and step — so the
   trace looks completely normal. Measured: 80.96 nm of a requested 100.
4. **Use the frequency buttons, not typed numbers.** A lock-in sitting a few
   hertz from its signal returns a slow beat — a clean sine across the trace
   that looks exactly like a measurement.
   Related: the Drive panel warns **"only N kHz from the switching supply
   (k x 504.868 kHz)"** whenever the modulation lands within 20 kHz of that
   family. It is advisory, not an error, and the drive still goes out — but a
   lock-in sitting there reads the board's own power supply as a strong,
   clean, steady optical signal. Move the frequency. The same check runs on
   the SFG products and logs to the Log pane.
5. **A negative trace is the maths, not the light.** Switch the plot to
   **lock-in R**. If R is flat while the trace swings through zero, you are
   looking at a phase rotation, not a signal.
6. **The laser power limit depends on which detector is fitted, and the written
   one is stale.** The "keep it under 1 mW" rule throughout `docs/` is the
   **PDA05CF2's** 0.96 mW saturation and nothing more. The APD now on IN1 is a
   different part with a much lower saturation, and dynamic-range work has been
   run at **+10 dBm at the laser** — the splitters, the AOM and the conversion
   efficiency sit between the two numbers. **Know what is fitted and what
   actually reaches it before turning the laser up** (Q39).
7. **IN1 on LV/AC, IN2 on HV/DC.** On LV the laser's 3.3 V trigger clips to a
   flat line, which looks like "the laser is not triggering".
8. **A narrower filter is not free.** It is quieter *and* often faster to
   settle, so nothing warns you — except the wavelength resolution, which is
   `speed / (2 × bandwidth)`. Map refuses anything past 100 pm.

The full list, in the order they bite, is `docs/08-the-bench.md` §3. Every
mistake this project has ever made is `docs/11-mistakes.md`.

---

## 8. The other programs

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

## 9. Numbers worth knowing

| | |
|---|---|
| Default f1 / f2 | 915 kHz / 1225 kHz |
| Acquisition | 31.25 MS/s (decimation 8) |
| Output | 5000 Sa/s, 2250 Hz bandwidth, τ = 71 µs |
| Noise floor | **σ = 3.57 µV** per point; **≥36 µV** for SNR 10 |
| Wavelength resolution | 22 pm at 100 nm/s; **100 pm is a hard limit** |

**Dynamic range, measured:** at **+10 dBm** out of the laser with the **APD on
gain notch 2**, the board gives **~55 dB**, against **~60 dB** from the
commercial lock-in under the same conditions. So this instrument is about
**5 dB short** of the bench reference, not orders of magnitude — and the gap
has not been chased yet. `run_dr.cmd` is the tool for finding the gain setting
that closes it.

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

## 10. If the bench says "fast-read helper NOT RUNNING"

Deep captures are read by a small program that runs **on the board**, not here.
It lives in `/dev/shm`, which is RAM, so it is wiped by a reboot or a power
cycle — and nothing redeploys it automatically. In practice the board stays up
for weeks and you will rarely see this.

When you do, from the project folder:

```bash
scp scripts/rp_fastread.py root@rp-fffe42.local:/dev/shm/
ssh -n root@rp-fffe42.local "nohup setsid python3 /dev/shm/rp_fastread.py > /dev/shm/rp_fastread.log 2>&1 < /dev/null &"
```

Then press Connect again. `setsid` and the redirects matter — without them the
program dies the moment the SSH session closes, which looks exactly like never
having started it. If it still says NOT RUNNING, read
`/dev/shm/rp_fastread.log`.

Everything else — configuring, arming, triggering, the laser — goes over SCPI
and does not need this. Only the bulk read does, and it is worth it: 87 MB/s
against SCPI's 5.7.

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
