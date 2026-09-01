# Session log

Append a new entry at the end of every session. This is the only continuity
between agent sessions — a fresh agent must be able to resume from it without
re-deriving anything.

Template:

```
## YYYY-MM-DD — <who> — <one-line summary>
**Goal:**
**Did:**
**Learned:**
**Broke / still broken:**
**Next:**
```

---

## HANDOFF / STATUS — updated 2026-08-28, read this first

**Both blockers from the 2026-08-26 handoff are GONE.** The board answers, the
laser answers, and the whole environment has been rebuilt on a new control PC.
Phase 0 and Phase 1 remain complete; the end-to-end pipeline exists and is
checked against known truth. Phase 2 is still gated on a planning session.

**The live task is the first real two-instrument measurement.** What stands in
the way is no longer access — it is two wiring/units issues, both found on
2026-08-28 and both written up below.

### Where to look

| Want | Go to |
|---|---|
| What each doc is for | `docs/00-index.md` |
| The deliverable path, in code | `src/rp_lockin/pipeline.py` |
| Any measured number | `docs/05-results.md` |
| What the board does, and the traps it sets | `docs/04-hardware-reference.md` |
| Phase 1, step by step | `docs/07-phase1-loopback.md` |
| Phase 2: risks U1–U12, steps P1–P6 | `docs/08-phase2-hardware.md` |
| Anything undecided | `docs/10-open-questions.md` |
| Agent ground rules and traps | `CLAUDE.md` |
| **The TSL-775 laser, in full** | **`TSL775_HANDOFF.md` — see "BLOCKER 2" below** |

---

### THE EXPERIMENT IS TWO LASERS

- A **fine sweeper** (TSL-775): ~1 s, 5001 points, carries the trigger BNC into
  IN2, and supplies the wavelength axis from its own log.
- A **stepper** (TSL-770): 11 discrete wavelengths, one per sweep. No trigger,
  no log — set it, let it settle, read `:WAVelength?`.

The deliverable is an **11 × 5000 map**. `SweepSeries` / `write_series` in
`pipeline.py` handle the set.

**Naming collision.** The docs' **f1/f2** are the AOM *modulation* frequencies
(5.004883 and 5.996704 MHz). Kevin's **freq1/freq2** are the *lasers*. Nine
orders of magnitude apart, same names.

**Serial control of the stepping laser is PARKED** at Kevin's request.

---

### THE CONTROL PC IS NEW, as of 2026-08-27/28

The old machine is gone, and with it its venv, its clone, and its SSH key. The
rebuild is recorded in the 2026-08-28 entry. What a fresh machine needs:

```bash
winget install --id Python.Python.3.13 --scope user
git clone https://github.com/kc-2026/rp-lockin-2tone.git C:\dev\rp-lockin-2tone
cd C:\dev\rp-lockin-2tone
python -m venv .venv && .venv\Scripts\python -m pip install -e ".[dev]"
```

**The repo URL was recorded nowhere in the repo** and had to be asked for during
a rebuild — exactly when it is needed. Keep it in `README.md`.

**Do not put the project in a OneDrive folder.** It lives at
`C:\dev\rp-lockin-2tone`. OneDrive scanning a `.venv` is slow, and the previous
machine's nested-repo incident started that way.

**Verified on the new stack 2026-08-28:** Python 3.13.15, numpy 2.5.2,
scipy 1.18.1, pytest 9.1.1 — **232 passed, 1 skipped, ~4 min**. Nothing in the
suite needed changing for a stack several versions newer than it was written on.

**`core.autocrlf=true`** (the Git for Windows default) gives
`scripts/rp_fastread.py` a CRLF shebang. Harmless as documented, because the
helper is launched as `python3 <file>`; but `./rp_fastread.py` would fail with
`bad interpreter: python3^M`. A `.gitattributes` would settle it permanently.

---

### BLOCKER 1 — DEAD. The board is reachable again.

The Ethernet link that had not come up since 2026-08-25 works on the new PC:
1 Gbps, board at `169.254.56.245` via `rp-fffe42.local`, ping 1 ms. **Q28's
cause was never identified**, and the evidence pointed at the old PC's port;
replacing the machine removed it either way. If it recurs, put the board on a
switch rather than a direct cable — that also ends the link-local churn.

SCPI (port 5000) and key-based SSH both work. **A new SSH key was generated on
the new PC** and installed by Kevin; the old one is gone.

**The fast-read helper is deployed and is now the NEW build** — the one with
zero-copy sends, TCP_NODELAY and per-GET timing, which had never actually been
on the board. It still lives in `/dev/shm`, so **it disappears on every reboot**.

### BLOCKER 2 — DEAD. The laser works, over LAN.

**The laser has never answered over USB because USB is a hardware fault inside
the instrument.** Not a driver problem, and not fixable on the host. Established
2026-08-21 in a separate effort whose notes live in `TSL775_HANDOFF.md`, and
confirmed on the new PC 2026-08-28.

The evidence, so nobody re-debugs it: the FT232H enumerates correctly and the
PC→chip half is provably healthy, but the instrument never replies — across 9
baud rates × 3 terminators, D2XX as UART, D2XX async and synchronous 245 FIFO,
santec's own init sequence replicated byte-for-byte, a full power cycle, and a
3 s passive listen. The **identical commands with the identical `\r` delimiter
work perfectly over LAN**. The fault is between the FT232H and the internal
controller. It is a warranty item for santec.

**Windows will show `CM_PROB_FAILED_INSTALL` on the USB node. Ignore it.** This
unit's EEPROM sets `IsVCP=0`, so a COM port is the wrong end state anyway. The
2026-08-26 handoff called that driver state "the most concrete lead this blocker
has ever had". It was a red herring, and chasing it cost real time.

**Keep the USB cable plugged in** — the FT232H is self-powered from the
instrument, so its presence in Device Manager is the fastest proof the laser has
power, which separates "network problem" from "someone turned it off".

**The working path:** raw TCP to `10.101.0.197:5000`, ASCII, bare CR. **Open one
connection and hold it** — roughly one reconnect in four dies with
`WinError 10054`, while a single held session went 20/20.

**The LAN interface drops out entirely, and this recurs.** Symptom: no ping, no
TCP. Recovery is to reapply the LAN settings on the front panel (Other →
Communication → LAN). It happened again on 2026-08-28 and the front panel fixed
it in one go. Run the §3.3 triage in `TSL775_HANDOFF.md` each time — but note
its "no ARP entry" indicator is **vacuous in this topology**, because the laser
is off-subnet and routed, so it would never have an ARP entry either way.

`santec.py` **already has a LAN transport** (`SantecTSL.over_lan`), and
`p2_trigger_check.py` already takes `--lan`. Anything implying the driver is
serial-only is wrong.

---

### WHAT IS MEASURED AND WHAT IS NOT, as of 2026-08-28

**The laser sweep is verified end to end, three times, reproducibly:**

| Check | Result |
|---|---|
| Point count | 5001 |
| Span | 1499.9999 → 1600.0002 nm, endpoints within 0.10 pm |
| Uniform step | worst deviation 0.40 pm on a 0.02 nm step |
| Linear in time | max 0.255 pm, rms 0.104 pm |
| Fitted rate | +100.0000 nm/s against 100.0 commanded |
| Trigger interval | **200.0 µs → 5000 Hz** |

**The electrical trigger has now been observed** — the item
`TSL775_HANDOFF.md` §7.3 called its top priority — and it holds up:

| P2 check | Result |
|---|---|
| P2.2 capture triggered | PASS — 33554432 samples at 31.2500 MS/s |
| P2.1 pulses in the record | **5001 — exactly the laser's log length** |
| P2.1 pulse width | **24.997 µs, sd 0.001** against the 25 µs spec |
| P2.1 spacing | mean 199.997 µs |
| P2.5 pulses lost at decimation 8 | **none** |
| P2.4 measured step | 199.9861 µs |

**Q24 is ANSWERED.** `:TRIG:OUTP:SETT` = 0 on the TSL-775 means *periodic in
wavelength*. The readback alone cannot settle it — a 0 is a 0 under either
manual — but the sweep runs at 0 and produces sub-picometre-linear points at
exactly 0.02 nm spacing, which is only consistent with that encoding. **The
TSL-775 manual is right and the TSL-770's table is the erroneous one.** It
matters less than feared: at constant sweep speed, uniform-in-wavelength is also
uniform-in-time, which is what `reduce_sweep`'s span/(N−1) step needs.

**Q26 stays dead, and P2 corroborated it anyway** — 5001 recorded pulses against
5001 logged points is 1:1.

---

### WHAT IS ACTUALLY BROKEN — one real defect, one artefact

**1. `p2_trigger_check.py` compares COUNTS against VOLTS.** It is the only P2
failure, and it is the script's fault, not the hardware's:

```
[ FAIL ] P2.1 high level: 302.000 V, expected ~3.3 V
```

`acquire_deep_fast` returns **raw ADC counts** — its own docstring says
"amplitude 361 counts". `pulse_shape()` treats them as volts. IN2 is on HV
(±20 V), and at ~1817 counts/V on LV that is ~90.9 counts/V on HV, so
**302 counts = 3.32 V and idle 6 counts = 0.07 V**. The trigger is exactly on
spec. Two related defects in the same function: the **10–90 % rise time comes
out NEGATIVE** (−199698 ns) when the edge is faster than one sample, and the
failure text ("If it is ~1 V, IN2 is still on LV and clipping") actively
misdirects, because the number is not in volts at all.

**Fix the units before trusting any other number this script prints.**

**2. A probe of IN1 read full-scale, and it was an ARTEFACT. Read this before
re-measuring anything with the standard buffer.**

A first pass reported `IN1: peak-to-peak 2056 counts, min -9, max 2047,
mean 840.6` and was written up as the detector clipping the +/-1 V range. **It is
not reproducible.** Re-measured properly -- 40 captures, both couplings:

```
DC:  IN1 median p-p 1.0  max 9.0  mean -7.4 counts     IN2 p-p 1.0  mean 7.0
AC:  IN1 median p-p 2.0  max 2.0                       IN2 p-p 1.0
     captures with p-p > 100 counts: 0 of 40
```

**IN1 sits at roughly 0 V with about 1 count of noise.** There is no 840-count
offset and no clipping.

**The likely cause of the bad reading, and the lesson:** those probes ran
immediately after a deep AXI capture, and `acquire()` reads the standard buffer.
`hardware.py` already warns that reading the ring at the wrong offset "looks
plausible" while being stale. A single full-range capture among a hundred, with
the maximum taken across all of them, is exactly what stale DMA content looks
like. **Take a median across captures, never a maximum, and do not trust the
standard buffer straight after a deep capture.**

**What this does NOT establish.** IN1 reading ~0 V with the shutter CLOSED is
equally consistent with a healthy detector in the dark and with nothing
connected at all. **The detector has never been shown to respond to light.**
That needs the shutter open, which is a decision for Kevin, and the power
question below comes first.

The standing advice to **AC-couple IN1** still holds on its own merits -- the
PDA05CF2 is 0-10 V unipolar into Hi-Z and Q25 measured AC coupling as free -- but
it is not currently fixing an observed fault.

### OPEN, AND WORTH A LOOK

**P2.4's line-fit residual is 43.2 µs rms**, and the pulse spacing has a
**minimum of 178.125 µs against a 199.997 µs mean**. Local spacing is clean, so a
43 µs residual on a line through 5001 edges suggests a step or discontinuity in
the train rather than jitter. **This is the measurement the wavelength axis rests
on (U11, Q19), so it needs explaining before the axis is trusted.** Not yet
investigated. Note it may itself be an artefact of the same units/edge-detection
defects above — check the script before concluding anything about the laser.

---

### Judgement calls not to relitigate

- **No attenuator.** Withdrawn three times over.
- **Decimation 8**, and **no device-tree memory move**.
- **AM with carrier**, not a pure product — hardware-verified by H2.2.
- **H2.5 failed and was downgraded** by Kevin; the deliverable is amplitude only.
- **No averaging** (Q13) and **CSV output** (Q15), both Kevin's decisions.
- **Do not "fix" the RF drive level.** Kevin's CW tuning is correct because the
  drive is depth-1 AM and the AOM is switched fully on and off.
- **Do not chase the laser's USB.** It is broken inside the instrument.

### Habits this project learned the hard way

- **When a claim is corrected, sweep the whole repo for it.**
- **A manual describing something differently from how a person described it is
  not the same as the person being wrong.** Kevin's Q20 answer was recorded as
  wrong in four documents, and was not.
- **Verify before theorising about hardware.** Several diagnoses this project
  recorded as fact did not survive being checked. The laser's "driver problem"
  is the most expensive example.
- **Check whether the work has already been done elsewhere.** The laser was
  solved on 2026-08-21 in a folder on the Desktop, while two later sessions went
  on describing it as an unsolved blocker and recommending a driver reinstall.

### Still wanted from Kevin

- An **optical damage threshold** for the PDA05CF2 — the manual gives saturation
  (~0.96 mW) but no damage figure. **The laser's own setpoint was found at
  12 dBm ≈ 15.8 mW on 2026-08-28, roughly 16× that saturation level**; it was set
  back to the validated 4.00 dBm. This number now matters.
- Whether there is a **second ZHL-1-2W+**; the design needs two
- **Q17**, the Phase 2 success criteria, and the **unattended-operation
  boundary** — both deferred at his request
- **Do not restart the board's SCPI server.** That is Kevin's, by request, and
  the deny list enforces it
---

## 2026-08-07 — Claude (Cowork, scoping session) — project bootstrap

**Goal:** Establish feasibility, fix the measurement architecture, and hand a
Claude Code agent a working starting point.

**Did:**
- Investigated `marceluda/rp_lock-in_pid` at source level. It cannot serve this
  measurement: reference generator capped at 49.6 kHz, output filter capped at
  1.2 kHz, built for a different board on a five-year-old toolchain, and it
  disables the stock signal generator. Reasoning recorded in ADR-0001
  (`docs/02-architecture.md`).
- Established that this is a burst measurement (one trace per laser sweep), so
  software demodulation over Deep Memory Acquisition is sufficient. No FPGA.
- Derived the frequency plan: f1 = 5 MHz, f2 = 6 MHz, |f2−f1| = 1 MHz, exact
  250-sample buffer. See `docs/03-frequency-plan.md`.
- Built and validated the DSP core, waveform construction, capture planner and
  DUT emulator. 62 offline tests pass.
- Wrote `hardware.py` from documentation. **Never executed.**

**Learned (the expensive parts):**
- A single FIR cannot set a 2 kHz corner at 250 MS/s — needs ~2.4M taps. The
  first implementation silently capped taps and used a filter ~100x too wide.
- FIR settling is the full impulse-response length, not the group delay.
  Trimming by group delay leaves ringing at the cutoff that mimics real noise.
- The output time axis must compensate both the trim and the group delay, or
  the whole trace shifts ~10 ms — which would bias every wavelength assignment.
- Streaming block boundaries must be bit-exact, not approximately equal. They
  are periodic, so any artefact lands identically in every sweep.
- Emulator clipping protection must rescale the ground truth too, or loopback
  tests report a phantom 2x amplitude error.
- Filter settling costs ~108 output points (22 ms) at 5000 Sa/s. The capture
  must pre-roll before the laser trigger.
- The naive buffer rule N = fs/f_mod is wrong whenever that is not an integer;
  f2 = 6 MHz needs 125 samples, not 41.67.

**Broke / still broken:**
- `hardware.py` is entirely unverified. Highest risk item.
- Deep Memory Generation not implemented — blocks full-length emulated sweeps.

**Next:** Test plan H1 — validate the SCPI transport against the real board,
starting by recording the OS version.

---

## 2026-08-10 — Claude (Claude Code) — first hardware contact; H1 essentially done

**Goal:** Onboard, validate the repo, get the board talking, and begin H1.

**Did:**
- Fixed the offline suite on Windows. `test_long_record_memory_bounded`
  imported Unix-only `resource` and failed at import, so its assertions never
  ran. Moved to stdlib `tracemalloc`. Verified it still guards: 346 MB at
  `CHUNK_SAMPLES = 1<<22` versus 4295 MB at `1<<26`, against an 800 MB bound.
- **Q10 decided by Kevin: τ stays at 71 µs / 5000 points.** Also corrected the
  spec's claim that τ is "configurable" — `dsp.py` clamps bandwidth to
  0.9 × output Nyquist and silently drops a wider request. Deliberate.
- H1.1–H1.6 complete except the deep-memory path. Details below.
- Verified `setup_acquisition` and the `setup_generator` command set against
  the board by set-then-read-back.
- **Found that `setup_am_generator` cannot work.** See below.

**Learned (the expensive parts):**

1. **The ASG does not replay a short buffer.** It always traverses a fixed
   16384-entry table; `SOUR:FREQ:FIX` is the traversal rate. `make_am_waveform`
   returns `fs/N` on the opposite assumption. Measured: a 50-sample buffer at
   5 MHz produces *no output at all* (min −2, max 4 counts). Loading the full
   table and playing at `fs/16384` = 15258.789 Hz reproduces it exactly —
   confirmed at 0.0153, 80.0018 and 0.9918 MHz, each dominant with the next
   line ≥53 dB down. **This is the biggest open item.** The offline tests could
   never have caught it: the commensurability arithmetic is right, the model of
   the hardware is wrong.
2. **The board has 1 GB, but `mem=512M` hides half of it from Linux.** I first
   concluded from `/proc/iomem` and `MemTotal` that it was a 512 MB board and
   started redesigning around decimation 4. Kevin pushed back with the
   datasheet and was right. Both of those sources show the capped view.
   `/proc/device-tree/memory/reg` is the honest one: base 0, size 0x40000000.
   The upper half, `0x20000000`–`0x3FFFFFFF`, is free for DMA and costs Linux
   nothing — so decimation 2 and the full 1 s capture are fine.
3. **The old H6.1 instruction was unsafe.** It based a 512 MB region at
   `0x1000000`, running to 528 MB and through Linux's own memory. Corrected to
   base `0x20000000`, plus a backup step: a bad device tree will not boot.
4. **A wedged SCPI server mimics a failing network.** Rapid reconnects (my
   probe opened ten in a row, which `conftest.py` explicitly warns against)
   left query latency at a 5.4 s median, max 21.9 s, in a pattern that looked
   exactly like TCP retransmission on a bad cable. Restarting the SCPI server
   fixed it: 0.050 s median. Never open a connection per command.
5. **A read timeout desynchronises the connection permanently** and yields
   believable-but-wrong values — `ACQ:AXI:SIZE?` appeared to return the region
   base. Use `*IDN?` as a sync token.
6. **Unsupported commands return zero bytes**, with no error string. A
   misspelled *setting* is indistinguishable from success, so write paths must
   be validated by reading back.
7. `*IDN?` cannot identify the model — no model name in the string. Confirmed
   the 250-12 by case label and by `monitor -f` → `z20_250`.
8. `ACQ:DATA:Units` defaults to `VOLTS` while `query_binary_int16` decodes
   int16. Wrong pairing gives the right sample count with meaningless values.
   `RAW` does take effect; the code is correct as written.

**Board facts:** `RP_HOST=rp-fffe42.local` (mDNS works; the link-local IP
changes). OS 2.00 build 37, Ubuntu 22.04.4, kernel 5.15.0-xilinx. AXI region
2 MiB at `0x1000000`. Sample rate confirmed 250 MS/s by measurement. Binary
transfer returns exactly 16384 int16 big-endian samples. Amplitude accurate to
0.1% at 1 MHz; ~1818 counts per volt on LV.

**LIMITATION — the drive frequencies are no longer round numbers.**

*Recorded at Kevin's explicit request when he approved the change on
2026-08-12. Anyone comparing this system against a spec, a commercial lock-in,
or an earlier dataset that says "1 MHz" needs to read this.*

The ASG can only emit integer multiples of fs/16384 = **15258.7890625 Hz**.
This is a hardware property, not a software choice: the table period is fixed
at 65.536 µs, and any frequency off that grid makes the table wrap
discontinuously and spray a 15.26 kHz spur comb across the baseband where the
swept trace lives. The nominal frequencies are all off the grid, so:

| Quantity | Nominal | Actual | Offset |
|---|---:|---:|---:|
| Carrier | 80 MHz | **80.001831 MHz** | +1831 Hz (+23 ppm) |
| f1 | 5 MHz | **5.004883 MHz** | +4883 Hz (+977 ppm) |
| f2 | 6 MHz | **5.996704 MHz** | −3296 Hz (−549 ppm) |
| \|f2 − f1\| | 1 MHz | **991.821 kHz** | −8179 Hz (−0.82%) |

Consequences to be aware of:

- **The lock-in frequency is 991.821 kHz, not 1 MHz.** Demodulate at the actual
  value. `plan_two_tone_grid().difference` is the number; do not hardcode 1e6.
- Cycles per integration time drop from 71 to 70. Immaterial against R4's 5–10.
- The carrier shift is 23 ppm, agreed as negligible for the AOMs.
- ADR-0001's remark that 1 MHz is exactly fs/250, which would make an FPGA
  demodulator a fixed 250-entry table, **no longer holds.** If FPGA work is
  ever revisited, that convenience is gone.
- `plan_two_tone_grid` snaps both tones independently. Snapping the difference
  instead would give 1.00708 MHz with f2 at 6.011963 MHz — equally exact, a
  different choice about which quantity stays nearest nominal. The independent
  snap is what was agreed and is pinned by
  `test_grid_plan_matches_the_agreed_operating_point`.

**Escape hatch:** if the ASG's table size turns out to be settable over SCPI
(Q3b, unprobed), a 250-entry table would restore exact 80/5/6 MHz and this
limitation disappears. Worth checking before anyone builds around 991.821 kHz.

**Broke / still broken:**
- ~~`setup_am_generator()` does not produce a usable signal.~~ **Fixed and
  verified.** Rewritten around the real ASG model; `make_am_table()` builds the
  full 16384-entry table and plays it at fs/16384. Verified through
  `hardware.py` itself: all three AM lines land at exactly the predicted
  frequencies, and at a 20 MHz carrier (where the analog path is flat) the
  sideband/carrier ratios are 0.512 and 0.488 against 0.500 theoretical.
  H2.3 spur check at the design point: worst spur −48.5 dBc, no comb.
- `waveforms.make_am_waveform()` embeds the wrong hardware model. Kept, because
  its arithmetic is sound and its tests are worth having, but its docstring now
  says in capitals not to drive the board with it. Use `make_am_table()`.
- ~~`hardware.py` has unbounded polling loops.~~ **Fixed.** Replaced with
  `wait_until()`, which raises `TimeoutError` with a diagnostic message. The
  deep-memory fill timeout scales with record length rather than being fixed.
  Not yet exercised against a trigger that never arrives (H7.2 proper).
- `acquire_deep_2ch` sets `Trig:Dly` to the full record, leaving no pre-roll,
  which contradicts H6.4. Not yet touched.
- The `ACQ:AXI:*` deep-memory path is entirely unverified.
- `scripts/plan.py` computes settling at 250 MS/s while the operating point is
  125 MS/s, so it reports 113 points instead of 108. Overstates, so it errs
  safe.

**Second coax (OUT2 → IN2) fitted; H2.4, H2.5 and Q3b done.**

- **Q3b: no.** `SOUR:TRAC:DATA:LEN?`, `:LENGTH?`, `SOUR:ARB:LEN?`,
  `SOUR:BUFF:SIZE?`, `SOUR:TRAC:DATA:SIZE?` all return zero bytes. The 16384
  table is fixed, so **the frequency limitation above is permanent.**
- **H2.4: passes.** Both channels generate simultaneously; carrier magnitudes
  201396 and 200157, within 0.6%.
