# 11 — Every mistake this project has made

**Why this document exists.** Almost nothing here failed loudly. This
measurement is a lock-in on a swept laser: the output is a smooth curve, and a
smooth curve is what you get whether the instrument is right or wrong. The
characteristic failure of this project is a **believable wrong answer** — a
clean trace, no error, no crash, and a number that is off by 2×, or 12%, or one
whole wavelength step.

So this is the catalogue. Each entry says what was believed, **what it looked
like**, and what settled it. Read it before changing anything; several of these
were made twice.

**Two conventions the project adopted because of this list:**

- **Failures are recorded, not hidden.** "Passed" and "we decided it did not
  matter" are very different things to inherit.
- **Superseded numbers are marked superseded, not deleted.** Several were
  revised, and quoting a stale one would change a decision.

---

## 1. Wrong models of the hardware

These are the expensive ones. Offline tests cannot catch them: the arithmetic
is right and the model is wrong.

### 1.1 "The generator replays exactly the N samples you load" — WRONG

**Believed until 2026-08-12.** The whole original frequency plan — a
250-sample buffer holding 80 carrier cycles, 5 of f1, 6 of f2 — rests on
`SOUR:FREQ:FIX = fs/N` replaying an N-sample buffer one entry per DAC clock.

**What it looked like:** a 50-sample buffer at 5 MHz produced **no output at
all** — min −2, max 4 counts. Not a bad signal. Nothing.

**Why offline testing could never have caught it.** The commensurability
arithmetic in `make_am_waveform` is correct. The model of the hardware is not.
Only the board could find it.

`make_am_waveform` and `plan_two_tone` are kept, because their arithmetic is
sound and their tests are worth having, with docstrings saying in capitals not
to drive the board with them. Use `make_am_table` / `plan_two_tone_grid`, or
`plan_exact_am` / `make_am_table_exact`.

### 1.2 "Every frequency must sit on a 15258.789 Hz grid" — ALSO WRONG

**Believed 2026-08-12 to 2026-08-28**, and written into every frequency the
code used, into four documents, and into a limitation notice recorded at
Kevin's explicit request.

The correction to 1.1 over-corrected. Because the full-table-at-`fs/16384` path
worked and the short-buffer path did not, the conclusion drawn was that the ASG
*always* traverses the full table at that one rate. **It does not.** The play
rate is free and quantised to 1 Hz; a short buffer is treated as the whole
table, so the frequency scales as 16384/N.

**What it looked like:** nothing. The grid plan works. It produced every Phase 1
result. It was needlessly constrained, not broken — which is exactly why it
survived sixteen days.

**The lesson:** *a correction derived from two data points is a hypothesis.* The
2026-08-28 session swept the play rate and the buffer length independently and
found the actual law in an afternoon.

### 1.3 "This is a 512 MB board" — WRONG, and Kevin caught it

Read from `/proc/iomem` and `MemTotal`, and a redesign around decimation 4 had
already started. **Both of those show the `mem=512M` capped view.** Kevin pushed
back with the datasheet and was right. `/proc/device-tree/memory/reg` is the
honest source: base 0, size `0x40000000`.

### 1.4 A device-tree instruction that would not have booted

The recorded instruction read `buffer@1000000 { reg = <0x1000000 0x20000000>; }`
— a 512 MB region based at the 16 MB mark, running to 528 MB and **straight
through the memory Linux is running in**. Corrected to base `0x20000000`, and a
backup step added. Never executed in the bad form.

A second error in the same section claimed recovery "requires an ext4 reader".
**It does not** — `/dev/mmcblk0p1` is vfat, so the device tree can be restored
from any Windows machine with the SD card in hand. That overstatement made the
change look far riskier than it was.

### 1.5 The planner recommended a board change that had been rejected

`describe_capture_plan()` recommended decimation 2 **plus the device-tree
move** for eleven days after the move was rejected, because `recommend()`
bounded by `MAX_DMA_MB` — the hypothetical enlarged region — instead of
`DMA_REGION_MB`, which is what exists.

**There were no tests on the planner at all**, which is why it drifted.
`tests/test_planning.py` now asserts both the recommendation and that the
output contains **no device-tree instructions**.

### 1.6 The attenuator, recommended three times and withdrawn three times

