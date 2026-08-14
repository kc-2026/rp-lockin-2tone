# Documentation index — start here

A two-tone lock-in measurement on a Red Pitaya SIGNALlab 250-12: two AOM drives
mix in a DUT, a photodetector returns the intermodulation response, and we
deliver amplitude against laser wavelength across a ~1 second sweep.

## Status, in one line

**Phase 0 and Phase 1 are complete. Phase 2 has not started and is gated on a
planning session.** 102 offline tests pass. Nothing beyond loopback cables is
connected.

## What each document is for

| Doc | What it holds | Read it when |
|---|---|---|
| **01-overview.md** | Goal, requirements, operating point, channel allocation, the four phases | You are new, or need to know what is being built and why |
| **02-architecture.md** | How the software is shaped, the design decisions (ADRs), and four bugs worth remembering | Before changing anything structural |
| **03-frequency-plan.md** | Why the frequencies are what they are, and the arithmetic behind them | Before changing any frequency. **Never hand-roll one** |
| **04-hardware-reference.md** | How the board behaves and the traps it sets: specs, SCPI, memory layout, safety | While writing code that talks to the board |
| **05-results.md** | Every number this project has measured | You need a figure — noise floor, timing, rejection, repeatability |
| **06-phase0-offline.md** | What was built with no hardware, and the test suite | Understanding what is already proved offline |
| **07-phase1-loopback.md** | The loopback campaign, H1–H7, complete | Checking what was tested, how, and what it found |
| **08-phase2-hardware.md** | What Phase 2 needs, the U1–U12 risks, and proposed steps P1–P6 | Planning the move to real hardware |
| **09-phase2-plan.md** | *Does not exist yet* — the agreed plan, once the session has happened | — |
| **10-open-questions.md** | What is undecided, what was decided, and who decided it | Something looks unresolved |

Also at the repository root:

| File | What it holds |
|---|---|
| `README.md` | Install, run, and a summary of the key numbers |
| `CLAUDE.md` | Onboarding for an agent working on this project |
| `SESSION_LOG.md` | Chronological history. **Its "STATUS AT A GLANCE" section is the fastest way to see where every step stands** |

## Where to find a specific thing

| I want to know… | Go to |
|---|---|
| How small a signal we can measure | `05-results.md` — σ = 3.57 µV, so ≥36 µV for SNR 10 |
| Why the lock-in frequency is 991.821 kHz and not 1 MHz | `03-frequency-plan.md` |
| Why the board returns nothing when I set a frequency | `04-hardware-reference.md` — the generator does not work how it looks |
| What still has to be answered before hardware goes in | `08-phase2-hardware.md`, sections 1–3 |
| Whether a given test passed | `SESSION_LOG.md`, "STATUS AT A GLANCE" |
| Why a decision was made | `10-open-questions.md`, then the session log entry it names |

## Two conventions worth knowing

**Numbers are traceable.** Every measured figure names the step that produced
it, so a claim can be followed back to the measurement. Where a number was later
revised, the old value is marked superseded rather than deleted — several were
revised, and quoting a stale one would change a decision.

**Failures are recorded, not hidden.** Two Phase 1 steps failed. H2.5 was
downgraded by a human decision; H7.4 was a real defect and was fixed. Both are
written up as failures, because "passed" and "we decided it did not matter" are
very different things to inherit.
