# Documentation index — start here

A two-tone lock-in measurement on a Red Pitaya SIGNALlab 250-12: two AOM drives
mix in a DUT, a photodetector returns the intermodulation response, and we
deliver amplitude against laser wavelength across a ~1 second sweep.

**TWO lasers, established 2026-08-25.** A fine sweeper (TSL-775: 5001 points,
~1 s, carries the trigger) and a stepper (TSL-770: 11 discrete wavelengths, one
per sweep). The deliverable is an **11 x 5000 map**. Anything written before that
date describing a single laser is stale — say so if you find some.

## Status, in one line

**The instrument is finished and works end to end against real hardware; what
is left is physics.** Real optical amplitude-against-wavelength sweeps exist,
driven from `scripts/bench.py`. **No blockers.** Next up is SHG, which needs a
crystal and the silicon detector; then SFG, which needs the second beam path
wired; then the stepping laser for the second axis. The fastest way to learn
the current state is the HANDOFF block at the top of `SESSION_LOG.md`.

*The old Phase 0–3 framing still describes the history accurately, and the
P1–P6 / U1–U12 planning structure is retired — see the appendix to
`08-the-bench.md`.*

## What each document is for

| Doc | What it holds | Read it when |
|---|---|---|
| **01-overview.md** | Goal, requirements, operating point, channel allocation, the four phases | You are new, or need to know what is being built and why |
| **02-architecture.md** | How the software is shaped, the design decisions (ADRs), and the bugs worth remembering | Before changing anything structural |
| **03-frequency-plan.md** | Why the frequencies are what they are, how the generator really works, and the arithmetic behind both | Before changing any frequency. **Never hand-roll one** |
| **04-hardware-reference.md** | How the board and the instruments behave, and the traps they set | While writing code that talks to hardware |
| **05-results.md** | Every number this project has measured | You need a figure — noise floor, timing, rejection, repeatability |
| **06-phase0-offline.md** | What was built with no hardware, and the test suite | Understanding what is already proved offline |
| **07-phase1-loopback.md** | The loopback campaign, H1–H7, complete | Checking what was tested, how, and what it found |
| **08-the-bench.md** | What is connected, **how a measurement is actually made**, and the traps in the order they bite | Driving the bench, or picking up after a break |
| **09-whats-next.md** | The remaining work in order — SHG, then SFG, then the second axis — with the decisions already taken | Deciding what to do next |
| **10-open-questions.md** | What is undecided, what was decided, and who decided it | Something looks unresolved |
| **11-pipeline.md** | The deliverable path end to end, and where its time axis comes from | Before touching `pipeline.py`, or before trusting a wavelength |

Also at the repository root:

| File | What it holds |
|---|---|
| `README.md` | Install, run, and a summary of the key numbers |
| `CLAUDE.md` | Onboarding for an agent working on this project |
| `SESSION_LOG.md` | Chronological history. **Its HANDOFF block is the fastest way to see where everything stands** |
| `TSL775_HANDOFF.md` | The laser in full, including why USB will never work |

## Where to find a specific thing

| I want to know… | Go to |
|---|---|
| How to drive any of this by hand | **`scripts/bench.py`** — the working bench. `bench_gui.py` is the older tabbed one, kept because it has a Simulate path needing no hardware |
| How a capture becomes a wavelength trace | `11-pipeline.md`, then `src/rp_lockin/pipeline.py` |
| What is connected right now, and what is not | `08-the-bench.md` section 1 |
| How to run a sweep, step by step | `08-the-bench.md` section 2 |
| What to do next, and how to set up SHG | `09-whats-next.md` |
| How small a signal we can measure | `05-results.md` — sigma = 3.57 uV at the ADC, ~11 uV from the detector, so ~120 uV for SNR 10 |
| Why the drive frequencies are not round numbers | `03-frequency-plan.md` — the switching supply at 504.868 kHz and its harmonics |
| Why a plan with fewer modulation cycles is better | `03-frequency-plan.md` — `mod_cycles` multiplies the generator's frequency error |
| Why the board returns nothing when I set a frequency | `04-hardware-reference.md` — the generator is a DDS and does not work how it looks |
| Whether to trust `amplitude()` or `R` | `05-results.md`, and the docstring in `dsp.py`. R is biased +1.25 sigma; the projection is unbiased but assumes a steady phase |
| Whether a given test passed | `SESSION_LOG.md`, "STATUS AT A GLANCE" |
| Why a decision was made | `10-open-questions.md`, then the session log entry it names |

## Three conventions worth knowing

**Numbers are traceable.** Every measured figure names the step that produced
it, so a claim can be followed back to the measurement. Where a number was later
revised, the old value is marked superseded rather than deleted — several were
revised, and quoting a stale one would change a decision.

**Failures are recorded, not hidden.** Two Phase 1 steps failed. H2.5 was
downgraded by a human decision; H7.4 was a real defect and was fixed. Both are
written up as failures, because "passed" and "we decided it did not matter" are
very different things to inherit. The same applies to changes that were made and
then reverted — the park-at-start change of 2026-09-01 is in the log with the
measurement that killed it.

**A test fake must not be richer than the real object.** Two bugs shipped on
2026-09-01 because a stand-in offered a method the instrument did not have, so
the suite was green and the bench raised `AttributeError`. Build fakes from the
real class's surface, and assert that they do not exceed it.