20 dB → 10 dB → 6 dB → "turn the drive down 4 dB" → **no attenuator**. All of
them were solving a problem this experiment does not have.

**The error:** assuming **small-signal** modulation — a carrier sitting at a
bias point with a small excursion, where the response is `dη/dP × ΔP` and
sitting on a diffraction peak means zero slope means no signal. That is the
standard lock-in picture and it is correct **for a different experiment**.

**This one is large-signal switching.** The drive is depth-1 AM, so the RF
envelope goes to zero every cycle and the AOM is switched fully on and off. The
envelope sweeps the entire diffraction curve; there is no operating point whose
slope matters.

**The tell was in what Kevin observed** — "less light either side" — which was
read as "you are at a stationary point, therefore no first-order response".
True for a small excursion; irrelevant when the excursion covers the whole
curve. **The two pictures give opposite advice about the same knob, and the
wrong one is the more natural thing to reach for.**

Do not reopen this. See `05-instruments.md` §3.1.

### 1.7 "302 V on the trigger" — counts compared against volts

`acquire_deep_fast` returns **raw ADC counts**. `pulse_shape()` treated them as
volts, and IN2 is on HV at ~90.9 counts/V, so 302 counts = **3.32 V — exactly on
spec**. The failure text even said "If it is ~1 V, IN2 is still on LV and
clipping", which actively misdirects, because the number was not in volts at
all.

Two more defects in the same function: the 10–90% rise time came out
**negative** (−199698 ns) because `t10` and `t90` were paired by *index* when
they are independent crossing lists — one extra crossing at either end shifts
every pair by a whole pulse. And a clipped record still yields clean-looking
widths and spacings, so clipping had to be reported separately or it was
invisible.

All fixed, `constants.py` gained `ADC_COUNTS_PER_V_*`, and **four offline tests
were added and each was checked against the OLD code and seen to fail.** That
matters: the first version of the rise-time test *passed* against the bug,
because a clean synthetic train cannot produce mismatched crossing lists. It was
tightened to start the record part way up an edge, which is what a real capture
does. **A regression test that has never failed proves nothing.**

### 1.8 "The detector is clipping" — a stale-DMA artefact

A probe reported `IN1: peak-to-peak 2056 counts, min -9, max 2047, mean 840.6`
and it was written up as the detector railing the ±1 V range.

**Not reproducible.** Re-measured over 40 captures on both couplings, IN1 sits
at roughly 0 V with about **1 count** of noise; zero captures out of 40 showed
peak-to-peak above 100 counts.

**The cause:** those probes ran immediately after a deep AXI capture, and
`acquire()` reads the *standard* buffer. `hardware.py` already warns that
reading the ring at the wrong offset "looks plausible" while being stale.

**Two rules came out of it.** Take a **median** across captures, never a
maximum — a single full-range record among a hundred is exactly what stale DMA
content looks like. And do not trust the standard buffer straight after a deep
capture.

### 1.9 The laser's "driver problem" — a red herring that cost days

Windows reported `CM_PROB_FAILED_INSTALL` on the laser's USB node, and no COM
ports were present. The 2026-08-26 handoff called it "the most concrete lead
this blocker has ever had".

**It was irrelevant.** The unit's EEPROM sets `IsVCP=0`, so a COM port is the
wrong end state anyway, and **USB is a hardware fault inside the instrument** —
the FT232H enumerates, the PC→chip half is healthy, and the instrument never
replies across 9 baud rates × 3 terminators, D2XX as UART, D2XX async and
synchronous FIFO, santec's own init sequence byte for byte, a power cycle, and
a passive listen. The identical commands over LAN work perfectly.

### 1.10 The trigger BNC was in the wrong socket

P2 sat at `WAIT` for 90 s through a sweep that emitted all 5001 pulses. A
read-only probe of both inputs during a live sweep settled it in one shot: IN2
was **dead flat**, 1 count peak-to-peak. The trigger was in the board's
**dedicated external-trigger connector**, not analog **IN2**.

Those are different things, and the design needs the train *digitised* —
`find_trigger_edges` runs on the IN2 trace, and the external pin would start a
capture while recording no train, losing both the measured time step and the
free clock-ratio check.

