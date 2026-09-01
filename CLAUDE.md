# Agent onboarding — read this first, every session

You are working on a two-tone lock-in measurement system for a Red Pitaya
SIGNALlab 250-12. A human (Kevin) has the board on his bench and can rewire it,
but is not watching continuously.

**Read in this order before doing anything:**

1. This file.
2. `docs/01-overview.md` — what is being built and why.
3. **`SESSION_LOG.md` — its "HANDOFF / STATUS" block at the very top.**
   That is the current state, what is ready to run, and the judgement calls not
   to relitigate. **There are no blockers as of 2026-09-01** — the board and
   the laser both work and the instrument runs end to end. What is left is
   physics waiting on hardware. Read it before touching anything.
4. Whatever doc covers the area you are about to touch.

**At the end of every session, append to `SESSION_LOG.md`.** Multiple sessions
will work on this. The log is the only continuity between them. Record what you
did, what you learned, what broke, and what you would do next. Be specific
enough that a fresh agent can resume without re-deriving anything.

---

## The one-paragraph summary

Two AOMs gate light, one at f1 = 5 MHz and one at f2 = 6 MHz, by amplitude
modulating the 80 MHz acoustic drive each AOM needs. **The 80 MHz is the AOM's
requirement, not the DUT's — the DUT only ever sees light varying in
brightness.** The DUT mixes the two; a photodetector returns the
intermodulation response at |f2 − f1| ≈ 991.821 kHz and nothing else.

**There are TWO Santec lasers, and this was only established on 2026-08-25.**
A **fine sweeper** covers ~1 s / 5000 points, carries the trigger BNC, and
supplies the wavelength axis from its own log. A **stepper** sits at 11 discrete
wavelengths, one per sweep — no trigger, no log, just set, settle and read. The
deliverable is an **11 × 5000 map**. Note the naming collision: the docs' f1/f2
are the AOM MODULATION frequencies (MHz); Kevin's "freq1/freq2" are the LASERS
(THz). Different things by nine orders of magnitude.

Per sweep: capture the photodetector on IN1, trigger the capture from the
sweeping laser's trigger output on IN2, demodulate in software, and deliver a
5000-point trace of **amplitude** against wavelength. `pipeline.reduce_sweep`
is that whole path.

**The wavelength axis comes from the laser over serial, not from trigger timing**
(Kevin, 2026-08-14). The laser logs **wavelength values with the time axis
IMPLICIT** — `:READout:DATa?` returns a bare array, so `wavelength[i]` is the
wavelength at trigger pulse `i`. With the trigger stepping in time that is
wavelength against relative time from the first trigger, exactly as Kevin
described; the times are simply reconstructed rather than read, as
`first_edge + i × step`. Its trigger also starts the capture, so both share
t = 0. `santec.py` reads the log; `wavelength.py` places it in
time. **Neither has ever met a laser.**

**Three traps to design against:**

- **Q21** — both sides call t = 0 "the first trigger", independently. Latch the
  second pulse instead of the first and every wavelength is off by one step,
  with a trace that looks entirely normal. Use
  `wavelength.logged_point_times()`, which locates ONE edge and indexes from it,
  so a missed edge mid-record changes nothing.
- **Q26 is DEAD as of 2026-08-25.** It asked whether the laser logs one point
  per trigger pulse — which no manual states — and it mattered only while the
  time step came from the trigger INTERVAL. `pipeline.reduce_sweep` takes the
  step from the trigger train's SPAN over (N−1) logged points, so nothing counts
  pulses and the question stops being load-bearing. **Q24 still matters**:
  the trigger must be periodic in TIME, not in wavelength.
- **A real trigger is a 25 µs PULSE, so every logged point makes TWO edges.**
  `find_trigger_edges` defaults to `polarity="both"`; anything deriving a step
  or counting pulses must pass `polarity="rising"` or it reads half the step and
  compresses the whole wavelength axis. Found 2026-08-25 by joining the pipeline.

