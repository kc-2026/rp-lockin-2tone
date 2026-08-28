# Agent onboarding — read this first, every session

You are working on a two-tone lock-in measurement system for a Red Pitaya
SIGNALlab 250-12. A human (Kevin) has the board on his bench and can rewire it,
but is not watching continuously.

**Read in this order before doing anything:**

1. This file.
2. `docs/01-overview.md` — what is being built and why.
3. **`SESSION_LOG.md` — its "HANDOFF / STATUS" block at the very top.**
   That is the current state, the live blockers (there are two, and as of
   2026-08-26 both are hardware access rather than software), what is ready to
   run, and the judgement calls not to relitigate. Read it before touching
   anything.
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
- Going beyond loopback requires a dedicated planning session with the human.
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
| `santec.py` | **Written from the TSL-770/775 manuals. STILL NEVER RUN AGAINST A LASER** — the working laser code on 2026-08-28 was `tsl775.py`, not this. Has both serial and LAN transports; **LAN is the only path that works.** Bare-CR delimiter and little-endian payloads — both the opposite of `hardware.py`. Every setter reads back. |
| `output.py` | CSV deliverable plus the raw `.npz`. Trusted, offline. |
| `pipeline.py` | **THE DELIVERABLE PATH**, added 2026-08-25. **The wavelength axis comes from the MEASURED trigger edges, not a uniform step** (Q29, 2026-08-28): the trigger is periodic in WAVELENGTH, and the laser's sweep speed ripples ~11%, so a uniform grid misassigns wavelength by up to 0.68 of a step. Do not reintroduce a uniform step as the default. `reduce_sweep` joins demodulate → edges → log → wavelength → CSV and is checked against emulator truth. `SweepSeries`/`write_series` handle the 11-step set. `measure_sweep` is the hardware wrapper and **has never run against a board.** |
| `scripts/bench_gui.py` | Tkinter bench GUI (Q14). Drives the implemented features by hand, including a Simulate path that needs no hardware. Outputs off on close; laser writes gated. |

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

**Match that contract in anything new.** `scripts/bench_gui.py` follows it too.

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
10. **A serial read that times out desynchronises `santec.py` permanently** —
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

## Current state — updated 2026-08-26

**This section is a summary. The authoritative current state is the HANDOFF
block at the top of `SESSION_LOG.md`, which is rewritten every session.**

**Phase 0 and Phase 1 are both COMPLETE.** The offline suite passes; its size
grows, so check `SESSION_LOG.md` rather than trusting a number quoted here. Every
loopback test in `07-phase1-loopback.md` has been run against the board, except two
that were deliberately skipped and are recorded as such (H6.1, H5.2/H5.3).

**Phase 2 has not started and is gated on a planning session with Kevin.** Do not
connect anything.

A step-by-step status of every H item, in plain language, is at the top of
`SESSION_LOG.md` under "STATUS AT A GLANCE". Start there.

Key-based SSH is installed, so the board helper no longer needs a human — see
"Talking to the board" below. **Restarting the SCPI server is Kevin's job, not
the agent's** (asked 2026-08-14).

| Test | State |
|---|---|
| H1 transport | done — OS 2.00, 250 MS/s confirmed by measurement, binary transfer verified |
| H2.1–H2.4 transmit | done — AM lines exact, depth 0.512/0.488 vs 0.500, worst spur −48.5 dBc |
| H2.5 / Q6 phase | failed, **downgraded, and its residual risk is now closed** by H3.2 |
| H3.1 amplitude linearity | done — linear over 2.4 decades; 0.3% spread above 20 mV |
| H3.2 phase stability | done — 0.002° over 28 ms |
| H3.3 noise floor / Q8 | **done, revised twice — σ = 3.57 µV per trace point; ≥36 µV of signal gives SNR 10.** Do not quote the earlier 2.96 µV |
| H3.4 √bandwidth law | done — holds to 2–4% over 8× in bandwidth |
| H3.5 offset response | **done — measured rejection matches the designed filter to 0.0 dB** over the range above the noise floor |
| H4.1–H4.4 trigger | done — edges recovered exactly, inputs aligned to 0.0005 samples, `Trig:Pos` solved |
| H5.1 Deep Memory Gen | **answered: NOT AVAILABLE.** 16384-point ceiling is permanent |
| H5.2 / H5.3 | superseded — H6.5 emulated the DUT by stepping amplitude instead |
| H6.1 memory move | **deliberately not done, and no longer needed** — see `04-hardware-reference.md` |
| H6.2 / H6.3 full capture | **done — exactly 5000 points at exactly 200.000 µs spacing** |
| H6.4 pre-roll | done — and two real `acquire_deep_fast` defects fixed getting there |
| H6.5 full capture | **PASSES** — the Phase 1 exit criterion |
| H7.1 repeatability | **done — 20/20 sweeps, amplitude to 0.0029% rms, first edge to 6 ns** |
| H7.2 trigger never arrives | **done — raises cleanly; fixed a defect that left the board armed and SCPI wedged** |
| H7.3 mid-capture disconnect | **done — all three stages fail cleanly and leave the board healthy** |
| H7.4 outputs off after a crash | **failed, then fixed — `close()` now disarms both outputs** |