**The lesson, recorded at the time:** the probe took two minutes and replaced an
argument about wiring with a number. Reach for that earlier.

### 1.11 Measuring the OUT1/OUT2 phase the obvious way gives a random number

The obvious observable — the phase of the difference-frequency beat,
reconstructed from each channel's envelope — is **worthless here**. The two
envelopes are at different frequencies (328 and 393 cycles/table), so a common
capture-start offset does not cancel: it moves their phase difference by
2π·991821·Δt, and about 1 µs of trigger jitter randomises it completely. 72°
was measured that way and briefly believed.

**Use the carrier line** — identical on both channels at 5243 cycles, so a
common offset cancels exactly. Also worth knowing: the carrier moves 115° per
sample of inter-channel offset versus 1.43° for the difference frequency, so it
is an 80× magnifier — useful for *detecting* the problem, misleading about its
*size*.

### 1.12 A wedged SCPI server looks exactly like a failing cable

Median query latency 5.4 s, max 21.9 s, clustering near TCP retransmission
backoff sums, on an adapter with 11546 historical receive errors. Everything
pointed at hardware. The cause was ten SCPI connections opened in quick
succession by a probe — the thing `tests/hardware/conftest.py` already warned
about. Restarting the server gave a 0.050 s median.

**If the link ever looks broken again, restart the SCPI server before
suspecting hardware.**

---

## 2. Measurement errors — where numbers came out wrong

### 2.1 The noise floor, revised twice

An original **45.6 nV/√Hz → 2.96 µV → 30 µV** set appeared in this document and
three others. It was ~21% optimistic. **Use 51.7 nV/√Hz → σ = 3.57 µV → 36 µV
for SNR 10.**

### 2.2 A mean over a window swallows a spur

The first pass of H3.3 averaged the noise density over ±38 kHz around the
lock-in frequency, absorbed the 1010.895 kHz switching harmonic, and reported
**6.2 µV instead of 3.16 µV** — wrong by 2×, with nothing looking wrong.

**Use a median.** It ignores lines. And the **mean/median ratio is itself the
diagnostic**: it ran 2.1–2.4 at decimation 2, which is the tell that a line is
present.

### 2.3 Do not size a narrow line from a coarse spectrum

An early pass put the switching-supply family at **505.447 kHz with ~4 µV**.
Both wrong: a 450 Hz-wide line smeared across a 7.6 kHz bin reads about **8×
too low**, and the frequencies were bin centres rather than measurements. The
real numbers are **504.868 kHz and ~32 µV**.

### 2.4 Do not read broadband noise at high decimation

At the same input on the same afternoon, the floor near 991.8 kHz "improved" on
IN1 from 52 to 17 nV/√Hz going from decimation 2 to 64, while on IN2 it
"worsened" from 54 to 134. **At decimation 2 the two channels agree within 5%;
at decimation 64 they disagree by 60×.** Both trends are artefacts — folding of
2–60 MHz into the reduced band plus whatever averaging the FPGA applies.

High decimation *is* good for locating discrete lines: a real line holds its
frequency as fs changes, a folded one moves.

### 2.5 The demodulator's noise gain is NOT the nominal bandwidth

**4763 Hz measured against 2250 Hz nominal** — about 1.9×. Predicting σ from the
−3 dB bandwidth gives **2.45 µV against 3.57 measured: 46% low, in the
dangerous direction.** Pinned by
`test_quadrature_noise_gain_matches_filter_chain`.

Scale by **√ENBW**, not √(nominal bandwidth) — the latter is only good to 4%
because the ENBW/bandwidth ratio drifts with bandwidth.

### 2.6 An AC/DC ratio of 1.37, which is not a response

At 100 Hz the AC/DC amplitude ratio read 1.37. The DC-coupled record carries a
~27 count offset and holds 13.42 cycles at that decimation, so DC leaks across
bins into the signal bin and **depresses the DC-coupled reading**. An artefact
of a single-bin DFT, not of the instrument. Points at ≥300 Hz sit near whole
cycle counts and are unaffected.

### 2.7 `mean(R)` is a biased amplitude estimator

It reads **+1.25σ with no signal at all**, and the bias does not average away.
Use `LockinResult.amplitude()`, which projects onto a common phase and is
unbiased.