- **H2.5 / Q6: FAILS, and not in the way expected.** The OUT2−OUT1 carrier
  phase scatters over 71–82° — *whether or not the generators are restarted*.
  Leaving them running does not fix it, so it is not injected at start.
  Ten consecutive captures with the generators untouched gave a 70.9° spread.
  Both DACs run from one clock; this is unexplained and needs a dedicated
  session.

  **Measurement trap, for whoever picks this up.** The obvious observable —
  the phase of the difference-frequency beat, reconstructed from each
  channel's envelope — is *worthless* here. The two envelopes are at different
  frequencies (328 and 393 cycles/table), so a common capture-start offset does
  not cancel: it moves their phase difference by 2π·991821·Δt, and about 1 µs
  of trigger jitter randomises it completely. I measured 72° that way and
  briefly believed it. **Use the carrier line instead** — identical on both
  channels at 5243 cycles, so a common offset cancels exactly. That is the only
  clean observable available without a third input.

  Also worth knowing: the carrier moves 115° per sample of inter-channel
  offset, versus 1.43° for the difference frequency. The carrier is an 80×
  magnifier — useful for detecting the problem, misleading about its size.

  **Impact.** Amplitude is unaffected. Phase *within* a sweep should be fine,
  since the generators run continuously through it. What is at risk is
  comparing or averaging phase *across* sweeps (bears directly on Q13).

  **RESOLVED AS NOT BLOCKING — Kevin, 2026-08-12: the deliverable is
  amplitude only, not amplitude and phase.** `01-overview.md` updated.

  His reasoning, which is the physical argument and worth keeping over my
  inference: *the 80 MHz is only there to drive the AOM, so its phase carries
  no information; and the 5/6 MHz modulation phase does not matter either,
  because the lock-in recovers R.* R is the magnitude of the demodulated
  phasor and is invariant to a constant phase offset between the two drives —
  so a scatter in that offset moves the demodulated phasor around the circle
  without changing its length. Do not spend time explaining the scatter unless
  phase comes back into scope.

  **Concerns to carry forward anyway, recorded at Kevin's request:**

  1. *A relative **drift** would matter even for amplitude* — this is the one
     concern that survives Kevin's argument, because it is not a constant
     offset. A constant offset leaves R alone; a steadily advancing one does
     not. If the two
     channels' table positions slide continuously rather than jumping, that is
     equivalent to a small frequency offset on the beat, and a large enough
     offset walks the signal off the lock-in centre frequency, where the
     2250 Hz bandwidth attenuates it. Amplitude would sag without anything
     looking wrong. The observed scatter is consistent with drift of order
     ~1 Hz, which is utterly negligible against 2250 Hz — but my captures were
     seconds apart, so I cannot distinguish slow drift from fast drift that
     aliases to look random. **Check once deep memory works:** demodulate a
     single long capture and confirm the amplitude is steady end to end. That
     settles it directly and needs no extra hardware.
  2. *My original alarm was over-stated.* The carrier is ~80× more sensitive
     to inter-channel misalignment than the beat is (115° vs 1.43° per sample),
     so 75° of carrier scatter is consistent with anything from a fraction of a
     degree of beat wobble to complete randomness. I reported the alarming end
     of that range as the finding. If anyone revisits this, measure the table
     alignment directly: put the *same* modulation on both channels and
     cross-correlate the two captures. That has neither the 80× magnifier nor
     the trigger-jitter confound.
  3. *Amplitude estimator bias.* With amplitude as the sole deliverable,
     `R = sqrt(X² + Y²)` is the obvious choice and is biased upward in noise —
     CLAUDE.md lists this as a known trap. Since phase is steady within a
     sweep, rotating X + jY to a common angle and taking the real part is
     unbiased and quieter. Worth doing before quoting any noise figure from
     H3.3.

**RESOLVED LATER THE SAME DAY — the DMA capture was always fine; the SCPI
read was the broken part.** Read the section below for the diagnosis, then
this correction: `acquire_deep_fast()` performs the identical arming and
trigger sequence and returns good data. Verified by driving 1 MHz and then
2 MHz and capturing each — recovered 1.0000 and 2.0000 MHz, amplitude 361
counts against 362 measured independently, rms exactly amplitude/√2. Each
capture tracks its own drive, so it is live data, not leftovers.

So the fast read path fixed a correctness problem, not just a speed one. That
was not the reason for building it and was not anticipated.

**Two things learned while getting there, both of which cost time:**

- **`ACQ:AXI:SOUR<n>:Trig:Dly` is a post-trigger SAMPLE COUNT, not a delay.**
  Set it below the number of samples you intend to read and the tail of the
  read is whatever occupied the region beforehand. My first attempt set it to
  1000 and read a million samples; the result had the right min/max but an rms
  of 63.6 where a full sine gives 255, and no coherent tone. It looked like a
  broken capture and was a broken test.
- **`ACQ:AXI:SOUR<n>:Trig:Pos?` returns 2139095040 = 0x7F800000**, the float32
  bit pattern for infinity. Evidently broken. It does not matter yet because
  `ACQ:TRig NOW` fires immediately and the capture starts at the region base,
  so reading from offset 0 is correct. **It will matter for H6.4**, where a
  laser-triggered capture with pre-roll writes into a ring and the data will
  not start at offset 0.

---

**Original diagnosis, kept because the reasoning is still useful:**

The DMA region change worked: `ACQ:AXI:SIZE?` now reports 134217728 (128 MiB),
up from 2 MiB. 268 ms of two-channel capture at decimation 2.

**Transfer is 5.7 MB/s, and it is a hard limit worth planning around.**
Measured cleanly: six consecutive 7.6 MB reads, every one within 0.02 s of the
others. The planner assumed 100 MB/s on the reasoning that a gigabit link sets
the pace. It does not — the link is essentially idle. The bottleneck is the
SCPI server on the board's ARM core, moving about 2.9 M samples/s out of DMA
into a socket. A trivial command round trip is 46 ms.

Ruled out: our receive code (switching the accumulator from repeated
`bytes +=` concatenation, which is quadratic, to a joined chunk list changed
nothing at all) and read size. `GBE_MB_PER_S = 100.0` is now
`SCPI_MB_PER_S = 5.7`.

**A 477 MB one-second sweep therefore takes ~84 s over SCPI — but this is
fixable, and the fix is worth taking.**

Kevin pushed back on the claim that the board's CPU was the limit, and he was
right. Measured on the same cable, same board:

| Path | Rate |
|---|---:|
| SCPI binary block | 5.7 MB/s |
| Board writing its own RAM (`dd` to tmpfs) | 151 MB/s |
| **Raw TCP, board RAM → this PC** | **87 MB/s** |

**15× faster over a raw socket.** Neither the hardware nor the network is the
constraint; it is something inside the SCPI server's data path. Note the SCPI
payload is *already* raw binary — `FORMAT BIN`, 2 bytes per sample, verified by
byte count — so this is not a text-encoding cost, which was my first guess and
was wrong.

At 87 MB/s a 477 MB sweep transfers in **5.5 s instead of 84 s**.

**Proposed fast read path** (not yet built, needs a scope decision — see
below). Keep SCPI for what it is good at: configuration, arming, triggering,
all small commands where the 46 ms round trip is irrelevant. Replace only the
bulk read. The captured samples sit at a known physical address
(`ACQ:AXI:START?` = 0x1000000), so a small board-side helper can `mmap`
`/dev/mem` and stream the region over a socket.

Two things to work out when building it: the region is a ring buffer, so the
wrap has to be handled using `ACQ:AXI:SOUR<n>:Trig:Pos?`; and each channel has
its own contiguous sub-region, set by `ACQ:AXI:SOUR<n>:SET:Buffer`, so they do
not need de-interleaving.

**Scope decision needed.** `CLAUDE.md` says "Code and this agent both run on
the control PC," and this would put a small data-pump script on the board.
It is not FPGA work so R7 is untouched, but it is a genuine deviation from the
stated architecture and should be agreed rather than assumed. The alternative
is to accept 84 s per sweep, which is survivable for a burst measurement but
makes H7.1 half an hour of transfers.

*How this was nearly mis-reported, twice.* First I divided the whole
`acquire_deep_2ch` call time by the bytes returned and called it a transfer
rate — that included setup, arming and trigger polling, and gave ~4 MB/s.
Then an intermediate benchmark showed 55.9 MB/s and I briefly believed the
transfer was fine; that reading was an artefact of the benchmark consuming
bytes already sitting in the receive buffer from the previous read. The
repeated single-size measurement is the trustworthy one, and the fast reading
never reproduced.

`acquire_deep_2ch` then *appeared* to work: 200000 samples/channel at
decimation 2, with IN1 showing 1.0000 MHz and IN2 2.0000 MHz — correct counts,
correct channel mapping, no duplicated buffer. **That result did not hold up.**

On later calls it returns railed data (min −2048, max +2047) and, decisively,
**byte-identical statistics at decimation 1 and decimation 2** (ch1 mean 193.2,
rms 865.0 in both). Two different decimations cannot produce identical data
from a live capture. Confirmed against a silent input: with both outputs off,
ordinary `acquire()` reads a quiet 25–31 count band while `acquire_deep_2ch`
on the same input returns full-scale noise. **It is reading stale or
uninitialised DMA memory, not capturing.**

Two concrete defects found while diagnosing, both worth fixing regardless:

1. **`acquire_deep_2ch` calls `ACQ:RST`, which wipes the coupling and gain that
   `setup_acquisition` just applied.** Any caller doing the documented
   setup-then-acquire sequence silently loses its input configuration.
2. **`ACQ:AXI:DATA:Units RAW` does not take effect.** After the call,
   `ACQ:DATA:UNITS?` reads `VOLTS`. The set spelling appears to be unsupported
   and silently ignored — precisely the failure mode documented earlier, where
   a misspelled setting is indistinguishable from success. (The returned byte
   count is still consistent with int16, so this may be a separate AXI units
   setting that is not queryable; either way it is unverified.)

**Consequence: the drift question is still open.** Both attempts to measure it
were invalidated, and neither by the board:

- First at decimation 2, where the 80 MHz carrier is **above the 62.5 MHz
  Nyquist** and aliases to 45 MHz, badly attenuated by the decimation filter.
  145° of scatter, and a straight line through it gave a fictitious 175 Hz
  offset. **Do not measure the 80 MHz carrier at decimation 2.**
- Then at decimation 1, which fixed the aliasing but hit the railed-data bug
  above. Phase from a clipped signal means nothing.

Lesson worth carrying: both runs would have looked plausible if the signal
levels had not been printed. **Always print min/max/rms alongside any phase
result** — it is the only thing that distinguishes a measurement from a
noise measurement.

**Next:**
1. **Fix `acquire_deep_2ch` before anything else.** It is the gate for H5, H6
   and the Phase 1 exit criterion. Start with whether the buffer is genuinely
   being armed: check `ACQ:AXI:SOUR<n>:TRIG:FILL?` transitions 0→1 rather than
   reading 1 immediately from a previous run, and whether
   `ACQ:AXI:SOUR<n>:ENable OFF` in a `finally` block leaves the region in a
   state that breaks the next capture. Note the *first* call after the reboot
   worked and later ones did not, which points at leftover state rather than a
   wrong command.
2. Re-measure the drift once deep capture is trustworthy — at **decimation 1**,
   with signal levels printed.
3. The DMA region was enlarged from 2 MiB to 128 MB on
   2026-08-12 (`reg = <0x1000000 0x8000000>`, staged deliberately: the node
   name and base are unchanged so the `dma_region` alias on line 19 of the DTS
   stays valid, and 144 MB is the hard ceiling before colliding with
   `labuf@a000000`). That is 0.27 s of two-channel capture at decimation 2 —
   enough to exercise the whole `ACQ:AXI:*` path and cover H5.2. Going to the
   full 512 MB needs the upper half of RAM, which means renaming the node
   *and* updating that alias, and the region would sit above the `mem=512M`
   cap where the kernel may refuse it. Prove the path at 128 MB first.
3. Enlarge the DMA region per the corrected H6.1 (base `0x20000000`, size
   512 MB, back up `dtraw.dts` first) before any deep-memory work. Nothing in
   H5 or H6 can proceed on the shipped 2 MiB.
4. Then the `ACQ:AXI:*` path, which is the last wholly unverified part of
   `hardware.py`, followed by H3 (receive path, noise floor — Q8).
5. Fix `acquire_deep_2ch`'s trigger delay so pre-roll is possible (H6.4).

**Test suite:** 74 passing, up from 62. The 12 new ones pin the real ASG model
so it cannot silently regress.

---

## 2026-08-20 — Claude (Claude Code) — P1 attempted: the laser does not answer, and the host side is eliminated

> **SUPERSEDED IN PART, 2026-08-26.** The conclusion below that "the host
> side is eliminated" did NOT hold for the VCP half: the laser's virtual COM
> port node reports `CM_PROB_FAILED_INSTALL` on the control PC. The rest of
> this entry stands. See Q27 and the HANDOFF block. *(Entries are not
> rewritten on this project — superseded claims are marked.)*

Kevin ran a patch cable and a BNC, so serial, the laser trigger output and the
laser light are all available. **P1 ran and failed, but usefully: the fault is
narrowed to a laser-side setting.**

### What was tried

| | Result |
|---|---|
| COM29 enumerates | yes — "USB Serial Port (COM29)" |
| Port opens and writes | yes, every time |
| `*IDN?` at 6 baud rates × 3 terminators × 2 flow-control states | **silence, all 18** |
| Anything unprompted | nothing |
| Same over the **D2XX** driver path | **silence** |
| D2XX enumeration | `desc='TSL-775' serial='2601S967' id=0x2428:0116 flags=0` |

`flags=0` means nothing else held the device, so we were not fighting Santec's
own software.

### What that eliminates

Cable, driver, COM port, baud rate, terminator, flow control, and the choice of
driver interface — an FTDI device can be reached two ways and **both were
silent while the device enumerated cleanly**. The chip is fine and reachable.
**The laser's firmware is not replying.**

That is worth stating precisely because it is the useful half of a failed test:
there is nothing left to try on this machine.

### The leading candidate, from the manual

**The delimiter is selectable on the front panel** — Other tab → Communication →
GPIB — between **CR, LF, CR+LF and EOI** (TSL-775 p55). **EOI is a GPIB hardware
signal that cannot be sent over USB at all.** With the delimiter on EOI the laser
can never see a complete command over serial, and would answer nothing, forever,
regardless of baud rate. That matches what we see exactly.

Note the manual is internally inconsistent here: sections 7.2.2 (USB) and 7.3.2
(LAN) both state flatly that "the delimiter of the command is CR", while 7.1.3
presents it as a user setting with four values. **Trust the setting over the
prose.**

Also worth noting from the same section: a **REMOTE** state exists in which all
front-panel keys but LOCAL are disabled. Stuck state is unlikely to block
comms, but a power cycle is free.

### Asked of Kevin, cheapest first

1. **Other tab → Communication → delimiter.** If EOI, set it to CR. Also note
   whether the command set is Legacy or SCPI.
2. **Power-cycle the laser**, to clear any stuck REMOTE state.
3. **Santec's own software, if supplied.** If it connects, the laser is listening
   and a setting is wrong on our side; if it does not, the fault is not ours.

**LAN remains a fallback that sidesteps all of it** — the TCP transport is
written, and the LAN section documents its own delimiter independently.

### Added

`scripts/laser_comms_diag.py`, read-only, sends nothing but `*IDN?`. Sweeps the
serial combinations and the D2XX path, and — the part that matters — prints what
each outcome *means*, including the EOI trap, so the next person does not have to
re-derive the reasoning from a wall of empty byte strings. Today's observation is
recorded in its docstring.

**No code changed.** `santec.py` may be perfectly correct; it has still never had
a reply to check it against.

---

## 2026-08-18 — Claude (Claude Code) — correction: Kevin's Q20 answer was right after all

An earlier entry today is titled "Q22 answered, Q20 was WRONG" and says Kevin's
description of the laser log was mistaken. **It was not, and this corrects it.**
The entry is left in place as history; the live documents are fixed.

**What Kevin said:** the laser reports wavelength against relative time from the
first trigger.

**What the manual says:** `:READout:DATa?` returns "a header and wavelength data
array" — 500 points in 2000 bytes, all wavelength. No time column on the wire.

**Both are true.** `wavelength[i]` belongs to trigger pulse `i`, and with the
trigger stepping in time that is exactly wavelength against relative time from
the first trigger. Kevin described the **semantics**; the manual describes the
**wire format**. The time axis is **implicit, not absent**, and calling his
answer "wrong in a way that matters" was itself wrong.

**What survives, and it is the only part with practical content.** Because the
times are reconstructed rather than read, they depend on two things a timestamped
log would not:

- the trigger really stepping in **time** rather than wavelength (**Q24** — the
  two manuals define that encoding oppositely), and
- exactly **one log point per pulse** (**Q26** — no manual states it).

If either is false the reconstructed times are wrong and **nothing in the data
would show it**. That is why `check_alignment` exists and why both are on the P1
list. The guard was right; the story told about why was not.

**The habit worth keeping from this.** Finding that a manual describes something
differently from how a person described it is not the same as finding the person
wrong — they may be describing different layers of the same thing. Checking
which before writing "and was wrong" into four documents would have cost one
sentence of thought.

---

## 2026-08-18 — Claude (Claude Code) — the 80 MHz belongs to the AOM, not the DUT

**Kevin, 2026-08-14: the DUT does not require 80 MHz.** The spec has said it did
since Phase 0 and it was wrong.

**What is actually true.** An acousto-optic modulator only diffracts while it is
driven acoustically, and the Aerodiode 1550AOM-1 is an 80 MHz part. Amplitude
modulating that 80 MHz — sweeping its envelope from zero to full — gates the
light. That is what produces optical modulation at f1 and f2.

**The DUT never sees 80 MHz at all.** It sees light, varying in brightness. If the
AOMs were a different part, 80 MHz would be a different number and nothing else
about the measurement would change.

Corrected in `01-overview.md` (goal, R1's Source column, the channel table),
`CLAUDE.md`, `README.md`, `waveforms.py` and `__init__.py`. R1's source now reads
**AOM** rather than **DUT**.

**Why it matters beyond tidiness.** Recorded as a DUT requirement, 80 MHz looks
like physics that constrains the experiment. It is not — it is a property of a
component, and the frequency plan's real constraints (the ASG grid, buffer
commensurability) come from the Red Pitaya. Anyone reasoning about whether the
carrier could move would have been reasoning about the wrong thing.

Added the related reassurance while in there: the grid snap puts the carrier at
80.001831 MHz rather than 80.000000, and **that 1.8 kHz is nothing to an AOM**
whose acoustic passband is megahertz-wide. The snap exists for the Red Pitaya's
buffer, not the modulator.

**Also fixed here:** `01-overview.md` still said the laser "reports wavelength
against relative time from its first trigger". That was corrected in the code and
the other documents earlier today but missed here — the log holds wavelength
values with no timestamps. Third document found carrying it; worth a sweep next
time a claim is corrected rather than fixing them as they surface.

---

## 2026-08-17 — Claude (Claude Code) — attenuator recommendation WITHDRAWN; Kevin's tuning was right

**Three attenuator recommendations (20 dB, 10 dB, 6 dB) and a "turn the drive
down 4 dB" are all withdrawn. Kevin's drive level is correct and must not be
changed.** Recorded in full because the mistake is a natural one and the two
pictures give opposite advice about the same knob.

### What Kevin actually did, and why it is right

Laser CW, unmodulated 80 MHz through the amplifier into the AOM, Red Pitaya
output tuned until the diffracted light on a scope peaked. Standard AOM tuning.

**The drive is depth-1 AM.** H2.2 measured sideband/carrier = 0.5, and
sideband/carrier is m/2, so m = 1.0 — **the RF envelope reaches zero on every
cycle.** The AOM is switched fully on and off. It is *not* held at a bias point
with a small excursion on top.

So the envelope sweeps the entire diffraction curve each cycle, dark to peak.
There is no operating point whose slope matters; what matters is how bright the
"on" end is, which is exactly what maximising CW diffraction finds.

| Envelope peak | η at peak | signal at f1 | signal at 2f1 |
|---:|---:|---:|---:|
| 0.75 × Pπ | 96% | 0.523 | 0.041 |
| **1.00 × — Kevin's tuning** | **100%** | **0.567** | **0.000** |
| 1.25 × | 97% | 0.570 | 0.055 |
| 1.50 × | 88% | 0.545 | 0.116 |

**99.4% of the theoretical best, with zero frequency doubling.** The 2f1 term
appears only when the envelope *overshoots* the peak — the light then dips at the
top of each cycle, two dips per period. Kevin's setting is the exact point where
the envelope touches the peak and turns around, which is the one place that
cannot happen. It is a genuine optimum, not luck.

### The error, and what made it plausible

The withdrawn analysis assumed **small-signal** modulation: a carrier at a bias
point with a small wiggle, response `dη/dP × ΔP`, so a peak means zero slope
means no signal. **That is the standard lock-in picture and it is correct — for a
different experiment.**

This one is large-signal switching. The two regimes give **opposite advice about
the same knob**, and the small-signal picture is the more natural one to reach
for, especially when the words "lock-in" and "modulation" are in the air.

Two things made it worse rather than catching it:

- **Kevin's own observation was read as confirmation.** "Less light either side"
  was taken as "you are at a stationary point, therefore no first-order
  response". True for a small excursion. Irrelevant when the excursion covers the
  whole curve. **The datum was right and the inference from it was wrong.**
- **Each revision felt like convergence.** 20 → 10 → 6 dB each followed a real
  measurement replacing an assumption, which reads like a process working. All
  three were refining a number that should not have existed.

**Kevin's pushback is what settled it** — "I'm not changing the voltage in the
actual experiment", then a plain description of the CW tuning procedure. The
second made the modulation regime explicit and the analysis fell out in one
calculation.

### What survives

- **No attenuator for protection either.** The amplifier sees −4 dBm against a
  +10 dBm rating — 14 dB of margin — and the board's 14 dB rolloff at 80 MHz
  means it cannot get closer. A pad would only matter if somebody ran this below
  the rolloff, where the board *can* reach +10 dBm.
- **The one-tone control measurement (P5.1) is unaffected and still matters.**
  Drive f1 alone, look for anything at |f2 − f1|. It tests whether the amplifiers
  or the detector manufacture a false signal, and that is independent of drive
  level.
- **14 dB of board rolloff at 80 MHz** stands, and still answers U1. If drive
  ever falls short, commanding a bigger number will not help — the board is
  already clamping at its range.

### Where the tuning could still be improved, if ever needed

Kevin's procedure maximises CW throughput, which here is within 0.6% of
maximising the f1 signal. If that last fraction is ever wanted, the direct
version is the same procedure with one change: **apply the AM and maximise the
photodetector's component at f1**, rather than the DC level. Not worth doing for
0.6%, but it is the measurement that answers the question directly rather than
through a model.

---

## 2026-08-17 — Claude (Claude Code) — attenuator revised to 10 dB; Santec driver, unbiased amplitude, CSV output

Kevin measured the board's real 80 MHz output and then went away, so the rest is
offline. **147 offline tests pass, up from 107.** No hardware touched.

### The attenuator drops from 20 dB to 10 dB

**Measured: the board delivers 800 mVpp at 80 MHz on a scope, even commanded to
2.7 V.** Its range clips the command and the 60 MHz rolloff takes the rest. That
is **8 dB below the +10 dBm the first estimate assumed**, and it moves the answer.

| Attenuation | Amp out | Backoff from P1dB | Diffraction |
|---:|---:|---:|---:|
| none — the current setup | +34 dBm | **−1 dB** | ~48% |
| **10 dB** | **+24 dBm** | **9 dB** | **9.1%** |
| 20 dB (the old answer) | +14 dBm | 19 dB | 0.9% |

