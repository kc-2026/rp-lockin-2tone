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
| `src/rp_lockin/dsp.py` | **Trusted.** 62 offline tests. Do not change without re-running them. |
| `waveforms.py`, `planning.py`, `emulator.py` | **Trusted.** Same suite. |
| `src/rp_lockin/hardware.py` | **NEVER RUN AGAINST HARDWARE.** Written from docs. Expect SCPI spellings to be wrong. |

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
- **The OS version is not yet recorded.** Establish it in your first hardware
  session and write it into `docs/05-hardware-notes.md` — every SCPI question
  depends on it.

## Quick orientation

```bash
python -c "from rp_lockin import plan_two_tone; print(plan_two_tone(1e6).describe())"
python -c "from rp_lockin import describe_capture_plan; print(describe_capture_plan(1.0, 1e6))"
pytest -q
```

## Current state

Phase 0 (offline) is complete: 62 tests pass, no hardware touched.
Phase 1 (H1, transport validation) has not started.

`docs/06-open-questions.md` lists what is still undecided. If you resolve one,
move it into the relevant doc and note it in the session log.