**Do not reach for `debiased_amplitude()`** — measured, it is *worse* than raw R
between 2σ and 6σ, which is exactly where our signals will sit.

### 2.8 An explanation withdrawn: the deep-read transfer rate

H6.2 attributed a 125 MB read's 6.7–11.2 s to "~125 round trips at ~50 ms
each". Reading the code showed **there are no such round trips** — the client
issues at most four GETs per capture and the board helper streams the reply
over one connection. **The measured times stand; the cause of the shortfall
against the 87 MB/s single-read figure is still unknown.**

### 2.9 Measuring a feature on a grid too coarse to hold it

**Made 2026-09-04, while checking whether the output was sampled too finely
for its own filter.** The chain's impulse response was measured directly off a
trace at the operating point and came out **450 µs FWHM**, against 222 µs from
`1/(2B)`. That reads as the resolution formula — and therefore the 100 pm limit
in ADR-0004 — being **2× optimistic**, which would have been a real finding.

**It was the measurement, not the filter.** At 2250 Hz the impulse is ~255 µs
wide and the output steps every 200 µs, so the feature spans barely two samples
and its FWHM is quantised to roughly half its own value. Holding the bandwidth
and raising the output rate to 50 kSa/s — the same filter, a finer ruler —
converges to **255 µs**, i.e. 1.15 × 1/(2B). The formula was fine.

**The tell was there and nearly missed:** the same measurement across
bandwidths gave `FWHM × bandwidth` = 0.58 at 250–1000 Hz but 1.01 at 2250 Hz.
A shape constant that is constant everywhere *except* at the operating point is
an artefact of the operating point's grid, not physics.

### 2.10 Summing only the positive autocorrelation terms

Same session. The number of independent values in a 5000-point trace was
estimated from the integrated autocorrelation time, computed as
`1 + 2·Σρₖ` over the terms that were **positive and above 0.02** — giving
τ_int = 1.75 and "3080 independent points per second".

This chain's autocorrelation **alternates in sign** (+0.21, −0.15, +0.10,
−0.06), because that is what a sharp lowpass does. Dropping the negative terms
counts the correlation and ignores the anticorrelation that partly cancels it.
All lags give **1.32**, and an independent route — the variance of block means
against block size — agrees at 1.26–1.34. The right answer is **~3800**, which
is also the one consistent with 2 × ENBW.

### 2.11 Comparing against the wrong instrument

**Made 2026-09-04.** Asked whether the output was sampled too finely for its
own filter, I answered that the traditional 5x rule is "written for a
single-pole RC", and used an RC as the foil throughout.

**Kevin: the SR865A does not use a simple RC, it uses a Gaussian FIR.** So the
comparison was against a filter nobody builds any more.

**The magnitude survived, the reasoning did not.** Matched at the same -3 dB
point, a Gaussian is **-3.8 dB** at the output Nyquist and an RC is **-3.6 dB**
-- indistinguishable, because a Gaussian is deliberately the gentlest possible
rolloff. So "gently-rolling filters have tails that fold, ours does not" is
still right; "this is about RCs" was not. Naming the wrong exemplar made the
argument look like an appeal to obsolete practice rather than to rolloff shape.

**And it hid the reciprocal question**, which is the one worth asking: if a
Gaussian has no overshoot and ours has 5-8%, what are we paying for the
sharpness? Nobody would have asked that while the comparison was against an RC,
which rings even less. That is now **Q40**.

### 2.12 "That output rate is a problem" -- when it is a specification

Same exchange, minutes later. Having computed that a Gaussian at our bandwidth
needs ~19.9 kSa/s of output, I presented that as a reason it "cannot simply be
dropped in".

**Kevin: why is 19851 Sa/s a problem? The ADC sample rate is much faster.**

Correct, and the framing was wrong. The converter runs at 31.25 MS/s;
`max_output_rate` allows **31250 Sa/s** at f1 = 915 kHz, and 25000 divides
31.25 MS/s exactly. The output rate was never the binding constraint. **The
5000 is R5 -- a line in the original brief asking for 4000-5000 points -- and
I had silently promoted a specification into a law of physics**, which made a
perfectly available option look impossible.