**Kevin's current no-attenuator setting sits about 1 dB INTO compression**, which
is exactly why he found it maximises light through the AOM. It is also exactly
what this measurement cannot use. The two facts are the same fact.

Damage stays impossible at 10 dB: the board would need +20 dBm to reach the
amplifier's rating and its absolute ceiling is +10 dBm, so **even with no rolloff
at all there is 10 dB of margin.**

**Still to confirm:** whether the scope was reading into 50 Ω or 1 MΩ. If 1 MΩ,
the real level is 6 dB lower again and every backoff improves. Re-measure into a
50 Ω load at P3.1.

### Why maximum light is the wrong target, which is worth stating plainly

The amplifier's P1dB is 2 W and the AOM's nominal drive is 2.5 W, so **full
diffraction is unreachable without saturating the amplifier.** Tuning for maximum
throughput therefore *necessarily* means running compressed. For CW work that is
correct. Here it is wrong twice:

- A compressed amplifier makes intermodulation at |f2 − f1| that is
  indistinguishable from the real signal (U2).
- **Saturation flattens the AM envelope.** The measurement lives in the
  modulation, not the average power, so driving harder for more light delivers
  *less* of the thing being measured.

The right target is not maximum η but maximum **dη/dP**, which for
η = sin²(k√P) peaks at **η = 50%, a quarter of full drive.** Unreachable
linearly with this amplifier, so: run what linearity allows and set the optical
level separately. **RF drive is set by amplifier linearity; laser power is set by
detector headroom.** An earlier version of the notes conflated them.

### `santec.py` — written from the manuals, never run against a laser

17 tests, against a fake laser replaying the byte-level replies the manuals
describe. Three things it gets right that a transport copied from `hardware.py`
would get wrong, and each fails in a way that looks like something else:

- **Bare CR, not CRLF.** The wrong delimiter hangs waiting for a newline that
  never comes, and presents as a dead cable.
- **Little-endian payloads.** The Red Pitaya's SCPI path is big-endian. Same
  `#4nnnn` block header, opposite byte order.
- **Two selectable command sets** return different payloads from the same
  command — 4-byte integers in 0.1 pm, or 8-byte doubles in metres.
  `read_wavelengths()` **infers which from the byte count** rather than being
  told, because both decode without error and only one is right.

Every setter reads back and raises on mismatch, since a setting command that
silently does nothing is this project's signature failure. `set_trigger_setting`
deliberately refuses to interpret its own argument — the two manuals define it
with opposite encodings (Q24), so it takes the raw value and says so.

### The unbiased amplitude estimator — and a measurement that changed the design

`01-overview.md` has flagged since Phase 0 that `R = sqrt(X²+Y²)` reads high in
noise. It matters more now: the detector puts the floor near 11 µV, so real
signals sit only a few times above it, which is where the bias stops being a
rounding error.

`LockinResult.amplitude()` projects onto a common phase. Unbiased, and it can
return negative values, which is what an honest estimator does when nothing is
there.

**Two things I had wrong, both caught by writing the tests:**

**1. "Unbiased and quieter" was wrong.** With no signal, R's *variance* is
actually LOWER — Rayleigh spread is 0.655σ against the projection's 1.0σ. What R
carries instead is a 1.25σ offset that never averages away. The projection trades
variance for removing that offset. It wins on total error, not on noise.

**2. `debiased_amplitude()` is a bad default, and measuring said so.** The
power-subtraction debias (√(R²−2σ²)) is only better than raw R below about
**1.5σ**. Between 2σ and 6σ it overcorrects and is **worse than doing nothing** —
and that band is exactly where our signals are expected. Mean error against
truth:

| A/σ | 0.5 | 1.0 | 2.0 | 3.0 | 4.0 |
|---|---:|---:|---:|---:|---:|
| raw R | +0.83 | +0.55 | +0.28 | +0.17 | +0.13 |
| debiased | +0.05 | −0.20 | **−0.31** | **−0.22** | **−0.15** |
| projection | +0.002 | +0.003 | +0.002 | +0.002 | −0.001 |

**The projection is essentially exact everywhere.** So rather than recommend the
magnitude route for phase-varying responses, `amplitude(smooth=N)` now tracks the
phase *locally* — averaging the complex trace over N points and projecting onto
that local angle. A DUT phase moves slowly with wavelength, so a window long
against the noise and short against the resonance recovers the amplitude without
the global angle's blind spots.

**Its failure mode is asymmetric and worth knowing:** too long merely reverts to
the global-angle problem; too SHORT is dangerous, because the reference then
carries a share of the same noise it is projecting, the two correlate, and R's
bias creeps back in a subtler form. Pinned by a test.

`debiased_amplitude()` is kept for the case with no usable phase at all, with the
table above in its docstring so nobody reaches for it by accident.

### `output.py` — CSV, as decided

`write_trace_csv` writes wavelength in nm and amplitude in volts, with provenance
as `#` comment lines above a normal column row. Points with no wavelength — the
pre-roll, normally — are dropped and **the count goes in the header** rather than
silently vanishing. An all-invalid trace raises rather than writing an empty file
that looks like a success until opened.

One correction found by testing: numpy's text readers do NOT handle this cleanly.
`loadtxt`'s `skiprows` counts comment lines and `genfromtxt(names=True)` takes the
first *comment* line as its header. `pandas.read_csv(comment="#")`, the stdlib
`csv` module and Excel all do. That is those numpy functions being awkward about
an ordinary CSV, not a defect — a real column row is what makes the file useful to
a person, which is the point of choosing CSV. The docstring said otherwise until
a test disagreed.

`write_raw_npz` saves the raw capture alongside, because a CSV of the finished
trace cannot support revisiting a demodulation choice — something this project has
already had to do more than once.

### State

147 offline tests. Nothing here has met an instrument: `santec.py` has never
seen a laser, and the attenuator figure needs the scope impedance confirmed.

---

## 2026-08-17 — Claude (Claude Code) — Q12 answered: attenuator decided at 20 dB; Phase 2 is unblocked

Kevin supplied the ZHL-1-2W+ and 1550AOM-1 datasheets, confirmed the laser's
interfaces, and delegated the remaining decisions. **All three Phase 2 blockers
are now down.** Full working in `04-hardware-reference.md`.

### The attenuator: 20 dB, and the reason is not the one I expected

**Without an attenuator the Red Pitaya at full scale sits EXACTLY on the
amplifier's absolute maximum input rating.** ±1 V into 50 Ω is +10 dBm; the
ZHL-1-2W+ damage rating is +10 dBm. Zero margin, and the first thing anyone would
have done is command full amplitude.

Three constraints, evaluated as peak envelope power because that is what
compresses an amplifier (AM at depth ~1, which H2.2 measured, puts PEP 6 dB above
the carrier):

| | Constraint | Binds at |
|---|---|---|
| 1 | Amplifier damage margin | ≤6 dB attenuation |
| 2 | **Amplifier linearity — the governing one** | ≤15 dB |
| 3 | **Detector saturation** | ≤15 dB |

**20 dB is the least attenuation satisfying all three.** It gives 11 dB of
backoff from P1dB, 0.39 mW in the first order against the detector's 0.96 mW
ceiling, and makes damage *physically impossible* — the board would have to
produce +30 dBm to reach the amplifier's rating and can produce +10.

**Constraint 2 matters more than the damage rating**, which is the part worth
remembering. Amplifier intermodulation lands at exactly |f2 − f1| — the frequency
being measured — and looks entirely legitimate (U2). An amplifier near
compression manufactures the signal we are looking for. Protecting the hardware
is the easy half; protecting the *result* is what sets the number.

**Constraint 3 was the surprise.** At 15 dB the first-order optical power alone
saturates the photodetector, independently of anything electrical. **The optics
run out of headroom before the electronics do**, which was not obvious before the
arithmetic and would have been a confusing afternoon otherwise.

**Specification: 20 dB fixed, 50 Ω, ≥0.5 W (2 W for margin), one per channel, so
two.** Dissipation is 10 mW, so the rating is not stressed.

### Two ordering rules that break hardware if ignored

- **Fit the attenuators before the amplifiers are powered at all.**
- **Connect the AOM before applying RF.** The amplifier datasheet warns that an
  open load can damage it and derates maximum input by 20 dB with no load.

### The optical side is comfortable, and the risk is at the far end

12 mW into an AOM rated for **0.5 W average is a 42× margin** — no optical risk
there at all. The constraint is entirely at the detector, which saturates at
0.96 mW. On this model the first order lands at 0.39 mW, about 40% of the
ceiling, before DUT losses. **Verify the detector's DC level at P4.1 before
raising anything.**

### P3.1 has a job beyond checking a level

The board's own 60 MHz rolloff means the real 80 MHz output is **below** the
+10 dBm the budget assumes, so effective attenuation is higher than nominal. If
the signal later turns out too small, that measurement is where the headroom
question gets answered — **not** by reaching for a smaller attenuator, since
15 dB fails two constraints at once.

### Decisions Kevin delegated

| | Decision |
|---|---|
| **Q13 averaging** | **No.** Detuning 1 is swept across ~11–13 discrete settings of detuning 2, so each sweep is its own measurement. Phase need not stay coherent between sweeps |
| **Q15 format** | **CSV** for the transfer function. Recommending `.npz` kept alongside for the raw capture — CSV of 32 M samples would be absurd, and raw is the only way to revisit a demodulation choice afterwards |
| **Laser interface** | BNC trigger out, USB mini, and LAN all present. **Recommend LAN**: it avoids the FTDI D2XX driver install the USB path requires, and is 30 Mb/s against 1 MB/s. Data volume is trivial either way (~160 kB per sweep), so this is about avoiding a driver, not speed |
| Q14 GUI, unattended operation | **Deferred** at Kevin's request |

Recorded as R9 and R10 in `01-overview.md`, since a deliverable format and "no
averaging" are requirements rather than notes.

### One thing to confirm

**Is there a second ZHL-1-2W+?** The design drives two AOMs, one per arm, so it
needs two amplifiers and two attenuators. Only one datasheet was supplied, which
proves the model rather than the count.

### State

**All three Phase 2 blockers are down.** Q22 (Santec command set), Q11
(photodetector) and Q12 (drive levels) are answered. What remains before hardware
goes in is the planning session itself, plus an optical damage threshold for the
detector and the deferred unattended-operation boundary.

No hardware touched this session. 107 offline tests pass.

---

## 2026-08-17 — Claude (Claude Code) — Q25 measured: AC coupling is free, and a defect that would have hidden it

Kevin started the SCPI server; loopback only, outputs off throughout and left off.

### A defect had to be fixed before the measurement was even possible

`ACQ:RST` reverts coupling to DC and gain to LV. Both deep-capture paths issue
it, so **an AC-coupled deep capture was impossible** — it would succeed, return
plausible data, and be DC coupled. Confirmed on the board: set AC, `ACQ:RST`,
read back DC.

This was already recorded as "harmless, because LV/DC is what it resets *to*".
That stopped being true the moment the real input became a photodetector with a
0–10 V pedestal that only AC coupling removes. **A caveat that is harmless today
is worth re-reading whenever the requirements move.**

Fixed: `setup_acquisition` now remembers the choice and both deep paths restore
it after the reset. Two offline tests pin it at the command level, since the
failure is invisible in the data. Also documented that gain and coupling are
**per channel**, which the real experiment needs — LV on IN1 for the
photodetector, HV on IN2 for the laser's 3.3 V trigger.

### Q25 answered: the AC corner is 17.0 Hz, and it costs nothing

Measured as the AC/DC amplitude ratio on a driven tone, so the counts-to-volts
calibration cancels and Q23 cannot affect the result.

| Frequency | AC/DC | Implied corner |
|---:|---:|---:|
| 3 Hz | 0.1724 | 17.14 Hz |
| 10 Hz | 0.5057 | 17.06 Hz |
| 30 Hz | 0.8728 | 16.78 Hz |
| ≥300 Hz | 0.998–1.002 | flat |

**Three points fit a single pole at 17.0 Hz to 2%.** At the lock-in frequency the
attenuation is **1.3 × 10⁻⁹ dB** — sixty thousand times above the corner — and AC
coupling does not cost even 0.1 dB until below ~78 Hz.

**The noise floor is unchanged too**: demodulated σ was 0.00601 counts DC against
0.00586 AC, a 2.5% difference on 392 output points whose own uncertainty is 3.6%.
**Every figure in `05-results.md` carries over to AC coupling.** The deep captures
also read back `AC` afterwards, which is the fix working.

So the input-stage plan is settled: **AC-couple IN1, keep the ±1 V range.** The
alternative — ±20 V at σ = 45 µV — would have let the ADC dominate a measurement
the detector should own.

### One artefact, recorded so nobody re-derives it

The 100 Hz point reads AC/DC = 1.37, which is not a real response. The DC-coupled
record carries a ~27 count offset, and at that decimation the record holds 13.42
cycles, so DC leaks across bins and *depresses* the DC-coupled reading. The
AC-coupled record has no offset to leak. Points at ≥300 Hz sit near whole cycle
counts and are unaffected. **An artefact of a single-bin DFT, not of the
instrument** — and a reminder that a ratio can look like a response.

### What AC coupling does cost

Nothing at the operating point, but it removes any DC reading of average optical
power. If that is ever wanted for diagnostics, the laser's own
`:READout:DATa:POWer?` log supplies it — noted in `08-phase2-hardware.md` rather
than left to be discovered.

### State

107 offline tests pass, up from 105. Board left with outputs off.

**Q25 closed.** Of everything blocking Phase 2, **only Q12 — safe drive levels
for the amplifiers and AOMs — still gates connecting anything.** The remaining
asks are small: which socket the laser is cabled on, an optical damage threshold,
and four decisions that need no measurement.

---

## 2026-08-14 — Claude (Claude Code) — photodetector manual read; Kevin's start-trigger idea adopted

Two things this session: Kevin's PDA05CF2 manual, and a question from him that
turned out to be a better design than the one recorded.

### Kevin's question: why not use only the start trigger?

*"Why can't you just use the start trigger as the only trigger, since everything
afterwards can be made into power over wavelength because the laser gives a
wavelength over time anyway?"*

**Right in substance, and it removes the worst failure mode in the design.**

The premise needs one correction — the laser does not give wavelength over
*time*, it gives one wavelength per trigger pulse (see the previous entry). But
**when the trigger is periodic in TIME, those are the same thing**: the i-th
logged wavelength sits at `first_edge + i × step`. So:

- **Only ONE edge is ever located.** A missed edge in the middle of the record
  changes nothing, because nothing is being counted.
- The catastrophic failure — one miscounted pulse shifting every subsequent
  wavelength by a full step, silently — **cannot happen**, rather than being
  guarded against after the fact.

Implemented as `wavelength.logged_point_times()`, with two tests: one showing a
dropped edge shifts the paired-to-edges method by exactly one step while leaving
the indexed method untouched, and one showing that taking `step` from a line fit
through the train — instead of from the laser's nominal setting — absorbs a
clock difference that would otherwise drift 150 µs across a 1 s sweep.

**That second point is the bonus.** Fitting the step in the board's own time base
turns **U11 from an assumption into a measurement**, and a line fit through
hundreds of edges does not care about a few missing ones. So the train is still
worth recording — just as a *verification* signal rather than as a dependency.

**One thing does not follow, and it is why Start mode alone will not do.** Mode 2
(Start) emits a single pulse. With no train there is nothing to fit the step
from, and no count to check against. **Keep Step mode; simply stop counting it.**
Best of both.

### The detector: PDA05CF2, and it changes the noise budget

Recorded in `04-hardware-reference.md`. Two consequences, one good and one not.

**U4 is closed, comfortably. The detector is flat to 150 MHz**, so 991.821 kHz
sits four orders of magnitude inside its passband. "Does the photodetector roll
off at 1 MHz" was a live risk to the entire measurement premise, and it is gone.

**But the detector is noisier than the board, and will dominate.** Two
independent routes from the datasheet:

| Route | Density | σ in our 4763 Hz ENBW |
|---|---:|---:|
| From the 2 mV rms output noise over 150 MHz | 163 nV/√Hz | **11.27 µV** |
| From NEP 1.26e-11 W/√Hz through the 50 Ω gain | 65.5 nV/√Hz | 4.52 µV |

They disagree by 2.5×, which is not a reason to average them — it probably means
the noise is not flat across 150 MHz, or the rms figure includes amplifier
contributions the NEP does not. **Plan against the pessimistic one.**

Combined with the board's 3.57 µV: **~11.8 µV, so SNR 10 needs ~120 µV rather
than the 36 µV loopback suggested.** Roughly 3× worse, before the real noise
environment (U6) or a longer cable are counted, and loopback showed a 30 cm lead
alone adds 50%.

**That the detector dominates is the right way round** — it means the instrument
is not the limitation. It is also why the sensitive ±1 V range is worth keeping
rather than retreating to ±20 V, where σ is 45 µV and the ADC would take charge
of a measurement it currently has no part in.

### The input stage needs AC coupling, and that has not been tested

The detector output is **unipolar, 0 to 10 V into Hi-Z**, and the Red Pitaya's
1 MΩ inputs make it Hi-Z. Ten volts will not fit a ±1 V range, and the signal is
a small modulation riding on a DC pedestal that tracks average optical power.

**AC coupling is the answer** and `setup_acquisition(coupling="AC")` already
supports it. But **every noise figure this project has measured was taken DC
coupled**, and the AC corner frequency is recorded nowhere. 991.821 kHz should be
far above any sensible corner — "should be" being the phrase this project keeps
getting caught by. Raised as **Q25**, and it is cheap to settle in loopback: AC
couple and repeat H3.3.

### Where Phase 2 stands

**Two of the three blockers are down.** Q22 (Santec command set) and Q11
(photodetector) are both answered from manuals. **Only Q12 — safe drive levels
for the amplifiers and AOMs — still blocks connecting anything**, and it is the
one that cannot be answered from a datasheet we already have.

Also worth noting what P4.4 should produce, so a wrong answer is recognisable:
**expect 11–12 µV.** Near 3.6 µV suggests the detector is not actually in the
path; above ~25 µV means something is wrong beyond the datasheet.

105 offline tests pass, up from 102. No hardware touched.

---

## 2026-08-14 — Claude (Claude Code) — Santec manuals read; Q22 answered, Q20 was WRONG

Kevin supplied the TSL-775 operation manual v1.0 and a link to the TSL-770's.
Both read in full. **Q22 is answered and the driver is unblocked.** Everything is
recorded in `04-hardware-reference.md` under "The Santec lasers"; the important
findings are below, and two of them are corrections rather than additions.

The manuals would not render as pages here (no poppler), so the text was
extracted with `pypdf` installed into the scratchpad rather than the project
venv, which is untouched.

### Q20's recorded answer was wrong, and the error mattered

The log said, on Kevin's description: *"the laser reports wavelength against
RELATIVE TIME FROM THE FIRST TRIGGER"*. **It does not.**

`:READout:DATa?` returns **a bare array of wavelengths — one value per trigger
pulse, with no timestamps at all.** `:READout:POINts?` returns its length.

So the pairing to time is **by INDEX against the recorded trigger pulses**, not
by interpolating against a time column. `wavelength.py` still has the right
shape — pass the recorded edge times as the table's time axis and the laser's
array as the wavelengths — and its end-to-end test already did exactly that. But
**the consequence is different, and worse:**

- Time-column pairing degrades gracefully. A slightly wrong time is a slightly
  wrong wavelength.
- **Index pairing does not. One miscounted pulse shifts every wavelength after
  it by one full step, silently.**

That is precisely the "counting" failure mode flagged when `wavelength.py` was
written, and the reason `check_alignment` exists. It is now the actual design
rather than the bad alternative — so **that guard is mandatory, not advisory**,
and it has a better number to check against than expected: `:READout:POINts?`
gives the laser's own row count directly, so the comparison is against a figure
the instrument reports rather than one we infer.

Docstrings in `wavelength.py` corrected accordingly.

### The two manuals contradict each other, and the failure would be silent

**`:TRIGger:OUTPut:SETTing` is documented with inverted encodings:**

| | 0 | 1 |
|---|---|---|
| **TSL-775** manual, p100 | periodic in **wavelength** | periodic in **time** |
| **TSL-770** manual, p99 | periodic in **time** | periodic in **wavelength** |

One is a documentation error, or the models genuinely differ. Raised as **Q24**.

It matters because the failure is invisible: the wrong value still produces a
trigger train, just periodic in the wrong variable. The wavelength spacing would
come out wrong with nothing looking broken. **Set it and read it back. Never
hardcode it.** A driver written for both models with a literal 0 or 1 in it is
wrong on one of them.

### The delimiter differs from the Red Pitaya's

**The Santec's delimiter is a bare `CR`. The Red Pitaya's is `CRLF`.** Reusing
`hardware.py`'s line reader unchanged will hang waiting for a newline that never
comes, and the symptom is a timeout indistinguishable from a dead cable.

Byte order is the same trap in a second instrument: the Santec's binary logging
data is **little-endian** ("Intel byte order"), while the Red Pitaya's SCPI path
is big-endian. `fast_read` already documents that hazard on the board; it now
applies to the laser too, in the opposite direction.

### The rest of what the manuals settle

| | |
|---|---|
| Interfaces | GPIB, USB (type B, FTDI D2XX, ~1 MB/s), LAN (100BASE-TX, TCP/IP, configurable port, ~30 Mb/s) |
| Command sets | **Two, selectable** — a legacy TSL-550-compatible set and the native TSL-770/775 SCPI set. They differ in response format **and in the binary logging payload** |
| Logging payload | Legacy: 4-byte signed ints in 0.1 pm. Native: 8-byte IEEE-754 doubles in metres. Both little-endian, both wrapped in an IEEE 488.2 `#4nnnn` block — the same header shape the Red Pitaya uses |
| Capacity | 500,000 points, comfortably above the ~122,000 a 1 s sweep at 8.192 µs steps would produce |
| Trigger output modes | 0 None, 1 Stop, **2 Start**, **3 Step** |
| Power log | `:READout:DATa:POWer?` — 32-bit floats in dBm. Not needed, but a free cross-check that the log lines up with the sweep |

**Structural question answered: it is a DUMP, not a stream.** `:READout:DATa?`
reads a completed log, so the driver runs **after** the capture rather than
alongside it. That is the simpler of the two shapes.

### One design choice worth making deliberately at P1

Trigger mode **2 (Start)** emits a single pulse at sweep start. That is all the
current alignment scheme actually needs, and it **removes the miscount risk
entirely** — with one pulse there is nothing to miscount.

Mode **3 (Step)** gives the train, which is what carries the index pairing to the
logged wavelengths and what makes the free clock-ratio check possible.

They are not interchangeable: with Start alone the wavelength log cannot be
indexed against anything recorded, so Step is almost certainly right. But it
should be **chosen**, not inherited from whatever the laser happens to be set to,
and the choice should be read back and recorded.

### State

`wavelength.py` docstrings corrected; no functional change, and the 20 tests
still pass unchanged, which is the point — the code was right, the prose about
it was not. 102 offline tests pass. No hardware touched.

**Q22 answered, Q20 corrected, Q24 raised. Of the three things blocking Phase 2,
one is now down.** Remaining: **Q11** (photodetector level and impedance) and
**Q12** (safe drive levels). The Santec driver can be written now, and P1 can run
with the Red Pitaya switched off.

---

## 2026-08-14 — Claude (Claude Code) — H6.2, H6.3, H7.3: PHASE 1 IS COMPLETE

**Every H step in Phase 1 is now done, except two that were deliberately not
done:** H6.1, the device-tree memory move, rejected on its merits and since made
unnecessary; and H5.2/H5.3, superseded because Deep Memory Generation does not
exist and H6.5 emulated the DUT by stepping amplitude instead.