**Both former blockers are CLOSED as of 2026-08-28.**

**1. The board is reachable** from the new control PC — 1 Gbps, ping 1 ms, SCPI
on port 5000 and key-based SSH both working. Q28's root cause was never found;
the evidence pointed at the old PC's port and replacing the machine removed it.

**2. The laser answers over LAN.** Its USB is a hardware fault inside the
instrument, established exhaustively — see Q27 and `TSL775_HANDOFF.md`. The
trigger train has now been observed electrically on IN2: 5001 pulses against
5001 logged points, 24.997 µs wide, 199.997 µs apart, none lost at decimation 8.

The lasers are a **TSL-770 and a TSL-775** (Kevin, 2026-08-14).

`santec.py` **is** written, entirely from the manuals — bare-CR delimiter,
little-endian payloads, every setter reading back. **It has a LAN transport
(`SantecTSL.over_lan`) as well as a serial one, and LAN is the working path.**
The module itself has still never been exercised against the instrument — the
2026-08-28 work drove the laser through `TSL775_HANDOFF.md`'s `tsl775.py`
instead — so treat its command strings as unproven even though the protocol
they speak is now known to be right. One command string in it is inferred rather than quoted
(`set_wavelength_m`, whose SET form is not in the manuals' tables); that is safe
only because it verifies itself by read-back, and the module says so. **Do not
extend that pattern to a command whose effect cannot be read back** — on this
project a misspelled command returns zero bytes exactly like a correct one, and
the wavelength axis is the one place a silent failure is invisible in the output.

`wavelength.py` still holds **no serial commands at all**, and `pipeline.py`
keeps the same split. What remains unknown about the laser: the port settings,
and whether the table streams during the sweep or is dumped afterwards (P1.4).

That change also **defused the decimation/memory question.** It was live only
because the wavelength axis depended on recovering trigger intervals exactly; it
no longer does. Do not start the device-tree move — see `04-hardware-reference.md`.

**Two numbers from H3.3 not to re-derive or guess at:**

- **The demodulator's noise gain is NOT the nominal bandwidth.** 4232.7 Hz
  analytically, **4763 Hz measured** — both about 1.9× the nominal 2250 Hz.
  Using the −3 dB bandwidth instead gives 2.45 µV against 3.57 measured,
  **46% low, in the dangerous direction.** Pinned by
  `test_quadrature_noise_gain_matches_filter_chain`.
- **A switching-supply harmonic sits 17.9 kHz from the lock-in frequency, and
  it is ~32 µV — 11× the noise floor.** Rejected by >200 dB today, but only
  **1.77%** of switcher drift from landing on it, where it would look like a
  strong, clean, steady DUT response rather than interference.
  **504.868 kHz and its multiples are off limits for any future
  difference frequency**, with several kHz of margin.

**Three things bit hard this session and are worth knowing before you start:**

1. The generator never worked as written — `make_am_waveform` models a device
   this board is not. Fixed by `make_am_table`; see `03-frequency-plan.md`.
2. **The drive frequencies are not round numbers.** The lock-in frequency is
   **991.821 kHz, not 1 MHz.** Never hardcode `1e6`; use
   `plan_two_tone_grid().difference`.
3. Deep captures need `scripts/rp_fastread.py` running on the board. It lives
   in `/dev/shm`, which is RAM, so **it disappears on every reboot.**

`docs/10-open-questions.md` lists what is still undecided. If you resolve one,
move it into the relevant doc and note it in the session log.

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