The general form, worth watching for: **when an option looks blocked, check
whether the thing blocking it is hardware or a number somebody wrote down.**

### 2.13 An unexplained residual, still open

P2.4's line-fit residual is **43.2 µs rms** over 5001 edges, with a minimum
pulse spacing of 178.125 µs against a 199.997 µs mean. Local spacing is clean,
so that suggests a step or discontinuity in the train rather than jitter. It
may itself be an artefact of the units and edge-pairing defects in §1.7 — check
the script before concluding anything about the laser.

### 2.14 The missed-edge panic came from a synthetic signal

Every anxiety about losing trigger edges at decimation 8 came from a **20 ns**
pattern that was an artefact of the ASG's 4 ns table step. A real santec trigger
is a **25 µs pulse** — 780 samples at decimation 8, with pulses ≥1560 samples
apart. The recorded cause of the 1.17% interval mismatch was off by a factor of
a hundred and was **never explained**; the question closed because the
requirement vanished, not because the fault was understood. If some future
design needs the whole train recovered intact, that fault is still there.

---

## 3. Software bugs, all silent

Every one of these produced a plausible wrong answer rather than a crash. Every
one now has a test, and several of those tests exist *only* because the bug was
real. **Do not delete a failing test to make the suite green.**

### 3.1 Found offline, in Phase 0

| Bug | What it looked like |
|---|---|
| **Filter tap explosion** | A single FIR setting a 2 kHz corner at 250 MS/s needs ~2.4 M taps. The code capped taps and silently substituted a filter **~100× too wide**, inflating the noise floor and drooping the passband. Fixed with multistage decimation |
| **Settling vs group delay** | An FIR is valid only after the *full* impulse response has entered, not half of it. Trimming by group delay left step-response ringing **at exactly the cutoff frequency** — a few percent wobble on R that looks like real noise |
| **Time-axis offset** | The axis must compensate the trimmed settling samples **and** the group delay. Getting one right shifts the whole trace ~10 ms at 5000 Sa/s — and since the wavelength calibration comes from trigger edges in the same record, that biases every wavelength in the sweep |
| **Clipping normalisation** | The emulator's clipping protection rescaled the synthesised waveform but not the recorded ground truth, so a loopback test would have reported a **phantom 2× amplitude error** |
| **Streaming block boundaries** | Must be **bit-exact**, not approximately equal. They are periodic, so any artefact lands identically in every sweep and looks like DUT structure. `test_chunked_equals_single_shot` pins exact equality — keep it exact |
| **A Windows-only test hole** | `test_long_record_memory_bounded` imported Unix-only `resource` and failed at import, so its assertions never ran. Moved to stdlib `tracemalloc`. Do not "simplify" it back |

### 3.2 Found by joining the pipeline together, 2026-08-25/26

The project passed 180 tests without ever having run the measurement it exists
to make. **Joining the components found five defects that no component test
could have seen, because they all live in the seams.**

**Both trigger polarities counted as pulses.** `find_trigger_edges` returns
rising *and* falling edges, and a real trigger is a 25 µs pulse, so every logged
point makes two edges. A step averaged over both is near **half** the truth,
which compresses the entire wavelength axis 2× and still draws a clean trace.
**This would have been live on the first real sweep.** Pass
`polarity="rising"`.

**The emulator only made square waves**, which hid the above completely — a 50%
duty cycle no laser emits. `make_trigger_pulses` produces the real shape. *An
emulator that cannot reproduce the failure cannot test for it.*

**A guard that read stronger than it was.** `check_alignment` documents two
checks, count and span. Under the pipeline's default step the span check is
**vacuous** — the step is derived from the span, so it compares a number against
itself. Verified: a capture that misses the first two pulses, where every
wavelength really is shifted, still reports a span error of exactly **0.00%**.
Only the **count** check catches it, and `describe()` now says so at the point
of use, because the summary otherwise prints two matching spans that read like
corroboration.

**A transport that could not resynchronise.** `santec.py`'s buffer persisted
between queries, so a read timing out mid-reply left the remainder behind and
every later query returned the tail of the previous one — plausibly, without
raising. `hardware.py` records the identical failure against the board. Fixed
with `resync()`.