Everything is done in software on a control PC. There is no FPGA work in scope.

---

## Ground rules

### Safety

Loopback phase only, for now. Within that:

- **Never exceed the Red Pitaya's own specifications.** Output range is
  software-selectable; do not command amplitudes outside it.
- **As of 2026-08-28 the board and the laser BOTH answer.** The board is on a
  new control PC at 1 Gbps with SCPI and key-based SSH working; the laser
  answers over LAN. Q28 and Q27 are both closed — see the HANDOFF block.
- **The laser's USB is a HARDWARE FAULT inside the instrument. Use LAN**
  (`10.101.0.197:5000`, bare CR, one held connection). Windows shows
  `CM_PROB_FAILED_INSTALL` on the USB node; ignore it, it is a red herring that
  has already cost this project real time. Full evidence in `TSL775_HANDOFF.md`.
- **The laser's LAN interface drops out periodically** — it happened twice on
  2026-08-28. Recovery is to reapply the LAN settings on the front panel. That
  is Kevin's, not yours.
- **As of 2026-08-28 the laser, its trigger BNC (on IN2) and the photodetector
  on IN1 ARE connected**, but the DUT, amplifiers and AOMs are **not**. If
  you believe a test needs those, stop and write the request into
  `SESSION_LOG.md` — do not improvise a way around it.
- **Reads are always safe; writes to the laser are not.** `*IDN?` and the
  `:READout:*` queries cannot disturb anything. Do not start a sweep or change a
  laser setting without asking — the light goes somewhere.
- **Leave outputs off when you finish.** `tests/hardware/conftest.py` does this
  automatically; preserve that behaviour.
- **The Phase 2 planning gate is DISCHARGED as of 2026-08-28** -- its answers
  are in `docs/09-phase2-plan.md`. **P1 and P2 are done; P3-P6 are not, and no
  RF has ever left this board.** Follow the P-series order and its gates.
- One item remains open: **nothing runs unattended** until Kevin says otherwise.
  **Phase 1 is complete; what Phase 2 needs is in `docs/08-phase2-hardware.md`.**
  Do not start it unilaterally.
- **Do not "fix" the RF drive level.** Kevin tuned it by maximising the
  diffracted light with an unmodulated carrier, and that is correct here:
  the drive is depth-1 AM, so the envelope reaches zero every cycle and the AOM
  is switched fully on and off rather than held at a bias point. Three separate
  attenuator recommendations were made and all three were withdrawn. See
  `docs/04-hardware-reference.md` — the reasoning is recorded because the mistake
  is an easy one to repeat.

### Verified versus unverified code

This distinction matters more than usual here.