All loopback. Outputs off throughout and left off.

### H7.3 PASSES — all three stages, and the H7.2 fix earned its keep

Run last and staged from harmless to risky, so that if the final stage wedged the
board the earlier results were already banked.

| Stage | Result |
|---|---|
| A — SCPI socket gone | `OSError` in 0.000 s |
| B — helper absent | `ConnectionError` naming the cause, before anything is armed |
| C — **helper killed mid-transfer**, 0.8 s into a 57 MB read | `ConnectionError` after 17.7 s |

**The board was responsive with outputs off after every stage.** That is the part
that matters, and it is the widened cleanup from H7.2 doing its job — before that
fix, stage C would very likely have left the capture armed and the server wedged,
which is precisely how this session lost twenty minutes earlier.

Stage C's 17.7 s is slow but it is a failure, not a hang. Not worth chasing.

Physically unplugging the Ethernet is still untested and needs a human; its
software-visible behaviour is stage A.

### H6.2 PASSES, and the transfer rate is worth knowing

32,812,500 samples on each channel, exactly as requested, both carrying signal.
125.2 MB — **97.8% of the region.**

**Transfer is much slower than the single-channel number suggests:** 6.7–11.2 s
for 125 MB including arming and the 1 s capture, so **11–19 MB/s against the
87 MB/s** measured on a 64 MB single-channel read. The 1 MB chunking added to
`rp_fastread.py` after a 50 MB request killed it means ~125 round trips, and at
~50 ms each that is most of the gap. A robustness-for-speed trade worth making;
larger chunks would recover most of it if a sweep ever needs to be faster.

### H6.3 PASSES — but only after finding a constraint nobody had written down

Exactly **5000 points**, spanning +0.1 ms to 999.9 ms about the trigger, at
**exactly 200.000 µs spacing with zero measurable jitter**, first point 100 µs
after the trigger.

**It failed the first time, at 4943 points, and the failure is the dangerous
kind.** A 1 s sweep with 45 ms of pre-roll, stopping at exactly trigger + 1 s,
comes up **57 points short — with no error, and a trace that looks perfectly
healthy and merely ends early.**

The cause: **`LockinResult.t` compensates the filter's GROUP DELAY as well as
trimming its settling.** That *shifts* the valid window rather than only
shortening it, so the usable span runs out about half the settling length before
the record does. 57 points against 113 trimmed — almost exactly half.

**Pre-roll alone is not enough. The record has to bracket the sweep on both
sides**: settling before it, and about half the settling after it. Added
`planning.recommended_tail()` next to `recommended_preroll()`, with the
measurement in its docstring and a test pinning the relationship. Re-running with
30 ms of pre-roll and a 20 ms tail gave exactly 5000.

**Memory is the constraint this runs into.** The recommended pre-roll (45.2 ms)
plus tail (16.9 ms) plus a 1 s sweep at decimation 8 is **98.9% of the 128 MiB
region**. It fits with essentially nothing to spare. Anyone lengthening the sweep,
widening the pre-roll, or adding a channel will hit the ceiling immediately —
and at that point the memory move comes back on the table, on *this* argument
rather than the trigger-edge one that has now evaporated.

### First end-to-end run of `wavelength.py` on real board data

Same capture, pushed through the whole chain. The laser table is synthetic — the
Santec is not connected and its command set is unknown (Q22) — but the edges, the
timing and the trace are all genuinely off the board, so everything except the
serial link itself was exercised.

- 128,174 edges recovered from IN2
- step 8.192000 µs against a nominal 8.192000, **0 missing**, line-fit residual
  **0.12 ns**
- `check_alignment`: count and span both match — the first recorded edge is the
  first table row
- `map_to_wavelength`: **5000 of 5000 points mapped**, none before or after the
  table, wavelength monotonic across 1521.4–1569.0 nm
- amplitude across the sweep steady to **0.0061%**

**The 0 ppm clock offset again proves nothing about U11** and the script says so
where it prints it: in loopback the generator and the ADC share one clock, so
there is no clock difference to detect. It validates the machinery, not the
premise.

### Where Phase 1 stands

Done: H1, H2 (H2.5 failed and was downgraded, its residual risk later closed by
H3.2), H3.1–H3.5, H4.1–H4.4, H5.1 answered, H6.2–H6.5, H7.1–H7.4.

Not done, deliberately: H6.1 (rejected, and now unnecessary), H5.2/H5.3
(superseded).

102 offline tests pass.

**The next work is not on the Red Pitaya.** It is the Santec serial driver, and
it is blocked on Q22 — the TSL-770/775 command set, the port settings, and
whether the wavelength table streams live or is dumped after the sweep. After
that, Phase 2 needs its own planning session before anything is connected; the
untestable list (U1–U12) is what that session is for, and U10/U11/U12 were added
today.

---

## 2026-08-14 — Claude (Claude Code) — H3.5 board half, H7.1/H7.2/H7.4; two real defects fixed

All loopback, outputs off at the end of every step and at the end.

### H3.5 board half PASSES, and the agreement is better than expected

Drove OUT1 at f_lockin + delta and demodulated at f_lockin. A tone offset by
delta lands at delta in the baseband as a vector of constant magnitude
A·|H(delta)| rotating at delta — so the magnitude is the measurement, and it
survives delta exceeding the output Nyquist, because downsampling changes the
apparent rotation rate and not the magnitude.

| Offset | Measured | Predicted | Diff |
|---:|---:|---:|---:|
| 0–1500 Hz | −0.0 dB | −0.0 dB | 0.0 |
| 2000 Hz | −0.8 dB | −0.8 dB | 0.0 |
| **2250 Hz** (nominal bandwidth) | **−12.1 dB** | **−12.0 dB** | **0.0** |
| 2500 Hz | −92.1 dB | −96.8 dB | at the noise floor |
| 3000, 5000 Hz | −95, −96 dB | −124, −106 dB | at the noise floor |

**Over the seven points above the noise floor the worst disagreement with the
designed filter response is 0.0 dB.** The filter does exactly what it was
designed to do.

Points past 2500 Hz are **lower bounds, not measurements**: a 0.5 V drive against
the 3.57 µV floor is 102 dB of range, and the residual 6.7–11 µV is what
complex-Gaussian noise gives (σ√2 = 5.05 µV). The script labels them as such
rather than reporting −95 dB as if it were the filter.

### The counts-per-volt discrepancy is real, and loopback cannot resolve it

A commanded 0.5 V came back as **902.8 counts**. At the 2048 counts/V this
codebase assumes, that is 0.4408 V — **12% low**, which is implausible next to
H3.1's 0.3% linearity and H2.2's 2% modulation depth.

902.8 counts for a nominal 0.5 V implies **1816.9 counts/V**, against the 1817.7
figure the H3.3 re-measurement flagged as "inherited and unverified". Those agree
to **0.04%**, from an unrelated measurement. So 1817.7 is right.

**But what it is a constant OF is the open question, and it matters.** Loopback
measures DAC × cable × ADC as one number. It cannot say whether the 0.882 factor
sits in the generator or the ADC, because the only instrument available to
measure the generator is that same ADC. And the distinction matters: in the real
experiment the photodetector drives the input **directly, with no DAC involved**,
so only the ADC's share applies.

Consequence for H3.3: σ is measured in counts and converted with this constant.
If the factor is in the ADC, the noise figures should use 1817.7 and the current
numbers stand. **If it is in the DAC, the ADC really is 2048 counts/V and every
absolute noise figure is 12.7% too high.** Raised as **Q23**. Resolving it needs
either a calibrated source into the input or a calibrated meter on the output —
neither is a loopback measurement.

### H7.2 PASSES — and fixing it fixed today's mystery wedge

Armed on CH2_PE at 2.0 V with the outputs off, so nothing could fire it. Raised
`TimeoutError` after 8.7 s against an 8 s budget, with a message naming the
trigger source. **H7.2's stated failure mode — hanging forever — does not occur.**

**But the first attempt left the board unusable, and that was a real defect.**
`acquire_deep_fast`'s cleanup `finally` only wrapped the *read*. When the trigger
never arrived, `wait_until` raised from **above** that block, so `ACQ:START`
stayed active and both channels stayed `ENable ON`. A board left armed that way
**stops answering SCPI queries entirely** — the TCP connection still accepts, so
it presents as a dead cable or a hung PC rather than as a capture that was never
disarmed. Recovering needs the SCPI server restarted by hand.

That is almost certainly what wedged the server earlier today, and it is
diagnostically nasty: every symptom points away from the cause. **Fixed** — the
cleanup now covers arming, triggering, filling and reading, issues `ACQ:STOP`
as well as the per-channel disables, and swallows errors so the original
exception survives.

### H7.4 FAILED, then was fixed

`close()` only shut the socket. **An unhandled exception anywhere in a
measurement script left the generator driving indefinitely, with nobody
watching.** Confirmed on hardware: after a simulated crash inside a `with` block,
`OUTPUT1:STATE?` still read `1`.

`tests/hardware/conftest.py` disarms outputs for the hardware suite, which is
exactly why this survived — the gap only ever showed in ad-hoc scripts, and
ad-hoc scripts are where most of this project's measuring actually happens.

**Fixed:** `close()` now switches both outputs off first, best-effort, never
raising — it usually runs while an exception is already propagating, and the
useful exception is the original one. `close(disable_outputs=False)` opts out.
Re-ran on hardware: `OUT1=0` after the crash. **PASSES.**

Five offline tests added (`tests/test_hardware_safety.py`) using a fake socket,
including one that pins the disarm as coming *after* the enable, and one that
proves a failing disarm does not replace the real exception. Suite is 101.

### H7.1 PASSES — twenty sweeps, and one number changes the decimation story

Twenty full-second two-channel captures at decimation 8, triggered from a
trigger train on IN2 with 45 ms of pre-roll. 20/20 succeeded, 239 s total.

| Quantity | Result |
|---|---|
| **Amplitude** | **0.0029% rms** (sd 0.0105 counts on 360.454) |
| **First edge in the record** | **1.330 µs, sd 6 ns**, range 19 ns — well inside one 32 ns sample |
| Recovered train step | 8.192 µs, sd 1.6e-12 µs |
| `Trig:Pos` | sd 17757 samples (2.6 ms range) |
| **Edge count** | **122071 on every single run. Zero variance. Zero missing.** |

Amplitude reproducing to 0.003% and the first edge to 6 ns is far better than
anything the measurement needs.

`Trig:Pos` scattering by 2.6 ms is expected and harmless — the trigger fires
wherever the DMA ring pointer happens to be. It is why reads are referenced to
`Trig:Pos` rather than to the region base.

**The edge count is the interesting one. At decimation 8, with a uniformly
spaced train, edge recovery was perfect across 2.4 million edges.** That sits
badly with the recorded "1.17% of intervals fail to match at decimation 8", and
supports the arithmetic objection raised earlier: the recorded cause (20 ns rise
against a 32 ns sample period) is identical in both experiments, so it cannot
explain one failing and the other not.

**What differs is the pattern**: H6.5 used H4.1's deliberately *uneven* intervals;
this used a uniform 8.192 µs train, which is what Q18 says the Santec actually
emits. **This does not explain the 1.17%** — it was not reproduced, so its cause
is still unknown — but it does show decimation 8 is not inherently lossy, and it
is the more representative test now.

Worth being clear about what the clock measurement did **not** show. It read
0 ppm offset with a standard deviation of 2e-7 ppm, which sounds superb and
proves nothing about U11: in loopback the generator and the ADC share one clock,
so there is no clock difference to detect. It validates the machinery, not the
premise. **U11 stays open until the real laser is attached.**

Also noted while setting this up: run `analyse_trigger_train` on an *uneven*
train and it reports one missing pulse per pattern period, because the long wrap
interval rounds to two steps. That is the routine used outside its stated
assumption of a fixed step, not a fault — but it is an easy mistake and the H7.1
script now says so where the pattern is defined.

### Still open

**H7.3, mid-capture disconnect** — attempted last, deliberately, because the
plausible failure is another wedged SCPI server and that needs a human to
restart. **SCPI server restarts are Kevin's, not the agent's** (asked
2026-08-14); the deny list now blocks `systemctl` on the board.

---

## 2026-08-14 — Claude (Claude Code) — wavelength mapping built; the serial half deliberately not

Kevin: the lasers are a **Santec TSL-770 and TSL-775**, not connected during
loopback, and no manual to hand. So the work split in two, and only one half was
written.

### What was built: `src/rp_lockin/wavelength.py`, 20 tests

Everything that does not depend on the laser's command set. It works from data
already in hand — the digitised trigger train, and whatever table a future driver
returns.

| Function | Does |
|---|---|
| `map_to_wavelength` | attaches a wavelength to every trace point by lookup against the laser's table |
| `analyse_trigger_train` | recovers the trigger step and **measures the laser's clock against the board's in ppm** |
| `check_alignment` | the off-by-one-trigger guard (Q21/U12) |

Usage, once a driver exists:

```python
edges = find_trigger_edges(in2_record, fs)          # same time base as result.t
assert check_alignment(edges, table_t).ok            # Q21 guard, do not skip
train = analyse_trigger_train(edges, nominal_step)   # free clock check (U11)
sweep = map_to_wavelength(result.t, amplitude, edges[0], table_t, table_wl)
wl, amp = sweep.dropna()
```

Design points worth keeping:

- **Locate the first edge in the recorded IN2 data, not from `Trig:Pos`.**
  `LockinResult.t` and `find_trigger_edges` are both referenced to the start of
  the input record, so using the recorded edge keeps one time base and sidesteps
  the fixed 1.14-sample offset `Trig:Pos` carries. `Trig:Pos` is still what arms
  and positions the capture; it is just not what defines t = 0.
- **The step comes from a line fit against corrected ordinals, not a mean of the
  intervals.** A single lost pulse inflates a mean and would report a step wrong
  by 1/N, quietly corrupting the clock measurement. Missing pulses are found
  from intervals near an integer multiple of the step — what a lost edge actually
  looks like — and the ordinals skip accordingly. Pinned by
  `test_a_missing_pulse_does_not_bias_the_step`.
- **Nothing extrapolates.** Points outside the laser's table get NaN and are
  counted, split into *before* (pre-roll — normal, never an error) and *after*
  (suspicious — raises unless `overrun_tol` is passed). Interpolating past the
  table end would invent a wavelength.
- **A grossly wrong t = 0 refuses rather than mapping.** If barely any of the
  trace falls inside the table, that is a misalignment, not a mapping.

**A lost edge and a late arm are now distinguishable**, which matters because
both show up as a short pulse count. A lost edge leaves a double-length gap; a
late arm does not. `test_lost_edge_and_late_arm_are_distinguishable` pins it.
That is the difference between a harmless recovery slip and a corrupted
wavelength axis.

**The tests earned their keep immediately.** `test_mapping_is_exact_on_the_table_
points` failed on the first run: a trace sampled exactly at the table times gives
`t_rel = (t0 + tt) - t0`, which floating-point leaves a few parts in 1e16 off
`tt`, putting the final point "past the end of the table" and tripping the
zero-tolerance overrun check on a *perfectly aligned* sweep. Fixed with an
epsilon scaled to the table span. Left as a comment in the code, because the
obvious reading of "no overrun allowed" is the buggy one.

### What was NOT built, on purpose

**No serial transport, and none should be added until someone has the manual.**
This project's recorded history is a list of SCPI commands that were misspelled
and returned zero bytes exactly like correct ones — `setup_am_generator`, the
`ACQ:DATA:Units` trap, the nine Deep Memory Generation spellings. A guessed
Santec command set would fail the same way: silently.

And the wavelength axis is the *worst* possible place for a silent failure,
because a mislabelled sweep looks exactly like a correct one. There is no
internal evidence in the data. So the module contains no command strings at all,
and takes the laser's table as an argument rather than fetching it.

Raised as **Q22**: the TSL-770/775 command set, whether the two models differ,
the port settings, and whether the wavelength table streams live during the sweep
or is dumped after it. That last one decides whether the driver runs alongside
the capture or after it, which is a structural choice, not a detail.

### State

96 offline tests pass, up from 76. No hardware touched this session; the board
was probed read-only earlier and outputs were off throughout.

Still open in Phase 1 and independent of all the laser work: **H7 robustness
(none of the four started)** and **H3.5's board half**. Either can proceed now.

---

## 2026-08-14 — Claude (Claude Code) — Q18–Q20 answered; one new silent failure found

Kevin answered all three questions raised in the entry below. Summary, then the
consequences, then the one new risk they create.

| | Answer (Kevin, 2026-08-14) |
|---|---|
| **Q18** trigger mode | Fires at **fixed TIME steps** — so IN2 does carry a pulse train. **Only the first edge is used**, to synchronise laser and board |
| **Q19** clocks | Already very closely synchronised; an external timebase can be attached if wanted |
| **Q20** serial report | **Wavelength against relative time from the first trigger** |

### The mapping is now genuinely simple

Both sides define t = 0 as the first trigger, so there is no sweep-rate
assumption and no step-index arithmetic anywhere: find the first trigger edge in
the record, call it zero, and look each trace point's time up in the laser's
table. That is about as clean as this could have been.

**The memory question is now properly closed.** Alignment needs one edge, not an
intact train, so the 1.17% missed-interval figure cannot affect it. Recorded in
`04-hardware-reference.md`. One honesty note kept there: **the memory question closed
because the requirement vanished, not because the fault was understood.** The
missed-edge mechanism is still unexplained — the recorded cause is off by a
factor of a hundred, see the entry below — and if some future design needs the
whole train recovered intact, that fault is still sitting there.

### The discarded part of the train is worth more than it looks

Q18 says the pulses are evenly spaced **in time**. That makes the recorded train
a direct measurement of how the laser's clock compares to the board's: fit a line
through the recorded edge times and compare the slope against the laser's
nominal step. **U11 stops being an assumption and becomes a per-sweep
measurement, from data already captured, for free.**

Worth doing even with an external timebase fitted — it is the check that the
timebase is actually working, and it costs nothing but a line fit. A few missing
edges do not disturb a slope through hundreds of them, and a missed edge shows
up as a double-length gap that is easy to reject. So decimation 8 is fine for
this purpose too.

### The new risk: "the first trigger" is defined twice, independently — Q21

The laser reports wavelength against time from **its** first trigger. The board
takes t = 0 from **its** first trigger. Nothing guarantees those are the same
edge. **If the acquisition arms late and latches the second pulse, every
wavelength in the sweep is offset by exactly one time step — and the trace looks
completely normal.** Same shape, same amplitudes, same noise; just wrong labels.
There is no internal evidence of the error anywhere in the data.

This is the most dangerous item now on the untestable list (added as U12),
because it is silent, and because both mitigations are so cheap there is no
reason to skip them:

1. **Arm the capture before the sweep starts, and use pre-roll.** H6.4 already
   proved pre-roll works and delivers real pre-trigger data.
2. **Cross-check the pulse count in the record against the length of the laser's
   table.** If the laser reports N points and the record holds N pulses, the
   first ones match. If the record holds N−1, it started late.

Both are software, both are free, and together they turn a silent failure into a
loud one. **Build them into the driver from the start rather than adding them
after a confusing result.**

### State of the trigger work

`07-phase1-loopback.md` H4 now reflects all of this. H4.4 — trigger the acquisition
from IN2 and know where the trigger sits in the record — is the load-bearing
test and passes, including the fixed 1.14 sample (9.1 ns) offset between
`Trig:Pos` and the true threshold crossing, which should be subtracted when the
absolute instant matters. It matters here.

### Next

The Santec serial driver is now the critical path, and its shape is known. Still
needed before writing it: the serial command set, the port settings, and whether
the wavelength table streams live during the sweep or is dumped afterwards. The
Q21 checks above should be part of it, not bolted on later.

Unaffected and available meanwhile: H7 robustness, and H3.5's board half.

---

## 2026-08-14 — Claude (Claude Code) — the wavelength axis comes from the laser, not the trigger

**Kevin, 2026-08-14: the lasers are Santec, and they can report their own
wavelength against time over serial. Their trigger output goes to the Red
Pitaya's trigger input purely to align the sweep with the capture. The trigger
pulses are no longer needed to carry the wavelength calibration.**

This is the largest scope change since the amplitude-only decision, and it is a
simplification. Written into `01-overview.md` (goal and R6/R6b),
`07-phase1-loopback.md` (H4 scope, the untestable table), `04-hardware-reference.md`
(decimation), `10-open-questions.md` (Q18–Q20) and `CLAUDE.md`.

### What it fixes

**The decimation-8 missed-edge problem largely dissolves, and with it the
justification for the memory move.** That problem was: 1.17% of trigger
intervals fail to match a designed value at decimation 8, and a missed edge
merges two intervals and corrupts the wavelength mapping. It mattered only
because the mapping was *derived from those intervals*. **Detecting one
sweep-start edge is a completely different task from recovering thousands of
intervals without losing any.** H4.4 already passes and is exactly what the new
scheme needs.

So the chain that has been driving the memory discussion — missed edges force
decimation 2, decimation 2 needs 477 MiB, 477 MiB needs the device-tree move —
is broken at its first link. **Do not do the memory move.** Two things stop this
being fully closed: the missed-edge mechanism was never actually explained (the
recorded cause is off by a factor of a hundred, see the previous entry), and Q18
below.

### What it changes about the H4 results

Nothing measured becomes wrong; some of it becomes less load-bearing.

| | Before | Now |
|---|---|---|
| H4.1 interval recovery | central | good evidence the path works; nothing gated on it |
| H4.2 timing resolution | central | same |
| H4.3 IN1/IN2 alignment | important | still relevant — a skew shifts the trace against the trigger instant — and settled at 0.0005 samples |
| **H4.4 trigger the capture** | one of four | **the load-bearing test, and it passes** |

The unticked-box duplication fixed earlier today matters more now: someone
reading H4 should see that H4.4 is the one that counts.

### Where the risk went — this is a trade, not a free win

Taking the wavelength axis from the laser removes a hard signal-processing
problem and replaces it with an instrument-integration one. The laser knows its
own wavelength far better than we can infer it from edge intervals, so it is a
good trade. But the failure modes are new, and both are invisible in loopback.
Added as U10 and U11:

- **U10 — the serial link itself.** The wavelength axis is now *entirely*
  dependent on it. A mis-aligned or wrong report mislabels every point, and
  nothing in the trace would look wrong. There is **no driver for this anywhere
  in the codebase** — not a line.
- **U11 — two clocks.** The trigger fixes a common origin, but the laser's
  timebase and the board's are independent. A 100 ppm rate mismatch is 100 µs of
  drift across a 1 s sweep. Whether that matters depends on how fast the
  wavelength moves and what wavelength error is tolerable.

### Three things to establish before writing any of it

- **Q18: which trigger-output mode is the laser in?** Santec TSL lasers can emit
  one pulse per sweep *or* one per wavelength step. Everything above assumes
  once per sweep. Per-step would put a pulse train back on IN2 — a *better* train,
  since each pulse would carry a known wavelength, but a train nonetheless, and
  the missed-edge question returns with it, and so does the memory question.
  **This one decides whether the paragraphs above hold.**
- **Q19: how do the two clocks relate?** See U11.
- **Q20: what does the serial report actually contain** — wavelength against
  absolute time, or against a step index? If indexed rather than timestamped,
  the mapping still needs sweep timing, which puts some work back on the
  trigger. Also needed: command set, port settings, and whether data streams
  live or is dumped after the sweep.

### Next