**A front end that could not differ between channels.** `_reapply_front_end`
forced both channels to one coupling and gain after every `ACQ:RST`, so IN2
could not stay on HV. That made P2 impossible to run as specified, and it would
have presented as **"the laser is not triggering"** rather than as a range
error.

Three more from the same work:

- **Dividing by N instead of (N−1)** when deriving the step is an error of 1
  part in N — which sounds negligible and is **exactly one whole step of
  accumulated drift by the far end**. 200 µs at the end of a 5000-point sweep.
- **Pre-roll shorter than the filter's settling yields NO pre-sweep points.**
  Settling trims 113 output points, 22.6 ms; an 8 ms pre-roll leaves nothing,
  and `n_before == 0` looks exactly like a mapping bug. Use
  `recommended_preroll()` (45.2 ms).
- **The recommended TAIL makes the trace legitimately overrun the laser's
  table**, and `map_to_wavelength` refused an overrun by default. Those points
  are correctly NaN; `overrun_tol` now defaults to `recommended_tail()`.

### 3.3 Found on the bench, 2026-09-01

**A sweep silently reverted to step mode between run 1 and run 2.** The laser
accepts writes it is not in a state to honour and reports nothing;
`configure_sweep` slept a fixed 0.5 s after `:WAV:SWE 0` and verified **one of
seven** settings. From cold every write lands, so **the first run always
worked**. Step mode ran ~2000× slow — measured, 28 nm in ten minutes against a
configured 100 nm/s. Now polls `:WAV:SWE?` and verifies all seven.

**A sweep started before the laser reached its start** covered 80.96 nm instead
of 100, at *exactly* the right speed and step: 4048 pulses at 200.00 µs against
5001 expected. The bench called it a 1.24× fast sweep because `check_train`
compared **spans** and never checked the **interval**. A short *range* and a
fast *sweep* are different faults and now report differently.

**`mod_cycles` multiplies the generator's frequency error.** 915 kHz planned as
12 cycles demodulated ~0.69 Hz off and drew **a smooth arch from −76 mV through
zero to +134 mV across the sweep**. R was flat at 134 mV throughout — the arch
was `A·cos(phase)`. See §2.7 and `03-frequency-plan.md` §2.

**The mouse wheel changed the sweep mode.** `ttk.Combobox` has a *class*
binding that steps the value on the wheel, and the rail scrolls on the wheel
too — so any box the pointer passed over changed silently. That is one way a
run ended up in step mode. `wheel_safe()` now wraps every combobox and
`_wheel_proof` asserts the pass covers all of them.

### 3.4 Found on the bench, 2026-09-03

**Two workers were never started, and the pump ate its own results.** In
`dr_bench.py` the worker threads were constructed but never `.start()`ed, *and*
`_pump` treated `(kind, payload)` result tuples as `Job` objects, so the first
result killed the pump. Symptom: "connect shows nothing on log". Four regression
tests fail against the previous commit.

**A test assumed settling is monotonic in bandwidth.** It is not — 113 → 48 →
70 → 98 output points across the range, because the transition width is floored
at 0.10 × output Nyquist. The test was rewritten to assert the readout reports
the real number rather than a modelled one.

---

## 4. Changes that were made and then reverted

**Park the laser at its sweep start before sweeping** (`19729d0`, `9cb39fb`),
reverted at **`61088d0`**.

The fault it addressed is real — a sweep started early covers a shorter range
with nothing looking wrong. The fix was worse: writing `:WAV` moved the laser
correctly (1600 → 1500 nm in 0.41 s, read back on target) and then `:WAV:SWE 1`
produced **no trigger train at all**, twice. That is **Q32**, still unexplained.

It also shipped two bugs on the way:

- `park_at_sweep_start` called `set_wavelength_m`, which exists on
  `SantecTSL`. The bench uses `TSL775`, which has no setters. **The suite was
  green because the test fake had been modelled on the wrong driver.**
- `wait_until_at_start` blocked forever, on the assumption that Configure
  returns the laser to its start. It does not — the laser sat at 1600 nm for
  60 s. It now *reports* arrival rather than raising, and both callers warn and
  continue.

**The rule that came out of it: a test fake must not be richer than the real
object.** Build fakes from the real class's surface, and assert that they do not
exceed it (`test_the_fakes_offer_no_more_than_the_real_driver`).