| Area | Status |
|---|---|
| `src/rp_lockin/dsp.py` | **Trusted.** Covered by the offline suite. Do not change without re-running it. |
| `planning.py`, `emulator.py` | **Trusted.** Same suite. |
| `waveforms.py` — `make_am_table`, `plan_two_tone_grid` | **Trusted and hardware-verified.** Use these to drive the board. |
| `waveforms.py` — `make_am_waveform`, `plan_two_tone` | **Sound arithmetic, WRONG hardware model.** Kept because their tests are worth having. Driving the board with them produces no output at all. |
| `hardware.py` — SCPI transport, generator, `acquire`, `acquire_deep_fast` | **Verified against the board 2026-08-12.** |
| `hardware.py` — `acquire_deep_2ch` | **The SCPI read is broken.** Arming is fine; the read returns garbage. Use `acquire_deep_fast`. |
| `scripts/rp_fastread.py` | **Runs ON THE BOARD**, not the control PC. The one deliberate exception to "everything runs on the PC". |
| `wavelength.py` | **Offline-tested, never run against a real laser.** Maps a trace onto wavelength, measures the laser/board clock ratio, and guards the off-by-one trigger. Contains NO serial code. |
| `santec.py` | Written from the TSL-770/775 manuals. **The bench does not use it — `scripts/tsl775.py` does**, and that is the code with hardware hours on it. Its transport and command strings are sound (a one-off `SantecTSL.over_lan` session on 2026-09-01 answered `*IDN?` and every `:READout:*` query correctly), but `pipeline.py` assumes this class while `_bench_ops.py` assumes the other, and **their surfaces differ** — `SantecTSL` has setters `TSL775` does not. Do not assume a method exists on both; that shipped a bug on 2026-09-01. See Q35. |
| `output.py` | CSV deliverable plus the raw `.npz`. Trusted, offline. |
| `pipeline.py` | **THE DELIVERABLE PATH**, added 2026-08-25. **The wavelength axis comes from the MEASURED trigger edges, not a uniform step** (Q29, 2026-08-28): the trigger is periodic in WAVELENGTH, and the laser's sweep speed ripples ~11%, so a uniform grid misassigns wavelength by up to 0.68 of a step. Do not reintroduce a uniform step as the default. `reduce_sweep` joins demodulate → edges → log → wavelength → CSV and is checked against emulator truth. `SweepSeries`/`write_series` handle the 11-step set. `measure_sweep` is the hardware wrapper and **has never run against a board.** |
| `scripts/bench.py` | **THE WORKING BENCH.** Panel GUI: independent operations that compose into a sweep. Hardware-exercised daily. Outputs off on close; every output enable needs a typed confirmation. |
| `scripts/_bench_ops.py` | Tk-free instrument operations shared by the bench buttons, its sequences and the P-scripts. **One implementation, so nothing can drift.** |
| `scripts/tsl775.py` | Vendored TSL-775 driver, `write`/`query` only. **This is what the bench talks to**, not `santec.py`. |
| `scripts/bench_gui.py` | The older tabbed GUI (Q14). Kept because it is the only path with a **Simulate** mode needing no hardware. |

`hardware.py` is deliberately isolated from the maths so a wrong command string
produces a connection error rather than corrupted physics. **Keep it that way.**
Do not move signal processing into the transport layer.

**Phase 1 is complete, so H1 is history** — every method in `hardware.py` has run
against the board. The live task is in the HANDOFF block at the top of
`SESSION_LOG.md`; at the time of writing it is the Santec laser not answering
over USB, and the Tier 1 work that needs no hardware at all.

### Driving hardware from a script

The P-series scripts (`scripts/p2_trigger_check.py` … `p6_robustness.py`) share
`scripts/_bench.py`, and its contract is not decoration:

- **Outputs are disarmed on EVERY exit path**, including exceptions and Ctrl-C.
- **Nothing drives an output without `--i-am-present` AND a typed confirmation.**
  A flag alone is too easy to leave in a shell history; EOF is not consent.
- **P5.2 refuses to run before P5.1**, and refuses if P5.1 was not clean. An
  amplifier-generated product sits at exactly the frequency P5.2 looks at, so a
  signal found there proves nothing until the one-tone control is clean.

**Match that contract in anything new.** `scripts/bench.py` and
`scripts/bench_gui.py` both follow it.

### Testing discipline

```bash
pytest                      # offline suite — must always pass
pytest -m "not slow"        # quick loop while iterating
RP_HOST=<ip> pytest tests/hardware -m hardware    # needs the board
```

- The offline suite must pass before you touch hardware, and again before you
  commit.
- **Do not delete a failing test to make the suite green.** Several tests exist
  because the corresponding bug was real and produced plausible-looking wrong
  answers. They are documented as such in their docstrings.
- When you fix a hardware-discovered bug, add an offline test that would have
  caught it, if one can exist.

### Things that will bite you

These are all real, all previously encountered, and all produce *believable*
wrong answers rather than crashes:

