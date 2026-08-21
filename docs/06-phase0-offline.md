# Phase 0 — offline development

**Status: COMPLETE.** No hardware involved at any point.

Phase 0 built everything that could be written and proved without a board, so
that when hardware did arrive the only new variable was the hardware itself.
That separation is why Phase 1 could attribute failures confidently — a wrong
answer was either a bad SCPI command or a bad cable, never suspect maths.

## What it covers

| Area | In plain words | Module |
|---|---|---|
| Signal processing | Turn a raw recording into an amplitude trace — the lock-in maths | `dsp.py` |
| Waveform construction | Build the drive signals the board will play | `waveforms.py` |
| Capture planning | How long, how fast, how much memory, and how much pre-roll and tail a sweep needs | `planning.py` |
| DUT emulator | Fake the experiment's physics, so the maths can be checked against a known answer | `emulator.py` |
| Wavelength mapping | Turn a trace plus the laser's table into power against wavelength | `wavelength.py` |

`wavelength.py` was written later, during Phase 1, but belongs here: it is
offline code with no hardware dependency, and it has never seen a laser.

## The test suite

```bash
pytest                      # 153 tests, no hardware. Must always pass.
pytest -m "not slow"        # quick loop while iterating
```

Covers: demodulation accuracy, noise scaling, filter settling, streaming block
equality, time-axis correctness, waveform commensurability, capture planning,
emulator round-trip against ground truth, trigger edge recovery, the wavelength
mapping, the laser/board clock measurement, the off-by-one-trigger guard, and
the transport's output-disarm safety behaviour.

**Do not delete a failing test to make the suite green.** Several exist because
the corresponding bug was real and produced a plausible-looking wrong answer.
They say so in their docstrings.

## Why this phase mattered more than it looks

Three of the bugs Phase 0 caught would have been nearly impossible to diagnose
on hardware, because each produced a believable wrong answer rather than an
error. They are written up in `02-architecture.md` under "Three bugs worth
remembering". The habit that caught them — build the ground truth separately,
then check against it — is the same habit that caught the H3.3 noise floor being
21% optimistic much later.