---

## 5. Process mistakes

### 5.1 The work had already been done, in another folder

The laser was solved on **2026-08-21** in `Desktop\TSL-775 Test\` — a complete
working driver, a 27 KB handoff, and verified sweep data. **The 08-25 and 08-26
sessions never saw it**, went on describing the laser as an unsolved blocker,
and recommended a driver reinstall that could not possibly have worked.

**Check whether the work has already been done elsewhere.**

### 5.2 A correction that was itself wrong

Kevin's Q20 answer — that the laser logs wavelength against time — was recorded
as **wrong in four documents**. It was not. He described the semantics; the
manual describes the wire format; both are true. The times are reconstructed
rather than transmitted, which is a real distinction and worth stating, but it
does not make his description wrong.

**A manual describing something differently from how a person described it is
not the same as the person being wrong.**

### 5.3 Reporting a state that had already gone

Two `bench.py` PIDs were reported as *currently* holding the laser connection.
They had exited six minutes earlier and `netstat` had shown no connection. The
claim was retracted when Kevin pointed out there were no bench windows open.

**Check the timestamp on evidence before describing it in the present tense.**

### 5.4 Spending a consumable while diagnosing

A laser port was probed twice during diagnosis, which is exactly what takes it
from accepting to dropping SYNs (Q33). Separately, a connect was attempted
while Kevin's bench held the session. **Neither was necessary.**

### 5.5 Hypotheses offered before checking

- A 50 Ω / Hi-Z divider was proposed to explain a factor of 2 in the voltages.
  Kevin corrected it: the lock-in's input impedance is 10 MΩ. Withdrawn.
- Output semantics and graph convention were conflated in the same discussion —
  "what `SOUR:VOLT` means" and "what the trace axis means" are two separate
  questions with two separate answers, and running them together produced a
  confident statement about neither.

**Verify before theorising about hardware.** Several diagnoses this project
recorded as fact did not survive being checked.

### 5.6 Environment mistakes worth not repeating

- **Do not put the project in a OneDrive folder.** It lives at
  `C:\dev\rp-lockin-2tone`. OneDrive scanning a `.venv` is slow, and the
  previous machine's nested-repo incident started that way.
- **Do not run from the stale Desktop snapshot.** It has no `.venv` and falls
  further behind every commit. Starting a GUI from it fails with
  `ModuleNotFoundError: No module named 'numpy'` — which names the interpreter
  but not the real problem, which is the folder.
- **The repo URL was recorded nowhere in the repo** and had to be asked for
  during a machine rebuild — exactly when it is needed. It is in `README.md`
  now.

### 5.7 Escapes written through a scripting layer, four times

Editing files by generating a patch script through another string-processing
layer wrote real control characters into tracked text:

- `\0000` inside a Python string is an **octal escape** — it wrote a NUL byte
  and turned two documents binary.
- `\r` in the phrase "identical `\r` delimiter" wrote a **carriage return**
  into a markdown table.
- `\n` in an f-string wrote a **real newline** and broke the file's syntax.
- `scripts\bench.py` in a `.cmd` file wrote a **backspace**, silently turning it
  into `scriptsench.py` — a launcher that looked right in a diff and could not
  possibly work.

The first three were caught by hand. **The fourth was not**, because the check
in use only looked for NUL and CR. Nobody notices a backspace by reading.
`tests/test_repo_hygiene.py` now rejects every control character except tab and
newline, and checks that the launchers name files that exist.

---

## 6. The habits that came out of all this

1. **When a claim is corrected, sweep the whole repo for it.** Stale numbers
   propagate; the 2.96 µV noise floor lived in four documents.
2. **Verify before theorising about hardware.** A two-minute probe beats an
   afternoon of argument about wiring.
3. **A test fake must not be richer than the real object.**
4. **A regression test that has never failed proves nothing.** Check every new
   test against the old code and watch it fail.
5. **An emulator that cannot reproduce the failure cannot test for it.**
6. **Take a median, not a maximum**, over repeated measurements.
7. **Read back every write.** On both instruments, a misspelled setting returns
   zero bytes exactly like a correct one.
8. **Numbers are traceable.** Every measured figure names the step that
   produced it, so a claim can be followed back to the measurement.