1. **Buffer commensurability.** A repeating waveform buffer must contain whole
   cycles of the carrier AND the modulation. Off-grid frequencies glitch at
   every wrap and scatter spurs across the baseband — exactly where the trace
   lives. Use `plan_two_tone()`; never hand-roll frequencies.
2. **The naive buffer rule is wrong.** N = fs/f_mod only works when that is an
   integer. The real minimum is the smallest N making N·f/fs whole for *every*
   frequency involved. f2 = 6 MHz needs 125 samples, not 41.67.
3. **Filter settling costs ~113 points** at 5000 Sa/s — about 22 ms, 2% of a
   sweep. The capture must pre-roll before the laser trigger or the start of
   every trace is garbage. See `planning.settling_points()`.
   **And it needs a TAIL too, which is easy to miss.** `LockinResult.t`
   compensates group delay as well as trimming settling, so the valid
   window is shifted: a record stopping at trigger + 1 s yields 4943 points,
   not 5000, with no error and a trace that just ends early. Use
   `planning.recommended_tail()`. Measured in H6.3.
4. **The time axis is not zero-based.** `LockinResult.t` is referenced to the
   start of the input record and already compensates settling and group delay.
   Do not add your own offset — the wavelength calibration depends on this.
5. **`mean(R)` is a biased amplitude estimator** in noise — it reads 1.25σ with
   no signal at all. Use `LockinResult.amplitude()`, which projects onto a
   common phase and is unbiased, or `amplitude(smooth=N)` if the response phase
   moves across the sweep. **Do not reach for
   `debiased_amplitude()`** — measured, it is worse than raw R between 2σ and 6σ,
   which is exactly where our signals will sit.
6. **Streaming block boundaries are periodic.** An artefact there lands at the
   same place in every sweep and looks like DUT structure. `test_chunked_equals_
   single_shot` pins this to exact equality; keep it exact, not approximate.
7. **`find_trigger_edges` reports BOTH polarities by default, and a real trigger
   is a 25 µs PULSE.** Every logged point makes two edges, so a step averaged
   over both is near HALF the truth — compressing the whole wavelength axis 2×
   while still drawing a clean trace. Pass `polarity="rising"` for anything
   deriving a step or counting pulses.
8. **`check_alignment`'s span test is vacuous when the table was built from the
   edges**, which is `reduce_sweep`'s default. It compares a number against
   itself and reports 0.00% on a genuinely broken alignment. Only the COUNT
   check does work there. Do not read "spans match" as corroboration.
9. **Coupling and gain are PER CHANNEL** (`setup_channel`). IN1 wants LV for the
   detector, IN2 wants HV for the 3.3 V trigger. On LV that trigger clips to a
   flat line, which reads as "the laser is not triggering".
10. **A connection attempt to the laser is a CONSUMABLE, not a free probe.**
    Measured 2026-09-01: two connect-and-close cycles on a port took it from
    accepting to silently dropping SYNs, with nothing else on the network
    talking to the instrument. Only a power cycle recovers it — a front-panel
    LAN reset alone does not. **One connection, held for the whole session.
    Never retry a failed connect; power cycle with the PC quiet instead.** Q33.
11. **A test fake must never be richer than the real object.** Two bugs shipped
    on 2026-09-01 because a stand-in offered a method the instrument did not
    have: the suite was green and the bench raised `AttributeError` on the
    first press. Build fakes from the real class, and assert their surface does
    not exceed it — `test_the_fakes_offer_no_more_than_the_real_driver` does.
12. **`mod_cycles` multiplies the generator's frequency error.** The output is
    `mod_cycles x play_rate`, so a plan with 12 modulation cycles carries 12x
    the error of one with 1. At 915 kHz that was ~0.69 Hz, which the lock-in
    drew as a smooth arch through zero across the whole sweep — reading exactly
    like a wavelength-dependent response. `plan_exact_am` now takes the fewest
    cycles the carrier tolerance allows. Q31.
