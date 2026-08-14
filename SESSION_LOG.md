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

## STATUS AT A GLANCE — updated 2026-08-14

Read this before the entries below. They are chronological and long; this is
where things actually stand.

**Phase 0 (offline) — COMPLETE. Phase 1 (loopback) — COMPLETE.**
102 offline tests pass. Phase 2 has not started and is gated on a planning
session with Kevin.

### Phase 0 — everything that needed no hardware

| Step | In plain words | State |
|---|---|---|
| Signal processing | Turn a raw recording into an amplitude trace (the lock-in maths) | done |
| Waveform construction | Build the drive signals the board will play | done |
| Capture planning | Work out how long, how fast, and how much memory a sweep needs | done |
| DUT emulator | Fake the experiment's physics so the maths can be checked against a known answer | done |
| Test suite | 102 tests, no hardware needed | done, must stay green |

### Phase 1 — loopback: the board wired to itself, nothing else connected

**H1 — can we talk to the board, and are our commands right?**

| Step | In plain words | State |
|---|---|---|
| H1.1 | Write down which operating system the board runs | done — OS 2.00, build 37 |
| H1.2 | Make sure it is the 250-12 model, not the 125-14 | done — but `*IDN?` cannot tell you; confirmed by label and `monitor -f` |
| H1.3 | Confirm it really samples at 250 million times a second | done, by measurement |
| H1.4 | Find out how much capture memory is reserved | done — 2 MiB as shipped, enlarged to 128 MiB |
| H1.5 | Check every command we send actually works | done — one whole function had to be rewritten, not just corrected |
| H1.6 | Confirm bulk data comes back correctly | done |

**H2 — can the board produce the drive signals?**

| Step | In plain words | State |
|---|---|---|
| H2.1 | Make a modulated 80 MHz signal, check the three expected tones appear | done — all three exactly where predicted |
| H2.2 | Check the modulation depth is the right size, not just present | done — 0.512 / 0.488 against 0.500 ideal |
| H2.3 | Check the looping waveform does not glitch each time it wraps | done — worst junk 48 dB down |
| H2.4 | Run both output channels at once | done — within 0.6% of each other |
| H2.5 | Check the two outputs keep a repeatable phase relationship | **FAILED** — scatters 71–82°. Kevin ruled it does not matter, because we only deliver amplitude. Its one surviving risk was later killed by H3.2 |

**H3 — can we measure what comes back?**

| Step | In plain words | State |
|---|---|---|
| H3.1 | Does a bigger signal read as proportionally bigger? | done — linear over 2.4 decades |
| H3.2 | Does the phase stay steady during one recording? | done — 0.002° over 28 ms |
| H3.3 | How small a signal is lost in the noise? | done — **σ = 3.57 µV per point; a real signal needs ≥36 µV to be clearly visible.** Revised twice; do not quote the older 2.96 µV |
| H3.4 | Does narrowing the filter reduce noise by the expected amount? | done — holds to 2–4% across 8× |
| H3.5 | Does the filter reject signals at the wrong frequency? | done — **matches the design to 0.0 dB** |

**H4 — can we find the laser's trigger in the recording?**

| Step | In plain words | State |
|---|---|---|
| H4.1 | Play a known pulse pattern and recover it | done — zero of 732 intervals wrong |
| H4.2 | How precisely can we time an edge? | done — 0.01 ns, but that is the *board's* contribution only |
| H4.3 | Do the two inputs record at exactly the same instant? | done — aligned to 0.0005 of a sample |
| H4.4 | Start a recording from the trigger, and know where the trigger sits in it | done — **this is the one that matters now** (see below) |

**H5 — can the board play a waveform longer than its buffer?**

| Step | In plain words | State |
|---|---|---|
| H5.1 | Is "Deep Memory Generation" available? | done — **NO, and permanently.** The ceiling is 16384 points = 65.5 µs |
| H5.2 / H5.3 | Play a long fake DUT response | **superseded** — H6.5 instead stepped the amplitude during the capture |
| H5.4 | Fall back to short waveforms and record the limit | done, by taking that route |

**H6 — a full one-second sweep**

| Step | In plain words | State |
|---|---|---|
| H6.1 | Enlarge the capture memory to 512 MB | **deliberately not done.** Buys 1.1 dB for a risk of a non-booting board, and the reason it was wanted has since evaporated |
| H6.2 | Record a full second on both channels | done — 32.8 M samples each, 97.8% of the available memory |
| H6.3 | Turn that into exactly 5000 trace points | done — **exactly 5000, at exactly 200.000 µs spacing** |
| H6.4 | Start recording *before* the trigger, so the filter is ready | done — and proved that without it the trace silently starts late |
| H6.5 | The whole chain end to end | done — **seven amplitude levels all within 1%** |

**H7 — does it survive things going wrong?**

| Step | In plain words | State |
|---|---|---|
| H7.1 | Repeat the whole sweep 20 times and see how much it varies | done — **20/20, amplitude repeats to 0.003%** |
| H7.2 | What if the trigger never comes? | done — fails cleanly after 8 s. **Fixing it also fixed a defect that left the board unusable** |
| H7.3 | What if the connection drops mid-recording? | done — all three ways of dropping it fail cleanly, board stays healthy |
| H7.4 | Are the outputs off after a crash? | **FAILED, then fixed.** They used to stay on. `close()` now switches them off |

### What is NOT done, and is not meant to be

- **H6.1** — the memory move. Rejected, and no longer needed.
- **H5.2 / H5.3** — superseded by how H6.5 was done.
- **U1–U12** — the list of things loopback physically cannot test. Enumerated in
  `07-phase1-loopback.md`, and the whole point of the Phase 2 planning session.

### What comes next

1. **The Santec laser driver.** This is the critical path and it is **blocked on
   Q22**: the TSL-770/775 command set, the port settings, and whether the
   wavelength table streams during the sweep or is dumped afterwards. Everything
   that does *not* need the command set is already written and tested
   (`wavelength.py`). **Do not guess the commands** — on this board a wrong
   command returns zero bytes exactly like a right one.
2. **The Phase 2 planning session**, with Kevin, before anything is physically
   connected. This is a hard gate.

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

## 2026-08-12 — Claude (Claude Code) — first hardware contact; H1 essentially done

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

### Repo structure hazard

The project lives at `.../rp-lockin-2tone/rp-lockin-2tone` — one level below the
directory of the same name. The **outer directory is an empty git repo with zero
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

## 2026-08-12 — Claude (Claude Code) — H3.3 done: noise floor measured, Q8 answered

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