The immediate work is no longer on the Red Pitaya. It is a small Santec serial
driver on the control PC, and it cannot sensibly be written before Q18–Q20 are
answered — the answers change its shape. Everything in Phase 1 that remains
(H7 robustness, H3.5's board half) is independent of this and can proceed.

---

## 2026-08-14 — Claude (Claude Code) — stale numbers fixed; two recorded explanations do not hold

No hardware measurements this session. Kevin asked where each H step stood, and
checking turned up three documents quoting superseded numbers plus two recorded
explanations that do not survive arithmetic. Read-only board probes only;
outputs were off throughout and left off.

### The optimistic noise figure was still in every summary document

`07-phase1-loopback.md`, `10-open-questions.md` (Q8 and Q11) and `CLAUDE.md` all still
carried **45.6 nV/√Hz → σ = 2.96 µV → ≥30 µV for SNR 10**, superseded twice: by
the independent re-measurement (~15% optimistic → 51.7 → 3.57 µV) and by the
terminated measurement (the cable adds ~50%). The log had the corrections; the
documents anyone would actually read did not. **All four now say 51.7 nV/√Hz,
σ = 3.57 µV, ≥36 µV.**

Worth a general note: a correction recorded only in the session log is
half-applied. The log is append-only history; the summaries are what get read.

Also fixed: Phase 0 said 62 tests and the setup section said 74; both are 76.
H3.5's `[~]` checkbox became a plain unticked box marked "(half done)". The
duplicated H4 block — a checked-off section followed by the original wording
with four *unticked* boxes — made H4 look untouched at a glance; the second copy
is now clearly labelled reference-only with the boxes removed.

### The memory picture is worse than recorded, and the recorded risk is wrong

Probed the board directly rather than trusting the notes:

| | Recorded | Actual (2026-08-14) |
|---|---|---|
| `MemTotal` | 470932 kB (460 MB) | **341908 kB (334 MB)** |
| `MemAvailable` | not recorded | **144756 kB (141 MB)** |
| Buffer node | `buffer@1000000` | confirmed: base `0x01000000`, size `0x08000000` |

The 460 MB figure was measured when the region was 2 MiB. **The 128 MB region is
carved out of Linux's own half, not taken from the free upper half** — it sits at
the 16 MB mark. That is very likely why `rp_fastread.py` died on a 50 MB request
and left SCPI degraded: with ~141 MB available it was an out-of-memory kill, and
the 1 MB chunking fix treated the symptom. Moving the region to the upper half
would hand those 128 MB back to Linux **regardless of how big the region is then
made** — a robustness gain the "skip the move" decision never counted.

**The recorded reason for skipping the move is factually wrong.** It reads
"recovery requiring an ext4 reader". Measured: `/dev/mmcblk0p1` is **vfat
(FAT16)**, mounted at *both* `/boot` and `/opt/redpitaya`, so the device tree
files under `/opt/redpitaya/dts/` are on the FAT partition. **Recovery is: pull
the SD card, open it on any Windows machine, copy the backup back.** No ext4
tooling involved. The move is far less risky than recorded.

**Two corrections to my own earlier arithmetic in this project's favour and
against it:**

1. Capture sizes were quoted in MiB and the region size in "MB", which made the
   comparison look wrong. 1 s × 2 ch at decimation 2 is exactly **500,000,000
   bytes** = 476.8 MiB; the region is **134,217,728 bytes** = 128 MiB exactly.
   Use bytes when comparing.
2. **Moving to the upper half buys no headroom, only the decimation.**
   `0x20000000` = 536,870,912 bytes; decimation 2 with 45 ms pre-roll needs
   522,600,000 — **97.3% full, the identical margin** to decimation 8 in the
   current 128 MiB region, because both sides scale by four. Anyone expecting
   512 MiB to feel roomy at decimation 2 will be disappointed.

**If the move is ever done, do it in two steps.** Nobody has demonstrated the
FPGA can DMA to `0x20000000` — every capture so far used `0x1000000`. Move the
region up but keep it at 128 MB first and confirm a quiet-input capture still
returns σ ≈ 0.68 counts; only then enlarge. A region that reports the right size
and returns zeros is this project's signature failure mode, and the notes
already warn that asking for more than exists does not fail loudly.

### The decimation-8 missed-edge explanation does not survive arithmetic

Recorded cause: at decimation 8 the sample period is 32 ns and the test pattern
rises in 20 ns, so an edge has no sample on its ramp and interpolation has
nothing to work with.

**That bounds the error at one sample period — 32 ns. The observed error is
3.24 µs rms, worst 48 µs.** A hundred to fifteen hundred times larger.
Interpolation error cannot produce it. With designed intervals of 7–11 µs, an
rms of 3.24 µs and a worst case of 48 µs is what **lost edges** look like —
48 µs is roughly five intervals fused into one. It is structural, not a
precision problem.

Two further reasons to doubt the recorded cause. `find_trigger_edges`
(`emulator.py:187`) detects a crossing as a sign change in `x > threshold`,
which registers **however fast the edge is** — detection cannot miss a fast
edge. And the board applies its own anti-alias filter when decimating (that is
established elsewhere in this log, correcting a 6 dB estimate to 1.1 dB), which
*smooths* edges and should make interpolation **better** at decimation 8.

The only mechanism in that function that can delete an edge is the **1 µs
debounce**, which fires only if spurious extra crossings appear. Two unconfirmed
candidates: filter ringing crossing the threshold near an edge, or the
`threshold=0.0` default sitting in the middle of a trigger signal that looks
unipolar (H4.4 used `ACQ:TRig:LEV 0.1` against a 0.5 V signal), so that noise
chatters across zero during every low period. The second would be a plain bug
rather than a physical limit.

**Not resolved. Do not quote 1.17% as a decimation-8 property until it is.**

### The wavelength calibration does not exist yet, which changes the stakes

`find_trigger_edges` returns edge times and **nothing in the repo consumes
them.** The time-to-wavelength calibration is referenced in comments in `dsp.py`
and `emulator.py` but is unwritten. So "a missed edge corrupts the mapping" is a
claim about software nobody has designed, and the severity is a **design choice**:

- **Counting** edges (edge N ⇒ N·Δλ) makes one missed edge shift every
  wavelength after it. 1.17% would be ruinous.
- **Gap detection** makes it trivial: in a regular train a missing edge leaves
  one interval at twice the normal length, which is blatant and correctable.
  Two in a row gives 3×, also obvious.
- **Fitting** a smooth λ(t) through the edge times absorbs a missing point
  almost entirely, since a swept laser's wavelength-versus-time is smooth.

The H4.1 test pattern's deliberately uneven intervals (11.0, 8.0, 10.536,
7.0 µs) and H4.4's use of that signature to locate absolute position suggest a
gap-tolerant design was already intended. **Write the calibration to detect
double-length gaps.** The hard residual case is an *irregular* train with
missing edges, where a genuinely short interval cannot be told from a merged
one without a signature to lock onto — and whether that applies depends
entirely on U7.

**Consequently the fix order for the missed edges is:** (1) write gap-tolerant
calibration — offline, free, no hardware risk; (2) establish U7 from the laser's
datasheet, which may make it a non-issue; (3) only then consider the memory
move. I had this backwards earlier in the session, treating the memory move as
the fix for a trigger problem that is mostly unwritten software plus an
unmeasured signal.

### U7 is the highest-value open question in the project

What the laser's trigger output actually is: pulse rate, amplitude, rise time,
logic family, and whether intervals are uniform. **None of it is documented
anywhere** — not in the spec, not in the open questions. Everything tested so
far used a stand-in whose 7–11 µs intervals and 20 ns rise came from the ASG's
fixed 16384-entry table at 4 ns per step, not from any laser. It is a pattern
designed to exercise the code, not to resemble the instrument.

It gates the decimation, which gates the memory question. **Answerable from a
datasheet. Ask Kevin for the make and model before doing anything
memory-related.**

### Repo structure hazard — RESOLVED 2026-08-26

> **This was fixed. The project now lives at a single level:
> `Downloads/rp-lockin-2tone/`, one folder, one git repo. The nested layout and
> the accidental outer repo are gone.** The paragraph below is kept because the
> hazard it describes did real damage — it is why a push on 2026-08-26 landed
> only `.claude` on GitHub, having been run from the outer directory.

The project used to live at `.../rp-lockin-2tone/rp-lockin-2tone` — one level
below the directory of the same name. The **outer directory is an empty git repo with zero
commits** that has snagged the real repo as an unregistered gitlink (mode
160000, pinned at `801c4a8`). It is almost certainly accidental. Nothing was
committed there; doing so would cement a nested-repo structure nobody chose.
Relative paths run from the wrong level fail confusingly — `scp
scripts/rp_fastread.py` from the outer directory reports "No such file". **Use
absolute paths, or check `git rev-parse --show-toplevel` first.**

---

## 2026-08-14 — Claude (Claude Code) — H6.5 PASSES: Phase 1 exit criterion met

Both channels captured together for a full second at decimation 8, triggered
from the trigger train on IN2, with 45.2 ms of pre-roll. IN1 carried a
991.821 kHz tone stepped through eight amplitudes during the capture — the
stand-in for a swept DUT response, since DMG does not exist (H5.1).

**Amplitude, windows derived from the data:**

| Commanded | Recovered | Ratio |
|---:|---:|---:|
| 0.05 | 0.04948 | 0.9896 |
| 0.10 | 0.09930 | 0.9930 |
| 0.20 | 0.19830 | 0.9915 |
| 0.30 | 0.29762 | 0.9921 |
| 0.25 | 0.24811 | 0.9924 |
| 0.15 | 0.14882 | 0.9921 |
| 0.08 | 0.07939 | 0.9924 |

**Every level within 1%, spread 0.34%**, and the consistent 0.8% under-read
matches H3.1's independent figure. **Relative timing: 119.07 ms mean against
119.3 ms commanded, 0.2% error.**

**Trace spans −33.9 to +943.3 ms relative to the trigger**, so the pre-roll
covers the sweep from its first instant. `Trig:Pos` came back identical on both
channels (4706 and 4706), independently corroborating H4.3's alignment result.

**Two analysis traps hit on the way, both mine, both worth avoiding:**

1. **Plateau windows keyed to the PC's command timestamps read as a blend of
   two levels.** The PC records when it *sent* each command; the board applies
   it ~46 ms later, so the windows straddle every transition. Ratios came out
   0.81–1.36 and looked like a real nonlinearity. Deriving the windows from the
   transitions in the data fixes it — and is what the real experiment does
   anyway, since the time axis comes from the record, not the PC.
2. **A spurious transition at the very start of the trace shifted every label
   by one**, making a clean result look like a 300% spread. It is the filter's
   settling edge. Discard transitions within the first settling time.

**The one genuine problem: trigger edge recovery degrades badly at decimation
8.** 1031 of 88458 intervals (1.17%) failed to match a designed value, rms
mismatch 3.24 µs, worst 48 µs — against **0.01 ns at decimation 2** (H4.2).

Cause is straightforward: at decimation 8 the sample period is 32 ns and the
test pattern's rise time is 20 ns, so an edge often has no sample on its ramp
at all and the threshold interpolation has nothing to work with. Missed edges
are worse than imprecise ones, because a missed edge merges two intervals and
corrupts the mapping rather than blurring it.

**This qualifies the earlier "decimation 8 costs only 1.1 dB" conclusion.**
That measurement was of the *signal* noise floor and it stands. But the trigger
channel wants the opposite of what the signal channel wants, and
`ACQ:AXI:DEC` is global — one setting for both. So there is a real tension:

- signal path: heavier decimation is nearly free (+1.1 dB at 8) and saves memory
- trigger path: heavier decimation loses edges once they are faster than a
  sample period

**Before Phase 2, establish the laser trigger's actual edge rate (U7).** If its
edges are slow — tens of ns or more — decimation 8 is fine. If they are fast,
either the decimation must drop (which brings the memory question back) or the
trigger needs conditioning to slow its edges deliberately. A slower edge is
*easier* to time precisely here, which is counter-intuitive but follows
directly from having more samples on the ramp.

---

## 2026-08-14 — Claude (Claude Code) — decimation costs little; skip the memory move

Kevin asked whether the upper-half DMA move is needed only for loopback testing
or for the real experiment. The honest answer was "for the real experiment, as
designed" — a 1 s two-channel capture at decimation 2 is 477 MB. But the choice
of decimation 2 rested on an *argument* (ADR-0002: the analog rolloff sits below
the decimation-2 Nyquist, so nothing folds) and had never been measured against
the alternatives. Measured it before taking a boot risk:

| Decimation | σ per output point | Cost vs dec 2 | Signal for SNR 10 | 1 s, 2 ch |
|---:|---:|---:|---:|---:|
| 2 | 3.29 µV | — | 36.0 µV | 477 MB |
| 4 | 3.65 µV | +0.9 dB | 39.8 µV | 238 MB |
| **8** | **3.75 µV** | **+1.1 dB** | **40.9 µV** | **119 MB** |
| 16 | 4.58 µV | +2.9 dB | 50.1 µV | 60 MB |

**Decimation 8 costs 1.1 dB and fits the existing 128 MB region.**

**Recommendation: do not do the upper-half device-tree move.** It changes a
node name, an alias that refers to it by name, and puts the region outside the
kernel's memory map, with a non-booting board as the failure mode and recovery
requiring an ext4 reader. All to buy 1.1 dB.

I had estimated ~6 dB for decimation 8 by counting alias bands. That was wrong,
and wrong in the direction that would have justified the risk. **The board
applies its own anti-alias filter when decimating**, so the naive Nyquist
arithmetic badly overstates the penalty. Worth remembering as a general point:
ADR-0002's reasoning is sound but its practical conclusion is much weaker than
it sounds.

It also helps that nothing here has high-frequency content to fold — the
photodetector returns only the ~1 MHz response, so only noise folds, not
signal.

**Caveat on margin:** 1 s at decimation 8 is 119 MB and 43 ms of pre-roll adds
~5 MB, so ~124 MB of 128 MB. It fits with almost nothing to spare. Decimation
16 gives comfortable headroom (63 MB) for +2.9 dB if that becomes awkward.

---

## 2026-08-14 — Claude (Claude Code) — H6.4 passes; pre-roll proven

| | Trace starts | Result |
|---|---|---|
| no pre-roll | 10.8 ms **after** the trigger | 1.1% of the sweep lost |
| 43.2 ms pre-roll | 32.4 ms **before** the trigger | **fully covered** |

Same constant 991.821 kHz signal on IN1, triggered from IN2, decimation 4. The
pre-roll region reads 1.0 × steady rather than ~0, so it is genuine
pre-trigger data and not unwritten memory.

**Correction to the project's own framing.** `07-phase1-loopback.md` said "without
this the first 2% of every sweep is garbage." It is not garbage — it is
**absent**. `demodulate()` trims the settling transient internally, so it never
reaches the output; the trace simply does not begin until the filter is valid.
Nothing looks wrong, the trace is just short at the front, and only the time
axis shows it. That is arguably easier to miss than corruption.

**Two defects in `acquire_deep_fast`, both found by this test, both fixed:**

1. **The DMA must accumulate history before the trigger is armed.** It only
   starts writing at `ACQ:START`, so a trigger firing immediately leaves
   nothing behind it and the pre-roll region is memory that was never written
   this capture. It reads back as near-silence — which presents as a dead
   input, not as a sequencing error. Now waits 1.5 × the pre-roll duration
   before issuing the trigger command.
2. **Reads must reference `Trig:Pos` whenever there is a real trigger**, not
   only when pre-roll is requested. Reading from offset 0 after a real trigger
   returns an arbitrary point in the ring. It looks entirely plausible and
   silently misplaces every event in the record — which is exactly what
   corrupted the timing in the stepped-amplitude run below.

**Also worth noting how the first attempt at this test failed.** It looked for
a settling *transient* at the start of the trace and found none in either
capture, concluding both were fine. The transient can never appear, because
`demodulate()` trims it. Measuring coverage rather than corruption is what made
the difference visible. A test that cannot fail is not evidence.

---

## 2026-08-14 — Claude (Claude Code) — H5.1 answered; first full-length capture

**H5.1 / Q5: Deep Memory Generation does NOT exist on this OS.** Nine candidate
spellings (`SOUR<n>:AXI:*`, `SOUR:AXI:*`, `SOUR<n>:DMG?`,
`SOUR<n>:TRAC:DATA:AXI?`, `SOUR<n>:TRAC:DATA:LEN?`) all return zero bytes, and
loading a 32768-entry table **closes the SCPI connection** — the server does not
reject an oversized write, it drops the socket. **Never send more than 16384
points.** Outputs were verified off after that crash.

So the generator's unique-waveform ceiling is 65.536 µs, permanently, and
H5.2 as written is impossible: 65.536 µs is 0.3 of one output point, so a
shorter version of the emulated-sweep test would prove nothing.

**H5.4 fallback taken: impose the envelope live instead of baking it into a
waveform.** The generator's amplitude can be changed over SCPI while a capture
runs, so a stepped amplitude profile substitutes for a smooth one. Coarser —
ten steps rather than 5000 points — but it exercises the same chain and does
H6.2's work at the same time.

**Result: amplitude recovery excellent, time correlation failed.**

| Commanded | Recovered | Ratio |
|---:|---:|---:|
| 0.40 | 0.397 | 0.993 |
| 0.30 | 0.298 | 0.993 |
| 0.20 | 0.199 | 0.993 |
| 0.10 | 0.099 | 0.994 |
| 0.05 | 0.0496 | 0.991 |

Every plateau within 1%, consistent with H3.1's 0.6% under-read. But the
plateaus appear ~300 ms earlier than commanded, so **the time correlation is
not established.** Two causes, both mine:

1. The read started at buffer offset 0 rather than being referenced to
   `Trig:Pos` — the very mechanism built earlier in the session and then not
   used here.
2. PC-side timestamps for the `SOUR:VOLT` commands do not share a timebase
   with the DMA, and carry the ~46 ms SCPI round trip as uncertainty.

**Redo it referenced to `Trig:Pos`** before claiming anything about timing.

**Solid results worth keeping:**

- **62 500 000 samples captured, exact match to the request.** First
  full-length 1 s capture (decimation 4; decimation 2 would need 250 MB against
  a 128 MB region).
- **4892 output points from a 5000 Sa/s demodulation = exactly 5000 − 108**,
  independently confirming the documented 108-point settling cost.
- Demodulation of 62.5 M samples took 9.3 s.

**Transfer ran at 3.1 MB/s, against 22 MB/s measured earlier.** Cause:
`fast_read` opens a **new TCP connection per call**, and this fetched 119 MB in
32 pieces of 4 MB. That is connection overhead, not the board. Worth fixing —
either keep one connection open across reads, or use larger pieces now that the
helper chunks its sends internally.

---

## 2026-08-14 — Claude (Claude Code) — Trig:Pos works; pre-roll implemented

**Correcting the previous entry: `ACQ:AXI:SOUR<n>:Trig:Pos?` is not broken.**

It returns 0x7F800000 (float infinity) only when **no trigger has occurred**.
Every reading behind the "broken" verdict was taken with the board idle or
after `ACQ:TRig NOW`. After a genuine `CH2_PE`-triggered capture it returns the
trigger's sample index — 18164, 19032, 17290, 18370 across four runs.

The first validation was also wrong, and worth describing because the mistake
is easy to repeat. It read *from* the reported position and complained there
was no edge at sample 0. But `CH2_PE` fires on a rising edge, so if the
position is right the transition has already happened by the first sample and
there is nothing left to cross. **The absence of an edge at 0 was success, read
as failure.**

Correct test: read a known distance *before* the reported position and check a
rising edge appears there. It does, every time:

| Capture | Trig:Pos | Rising edge (expected 1000) | Error |
|---|---:|---:|---:|
| 1 | 18164 | 998.86 | −1.14 |
| 2 | 19032 | 998.87 | −1.13 |
| 3 | 17290 | 998.86 | −1.14 |
| 4 | 18370 | 998.86 | −1.14 |

**Spread 0.00 samples.** `Trig:Pos` sits a fixed 1.14 samples (9.1 ns) after
the true threshold crossing — trigger comparator latency plus the difference
between the board's 0.1 V threshold and the mid-level used for edge finding.
Not corrected for in `hardware.py`, because it depends on trigger level and
edge slew and so belongs to the signal, not the transport.

**Pre-roll is implemented and verified, so H6.4 is unblocked.**
`acquire_deep_fast` gained `trigger`, `trigger_level`, `preroll_samples` and
`trigger_timeout`. It sets `Trig:Dly` to the post-trigger count, reads from
`Trig:Pos − preroll_samples`, and handles the ring wrap in
`_fast_read_wrapped` (offsets in samples, byte arithmetic in one place so
callers cannot get the factor of two wrong).

| Pre-roll asked | Rising edge at | Error | Pre-roll region rms |
|---:|---:|---:|---:|
| 5 000 | 4998.87 | −1.13 | 712.0 |
| 25 000 | 24999.39 | −0.61 | 713.7 |
| 100 000 | 99998.87 | −1.13 | 712.4 |

The pre-roll region carries the same rms as the rest of the record (712.6), so
it is **real pre-trigger signal, not uninitialised memory** — which is the
failure this could plausibly have had. Both misuse cases raise: pre-roll with
`trigger="NOW"`, and pre-roll larger than the record.

The 22 ms of filter settling H6.4 needs is 2.75 M samples at decimation 2,
comfortably inside the region.

**Lesson worth carrying:** two of this session's three "broken hardware"
verdicts were wrong — the deep-memory read and now `Trig:Pos` — and both times
the fault was in the test, not the board. Before concluding a command is
broken, check it is being exercised in the state it is meant for.

---

## 2026-08-14 — Claude (Claude Code) — noise floor with 50 Ω terminators

Kevin fitted terminators on IN1 and IN2, nothing else connected. This is the
textbook H3.3 configuration, which the earlier measurements did not use.