13. **`amplitude()` can go negative, and that is correct.** It projects X+jY
    onto one phase, so it is unbiased where `R` reads +1.25 sigma on pure
    noise — but it assumes the phase is steady. A sign change means the phase
    rotated past 90 degrees, which no optical amplitude can do. When you see
    one, plot **lock-in R**: if R is flat, it is phase, not physics.
14. **A serial read that times out desynchronises `santec.py` permanently** —
    every later query returns the tail of the previous reply, plausibly and
    without raising. Call `resync()`; it is read-only and safe any time.

### Conventions

- Python ≥ 3.10, numpy + scipy. Keep dependencies minimal.
- Comments explain *why*, not *what*. Non-obvious numerical choices get a
  sentence of justification.
- Errors should refuse and explain, not silently degrade. If a record is too
  short or a frequency is off-grid, raise with a message saying what to do
  instead. This codebase already does that in several places — match the style.
- Commit in logical units with messages saying what changed and why.

---

## Environment

- Code and this agent both run on the control PC.
- The board is reachable over the network; the human will supply `RP_HOST`.
  Nobody else uses the board.
- The board's SCPI server must be running: web interface → Development → SCPI
  server → Run. Port 5000.
- SSH access to the board is available for the device-tree change described in
  `docs/04-hardware-reference.md`. Rebooting the board is permitted.
- **OS version: 2.00, build 37** (Ubuntu 22.04.4, kernel 5.15.0-xilinx).
  Recorded in `docs/04-hardware-reference.md`. It is in
  `/opt/redpitaya/version.txt`, not `/etc/redpitaya_version`, which does not
  exist on this image.

## Quick orientation

```bash
python -c "from rp_lockin import plan_two_tone; print(plan_two_tone(1e6).describe())"
python -c "from rp_lockin import describe_capture_plan; print(describe_capture_plan(1.0, 1e6))"
pytest -q
```

## Current state — updated 2026-09-01

**This section is a summary. The authoritative current state is the HANDOFF
block at the top of `SESSION_LOG.md`, which is rewritten every session.**

**Phases 0 and 1 are complete. Phase 2 is under way and there are no blockers.**
The offline suite passes; its size grows, so check `SESSION_LOG.md` rather than
trusting a number quoted here.

**The instrument works end to end against real hardware.** A sweep runs from
`scripts/bench.py`: drive on, capture armed, laser sweeps, 5001 trigger pulses
land on IN2, the capture demodulates at f1, and the wavelength axis is built
from the measured trigger edges. Real optical amplitude-against-wavelength
traces exist.

**What Phase 2 has left is physics, not instrumentation:**

- **There is no crystal yet.** No SHG or SFG signal has ever been looked for.
- **The second beam path is not wired** — the second ZHL-1-2W+ and second AOM
  exist but are not connected, so nothing two-tone has been driven.
- **The stepping laser (TSL-770) has never been contacted**, so the deliverable
  is a 1 x 5000 sweep rather than the 11 x 5000 map. Parked at Kevin's request.
- **The PDA100A2 silicon detector is on the bench, not installed.** It is how
  SHG gets separated from the AOM's own second harmonic (Q30), because silicon
  cannot see 1550 at all.

Details in `docs/08-phase2-hardware.md` (what is connected) and
`docs/09-phase2-plan.md` (what to do next).

### Numbers not to re-derive or guess at

- **The demodulator's noise gain is NOT the nominal bandwidth.** 4232.7 Hz
  analytically, **4763 Hz measured** — both about 1.9x the nominal 2250 Hz.
  Using the -3 dB bandwidth instead gives 2.45 uV against 3.57 measured,
  **46% low, in the dangerous direction.** Pinned by
  `test_quadrature_noise_gain_matches_filter_chain`.
- **A switching-supply harmonic family sits at 504.868 kHz and its multiples**,
  at ~32 uV — nine times the noise floor. Rejected by >200 dB when you are far
  from it, but a drive frequency landing there reads as a strong, clean, steady
  optical signal. **Every frequency the lock-in will ever sit on must clear it
  by several kHz — including sums and differences, not just the driven tones.**
