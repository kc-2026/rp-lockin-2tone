# Agent onboarding — read this first, every session

You are working on a two-tone lock-in measurement system for a Red Pitaya
SIGNALlab 250-12. A human (Edwin) has the board on his bench and can rewire it,
but is not watching continuously.

**Read in this order before doing anything:**

1. This file.
2. `docs/01-project-spec.md` — what is being built and why.
3. `SESSION_LOG.md` — what previous sessions did and what state things are in.
4. Whatever doc covers the area you are about to touch.

**At the end of every session, append to `SESSION_LOG.md`.** Multiple sessions
will work on this. The log is the only continuity between them. Record what you
did, what you learned, what broke, and what you would do next. Be specific
enough that a fresh agent can resume without re-deriving anything.

---

## The one-paragraph summary

Two 80 MHz carriers, amplitude modulated at f1 = 5 MHz and f2 = 6 MHz, drive a
DUT through AOMs. The DUT mixes them; a photodetector returns the
intermodulation response at |f2 − f1| = 1 MHz and nothing else. A laser sweeps
its wavelength over ~1 s, emitting trigger pulses whose relative timing encodes
the time-to-wavelength calibration. We capture the photodetector on IN1 and the
trigger train on IN2, demodulate the 1 MHz response in software, and deliver a
5000-point trace of amplitude and phase across the sweep.

Everything is done in software on a control PC. There is no FPGA work in scope.

---

## Ground rules

### Safety

Loopback phase only, for now. Within that:

- **Never exceed the Red Pitaya's own specifications.** Output range is
  software-selectable; do not command amplitudes outside it.
- **The DUT, the amplifier chain, the AOMs and the photodetector are NOT
  connected** during loopback work. If you believe a test needs them, stop and
  write the request into `SESSION_LOG.md` — do not improvise a way around it.
- **Leave outputs off when you finish.** `tests/hardware/conftest.py` does this
  automatically; preserve that behaviour.
- Going beyond loopback requires a dedicated planning session with the human.
  There is a placeholder for it in `docs/04-test-plan.md`. Do not start it
  unilaterally.

### Verified versus unverified code

This distinction matters more than usual here.

| Area | Status |
|---|---|
| `src/rp_lockin/dsp.py` | **Trusted.** 74 offline tests. Do not change without re-running them. |
| `planning.py`, `emulator.py` | **Trusted.** Same suite. |
| `waveforms.py` — `make_am_table`, `plan_two_tone_grid` | **Trusted and hardware-verified.** Use these to drive the board. |
| `waveforms.py` — `make_am_waveform`, `plan_two_tone` | **Sound arithmetic, WRONG hardware model.** Kept because their tests are worth having. Driving the board with them produces no output at all. |
| `hardware.py` — SCPI transport, generator, `acquire`, `acquire_deep_fast` | **Verified against the board 2026-08-10.** |
| `hardware.py` — `acquire_deep_2ch` | **The SCPI read is broken.** Arming is fine; the read returns garbage. Use `acquire_deep_fast`. |
| `scripts/rp_fastread.py` | **Runs ON THE BOARD**, not the control PC. The one deliberate exception to "everything runs on the PC". |

`hardware.py` is deliberately isolated from the maths so a wrong command string
produces a connection error rather than corrupted physics. **Keep it that way.**
Do not move signal processing into the transport layer.

Your first hardware task is H1 in `docs/04-test-plan.md`: walk `hardware.py`
method by method and confirm each SCPI command against the board's actual OS
version. Every method carries a `VERIFY:` note naming what to check.

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
3. **Filter settling costs ~108 points** at 5000 Sa/s — about 22 ms, 2% of a
   sweep. The capture must pre-roll before the laser trigger or the start of
   every trace is garbage. See `planning.settling_points()`.
4. **The time axis is not zero-based.** `LockinResult.t` is referenced to the
   start of the input record and already compensates settling and group delay.
   Do not add your own offset — the wavelength calibration depends on this.
5. **`mean(R)` is a biased amplitude estimator** in noise. Use the vector mean
   of X + jY.
6. **Streaming block boundaries are periodic.** An artefact there lands at the
   same place in every sweep and looks like DUT structure. `test_chunked_equals_
   single_shot` pins this to exact equality; keep it exact, not approximate.

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
  `docs/05-hardware-notes.md`. Rebooting the board is permitted.
- **OS version: 2.00, build 37** (Ubuntu 22.04.4, kernel 5.15.0-xilinx).
  Recorded in `docs/05-hardware-notes.md`. It is in
  `/opt/redpitaya/version.txt`, not `/etc/redpitaya_version`, which does not
  exist on this image.

## Quick orientation

```bash
python -c "from rp_lockin import plan_two_tone; print(plan_two_tone(1e6).describe())"
python -c "from rp_lockin import describe_capture_plan; print(describe_capture_plan(1.0, 1e6))"
pytest -q
```

## Current state — updated 2026-08-10

Phase 0 complete. **Phase 1 substantially advanced**: H1 done, H2 done except
the phase items, H5/H6 unblocked. 74 offline tests pass.

| Test | State |
|---|---|
| H1 transport | done — OS 2.00, 250 MS/s confirmed by measurement, binary transfer verified |
| H2.1–H2.3 transmit | done — AM lines exact, modulation depth 0.512/0.488 vs 0.500, worst spur −48.5 dBc |
| H2.4 both channels | done |
| H2.5 / Q6 phase | fails, **downgraded** — deliverable is amplitude only, see `06-open-questions.md` |
| H3 receive / noise floor | **not started — do this next**, it predicts whether the real measurement works |
| H4 trigger digitisation | not started |
| H5 / H6 long capture | unblocked by `acquire_deep_fast`, not yet run at full length |

**Three things bit hard this session and are worth knowing before you start:**

1. The generator never worked as written — `make_am_waveform` models a device
   this board is not. Fixed by `make_am_table`; see `03-frequency-plan.md`.
2. **The drive frequencies are not round numbers.** The lock-in frequency is
   **991.821 kHz, not 1 MHz.** Never hardcode `1e6`; use
   `plan_two_tone_grid().difference`.
3. Deep captures need `scripts/rp_fastread.py` running on the board. It lives
   in `/dev/shm`, which is RAM, so **it disappears on every reboot.**

`docs/06-open-questions.md` lists what is still undecided. If you resolve one,
move it into the relevant doc and note it in the session log.

## Getting the environment up

`.venv/` is gitignored, so a fresh clone needs:

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"     # Windows
.venv/bin/python -m pip install -e ".[dev]"         # Linux
pytest -q                                            # expect 74 passed
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
- For deep captures, start the helper first:
  `python3 /dev/shm/rp_fastread.py` (copy it over with `scp` if the board has
  rebooted).