| Configuration | IN1 density @ 991.821 kHz | σ per quadrature* |
|---|---:|---:|
| **50 Ω terminated** (board's intrinsic floor) | **34.6 nV/√Hz** | 2.39 µV |
| Short loopback cable, output off | 51.7 nV/√Hz | 3.57 µV |
| Ratio | **0.67×** | |

\* using the measured 4763 Hz noise gain, not the nominal 2250 Hz bandwidth.

**The cable adds about 50% to the noise floor.** That is pickup, not a
measurement artefact — the terminated figure is the board's own floor and the
cable figure is what you get once anything is plugged in.

**Which number to plan with: the cable one, or worse.** The real input is a
cable from a photodetector, longer than our 30 cm loopback lead and in a
noisier environment. 34.6 nV/√Hz is a floor the real system will not see.
**SNR 10 per trace point needs ~36 µV with a cable; ~24 µV is the unreachable
best case.** Hand the 36 µV figure to whoever answers Q11.

**The spur family is partly conducted and partly picked up**, which matters
because the two have different remedies:

| | IN1 505 kHz | IN1 1011 kHz | IN2 505 kHz | IN2 1011 kHz |
|---|---:|---:|---:|---:|
| Terminated | 163.6 nV/√Hz, 4.7× floor | 179.3, 5.2× | 69.1, 2.0× | 60.8, 1.7× |
| With cable | 439.1, 8.5× | 484.7, 9.4× | — | — |

It **survives termination on IN1** at roughly 5× the local floor, so part of it
is conducted — supply-borne, internal, and not fixable by cabling or shielding
at the input. The cable roughly triples it, so the rest is antenna pickup. On
IN2 termination removes it almost entirely.

Consequence for the real experiment: better cabling and shielding will reduce
the spur but cannot eliminate it. The forbidden-zone warning stands unchanged —
**do not place the difference frequency on 505.447 kHz or its multiples.**

Also settled: terminated, the spurs sit at exactly 505.447 and 1010.895 kHz,
the frequencies originally logged. The ~1.9 kHz offset I saw earlier was the
1907 Hz Welch bin resolution, exactly as suspected. It was correctly **not**
reported as switcher drift.

---

## 2026-08-14 — Claude (Claude Code) — H4: edges recovered, trigger position not

**H4.1 passes comfortably.** A six-edge pattern played from the ASG table and
recovered on IN2: 733 edges over 122.1 repeats (expected 732), all six designed
intervals recovered, **zero of 732 intervals failing to match a designed
value**, worst mean error **0.1 ns = 0.007 samples**.

**H4.2 timing resolution: 0.01 ns rms, 0.002 samples**, against an 8 ns sample
period at decimation 2.

**Do not quote 0.01 ns as the system's trigger resolution.** Everything in this
measurement shares one clock — the ASG advances one table entry per DAC tick
and the ADC samples at exactly half — so edges land at perfectly reproducible
positions and the threshold interpolation is consistent to numerical precision.
It measures the *instrument's* contribution, which is negligible. The real
laser trigger is asynchronous and brings its own jitter and slower edges; that
is U7, and it remains untestable in loopback.

**H4.4 is where it gets interesting, and it is a partial pass.**

Working: `ACQ:TRig CH2_PE` with `ACQ:TRig:LEV 0.1` triggers the acquisition
from IN2. And with the level at 2.0 V, above the 0.5 V signal, it correctly
does not fire and `wait_until` raises cleanly rather than spinning — which
incidentally covers **H7.2**'s failure mode.

Not working: **locating the trigger instant in the record.** The first edge sat
9.71 µs into the record and was falling; its interval signature (11.0, 8.0,
10.536, 7.0 µs) identifies it as the pattern's 41 µs edge, so the record starts
at table-time 31.3 µs — while the rising edge that fired the trigger was at
25 µs. The DMA ring was already running, so **buffer offset 0 is not the
trigger instant**; it is wherever the write pointer happened to be.

That is the limitation already noted in `acquire_deep_fast`'s docstring, now
confirmed by measurement rather than suspected. It did not surface earlier
because `ACQ:TRig NOW` fires immediately and the capture happens to begin at
the region base.

`ACQ:AXI:SOUR<n>:Trig:Pos?` exists precisely for this and returns 0x7F800000 —
the float bit pattern for infinity. **This blocks H6.4**, the pre-roll test,
and any accurate placement of the sweep within the record.

Two routes, in preference order:

1. Find a working spelling or an alternative way to read the trigger position.
   Worth a focused probe before anything else.
2. Locate everything from the IN2 edge pattern itself. The wavelength
   calibration already derives from *recorded* trigger edges rather than from
   the acquisition trigger, so this may be sufficient on its own. The ring wrap
   still has to be unwrapped, which needs the write pointer either way.

**H4.3 is not done and cannot be done with current hardware.** Confirming IN1
and IN2 are sample-aligned needs ONE source split to BOTH inputs — a BNC tee.
Driving OUT1→IN1 and OUT2→IN2 cannot separate input skew from output skew or
from the ASG's random start phase; all three produce a phase difference
proportional to frequency and are degenerate. **Needs a BNC tee and a short
matched cable pair from Kevin.**

---

## 2026-08-14 — Claude (Claude Code) — H3.1 and H3.2 done; H2.5 risk closed

**H3.1 — amplitude linearity: passes over 2.4 decades.** Drove the lock-in
frequency at 2, 5, 10, 20, 50, 100, 200 and 500 mV.

| Commanded | Recovered | Ratio |
|---:|---:|---:|
| 2 mV | 2.036 mV | 1.0182 |
| 5 mV | 4.870 mV | 0.9741 |
| 20 mV | 19.892 mV | 0.9946 |
| 100 mV | 99.515 mV | 0.9951 |
| 500 mV | 496.9 mV | 0.9938 |

**Above 20 mV the ratio spread is 0.3%** (0.9919–0.9951). The 4.5% spread over
the full range is entirely the 2 mV and 5 mV points. That is the *generator's*
amplitude resolution at small settings, not demodulator nonlinearity — noise
cannot account for it, because the vector mean's noise at 2 mV is 0.3 µV
against a 2036 µV signal. Consistent ~0.6% under-read across the range is the
combined output/input gain, not a linearity defect.

Amplitude taken as |mean(X + jY)|. `mean(R)` is biased upward in noise
(CLAUDE.md trap 5) and would have flattered the small-amplitude points.

**H3.2 — phase stability within a capture: excellent.** 0.002° total excursion
over 28 ms, linear drift 0.00003 Hz, R stable to 0.003% rms. The DAC and ADC
share a clock and the demodulation frequency is exactly the generated one, so
the phase is deterministic — which is what `02-architecture.md` asserts, now
measured.

**The H2.5 residual drift risk is CLOSED, and it needed its own test.** H3.2
measures one channel against the ADC; the risk was about the two channels
against each other. Drove **both channels at the same frequency**, captured
both simultaneously, tracked OUT2−OUT1 across the record:

- mean offset **−113.146°**, total excursion **0.053°** over 24 ms
- linear drift **+0.873 °/s = +0.0024 Hz** equivalent frequency offset
- scatter about the fit 0.013°

Against a 2250 Hz lock-in bandwidth that offset is a factor of 9×10⁵ too small
to matter. **The relative phase is a constant, and a constant offset does not
affect R** — which is exactly Kevin's argument, now with a number behind it.

The complete picture, since the pieces looked contradictory in isolation: the
inter-channel phase offset is **random at start** (H2.5, 71–82° across
restarts) but **rock-constant within a run** (0.05° over 24 ms). Both are true
and neither threatens the deliverable.

Driving both channels at the *same* frequency is what makes this measurement
valid. A common capture-start offset then cancels exactly. The earlier attempt
used the two different modulation frequencies, where it does not cancel — that
is what made it worthless, and it is worth not repeating.

**Next:** H3.5's on-board half, then H4 (trigger digitisation, no rewiring
needed), then H5/H6.

---

## 2026-08-14 — Claude (Claude Code) — H3.3 independently re-measured

**Kevin asked for the H3.3 numbers below to be verified.** Re-measured from a
fresh 100 ms capture, with a different estimator, via two routes chosen to be
independent of each other. **The findings hold; the magnitudes are ~15%
optimistic.**

| Quantity | Logged below | Re-measured | Ratio |
|---|---:|---:|---:|
| Density @ 991.821 kHz | 45.6 nV/√Hz | **51.7** | 1.13× |
| σ per quadrature | 2.96 µV | **3.57** (Y: 3.47) | 1.21× |
| Implied noise gain | 4232.7 Hz | **4763 Hz** | 1.13× |
| Spur fundamental | 505.447 kHz | 503.5, 8.5× floor | present |
| Spur 2nd harmonic | 1010.895 kHz | 1009.0, 9.4× floor | present |
| Spur 3rd harmonic | 1516.342 kHz | 4.5× floor | marginal |

**Confirmed, and this is the part that matters: the noise gain is not the
nominal bandwidth.** Predicting σ from the nominal 2250 Hz gives 2.45 µV
against 3.57 measured — 46% low. Predicting from the claimed 4232.7 Hz gives
3.36 µV, within 6%. Anyone reaching for the −3 dB bandwidth to estimate noise
will be badly wrong, in the dangerous direction.

The two routes — spectral density, and σ straight out of `demodulate()` —
agree with each other to 6%. That mutual agreement is what makes them
trustworthy; a shared calibration error would have moved both together and
this cross-check would not have caught it, but the ENBW consistency would.

**The 13–21% gap is real, not statistical** (σ from 392 output points carries
only ~4% uncertainty). Candidate causes, unresolved: the 100 ms record here
versus 256 ms below, the inherited 1817.7 counts/V calibration, or conditions
on the day. **Use the pessimistic figure.** The practical consequence is that
SNR 10 per trace point needs roughly **36 µV**, not 30 µV — that is the number
to hand whoever answers Q11.

**Do NOT read the spur frequencies as evidence of drift.** They came out
~1.9 kHz below the values logged below, which looks like exactly the switcher
drift warned about — but the Welch resolution here was 1907 Hz, so the offset
is one bin and establishes nothing. Settling whether the switcher actually
moves needs a longer record with finer resolution. The warning below stands on
its own merits; this measurement neither supports nor undermines it.

**Also fixed this session:** `scripts/rp_fastread.py` built the entire
requested slice in memory before sending. A 50 MB request killed the helper
outright and left the SCPI server degraded to multi-second latencies until it
was restarted. Now sends in 1 MB chunks. Reads up to ~4 MB had always worked,
which is why it survived first verification.

---

## 2026-08-13 — Claude (Claude Code) — H3.3 done: noise floor measured, Q8 answered

**Goal:** H3.3 — the noise floor at the lock-in frequency, the number that
predicts whether the real measurement can work. Loopback only; both cables
(OUT1→IN1, OUT2→IN2) fitted; nothing else connected; outputs off throughout.

**Answer, and it is good news.** At the operating point (decimation 2, DC
coupled, LV range, outputs off, loopback cables attached):

| | IN1 (signal) | IN2 (trigger) |
|---|---:|---:|
| Input noise density @ 991.821 kHz | **45.6 nV/√Hz** | 52.5 nV/√Hz* |
| σ per quadrature, operating bandwidth | **2.96 µV** | 3.42 µV* |
| As a fraction of the ±1 V range | 2.96 ppm | 3.42 ppm* |

IN1 is the number that matters and is **measured directly** off a 256 ms
deep capture. *IN2's figures come from the short-capture density route only
and are likely ~6% high, for the same reason IN1's first pass was — see the
deep-capture section at the end of this entry. IN2 carries the trigger
train, where a few percent of amplitude noise is irrelevant, so it was not
re-measured.

Repeat-to-repeat spread 0.2%, so this is a stable property of the instrument,
not one lucky moment. On the HV (±20 V) range: 697 nV/√Hz → σ = 45 µV, which is
14× worse in absolute volts but slightly *better* as a fraction of range
(2.3 ppm), so choosing HV costs nothing in relative precision — it only matters
if the signal is small enough to fit in ±1 V, where LV wins outright.

**What it means in one line: an intermodulation signal of ≥30 µV amplitude at
the ADC input gives SNR 10 on every one of the 5000 trace points, with no
averaging across sweeps.** That is the number to hand whoever answers Q11.
Below ~3 µV a single sweep cannot see it at all.

**Did:**
- Confirmed the offline suite green (74) before touching hardware, and again
  after (76 — two new tests, below).
- Probed board state read-only. Region is still the 128 MB from 2026-08-12.
  `ACQ:DATA:FORMAT?` read `ASCII` and units `VOLTS` on connect, i.e. a fresh
  SCPI server since the reboot; `setup_acquisition` correctly sets BIN/RAW.
- Measured the floor with averaged Welch periodograms of many short captures,
  at decimations 2/8/16/32/64, both channels, LV and HV.
- Measured the demodulator's off-frequency rejection offline (the offline half
  of **H3.5**).

**Learned (the parts worth keeping):**

1. **The demodulator's noise gain is 4232.7 Hz, not the nominal 2250 Hz
   bandwidth — a factor of 1.88.** With a one-sided input density S,
   var(X) = S · fs · Σh_eff² where h_eff is the cascaded impulse response.
   Anyone equating noise bandwidth with the −3 dB bandwidth understates the
   noise by √1.88 = 37%. Established three independent ways that agree to
   1.5%: analytically, empirically through the real `demodulate()` on
   known-density white noise, and by Welch periodogram (which recovers a known
   input density to 0.2%). **Now pinned by
   `test_quadrature_noise_gain_matches_filter_chain`** — if the filter design
   ever changes, that test fails and says to recompute this section, because
   nothing else would notice.

2. **There is a switching-supply spur family on both inputs, with the outputs
   off: 505.447 kHz fundamental, harmonics at 1010.895 and 1516.342 kHz.**
   Present on IN1 and IN2 alike, stable in frequency, 20–60× the local noise
   floor in density. The second harmonic sits **+19.073 kHz from the lock-in
   frequency**. It is *not* a problem now: measured offline, the demodulator
   attenuates a component at that offset by **−204 dB**. Nothing reaches the
   trace.

   **But record the margin, because it is thinner than −204 dB suggests.** The
   rejection is a property of the *offset*, not of the spur. If the switching
   frequency drifted 1.9% (505.447 → 495.91 kHz) its second harmonic would land
   exactly on 991.821 kHz, where there is no rejection at all. Integrating the
   observed line power over the measurement bandwidth, it would then appear as
   a **~4 µV steady amplitude — comparable to the 3.16 µV noise floor, and it
   would look like a real, constant DUT response rather than noise.** Two
   consequences:
   - **Anyone who changes the difference frequency must avoid 505.447 kHz and
     its multiples.** `03-frequency-plan.md` offers lower difference
     frequencies for Q9; 505.447 kHz is now a forbidden zone. The current
     991.821 kHz is safe by luck, not by design.
   - Worth a re-check under different thermal/load conditions before trusting
     the margin, since switcher frequencies move with both.

3. **My own first pass got the floor wrong by 2×, in the believable direction.**
   I averaged the density over ±38 kHz around the lock-in frequency, which
   swallowed the 1010.895 kHz spur, and reported 6.2 µV instead of 3.16 µV.
   Nothing looked wrong. **Use a median, not a mean, for a noise floor** — a
   median ignores discrete lines and a mean silently absorbs them. Both are
   printed side by side in the scan output for exactly this reason (the
   mean/median ratio ran 2.1–2.4 at decimation 2, which is the tell).

4. **Do not read broadband noise at high decimation.** The floor "improved" on
   IN1 (52 → 17 nV/√Hz from decimation 2 to 64) and "worsened" on IN2
   (54 → 134) over the same range. Both are artefacts of folding and of
   whatever averaging the FPGA applies at high decimation; they diverge by 60×
   at decimation 64 while agreeing within 5% at decimation 2. High decimation
   is still perfectly good for *locating discrete lines* — that is how the spur
   family above was pinned to 505.447 kHz from a 16384-sample buffer — because
   a real line keeps its frequency as fs changes whereas a folded one moves.
   Use it for that and nothing else.

5. **The Rayleigh bias flagged in the 2026-08-12 log is real and confirmed to
   0.7%.** With no signal, mean(R) reads 1.2533σ and never zero — on IN1 that
   is an apparent 3.96 µV "signal" that does not exist. The honest noise figure
   is the per-quadrature σ, which is also exactly what limits a real amplitude
   reading. Pinned by `test_magnitude_is_biased_upward_in_pure_noise`.

6. Quantisation is a real but minor contributor, not the limit: raw σ is
   0.68 counts at decimation 2 against 0.289 counts for ideal 12-bit
   quantisation, so quantisation is ~18% of the variance. The floor is analog.

7. DC offsets, for reference: IN1 sits at +27 counts, IN2 at +2 counts on LV.
   Irrelevant at 991 kHz, but a large offset would matter for H4's edge
   thresholds.

**Board facts unchanged:** `RP_HOST=rp-fffe42.local`, port 5000 open, SCPI
healthy at ~50 ms round trip, DMA region 128 MB at 0x1000000.

**Broke / still broken:**
- Nothing broken this session. No code changed except two added tests.
- `tests/hardware/test_loopback.py` **is stale and would mislead.** It still
  imports `plan_two_tone` and `make_am_waveform` — the pair CLAUDE.md marks as
  the wrong hardware model — and `PLAN = plan_two_tone(difference=1e6)` at
  module scope hardcodes the 1 MHz that the 2026-08-12 session established is
  actually 991.821 kHz. Its H3 test also calls `acquire_deep`, which routes to
  the broken `acquire_deep_2ch`. Not touched, because fixing it is a task in
  its own right and it is skipped without `RP_HOST`. **Do not trust it as a
  record of what passes.**
- `scripts/plan.py` still computes settling at 250 MS/s (reports 113 points
  instead of 108). Errs safe, unchanged from 2026-08-12.

**What H3.3 does NOT cover — read this before quoting the number:**

1. **The end-to-end confirmation is not done.** The floor was measured as a
   density and converted to a per-quadrature σ using the noise gain above. That
   conversion is validated three ways against the real `demodulate()` code
   path, but it has not been confirmed by demodulating one long contiguous
   board capture and measuring the scatter directly. That needs deep memory,
   which needs `scripts/rp_fastread.py` running on the board, which needs SSH —
   and **there is no SSH key installed on this PC, so the helper could not be
   restored** (`Permission denied (publickey,password)`, and a password cannot
   be typed non-interactively). Left for whoever has credentials. Everything
   else in H3.3 was achievable without it because noise statistics do not need
   a contiguous record.
2. **The input was not 50 Ω terminated.** H3.3 as written says "input
   terminated"; what was measured is the input with the **loopback cable
   fitted and the output commanded off**, since that is the wiring in place and
   changing it needs a human. **Kevin accepted this as the operative
   configuration on 2026-08-12** rather than spend a rewiring round trip on a
   50 Ω terminator, on the grounds that it is the wiring the rest of Phase 1
   runs in. So the question below stays open by choice, not by oversight. So the figure includes whatever the OUT1 stage
   emits when off. It is the right number for the rest of Phase 1, which runs
   with those cables on. Separating the receiver's own floor from DAC leakage
   needs a 50 Ω terminator in place of the cable. That IN1 and IN2 agree within
   8% is weak evidence the floor is front-end dominated rather than
   output-stage dominated.
3. **Spur resolution inside the measurement band is limited to 238 Hz**, from
   4.19 ms at decimation 64. No line was found within ±2250 Hz of the lock-in
   frequency at any decimation (in-band peaks ran 0.9–1.4× the local floor,
   i.e. nothing). A line narrower than 238 Hz and weaker than ~5× the floor
   could still hide. A deep capture would settle it.
4. **AC coupling unmeasured.** DC was used throughout, matching
   `setup_acquisition`'s default and the operating point.
5. **Absolute volts carry ~13% unresolved uncertainty.** Counts were converted
   at the nominal 2048 counts/V for LV. The 2026-08-12 log records a measured
   round-trip figure of ~1818 counts/V, 13% away. That figure conflates the
   DAC's real output amplitude with the ADC's scale, so it is not necessarily
   the ADC scale — but until someone measures the ADC scale against a
   calibrated source, every absolute voltage here inherits that uncertainty.
   **All the counts figures, and every SNR ratio, are unaffected.**

**Next:**
1. **H3.1 and H3.2**, which H3.3 skipped ahead of and which need no new
   hardware: amplitude linearity across a decade, and phase stability within a
   capture. Both run off `acquire_deep_fast`, so both want the helper too.
2. **Restore `scripts/rp_fastread.py`** (`scp` to `/dev/shm`, then
   `python3 /dev/shm/rp_fastread.py`) and either install an SSH key on this PC
   or have a human start it. This now gates H3.1, H3.2, H3.4, H5 and H6 — it is
   the single highest-value unblock available.
3. **H3.4** — the √bandwidth law on real data. Straightforward once a long
   capture exists: demodulate one record at several bandwidths and confirm σ
   halves per 4× bandwidth reduction. The offline half is already covered by
   the existing noise-scaling test.
4. **H3.5** — the offline half is done (rejection table below); confirm on the
   board by driving a tone offset from the lock-in frequency.
5. Re-check the 505.447 kHz switcher frequency when the board has been running
   under different load/temperature, per finding 2.

**Measured off-frequency rejection of the demodulator** (offline, operating
point, unit-amplitude tone at f_lockin + offset). Note the response is already
−12 dB at the nominal 2250 Hz "bandwidth", so the effective passband is
narrower than the nominal figure even though the *noise* bandwidth is wider:

| Offset | Recovered | Attenuation |
|---:|---:|---:|
| 0 Hz | 1.0000 | 0.0 dB |
| 1 kHz | 0.9999 | −0.0 dB |
| 2.25 kHz | 0.2500 | −12.0 dB |
| 3 kHz | 6.5e−7 | −124 dB |
| 10 kHz | 1.9e−7 | −134 dB |
| **19.073 kHz** | **6.1e−11** | **−204 dB** ← the supply harmonic |
| 38.146 kHz | 7.6e−13 | −242 dB |

### CONFIRMED BY DEEP CAPTURE, LATER THE SAME DAY — and one figure above was badly wrong

Kevin started `rp_fastread.py` by hand, which unblocked everything the section
above listed as pending. One contiguous 32 M-sample capture (256 ms, IN1,
decimation 2, LV, DC, outputs off) settled all of it. **The headline table above
has been updated to these numbers; what follows is what changed and why.**

**1. The noise floor is confirmed, and slightly better than reported: σ = 2.96 µV
measured DIRECTLY, against 3.16 µV predicted via the density route.** The direct
measurement demodulates the real record and takes the scatter of X and Y, with
no conversion factor at all: σ_X = 2.961 µV, σ_Y = 2.957 µV — agreeing with each
other to 0.1%, which is itself a good sign. The 6% gap from the density route is
explained: the short-capture median was taken over only ~16 bins of 7.6 kHz and
sat slightly high on spur skirts, whereas the deep record gives ~2000 bins of
59.6 Hz and a clean median of **45.6 nV/√Hz** against the earlier 48.5. **Use
2.96 µV and 45.6 nV/√Hz.** The density route was right to 6%, which is a fair
validation of the method, but the direct number is the one to quote.

**2. H3.4 passes on real data.** Demodulating the same record at four
bandwidths:

| Bandwidth | ENBW | σ (µV) | σ ratio | √(bandwidth ratio) | agreement |
|---:|---:|---:|---:|---:|---:|
| 2250 Hz | 4232.7 | 2.96 | 1.0000 | 1.0000 | — |
| 1125 Hz | 2009.0 | 2.01 | 0.6778 | 0.7071 | 0.959 |
| 562.5 Hz | 1027.4 | 1.45 | 0.4908 | 0.5000 | 0.982 |
| 281.25 Hz | 507.5 | 1.02 | 0.3453 | 0.3536 | 0.977 |

So σ ∝ √bandwidth holds to 2–4%. The residual is not error: ENBW does not scale
exactly with the nominal bandwidth (the ratio drifts from 1.881 to 1.804 across
this range), and σ tracks **√ENBW** to ~1.5%, better than it tracks √bandwidth.
If you need the noise at some other bandwidth, scale by √ENBW, not by
√bandwidth.

**3. The Rayleigh bias is confirmed on real board noise, not just synthetic:**
mean(R) = 3.723 µV against 1.2533σ = 3.708 µV, a ratio of 1.0039.

**4. `fast_read`'s little-endian decode is now PROVEN, and the way it was proven
is worth reusing.** `hardware.py` said the little-endian/big-endian split
between `fast_read` and `query_binary_int16` was "not a typo and not yet
proven" — and a byte-swapped *noise* record still looks exactly like noise, just
with the wrong amplitude, so nothing would have complained. The check: the deep
record's raw σ is 0.6797 counts against 0.6781 from a plain `acquire()` on the
same quiet input, a ratio of 1.002. A byte swap would be off by ~100×, not 0.2%.
The docstring has been updated. **Any future change to that decode should be
re-checked the same way — against `acquire()` on a quiet input, not against a
waveform, where a plausible-looking result proves less.**

**5. `ACQ:RST` resets gain to LV and coupling to DC** (measured: forced HV, then
`ACQ:RST`, then read back LV). It also resets `ACQ:DEC` to 1, the format to
ASCII and units to VOLTS. So the documented defect — that `acquire_deep_fast`
and `acquire_deep_2ch` wipe what `setup_acquisition` applied — **is harmless for
LV/DC work, because that is exactly what it resets to.** It would silently ruin
an HV or AC-coupled deep capture. `ACQ:AXI:DEC` is set after the reset, so the
decimation is fine. Recorded in `04-hardware-reference.md`.

**6. Nothing is inside the measurement band.** At 59.6 Hz resolution the worst
in-band bin is 1.44× the local floor, which is what the maximum of 75 noise bins
looks like with 15 averages. Integrating the in-band excess as if it were a line
gives 1.09 µV, which is what integrating positive noise scatter always gives —
not a detection. Caveat 3 of the section above is now closed.

