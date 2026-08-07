# Open questions

Resolve these as they come up. When one is settled, move the answer into the
relevant doc and note it in `SESSION_LOG.md`.

## Blocking Phase 1

| # | Question | Where it gets answered |
|---|---|---|
| Q1 | Red Pitaya OS version | H1.1 |
| Q2 | Are the SCPI commands in `hardware.py` correct for that version? | H1.5 |
| Q3 | Does the generator accept a 250-sample arbitrary buffer? | H2.1 |
| Q4 | Does `SOUR:TRig:INT` start both channels synchronously? | H2.4 |
| Q5 | Is Deep Memory Generation available on this OS? | H5.1 |

## Affects measurement quality

| # | Question | Notes |
|---|---|---|
| Q6 | Is the OUT1/OUT2 relative carrier phase repeatable across restarts? | If not, the difference-frequency phase varies sweep to sweep and needs referencing. No spare input channel for a pickoff — would need another approach. |
| Q7 | Are IN1 and IN2 sample-aligned? | A fixed skew between signal and trigger biases every wavelength assignment. Measure, do not assume. |
| Q8 | What is the real noise floor at 1 MHz? | H3.3. This is the number that predicts whether the measurement works. |
| Q9 | Does the DUT response roll off at 1 MHz? | Physics, not measurable in loopback. Lower difference frequencies are available — see `03-frequency-plan.md`. |

## Needs a human decision

| # | Question |
|---|---|
| Q10 | Confirm the τ change from 30 µs to 71 µs is acceptable. It is quieter, non-aliasing, and delivers the same 5000 points — but if there is a reason to match a commercial lock-in's convention, it is one parameter. |
| Q11 | Photodetector output amplitude, to set input range and coupling. |
| Q12 | Safe drive levels for the amplifier chain and AOMs — Phase 2 gate. |
| Q13 | Is averaging across repeated sweeps wanted? Changes buffer management and whether phase must stay coherent between sweeps. |
| Q14 | Is a GUI actually wanted, and what would it show? |
| Q15 | Output file format for the traces. Currently `.npz`. |

## Deferred

| # | Question |
|---|---|
| Q16 | Does anything need continuous analog output of the demodulated signal? Only this would justify revisiting FPGA — see ADR-0001. |
| Q17 | Phase 2 success criteria. Deliberately not set until Phase 1 results are in. |
