# 00 — Documentation index

A lock-in measurement on a Red Pitaya SIGNALlab 250-12: an AOM gates 1550 nm
light at an audio-to-megahertz rate, a nonlinear sample mixes it, a
photodetector returns the product, and we deliver **amplitude against laser
wavelength** across a ~1 second sweep.

**If you just want to run it, you want `README.md`, not this folder.** This is
the reference and the reasoning.

## Status, in one line

**The instrument works, and it has measured the physics it was built for.**
**SHG was seen on 2026-09-03** — crystal in, APD on IN1, demodulating at 2 x f1,
a clear peak at ~1559 nm where phase matching was expected. **No blockers.**
What is left: write the SHG numbers down and measure the power-scaling control;
then SFG, which needs the second beam path wired; then the stepping laser for
the second axis.

## Reading order

**New to the project?** 01 → 08 → 11. That is what it does, what is plugged in,
and every way it has gone wrong.

**About to change code?** 02 → 11, then whichever reference covers the area.

**About to change a frequency?** 03, all of it. Never hand-roll one.

**Do not trust a trace?** 07, then `SweepReduction.describe()`.

| Doc | What it holds | Read it when |
|---|---|---|
| **01-overview.md** | Goal, requirements, operating point, channel allocation, how the project was sequenced | You are new, or need to know what is being built and why |
| **02-architecture.md** | How the software is shaped, what is trusted and what is not, and the design decisions (ADRs) | Before changing anything structural |
| **03-frequency-plan.md** | How the generator really works, how frequencies are chosen, and both models that turned out to be wrong | Before changing any frequency |
| **04-board-reference.md** | The Red Pitaya: specs, SCPI, front end, memory, deep captures, and the traps each sets | While writing code that talks to the board |
| **05-instruments.md** | The lasers, the detectors, the amplifier and the AOM — including why the laser's USB will never work and what the LAN recipe is | While working on anything that is not the board |
| **06-results.md** | Every number this project has measured | You need a figure — noise floor, timing, rejection, repeatability, dynamic range |
| **07-pipeline.md** | The deliverable path end to end, and where its time axis comes from | Before touching `pipeline.py`, or before trusting a wavelength |
| **08-the-bench.md** | What is connected, **how a measurement is actually made**, and the traps in the order they bite | Driving the bench, or picking up after a break |
| **09-whats-next.md** | The remaining work in order — SHG, then SFG, then the second axis — with the decisions already taken | Deciding what to do next |
| **10-open-questions.md** | What is undecided, what was decided, and who decided it | Something looks unresolved |
| **11-mistakes.md** | **Every wrong turn this project has taken**, what each one looked like, and what settled it | Before you conclude anything. Several of these were made twice |
| **12-test-campaigns.md** | Phase 0 (offline) and Phase 1 (loopback), complete, including the two steps that failed and the two that were skipped | Checking what was tested, how, and what it found |

Also at the repository root:

| File | What it holds |
|---|---|
| `README.md` | **How to install and use it.** Start here if you are operating the bench |
| `CLAUDE.md` | Onboarding for an agent working on this project |
| `SESSION_LOG.md` | Chronological history. Its **HANDOFF block** is the fastest way to see where everything stands |

## Where to find a specific thing

| I want to know… | Go to |
|---|---|
| How to drive any of this by hand | `README.md`, then `08-the-bench.md` §2 |
| What is connected right now, and what is not | `08-the-bench.md` §1 |
| What to do next, and how to set up SHG | `09-whats-next.md` |
| How a capture becomes a wavelength trace | `07-pipeline.md`, then `src/rp_lockin/pipeline.py` |
| How small a signal we can measure | `06-results.md` — σ = 3.57 µV at the ADC, ~11 µV from the detector, so ~120 µV for SNR 10 |
| Why the drive frequencies are not round numbers | `03-frequency-plan.md` — the switching supply at 504.868 kHz and its harmonics |
| Why the board returns nothing when I set a frequency | `04-board-reference.md` — the generator is a DDS and does not work how it looks |
| Why the laser will not answer over USB | `05-instruments.md` §1.1 — it is a hardware fault inside the instrument. Do not re-debug it |
| Whether to trust `amplitude()` or `R` | `06-results.md`, and the docstring in `dsp.py`. R is biased +1.25σ; the projection is unbiased but assumes a steady phase |
| Whether a given test passed | `12-test-campaigns.md` — every H step, with its result |
| Why a decision was made | `10-open-questions.md`, then the session-log entry it names |
| Whether this mistake has been made before | `11-mistakes.md`. It usually has |

## Four conventions worth knowing

**Numbers are traceable.** Every measured figure names the step that produced
it, so a claim can be followed back to the measurement. Where a number was
later revised, the old value is marked superseded rather than deleted — several
were revised, and quoting a stale one would change a decision.

**Failures are recorded, not hidden.** Two Phase 1 steps failed; H2.5 was
downgraded by a human decision and H7.4 was a real defect that was fixed. Both
are written up as failures, because "passed" and "we decided it did not matter"
are very different things to inherit. The same applies to changes that were made
and then reverted.

**A test fake must not be richer than the real object.** Two bugs shipped on
2026-09-01 because a stand-in offered a method the instrument did not have, so
the suite was green and the bench raised `AttributeError`. Build fakes from the
real class's surface, and assert that they do not exceed it.

**A regression test that has never failed proves nothing.** Check every new
test against the old code and watch it fail first.