**7. THE SPUR IS ~8× BIGGER THAN I REPORTED, and this is the one finding here
that raises the stakes rather than lowering them.** With the line properly
resolved and its power integrated (estimator validated against an injected tone
of known amplitude, recovered to 0.2%):

| | Centre | FWHM | Amplitude | vs σ | Offset from f_lockin |
|---|---:|---:|---:|---:|---:|
| Fundamental | **504 867.6 Hz** | 335 Hz | **33.7 µV** | 11.4× | −486.95 kHz |
| 2nd harmonic | **1 009 737.7 Hz** | 451 Hz | **32.2 µV** | 10.9× | **+17.92 kHz** |
| 3rd harmonic | 1 514 602.7 Hz | 750 Hz | 18.0 µV | 6.1× | +522.78 kHz |

The earlier "~4 µV" estimate came from a coarse-resolution density and was wrong
by a factor of 8: a 450 Hz-wide line smeared across a 7.6 kHz bin reads far
lower than it is. **Correct figure: ~32 µV.** The offset also moves from the
estimated +19.07 kHz to a measured **+17.92 kHz**, and the fundamental from
505.447 to 504.868 kHz — the coarse values were bin centres, not measurements.

**Why this matters more than the first pass suggested.** The rejection is
unchanged and still total (>200 dB at this offset — the offline table brackets
it at −277 dB by 17.5 kHz), so **nothing reaches the trace today.** But the
consequence *if* it ever landed in band is now much worse than recorded: a
32 µV apparent amplitude is **11× the noise floor and squarely in the middle of
the 30 µV range we would call a healthy real signal.** It would not look like
interference. It would look like a strong, clean, steady DUT response. Combined
with the drift figure below, this is the single most dangerous failure mode H3.3
has turned up:

- **A −1.77% drift of the fundamental** (504.868 → 495.911 kHz) puts the second
  harmonic exactly on 991.821 kHz. The third harmonic needs −34.5% and is not a
  concern.
- Short-term the line is stable: the peak held to within one 476 Hz bin across
  all eight sub-segments of the 256 ms record, and the 335 Hz FWHM implies
  jitter of only ~0.07%. That is 25× smaller than the 1.77% needed. **But
  256 ms says nothing about hours, load, or temperature**, and a switching
  regulator moving a few percent over its full range is ordinary.

**Recommended, and not done here:** re-measure the fundamental after the board
has been powered for some hours and while something is loading it (a long deep
capture running, say), and confirm it has not walked toward 495.9 kHz. If it
ever does, the fix is cheap and known — move the difference frequency, which
`plan_two_tone_grid` can re-snap — but only if someone is watching for it.
**Anyone choosing a new difference frequency must avoid 504.868 kHz and its
multiples, with a margin of several kHz.**

---

## 2026-08-25 — Claude (Claude Code) — transfer speed, the experiment's real shape, and a bench GUI

**Goal:** Status report, then whatever Kevin pointed at. Ended up on three
things: the deep-capture read, a correction to what the experiment actually is,
and a human-usable GUI.

**Did:**

- **Sped up the deep-capture read** and, more usefully, instrumented it.
  Board helper now slices a `memoryview` rather than the mmap (`mem[a:b]`
  materialises a copy, so the old path memcpy'd all 125 MB on the ARM before
  sending a byte); `CHUNK` 1 MB -> 8 MB, which was only 1 MB because of that
  copy; `TCP_NODELAY` both ends; client uses `recv_into` over a preallocated
  buffer instead of accumulate-then-join, which held the reply twice at its
  peak. Helper logs bytes and elapsed per GET.
- **Added `tests/test_fast_read.py`** — there were NO tests of `fast_read`, on
  the transport every sample of every sweep arrives through. Pins the short-reply
  refusal and the little-endian convention against a real loopback socket.
- **Added `set_wavelength_m()`** to `santec.py`, then **parked it** at Kevin's
  request. Written because the stepping laser could not be commanded at all.
- **Built `scripts/bench_gui.py`** (Q14) with `tests/test_bench_gui.py`.

**Learned (the expensive part):**

1. **The recorded cause of the slow transfer does not survive reading the
   code, and I repeated it before checking.** H6.2 attributed 6.7-11.2 s for
   125 MB to "~125 round trips at ~50 ms each". There are no such round trips:
   the client issues at most FOUR GETs per capture (one per channel, two if the
   ring wraps) and the helper streams the whole reply over one connection. The
   125 are `sendall()` calls on a continuous unidirectional stream, which is not
   a pattern Nagle plus delayed-ACK stalls. **The real cause is still unknown**,
   which is why the per-GET timing went in. Do not quote the round-trip
   explanation; it is wrong.
2. **The experiment is TWO lasers, and no document said so.** Kevin, 2026-08-25:
   a fine sweeper (5000 points over ~1 s, trigger BNC, wavelength axis from its
   log) and a stepper (11 discrete wavelengths, no trigger, no log — set, allowed
   to settle, and read). The deliverable is an 11 x 5000 map. Everything already
   built holds; the 11 sweeps are 11 runs of the same capture.
3. **Q26 is dead under that structure.** It mattered only because the time step
   came from the trigger interval. With the step coming from the sweep duration
   and the stepper read as a scalar, nothing depends on one-log-point-per-pulse.
   **Q24 still matters** — periodic in time vs in wavelength.
4. **f1/f2 vs freq1/freq2 is a live naming collision.** The docs use f1/f2 for
   the AOM *modulation* frequencies (MHz); Kevin uses freq1/freq2 for the
   *lasers* (THz). Same names, different things by nine orders of magnitude.
   Worth separating before it produces a plausible-looking bug.
5. **Decimation 16 is close to free once the real detector is in.** The measured
   penalty is 1.8 dB on the BOARD's noise (3.75 -> 4.58 uV), but at the expected
   ~11 uV detector floor the totals are 11.6 vs 11.9 uV — **about 0.2 dB** for
   half the data. Rests on the 11 uV estimate, which P4.4 measures. Kevin asked
   for it; not applied as a default anywhere.

**Broke / still broken:**

- **None of the transfer work is verified against the board.** The helper on the
  board is still the old one — `/dev/shm` is RAM, so it needs re-copying.
- The laser is still silent. Untouched this session.
- `describe_capture_plan()` still recommends decimation 2 plus the device-tree
  memory move, which contradicts the settled decision (decimation 8, no move).
  Spotted, flagged to Kevin, **not yet fixed.**

**Next:**

1. Re-deploy `rp_fastread.py` and take one capture — the per-GET line will say
   whether the time is board-side or client-side. That is the whole point of it.
2. **The end-to-end pipeline**, still the top Tier 1 item and still not started.
   Now better specified: one 5000-point trace per sweep, tagged with the
   stepper's wavelength, eleven times.
3. Fix the stale `describe_capture_plan()` recommendation.
4. Decide the 11 x 5000 output layout (eleven CSVs plus an index, or one file
   with a lambda-2 column).

---

## 2026-08-25 (later) — Claude (Claude Code) — the end-to-end pipeline exists

**Goal:** Join demodulate -> trigger edges -> laser log -> wavelength -> CSV.
That path was the deliverable and nothing had ever run it.

**Did:** Added `src/rp_lockin/pipeline.py` (`reduce_sweep`, `measure_sweep`,
`SweepReduction`) and `tests/test_pipeline.py`, checked against emulator truth.
A synthetic sweep with the resonance planted at a known wavelength comes back
with the peak at **exactly** that wavelength, through the real code.

**Learned — four things the joining exposed that no component test could:**

1. **`find_trigger_edges` returns BOTH polarities, and the real trigger is a
   PULSE.** 25 us wide every step (TSL-775 p46), so each logged point makes two
   transitions. Averaging both gives a step near half the truth — a clean-looking
   trace with the wavelength axis compressed 2x. Added `polarity=` (default
   "both", unchanged) and the pipeline asks for "rising". **This would have
   been a live bug on the first real sweep.**
2. **The emulator only made SQUARE WAVES.** `make_trigger_sequence` alternates
   state at every time given, i.e. 50% duty cycle, which no laser emits — and
   which hides trap 1 completely. Added `make_trigger_pulses`, with `n_pulses`,
   because a train running to the end of the record (rather than stopping when
   the sweep does) stretches the measured span and inflates the step. Both of
   those were mistakes I made in the first draft of the test.
3. **The recommended TAIL makes the trace legitimately overrun the laser's
   table**, and `map_to_wavelength` refuses an overrun by default. Those points
   are correctly NaN. `reduce_sweep` now defaults `overrun_tol` to
   `recommended_tail()`, which is the honest bound: a real misalignment is off
   by a large fraction of a sweep, far more than a tail, so it is still caught.
4. **Pre-roll shorter than the settling produces no pre-sweep points at all.**
   Settling trims 113 output points = 22.6 ms; an 8 ms pre-roll leaves nothing,
   and `n_before == 0` looks exactly like a mapping bug. Use
   `recommended_preroll()` (45.2 ms). Written into the test that found it.

**The step comes from the trigger SPAN / (N - 1)**, per Kevin 2026-08-25, with
the span measured rather than assumed. Dividing by N instead is a 1-in-N error
that equals one whole step of drift by the far end. **Q26 is dead** under this
scheme: nothing counts pulses, so one-log-point-per-pulse stops mattering.

**Broke / still broken:**

- `measure_sweep` is written but **has never touched hardware** — no board.
- The GUI does not use the pipeline yet; its CSV still writes an empty
  wavelength column.
- Still outstanding from earlier today: the board runs the OLD `rp_fastread.py`,
  and `describe_capture_plan()` still recommends decimation 2 plus the
  device-tree move, contradicting the settled decision.

**Next:** wire the GUI's Demodulate tab to `reduce_sweep` so a laser log can be
loaded and the axis becomes wavelength; then the 11 x 5000 stepping loop.

**GUI wired to the pipeline (same session).** The Demodulate tab now runs
`reduce_sweep` whenever a laser log is loaded, and the x axis becomes
wavelength. Verified headlessly end to end: resonance planted at 1549.0000 nm,
recovered at 1548.9841 nm, inside a fifth of the 0.05 nm logged step, with the
CSV carrying real wavelengths and full provenance.

Three things this forced, all of them corrections rather than additions:

1. **Simulate now builds a REALISTIC record** -- pre-roll, sweep, tail, a 25 us
   trigger PULSE per logged point, and a matching wavelength log. It used to
   make a square wave with no pre-roll, which cannot exercise the pipeline and
   actively hid the two-edges-per-pulse trap. It now refuses a duration too
   short to hold pre-roll + tail rather than producing a sweep with neither.
2. **The GUI's find-edges asks for rising edges** and reports PULSES. It was
   counting both polarities, which on a real trigger doubles the count and
   halves the step.
3. **The cursor readout needed an index translation.** With a wavelength axis
   the plot shows only the MAPPED points, so a plot index is not a trace index
   -- without `_plot_index` the X/Y/R/theta boxes would describe a point a
   whole pre-roll away from the pointer. Pinned by a test that asserts the two
   indices actually differ.

The Laser tab's "read wavelength log" button used to draw the log over the
trace plot, which looked like a result and silently replaced the measurement.
It now loads the log into the pipeline instead.

195 offline tests pass.

**Same session, continued: the stale planner, the stepped series, and CLAUDE.md.**

1. **`describe_capture_plan()` fixed.** It had recommended decimation 2 plus the
   device-tree move for eleven days after both were decided against, because
   `recommend()` bounded by `MAX_DMA_MB` (512, the hypothetical size after a
   REJECTED move) instead of the region that exists. Added `DMA_REGION_MB = 128`
   and planned against it; it now says decimation 8, no board changes.
   **There were no tests on `plan_capture`, `recommend` or
   `describe_capture_plan` at all** — that is why it drifted. `tests/test_planning.py`
   now asserts the recommendation IS decimation 8 and that the output contains
   no device-tree instructions.