- **sigma = 3.57 uV per trace point at the ADC**, but the PDA05CF2 contributes
  ~11 uV, so **SNR 10 needs ~120 uV**, not 36.

### Things that were true and are not

Do not act on these if you find them repeated somewhere:

- ~~"The Ethernet link to the board is dead"~~ — fixed by the new control PC.
- ~~"The laser has never answered"~~ — it answers over LAN. USB is a hardware
  fault inside the instrument and is not worth another minute.
- ~~"santec.py has never been run against a laser"~~ — the bench uses
  `scripts/tsl775.py` instead, which has. See the driver note below.
- ~~"Phase 2 is gated on a planning session"~~ — discharged 2026-08-28.
- ~~"Frequencies must sit on the fs/16384 grid"~~ — that grid is only the
  default play rate. Any whole number of hertz is exact.

### Two laser drivers, and the bench uses the one in `scripts/`

`scripts/tsl775.py` defines **`TSL775`**, which has `write`, `query`,
`read_line`, `read_block` and `query_wavelength_log` — and no setters.
**`scripts/bench.py` and `scripts/_bench_ops.py` use this one.**

`src/rp_lockin/santec.py` defines **`SantecTSL`**, a much richer surface
including `set_wavelength_m`. `pipeline.py` assumes this one.

Writing an operation against the wrong class shipped a bug on 2026-09-01 that
the offline suite could not catch, because the test fake had been built from
the wrong class too. **Check which object you actually have**, and build fakes
from the real class's surface. Q35.

## Getting the environment up

`.venv/` is gitignored, so a fresh clone needs:

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"     # Windows
.venv/bin/python -m pip install -e ".[dev]"         # Linux
pytest -q                                            # expect 200+ passed
```

Most machines here run Windows; keep the suite passing on it. One test uses
`tracemalloc` rather than the Unix-only `resource` module for exactly that
reason — do not "simplify" it back.

## Talking to the board

```bash
export RP_HOST=rp-fffe42.local     # mDNS; the link-local IP changes on reconnect
```

- **SCPI does not auto-start after a reboot.** Web interface → Development →
  SCPI server → Run. Port 5000.
- **One persistent connection, always.** Opening a connection per command
  wedges the server, and the symptom is multi-second latency that looks
  exactly like a failing cable, not an error.
- For deep captures, start the helper first. It lives in `/dev/shm`, which is
  RAM, so **it is gone after every reboot** and these two commands are the
  routine. Key-based SSH was installed on the control PC on 2026-08-12, so this
  needs no password and no human:

  ```bash
  scp scripts/rp_fastread.py root@rp-fffe42.local:/dev/shm/
  ssh -n root@rp-fffe42.local "nohup setsid python3 /dev/shm/rp_fastread.py > /dev/shm/rp_fastread.log 2>&1 < /dev/null &"
  ```

  `setsid` and the redirects matter: without them the helper dies when the SSH
  session closes, which looks identical to "the helper was never started".
  Confirm with `RedPitaya.fast_read_available()`, and read
  `/dev/shm/rp_fastread.log` if it says False. Stop it cleanly by sending
  `QUIT\n` to port 9999.

- **The board's root filesystem is mounted read-write** (confirmed
  2026-08-14: `/dev/root / ext4 rw,relatime,errors=remount-ro`), apparently
  left that way by the 2026-08-12 device-tree edit. That is why the documented
  `rw` step appears unnecessary — and note `rw`/`ro` are interactive shell
  shortcuts that do not exist in a one-shot `ssh host "..."` command; use
  `mount -o remount,rw /` there. A permanently writable root on an SD card is a
  mild corruption risk on power loss; worth putting back with
  `mount -o remount,ro /` once the device-tree work is finished.