2. **A second stale number in the same function**: the transfer column quoted
   `SCPI_MB_PER_S` (5.7) for a path that does not use SCPI. `acquire_deep_fast`
   reads over the raw socket. Added `FAST_READ_MB_PER_S = 11.0` (conservative
   end of H6.2's measured 11-19 MB/s); a 1 s decimation-8 sweep now estimates
   ~11 s rather than 21 s, and the summary names both paths.
3. **`SweepSeries` / `write_series`** for the 11-step measurement. One CSV per
   sweep plus an index, rather than one long file with a lambda2 column: each
   trace stays independently openable, provenance stays in a header instead of
   being repeated on 55,000 rows, and a failed sweep costs one file. The
   stepping wavelength is unit-guarded like everything else, and the summary
   flags any sweep whose alignment is suspect — a shifted axis looks normal in
   the trace, so it has to be said out loud.
4. **CLAUDE.md refreshed.** It still described a ONE-laser experiment, still
   listed Q26 as a live assumption, quoted a stale test count, and had no entry
   for `pipeline.py` or the GUI. All corrected, including the f1/f2 vs
   freq1/freq2 naming collision.

208 offline tests pass.

**Next, unchanged and still needing hardware:** re-deploy `rp_fastread.py` and
take one capture to settle where the transfer time goes; run P2 (trigger into
IN2) once the board is reachable. **Still needing nothing:** bench scripts for
P3-P6, and a code-review pass over everything written on 2026-08-14, which has
still never had a second look.

**Code-review pass over the 2026-08-14 code (same session).** `santec.py`,
`wavelength.py`, `output.py`. Three findings, all of the project's
characteristic kind — plausible wrong answers rather than crashes.

1. **`check_alignment`'s span test is VACUOUS under the pipeline's default
   step, and it reads as though it is not.** Its docstring says both a count
   and a span are checked "because either alone is weak". But
   `reduce_sweep` derives the step as (edge span)/(N−1), which makes
   `table_span` identically equal to `edge_span`. **Verified**: a capture that
   misses the first two pulses — where every wavelength really is shifted —
   still reports a span error of exactly 0.00%, and only the COUNT check finds
   it. Not removed, because the span test does real work when the table comes
   from a configured sweep time or an explicit step. Documented at both ends,
   and `SweepReduction.describe()` now says so at the point of use, because the
   summary otherwise prints two identical spans that look like corroboration.
   Pinned by `test_the_span_check_is_vacuous_when_the_step_came_from_the_span`.
2. **`santec.py` had no way to resynchronise.** `self._buf` persists between
   queries, so a read that times out part-way through a reply leaves the
   remainder behind and every subsequent query returns the TAIL OF THE PREVIOUS
   ONE — plausible values, nothing raised. `hardware.py` records exactly this
   failure against the board on 2026-08-12 and fixed it with `*IDN?` as a sync
   token; the laser client had no equivalent. Added `resync()`, reads only, plus
   `drain()` on both transports — because our buffer is not the only place bytes
   hide, and clearing only ours leaves the serial driver's to arrive next.
   Writing the test exposed that limit, so it is pinned too rather than
   overstated.
3. **`TriggerConfig.step_m` is a scalar with no units guard**, unlike
   `wavelength_m()` which raises rather than return nanometres as metres. Its
   unit depends on the command set (metres vs nanometres) AND on SETTing
   (it is SECONDS when periodic in time) — while the two manuals disagree about
   which value that is. Nothing computes with it today, so it is documented
   rather than restructured, with a note that anything which starts computing
   with it must resolve the units first.

Also noted, not changed: `analyse_trigger_train` produces confident nonsense if
handed BOTH polarities of a pulse train (median interval lands between 25 us and
the real spacing, so every interval reads as a missing pulse). The pipeline
passes rising-only edges so it cannot happen there, but the function does not
defend itself.

214 offline tests pass.

**Bench scripts P2-P6 (same session).** `scripts/_bench.py` plus
`p2_trigger_check.py`, `p3_drive_chain.py`, `p4_detector.py`,
`p5_first_measurement.py`, `p6_robustness.py`. **P2 was written too**, not just
P3-P6, because it is the next step to actually run and had no script.

**Writing P2 found a real blocker in `hardware.py`.** P2 needs IN2 on HV (the
trigger is 3.3 V) and IN1 on LV, and the docs say so — but `_reapply_front_end`
forced BOTH channels to one coupling/gain after every `ACQ:RST`, so IN2 came
back on LV and clipped the trigger into a flat line. That reads as "the laser is
not triggering", not as a range error. **P2 as specified was impossible with the
old API.** `front_end` is now per channel, with `setup_channel(ch, coupling,
gain)`; `setup_acquisition` still sets both, and `rp.coupling`/`rp.gain` still
read channel 1 so older callers are unaffected.

Safety scaffolding, shared by all five:

* `session()` disarms both outputs and closes the link on EVERY exit path.
* Anything that drives an output needs `--i-am-present` AND a typed "drive".
  A flag alone is too easy to leave in a shell history; EOF is not consent.
* P3 runs ONE sub-step at a time, so nothing is energised as a side effect.
* **P5.2 refuses to run before P5.1, and refuses if P5.1 was not clean** — the
  verdict is written to `data/p5_control.json` rather than left to memory.
  An amplifier-generated product sits at exactly the frequency P5.2 looks at,
  so a signal there means nothing until the one-tone control is clean.
* P5 takes the noise floor as an argument and says plainly when the default is
  the datasheet expectation rather than P4.4's measurement.
* Every script prints a block to paste into this log, and exits non-zero if any
  check failed.

Also found while writing P4: `PLAN.grid` does not exist (it is
`asg_grid(PLAN.fs)`) — a NameError that would have surfaced on the bench with
an amplifier powered. `tests/test_bench_scripts.py` now imports every script for
exactly that reason, alongside pinning the consent gates and P5's ordering.

233 offline tests pass. **None of these have been run against hardware.**

---

## 2026-08-26 — Claude (Claude Code) — documentation sweep for handoff

**Goal:** Kevin is handing the project on. Make every document true.

**Did:** Rewrote the HANDOFF block at the top of this file from scratch, and
swept all thirteen other documents. The changes worth knowing about:

- **`docs/11-pipeline.md` is new** — the deliverable path, where its time step
  comes from, and the five defects joining it up exposed. `00-index.md` and
  `README.md` reference it.
- **The two-laser correction was propagated everywhere.** Before today,
  `README.md`, `01-overview.md`, `00-index.md` and `08-phase2-hardware.md` all
  described a single sweeping laser. The f1/f2 vs freq1/freq2 naming collision
  is now called out in four places, because it will otherwise produce a bug that
  looks entirely reasonable.
- **`README.md`'s "Key numbers" table carried the PRE-GRID frequencies** — 80
  MHz, 5/6 MHz, lock-in 1 MHz, a 250-sample buffer. Every one of those is wrong
  and has been since 2026-08-12, in the most-read file in the repository, next
  to a warning about never hardcoding the round number. Corrected, with the
  reason attached.
- **The wrong transfer explanation was withdrawn at its source** in
  `07-phase1-loopback.md`, not only in the summary. The measured times stand;
  the story about them did not survive being checked.
- **ADR-0002 still said the planner recommends decimation 2.** Corrected with
  the memory reasoning and a pointer to why the planner drifted.
- **Q26 marked dead in all five places it appeared.** Q27 re-opened with the
  driver evidence. **Q28 raised** for the Ethernet failure, and both are now in
  the blocking table at the top of `10-open-questions.md`, which previously
  listed neither actual blocker.
- `CLAUDE.md` gained four new entries under "Things that will bite you" and a
  section on the P-series safety contract.

**Learned:** two documents were corrupted mid-edit by writing `\0000` inside a
Python string — it is an octal escape, and it wrote a NUL byte that turned both
files binary. Caught because `grep` reported "Binary file matches". **Build
backslashes with `chr(92)` when scripting edits**, and scan for NUL before
committing; there is now a check that does both.

**Broke / still broken:** nothing in code. 233 tests pass. The two blockers are
unchanged and both are hardware: the Ethernet link and the laser.

**Next, for whoever picks this up:**

1. **Push.** The repository was 17 commits ahead of GitHub at the start of this
   session and everything from 2026-08-25/26 is local-only.
2. Fix the Ethernet link — cross-test each end against a switch (Q28).
3. Re-deploy `rp_fastread.py`; the board still runs the old one.
4. Run P2. It needs only the BNC already fitted.
5. The laser's VCP driver (Q27) — a clean install on other hardware is the
   cheapest test the blocker has ever had.

A provisioning runbook for a fresh control PC was published as an artifact this
session; if that link is lost, its content is reproducible from this log plus
`pyproject.toml`.

---

## 2026-08-26 (later) — Claude (Claude Code) — flattened the nested folder

**Goal:** Remove the `rp-lockin-2tone/rp-lockin-2tone` nesting, which had just
caused a real failure.

**What the nesting actually was.** Someone ran `git init` + `git add .` in the
OUTER folder while the real project already sat inside it with its own `.git`.
Git recorded the inner project as a **submodule pointer** (`mode 160000`), not
as files. A later commit removed the pointer. So the outer repo's entire
history was: add `.claude/settings.local.json` and a stray gitlink, then delete
the gitlink. No value.

**It cost something before it was fixed.** Both repos had been pointed at the
same remote, and a push run from the outer directory put only `.claude` on
GitHub — which looked exactly like the real push having failed.

**Did:**
- Verified the real repo's 72 commits were pushed and `origin/main` matched
  (`17b3439`) **before** touching anything. The flatten was not attempted while
  the work existed only on this disk.
- Moved the outer `.git` aside to the scratchpad rather than deleting it.
- Moved all 14 inner entries up one level; removed the empty inner folder.
- **Reinstalled the editable package.** This is the part that would have bitten
  a future session: `__editable__.rp_lockin_2tone-0.1.0.pth` still contained the
  OLD absolute path, so `import rp_lockin` failed after the move. The venv
  itself survived — Windows resolves `sys.prefix` from the executable's location
  — but the editable install did not.
- Added `.claude/settings.local.json` to `.gitignore`. A user-level ignore at
  `~/.config/git/ignore` had been hiding it; that will not exist on a fresh
  machine, so the rule is now in the repo.

**Learned:** moving a Python project on Windows breaks the editable install and
nothing else. `pyvenv.cfg`'s `command =` line still records the old path and is
harmless — it is a record of creation, not a runtime lookup.

**Next:** unchanged — the two hardware blockers. The layout is no longer one of
them.

---

## 2026-08-28 — Claude (Claude Code) — new control PC; both blockers dead; the trigger is real

**Goal:** Kevin is on an entirely new machine with nothing but the code, VSCode
and git. Get the project running again, then reconnect the instruments.

### Dates: the previous entries were wrong, and are now fixed

Nine entry headers disagreed with the commits that produced the work. Corrected
against `git log`, which is the only authoritative record:

| Entry | Was | Now |
|---|---|---|
| first hardware contact; H1 essentially done | 08-12 | **08-10** |
| H3.3 done: noise floor measured, Q8 answered | 08-12 | **08-13** |
| Q25 measured: AC coupling is free | 08-14 | **08-17** |
| Q12 answered: attenuator decided at 20 dB | 08-14 | **08-17** |
| attenuator revised to 10 dB | 08-14 | **08-17** |
| attenuator recommendation WITHDRAWN | 08-14 | **08-17** |
| the 80 MHz belongs to the AOM, not the DUT | 08-14 | **08-18** |
| correction: Kevin's Q20 answer was right after all | 08-14 | **08-18** |
| P1 attempted: the laser does not answer | 08-14 | **08-20** |

The pattern: a fortnight of work between 08-17 and 08-20 had been collapsed onto
08-14. **This matters beyond tidiness** — "the laser has never answered since
2026-08-14" was six days more alarming than the truth, and the attenuator
decision looked like three reversals in one day rather than a day's iteration.

**Not yet swept:** the same wrong dates appear in prose across `CLAUDE.md`,
`docs/10-open-questions.md` and others ("Kevin, 2026-08-14" on the AOM point,
Q12, Q25, Q27's "raised 2026-08-14"). Those need the same treatment, carefully —
many 08-14 references are correct, so a blind replace would corrupt them.

### The environment, rebuilt

New PC had git, VSCode, OpenSSH and winget — and only the WindowsApps Python
stub. Installed Python 3.13.15, cloned to `C:\dev\rp-lockin-2tone` (deliberately
off OneDrive), venv, editable install. **232 passed, 1 skipped in 4m17s** on
numpy 2.5.2 / scipy 1.18.1 / pytest 9.1.1 — a much newer stack than the suite was
written against, and it needed no changes.

Git identity was unset; set to match the existing history rather than guessed.
The unzipped snapshot Kevin had was byte-identical to `main` — all 54 apparent
differences were CRLF from `core.autocrlf`, zero real content differences.

**The repo URL is recorded nowhere in the repo**, so a rebuild has to ask for it.

### The laser: found already solved, five days earlier

`Desktop\TSL-775 Test\` contains a complete working driver, a 27 KB handoff and
verified sweep data, all dated **2026-08-21**. The 08-25 and 08-26 sessions never
saw it and went on calling the laser an open blocker, recommending a driver
reinstall that could not possibly have worked.

**USB is a hardware fault inside the instrument**, exhaustively established. LAN
works. Full detail is in the HANDOFF block above and in `TSL775_HANDOFF.md`.

On the day: the laser was unreachable, and the documented triage placed it
exactly — instrument powered (FT232H enumerating), gateway and internet fine,
`10.101.0.1` replying, `tracert` reaching hop 1 and dying. Kevin reapplied the
LAN settings on the front panel and it came straight back.

**Its configuration had drifted off the validated one** and three of the
differences fail silently: `:TRIG:OUTP` was 0 (no trigger train, empty log),
`:WAV:SWE:MOD` was 3 (two-way — the return pass overwrites the log), and the
speed/step combination gave a 10 Hz trigger where the board expects 5 kHz.
`sweep_capture.py` sets all of them and restores the originals in a `finally`.

**Power was found at 12.00 dBm ≈ 15.8 mW** against the August-validated 4.00 dBm,
with a photodetector now connected whose saturation is ~0.96 mW and whose damage
threshold is still unknown. Set back to 4.00 dBm before anything was enabled.

**The whole verification was run with the shutter CLOSED**, which emits no light
at all. `sweep_capture.py` only reports the shutter, never opens it. Worth
knowing: the internal power log still reads correctly with it closed (3.983 –
4.027 dBm), so the monitor sits before the shutter.

### The trigger, observed electrically for the first time

`TSL775_HANDOFF.md` §7.3 called this the top priority: everything about the
trigger/log 1:1 correspondence rested on instrument-side self-consistency plus
the manual, and nobody had put a digitiser on the BNC.

**First attempt failed** — P2 sat at `WAIT` for 90 s through a sweep that
emitted all 5001 pulses. A read-only probe of both inputs during a live sweep
settled it in one shot:

```
IN1: peak-to-peak 2056.0 counts   min -9.0   max 2047.0   mean 840.6
IN2: peak-to-peak    1.0 counts   min  6.0   max    7.0   mean   7.0
```

IN2 dead flat: the trigger was in the board's **dedicated external-trigger
connector**, not analog **IN2**. Those are different things, and the design needs
the train *digitised* — `find_trigger_edges` runs on the IN2 trace, and the
external pin would start a capture while recording no train, losing both the
measured time step and the free clock-ratio check. Kevin moved it.

**Second attempt: the trigger is real and on spec.** 5001 pulses recorded against
5001 logged points, width 24.997 µs (sd 0.001) against the 25 µs spec, spacing
199.997 µs, no pulses lost at decimation 8. **Q24 answered** — see the HANDOFF.

**Learned:** the probe that settled it took two minutes and replaced an argument
about wiring with a number. Reach for that earlier.

**Broke / still broken:**

1. **`p2_trigger_check.py` compares raw ADC counts against a voltage spec** — the
   only P2 failure, and the hardware is fine. 302 counts on HV is 3.32 V. The
   rise-time figure comes out negative too, and the failure message misdirects.
   Not fixed; it needs an offline test alongside the fix.
2. **NOT broken after all: the IN1 "clipping" was an artefact.** The full-scale
   reading above came from a stale standard-buffer capture taken right after a
   deep AXI capture. Re-measured over 40 captures, IN1 is flat at ~1 count and
   ~0 V on both couplings. **The IN1 numbers in the probe block above are the
   bad reading, kept deliberately so the artefact is recognisable.** What
   remains genuinely unknown is whether the detector responds to light at all —
   it has only ever been observed with the shutter closed.
3. **P2.4's line-fit residual is 43.2 µs rms** with a minimum spacing of
   178.125 µs. Unexplained, and it may be an artefact of (1). The wavelength axis
   rests on this measurement.

### Fixed later the same day

- **The counts/volts bug is FIXED**, with `ADC_COUNTS_PER_V_LV/_HV`,
  `ADC_COUNT_MAX/_MIN` added to `constants.py` carrying Q23's caveat, so the
  disputed absolute scale is not silently enshrined. `pulse_shape()` now
  converts once, up front, and reports volts.
- **A clipping check was added** to P2.1. A clipped record still yields
  clean-looking widths and spacings, so it has to be reported separately or it
  is invisible.
- **The negative rise time is FIXED.** `t10` and `t90` were paired by INDEX;
  they are independent crossing lists, so one extra crossing at either end
  shifts every pair by a whole pulse. Now paired with `searchsorted`, as the
  width calculation already did.
- **Four offline tests added**, and — importantly — **each was checked against
  the OLD code and seen to fail.** The first version of the rise-time test
  passed against the bug, because a clean synthetic train cannot produce the
  mismatched crossing lists; it was tightened to start the record part way up
  an edge, which is what a real capture does. **A regression test that has
  never failed proves nothing.** Suite is now **237 passed**.
- **Dates swept through the docs**, but only where the commit that introduced
  the line could be identified with `git log -S`. Note that three lines came
  back as "Reorganise docs into a coherent set" (08-14) — that commit MOVED
  text between files, so it dates the move, not the work; those fell back to
  the session-log mapping. Q24, Q27 and Q28 updated in
  `docs/10-open-questions.md`; the stale blocker claims in `CLAUDE.md` replaced.
- `.gitattributes` pins `rp_fastread.py` to LF. **The repo URL is now in
  `README.md`.**

**Blocked, not forgotten:** the 43.2 µs residual could not be investigated
because **the laser's LAN interface dropped out a second time** partway through
the session, with the same signature as the first (instrument powered, both
gateways replying, no answer on 5000). Two dropouts in one afternoon, both after
sustained activity including the 40 KB + 20 KB binary log reads that
`TSL775_HANDOFF.md` §3.5 already lists as a suspected contributor. **That is now
two data points for an open question that had none.** The armed capture timed
out cleanly and left the board healthy.

**Next:**

1. ~~Fix the counts/volts units in `p2_trigger_check.py`~~ — done.
2. Show the detector responds to light at all — IN1 has only been seen in the
   dark. Needs the shutter open, and the PDA05CF2 damage threshold first.
3. Explain the 43 µs residual before trusting the wavelength axis. Needs the
   laser back. `scratchpad/edge_profile.py` is written and ready to run.
4. ~~Sweep the stale dates~~ — done for everything pinnable to a commit.
5. ~~`.gitattributes`; repo URL into `README.md`~~ — done.
6. **Whether the LAN dropouts correlate with the binary log reads.** Two for two
   today. If they do, the fix may be as simple as pacing those reads.

---

## 2026-08-28 (later) — Claude (Claude Code) — the full sweep runs, and the time axis is not uniform

**Goal:** get to a full end-to-end laser sweep as fast as possible.

**Did:** vendored the proven `tsl775.py` into `scripts/` (it was the only
working laser code and it lived on the Desktop), and wrote
`scripts/full_sweep_test.py` — the first run of `pipeline.reduce_sweep` against
real hardware. **It passes.** One sweep, shutter closed, no RF: real trigger,
real laser log, real reduction, `sweep_001.csv` with 5097 rows.

Two mis-sizings found by the code refusing rather than guessing:

- `map_to_wavelength` **refused to extrapolate** past the end of the laser's
  table when the record was sized to the DMA ceiling (1.0737 s) rather than to
  the sweep (1.000 s). It was right to: every sample past the last logged point
  has no wavelength. The record is now pre-roll + sweep + tail.
- The `trigger_threshold=0.0` default finds **no edges at all** on our unipolar
  trigger, which idles at 6 counts and peaks at 302. The script computes the
  threshold from the record.

### Q29 — the answer to the 43.2 µs residual, and a correction

**I was wrong about the mechanism.** From P2's four summary numbers I inferred
"a large smooth wander plus one isolated short gap", and ruled out widespread
gap variation. The captured edges say otherwise:

```
gaps: mean 200.005  sd 5.867  min 181.212  max 225.038 us
      2061 of 5000 gaps more than 5 us off the median
      peak-to-peak 43.8 us = 21.9% of the mean
```

The gaps vary *everywhere*, not in one place. **The error was reasoning from
`min` without `sd`** — P2 reports the minimum gap but not its spread, and I
assumed a small spread. It is 5.87 µs. Print the spread.

**What it actually is: the sweep speed ripples by about ±11%, periodically,
with a period of 0.41 nm (~20.4 triggers, 4.1 ms).** Because the trigger is
periodic in WAVELENGTH (Q24), that speed ripple is recorded directly as
interval variation. Integrated, it puts the edges up to **157.7 µs = 0.79 of a
step** off a uniform grid — **15.8 pm of wavelength error**, against a laser
whose own log is linear to 0.4 pm. Assuming uniformity inflates the error ~40×.

**Why nothing caught it before.** The laser-side check is tautological:
`sweep_capture.py` sets `dt = TRIG_STEP_NM / SPEED_NM_S` from the *commanded*
settings, builds `xs = [i*dt]`, then fits wavelength against `xs`. Wavelength is
uniform in index by construction, so "linear in time" tests nothing about time,
and "fitted rate == commanded" returns the commanded number by arithmetic —
which is why it reads **+100.0000 nm/s** against 100.0. Same genre as the
vacuous span test in `check_alignment`.

**The fix costs nothing:** stop deriving a uniform step and use the measured
edge times, which every capture already contains. Not yet done.

**Broke / still broken:** `reduce_sweep` still defaults to the uniform step, so
today's CSV carries up to 15.8 pm of axis error. The laser's LAN dropped out
twice more today; front-panel reapply fixed it both times.

**Next:**

1. **Use the measured edge times in `reduce_sweep`** instead of span/(N−1), with
   an offline test built on a rippling train. This is the live task.
2. Ask santec what the 0.41 nm ripple is — etalon, or grating drive?
3. The detector still has never seen light (Q11b), and the PDA05CF2 damage
   threshold is still unknown.

---

## 2026-08-28 (later still) — Claude (Claude Code) — Q29 fixed: the axis uses the measured edges

**Goal:** stop `reduce_sweep` assuming a uniform time step.

**Did:** the wavelength axis is now built from the trigger edges the capture
already contains. Re-reducing the SAME real capture (`data/sweep_001.npz`) both
ways:

```
measured edge times   deviation from uniform  50.55 us
uniform step          deviation                0.00 us
difference between the two axes: max 13.68 pm = 0.684 logged steps, rms 2.81 pm
                                 (one logged step is 20 pm)
```

That difference is the error the uniform grid was carrying, and removing it
cost nothing — the edges were always in the record.

**Lost pulses are handled by ORDINAL, not array position.** This mattered more
than expected: the obvious implementation (fall back to a uniform grid whenever
a pulse is missing) *broke the existing Q21 test*, and rightly — it throws away
every other measured edge because one is absent, which lets Q29's error back in
through the door Q21 guards. Indexing rows by array position instead would BE
the Q21 counting bug. A gap now costs one interpolated row.

**Learned, about testing rather than about the instrument:**

- **A peak-position test could not work here.** One output sample is 0.59 of a
  logged step in the synthetic harness, so the peak is quantised more coarsely
  than the whole effect. Measured both argmax and a centroid before committing
  to an assertion — neither separated the two axes and the **centroid actually
  favoured the wrong one**. The tests assert on the axis itself instead.
- **An over-harsh synthetic is not conservative.** The first rippling train used
  ±25% gap variation against the instrument's ±11%; at that level two merged
  gaps reach 2.6× the median, round to THREE missing rows, and drop into the
  uniform fallback for a reason the hardware never produces. The synthetic now
  matches the measurement.
- The first ripple peak sits inside the 22.6 ms of filter settling, so a
  resonance planted there is trimmed before the mapping sees it — CLAUDE.md
  trap 3, met from the inside.

All three new tests were checked to fail with `use_edge_times=False`. **240
tests pass.**

**Broke / still broken:** the laser's LAN dropped out a **third** time, which is
why the fix is validated against the stored capture rather than a fresh sweep.
Three dropouts in one afternoon, all after sustained activity.

**Next:**

1. Re-run `full_sweep_test.py` once the laser is back, to confirm on live data.
2. The LAN dropouts now have three data points. If they track the binary log
   reads, pacing those may be the whole fix.
3. Q11b — the detector has still never seen light — and the PDA05CF2 damage
   threshold.

---

## 2026-08-28 (evening) — Claude (Claude Code) — THE CHAIN WORKS: first real optical measurement

**The linear sweep runs end to end and the signal is provably optical.** Every
component between the board and the detector is now exercised and confirmed.

| Run | Amplitude at 915.527 kHz |
|---|---|
| Normal, laser +4.00 dBm | **130 mV** |
| Control, laser −5.00 dBm | **15 mV** |
| Control, OUT1 disarmed | **nanovolts** |

**The two controls answer two different questions and both came back clean.**

- **No drive → nanovolts.** The 915 kHz exists only while OUT1 is on. It is not
  ambient, not another instrument, not the demodulator inventing something.
- **Low power → the amplitude scales with LIGHT.** +4 to −5 dBm is a 9 dB drop,
  predicting a 7.94× fall; measured 130/15 = **8.67×**, agreeing to **0.38 dB**.
  The RF drive was byte-identical in both runs, so an electrical pickup path
  could not have moved at all. It moved by the optical ratio.

**Q11b is CLOSED.** The photodetector responds to light. Until today every
optical measurement had run with the shutter closed, where a working detector
and a disconnected one are indistinguishable.

**What this proves, in one line each:** the AM drive reaches the amplifier; the
amplifier drives the AOM; the AOM modulates light at f1; the light reaches the
detector; the detector converts it; IN1 digitises it; the lock-in recovers it;
the trigger places it on a wavelength axis; the CSV comes out.

### How the controls got there, which is the part worth remembering

Three of them were wrong before this one worked, and each was wrong in a way
that still produced a confident-looking result:

1. **The checkbox only LABELLED the output file.** A "control" run with the
   beam never blocked is indistinguishable from a real one. Kevin ticked it,
   got the same amplitude, and correctly disbelieved the setup rather than the
   control.
2. **Closing the shutter in software does not work.** The instrument REOPENS it
   when a sweep starts — found with a scope on the detector, not by us. Any
   shutter-based control silently has light in it. The shutter is now read
   DURING the sweep, because its state beforehand means nothing.
3. **The replacement control asked for −10 dBm and the laser ignored it.** Its
   range is −5 to +13 dBm (`:POWer:LEVel? MIN`/`MAX`), and a request below the
   floor is not refused — the setpoint stays put and the query answers with the
   old value. Only the read-back caught it. The limits are now queried from the
   instrument and the request clamped to them.

**The control that finally worked removes the LIGHT or the DRIVE, and depends
on neither a human remembering nor a shutter behaving.** Kevin's suggestion of
"just don't sweep" would not have worked for a reason worth recording: the
sweep does not create the signal, so a static run shows the same amplitude with
no wavelength axis and no trigger to capture on.

### Also fixed

- **A failed job left the UI wedged.** `_pump` logged the error and showed a
  dialog but ran no callback, so one refused sweep greyed out RUN SWEEP until
  the GUI was restarted from a terminal. Jobs carry an `on_error` now.
- **Indicators measured rather than inferred.** OUT1's state came from
  remembering which buttons had been pressed; it is polled from
  `OUTPUT1:STATE?` once a second, skipped while the worker is busy.
- **Amplitude is in volts, not ADC counts**, and the wavelength axis prints
  1500/1550/1600 rather than "1.5k".
- **The power gate reads at the DETECTOR**, not at the laser: the 90/10 and
  50/50 put about 13 dB between them, and gating on the laser's own number
  refused runs that were nowhere near saturation.

**Broke / still broken:** nothing known. 245 tests pass.

**Next:**

1. **Look at the SHAPE.** 130 mV is the level; the wavelength dependence is the
   physics. A smooth curve is the AOM's Bragg efficiency times the detector's
   responsivity. Structure would want explaining.
2. **Sanity-check the modulation depth** against the DC level on the scope. If
   the AC amplitude is far below half the DC, the AOM is not being switched as
   fully as depth-1 AM assumes, which bears on Q12.
3. The stepping laser (TSL-770) is still untouched — half the deliverable's
   wavelength axis.
4. Then P3 properly, and the two-tone measurement.

---

## 2026-08-28 (late) — Claude (Claude Code) — the AOM's own 2*f1, measured

**The AOM produces a second harmonic at -17.5 dB, and it has the SAME
wavelength shape as the fundamental.** Measured while testing the SHG path with
no crystal in it.

| Demodulated at | Amplitude | Shape |
|---|---|---|
| f1 = 915.5273 kHz | 180 mV | the linear trace |
| 2*f1 = 1831.0547 kHz | **24 mV** | **the same trace, scaled** |

24/180 = 13.3% = **-17.5 dB**.

**Why the same shape is the confirmation, not a coincidence.** An AOM diffracts
as sin^2 of its drive, and the drive is depth-1 AM, so the diffracted light is
already distorted before it goes anywhere: it carries harmonics of f1. That
harmonic rides on the SAME light, through the same fibre, onto the same
detector, so its wavelength dependence is the fundamental's multiplied by a
constant. A scaled copy is exactly what a distortion product looks like; a
DIFFERENT shape would have meant something else was going on.

**This is the SHG confound, now quantified.** Any second-harmonic experiment
has to clear 13.3% of the fundamental's amplitude before it has said anything.

### Two ways to separate real SHG from it, when the crystal arrives

1. **POWER SCALING, and this is the good one.** The AOM's 2*f1 is a
   linear-optics artefact -- the light is already modulated at 2*f1 before it
   reaches any crystal -- so the detected amplitude scales as P^1. True SHG
   scales as **P^2**. On log-log against laser power the AOM background has
   slope 1 and SHG has slope 2. **This works with the crystal left in place**,
   which crystal-in/crystal-out does not, and the laser's -5 to +13 dBm range
   gives an 18 dB lever arm. Worth measuring the slope-1 baseline BEFORE the
   crystal arrives, so the comparison is against data rather than theory.
2. **The detector.** The AOM's harmonic is carried on 1550 nm light. SHG of
   1550 is 775 nm, which the InGaAs PDA05CF2 cannot see at all (800-1700 nm).
   A silicon detector behind a filter that blocks the fundamental does not
   receive the confound in the first place -- only whatever fundamental leaks
   through the filter carries it.

### The trap that found this

Demodulating at a typed "1831" kHz gave a clean SINE WAVE, which reads as a
result. It was a beat: the ASG snaps the drive to its 15258.789 Hz grid, so the
real second harmonic is **1831.0547 kHz** and 1831.0000 is **54.7 Hz** away. A
lock-in referenced 54.7 Hz from its signal returns a 54.7 Hz beat, and
`amplitude()` projects onto a common phase, which turns that into a sine across
the trace. About 55 cycles in a 1 s sweep.

**Fixed in the bench two ways.** The Demodulate panel has f1 / 2*f1 / 3*f1
buttons that take the SNAPPED drive frequency, so the harmonic cannot be typed
wrong; and the lock-in output is checked for sign changes after every
demodulation, which names the beat and its frequency rather than leaving a sine
on screen.

**Next:** measure the 2*f1 amplitude against laser power now, and confirm the
slope is 1. That is the baseline the crystal will have to beat.

---

## 2026-08-28 (night) — Claude (Claude Code) — the ASG grid was never a hardware limit

**Kevin said he had previously run a short table played at 1 MHz. The record
said that was impossible. He was right and the record was wrong.**

Measured directly, OUT2 looped to IN2:

```
buffer written    out / play_rate
        16384              1.00
         4096              4.00
         1024             16.00
          250             65.54          = 16384 / N, exactly
```

So a short buffer is NOT ignored and does not produce silence -- Q3's "a
50-sample buffer produces no output at all" is wrong. What actually happens is
that the board treats whatever you write as the whole table, so the output
frequency is `cycles x play_rate x 16384/N`.

**And SOUR:FREQ:FIX accepts 1 MHz and 5 MHz.** There is no 15258 Hz ceiling.
That number is only fs/16384 -- the rate at which the table advances one entry
per DAC clock -- and nothing was ever enforcing it.

### The decisive test

A 16384-entry table holding **one** modulation cycle and **80** carrier cycles,
played at **1000000 Hz**:

```
carrier    80.0018 MHz  (rel 1.000)
sidebands  78.995 and 80.978 MHz
swing      132 counts   (the verified grid path gives 124)
```

Exactly 80 MHz AM'd at exactly 1 MHz, at the same amplitude. **This is what
Kevin remembered doing, and it works.**

### What this supersedes

| Was recorded | Actually |
|---|---|
| Q3: the ASG always traverses 16384 entries; a short buffer gives no output | Short buffers work; frequency scales as 16384/N |
| The fs/16384 grid is a hardware limit | It is only the default play rate |
| Play rate <= 15258 Hz | At least 5 MHz is accepted |
| mod_cycles >= modulation x 16384/fs | mod_cycles can be 1 |

**The one real limit, measured: the play rate is quantised to 1 Hz.** 1000000.5
reads back 1000000, 15151.5152 reads back 15151. So the modulation must be a
whole number of hertz -- and that is the entire remaining grid.

`plan_exact_am` now uses `mod_cycles = 1` wherever it can, so **every whole-hertz
modulation is exactly reachable**, including 999983 (prime) and 1234567, which
the previous divisor-hunting version refused. The carrier lands on the nearest
multiple of the same play rate, within a few hundred kHz of 80 MHz, which the
1550AOM-1's megahertz-wide passband cannot tell apart.

**Not free, and worth knowing:** driving at a high play rate raised spurs at
36.0 and 54.0 MHz to ~6% and ~4.6% of the carrier, against ~0.2% on the default
grid. They sit far from the modulation and an AOM will not diffract them
efficiently, but they are real and unexplained.

**One constraint I had to add back.** The first rewrite chose the pairing with
the closest carrier, which picked 8000 carrier cycles in a 16384 table --
2.05 entries per cycle. That satisfies Nyquist and reconstructs to pure alias.
The search now requires at least 8 entries per carrier cycle, which is what the
measured-working configuration had (204.8).

### The habit this rewards

Three times today a recorded "impossible" turned out to be an untested
assumption: the laser's LAN, the play rate, and the buffer length. In each case
the measurement took minutes and the belief had stood for weeks. **When
somebody who was there says it used to work, test it before explaining why it
cannot.**

**Next:** the two-tone plan (`plan_two_tone_grid`, carrier 80.001831 MHz, f1/f2
on the fs/16384 grid) is still built on the superseded model. It is not wrong --
those frequencies do work -- but it is now needlessly constrained, and
`docs/03-frequency-plan.md` should say so.

